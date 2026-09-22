from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .catalog import catalog_hash, catalog_index
from .constants import SCHEMA_VERSION
from .data import user_data_paths
from .loadout import validate_loadout_schema
from .profile import ProfileError, effective_preferences, validate_profile
from .storage import fingerprint, read_json, slugify, utc_now, write_json


WARNING = "GENERATED FILE — DO NOT EDIT\nSource data is stored in the JSON profile/catalog files."


def _inventory_snapshot(character: dict[str, Any], catalog: dict[str, Any], preferences: dict[str, Any]) -> dict[str, Any]:
    index = catalog_index(catalog)
    snapshot: dict[str, list[dict[str, Any]]] = {}
    item_prefs = preferences.get("item_preferences", {})
    for category, entries in character.get("inventory", {}).items():
        values = []
        for item_id, state in sorted(entries.items(), key=lambda value: index.get(value[0], {}).get("name", value[0])):
            catalog_item = index.get(item_id, {})
            value = {
                "id": item_id,
                "name": catalog_item.get("name", item_id),
                "status": state.get("status", "unknown"),
                "preference": item_prefs.get(item_id, "neutral"),
                "facts": catalog_item.get("facts", {}),
            }
            if "level" in state:
                value["level"] = state["level"]
            values.append(value)
        snapshot[category] = values
    return snapshot


def _load_linked_loadouts(profile: dict[str, Any], root: Path | None = None) -> list[dict[str, Any]]:
    root = user_data_paths().loadouts if root is None else root
    result = list(profile.get("saved_loadouts", []))
    for relative in profile.get("saved_loadout_files", []):
        path = root / relative
        if path.exists():
            result.append(read_json(path))
    return result


def build_context(profile: dict[str, Any], character_id: str, catalog: dict[str, Any]) -> dict[str, Any]:
    if character_id not in profile["characters"]:
        raise ValueError(f"Unknown character {character_id!r}")
    character = profile["characters"][character_id]
    preferences = effective_preferences(profile, character_id)
    profile_hash = fingerprint(profile)
    current_catalog_hash = catalog_hash(catalog)
    generated_at = utc_now()
    observations = [
        observation for observation in profile.get("gameplay_observations", [])
        if observation.get("character") in (None, character_id)
    ]
    return {
        "generated_file": {
            "warning": WARNING,
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated_at,
            "profile_hash": profile_hash,
            "catalog_hash": current_catalog_hash,
        },
        "catalog": {
            "catalog_version": catalog["manifest"].get("catalog_version"),
            "game_version": catalog["manifest"].get("game_version"),
        },
        "player": profile["player"],
        "character_id": character_id,
        "character": {
            "display_name": character.get("display_name", character_id),
            "platform": character.get("platform"),
            "level": character.get("level"),
            "resources": character.get("resources", {}),
        },
        "preferences": preferences,
        "inventory": _inventory_snapshot(character, catalog, preferences),
        "gameplay_observations": observations,
        "saved_loadouts": _load_linked_loadouts(profile),
        "progression_notes": profile.get("progression_notes", []),
    }


def _state_table(items: list[dict[str, Any]]) -> str:
    if not items:
        return "_No recorded items; treat availability as unknown._\n"
    lines = ["| Item | Unlock | Preference |", "|---|---|---|"]
    lines.extend(
        f"| {item['name']} (`{item['id']}`)"
        + (f" — level {item['level']}" if "level" in item else "")
        + f" | {item['status']} | {item['preference']} |"
        for item in items
    )
    return "\n".join(lines) + "\n"


