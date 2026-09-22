"""Persistent appearance preference and semantic color tokens."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from .storage import read_json, write_json


APPEARANCE_CHOICES = ("System", "Light", "Dark")

LIGHT_TOKENS = {
    "canvas": "#f5f6f7", "rail": "#e8ebee", "card": "#ffffff",
    "inspector": "#ffffff", "dialog": "#f5f6f7", "text": "#1f252c",
    "muted_text": "#606a74", "divider": "#cbd1d7", "selection": "#d8c789",
    "selection_text": "#171a1d", "input": "#ffffff", "input_text": "#1f252c",
    "heading": "#151a20", "button": "#e7eaed", "button_text": "#1f252c",
    "button_active": "#d9dde1", "menu": "#ffffff", "menu_text": "#1f252c",
    "disabled": "#929aa2", "error": "#9b3030", "unlocked": "#2f7350",
    "locked": "#9b3030", "unknown": "#68727c", "accent": "#a17c24",
    "accent_soft": "#eee2bd", "focus": "#a17c24",
}

DARK_TOKENS = {
    "canvas": "#171a1e", "rail": "#20242a", "card": "#262b31",
    "inspector": "#262b31", "dialog": "#20242a", "text": "#edf0f2",
    "muted_text": "#b1b8bf", "divider": "#3c434b", "selection": "#6f5a25",
    "selection_text": "#ffffff", "input": "#30363d", "input_text": "#f3f5f6",
    "heading": "#ffffff", "button": "#343a41", "button_text": "#f1f3f5",
    "button_active": "#414850", "menu": "#2b3036", "menu_text": "#f1f3f5",
    "disabled": "#7f878f", "error": "#ff9696", "unlocked": "#82d3a5",
    "locked": "#ff9696", "unknown": "#bac1c7", "accent": "#c5a24a",
    "accent_soft": "#55471f", "focus": "#d4b45d",
}


def load_appearance(settings_path: Path) -> str:
    if not settings_path.exists():
        return "System"
    try:
        value = read_json(settings_path).get("appearance", "System")
    except (OSError, ValueError):
        return "System"
    return value if value in APPEARANCE_CHOICES else "System"


def save_appearance(settings_path: Path, appearance: str) -> None:
    if appearance not in APPEARANCE_CHOICES:
        raise ValueError(f"Unknown appearance {appearance!r}")
    settings: dict[str, Any] = {}
    if settings_path.exists():
        try:
            settings = read_json(settings_path)
        except (OSError, ValueError):
            settings = {}
    settings["appearance"] = appearance
    write_json(settings_path, settings)


def system_appearance(*, platform: str | None = None) -> str:
    """Return Light or Dark without consulting network or mutable app data."""
    platform = sys.platform if platform is None else platform
    if platform != "darwin":
        return "Light"
    result = subprocess.run(
        ["/usr/bin/defaults", "read", "-g", "AppleInterfaceStyle"],
        text=True, capture_output=True, check=False,
    )
    return "Dark" if result.returncode == 0 and result.stdout.strip().casefold() == "dark" else "Light"


def resolved_appearance(choice: str) -> str:
    return system_appearance() if choice == "System" else choice


def semantic_tokens(mode: str) -> dict[str, str]:
    if mode == "Dark":
        return dict(DARK_TOKENS)
    if mode == "Light":
        return dict(LIGHT_TOKENS)
    raise ValueError(f"Appearance mode must be Light or Dark, not {mode!r}")
