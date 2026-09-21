from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .catalog import catalog_index
from .constants import INVENTORY_TO_CATALOG, PREFERENCE_STATES, PROFILES_DIR, SCHEMA_VERSION, UNLOCK_STATES
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


def profile_path(player_id: str, directory: Path = PROFILES_DIR) -> Path:
    return directory / f"{slugify(player_id)}.json"


def find_profile(player_id: str, directory: Path = PROFILES_DIR) -> Path:
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


def effective_preferences(profile: dict[str, Any], character_id: str) -> dict[str, Any]:
    character = profile["characters"][character_id]
    base = copy.deepcopy(profile.get("preferences", {}))
    overrides = character.get("preference_overrides", {})
    base.setdefault("general", {}).update(overrides.get("general", {}))
    base.setdefault("item_preferences", {}).update(overrides.get("item_preferences", {}))
    return base


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
                expected = INVENTORY_TO_CATALOG[category]
                if index[item_id]["_collection"] != expected:
                    errors.append(f"characters.{character_id}: {item_id!r} does not belong in {category}")
                facts = index[item_id].get("facts", {})
                expected_weapon_category = {
                    "primary_weapons": "primary",
                    "secondary_weapons": "secondary",
                    "support_weapons": "support_weapon",
                }.get(category)
                if expected_weapon_category and facts.get("category") != expected_weapon_category:
                    errors.append(f"characters.{character_id}: {item_id!r} has the wrong weapon category for {category}")
                if category == "armor" and facts.get("equipment_slot") != "body_armor":
                    errors.append(f"characters.{character_id}: {item_id!r} is not body armor")
                if category == "stratagems" and facts.get("player_equippable") is not True:
                    errors.append(f"characters.{character_id}: {item_id!r} is not a player-equippable stratagem")
                status = state.get("status") if isinstance(state, dict) else None
                if status not in UNLOCK_STATES:
                    errors.append(f"characters.{character_id}.{item_id}: invalid status {status!r}")
        prefs = effective_preferences(profile, character_id).get("item_preferences", {})
        for item_id, preference in prefs.items():
            if item_id not in index:
                errors.append(f"characters.{character_id}: preference has invalid item id {item_id!r}")
            if preference not in PREFERENCE_STATES:
                errors.append(f"characters.{character_id}.{item_id}: invalid preference {preference!r}")
    for number, observation in enumerate(profile.get("gameplay_observations", []), 1):
        if observation.get("character") not in characters:
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
