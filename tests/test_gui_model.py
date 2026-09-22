from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from hd2lib.catalog import load_catalog
from hd2lib.cli import parser
from hd2lib.data import UserDataPaths
from hd2lib.exporter import export_context
from hd2lib.gui_model import PlannerService
from hd2lib.profile import add_character, new_profile, save_profile
from hd2lib.storage import read_json
from hd2lib.update import UpdateResult


ROOT = Path(__file__).resolve().parent.parent


class GUIModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(ROOT / "catalog")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.paths = UserDataPaths(Path(self.temporary.name) / "external-data").initialize()
        profile = new_profile("tester", "Test Player")
        add_character(profile, "pc", "PC", 10, "Main")
        add_character(profile, "xbox", "Xbox", 2, "Alt")
        save_profile(self.paths.profiles / "tester.json", profile)
        self.service = PlannerService(paths=self.paths, catalog=self.catalog)
        self.service.open_profile("tester", "pc")

    def tearDown(self):
        self.temporary.cleanup()

    def test_gui_reads_existing_player_and_character_data(self):
        self.assertEqual(self.service.profile["player"]["display_name"], "Test Player")
        self.assertEqual(self.service.character()["display_name"], "Main")
        self.assertEqual(self.service.character()["level"], 10)

    def test_switching_characters_switches_inventory_state(self):
        self.service.set_inventory_status("primary_weapons", "sg_225_breaker", "unlocked")
        self.service.select_character("xbox")
        self.assertEqual(self.service.inventory_status("primary_weapons", "sg_225_breaker"), "unknown")
        self.service.set_inventory_status("primary_weapons", "sg_225_breaker", "locked")
        self.service.select_character("pc")
        self.assertEqual(self.service.inventory_status("primary_weapons", "sg_225_breaker"), "unlocked")

    def test_marking_unknown_unlocked_updates_canonical_profile(self):
        self.assertEqual(self.service.inventory_status("primary_weapons", "sg_225_breaker"), "unknown")
        self.service.set_inventory_status("primary_weapons", "sg_225_breaker", "unlocked")
        saved = read_json(self.paths.profiles / "tester.json")
        self.assertEqual(saved["characters"]["pc"]["inventory"]["primary_weapons"]["sg_225_breaker"]["status"], "unlocked")

    def test_marking_unlocked_locked_updates_canonical_profile(self):
        self.service.set_inventory_status("primary_weapons", "sg_225_breaker", "unlocked")
        self.service.set_inventory_status("primary_weapons", "sg_225_breaker", "locked")
        self.assertEqual(read_json(self.paths.profiles / "tester.json")["characters"]["pc"]["inventory"]["primary_weapons"]["sg_225_breaker"]["status"], "locked")

    def test_bulk_remaining_visible_locked_affects_only_visible_unknown(self):
        rows = self.service.inventory_rows("primary_weapons", search="Breaker")
        self.assertGreater(len(rows), 1)
        protected = rows[0].item_id
        self.service.set_inventory_status("primary_weapons", protected, "unlocked")
        visible_ids = [row.item_id for row in rows]
        changed = self.service.bulk_set_status("primary_weapons", visible_ids, "locked", only_unknown=True)
        self.assertEqual(changed, len(rows) - 1)
        self.assertEqual(self.service.inventory_status("primary_weapons", protected), "unlocked")
        outside = next(row.item_id for row in self.service.inventory_rows("primary_weapons") if row.item_id not in visible_ids)
        self.assertEqual(self.service.inventory_status("primary_weapons", outside), "unknown")

    def test_search_filtering(self):
        rows = self.service.inventory_rows("primary_weapons", search="breaker incendiary")
        self.assertTrue(rows)
        self.assertTrue(all("breaker incendiary" in row.name.casefold() for row in rows))

    def test_status_filtering(self):
        self.service.set_inventory_status("primary_weapons", "sg_225_breaker", "unlocked")
        rows = self.service.inventory_rows("primary_weapons", status="unlocked")
        self.assertEqual([row.item_id for row in rows], ["sg_225_breaker"])

    def test_warbond_filtering(self):
        candidate = next(row for row in self.service.inventory_rows("primary_weapons") if row.warbond_id)
        rows = self.service.inventory_rows("primary_weapons", warbond_id=candidate.warbond_id)
        self.assertTrue(rows)
        self.assertTrue(all(row.warbond_id == candidate.warbond_id for row in rows))

    def test_weapon_level_editing_persists_and_exports(self):
        self.service.set_weapon_level("primary_weapons", "sg_225_breaker", 18)
        saved = read_json(self.paths.profiles / "tester.json")
        self.assertEqual(saved["characters"]["pc"]["inventory"]["primary_weapons"]["sg_225_breaker"]["level"], 18)
        _, markdown = self.service.generate_context()
        self.assertIn("level 18", markdown.read_text(encoding="utf-8"))

    def test_resource_inputs_preserve_blank_versus_zero(self):
        parsed = self.service.parse_resource_inputs({
            "medals": "0", "requisition": "", "super_credits": " 25 ",
        })
        self.assertEqual(parsed, {"medals": 0, "requisition": None, "super_credits": 25})
        self.service.set_resources(parsed)
        saved = read_json(self.paths.profiles / "tester.json")
        self.assertEqual(saved["characters"]["pc"]["resources"], {"medals": 0, "super_credits": 25})

    def test_resource_edit_preserves_unrecognized_legacy_fields(self):
        self.service.character()["resources"]["future_currency"] = "preserved"
        self.service.set_resources({"medals": 4})
        saved = read_json(self.paths.profiles / "tester.json")
        self.assertEqual(saved["characters"]["pc"]["resources"]["future_currency"], "preserved")

    def test_resource_inputs_reject_negative_fractional_and_text_values(self):
        for value in ("-1", "1.5", "ten"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "non-negative whole numbers"):
                self.service.parse_resource_inputs({"medals": value})

    def test_resource_save_is_atomic_and_rolls_back_display_model(self):
        self.service.set_resources({"medals": 7})
        before_file = (self.paths.profiles / "tester.json").read_bytes()
        with patch("hd2lib.gui_model.save_profile", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.service.set_resources({"medals": 99})
        self.assertEqual(self.service.resources(), {"medals": 7})
        self.assertEqual((self.paths.profiles / "tester.json").read_bytes(), before_file)

    def test_resources_are_character_specific(self):
        self.service.set_resources({"medals": 12, "rare_samples": 3})
        self.service.select_character("xbox")
        self.assertEqual(self.service.resources(), {})
        self.service.set_resources({"medals": 1})
        self.service.select_character("pc")
        self.assertEqual(self.service.resources(), {"medals": 12, "rare_samples": 3})

    def test_resources_are_in_json_and_markdown_context(self):
        self.service.set_resources({"medals": 17, "requisition": 0, "super_samples": None})
        json_path, markdown_path = self.service.generate_context()
        context = read_json(json_path)
        self.assertEqual(context["character"]["resources"], {"medals": 17, "requisition": 0})
        markdown = markdown_path.read_text(encoding="utf-8")
        self.assertIn("- Medals: 17", markdown)
        self.assertIn("- Requisition slips: 0", markdown)

    def test_preferences_list_only_explicit_non_neutral_values(self):
        self.assertEqual(self.service.explicit_item_preferences(), [])
        self.service.profile["preferences"]["item_preferences"]["ar_23_liberator"] = "like"
        self.service.set_item_preference("sg_225_breaker", "favorite")
        rows = self.service.explicit_item_preferences()
        self.assertEqual({row.item_id for row in rows}, {"ar_23_liberator", "sg_225_breaker"})
        self.assertEqual({row.scope for row in rows}, {"Player preference", "Character override"})
        self.service.set_item_preference("sg_225_breaker", "neutral")
        self.assertEqual([row.item_id for row in self.service.explicit_item_preferences()], ["ar_23_liberator"])

    def test_explicit_preference_search_does_not_expand_to_neutral_catalog(self):
        self.service.set_item_preference("sg_225_breaker", "avoid")
        self.assertEqual([row.item_id for row in self.service.explicit_item_preferences(search="breaker")], ["sg_225_breaker"])
        self.assertEqual(self.service.explicit_item_preferences(search="liberator"), [])

    def test_attachment_state_editing_persists(self):
        attachment = self.service.inventory_rows("weapon_attachments", compatible_weapon_id="sg_225_breaker")[0]
        self.service.set_inventory_status("weapon_attachments", attachment.item_id, "unlocked")
        reopened = PlannerService(paths=self.paths, catalog=self.catalog)
        reopened.open_profile("tester", "pc")
        self.assertEqual(reopened.inventory_status("weapon_attachments", attachment.item_id), "unlocked")

    def test_autosave_uses_canonical_profile_writer(self):
        with patch("hd2lib.gui_model.save_profile", wraps=save_profile) as writer:
            self.service.set_inventory_status("grenades", "g_12_high_explosive", "unlocked")
        writer.assert_called_once()
        self.assertEqual(writer.call_args.args[0], self.paths.profiles / "tester.json")

    def test_context_button_service_calls_existing_exporter(self):
        expected = (self.paths.generated / "a.json", self.paths.generated / "a.md")
        exporter = Mock(return_value=expected)
        service = PlannerService(paths=self.paths, catalog=self.catalog, context_exporter=exporter)
        service.open_profile("tester", "pc")
        self.assertEqual(service.generate_context(), expected)
        exporter.assert_called_once_with(service.profile, "pc", self.catalog, self.paths.generated)

    def test_update_gui_service_uses_existing_update_service(self):
        expected = UpdateResult("0.2.1", "0.3.0", "https://example.test", True)
        checker = Mock(return_value=expected)
        service = PlannerService(paths=self.paths, catalog=self.catalog, update_checker=checker)
        self.assertEqual(service.check_updates(), expected)
        checker.assert_called_once_with()

    def test_existing_cli_created_profile_loads(self):
        # These are the same canonical constructor/writer calls used by CLI setup.
        cli_profile = new_profile("cli_player", "CLI Player")
        add_character(cli_profile, "main", "PC", 5)
        save_profile(self.paths.profiles / "cli_player.json", cli_profile)
        service = PlannerService(paths=self.paths, catalog=self.catalog)
        service.open_profile("cli_player", "main")
        self.assertEqual(service.character()["platform"], "PC")

    def test_locked_warbond_helper_only_changes_explicit_links(self):
        candidate = next(row for row in self.service.inventory_rows("primary_weapons") if row.warbond_id)
        self.service.set_inventory_status("warbonds", candidate.warbond_id, "locked")
        pairs = self.service.locked_warbond_unknown_items()
        self.assertIn(("primary_weapons", candidate.item_id), pairs)
        count = self.service.lock_items_from_locked_warbonds()
        self.assertGreater(count, 0)
        self.assertEqual(self.service.inventory_status("primary_weapons", candidate.item_id), "locked")

    def test_gui_changes_are_readable_by_cli_backend(self):
        self.service.set_inventory_status("stratagems", "stratagem_eagle_airstrike", "unlocked")
        profile = read_json(self.paths.profiles / "tester.json")
        output = self.paths.generated / "cli-compatible"
        json_path, _ = export_context(profile, "pc", self.catalog, output)
        context = read_json(json_path)
        entry = next(item for item in context["inventory"]["stratagems"] if item["id"] == "stratagem_eagle_airstrike")
        self.assertEqual(entry["status"], "unlocked")

    def test_user_data_path_remains_external_to_application(self):
        self.assertFalse(self.paths.root.is_relative_to(ROOT))
        self.service.set_inventory_status("boosters", self.service.inventory_rows("boosters")[0].item_id, "unlocked")
        self.assertTrue((self.paths.profiles / "tester.json").exists())

    def test_cli_gui_command_is_registered(self):
        self.assertEqual(parser().parse_args(["gui"]).command, "gui")


if __name__ == "__main__":
    unittest.main()
