from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .catalog import catalog_index
from .constants import INVENTORY_TO_CATALOG, PREFERENCE_STATES, SCHEMA_VERSION, UNLOCK_STATES
from .data import UserDataPaths, user_data_paths
from .storage import read_json, slugify, utc_now, write_json


class ProfileError(ValueError):
    pass


def empty_inventory() -> dict[str, dict[str, dict[str, str]]]:
    return {key: {} for key in INVENTORY_TO_CATALOG}


def new_profile(player_id: str, display_name: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "profile_updated_at": utc_now(),
        "player": {"id": slugify(player_id), "display_name": display_name},
        "preferences": {"general": {}, "item_preferences": {}},
        "characters": {},
        "gameplay_observations": [],
        "saved_loadouts": [],
        "progression_notes": [],
    }


def add_character(profile: dict[str, Any], character_id: str, platform: str, level: int, display_name: str | None = None) -> None:
    character_id = slugify(character_id)
    if not character_id:
        raise ProfileError("Character id cannot be empty")
    if character_id in profile["characters"]:
        raise ProfileError(f"Character already exists: {character_id}")
    profile["characters"][character_id] = {
        "display_name": display_name or character_id,
        "platform": platform,
        "level": level,
        "inventory": empty_inventory(),
        "preference_overrides": {"general": {}, "item_preferences": {}},
        "resources": {},
        "onboarding": {"completed_sections": [], "skipped_sections": []},
    }


def profile_path(player_id: str, directory: Path | None = None) -> Path:
    directory = user_data_paths().initialize().profiles if directory is None else directory
    return directory / f"{slugify(player_id)}.json"


def find_profile(player_id: str, directory: Path | None = None) -> Path:
    directory = user_data_paths().initialize().profiles if directory is None else directory
    direct = profile_path(player_id, directory)
    if direct.exists():
        return direct
    for path in directory.glob("*.json"):
        try:
            if read_json(path).get("player", {}).get("id") == player_id:
                return path
        except (ValueError, OSError):
            continue
    raise ProfileError(f"No profile found for player {player_id!r}")


def profile_summaries(directory: Path | None = None) -> list[dict[str, Any]]:
    """Return readable profile identities, ignoring unrelated/broken JSON files."""
    directory = user_data_paths().initialize().profiles if directory is None else directory
    result: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            player = read_json(path).get("player", {})
            if player.get("id") and player.get("display_name"):
                result.append({"player_id": player["id"], "display_name": player["display_name"], "path": path})
        except (OSError, ValueError):
            continue
    return sorted(result, key=lambda value: value["display_name"].casefold())


def load_profile(player_id: str, catalog: dict[str, Any], paths: UserDataPaths | None = None) -> tuple[Path, dict[str, Any]]:
    """Load, migrate, and validate a persistent profile for any frontend."""
    from .migrations import migrate_profile_file

    paths = (paths or user_data_paths()).initialize()
    path = find_profile(player_id, paths.profiles)
    migrate_profile_file(path, catalog, paths)
    profile = read_json(path)
    errors = validate_profile(profile, catalog)
    if errors:
        raise ProfileError("Profile is invalid:\n- " + "\n- ".join(errors))
    return path, profile


def effective_preferences(profile: dict[str, Any], character_id: str) -> dict[str, Any]:
    character = profile["characters"][character_id]
    base = copy.deepcopy(profile.get("preferences", {}))
    overrides = character.get("preference_overrides", {})
    base.setdefault("general", {}).update(overrides.get("general", {}))
    base.setdefault("item_preferences", {}).update(overrides.get("item_preferences", {}))
    return base


def inventory_item_ineligibility(category: str, item: dict[str, Any], collection: str | None = None) -> str | None:
    """Return why a catalog item cannot be recorded in an inventory category."""
    item_id = item.get("id", "item")
    collection = collection or item.get("_collection")
    expected_collection = INVENTORY_TO_CATALOG[category]
    if collection != expected_collection:
        return f"{item_id!r} does not belong in {category}"
    facts = item.get("facts", {})
    expected_weapon_category = {
        "primary_weapons": "primary",
        "secondary_weapons": "secondary",
        "support_weapons": "support_weapon",
    }.get(category)
    if expected_weapon_category and facts.get("category") != expected_weapon_category:
        return f"{item_id!r} has the wrong weapon category for {category}"
    if category == "armor" and facts.get("equipment_slot") != "body_armor":
        return f"{item_id!r} is not body armor"
    if category == "stratagems" and facts.get("player_equippable") is not True:
        return f"{item_id!r} is not a player-equippable stratagem"
    return None


def set_inventory_item_status(
    profile: dict[str, Any], character_id: str, category: str, item_id: str,
    status: str, catalog: dict[str, Any],
) -> None:
    """Set a canonical three-state inventory value after catalog validation."""
    if status not in UNLOCK_STATES:
        raise ProfileError(f"Unknown inventory status {status!r}")
    if category not in INVENTORY_TO_CATALOG:
        raise ProfileError(f"Unknown inventory category {category!r}")
    item = catalog_index(catalog).get(item_id)
    if item is None:
        raise ProfileError(f"Unknown catalog item {item_id!r}")
    reason = inventory_item_ineligibility(category, item)
    if reason:
        raise ProfileError(reason)
    entry = profile["characters"][character_id]["inventory"].setdefault(category, {}).setdefault(item_id, {})
    entry["status"] = status


