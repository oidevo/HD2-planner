from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .catalog import compare_catalogs, load_catalog, validate_catalog
from .constants import CATALOG_DIR, ROOT
from .data import user_data_paths
from .exporter import export_context, validate_generated
from .gui_runtime import missing_tkinter_message, tkinter_import_failed
from .local_data import migrate_local_data
from .loadout import validate_for_character
from .migrations import migrate_profile_file
from .onboarding import review_inventory, setup_profile
from .packaging import build_macos_app_package, build_package
from .profile import ProfileError, import_profile, load_profile, validate_profile
from .storage import read_json, write_json
from .update import check_for_update
from .version import PROFILE_SCHEMA_VERSION, application_version


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(prog="hd2.py", description="Offline Helldivers 2 inventory tracker and context exporter")
    sub = command.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="Create a player and one or more characters interactively")
    sub.add_parser("gui", help="Open the desktop inventory checklist")
    sub.add_parser("data-dir", help="Print the persistent per-user data directory")
    sub.add_parser("version", help="Print application, catalog, and profile schema versions")
    sub.add_parser("update-check", help="Check GitHub Releases without downloading anything")
    sub.add_parser("migrate-local-data", help="Copy legacy repo-local personal data into persistent storage")
    sub.add_parser("migrate", help="Migrate supported persistent profiles and create backups")

    inventory = sub.add_parser("inventory", help="Maintain a character inventory")
    inventory_sub = inventory.add_subparsers(dest="inventory_command", required=True)
    review = inventory_sub.add_parser("review", help="Review one inventory section")
    review.add_argument("--player", required=True)
    review.add_argument("--character", required=True)
    review.add_argument("--category", required=True)
    review.add_argument("--warbond")

    profile = sub.add_parser("profile", help="Profile operations")
    profile_sub = profile.add_subparsers(dest="profile_command", required=True)
    profile_import = profile_sub.add_parser("import", help="Validate and import onboarding JSON atomically")
    profile_import.add_argument("path", type=Path)
    profile_import.add_argument("--overwrite", action="store_true")
    profile_validate = profile_sub.add_parser("validate", help="Validate a profile")
    profile_validate.add_argument("path", type=Path)

    export = sub.add_parser("export-context", help="Generate portable JSON and Markdown context")
    export.add_argument("--player", required=True)
    export.add_argument("--character", required=True)
    export.add_argument("--output", type=Path, help="Override the persistent generated directory")

    generated = sub.add_parser("validate-generated", help="Check whether an export is stale")
    generated.add_argument("path", type=Path)
    generated.add_argument("--player", required=True)

    loadout = sub.add_parser("loadout", help="Saved loadout operations")
    loadout_sub = loadout.add_subparsers(dest="loadout_command", required=True)
    loadout_validate = loadout_sub.add_parser("validate", help="Validate a saved loadout against a character")
    loadout_validate.add_argument("path", type=Path)
    loadout_validate.add_argument("--player", required=True)
    loadout_validate.add_argument("--character", required=True)

    catalog = sub.add_parser("catalog", help="Maintainer catalog operations")
    catalog_sub = catalog.add_subparsers(dest="catalog_command", required=True)
    fetch = catalog_sub.add_parser("fetch", help="Fetch a candidate catalog from structured wiki APIs")
    fetch.add_argument("--output", type=Path, required=True)
    fetch.add_argument("--catalog-version", required=True)
    fetch.add_argument("--game-version", default="unknown")
    compare = catalog_sub.add_parser("compare", help="Compare accepted and candidate catalogs")
    compare.add_argument("old", type=Path)
    compare.add_argument("new", type=Path)
    compare.add_argument("--output", type=Path, required=True)
    catalog_validate = catalog_sub.add_parser("validate", help="Validate the accepted catalog")
    catalog_validate.add_argument("directory", type=Path, nargs="?", default=CATALOG_DIR)

    package = sub.add_parser("package", help="Build an offline distributable ZIP")
    package.add_argument("--output", type=Path, default=ROOT / "dist")
    package.add_argument("--macos-app", action="store_true", help="Also build the self-contained unsigned Apple Silicon app and archive")
    return command


def _profile(player_id: str) -> tuple[Path, dict]:
    return load_profile(player_id, load_catalog(), user_data_paths())


