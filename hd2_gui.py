#!/usr/bin/env python3
"""Convenience launcher for the Tk desktop application."""
from __future__ import annotations

import os
import sys

from hd2lib.data import DATA_DIR_ENV
from hd2lib.gui_launcher import main


def release_verification(mode: str) -> int:
    """Exercise real GUI persistence in an explicitly isolated release test."""
    if not os.environ.get(DATA_DIR_ENV):
        raise RuntimeError(f"{mode} requires an explicit disposable {DATA_DIR_ENV}")

    from hd2lib.gui import launch_gui
    from hd2lib.gui_model import PlannerService

    service = PlannerService()
    if mode == "--release-verify-seed":
        service.create_profile("Release Verification", "Main", "macOS", 76, player_id="release_verification")
        service.set_resources({"medals": 123, "requisition": 456, "super_credits": 78})
        service.set_inventory_status("primary_weapons", "sg_225_breaker", "unlocked")
        service.set_weapon_level("primary_weapons", "sg_225_breaker", 18)
        service.set_inventory_status("grenades", "g_12_high_explosive", "locked")
        service.set_inventory_status("stratagems", "stratagem_eagle_airstrike", "unlocked")
        service.set_item_preference("sg_225_breaker", "favorite")
        service.generate_context()
    elif mode == "--release-verify-reopen":
        service.open_profile("release_verification", "main")
        character = service.character()
        if character.get("level") != 76 or service.resources().get("medals") != 123:
            raise RuntimeError("release verification profile did not persist across launch")
        if service.inventory_status("primary_weapons", "sg_225_breaker") != "unlocked":
            raise RuntimeError("release verification inventory did not persist across launch")
        service.edit_character("Main", "macOS", 77)
        service.generate_context()
    else:
        raise ValueError(f"Unknown release verification mode: {mode}")
    return launch_gui(service, close_after_ms=3000)


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1].startswith("--release-verify-"):
        raise SystemExit(release_verification(sys.argv[1]))
    raise SystemExit(main())
