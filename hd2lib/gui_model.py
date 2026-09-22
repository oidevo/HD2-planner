"""Headless application service used by the Tk GUI.

The service deliberately owns no alternate persistence format.  It loads,
validates, and atomically saves the same profile dictionaries used by the CLI.
Keeping filtering and mutations here makes the important GUI behaviour
testable without a display server.
"""
from __future__ import annotations

import copy
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timezone
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
    set_character_resources,
    set_inventory_item_status,
    set_inventory_items_status,
    set_weapon_level,
    validate_profile,
)
from .presentation_order import load_presentation_order, sort_with_presentation_order
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


@dataclass(frozen=True)
class PreferenceRow:
    item_id: str
    name: str
    preference: str
    scope: str


RESOURCE_FIELDS = (
    ("medals", "Medals"),
    ("requisition", "Requisition slips"),
    ("super_credits", "Super credits"),
    ("common_samples", "Common samples"),
    ("rare_samples", "Rare samples"),
    ("super_samples", "Super samples"),
)


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
        self.presentation_order = load_presentation_order(
            catalog_version=str(self.catalog["manifest"].get("catalog_version")),
            known_item_ids=set(self.index),
        )
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

    def delete_character(self, typed_confirmation: str) -> tuple[Path, str]:
        """Back up and atomically remove only the selected character's state."""
        profile = self._require_profile()
        if self.character_id is None:
            raise ProfileError("No character selected")
        if len(profile.get("characters", {})) <= 1:
            raise ProfileError(
                "The final character cannot be deleted here. A separate player-profile deletion workflow is required."
            )
        character_id = self.character_id
        character = profile["characters"][character_id]
        display_name = str(character.get("display_name", character_id))
        if typed_confirmation not in {display_name, character_id}:
            raise ProfileError("Confirmation did not match the character display name or ID; nothing was deleted.")
        if self.profile_path is None:
            raise ProfileError("No profile path is available")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = self.paths.backups / f"{self.profile_path.stem}-{stamp}-pre-character-delete.json"
        number = 1
        while backup.exists():
            backup = self.paths.backups / f"{self.profile_path.stem}-{stamp}-pre-character-delete-{number}.json"
            number += 1
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.profile_path, backup)

        before = copy.deepcopy(profile)
        before_character_id = character_id
        try:
            del profile["characters"][character_id]
            profile["gameplay_observations"] = [
                observation for observation in profile.get("gameplay_observations", [])
                if observation.get("character") != character_id
            ]
            self.character_id = next(iter(profile["characters"]))
            self._save()
        except BaseException:
            self.profile = before
            self.character_id = before_character_id
            raise
        return backup, self.character_id

    def resources(self) -> dict[str, Any]:
        """Return a copy of the selected character's recorded balances."""
        return dict(self.character().get("resources", {}))

    @staticmethod
    def parse_resource_inputs(values: dict[str, str]) -> dict[str, int | None]:
        """Parse focused-dialog text, keeping blanks distinct from zero."""
        result: dict[str, int | None] = {}
        allowed = {key for key, _label in RESOURCE_FIELDS}
        for key, raw in values.items():
            if key not in allowed:
                raise ProfileError(f"Unknown resource {key!r}")
            value = raw.strip()
            if not value:
                result[key] = None
                continue
            if not value.isdecimal():
                raise ProfileError("Resource amounts must be non-negative whole numbers or blank")
            result[key] = int(value)
        return result

    def set_resources(self, resources: dict[str, int | None]) -> None:
        allowed = {key for key, _label in RESOURCE_FIELDS}
        if set(resources) - allowed:
            raise ProfileError(f"Unknown resource fields: {', '.join(sorted(set(resources) - allowed))}")
        self._mutate(lambda: set_character_resources(
            self._require_profile(), self.character_id or "", resources,
        ))

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
        screen = {
            "warbonds": "requisitions_warbonds",
            "stratagems": "stratagems",
            "ship_modules": "ship_management",
        }.get(category, "armory")
        return sort_with_presentation_order(
            rows, self.presentation_order, screen,
            item_id=lambda row: row.item_id,
            group_id=lambda row: row.group if category in {"stratagems", "ship_modules"} else category,
            fallback=lambda row: (
                int(row.facts.get("tier", 0) or 0) if category == "ship_modules" else 0,
                row.name.casefold(), row.item_id,
            ),
        )

    def ordering_message(self, category: str) -> str:
        screen = {
            "warbonds": "requisitions_warbonds",
            "stratagems": "stratagems",
            "ship_modules": "ship_management",
        }.get(category, "armory")
        return self.presentation_order.verification_message(screen)

    def warbond_contents(
        self, warbond_id: str, *, category: str = "all", status: str = "all",
    ) -> list[InventoryRow]:
        if warbond_id not in {item["id"] for item in self.catalog["collections"]["warbonds"]}:
            raise ProfileError(f"Unknown Warbond {warbond_id!r}")
        categories = [
            key for key in INVENTORY_TO_CATALOG
            if key not in {"warbonds", "armor_passives", "weapon_attachments"}
        ]
        if category != "all":
            if category not in categories:
                raise ValueError(f"Unsupported Warbond content category {category!r}")
            categories = [category]
        rows = [
            row for content_category in categories
            for row in self.inventory_rows(content_category, status=status, warbond_id=warbond_id)
        ]
        category_rank = {key: index for index, key in enumerate(categories)}
        return sorted(rows, key=lambda row: (
            category_rank[row.category],
            int(row.facts.get("warbond_page", 2**31 - 1) or 2**31 - 1),
            row.name.casefold(), row.item_id,
        ))

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
        inventory = self.character().get("inventory", {}).get(category, {})
        selected = [
            item_id for item_id in selected
            if inventory.get(item_id, {}).get("status", "unknown") != status
            and (not only_unknown or inventory.get(item_id, {}).get("status", "unknown") == "unknown")
        ]
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
                base = self._require_profile().get("preferences", {}).get("item_preferences", {})
                if base.get(item_id, "neutral") == "neutral":
                    prefs.pop(item_id, None)
                else:
                    prefs[item_id] = "neutral"
            else:
                prefs[item_id] = preference

        self._mutate(change)

    def explicit_item_preferences(self, *, search: str = "") -> list[PreferenceRow]:
        """Return only non-neutral effective preferences for the selected character."""
        profile = self._require_profile()
        character = self.character()
        base = profile.get("preferences", {}).get("item_preferences", {})
        overrides = character.get("preference_overrides", {}).get("item_preferences", {})
        effective = dict(base)
        effective.update(overrides)
        query = search.strip().casefold()
        rows: list[PreferenceRow] = []
        for item_id, preference in effective.items():
            if preference == "neutral" or item_id not in self.index:
                continue
            name = self.index[item_id]["name"]
            if query and query not in name.casefold() and query not in item_id.casefold():
                continue
            rows.append(PreferenceRow(
                item_id=item_id,
                name=name,
                preference=preference,
                scope="Character override" if item_id in overrides else "Player preference",
            ))
        return sorted(rows, key=lambda row: row.name.casefold())

    def item_preference(self, item_id: str) -> str:
        profile = self._require_profile()
        base = profile.get("preferences", {}).get("item_preferences", {})
        overrides = self.character().get("preference_overrides", {}).get("item_preferences", {})
        return overrides.get(item_id, base.get(item_id, "neutral"))

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
