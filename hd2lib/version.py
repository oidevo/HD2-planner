"""Canonical application version and display helpers."""
from __future__ import annotations

from .resources import resource_root

PROFILE_SCHEMA_VERSION = "1.1.0"


def application_version() -> str:
    return (resource_root() / "VERSION").read_text(encoding="utf-8").strip()
