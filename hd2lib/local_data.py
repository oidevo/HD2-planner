"""Safe one-time import of data created by pre-0.2 repository layouts."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .data import UserDataPaths


@dataclass(frozen=True)
class LocalDataImport:
    copied: tuple[Path, ...]
    skipped: tuple[Path, ...]


def migrate_local_data(root: Path, destination: UserDataPaths) -> LocalDataImport:
    """Copy legacy personal files, never overwrite, and leave the checkout intact."""
    destination.initialize()
    mappings = ((root / "profiles", destination.profiles, lambda p: p.name != "example_player.json"),
                (root / "profiles" / "loadouts", destination.loadouts, lambda p: True),
                (root / "generated", destination.generated, lambda p: True))
    copied: list[Path] = []; skipped: list[Path] = []
    for source_root, target_root, include in mappings:
        if not source_root.exists():
            continue
        for source in source_root.rglob("*"):
            if not source.is_file() or not include(source):
                continue
            # Do not copy nested loadouts once as a profile and again as a loadout.
            if source_root.name == "profiles" and "loadouts" in source.relative_to(source_root).parts:
                continue
            target = target_root / source.relative_to(source_root)
            if target.exists():
                skipped.append(source); continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(target)
    return LocalDataImport(tuple(copied), tuple(skipped))
