from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import urllib.request
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from hd2lib.catalog import CatalogError, catalog_hash, compare_catalogs, load_catalog
from hd2lib.cli import run
from hd2lib.exporter import build_context, context_markdown, export_context, validate_generated
from hd2lib.loadout import validate_for_character
from hd2lib.onboarding import items_for_inventory_category, setup_profile
from hd2lib.packaging import build_package
from hd2lib.profile import add_character, effective_preferences, import_profile, new_profile, validate_profile
from hd2lib.storage import read_json, write_json
from importer.normalize import parse_currency, split_traits


ROOT = Path(__file__).resolve().parent.parent


class FoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(ROOT / "catalog")

    def profile(self):
        profile = new_profile("tester", "Tester")
        add_character(profile, "pc", "PC", 10)
        add_character(profile, "xbox", "Xbox", 1)
        return profile

    def test_multiple_characters_have_independent_inventories(self):
        profile = self.profile()
        profile["characters"]["pc"]["inventory"]["primary_weapons"]["sg_225_breaker"] = {"status": "unlocked"}
        self.assertNotIn("sg_225_breaker", profile["characters"]["xbox"]["inventory"]["primary_weapons"])

    def test_player_preferences_inherit(self):
        profile = self.profile()
        profile["preferences"]["item_preferences"]["sg_225_breaker"] = "favorite"
        self.assertEqual(effective_preferences(profile, "pc")["item_preferences"]["sg_225_breaker"], "favorite")

    def test_character_preference_overrides(self):
        profile = self.profile()
        profile["preferences"]["item_preferences"]["sg_225_breaker"] = "favorite"
        profile["characters"]["xbox"]["preference_overrides"]["item_preferences"]["sg_225_breaker"] = "avoid"
        self.assertEqual(effective_preferences(profile, "xbox")["item_preferences"]["sg_225_breaker"], "avoid")
        self.assertEqual(effective_preferences(profile, "pc")["item_preferences"]["sg_225_breaker"], "favorite")

    def test_unlock_states_remain_distinct(self):
        profile = self.profile()
        inventory = profile["characters"]["pc"]["inventory"]["primary_weapons"]
        inventory.update({"sg_225_breaker": {"status": "unlocked"}, "ar_23_liberator": {"status": "locked"}, "ar_11_arbitrator": {"status": "unknown"}})
        self.assertEqual({entry["status"] for entry in inventory.values()}, {"unknown", "locked", "unlocked"})

    def test_valid_profile_validates(self):
        profile = self.profile()
        self.assertEqual(validate_profile(profile, self.catalog), [])

    def test_invalid_item_id_is_detected(self):
        profile = self.profile()
        profile["characters"]["pc"]["inventory"]["primary_weapons"]["not_real"] = {"status": "unlocked"}
        self.assertTrue(any("invalid item id" in error for error in validate_profile(profile, self.catalog)))

    def test_profile_rejects_helmet_in_armor_inventory(self):
        profile = self.profile()
        helmet = next(item for item in self.catalog["collections"]["armor"] if item["facts"].get("equipment_slot") == "helmet")
        profile["characters"]["pc"]["inventory"]["armor"][helmet["id"]] = {"status": "unlocked"}
        self.assertTrue(any("is not body armor" in error for error in validate_profile(profile, self.catalog)))

    def test_profile_rejects_non_equippable_stratagem(self):
        profile = self.profile()
        profile["characters"]["pc"]["inventory"]["stratagems"]["stratagem_hellbomb"] = {"status": "unlocked"}
        self.assertTrue(any("not a player-equippable stratagem" in error for error in validate_profile(profile, self.catalog)))

    def test_loadout_validation_catches_unavailable(self):
        profile = self.profile()
        character = profile["characters"]["pc"]
        character["inventory"]["primary_weapons"]["sg_225_breaker"] = {"status": "locked"}
        character["inventory"]["secondary_weapons"]["p_2_peacemaker"] = {"status": "unknown"}
        loadout = {"id": "test", "name": "Test", "primary": "sg_225_breaker", "secondary": "p_2_peacemaker", "grenade": None, "armor": None, "booster": None, "stratagems": []}
        result = validate_for_character(loadout, character, self.catalog)
        self.assertEqual(result["missing"][0]["id"], "sg_225_breaker")
        self.assertEqual(result["unknown"][0]["id"], "p_2_peacemaker")

    def test_loadout_validation_enforces_slot_semantics(self):
        profile = self.profile()
        loadout = {"id": "test", "name": "Test", "primary": "p_2_peacemaker", "secondary": None, "grenade": None, "armor": None, "booster": None, "stratagems": ["stratagem_hellbomb", "stratagem_hellbomb"]}
        errors = validate_for_character(loadout, profile["characters"]["pc"], self.catalog)["errors"]
        self.assertTrue(any("primary slot" in error for error in errors))
        self.assertTrue(any("duplicate" in error for error in errors))
        self.assertTrue(any("player-equippable" in error for error in errors))

    def test_generated_markdown_reflects_canonical_json(self):
        profile = self.profile()
        profile["characters"]["pc"]["inventory"]["primary_weapons"]["sg_225_breaker"] = {"status": "unlocked"}
        context = build_context(profile, "pc", self.catalog)
        markdown = context_markdown(context)
        self.assertIn("SG-225 Breaker (`sg_225_breaker`) | unlocked", markdown)
        self.assertEqual(context["inventory"]["primary_weapons"][0]["status"], "unlocked")

    def test_generated_file_becomes_stale_after_profile_change(self):
        profile = self.profile()
        with tempfile.TemporaryDirectory() as temporary:
            json_path, _ = export_context(profile, "pc", self.catalog, Path(temporary))
            self.assertTrue(validate_generated(json_path, profile, self.catalog)["valid"])
            profile["characters"]["pc"]["level"] = 11
            result = validate_generated(json_path, profile, self.catalog)
            self.assertTrue(result["stale"])
            self.assertIn("profile_hash", result["stale_reasons"])

    def test_export_context_cli_accepts_valid_profile(self):
        profile = self.profile()
        with tempfile.TemporaryDirectory() as temporary, patch("hd2lib.cli._profile", return_value=(Path("profile.json"), profile)), patch("hd2lib.cli.load_catalog", return_value=self.catalog):
            output = Path(temporary) / "generated"
            stdout = StringIO()
            with redirect_stdout(stdout):
                status = run(["export-context", "--player", "tester", "--character", "pc", "--output", str(output)])
            self.assertEqual(status, 0)
            self.assertTrue((output / "tester" / "pc-context.json").exists())
            self.assertTrue((output / "tester" / "pc-context.md").exists())
            self.assertIn("Generated:", stdout.getvalue())

    def test_export_context_cli_rejects_invalid_profile_before_writing(self):
        profile = self.profile()
        profile["characters"]["pc"]["inventory"]["stratagems"]["stratagem_hellbomb"] = {"status": "unlocked"}
        with tempfile.TemporaryDirectory() as temporary, patch("hd2lib.cli._profile", return_value=(Path("profile.json"), profile)), patch("hd2lib.cli.load_catalog", return_value=self.catalog):
            output = Path(temporary) / "generated"
            stderr = StringIO()
            with redirect_stderr(stderr):
                status = run(["export-context", "--player", "tester", "--character", "pc", "--output", str(output)])
            self.assertEqual(status, 1)
            self.assertFalse(output.exists())
            self.assertIn("Export rejected; no files created", stderr.getvalue())
            self.assertIn("not a player-equippable stratagem", stderr.getvalue())

    def test_onboarding_import_validates_before_modifying(self):
        profile = self.profile()
        profile["characters"]["pc"]["inventory"]["primary_weapons"]["fake"] = {"status": "unlocked"}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            candidate = directory / "candidate.json"
            write_json(candidate, profile)
            output = directory / "profiles"
            output.mkdir()
            with self.assertRaises(ValueError):
                import_profile(candidate, output, self.catalog)
            self.assertEqual(list(output.iterdir()), [])

    def test_catalog_provenance_survives_loading(self):
        item = next(item for item in self.catalog["collections"]["weapons"] if item["id"] == "mg_43_machine_gun")
        source = item["provenance"][0]
        self.assertEqual(source["source"], "helldivers_wiki")
        self.assertIsInstance(source["revision_id"], int)

    def test_catalog_manifest_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "catalog"
            shutil.copytree(ROOT / "catalog", directory)
            weapons_path = directory / "weapons.json"
            weapons = read_json(weapons_path)
            weapons["items"][0]["name"] = "Tampered"
            write_json(weapons_path, weapons)
            with self.assertRaises(CatalogError):
                load_catalog(directory)

    def test_normalized_relationships_are_explicit(self):
        index = {item["id"]: item for items in self.catalog["collections"].values() for item in items}
        autocannon = index["stratagem_ac_8_autocannon"]
        self.assertEqual(autocannon["facts"]["support_weapon_id"], "ac_8_autocannon")
        self.assertTrue(autocannon["facts"]["occupies_backpack_slot"])
        self.assertEqual(index["advanced_construction"]["facts"]["prerequisite_module_id"], "synthetic_supplementation")
        self.assertIn("sg_225_breaker", index["drum_magazine"]["facts"]["compatible_weapon_ids"])

    def test_mission_only_stratagems_are_not_equippable(self):
        index = {item["id"]: item for item in self.catalog["collections"]["stratagems"]}
        self.assertFalse(index["stratagem_hellbomb"]["facts"]["player_equippable"])
        self.assertTrue(index["stratagem_eagle_airstrike"]["facts"]["player_equippable"])

    def test_armor_onboarding_lists_only_body_armor(self):
        shown = items_for_inventory_category(self.catalog, "armor")
        expected = [item for item in self.catalog["collections"]["armor"] if item["facts"].get("equipment_slot") == "body_armor"]
        self.assertEqual({item["id"] for item in shown}, {item["id"] for item in expected})
        self.assertFalse(any(item["facts"].get("equipment_slot") == "helmet" for item in shown))

    def test_stratagem_onboarding_lists_only_player_equippable_records(self):
        shown = items_for_inventory_category(self.catalog, "stratagems")
        expected = [item for item in self.catalog["collections"]["stratagems"] if item["facts"].get("player_equippable") is True]
        self.assertEqual({item["id"] for item in shown}, {item["id"] for item in expected})
        self.assertNotIn("stratagem_hellbomb", {item["id"] for item in shown})

    def test_weapon_onboarding_retains_category_and_warbond_filters(self):
        candidate = next(item for item in self.catalog["collections"]["weapons"] if item["facts"].get("category") == "primary" and item["facts"].get("warbond_id"))
        warbond = candidate["facts"]["warbond_id"]
        shown = items_for_inventory_category(self.catalog, "primary_weapons", warbond)
        expected = [item for item in self.catalog["collections"]["weapons"] if item["facts"].get("category") == "primary" and item["facts"].get("warbond_id") == warbond]
        self.assertEqual({item["id"] for item in shown}, {item["id"] for item in expected})

    def test_setup_item_quit_stops_and_preserves_partial_category(self):
        answers = iter(["Tester", "tester", "pc", "PC", "1", "n", "y", "u", "q"])

        def ask(_: str) -> str:
            try:
                return next(answers)
            except StopIteration:
                raise AssertionError("setup continued after item-level quit")

        with tempfile.TemporaryDirectory() as temporary:
            path = setup_profile(self.catalog, Path(temporary), ask=ask, tell=lambda _: None)
            profile = read_json(path)
        character = profile["characters"]["pc"]
        self.assertEqual(len(character["inventory"]["warbonds"]), 1)
        self.assertNotIn("warbonds", character["onboarding"]["completed_sections"])
        self.assertNotIn("warbonds", character["onboarding"]["skipped_sections"])

    def test_normalization_helpers_do_not_require_wiki_prose(self):
        self.assertEqual(split_traits("Explosive &nbsp;&bull;&nbsp; Anti-Tank"), ["Explosive", "Anti-Tank"])
        self.assertEqual(parse_currency('[[File:Medal.svg]] 1,200 [[Medal]]s'), {"currency": "medals", "amount": 1200})

    def test_planner_tags_state_provenance_kind(self):
        for items in self.catalog["collections"].values():
            for item in items:
                for tag in item.get("planner_tags", []):
                    self.assertIn(tag["provenance_kind"], {"imported", "derived", "manually_curated"})

    def test_planner_fixture_matches_normalized_catalog(self):
        fixture = read_json(ROOT / "tests" / "fixtures" / "planner_readiness.json")
        self.assertEqual(fixture["source_catalog_version"], self.catalog["manifest"]["catalog_version"])
        index = {item["id"]: item for items in self.catalog["collections"].values() for item in items}
        entries = []
        entries.extend(fixture["equipment"]["primaries"])
        entries.extend(fixture["equipment"]["secondaries"])
        entries.extend(fixture["equipment"]["grenades"])
        entries.extend(fixture["stratagems"])
        entries.extend(fixture["missions"])
        for entry in entries:
            self.assertIn(entry["id"], index)
            for key, expected in entry["expected"].items():
                self.assertEqual(index[entry["id"]]["facts"].get(key), expected)
        for faction, enemy_ids in fixture["enemies"].items():
            for enemy_id in enemy_ids:
                self.assertEqual(index[enemy_id]["facts"].get("faction_id"), faction)
        warbond = index[fixture["warbond_progression"]["warbond_id"]]
        self.assertEqual(warbond["facts"]["purchase_cost"], fixture["warbond_progression"]["purchase_cost"])
        for reward in fixture["warbond_progression"]["representative_rewards"]:
            facts = index[reward["id"]]["facts"]
            self.assertEqual(facts["warbond_id"], fixture["warbond_progression"]["warbond_id"])
            self.assertEqual(facts["warbond_page"], reward["page"])
            self.assertEqual(facts["unlock_cost_normalized"], {"currency": "medals", "amount": reward["medal_cost"]})

    def test_mechanical_constraints_are_explicit(self):
        document = read_json(ROOT / "planner" / "constraints.json")
        constraints = {item["id"]: item for item in document["constraints"]}
        self.assertEqual(constraints["four_distinct_stratagems"]["maximum"], 4)
        self.assertEqual(constraints["one_backpack_slot"]["capacity"], 1)
        self.assertEqual(constraints["armor_passive_is_armor_property"]["source_fact"], "passive_id")

    def test_catalog_comparison_finds_added_changed_removed(self):
        old = {"manifest": {"schema_version": "1.0.0"}, "collections": {"weapons": [{"id": "a", "name": "A", "facts": {}, "provenance": []}, {"id": "b", "name": "B", "facts": {}, "provenance": []}]}}
        new = {"manifest": {"schema_version": "1.0.0"}, "collections": {"weapons": [{"id": "a", "name": "A2", "facts": {}, "provenance": []}, {"id": "c", "name": "C", "facts": {}, "provenance": []}]}}
        diff = compare_catalogs(old, new)
        self.assertEqual(diff["changed"], ["a"])
        self.assertEqual(diff["added"], ["c"])
        self.assertEqual(diff["removed"], ["b"])

    def test_packaging_excludes_private_profiles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"; root.mkdir()
            for name in ("hd2.py", "hd2_gui.py", ".python-version", "README.md", "LICENSE", "LICENSE_OR_ATTRIBUTION.md", "CHANGELOG.md", "pyproject.toml"):
                (root / name).write_text(name, encoding="utf-8")
            (root / "profiles" / "loadouts").mkdir(parents=True)
            (root / "profiles" / "example_player.json").write_text("{}", encoding="utf-8")
            (root / "profiles" / "private_alex.json").write_text("{}", encoding="utf-8")
            (root / "generated" / "alex").mkdir(parents=True)
            (root / "generated" / "alex" / "context.json").write_text("{}", encoding="utf-8")
            destination = Path(temporary) / "out"
            archive = build_package(destination, root)
            with zipfile.ZipFile(archive) as zipped:
                names = zipped.namelist()
            self.assertTrue(any(name.endswith("profiles/example_player.json") for name in names))
            self.assertTrue(any(name.endswith("hd2_gui.py") for name in names))
            self.assertTrue(any(name.endswith(".python-version") for name in names))
            self.assertFalse(any("private_alex" in name for name in names))
            self.assertFalse(any("generated/alex/context.json" in name for name in names))

    def test_offline_context_operation_never_uses_network(self):
        profile = self.profile()
        with patch.object(urllib.request, "urlopen", side_effect=AssertionError("network used")):
            catalog = load_catalog(ROOT / "catalog")
            context = build_context(profile, "pc", catalog)
        self.assertEqual(context["player"]["id"], "tester")


if __name__ == "__main__":
    unittest.main()
