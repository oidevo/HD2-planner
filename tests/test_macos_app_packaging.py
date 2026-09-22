from __future__ import annotations

import os
import plistlib
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from hd2lib.data import resolve_data_dir
from hd2lib.packaging import (
    EMBEDDED_PYTHON_VERSION,
    EMBEDDED_TK_VERSION,
    MACOS_ARCHITECTURE,
    MACOS_BUNDLE_IDENTIFIER,
    MACOS_BUNDLE_NAME,
    MACOS_MINIMUM_SYSTEM_VERSION,
    PYINSTALLER_VERSION,
    build_macos_app_archive,
    machine_specific_reference_violations,
    macos_binary_dependency_violations,
    macos_bundle_errors,
    private_payload_violations,
)
from hd2lib.resources import resource_root


ROOT = Path(__file__).resolve().parent.parent


class MacOSAppPackagingTests(unittest.TestCase):
    def make_bundle(self, parent: Path) -> Path:
        bundle = parent / MACOS_BUNDLE_NAME
        executable = bundle / "Contents" / "MacOS" / "HD2 Planner"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"fake Mach-O")
        executable.chmod(0o755)
        metadata = {
            "CFBundleDisplayName": "HD2 Planner",
            "CFBundleIdentifier": MACOS_BUNDLE_IDENTIFIER,
            "CFBundleShortVersionString": "1.2.3",
            "CFBundleVersion": "1.2.3",
            "LSMinimumSystemVersion": MACOS_MINIMUM_SYSTEM_VERSION,
            "LSArchitecturePriority": [MACOS_ARCHITECTURE],
            "HD2EmbeddedPythonVersion": EMBEDDED_PYTHON_VERSION,
            "HD2EmbeddedTkVersion": EMBEDDED_TK_VERSION,
            "HD2PyInstallerVersion": PYINSTALLER_VERSION,
        }
        with (bundle / "Contents" / "Info.plist").open("wb") as stream:
            plistlib.dump(metadata, stream)
        resources = bundle / "Contents" / "Resources"
        for relative in (
            "catalog/catalog_manifest.json",
            "schemas/profile.schema.json",
            "planner/rules.json",
            "planner/presentation_order.json",
            "onboarding/LOCAL_SETUP.md",
            "VERSION",
            "LICENSE",
            "LICENSE_OR_ATTRIBUTION.md",
            "examples/profiles/example_player.json",
            "licenses/python/LICENSE.txt",
            "licenses/tcl/license.terms",
            "licenses/tk/license.terms",
            "licenses/pyinstaller/COPYING.txt",
            "tcl9.0/init.tcl",
        ):
            path = resources / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative, encoding="utf-8")
        for relative in (
            "Frameworks/Python.framework/Versions/3.14/Python",
            "Frameworks/_tkinter.cpython-314-darwin.so",
            "Frameworks/libtcl9.0.dylib",
        ):
            path = bundle / "Contents" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"runtime")
        return bundle

    def test_bundle_layout_metadata_runtime_resources_and_privacy(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = self.make_bundle(Path(temporary))
            completed = subprocess.CompletedProcess([], 0, stdout="arm64\n", stderr="")
            with patch("hd2lib.packaging.subprocess.run", return_value=completed), patch(
                "hd2lib.packaging.macos_binary_dependency_violations", return_value=[]
            ):
                self.assertEqual(macos_bundle_errors(bundle, expected_version="1.2.3"), [])

    def test_bundle_rejects_private_data_and_external_runtime_dependencies(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = self.make_bundle(Path(temporary))
            private = bundle / "Contents" / "Resources" / "profiles" / "alex.json"
            private.parent.mkdir(parents=True)
            private.write_text("private", encoding="utf-8")
            self.assertIn("Contents/Resources/profiles/alex.json", private_payload_violations(bundle))

            machine_path = bundle / "Contents" / "Resources" / "compiler.txt"
            machine_path.write_text("/Users/alice/build/project", encoding="utf-8")
            self.assertEqual(
                machine_specific_reference_violations(bundle),
                ["Contents/Resources/compiler.txt: contains /Users/"],
            )

    def test_archive_name_and_modes_are_apple_silicon_specific(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            bundle = self.make_bundle(temporary_path)
            root = temporary_path / "source"
            root.mkdir()
            (root / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            archive = build_macos_app_archive(bundle, temporary_path, root)
            self.assertEqual(archive.name, "hd2-planner-1.2.3-macos-arm64.zip")
            with zipfile.ZipFile(archive) as zipped:
                executable = zipped.getinfo("HD2 Planner.app/Contents/MacOS/HD2 Planner")
                mode = executable.external_attr >> 16
                self.assertTrue(mode & stat.S_IXUSR)
                names = zipped.namelist()
            self.assertFalse(any("profiles/alex" in name or "__pycache__" in name for name in names))

    def test_frozen_and_source_resource_resolution(self):
        self.assertEqual(resource_root(), ROOT)
        with tempfile.TemporaryDirectory() as temporary, patch.object(sys, "frozen", True, create=True), patch.object(
            sys, "_MEIPASS", temporary, create=True
        ):
            self.assertEqual(resource_root(), Path(temporary))

    def test_frozen_mode_keeps_external_data_directory(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(sys, "frozen", True, create=True), patch.object(
            sys, "_MEIPASS", "/Applications/HD2 Planner.app/Contents/Frameworks", create=True
        ):
            external = Path(temporary) / "user-data"
            resolved = resolve_data_dir(environ={"HD2_PLANNER_DATA_DIR": str(external)})
            self.assertEqual(resolved, external)
            self.assertNotIn("HD2 Planner.app", str(resolved))

    @unittest.skipUnless(os.environ.get("HD2_TEST_MACOS_APP"), "set HD2_TEST_MACOS_APP for final-bundle integration checks")
    def test_final_bundle_integration(self):
        bundle = Path(os.environ["HD2_TEST_MACOS_APP"])
        self.assertEqual(macos_bundle_errors(bundle), [])
        self.assertEqual(macos_binary_dependency_violations(bundle), [])
        self.assertEqual(machine_specific_reference_violations(bundle), [])
        executable = bundle / "Contents" / "MacOS" / "HD2 Planner"
        strings = subprocess.run(
            ["/usr/bin/strings", str(executable)], text=True, capture_output=True, check=True
        ).stdout
        self.assertNotIn("HD2_PLANNER_PYTHON", strings)
        self.assertNotIn("/usr/bin/python3", strings)
        self.assertNotIn("/opt/homebrew", strings)


if __name__ == "__main__":
    unittest.main()
