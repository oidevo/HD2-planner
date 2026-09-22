"""Tk GUI entry point with safe diagnostics for Python builds without Tk."""
from __future__ import annotations

import sys

from .gui_runtime import missing_tkinter_message, tkinter_import_failed


def main() -> int:
    try:
        from .gui import launch_gui
    except ImportError as exc:
        if tkinter_import_failed(exc):
            print(f"Error: {missing_tkinter_message()}", file=sys.stderr)
            return 1
        raise
    return launch_gui()
