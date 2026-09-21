from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path

from .constants import APP_VERSION, ROOT


INCLUDE_FILES = [
    "hd2.py", "VERSION", "README.md", "LICENSE", "LICENSE_OR_ATTRIBUTION.md", "CHANGELOG.md", "pyproject.toml",
]
INCLUDE_DIRS = ["hd2lib", "catalog", "community", "docs", "planner", "importer", "onboarding", "schemas", "tests"]


def build_package(output_directory: Path, root: Path = ROOT) -> Path:
    output_directory.mkdir(parents=True, exist_ok=True)
    package_name = f"helldivers-planner-{APP_VERSION}"
    destination = output_directory / f"{package_name}.zip"
    with tempfile.TemporaryDirectory(prefix="hd2-package-") as temporary:
        stage = Path(temporary) / package_name
        stage.mkdir()
        for filename in INCLUDE_FILES:
            source = root / filename
            if source.exists():
                shutil.copy2(source, stage / filename)
        for dirname in INCLUDE_DIRS:
            source = root / dirname
            if source.exists():
                shutil.copytree(source, stage / dirname, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "raw", "staging"))
        # Examples remain source-controlled onboarding material; no user-data
        # directories are created in a release archive.
        profiles = stage / "examples" / "profiles"
        profiles.mkdir(parents=True)
        example = root / "profiles" / "example_player.json"
        if example.exists():
            shutil.copy2(example, profiles / example.name)
        loadout = root / "profiles" / "loadouts" / "example_illuminate_general.json"
        if loadout.exists():
            (profiles / "loadouts").mkdir()
            shutil.copy2(loadout, profiles / "loadouts" / loadout.name)
        (stage / "generated").mkdir()
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(stage.parent))
    return destination
