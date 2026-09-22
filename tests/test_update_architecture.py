from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from hd2lib.catalog import load_catalog
from hd2lib.cli import run
from hd2lib.data import UserDataPaths, resolve_data_dir
from hd2lib.local_data import migrate_local_data
from hd2lib.migrations import migrate_profile_file
from hd2lib.profile import add_character, new_profile, save_profile
from hd2lib.storage import read_json, write_json
from hd2lib.update import check_for_update, is_newer

ROOT = Path(__file__).resolve().parent.parent


class _Response(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *args): self.close()


class UpdateArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(ROOT / "catalog")

    def profile(self):
        value = new_profile("alex", "Alex"); add_character(value, "pc", "PC", 1)
        return value

    def test_data_dir_resolution_by_platform_and_override(self):
        home = Path("/home/tester")
        self.assertEqual(resolve_data_dir(platform="darwin", home=home, environ={}), home / "Library/Application Support/HD2 Planner")
        self.assertEqual(resolve_data_dir(platform="linux", home=home, environ={}), home / ".local/share/hd2-planner")
        self.assertEqual(resolve_data_dir(platform="linux", home=home, environ={"XDG_DATA_HOME": "/xdg"}), Path("/xdg/hd2-planner"))
        self.assertEqual(resolve_data_dir(platform="win32", home=home, environ={"APPDATA": "C:/Users/test/AppData/Roaming"}), Path("C:/Users/test/AppData/Roaming/HD2 Planner"))
        self.assertEqual(resolve_data_dir(environ={"HD2_PLANNER_DATA_DIR": "/custom"}), Path("/custom"))

    def test_initialize_creates_all_persistent_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = UserDataPaths(Path(temporary) / "data").initialize()
            self.assertTrue(all(path.is_dir() for path in (paths.profiles, paths.loadouts, paths.generated, paths.backups, paths.migrations)))

    def test_version_command_reports_independent_versions(self):
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(run(["version"]), 0)
        self.assertIn("HD2 Planner 0.5.0", output.getvalue())
        self.assertIn("Catalog 2026.09.21.2", output.getvalue())
        self.assertIn("Profile schema 1.1.0", output.getvalue())

    def test_profile_and_generated_use_external_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = UserDataPaths(Path(temporary)).initialize(); profile = self.profile()
            path = paths.profiles / "alex.json"; save_profile(path, profile)
            from hd2lib.exporter import export_context
            generated, _ = export_context(profile, "pc", self.catalog, paths.generated)
            self.assertTrue(path.exists()); self.assertTrue(generated.is_relative_to(paths.generated))

    def test_update_check_newer_equal_and_network_failure(self):
        payload = json.dumps({"tag_name": "v0.6.0", "html_url": "https://github.com/oidevo/HD2-planner/releases/tag/v0.6.0"}).encode()
        with patch("urllib.request.urlopen", return_value=_Response(payload)):
            result = check_for_update(); self.assertTrue(result.available); self.assertEqual(result.latest, "0.6.0")
        payload = json.dumps({"tag_name": "v0.5.0", "html_url": "https://example.test/release"}).encode()
        with patch("urllib.request.urlopen", return_value=_Response(payload)):
            self.assertFalse(check_for_update().available)
        with patch("urllib.request.urlopen", side_effect=OSError("offline")):
            result = check_for_update(); self.assertIsNotNone(result.error); self.assertFalse(result.available)
        self.assertTrue(is_newer("1.0.0", "1.0.0-rc.1"))
        self.assertFalse(is_newer("1.0.0-rc.2", "1.0.0"))

    def test_supported_migration_creates_backup_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = UserDataPaths(Path(temporary)).initialize(); path = paths.profiles / "alex.json"
            old = self.profile(); old["schema_version"] = "0.9.0"; old.pop("progression_notes")
            write_json(path, old)
            backup = migrate_profile_file(path, self.catalog, paths)
            self.assertIsNotNone(backup); self.assertTrue(backup.exists())
            self.assertEqual(read_json(path)["schema_version"], "1.1.0")
            self.assertIsNone(migrate_profile_file(path, self.catalog, paths))

    def test_failed_migration_leaves_original_recoverable(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = UserDataPaths(Path(temporary)).initialize(); path = paths.profiles / "bad.json"
            write_json(path, {"schema_version": "0.9.0", "player": {}})
            with self.assertRaises(ValueError): migrate_profile_file(path, self.catalog, paths)
            self.assertEqual(read_json(path)["schema_version"], "0.9.0")

    def test_legacy_import_copies_without_overwrite_or_delete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "app"; (root / "profiles/loadouts").mkdir(parents=True); (root / "generated/alex").mkdir(parents=True)
            (root / "profiles/alex.json").write_text("{}", encoding="utf-8")
            (root / "profiles/example_player.json").write_text("{}", encoding="utf-8")
            (root / "profiles/loadouts/a.json").write_text("{}", encoding="utf-8")
            (root / "generated/alex/context.json").write_text("{}", encoding="utf-8")
            paths = UserDataPaths(Path(temporary) / "data").initialize()
            first = migrate_local_data(root, paths); second = migrate_local_data(root, paths)
            self.assertTrue((paths.profiles / "alex.json").exists())
            self.assertFalse((paths.profiles / "example_player.json").exists())
            self.assertTrue((root / "profiles/alex.json").exists())
            self.assertGreaterEqual(len(first.copied), 3); self.assertGreaterEqual(len(second.skipped), 3)
