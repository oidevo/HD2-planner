"""Locations for user-owned HD2 Planner state.

Nothing in this module points at the application checkout so replacing a release
folder cannot replace a player's data.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


DATA_DIR_ENV = "HD2_PLANNER_DATA_DIR"


@dataclass(frozen=True)
class UserDataPaths:
    root: Path

    @property
    def profiles(self) -> Path: return self.root / "profiles"
    @property
    def loadouts(self) -> Path: return self.root / "loadouts"
    @property
    def generated(self) -> Path: return self.root / "generated"
    @property
    def settings(self) -> Path: return self.root / "settings.json"
    @property
    def backups(self) -> Path: return self.root / "backups"
    @property
    def migrations(self) -> Path: return self.root / "migrations"

    def initialize(self) -> "UserDataPaths":
        for path in (self.root, self.profiles, self.loadouts, self.generated, self.backups, self.migrations):
            path.mkdir(parents=True, exist_ok=True)
        return self


def resolve_data_dir(*, platform: str | None = None, environ: dict[str, str] | None = None, home: Path | None = None) -> Path:
    """Return the per-user data directory without creating it."""
    environ = os.environ if environ is None else environ
    if environ.get(DATA_DIR_ENV):
        return Path(environ[DATA_DIR_ENV]).expanduser()
    platform = sys.platform if platform is None else platform
    home = Path.home() if home is None else home
    if platform == "darwin":
        return home / "Library" / "Application Support" / "HD2 Planner"
    if platform.startswith("win"):
        base = Path(environ.get("APPDATA", str(home / "AppData" / "Roaming")))
        return base / "HD2 Planner"
    base = Path(environ.get("XDG_DATA_HOME", str(home / ".local" / "share")))
    return base / "hd2-planner"


def user_data_paths() -> UserDataPaths:
    return UserDataPaths(resolve_data_dir())
