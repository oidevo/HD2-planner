from __future__ import annotations

from typing import Any

from .catalog import catalog_index


SLOTS = ("primary", "secondary", "grenade", "armor", "booster")

SLOT_RULES = {
    "primary": ("weapons", "category", "primary"),
    "secondary": ("weapons", "category", "secondary"),
    "grenade": ("grenades", None, None),
    "armor": ("armor", "equipment_slot", "body_armor"),
    "booster": ("boosters", None, None),
}


def loadout_item_ids(loadout: dict[str, Any]) -> list[str]:
    item_ids = [loadout.get(slot) for slot in SLOTS]
    item_ids.extend(loadout.get("stratagems", []))
    return [item_id for item_id in item_ids if item_id]


def validate_loadout_schema(loadout: dict[str, Any], catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not loadout.get("id") or not loadout.get("name"):
        errors.append("loadout.id and loadout.name are required")
    stratagems = loadout.get("stratagems", [])
    if not isinstance(stratagems, list) or len(stratagems) > 4:
        errors.append("stratagems must be an array of at most four item ids")
    elif len(stratagems) != len(set(stratagems)):
        errors.append("stratagems must not contain duplicate item ids")
    index = catalog_index(catalog)
    for slot, (collection, fact_key, fact_value) in SLOT_RULES.items():
        item_id = loadout.get(slot)
        if not item_id or item_id not in index:
            continue
        item = index[item_id]
        if item["_collection"] != collection or (fact_key and item.get("facts", {}).get(fact_key) != fact_value):
            errors.append(f"{item_id!r} is not valid for the {slot} slot")
    for item_id in stratagems if isinstance(stratagems, list) else []:
        if item_id in index:
            item = index[item_id]
            if item["_collection"] != "stratagems" or item.get("facts", {}).get("player_equippable") is not True:
                errors.append(f"{item_id!r} is not a player-equippable stratagem")
    for item_id in loadout_item_ids(loadout):
        if item_id not in index:
            errors.append(f"invalid item id {item_id!r}")
    return errors


def validate_for_character(loadout: dict[str, Any], character: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    errors = validate_loadout_schema(loadout, catalog)
    if errors:
        return {"errors": errors, "usable": [], "missing": [], "unknown": []}
    index = catalog_index(catalog)
    statuses = {
        item_id: state.get("status", "unknown")
        for entries in character.get("inventory", {}).values()
        for item_id, state in entries.items()
    }
    result: dict[str, list[dict[str, str]] | list[str]] = {"errors": [], "usable": [], "missing": [], "unknown": []}
    for item_id in loadout_item_ids(loadout):
        entry = {"id": item_id, "name": index[item_id]["name"]}
        status = statuses.get(item_id, "unknown")
        if status == "unlocked":
            result["usable"].append(entry)
        elif status == "locked":
            result["missing"].append(entry)
        else:
            result["unknown"].append(entry)
    result["total"] = len(loadout_item_ids(loadout))
    return result
