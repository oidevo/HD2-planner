from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from hd2lib.appearance import DARK_TOKENS, LIGHT_TOKENS, load_appearance, save_appearance, semantic_tokens, system_appearance
from hd2lib.catalog import catalog_index, load_catalog
from hd2lib.gui import BULK_UNREVIEWED_LABEL, bulk_confirmation_copy
from hd2lib.presentation import inspector_facts
from hd2lib.presentation_order import PresentationOrderError, load_presentation_order, sort_with_presentation_order
from hd2lib.packaging import build_package
from hd2lib.storage import write_json


ROOT = Path(__file__).resolve().parent.parent


class AppearanceTests(unittest.TestCase):
    def test_default_and_persistent_appearance_choice(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            self.assertEqual(load_appearance(path), "System")
            save_appearance(path, "Dark")
            self.assertEqual(load_appearance(path), "Dark")
            self.assertEqual(json.loads(path.read_text())["appearance"], "Dark")

    def test_semantic_tokens_cover_every_required_surface(self):
        required = {"canvas", "rail", "card", "inspector", "dialog", "text", "muted_text", "divider", "selection", "selection_text", "input", "input_text", "heading", "button", "button_text", "menu", "menu_text", "disabled", "error", "unlocked", "locked", "unknown", "accent"}
        for tokens in (LIGHT_TOKENS, DARK_TOKENS):
            self.assertTrue(required <= tokens.keys())
        self.assertEqual(semantic_tokens("Dark")["text"], DARK_TOKENS["text"])

    def test_macos_system_appearance_detection(self):
        completed = type("Result", (), {"returncode": 0, "stdout": "Dark\n"})()
        with patch("hd2lib.appearance.subprocess.run", return_value=completed) as run:
            self.assertEqual(system_appearance(platform="darwin"), "Dark")
        run.assert_called_once_with(["/usr/bin/defaults", "read", "-g", "AppleInterfaceStyle"], text=True, capture_output=True, check=False)


class InspectorPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(ROOT / "catalog")

    def test_current_warbond_raw_markup_is_never_presented(self):
        item = self.catalog["collections"]["warbonds"][0]
        self.assertIn("[[", item["facts"]["cost"])
        rendered = inspector_facts("warbonds", item["facts"])
        display = "\n".join(f"{label}: {value}" for label, value in rendered)
        self.assertIn("Purchase cost", display)
        for marker in ("[[", "]]", "<span", "File:", "&nbsp;"):
            self.assertNotIn(marker, display)

    def test_questionable_non_normalized_fields_are_omitted_not_cleaned(self):
        facts = {"source": "[[Unsafe]]", "type": "<b>Unsafe</b>", "category": "primary", "warbond_page": 2}
        self.assertEqual(inspector_facts("primary_weapons", facts), [("Category", "Primary"), ("Warbond page", "2")])


class BulkCopyTests(unittest.TestCase):
    def test_unreviewed_label_and_exact_confirmation_copy(self):
        self.assertEqual(BULK_UNREVIEWED_LABEL, "Mark unreviewed visible items as locked…")
        heading, message = bulk_confirmation_copy(7, "locked", True)
        self.assertIn("7 unreviewed visible", heading)
        self.assertIn("Locked", heading)
        self.assertIn("Exactly 7", message)
        self.assertIn("does not block", message)


class PresentationOrderTests(unittest.TestCase):
    def document(self) -> dict:
        return {
            "schema_version": "1.0.0", "source_catalog_version": "test.1",
            "capture": {"captured_at": "2026-09-22", "game_build": "test", "evidence_references": ["capture-1"]},
            "screens": [{"id": "armory", "heading": "Armory", "verification": "partial", "groups": [
                {"id": "primary", "heading": "Primary", "categories": ["primary_weapons"], "verification": "verified", "item_ids": ["b", "a"]},
                {"id": "secondary", "heading": "Secondary", "categories": ["secondary_weapons"], "verification": "unverified", "item_ids": []},
            ]}],
        }

    def test_stable_id_group_and_fallback_ordering(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "order.json"; write_json(path, self.document())
            order = load_presentation_order(path, catalog_version="test.1", known_item_ids={"a", "b", "c", "z"})
            values = [("z", "secondary", "Zulu"), ("c", "primary", "Charlie"), ("a", "primary", "Alpha"), ("b", "primary", "Beta")]
            sorted_values = sort_with_presentation_order(values, order, "armory", item_id=lambda value: value[0], group_id=lambda value: value[1], fallback=lambda value: (value[2].casefold(), value[0]))
            self.assertEqual([value[0] for value in sorted_values], ["b", "a", "c", "z"])
            self.assertIn("fallback order", order.verification_message("armory"))

    def test_catalog_version_and_unknown_ids_are_validated(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "order.json"; write_json(path, self.document())
            with self.assertRaisesRegex(PresentationOrderError, "does not match"):
                load_presentation_order(path, catalog_version="test.2", known_item_ids={"a", "b"})
            with self.assertRaisesRegex(PresentationOrderError, "unknown stable IDs"):
                load_presentation_order(path, catalog_version="test.1", known_item_ids={"a"})

    def test_packaged_document_links_to_current_catalog(self):
        catalog = load_catalog(ROOT / "catalog")
        order = load_presentation_order(catalog_version=catalog["manifest"]["catalog_version"], known_item_ids=set(catalog_index(catalog)))
        self.assertEqual(order.source_catalog_version, catalog["manifest"]["catalog_version"])

    def test_ordinary_package_includes_presentation_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = build_package(Path(temporary), ROOT)
            with zipfile.ZipFile(archive) as package:
                self.assertTrue(any(name.endswith("planner/presentation_order.json") for name in package.namelist()))


if __name__ == "__main__":
    unittest.main()