def context_markdown(context: dict[str, Any]) -> str:
    metadata = context["generated_file"]
    player = context["player"]
    character = context["character"]
    inventory = context["inventory"]
    lines = [
        "<!-- GENERATED FILE — DO NOT EDIT. Source data is stored in the JSON profile/catalog files. -->",
        "# Helldivers 2 Player Context", "",
        "> **GENERATED FILE — DO NOT EDIT**  ",
        "> Source data is stored in the JSON profile/catalog files.", "",
        f"- Player: {player['display_name']} (`{player['id']}`)",
        f"- Character: {character['display_name']} (`{context['character_id']}`)",
        f"- Platform: {character.get('platform', 'unknown')}", f"- Level: {character.get('level', 'unknown')}",
        f"- Catalog version: {context['catalog'].get('catalog_version')}",
        f"- Game version: {context['catalog'].get('game_version')}", f"- Generated: {metadata['generated_at']}",
        f"- profile_hash: `{metadata['profile_hash']}`", f"- catalog_hash: `{metadata['catalog_hash']}`", "",
        "## How to interpret this document", "",
        "`unlocked` means immediately usable, `locked` means known unavailable, and `unknown` means not yet recorded. Player preference is independent of unlock state. Personal gameplay observations are context-scoped evidence, not universal rules. Community observations, when present, are dated third-party evidence rather than game facts.", "",
        "**When recommending an immediately usable loadout, do not equip locked or unknown items. Locked items may be suggested as future progression targets. Do not treat a personal negative experience as a universal game rule.**", "",
        "## Resources", "",
    ]
    resources = character.get("resources", {})
    if resources:
        resource_labels = {
            "medals": "Medals", "requisition": "Requisition slips",
            "super_credits": "Super credits", "common_samples": "Common samples",
            "rare_samples": "Rare samples", "super_samples": "Super samples",
        }
        lines.extend(
            f"- {resource_labels.get(key, key.replace('_', ' ').title())}: {value}"
            for key, value in resources.items()
        )
    else:
        lines.append("_No resource balances recorded._")
    lines.extend([
        "", "## Preferences", "", "```json", json.dumps(context["preferences"], indent=2, ensure_ascii=False), "```", "",
        "## Warbonds", "", _state_table(inventory.get("warbonds", [])),
        "## Weapons", "", "### Primary", "", _state_table(inventory.get("primary_weapons", [])),
        "### Secondary", "", _state_table(inventory.get("secondary_weapons", [])),
        "### Support", "", _state_table(inventory.get("support_weapons", [])),
        "## Weapon attachments / progression", "", _state_table(inventory.get("weapon_attachments", [])),
        "## Grenades", "", _state_table(inventory.get("grenades", [])),
        "## Armor / passives", "", "### Armor", "", _state_table(inventory.get("armor", [])),
        "### Passives", "", _state_table(inventory.get("armor_passives", [])),
        "## Boosters", "", _state_table(inventory.get("boosters", [])),
        "## Stratagems", "",
    ])
    stratagems = inventory.get("stratagems", [])
    groups = (("Support", "support_weapon"), ("Backpack", "backpack"), ("Eagle", "eagle"), ("Orbital", "orbital"), ("Sentry / Emplacement", "sentry_emplacement"), ("Vehicle", "vehicle"), ("Other", "other"))
    used: set[str] = set()
    for label, group in groups:
        selected = []
        for item in stratagems:
            category = item.get("facts", {}).get("category", "other")
            match = category == group or (group == "sentry_emplacement" and category in {"sentry", "emplacement"})
            if match:
                selected.append(item); used.add(item["id"])
        if group == "other":
            selected.extend(item for item in stratagems if item["id"] not in used)
        lines.extend([f"### {label}", "", _state_table(selected)])
    lines.extend(["## Ship modules", "", _state_table(inventory.get("ship_modules", [])), "## Gameplay observations", ""])
    if context["gameplay_observations"]:
        for obs in context["gameplay_observations"]:
            lines.append(f"- {obs.get('date', 'undated')} — `{obs.get('item_id', 'general')}`; faction={obs.get('faction') or 'any'}; mission={obs.get('mission_type') or 'any'}; difficulty={obs.get('difficulty') or 'any'}; rating={obs.get('rating', 'unrated')}; confidence={obs.get('confidence', 'unknown')}: {obs.get('notes', '')}")
    else:
        lines.append("_No gameplay observations recorded._")
    lines.extend(["", "## Saved loadouts", ""])
    if context["saved_loadouts"]:
        for loadout in context["saved_loadouts"]:
            lines.append(f"- **{loadout.get('name', loadout.get('id', 'Unnamed'))}**: {', '.join(loadout.get('stratagems', []))}. {loadout.get('notes', '')}")
    else:
        lines.append("_No saved loadouts recorded._")
    lines.extend(["", "## Current progression notes", ""])
    notes = context["progression_notes"]
    lines.extend(f"- {note}" for note in notes) if notes else lines.append("_No progression notes recorded._")
    return "\n".join(lines).rstrip() + "\n"


def export_context(profile: dict[str, Any], character_id: str, catalog: dict[str, Any], output_root: Path | None = None) -> tuple[Path, Path]:
    errors = validate_profile(profile, catalog)
    if errors:
        raise ProfileError("Export rejected; no files created:\n- " + "\n- ".join(errors))
    output_root = user_data_paths().initialize().generated if output_root is None else output_root
    context = build_context(profile, character_id, catalog)
    output = output_root / profile["player"]["id"]
    json_path = output / f"{character_id}-context.json"
    markdown_path = output / f"{character_id}-context.md"
    write_json(json_path, context)
    markdown_path.write_text(context_markdown(context), encoding="utf-8", newline="\n")
    return json_path, markdown_path


def validate_generated(path: Path, profile: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    if path.suffix.casefold() == ".json":
        metadata = read_json(path).get("generated_file", {})
    else:
        text = path.read_text(encoding="utf-8")
        metadata = {}
        for key in ("profile_hash", "catalog_hash"):
            marker = f"- {key}: `"
            for line in text.splitlines():
                if line.startswith(marker):
                    metadata[key] = line[len(marker):].rstrip("`")
    expected = {"profile_hash": fingerprint(profile), "catalog_hash": catalog_hash(catalog)}
    stale_reasons = [key for key, value in expected.items() if metadata.get(key) != value]
    return {"valid": not stale_reasons, "stale": bool(stale_reasons), "stale_reasons": stale_reasons, "expected": expected, "found": metadata}
