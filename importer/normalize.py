from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from hd2lib.storage import read_json, slugify, write_json


_BULLET = re.compile(r"\s*(?:&nbsp;)?&bull;(?:&nbsp;)?\s*|\s*•\s*", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_WIKI_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_PAGE = re.compile(r"#Page[ _](\d+)", re.IGNORECASE)
_INTEGER = re.compile(r"(?<![\w.])(\d[\d,]*)(?![\w.])")
_COOLDOWN = re.compile(r"^(\d+)s$")
_WEAPON_PREFIX = re.compile(r"^[A-Z0-9][A-Z0-9/+.\-]*\s+", re.IGNORECASE)


def _values(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [str(entry) for entry in values if entry not in (None, "")]


def _plain(value: str) -> str:
    value = html.unescape(value).replace("_", " ")
    value = _TAG.sub("", value)
    value = re.sub(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]", r"\1", value)
    return " ".join(value.split())


def _key(value: str) -> str:
    return _plain(value).replace("’", "'").casefold().rstrip("!")


def split_traits(value: Any) -> list[str]:
    result: list[str] = []
    for entry in _values(value):
        for part in _BULLET.split(entry):
            normalized = _plain(part).strip()
            if normalized and normalized not in result:
                result.append(normalized)
    return result


def parse_currency(value: Any, default_currency: str | None = None) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None
    if value.strip().casefold() in {"free", "none"}:
        return {"currency": default_currency or "none", "amount": 0}
    currency_markers = (
        ("Super Credit", "super_credits"),
        ("Common Sample", "common_samples"),
        ("Rare Sample", "rare_samples"),
        ("Super Sample", "super_samples"),
        ("Requisition", "requisition"),
        ("Medal", "medals"),
    )
    currency = next((name for marker, name in currency_markers if marker.casefold() in value.casefold()), default_currency)
    match = _INTEGER.search(_plain(value))
    if currency is None or match is None:
        return None
    return {"currency": currency, "amount": int(match.group(1).replace(",", ""))}


def _set_derived(item: dict[str, Any], key: str, value: Any, *sources: str) -> None:
    item.setdefault("facts", {})[key] = value
    item.setdefault("fact_provenance", {})[key] = {
        "kind": "derived",
        "from": list(sources),
    }


def _warbond_aliases(warbonds: list[dict[str, Any]]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for item in warbonds:
        aliases[_key(item["name"])] = item["id"]
        for source in item.get("provenance", []):
            page = source.get("page")
            if page:
                aliases[_key(str(page))] = item["id"]
    return aliases


def _source_warbond(value: Any, aliases: dict[str, str]) -> tuple[str | None, int | None]:
    if not isinstance(value, str):
        return None, None
    match = _WIKI_LINK.search(value)
    if match is None or "warbond" not in match.group(1).casefold():
        return None, None
    target = match.group(1)
    page_match = _PAGE.search(target) or re.search(r'title="Page (\d+)"', value, flags=re.IGNORECASE)
    target_without_fragment = target.split("#", 1)[0]
    warbond_id = aliases.get(_key(target_without_fragment))
    return warbond_id, int(page_match.group(1)) if page_match else None


def _damage_types(value: Any) -> list[str]:
    found: list[str] = []
    for entry in _values(value):
        for damage_type in re.findall(r"Damage ([A-Za-z]+) Icon", entry, flags=re.IGNORECASE):
            normalized = damage_type.casefold()
            if normalized not in found:
                found.append(normalized)
    return found


def _normalize_unlock_source(item: dict[str, Any], aliases: dict[str, str]) -> None:
    facts = item["facts"]
    warbond_id, page = _source_warbond(facts.get("source"), aliases)
    if warbond_id:
        _set_derived(item, "warbond_id", warbond_id, "facts.source")
    if page is not None:
        _set_derived(item, "warbond_page", page, "facts.source")
    raw_cost = facts.get("unlock_cost", facts.get("cost"))
    cost = parse_currency(raw_cost)
    if cost:
        _set_derived(item, "unlock_cost_normalized", cost, "facts.unlock_cost" if "unlock_cost" in facts else "facts.cost")


def _weapon_aliases(weapons: list[dict[str, Any]]) -> dict[str, str]:
    candidates: dict[str, list[str]] = {}
    for item in weapons:
        names = {item["name"], _WEAPON_PREFIX.sub("", item["name"], count=1)}
        for name in names:
            candidates.setdefault(_key(name), []).append(item["id"])
    return {name: ids[0] for name, ids in candidates.items() if len(set(ids)) == 1}


def _normalize_weapons(collections: dict[str, list[dict[str, Any]]], warbond_aliases: dict[str, str]) -> None:
    for collection in ("weapons", "grenades"):
        for item in collections.get(collection, []):
            facts = item["facts"]
            traits = split_traits(facts.get("weapon_traits"))
            if traits:
                _set_derived(item, "traits_normalized", traits, "facts.weapon_traits")
                penetration = next((level for level in ("Heavy", "Medium", "Light") if f"{level} Armor Penetrating" in traits), None)
                if penetration:
                    _set_derived(item, "armor_penetration", penetration.casefold(), "facts.weapon_traits")
                for trait, key in (("Explosive", "explosive"), ("Rounds Reload", "rounds_reload")):
                    if trait in traits:
                        _set_derived(item, key, True, "facts.weapon_traits")
            types = _damage_types(facts.get("damage"))
            if types:
                _set_derived(item, "damage_types", types, "facts.damage")
            if str(facts.get("capacity", "")).isdigit():
                _set_derived(item, "capacity_count", int(facts["capacity"]), "facts.capacity")
            _normalize_unlock_source(item, warbond_aliases)


def _normalize_attachments(collections: dict[str, list[dict[str, Any]]]) -> None:
    weapons = collections.get("weapons", [])
    aliases = _weapon_aliases(weapons)
    compatible_by_weapon: dict[str, list[str]] = {}
    for item in collections.get("attachments", []):
        facts = item["facts"]
        slot = slugify(str(facts.get("type", "")))
        if slot:
            _set_derived(item, "slot", slot, "facts.type")
        weapon_ids: list[str] = []
        for entry in _values(facts.get("available_on")):
            for name in entry.split(","):
                weapon_id = aliases.get(_key(name.strip()))
                if weapon_id and weapon_id not in weapon_ids:
                    weapon_ids.append(weapon_id)
        if weapon_ids:
            weapon_ids.sort()
            _set_derived(item, "compatible_weapon_ids", weapon_ids, "facts.available_on")
            for weapon_id in weapon_ids:
                compatible_by_weapon.setdefault(weapon_id, []).append(item["id"])
    weapon_index = {item["id"]: item for item in weapons}
    for weapon_id, attachment_ids in compatible_by_weapon.items():
        _set_derived(weapon_index[weapon_id], "compatible_attachment_ids", sorted(attachment_ids), "attachments.facts.available_on")


def _normalize_stratagems(collections: dict[str, list[dict[str, Any]]], warbond_aliases: dict[str, str]) -> None:
    weapons_by_name = {_key(item["name"]): item["id"] for item in collections.get("weapons", [])}
    equippable_types = {"backpack", "eagle", "emplacement", "orbital", "sentry", "support weapon", "vehicle"}
    for item in collections.get("stratagems", []):
        facts = item["facts"]
        stratagem_type = str(facts.get("stratagem_type", "")).casefold()
        _set_derived(item, "player_equippable", stratagem_type in equippable_types, "facts.stratagem_type")
        cooldown = _COOLDOWN.fullmatch(str(facts.get("base_cooldown", "")))
        if cooldown:
            _set_derived(item, "cooldown_seconds", int(cooldown.group(1)), "facts.base_cooldown")
        traits = split_traits(facts.get("traits"))
        if traits:
            _set_derived(item, "traits_normalized", traits, "facts.traits")
            if "Backpack" in traits or stratagem_type == "backpack":
                _set_derived(item, "occupies_backpack_slot", True, "facts.traits", "facts.stratagem_type")
            if "Anti-Tank" in traits:
                _set_derived(item, "anti_tank", True, "facts.traits")
            penetration = next((level for level in ("Heavy", "Medium", "Light") if f"{level} Armor Penetrating" in traits), None)
            if penetration:
                _set_derived(item, "armor_penetration", penetration.casefold(), "facts.traits")
            if "Explosive" in traits:
                _set_derived(item, "explosive", True, "facts.traits")
        if stratagem_type == "support weapon":
            weapon_id = weapons_by_name.get(_key(item["name"]))
            if weapon_id:
                _set_derived(item, "support_weapon_id", weapon_id, "name", "weapons.name")
        _normalize_unlock_source(item, warbond_aliases)


def _normalize_armor(collections: dict[str, list[dict[str, Any]]], warbond_aliases: dict[str, str]) -> None:
    passive_ids = {_key(item["name"]): item["id"] for item in collections.get("armor_passives", [])}
    for item in collections.get("armor", []):
        facts = item["facts"]
        armor_type = str(facts.get("type", ""))
        if armor_type.casefold() in {"light", "medium", "heavy"}:
            _set_derived(item, "equipment_slot", "body_armor", "facts.type")
            _set_derived(item, "armor_class", armor_type.casefold(), "facts.type")
            passive_name = _plain(str(facts.get("passive", "")))
            if _key(passive_name) == "standard issue":
                _set_derived(item, "passive_id", None, "facts.passive")
            elif _key(passive_name) in passive_ids:
                _set_derived(item, "passive_id", passive_ids[_key(passive_name)], "facts.passive")
            for raw_key, normalized_key in (("armor", "armor_rating"), ("speed", "speed_rating"), ("stam_regen", "stamina_regeneration")):
                if str(facts.get(raw_key, "")).isdigit():
                    _set_derived(item, normalized_key, int(facts[raw_key]), f"facts.{raw_key}")
        elif armor_type.casefold() == "helmet":
            _set_derived(item, "equipment_slot", "helmet", "facts.type")
        elif armor_type.casefold() == "cape":
            _set_derived(item, "equipment_slot", "cape", "facts.type")
        _normalize_unlock_source(item, warbond_aliases)


def _normalize_ship_modules(collections: dict[str, list[dict[str, Any]]]) -> None:
    modules = collections.get("ship_modules", [])
    module_ids = {_key(item["name"]): item["id"] for item in modules}
    for item in modules:
        facts = item["facts"]
        _set_derived(item, "path_id", slugify(str(facts.get("section", ""))), "facts.section")
        prior = str(facts.get("prior", ""))
        if prior.casefold() == "none":
            _set_derived(item, "prerequisite_module_id", None, "facts.prior")
        elif _key(prior) in module_ids:
            _set_derived(item, "prerequisite_module_id", module_ids[_key(prior)], "facts.prior")
        costs = [parsed for key in ("cost1", "cost2", "cost3", "cost4", "cost5") if (parsed := parse_currency(facts.get(key)))]
        if costs:
            _set_derived(item, "costs_normalized", costs, "facts.cost1", "facts.cost2", "facts.cost3", "facts.cost4", "facts.cost5")


def _normalize_warbonds(collections: dict[str, list[dict[str, Any]]]) -> None:
    for item in collections.get("warbonds", []):
        facts = item["facts"]
        for raw_key, normalized_key, default in (
            ("cost", "purchase_cost", "super_credits"),
            ("all_pages", "total_reward_medal_cost", "medals"),
            ("credit_claim", "included_super_credits", "super_credits"),
        ):
            value = parse_currency(facts.get(raw_key), default)
            if value:
                _set_derived(item, normalized_key, value, f"facts.{raw_key}")


def _normalize_factions(collections: dict[str, list[dict[str, Any]]]) -> None:
    enemy_factions = {"automatons": "automatons", "terminids": "terminids", "illuminate": "illuminate"}
    mission_factions = {"automaton": "automatons", "terminid": "terminids", "illuminate": "illuminate", "any": "any"}
    for item in collections.get("enemies", []):
        faction = item["facts"].get("faction")
        if isinstance(faction, str) and faction.casefold() in enemy_factions:
            _set_derived(item, "faction_id", enemy_factions[faction.casefold()], "facts.faction")
    for item in collections.get("mission_types", []):
        faction = item["facts"].get("faction")
        if isinstance(faction, str) and faction.casefold() in mission_factions:
            _set_derived(item, "faction_id", mission_factions[faction.casefold()], "facts.faction")


def normalize_collections(collections: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """Add only deterministic fields derived from imported structured values."""
    aliases = _warbond_aliases(collections.get("warbonds", []))
    _normalize_weapons(collections, aliases)
    _normalize_attachments(collections)
    _normalize_stratagems(collections, aliases)
    _normalize_armor(collections, aliases)
    _normalize_ship_modules(collections)
    _normalize_warbonds(collections)
    _normalize_factions(collections)
    return collections


def normalize_directory(directory: Path, catalog_version: str | None = None) -> None:
    from hd2lib.constants import CATALOG_FILES
    from hd2lib.catalog import update_manifest_hashes

    documents = {name: read_json(directory / filename) for name, filename in CATALOG_FILES.items()}
    collections = {name: document["items"] for name, document in documents.items()}
    normalize_collections(collections)
    for name, filename in CATALOG_FILES.items():
        if catalog_version:
            documents[name]["catalog_version"] = catalog_version
        write_json(directory / filename, documents[name])
    manifest_path = directory / "catalog_manifest.json"
    manifest = read_json(manifest_path)
    if catalog_version:
        manifest["catalog_version"] = catalog_version
    manifest["normalizer_version"] = "1.0.0"
    write_json(manifest_path, manifest)
    update_manifest_hashes(directory)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Deterministically normalize an imported HD2 catalog")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--catalog-version")
    args = parser.parse_args()
    normalize_directory(args.directory, args.catalog_version)
