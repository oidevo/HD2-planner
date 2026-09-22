from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from hd2lib.catalog import load_catalog
from hd2lib.data import UserDataPaths
from hd2lib.gui import HD2PlannerApp
from hd2lib.gui_model import PlannerService
from hd2lib.migrations import migrate_profile_file
from hd2lib.onboarding import review_inventory
from hd2lib.packaging import build_package
from hd2lib.profile import ProfileError, add_character, new_profile, save_profile
from hd2lib.storage import read_json, write_json


ROOT = Path(__file__).resolve().parent.parent


class InventoryRedesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_catalog(ROOT / "catalog")

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.paths = UserDataPaths(Path(self.temp.name)).initialize()
        profile = new_profile("redesign", "Redesign")
        add_character(profile, "one", "PC", 5)
        add_character(profile, "two", "PC", 1)
        self.path = self.paths.profiles / "redesign.json"
        save_profile(self.path, profile)
        self.service = PlannerService(paths=self.paths, catalog=self.catalog)
        self.service.open_profile("redesign", "one")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_migration_backs_up_global_answers_without_assigning_any_weapon(self) -> None:
        old = read_json(self.path)
        old["schema_version"] = "1.0.0"
        old["characters"]["one"]["inventory"]["weapon_attachments"] = {
            "drum_magazine": {"status": "unlocked"},
            "10x_sniper_scope": {"status": "unknown"},
        }
        old["characters"]["one"]["inventory"]["primary_weapons"] = {
            "sg_225_breaker": {"status": "unknown"},
        }
        write_json(self.path, old)
        backup = migrate_profile_file(self.path, self.catalog, self.paths)
        self.assertIsNotNone(backup)
        self.assertEqual(read_json(backup), old)
        migrated = read_json(self.path)
        one = migrated["characters"]["one"]
        self.assertEqual(one["legacy_attachment_review"]["drum_magazine"]["status"], "unlocked")
        self.assertEqual(one["legacy_attachment_review"]["10x_sniper_scope"]["status"], "unknown")
        self.assertEqual(one["weapon_attachments_by_weapon"], {})
        self.assertEqual(one["inventory"]["primary_weapons"]["sg_225_breaker"]["status"], "unknown")
        self.assertIsNone(migrate_profile_file(self.path, self.catalog, self.paths))

    def test_attachment_isolation_validation_and_export(self) -> None:
        first = "sg_225_breaker"
        attachment = self.service.inventory_rows("weapon_attachments", compatible_weapon_id=first)[0].item_id
        other = next(item for item in self.catalog["collections"]["attachments"]
                     if item["id"] == attachment)["facts"]["compatible_weapon_ids"]
        second = next(weapon for weapon in other if weapon != first)
        self.service.set_attachment_status(first, attachment, "unlocked")
        self.assertEqual(self.service.attachment_status(second, attachment), "unknown")
        self.service.select_character("two")
        self.assertEqual(self.service.attachment_status(first, attachment), "unknown")
        self.service.select_character("one")
        with self.assertRaises(ProfileError):
            self.service.set_attachment_status("not_a_weapon", attachment, "unlocked")
        context = read_json(self.service.generate_context()[0])
        self.assertEqual(context["weapon_attachments_by_weapon"][first][attachment]["status"], "unlocked")
        self.assertNotIn(second, context["weapon_attachments_by_weapon"])
        self.assertEqual(context["attachment_progression"][0]["weapon_id"], first)
        self.assertIn("sg_225_breaker", self.service.generate_context()[1].read_text(encoding="utf-8"))

    def test_attachment_save_failure_rolls_back_memory_and_file(self) -> None:
        weapon = "sg_225_breaker"
        attachment = self.service.inventory_rows("weapon_attachments", compatible_weapon_id=weapon)[0].item_id
        before = self.path.read_bytes()
        with patch("hd2lib.gui_model.save_profile", side_effect=OSError("full")):
            with self.assertRaises(OSError):
                self.service.set_attachment_status(weapon, attachment, "unlocked")
        self.assertEqual(self.service.attachment_status(weapon, attachment), "unknown")
        self.assertEqual(self.path.read_bytes(), before)

    def test_warbond_access_and_ownership_are_separate(self) -> None:
        row = next(row for row in self.service.inventory_rows("primary_weapons") if row.warbond_id and row.facts.get("warbond_page"))
        self.assertEqual(self.service.reward_access(row), "Warbond ownership unreviewed")
        self.service.set_inventory_status("warbonds", row.warbond_id, "unlocked")
        self.assertEqual(self.service.inventory_status(row.category, row.item_id), "unknown")
        self.assertEqual(self.service.reward_access(row), "Warbond owned · Page access unverified")
        self.service.set_inventory_status(row.category, row.item_id, "unlocked")
        self.service.set_inventory_status("warbonds", row.warbond_id, "locked")
        owned_row = next(value for value in self.service.inventory_rows(row.category) if value.item_id == row.item_id)
        self.assertIn("special grant", self.service.reward_access(owned_row))

    def test_unverified_reward_page_is_not_claimed_available(self) -> None:
        row = next(row for category in ("primary_weapons", "secondary_weapons", "armor", "grenades")
                   for row in self.service.inventory_rows(category)
                   if row.warbond_id and not row.facts.get("warbond_page"))
        self.service.set_inventory_status("warbonds", row.warbond_id, "unlocked")
        self.assertEqual(self.service.reward_access(row), "Warbond owned · Reward page unverified")

    def test_cli_attachment_review_uses_same_weapon_scoped_profile(self) -> None:
        weapon = "sg_225_breaker"
        answers = iter(["u", "s"])
        review_inventory(self.service.profile, "one", "weapon_attachments", self.catalog,
                         self.path, ask=lambda _prompt: next(answers), tell=lambda _message: None, weapon=weapon)
        reopened = PlannerService(paths=self.paths, catalog=self.catalog)
        reopened.open_profile("redesign", "one")
        self.assertEqual(sum(row.status == "unlocked" for row in reopened.inventory_rows(
            "weapon_attachments", compatible_weapon_id=weapon)), 1)
        with self.assertRaisesRegex(ValueError, "requires --weapon"):
            review_inventory(reopened.profile, "one", "weapon_attachments", self.catalog,
                             self.path, ask=lambda _prompt: "s", tell=lambda _message: None)

    def test_checkmark_click_is_distinct_from_row_selection_and_undo(self) -> None:
        self.assertEqual(HD2PlannerApp.click_action("cell", "#1", "x"), "toggle")
        self.assertEqual(HD2PlannerApp.click_action("cell", "#2", "x"), "select")
        self.assertEqual(HD2PlannerApp.click_action("heading", "#1", ""), "none")
        app = object.__new__(HD2PlannerApp)
        app.service = self.service
        app.current_category = "primary_weapons"
        app.current_view = "primary_weapons"
        app._warbond_context = None
        app.root = Mock()
        app.root.after.return_value = "undo-timer"
        app.undo_button = Mock()
        app._undo_change = None
        app._undo_job = None
        app._saved = Mock()
        app._refresh_inventory = Mock()
        app._inventory_selection_changed = Mock()
        app._toggle_item("sg_225_breaker")
        self.assertEqual(self.service.inventory_status("primary_weapons", "sg_225_breaker"), "unlocked")
        app._undo_inventory_change()
        self.assertEqual(self.service.inventory_status("primary_weapons", "sg_225_breaker"), "unknown")

    def test_ordinary_zip_contains_schema_docs_and_tests_without_private_data(self) -> None:
        archive = build_package(Path(self.temp.name) / "dist")
        with zipfile.ZipFile(archive) as contents:
            names = contents.namelist()
            self.assertTrue(any(name.endswith("schemas/profile.schema.json") for name in names))
            self.assertTrue(any(name.endswith("tests/test_inventory_redesign.py") for name in names))
            self.assertTrue(any(name.endswith("examples/profiles/example_player.json") for name in names))
            self.assertFalse(any("/backups/" in name or "/settings.json" in name or "/generated/" in name and not name.endswith("/generated/") for name in names))


if __name__ == "__main__":
    unittest.main()
