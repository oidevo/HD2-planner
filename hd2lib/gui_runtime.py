"""GUI runtime diagnostics that remain importable without Tkinter."""
from __future__ import annotations

import sys


def tkinter_import_failed(exc: ImportError) -> bool:
    """Return whether an import failure came from Tkinter itself."""
    return exc.name in {"_tkinter", "tkinter"}


def missing_tkinter_message() -> str:
    """Give GUI users actionable, non-destructive recovery guidance."""
    return (
        "Tkinter is missing from this Python installation.\n"
        f"Interpreter: {sys.executable}\n"
        f"Detected Python: {sys.version.split()[0]}\n\n"
        "HD2 Planner requires a Tk-enabled Python 3.12 or newer to run its desktop GUI. "
        "Install or select a matching Python build with Tkinter, then run the GUI again. "
        "The CLI and your stored profile data are unaffected."
    )