def set_inventory_items_status(
    profile: dict[str, Any], character_id: str, category: str,
    item_ids: list[str], status: str, catalog: dict[str, Any], *, only_unknown: bool = False,
) -> int:
    """Set inventory state for an explicit caller-provided scope."""
    inventory = profile["characters"][character_id]["inventory"].setdefault(category, {})
    targets = [
        item_id for item_id in dict.fromkeys(item_ids)
        if inventory.get(item_id, {}).get("status", "unknown") != status
        and (not only_unknown or inventory.get(item_id, {}).get("status", "unknown") == "unknown")
    ]
    for item_id in targets:
        set_inventory_item_status(profile, character_id, category, item_id, status, catalog)
    return len(targets)


def set_weapon_level(
    profile: dict[str, Any], character_id: str, category: str,
    item_id: str, level: int | None, catalog: dict[str, Any],
) -> None:
    """Store optional player-entered weapon progression metadata."""
    if category not in {"primary_weapons", "secondary_weapons", "support_weapons"}:
        raise ProfileError("Progression level is only available for weapons")
    if level is not None and (not isinstance(level, int) or isinstance(level, bool) or level < 0):
        raise ProfileError("Weapon level must be a non-negative whole number")
    current = profile["characters"][character_id]["inventory"].setdefault(category, {}).get(item_id, {}).get("status", "unknown")
    set_inventory_item_status(profile, character_id, category, item_id, current, catalog)
    entry = profile["characters"][character_id]["inventory"][category][item_id]
    if level is None:
        entry.pop("level", None)
    else:
        entry["level"] = level


def set_character_resources(
    profile: dict[str, Any], character_id: str, resources: dict[str, int | None],
) -> None:
    """Update recorded resources while preserving blanks and unknown future fields."""
    if character_id not in profile.get("characters", {}):
        raise ProfileError(f"Unknown character {character_id!r}")
    current = profile["characters"][character_id].setdefault("resources", {})
    if not isinstance(current, dict):
        raise ProfileError("Character resources must be an object")
    for key, value in resources.items():
        if value is None:
            current.pop(key, None)
            continue
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ProfileError(f"Resource {key!r} must be a non-negative whole number or blank")
        current[key] = value


def validate_profile(profile: dict[str, Any], catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if profile.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"Unsupported profile schema_version: {profile.get('schema_version')!r}")
    player = profile.get("player")
    if not isinstance(player, dict) or not player.get("id") or not player.get("display_name"):
        errors.append("player.id and player.display_name are required")
    characters = profile.get("characters")
    if not isinstance(characters, dict) or not characters:
        errors.append("At least one character is required")
        return errors
    index = catalog_index(catalog)
    for character_id, character in characters.items():
        level = character.get("level")
        if not isinstance(level, int) or level < 0:
            errors.append(f"characters.{character_id}.level must be a non-negative integer")
        inventory = character.get("inventory", {})
        for category in INVENTORY_TO_CATALOG:
            entries = inventory.get(category, {})
            if not isinstance(entries, dict):
                errors.append(f"characters.{character_id}.inventory.{category} must be an object")
                continue
            for item_id, state in entries.items():
                if item_id not in index:
                    errors.append(f"characters.{character_id}: invalid item id {item_id!r}")
                    continue
                reason = inventory_item_ineligibility(category, index[item_id])
                if reason:
                    errors.append(f"characters.{character_id}: {reason}")
                status = state.get("status") if isinstance(state, dict) else None
                if status not in UNLOCK_STATES:
                    errors.append(f"characters.{character_id}.{item_id}: invalid status {status!r}")
                if isinstance(state, dict) and "level" in state:
                    level_value = state["level"]
                    if category not in {"primary_weapons", "secondary_weapons", "support_weapons"}:
                        errors.append(f"characters.{character_id}.{item_id}: level is only valid for weapons")
                    elif not isinstance(level_value, int) or isinstance(level_value, bool) or level_value < 0:
                        errors.append(f"characters.{character_id}.{item_id}: level must be a non-negative integer")
        prefs = effective_preferences(profile, character_id).get("item_preferences", {})
        for item_id, preference in prefs.items():
            if item_id not in index:
                errors.append(f"characters.{character_id}: preference has invalid item id {item_id!r}")
            if preference not in PREFERENCE_STATES:
                errors.append(f"characters.{character_id}.{item_id}: invalid preference {preference!r}")
    for number, observation in enumerate(profile.get("gameplay_observations", []), 1):
        if "character" not in observation:
            errors.append(f"observation {number}: character is required (use null for unscoped)")
        elif observation.get("character") is not None and observation.get("character") not in characters:
            errors.append(f"observation {number}: unknown character")
        if observation.get("item_id") and observation["item_id"] not in index:
            errors.append(f"observation {number}: invalid item id {observation['item_id']!r}")
    return errors


def save_profile(path: Path, profile: dict[str, Any]) -> None:
    profile["profile_updated_at"] = utc_now()
    write_json(path, profile)


def import_profile(input_path: Path, output_directory: Path, catalog: dict[str, Any], overwrite: bool = False) -> Path:
    candidate = read_json(input_path)
    errors = validate_profile(candidate, catalog)
    if errors:
        raise ProfileError("Import rejected; no profile modified:\n- " + "\n- ".join(errors))
    output = profile_path(candidate["player"]["id"], output_directory)
    if output.exists() and not overwrite:
        raise ProfileError(f"Profile exists: {output}. Use --overwrite to replace it.")
    save_profile(output, candidate)
    return output
