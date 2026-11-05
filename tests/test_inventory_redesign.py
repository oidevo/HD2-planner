from __future__ import annotations

import tempfile
import unittest
import zipfile
from collections import Counter
from dataclasses import replace
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

    def test_warbond_reward_keeps_its_page_and_shared_ownership_record(self) -> None:
        warbond_id = "democratic_detonation"
        item_id = "cb_9_exploding_crossbow"
        reward = next(row for row in self.service.warbond_contents(warbond_id) if row.item_id == item_id)
        self.assertEqual(reward.warbond_page, 3)
        self.assertEqual(reward.category, "primary_weapons")

        self.service.set_inventory_status(reward.category, reward.item_id, "unlocked")
        owned = self.service.inventory_rows("primary_weapons", warbond_id=warbond_id, status="unlocked")
        self.assertEqual([row.item_id for row in owned], [item_id])
        self.assertEqual(self.service.inventory_status("warbonds", warbond_id), "unknown")

        self.service.set_inventory_status("primary_weapons", item_id, "locked")
        contents = self.service.warbond_contents(warbond_id, category="primary_weapons", status="locked")
        self.assertEqual([(row.item_id, row.warbond_page) for row in contents], [(item_id, 3)])

    def test_ship_groups_keep_support_weapon_and_stratagem_records_distinct(self) -> None:
        stratagem, = self.service.inventory_rows("stratagems", search="mg-43", group="support_weapon")
        self.assertEqual(self.service.inventory_section(stratagem), "Patriotic Administration Center")
        weapon, = self.service.inventory_rows("support_weapons", search=stratagem.facts["support_weapon_id"])
        self.service.set_inventory_status(stratagem.category, stratagem.item_id, "unlocked")
        self.assertEqual(self.service.inventory_status(weapon.category, weapon.item_id), "unknown")
        modules = self.service.inventory_rows("ship_modules", group="engineering_bay")
        self.assertEqual({self.service.inventory_section(row) for row in modules}, {"Engineering Bay"})
        self.assertEqual([int(row.facts["tier"]) for row in modules], [1, 2, 3, 4, 5])

    def test_detail_routes_highlight_their_terminal_and_parent_tab(self) -> None:
        app = object.__new__(HD2PlannerApp)
        app.active_terminal = None
        app.tab_bar = Mock()
        app.tab_bar.winfo_children.return_value = []
        app.nav_buttons = {name: Mock() for name in ("Armory", "Ship Management", "Acquisition Center", "Planner")}
        app.tab_buttons = {}
        with patch("hd2lib.gui.ttk.Button", side_effect=lambda *_args, **_kwargs: Mock()):
            for route, terminal, tab in (
                ("support_weapons", "Ship Management", "stratagems"),
                ("ship_modules", "Ship Management", "ship_modules"),
                ("secondary_weapons", "Armory", "primary_weapons"),
                ("armor", "Armory", "armor"),
                ("warbond_contents", "Acquisition Center", "warbonds"),
                ("context", "Planner", "context"),
            ):
                with self.subTest(route=route):
                    app._activate_route(route)
                    self.assertEqual(app.current_view, route)
                    self.assertEqual(app.active_terminal, terminal)
                    for name, button in app.nav_buttons.items():
                        button.configure.assert_called_with(style="Accent.TButton" if name == terminal else "TButton")
                    for key, button in app.tab_buttons.items():
                        button.configure.assert_called_with(style="Accent.TButton" if key == tab else "TButton")

    def test_unverified_reward_page_is_not_claimed_available(self) -> None:
        row = self.service.warbond_contents("python_commandos")[0]
        row = replace(row, facts={key: value for key, value in row.facts.items() if key != "warbond_page"})
        self.service.set_inventory_status("warbonds", row.warbond_id, "unlocked")
        self.assertEqual(self.service.reward_access(row), "Warbond owned · Reward page unverified")

    def test_python_commandos_contains_each_page_and_reward_type(self) -> None:
        rows = self.service.warbond_contents("python_commandos")
        self.assertEqual(Counter(row.warbond_page for row in rows), {1: 8, 2: 7, 3: 6})
        self.assertEqual(
            {row.facts["reward_type"] for row in rows if row.category == "warbond_rewards"},
            {"Cape", "Currency", "Emote", "Helmet", "Pattern", "Player Card", "Title"},
        )
        self.assertEqual(
            {row.item_id for row in rows if row.category == "stratagems"},
            {"stratagem_ax_flam_75_hot_dog", "stratagem_cqc_9_defoliation_tool", "stratagem_m_1000_maxigun"},
        )
        self.assertEqual({row.warbond_page for row in rows if row.facts["reward_type"] == "Currency"}, {1, 2, 3})

    def test_all_catalog_warbonds_have_reward_pages(self) -> None:
        for warbond in self.service.inventory_rows("warbonds"):
            with self.subTest(warbond=warbond.name):
                self.assertTrue(self.service.has_warbond_reward_pages(warbond.item_id))
                pages = {row.warbond_page for row in self.service.warbond_contents(warbond.item_id)}
                self.assertEqual(pages, set(range(1, 11 if warbond.item_id == "helldivers_mobilize" else 4)))

    def test_warbond_currency_claim_persists_independently_of_bond_and_balance(self) -> None:
        warbond_id = "python_commandos"
        self.service.set_resources({"medals": 300, "super_credits": 200})
        self.service.set_inventory_status("warbonds", warbond_id, "unlocked")
        claims = [row for row in self.service.warbond_contents(warbond_id) if row.facts["reward_type"] == "Currency"]
        self.assertTrue(all(row.status == "unknown" for row in claims))
        self.service.set_inventory_status(claims[0].category, claims[0].item_id, "unlocked")
        self.service.reload()
        claims = [row for row in self.service.warbond_contents(warbond_id) if row.facts["reward_type"] == "Currency"]
        self.assertEqual([row.status for row in claims], ["unlocked", "unknown", "unknown"])
        self.assertEqual(self.service.inventory_status("warbonds", warbond_id), "unlocked")
        self.assertEqual(self.service.resources()["super_credits"], 200)
        self.assertEqual(self.service.resources()["medals"], 300)
        context_json, context_markdown = self.service.generate_context()
        exported, = read_json(context_json)["inventory"]["warbond_rewards"]
        self.assertEqual((exported["id"], exported["status"]), (claims[0].item_id, "unlocked"))
        self.assertIn("### Warbond-only rewards", context_markdown.read_text(encoding="utf-8"))
        self.service.select_character("two")
        self.assertEqual(self.service.inventory_status("warbond_rewards", claims[0].item_id), "unknown")

    def test_warbond_booster_opens_the_same_record_with_warbond_filter(self) -> None:
        bond_id = "viper_commandos"
        reward, = self.service.warbond_contents(bond_id, category="boosters")
        self.service.set_inventory_status(reward.category, reward.item_id, "unlocked")
        row, = self.service.inventory_rows("boosters", warbond_id=bond_id, status="unlocked")
        self.assertEqual((row.item_id, row.warbond_page), (reward.item_id, reward.warbond_page))

    def test_linked_reward_cannot_create_a_second_ownership_record(self) -> None:
        reward = next(item for item in self.catalog["collections"]["warbond_rewards"]
                      if item["facts"].get("inventory_ref", {}).get("item_id") == "stratagem_m_1000_maxigun")
        with self.assertRaisesRegex(ProfileError, "linked inventory ownership"):
            self.service.set_inventory_status("warbond_rewards", reward["id"], "unlocked")

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
