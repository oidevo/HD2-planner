from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .constants import DISPLAY_CATEGORIES, INVENTORY_TO_CATALOG
from .profile import add_character, inventory_item_ineligibility, new_profile, save_profile, set_inventory_item_status


Ask = Callable[[str], str]
Tell = Callable[[str], None]


def _ask_int(ask: Ask, prompt: str, default: int = 0) -> int:
    while True:
        raw = ask(prompt).strip()
        if not raw:
            return default
        try:
            value = int(raw)
            if value >= 0:
                return value
        except ValueError:
            pass
        print("Enter a non-negative whole number.")


def setup_profile(catalog: dict[str, Any], output_directory: Path, ask: Ask = input, tell: Tell = print) -> Path:
    tell("Helldivers 2 Planner setup. You can stop between inventory sections and resume later.")
    display_name = ask("Player display name: ").strip()
    player_id = ask("Portable player id (blank to derive from name): ").strip() or display_name
    profile = new_profile(player_id, display_name)
    path = output_directory / f"{profile['player']['id']}.json"
    while True:
        character_id = ask("Character id (for example main, pc, xbox): ").strip()
        platform = ask("Platform: ").strip() or "unknown"
        level = _ask_int(ask, "Level (blank for 0): ")
        add_character(profile, character_id, platform, level)
        save_profile(path, profile)
        another = ask("Add another independent character? [y/N]: ").strip().casefold()
        if another != "y":
            break
    tell(f"Saved {path}")
    for character_id in profile["characters"]:
        tell(f"\nInventory for {character_id}. Each completed or skipped section is saved immediately.")
        for category in INVENTORY_TO_CATALOG:
            action = ask(f"Review {category.replace('_', ' ')} now? [Y/n/quit]: ").strip().casefold()
            if action == "quit" or action == "q":
                tell(f"Stopped safely. Resume with: python3.12 hd2.py inventory review --player {profile['player']['id']} --character {character_id} --category {category}")
                return path
            if action == "n":
                profile["characters"][character_id]["onboarding"]["skipped_sections"].append(category)
            else:
                completed = review_inventory(profile, character_id, category, catalog, path, ask, tell)
                if not completed:
                    tell(f"Stopped safely. Resume with: python3.12 hd2.py inventory review --player {profile['player']['id']} --character {character_id} --category {category}")
                    return path
            save_profile(path, profile)
    tell("Setup complete. Generate context with: " + f"python3.12 hd2.py export-context --player {profile['player']['id']} --character {next(iter(profile['characters']))}")
    return path


def items_for_inventory_category(catalog: dict[str, Any], category: str, warbond: str | None = None) -> list[dict[str, Any]]:
    collection = INVENTORY_TO_CATALOG[category]
    items = catalog["collections"][collection]
    items = [item for item in items if not inventory_item_ineligibility(category, item, collection)]
    if warbond:
        items = [item for item in items if item.get("facts", {}).get("warbond_id") == warbond]
    return sorted(items, key=lambda item: item["name"])


def review_inventory(profile: dict[str, Any], character_id: str, category: str, catalog: dict[str, Any], profile_path: Path, ask: Ask = input, tell: Tell = print, warbond: str | None = None) -> bool:
    category = DISPLAY_CATEGORIES.get(category, category)
    if category not in INVENTORY_TO_CATALOG:
        raise ValueError(f"Unknown inventory category {category!r}")
    character = profile["characters"][character_id]
    inventory = character["inventory"].setdefault(category, {})
    preferences = character["preference_overrides"].setdefault("item_preferences", {})
    items = items_for_inventory_category(catalog, category, warbond)
    if not items:
        tell("No catalog items match this section.")
        return True
    tell("Commands: u=unlocked, l=locked, ?=unknown, f=favorite+unlocked, d=dislike (keeps unlock state), Enter=keep, s=skip rest, q=stop")
    for item in items:
        prior = inventory.get(item["id"], {}).get("status", "unknown")
        pref = preferences.get(item["id"], "neutral")
        command = ask(f"{item['name']} [{prior}; {pref}]: ").strip().casefold()
        if command == "q":
            save_profile(profile_path, profile)
            tell("Stopped safely; current answers were saved.")
            return False
        if command == "s":
            break
        if command in {"u", "l", "?", "f"}:
            status = {"u": "unlocked", "l": "locked", "?": "unknown", "f": "unlocked"}[command]
            set_inventory_item_status(profile, character_id, category, item["id"], status, catalog)
        if command == "f":
            preferences[item["id"]] = "favorite"
        elif command == "d":
            preferences[item["id"]] = "dislike"
        save_profile(profile_path, profile)
    completed = character["onboarding"].setdefault("completed_sections", [])
    if category not in completed:
        completed.append(category)
    skipped = character["onboarding"].setdefault("skipped_sections", [])
    if category in skipped:
        skipped.remove(category)
    save_profile(profile_path, profile)
    return True
