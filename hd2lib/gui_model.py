"""Headless application service used by the Tk GUI.

The service deliberately owns no alternate persistence format.  It loads,
validates, and atomically saves the same profile dictionaries used by the CLI.
Keeping filtering and mutations here makes the important GUI behaviour
testable without a display server.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable

from .catalog import catalog_index, load_catalog
from .constants import INVENTORY_TO_CATALOG, PREFERENCE_STATES, UNLOCK_STATES
from .data import UserDataPaths, user_data_paths
from .exporter import export_context
from .loadout import validate_for_character
from .onboarding import items_for_inventory_category
from .profile import (
    ProfileError,
    add_character,
    load_profile,
    new_profile,
    profile_summaries,
    save_profile,
    set_inventory_item_status,
    set_inventory_items_status,
    set_weapon_level,
    validate_profile,
)
from .storage import read_json, slugify
from .update import UpdateResult, check_for_update


@dataclass(frozen=True)
class InventoryRow:
    item_id: str
    name: str
    status: str
    category: str
    warbond_id: str | None
    group: str | None
    detail: str
    level: int | None
    facts: dict[str, Any]


@dataclass(frozen=True)
class ProfileChoice:
    player_id: str
    display_name: str
    path: Path


class PlannerService:
    """Canonical profile/catalog operations shared by GUI widgets."""

    def __init__(
        self,
        *,
        paths: UserDataPaths | None = None,
        catalog: dict[str, Any] | None = None,
        context_exporter: Callable[..., tuple[Path, Path]] = export_context,
        update_checker: Callable[[], UpdateResult] = check_for_update,
    ) -> None:
        self.paths = (paths or user_data_paths()).initialize()
        self.catalog = catalog or load_catalog()
        self.index = catalog_index(self.catalog)
        self.context_exporter = context_exporter
        self.update_checker = update_checker
        self.profile: dict[str, Any] | None = None
        self.profile_path: Path | None = None
        self.character_id: str | None = None

    def profiles(self) -> list[ProfileChoice]:
        return [
            ProfileChoice(value["player_id"], value["display_name"], value["path"])
            for value in profile_summaries(self.paths.profiles)
        ]

    def open_profile(self, player_id: str, character_id: str | None = None) -> dict[str, Any]:
        choice = next((choice for choice in self.profiles() if choice.player_id == player_id), None)
        if choice is None:
            raise ProfileError(f"No profile found for player {player_id!r}")
        path, profile = load_profile(player_id, self.catalog, self.paths)
        self.profile = profile
        self.profile_path = path
        if character_id is not None and character_id not in profile["characters"]:
            raise ProfileError(f"Unknown character {character_id!r}")
        self.character_id = character_id or next(iter(profile["characters"]))
        return profile

    def create_profile(
        self,
        player_name: str,
        character_name: str,
        platform: str,
        level: int,
        *,
        player_id: str | None = None,
    ) -> dict[str, Any]:
        player_name = player_name.strip()
        character_name = character_name.strip()
        if not player_name or not character_name:
            raise ProfileError("Player and character names are required")
        if level < 0:
            raise ProfileError("Level must be a non-negative whole number")
        resolved_player_id = slugify(player_id or player_name)
        if not resolved_player_id:
            raise ProfileError("Player name must contain letters or numbers")
        path = self.paths.profiles / f"{resolved_player_id}.json"
        if path.exists():
            raise ProfileError(f"A profile already exists for {resolved_player_id!r}")
        profile = new_profile(resolved_player_id, player_name)
        character_id = slugify(character_name)
        add_character(profile, character_id, platform.strip() or "unknown", level, character_name)
        self.profile, self.profile_path, self.character_id = profile, path, character_id
        self._save()
        return profile

    def select_character(self, character_id: str) -> None:
        profile = self._require_profile()
        if character_id not in profile["characters"]:
            raise ProfileError(f"Unknown character {character_id!r}")
        self.character_id = character_id

    def add_character(self, name: str, platform: str, level: int) -> str:
        profile = self._require_profile()
        character_id = slugify(name)
        before = copy.deepcopy(profile)
        try:
            add_character(profile, character_id, platform.strip() or "unknown", level, name.strip())
            self.character_id = character_id
            self._save()
        except BaseException:
            self.profile = before
            raise
        return character_id

    def edit_character(self, name: str, platform: str, level: int) -> None:
        character = self.character()
        if not name.strip():
            raise ProfileError("Character name is required")
        if level < 0:
            raise ProfileError("Level must be a non-negative whole number")
        self._mutate(lambda: character.update({
            "display_name": name.strip(), "platform": platform.strip() or "unknown", "level": level,
        }))

    def character(self) -> dict[str, Any]:
        profile = self._require_profile()
        if self.character_id is None:
            raise ProfileError("No character selected")
        return profile["characters"][self.character_id]

    def character_choices(self) -> list[tuple[str, str]]:
        profile = self._require_profile()
        return [
            (character_id, self.character_label(character_id))
            for character_id in profile["characters"]
        ]

    def character_label(self, character_id: str | None = None) -> str:
        profile = self._require_profile()
        character_id = character_id or self.character_id
        if character_id is None:
            return ""
        character = profile["characters"][character_id]
        return f"{character.get('display_name', character_id)} — {character.get('platform', 'unknown')} (Lv {character.get('level', 0)})"

    def inventory_rows(
        self,
        category: str,
        *,
        search: str = "",
        status: str = "all",
        warbond_id: str | None = None,
        group: str | None = None,
        compatible_weapon_id: str | None = None,
    ) -> list[InventoryRow]:
        if category not in INVENTORY_TO_CATALOG:
            raise ValueError(f"Unknown inventory category {category!r}")
        inventory = self.character().get("inventory", {}).get(category, {})
        query = search.strip().casefold()
        rows: list[InventoryRow] = []
        for item in items_for_inventory_category(self.catalog, category):
            facts = item.get("facts", {})
            item_status = inventory.get(item["id"], {}).get("status", "unknown")
            item_warbond = facts.get("warbond_id")
            item_group = self._item_group(category, facts)
            if query and query not in item["name"].casefold() and query not in item["id"].casefold():
                continue
            if status != "all" and item_status != status:
                continue
            if warbond_id and item_warbond != warbond_id:
                continue
            if group and item_group != group:
                continue
            if compatible_weapon_id and compatible_weapon_id not in facts.get("compatible_weapon_ids", []):
                continue
            state = inventory.get(item["id"], {})
            rows.append(InventoryRow(
                item_id=item["id"], name=item["name"], status=item_status, category=category,
                warbond_id=item_warbond, group=item_group, detail=self._item_detail(category, facts),
                level=state.get("level"), facts=facts,
            ))
        if category == "ship_modules":
            rows.sort(key=lambda row: (row.group or "", int(row.facts.get("tier", 0) or 0), row.name.casefold()))
        elif category == "stratagems":
            rows.sort(key=lambda row: (row.group or "other", row.name.casefold()))
        return rows

    def inventory_status(self, category: str, item_id: str) -> str:
        return self.character().get("inventory", {}).get(category, {}).get(item_id, {}).get("status", "unknown")

    def set_inventory_status(self, category: str, item_id: str, status: str) -> None:
        if status not in UNLOCK_STATES:
            raise ValueError(f"Unknown inventory status {status!r}")
        def change() -> None:
            set_inventory_item_status(self._require_profile(), self.character_id or "", category, item_id, status, self.catalog)

        self._mutate(change)

    def bulk_set_status(
        self,
        category: str,
        item_ids: Iterable[str],
        status: str,
        *,
        only_unknown: bool = False,
    ) -> int:
        if status not in UNLOCK_STATES:
            raise ValueError(f"Unknown inventory status {status!r}")
        selected = list(dict.fromkeys(item_ids))
        changed = 0

        def change() -> None:
            nonlocal changed
            changed = set_inventory_items_status(
                self._require_profile(), self.character_id or "", category, selected,
                status, self.catalog, only_unknown=only_unknown,
            )

        if selected:
            self._mutate(change)
        return changed

    def set_weapon_level(self, category: str, item_id: str, level: int | None) -> None:
        def change() -> None:
            set_weapon_level(self._require_profile(), self.character_id or "", category, item_id, level, self.catalog)

        self._mutate(change)

    def set_item_preference(self, item_id: str, preference: str) -> None:
        if item_id not in self.index:
            raise ProfileError(f"Unknown catalog item {item_id!r}")
        if preference not in PREFERENCE_STATES:
            raise ProfileError(f"Unknown preference {preference!r}")

        def change() -> None:
            prefs = self.character().setdefault("preference_overrides", {}).setdefault("item_preferences", {})
            if preference == "neutral":
                prefs.pop(item_id, None)
            else:
                prefs[item_id] = preference

        self._mutate(change)

    def set_general_preference(self, key: str, value: str) -> None:
        key = key.strip()
        if not key:
            raise ProfileError("Preference name is required")

        def change() -> None:
            prefs = self.character().setdefault("preference_overrides", {}).setdefault("general", {})
            if value.strip():
                prefs[key] = value.strip()
            else:
                prefs.pop(key, None)

        self._mutate(change)

    def add_observation(
        self,
        *,
        item_id: str | None,
        faction: str | None,
        difficulty: int | None,
        mission_type: str | None,
        rating: str,
        confidence: str,
        notes: str,
    ) -> None:
        if item_id and item_id not in self.index:
            raise ProfileError(f"Unknown item {item_id!r}")
        if not notes.strip():
            raise ProfileError("Observation notes are required")
        observation = {
            "date": date.today().isoformat(), "character": self.character_id,
            "item_id": item_id or None, "faction": faction or None,
            "difficulty": difficulty, "mission_type": mission_type or None,
            "rating": rating, "confidence": confidence, "notes": notes.strip(),
        }
        self._mutate(lambda: self._require_profile().setdefault("gameplay_observations", []).append(observation))

    def saved_loadouts(self) -> list[dict[str, Any]]:
        profile = self._require_profile()
        result: list[dict[str, Any]] = []
        for number, loadout in enumerate(profile.get("saved_loadouts", [])):
            result.append({"source": "inline", "key": number, "loadout": loadout})
        for relative in profile.get("saved_loadout_files", []):
            path = self.paths.loadouts / relative
            try:
                loadout = read_json(path)
            except (OSError, ValueError) as exc:
                loadout = {"id": relative, "name": relative, "_read_error": str(exc)}
            result.append({"source": "file", "key": relative, "path": path, "loadout": loadout})
        return result

    def validate_loadout(self, entry: dict[str, Any]) -> dict[str, Any]:
        loadout = entry["loadout"]
        if loadout.get("_read_error"):
            return {"errors": [loadout["_read_error"]], "usable": [], "missing": [], "unknown": [], "total": 0}
        return validate_for_character(loadout, self.character(), self.catalog)

    def delete_loadout(self, source: str, key: int | str) -> None:
        def change() -> None:
            profile = self._require_profile()
            if source == "inline":
                del profile.setdefault("saved_loadouts", [])[int(key)]
            elif source == "file":
                links = profile.setdefault("saved_loadout_files", [])
                links.remove(str(key))
            else:
                raise ProfileError(f"Unknown loadout source {source!r}")

        self._mutate(change)

    def locked_warbond_unknown_items(self) -> list[tuple[str, str]]:
        """Return (category, item id) pairs explicitly linked to locked Warbonds."""
        locked = {
            row.item_id for row in self.inventory_rows("warbonds") if row.status == "locked"
        }
        result: list[tuple[str, str]] = []
        for category in INVENTORY_TO_CATALOG:
            if category == "warbonds":
                continue
            for row in self.inventory_rows(category):
                if row.status == "unknown" and row.warbond_id in locked:
                    result.append((category, row.item_id))
        return result

    def lock_items_from_locked_warbonds(self) -> int:
        pairs = self.locked_warbond_unknown_items()
        changed = 0

        def change() -> None:
            nonlocal changed
            for category in INVENTORY_TO_CATALOG:
                item_ids = [item_id for pair_category, item_id in pairs if pair_category == category]
                if item_ids:
                    changed += set_inventory_items_status(
                        self._require_profile(), self.character_id or "", category,
                        item_ids, "locked", self.catalog, only_unknown=True,
                    )

        if pairs:
            self._mutate(change)
        return changed

    def generate_context(self) -> tuple[Path, Path]:
        profile = self._require_profile()
        if self.character_id is None:
            raise ProfileError("No character selected")
        return self.context_exporter(profile, self.character_id, self.catalog, self.paths.generated)

    def check_updates(self) -> UpdateResult:
        return self.update_checker()

    def reload(self) -> None:
        if self.profile_path is None or self.character_id is None:
            return
        character_id = self.character_id
        player_id = self._require_profile()["player"]["id"]
        self.open_profile(player_id, character_id)

    def _require_profile(self) -> dict[str, Any]:
        if self.profile is None:
            raise ProfileError("No profile is open")
        return self.profile

    def _mutate(self, callback: Callable[[], None]) -> None:
        before = copy.deepcopy(self._require_profile())
        try:
            callback()
            self._save()
        except BaseException:
            self.profile = before
            raise

    def _save(self) -> None:
        profile = self._require_profile()
        if self.profile_path is None:
            raise ProfileError("No profile path is available")
        errors = validate_profile(profile, self.catalog)
        if errors:
            raise ProfileError("Profile update rejected:\n- " + "\n- ".join(errors))
        save_profile(self.profile_path, profile)

    @staticmethod
    def _item_group(category: str, facts: dict[str, Any]) -> str | None:
        if category == "stratagems":
            return facts.get("category", "other")
        if category == "ship_modules":
            return facts.get("path_id") or facts.get("section")
        if category == "armor":
            return facts.get("armor_class")
        if category == "weapon_attachments":
            return facts.get("slot")
        return None

    @staticmethod
    def _item_detail(category: str, facts: dict[str, Any]) -> str:
        if category == "armor":
            values = [facts.get("armor_class"), facts.get("passive_id") or facts.get("passive")]
            return " • ".join(str(value) for value in values if value)
        if category == "stratagems":
            level = facts.get("unlock_level")
            return f"{facts.get('category', 'other').replace('_', ' ').title()}" + (f" • unlock level {level}" if level else "")
        if category == "ship_modules":
            return f"{facts.get('section', 'Other')} • Tier {facts.get('tier', '?')}"
        if category == "weapon_attachments":
            return str(facts.get("slot", "Unknown slot")).replace("_", " ").title()
        if facts.get("warbond_page"):
            return f"Warbond page {facts['warbond_page']}"
        return ""
