"""Regression coverage for the Super Destroyer terminal navigation redesign.

The model and service tests run anywhere. The Tk flow tests need a display
(a real desktop or ``xvfb-run``) and skip cleanly without one.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hd2lib.catalog import catalog_index, load_catalog
from hd2lib.data import UserDataPaths
from hd2lib.gui_model import PlannerService
from hd2lib.navigation import (
    ACQUISITION_CENTER, ARMORY, PLANNER, SHIP_MANAGEMENT, SUPER_DESTROYER_TERMINALS, TERMINALS,
    location_for, presentation_screen, tab_for_category, tracked_categories,
)
from hd2lib.presentation_order import load_presentation_order
from hd2lib.profile import add_character, new_profile, save_profile


ROOT = Path(__file__).resolve().parent.parent
TRACKED_INVENTORY = {"warbonds", "primary_weapons", "secondary_weapons", "support_weapons", "grenades", "armor", "boosters", "stratagems", "ship_modules"}


class NavigationModelTests(unittest.TestCase):
    def test_three_terminals_plus_planner_in_game_order(self):
        self.assertEqual([terminal.label for terminal in SUPER_DESTROYER_TERMINALS], ["Armory", "Ship Management", "Acquisition Center"])
        self.assertEqual([terminal.label for terminal in TERMINALS], ["Armory", "Ship Management", "Acquisition Center", "Planner"])
        self.assertTrue(PLANNER.planner)
        self.assertFalse(any(terminal.planner for terminal in SUPER_DESTROYER_TERMINALS))

    def test_tab_labels_follow_the_terminals(self):
        self.assertEqual([tab.label for tab in ARMORY.tabs], ["Primary", "Secondary", "Grenade", "Armor", "Booster"])
        self.assertEqual([tab.label for tab in SHIP_MANAGEMENT.tabs], ["Stratagems", "Ship Modules"])
        self.assertEqual([tab.label for tab in ACQUISITION_CENTER.tabs], ["Warbonds"])
        self.assertEqual([tab.label for tab in PLANNER.tabs], ["Preferences", "Observations", "Saved Loadouts", "Context Export"])

    def test_every_tracked_inventory_category_has_exactly_one_home(self):
        self.assertEqual(tracked_categories(), TRACKED_INVENTORY)
        homes = {}
        for terminal in TERMINALS:
            for tab in terminal.tabs:
                if tab.category:
                    self.assertNotIn(tab.category, homes, "category appears under two tabs")
                    homes[tab.category] = (terminal.id, tab.id)
        self.assertEqual(homes["stratagems"], ("ship_management", "stratagems"))
        self.assertEqual(homes["ship_modules"], ("ship_management", "ship_modules"))
        self.assertEqual(homes["warbonds"], ("acquisition_center", "warbonds"))
        self.assertEqual(homes["primary_weapons"], ("armory", "primary_weapons"))

    def test_subviews_resolve_to_their_terminal_and_tab(self):
        support = location_for("support_weapons")
        self.assertEqual(support.breadcrumb(), "Ship Management › Stratagems › Support weapon records")
        contents = location_for("warbond_contents", trail=("Cutting Edge",))
        self.assertEqual(contents.breadcrumb(), "Acquisition Center › Warbonds › Cutting Edge")
        customize = location_for("weapon_customization", category="secondary_weapons", trail=("Customize · P-2 Peacemaker",))
        self.assertEqual(customize.breadcrumb(), "Armory › Secondary › Customize · P-2 Peacemaker")
        support_customize = location_for("weapon_customization", category="support_weapons", trail=("Customize · X",))
        self.assertEqual((support_customize.terminal.id, support_customize.tab.id), ("ship_management", "stratagems"))
        self.assertEqual(location_for("legacy_attachments").terminal.id, "armory")
        self.assertIsNone(location_for("settings"))
        self.assertEqual(tab_for_category("boosters")[1].label, "Booster")

    def test_presentation_screens_match_terminal_tabs_and_catalog_groups(self):
        catalog = load_catalog(ROOT / "catalog")
        order = load_presentation_order(catalog_version=catalog["manifest"]["catalog_version"], known_item_ids=set(catalog_index(catalog)))
        screen_ids = {screen["id"] for screen in order.document["screens"]}
        self.assertEqual(screen_ids, {"acquisition_center_warbonds", "ship_management_stratagems", "ship_management_ship_modules", "armory"})
        for category in TRACKED_INVENTORY | {"weapon_attachments"}:
            self.assertIn(presentation_screen(category), screen_ids, category)
        self.assertEqual(presentation_screen("support_weapons"), "ship_management_stratagems")
        departments = {item["facts"]["path_id"] for item in catalog["collections"]["ship_modules"]}
        self.assertEqual({group["id"] for group in order.screen("ship_management_ship_modules")["groups"]}, departments)
        stratagem_types = {item["facts"]["category"] for item in catalog["collections"]["stratagems"] if item["facts"].get("player_equippable")}
        self.assertLessEqual(stratagem_types, {group["id"] for group in order.screen("ship_management_stratagems")["groups"]})
        # No captures were supplied: nothing may claim verified game order.
        for screen in order.document["screens"]:
            self.assertEqual(screen["verification"], "unverified", screen["id"])
            for group in screen["groups"]:
                self.assertEqual(group["item_ids"], [], f"{screen['id']}/{group['id']}")


class NavigationServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(ROOT / "catalog")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.paths = UserDataPaths(Path(self.temporary.name) / "data").initialize()
        profile = new_profile("nav", "Nav Tester")
        add_character(profile, "pc", "PC", 30, "Main")
        add_character(profile, "alt", "PS5", 3, "Alt")
        save_profile(self.paths.profiles / "nav.json", profile)
        self.service = PlannerService(paths=self.paths, catalog=self.catalog)
        self.service.open_profile("nav", "pc")

    def tearDown(self):
        self.temporary.cleanup()

    def test_every_support_weapon_stratagem_links_to_a_support_weapon_record(self):
        stratagems = [row for row in self.service.inventory_rows("stratagems") if row.group == "support_weapon"]
        self.assertTrue(stratagems)
        records = {row.item_id for row in self.service.inventory_rows("support_weapons")}
        for row in stratagems:
            weapon_id = self.service.support_weapon_for_stratagem(row.item_id)
            self.assertIn(weapon_id, records, row.name)
            self.assertEqual(self.service.stratagem_for_support_weapon(weapon_id), row.item_id)
        self.assertIsNone(self.service.support_weapon_for_stratagem("eagle_airstrike"))
        self.assertIsNone(self.service.support_weapon_for_stratagem("sg_225_breaker"))

    def test_stratagem_and_support_weapon_ownership_remain_separate_records(self):
        stratagem = next(row for row in self.service.inventory_rows("stratagems") if row.group == "support_weapon")
        weapon_id = self.service.support_weapon_for_stratagem(stratagem.item_id)
        self.service.set_inventory_status("stratagems", stratagem.item_id, "unlocked")
        self.assertEqual(self.service.inventory_status("support_weapons", weapon_id), "unknown")
        self.service.set_inventory_status("support_weapons", weapon_id, "locked")
        self.assertEqual(self.service.inventory_status("stratagems", stratagem.item_id), "unlocked")

    def test_ship_modules_group_by_department_and_stay_unverified(self):
        rows = self.service.inventory_rows("ship_modules")
        self.assertEqual([row.group for row in rows[:5]], ["patriotic_administration_center"] * 5)
        departments = [group["id"] for group in self.service.presentation_order.screen("ship_management_ship_modules")["groups"]]
        self.assertEqual({row.group for row in rows}, set(departments))
        self.assertEqual([row.group for row in rows], sorted((row.group for row in rows), key=departments.index), "rows follow the department group order")
        self.assertIn("fallback order", self.service.ordering_message("ship_modules"))
        self.assertIn("fallback order", self.service.ordering_message("support_weapons"))

    def test_warbond_reward_ownership_is_the_same_record_as_the_inventory_view(self):
        rows = self.service.warbond_contents("cutting_edge")
        reward = next(row for row in rows if row.category == "primary_weapons")
        self.service.set_inventory_status(reward.category, reward.item_id, "unlocked")
        inventory_row = next(row for row in self.service.inventory_rows("primary_weapons", warbond_id="cutting_edge") if row.item_id == reward.item_id)
        self.assertEqual(inventory_row.status, "unlocked")
        self.assertEqual(next(row for row in self.service.warbond_contents("cutting_edge") if row.item_id == reward.item_id).status, "unlocked")
        self.assertEqual(self.service.inventory_status("warbonds", "cutting_edge"), "unknown")
        self.service.select_character("alt")
        self.assertEqual(self.service.inventory_status("primary_weapons", reward.item_id), "unknown")

    def test_warbond_pages_group_known_pages_first_and_unmapped_last(self):
        rows = self.service.warbond_contents("cutting_edge")
        pages = self.service.warbond_pages(rows)
        numbered = [page for page, _members in pages if page is not None]
        self.assertEqual(numbered, sorted(numbered))
        self.assertTrue(all(members for _page, members in pages))
        if pages[-1][0] is None:
            self.assertTrue(all(self.service.warbond_page_of(row) is None for row in pages[-1][1]))
        self.assertEqual(sum(len(members) for _page, members in pages), len(rows))

    def test_attachment_summary_counts_only_this_weapon_and_character(self):
        weapon = "sg_225_breaker"
        attachment = self.service.inventory_rows("weapon_attachments", compatible_weapon_id=weapon)[0].item_id
        other = next(value for value in self.service.index[attachment]["facts"]["compatible_weapon_ids"] if value != weapon)
        self.assertEqual(self.service.attachment_summary(weapon)[0], 0)
        self.service.set_attachment_status(weapon, attachment, "unlocked")
        self.assertEqual(self.service.attachment_summary(weapon)[0], 1)
        self.assertEqual(self.service.attachment_summary(other)[0], 0)
        self.service.select_character("alt")
        self.assertEqual(self.service.attachment_summary(weapon)[0], 0)


def _display_available() -> bool:
    try:
        import tkinter as tk
        root = tk.Tk()
    except Exception:  # noqa: BLE001 - any Tk startup failure means no display
        return False
    root.destroy()
    return True


@unittest.skipUnless(_display_available(), "Tk display not available (run under xvfb-run or a desktop session)")
class NavigationFlowTests(unittest.TestCase):
    """Drive the real Tk views through the three handoff flows."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(ROOT / "catalog")

    def setUp(self):
        import tkinter as tk
        from hd2lib.gui import HD2PlannerApp

        self.temporary = tempfile.TemporaryDirectory()
        self.paths = UserDataPaths(Path(self.temporary.name) / "data").initialize()
        self.service = PlannerService(paths=self.paths, catalog=self.catalog)
        self.service.create_profile("Flow Tester", "Main", "PC", 12)
        self.root = tk.Tk()
        self.errors: list[str] = []
        self.root.report_callback_exception = lambda *exc: self.errors.append(repr(exc))
        self.app = HD2PlannerApp(self.root, self.service)
        self.root.update()

    def tearDown(self):
        self.app.shutdown()
        self.root.destroy()
        self.temporary.cleanup()
        self.assertEqual(self.errors, [])

    def pump(self):
        self.root.update()

    def test_ship_management_flow_support_weapon_then_ship_modules(self):
        app = self.app
        app.open_terminal("ship_management"); self.pump()
        self.assertEqual(app.current_view, "stratagems")
        self.assertEqual(app.current_location.breadcrumb(), "Ship Management › Stratagems")
        self.assertEqual(app.nav_terminal_buttons["ship_management"].cget("style"), "ActiveRailTerminal.TButton")
        self.assertEqual(app.nav_buttons["stratagems"][0].cget("style"), "ActiveRailTab.TButton")
        stratagem = next(row for row in app.visible_rows if row.group == "support_weapon")
        app.search_var.set(stratagem.name[:5]); app._refresh_inventory(); self.pump()
        app.inventory_tree.selection_set(stratagem.item_id); app._inventory_selection_changed(); self.pump()
        weapon_id = self.service.support_weapon_for_stratagem(stratagem.item_id)
        app.open_linked_item("support_weapons", weapon_id); self.pump()
        self.assertEqual(app.current_view, "support_weapons")
        self.assertEqual(app.current_location.breadcrumb(), "Ship Management › Stratagems › Support weapon records")
        self.assertEqual(app._selected_ids(), [weapon_id])
        self.assertEqual(app.back_button.cget("text"), "← Back to Stratagems")
        app.go_back(); self.pump()
        self.assertEqual(app.current_view, "stratagems")
        self.assertEqual(app.search_var.get(), stratagem.name[:5], "search filter must survive Back")
        self.assertEqual(app._selected_ids(), [stratagem.item_id], "selection must survive Back")
        self.assertEqual(app._history, [])
        app.open_tab("ship_modules"); self.pump()
        self.assertEqual(app.current_location.breadcrumb(), "Ship Management › Ship Modules")
        self.assertIn("Patriotic Administration Center", app._group_ids)
        self.assertEqual(len(app.visible_rows), len(self.service.inventory_rows("ship_modules")))

    def test_acquisition_center_flow_reward_edit_round_trip(self):
        app = self.app
        app.open_terminal("acquisition_center"); self.pump()
        self.assertEqual(app.current_location.breadcrumb(), "Acquisition Center › Warbonds")
        app.status_var.set("Unreviewed"); app.search_var.set("cutting"); app._refresh_inventory(); self.pump()
        app.inventory_tree.selection_set("cutting_edge"); app._inventory_selection_changed(); self.pump()
        app.open_warbond("cutting_edge"); self.pump()
        self.assertEqual(app.current_view, "warbond_contents")
        self.assertEqual(app.current_location.breadcrumb(), "Acquisition Center › Warbonds › Cutting Edge")
        headings = [app.warbond_tree.item(iid, "values")[2] for iid in app.warbond_tree.get_children() if str(iid).startswith("group-")]
        self.assertTrue(headings and headings[0].startswith("Page 1"), headings)
        reward = next(row for row in app._warbond_rows().values() if row.category == "primary_weapons")
        app.warbond_tree.selection_set(reward.item_id); self.pump()
        app._set_warbond_reward_status(reward, "unlocked"); self.pump()
        self.assertEqual(self.service.inventory_status("primary_weapons", reward.item_id), "unlocked")
        self.assertEqual(self.service.inventory_status("warbonds", "cutting_edge"), "unknown", "reward edit must not change Warbond ownership")
        self.assertEqual(app.warbond_tree.selection(), (reward.item_id,), "inspected reward stays selected after the edit")
        app.open_linked_item("primary_weapons", reward.item_id, warbond_context="cutting_edge"); self.pump()
        self.assertEqual(app.current_location.breadcrumb(), "Armory › Primary")
        self.assertEqual(app.warbond_var.get(), "Cutting Edge")
        self.assertEqual(app._selected_ids(), [reward.item_id])
        self.assertTrue(app.inventory_tree.item(reward.item_id, "values")[0].endswith("Owned"), "inventory view reads the same ownership record")
        self.assertEqual(app.back_button.cget("text"), "← Back to Cutting Edge")
        app.go_back(); self.pump()
        self.assertEqual(app.current_view, "warbond_contents")
        self.assertEqual(app.warbond_tree.selection(), (reward.item_id,))
        app.go_back(); self.pump()
        self.assertEqual(app.current_view, "warbonds")
        self.assertEqual((app.search_var.get(), app.status_var.get()), ("cutting", "Unreviewed"))
        self.assertEqual(app._selected_ids(), ["cutting_edge"])

    def test_armory_flow_customization_stays_scoped_to_one_weapon(self):
        app = self.app
        weapon, sibling = "sg_225_breaker", "sg_225ie_breaker_incendiary"
        app.open_terminal("armory"); self.pump()
        self.assertEqual(app.current_location.breadcrumb(), "Armory › Primary")
        app.inventory_tree.selection_set(weapon); app._inventory_selection_changed(); self.pump()
        app.open_weapon_customization("primary_weapons", weapon); self.pump()
        self.assertEqual(app.current_view, "weapon_customization")
        self.assertEqual(app.current_location.breadcrumb(), "Armory › Primary › Customize · SG-225 Breaker")
        attachment = next(iid for iid in app.customization_tree.get_children() if not str(iid).startswith("slot-"))
        self.assertIn(sibling, self.service.index[attachment]["facts"]["compatible_weapon_ids"])
        app._set_attachment_status(attachment, "unlocked"); self.pump()
        self.assertEqual(self.service.attachment_status(weapon, attachment), "unlocked")
        self.assertEqual(self.service.attachment_status(sibling, attachment), "unknown")
        self.assertEqual(self.service.character().get("inventory", {}).get("weapon_attachments", {}), {}, "no global attachment answer is written")
        self.assertIn("1 of", app.customization_summary_var.get())
        app._undo_inventory_change(); self.pump()
        self.assertEqual(self.service.attachment_status(weapon, attachment), "unknown")
        app.go_back(); self.pump()
        self.assertEqual(app.current_view, "primary_weapons")
        self.assertEqual(app._selected_ids(), [weapon])

    def test_tab_switch_clears_history_and_planner_area_is_separate(self):
        app = self.app
        app.open_warbond("cutting_edge"); self.pump()
        self.assertEqual(len(app._history), 1)
        app.open_tab("armor"); self.pump()
        self.assertEqual(app._history, [])
        self.assertFalse(hasattr(app, "back_button") and app.back_button.winfo_exists())
        for tab in ("preferences", "observations", "loadouts", "context_export"):
            app.open_tab(tab); self.pump()
            self.assertEqual(app.current_location.terminal.id, "planner")
        app._toggle_nav(); self.pump()
        self.assertEqual(app.nav_terminal_buttons["planner"].cget("text"), "PL")
        app._toggle_nav(); self.pump()
        self.assertEqual(app.nav_terminal_buttons["planner"].cget("text"), "›  Planner")


if __name__ == "__main__":
    unittest.main()