def run(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        paths = user_data_paths()
        if args.command == "gui":
            try:
                from .gui import launch_gui
            except ImportError as exc:
                if tkinter_import_failed(exc):
                    raise RuntimeError(missing_tkinter_message()) from exc
                raise
            return launch_gui()
        if args.command == "data-dir":
            print("HD2 Planner data directory:\n" + str(paths.initialize().root)); return 0
        if args.command == "version":
            manifest = load_catalog()["manifest"]
            print(f"HD2 Planner {application_version()}\nCatalog {manifest.get('catalog_version', 'unknown')}\nProfile schema {PROFILE_SCHEMA_VERSION}")
            return 0
        if args.command == "update-check":
            result = check_for_update()
            print(f"Installed: {result.installed}")
            if result.error:
                print(result.error); return 0
            print(f"Latest:    {result.latest}")
            print(("Update available:\n" if result.available else "You are up to date.\n") + str(result.url))
            return 0
        if args.command == "migrate-local-data":
            result = migrate_local_data(ROOT, paths)
            print(f"Persistent data directory: {paths.root}")
            print(f"Copied {len(result.copied)} file(s); skipped {len(result.skipped)} existing destination(s).")
            for path in result.copied: print(f"- copied: {path}")
            for path in result.skipped: print(f"- skipped (already exists): {path}")
            return 0
        if args.command == "migrate":
            catalog = load_catalog(); paths.initialize(); changed = []
            for path in sorted(paths.profiles.glob("*.json")):
                backup = migrate_profile_file(path, catalog, paths)
                if backup: changed.append((path, backup))
            print("No profile migrations needed." if not changed else "Migrated profiles:\n" + "\n".join(f"- {path} (backup: {backup})" for path, backup in changed))
            return 0
        if args.command == "setup":
            setup_profile(load_catalog(), paths.initialize().profiles)
            return 0
        if args.command == "profile":
            catalog = load_catalog()
            if args.profile_command == "import":
                output = import_profile(args.path, paths.initialize().profiles, catalog, args.overwrite)
                print(f"Imported validated profile: {output}")
            else:
                errors = validate_profile(read_json(args.path), catalog)
                if errors:
                    print("Invalid profile:\n- " + "\n- ".join(errors))
                    return 1
                print("Profile is valid.")
            return 0
        if args.command == "inventory":
            path, profile = _profile(args.player)
            review_inventory(profile, args.character, args.category, load_catalog(), path, warbond=args.warbond)
            return 0
        if args.command == "export-context":
            _, profile = _profile(args.player)
            output_paths = export_context(profile, args.character, load_catalog(), args.output)
            print("Generated:\n- " + "\n- ".join(str(path) for path in output_paths))
            return 0
        if args.command == "validate-generated":
            _, profile = _profile(args.player)
            result = validate_generated(args.path, profile, load_catalog())
            print(json.dumps(result, indent=2))
            return 0 if result["valid"] else 1
        if args.command == "loadout":
            _, profile = _profile(args.player)
            result = validate_for_character(read_json(args.path), profile["characters"][args.character], load_catalog())
            if result["errors"]:
                print("Invalid loadout:\n- " + "\n- ".join(result["errors"]))
                return 1
            print(f"Usable: {len(result['usable'])}/{result['total']} items")
            print("\nMissing:")
            print("\n".join(f"- {item['name']}" for item in result["missing"]) or "- None")
            print("\nUnknown:")
            print("\n".join(f"- {item['name']}" for item in result["unknown"]) or "- None")
            return 0 if not result["missing"] and not result["unknown"] else 2
        if args.command == "catalog":
            if args.catalog_command == "fetch":
                from importer.wiki import fetch_catalog
                counts = fetch_catalog(args.output, ROOT / "importer" / "overrides", args.catalog_version, args.game_version)
                print(json.dumps(counts, indent=2))
            elif args.catalog_command == "compare":
                from importer.review import write_review
                diff = compare_catalogs(load_catalog(args.old), load_catalog(args.new))
                args.output.mkdir(parents=True, exist_ok=True)
                write_json(args.output / "catalog-diff.json", diff)
                write_review(args.output / "catalog-review.md", diff)
                print(json.dumps(diff["summary"], indent=2))
            else:
                loaded = load_catalog(args.directory)
                errors = validate_catalog(loaded)
                print("Catalog is valid." if not errors else "Invalid catalog:\n- " + "\n- ".join(errors))
                return 0 if not errors else 1
            return 0
        if args.command == "package":
            result = build_package(args.output)
            print(f"Created offline package: {result}")
            if args.macos_app:
                bundle, archive = build_macos_app_package(args.output)
                print(f"Created self-contained macOS app: {bundle}")
                print(f"Created Apple Silicon app archive: {archive}")
            return 0
    except (ValueError, KeyError, OSError, ProfileError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 1
