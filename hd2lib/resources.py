"""Read-only application resource locations for source and frozen builds."""
from __future__ import annotations

import sys
from pathlib import Path


def resource_root() -> Path:
    """Return the immutable application root without touching user data."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parent.parent
