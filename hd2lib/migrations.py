"""Small, explicit migration registry for persistent profiles."""
from __future__ import annotations

import copy
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .data import UserDataPaths
from .profile import ProfileError, validate_profile
from .storage import read_json, write_json
from .version import PROFILE_SCHEMA_VERSION

Migration = Callable[[dict[str, Any]], dict[str, Any]]


def _v090_to_v100(profile: dict[str, Any]) -> dict[str, Any]:
    """Normalize optional top-level fields introduced by the portable profile."""
    result = copy.deepcopy(profile)
    result.setdefault("saved_loadouts", [])
    result.setdefault("gameplay_observations", [])
    result.setdefault("progression_notes", [])
    result["schema_version"] = "1.0.0"
    return result


MIGRATIONS: dict[str, tuple[str, Migration]] = {"0.9.0": ("1.0.0", _v090_to_v100)}


def migration_path(from_version: str, target: str = PROFILE_SCHEMA_VERSION) -> list[Migration]:
    steps: list[Migration] = []
    current = from_version
    while current != target:
        if current not in MIGRATIONS:
            raise ProfileError(f"Unsupported profile schema {from_version!r}; cannot migrate to {target!r}")
        current, transform = MIGRATIONS[current]
        steps.append(transform)
    return steps


def backup_profile(path: Path, data_paths: UserDataPaths) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = data_paths.backups / f"{path.stem}-{stamp}-pre-migration.json"
    number = 1
    while target.exists():
        target = data_paths.backups / f"{path.stem}-{stamp}-pre-migration-{number}.json"; number += 1
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    return target


def migrate_profile_file(path: Path, catalog: dict[str, Any], data_paths: UserDataPaths) -> Path | None:
    original = read_json(path)
    if original.get("schema_version") == PROFILE_SCHEMA_VERSION:
        return None
    migrated = original
    for transform in migration_path(str(original.get("schema_version"))):
        migrated = transform(migrated)
    errors = validate_profile(migrated, catalog)
    if errors:
        raise ProfileError("Migration validation failed; original left unchanged:\n- " + "\n- ".join(errors))
    backup = backup_profile(path, data_paths)
    try:
        write_json(path, migrated)
    except BaseException:
        # Atomic writes leave the old file intact; restore if an unusual failure occurred after replacement.
        if not path.exists(): shutil.copy2(backup, path)
        raise
    return backup
