from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .catalog import compare_catalogs, load_catalog, validate_catalog
from .constants import CATALOG_DIR, GENERATED_DIR, PROFILES_DIR, ROOT
from .exporter import export_context, validate_generated
from .loadout import validate_for_character
from .onboarding import review_inventory, setup_profile
from .packaging import build_package
from .profile import ProfileError, find_profile, import_profile, save_profile, validate_profile
from .storage import read_json, write_json


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(prog="hd2.py", description="Offline Helldivers 2 inventory tracker and context exporter")
    sub = command.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="Create a player and one or more characters interactively")

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
    export.add_argument("--output", type=Path, default=GENERATED_DIR)

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
    return command


def _profile(player_id: str) -> tuple[Path, dict]:
    path = find_profile(player_id)
    return path, read_json(path)


def run(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "setup":
            setup_profile(load_catalog(), PROFILES_DIR)
            return 0
        if args.command == "profile":
            catalog = load_catalog()
            if args.profile_command == "import":
                output = import_profile(args.path, PROFILES_DIR, catalog, args.overwrite)
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
            paths = export_context(profile, args.character, load_catalog(), args.output)
            print("Generated:\n- " + "\n- ".join(str(path) for path in paths))
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
            return 0
    except (ValueError, KeyError, OSError, ProfileError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 1

