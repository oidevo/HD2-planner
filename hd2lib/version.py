"""Canonical application version and display helpers."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE_SCHEMA_VERSION = "1.0.0"


def application_version() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
