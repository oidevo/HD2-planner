from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from hd2lib.constants import CATALOG_FILES, SCHEMA_VERSION
from hd2lib.storage import read_json, slugify, utc_now, write_json

API_URL = "https://helldivers.wiki.gg/api.php"
IMPORTER_VERSION = "1.1.0"
USER_AGENT = "HD2InventoryPlanner/0.1 (offline catalog updater; respectful MediaWiki API client)"

TABLES = {
    "weapons": ("Weapons", ["_pageName", "title", "weapon_category", "weapon_type", "damage", "capacity", "recoil", "fire_rate", "weapon_traits", "firing_modes", "scope_options", "source", "cost"]),
    "attachments": ("Attachments", ["_pageName", "title", "type", "available_on", "horizontal_recoil", "vertical_recoil", "horizontal_spread", "vertical_spread", "sway", "ergonomics", "mag_capacity", "max_magazines", "heatsink_overheat", "optic_range"]),
    "armor": ("Armor", ["_pageName", "title", "type", "armor", "speed", "stam_regen", "passive", "source", "cost"]),
    "armor_passives": ("Armor_Passive", ["_pageName", "title"]),
    "stratagems": ("Stratagems", ["_pageName", "title", "permit_type", "unlock_level", "unlock_cost", "source", "traits", "stratagem_type", "base_cooldown"]),
    "ship_modules": ("Ship_Modules", ["_pageName", "title", "section", "cost1", "cost2", "cost3", "cost4", "cost5", "tier", "prior"]),
    "warbonds": ("Warbonds", ["_pageName", "title", "date", "type", "cost", "credit_claim", "all_pages"]),
    "enemies": ("Enemies", ["_pageName", "title", "faction", "class", "size", "health", "min_difficulty", "fire_mult", "arc_mult", "acid_mult", "gas_mult"]),
    "mission_types": ("Missions", ["_pageName", "title", "time_limit", "faction", "min_difficulty", "max_difficulty"]),
    "biomes": ("Biomes", ["_pageName", "biome", "landscape", "internal_name", "archetype", "environmental_conditions"]),
    "_equipment": ("Equipment", ["_pageName", "title", "equip_type", "traits"]),
}


class WikiClient:
    def __init__(self, delay: float = 1.25):
        self.delay = delay
        self.last_request = 0.0

    def get(self, params: dict[str, Any]) -> dict[str, Any]:
        elapsed = time.monotonic() - self.last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        query = urllib.parse.urlencode({**params, "format": "json"})
        request = urllib.request.Request(f"{API_URL}?{query}", headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    self.last_request = time.monotonic()
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or attempt == 2:
                    raise
                time.sleep(3 * (attempt + 1))
        raise RuntimeError("unreachable")

    def cargo_rows(self, table: str, fields: list[str]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        offset = 0
        while True:
            response = self.get({"action": "cargoquery", "tables": table, "fields": ",".join(fields), "limit": 500, "offset": offset})
            batch = []
            for entry in response.get("cargoquery", []):
                raw = entry.get("title", {})
                normalized = {}
                for key, value in raw.items():
                    normalized["_pageName" if key == "_pageName" else slugify(key)] = value
                batch.append(normalized)
            result.extend(batch)
            if len(batch) < 500:
                return result
            offset += 500

    def revisions(self, pages: list[str]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for start in range(0, len(pages), 50):
            response = self.get({"action": "query", "prop": "revisions", "rvprop": "ids|timestamp", "redirects": 1, "titles": "|".join(pages[start:start + 50])})
            for page in response.get("query", {}).get("pages", {}).values():
                revision = (page.get("revisions") or [{}])[0]
                result[page.get("title", "")] = {"revision_id": revision.get("revid"), "revision_timestamp": revision.get("timestamp")}
        return result

    def category_members(self, category: str) -> list[dict[str, Any]]:
        response = self.get({"action": "query", "list": "categorymembers", "cmtitle": f"Category:{category}", "cmnamespace": 0, "cmlimit": 500})
        return [{"_pageName": row["title"], "title": row["title"]} for row in response.get("query", {}).get("categorymembers", []) if row["title"] != category]


def _clean_facts(row: dict[str, Any]) -> dict[str, Any]:
    excluded = {"_pageName", "title"}
    return {slugify(key): value for key, value in row.items() if key not in excluded and value not in (None, "")}


def _weapon_category(row: dict[str, Any]) -> str:
    combined = f"{row.get('weapon_category', '')} {row.get('weapon_type', '')}".casefold()
    if "secondary" in combined or "sidearm" in combined:
        return "secondary"
    if "support" in combined:
        return "support_weapon"
    if "primary" in combined:
        return "primary"
    if "grenade" in combined or "throwable" in combined:
        return "grenade"
    return "unknown"


def _stratagem_category(row: dict[str, Any]) -> str:
    value = f"{row.get('permit_type', '')} {row.get('stratagem_type', '')}".casefold()
    for needle, category in (("eagle", "eagle"), ("orbital", "orbital"), ("backpack", "backpack"), ("sentry", "sentry"), ("emplacement", "emplacement"), ("vehicle", "vehicle"), ("mech", "vehicle"), ("weapon", "support_weapon"), ("defensive", "defensive_support")):
        if needle in value:
            return category
    return "other"


def _record(collection: str, row: dict[str, Any], revisions: dict[str, dict[str, Any]], retrieved_at: str) -> dict[str, Any]:
    page = row.get("_pageName") or row.get("title")
    name = row.get("title") or row.get("biome") or page
    prefix = {
        "stratagems": "stratagem_",
        "enemies": "enemy_",
        "mission_types": "mission_",
        "biomes": "biome_",
    }.get(collection, "")
    item_id = prefix + slugify(str(name))
    if collection == "armor" and str(row.get("type", "")).casefold() in {"helmet", "cape"}:
        item_id += "_" + slugify(str(row["type"]))
    facts = _clean_facts(row)
    if collection == "weapons":
        facts["category"] = _weapon_category(row)
    elif collection == "stratagems":
        facts["category"] = _stratagem_category(row)
    provenance = {
        "source": "helldivers_wiki",
        "source_name": "The Helldivers Wiki",
        "page": page,
        "source_url": f"https://helldivers.wiki.gg/wiki/{urllib.parse.quote(str(page).replace(' ', '_'))}",
        "retrieved_at": retrieved_at,
        "importer_version": IMPORTER_VERSION,
        **revisions.get(str(page), {}),
    }
    return {"id": item_id, "name": name, "facts": facts, "planner_tags": [], "provenance": [provenance]}


def _merge_overrides(collection: str, items: list[dict[str, Any]], overrides_directory: Path) -> list[dict[str, Any]]:
    path = overrides_directory / f"{collection}.json"
    if not path.exists():
        return items
    override_doc = read_json(path)
    index = {item["id"]: item for item in items}
    for patch in override_doc.get("items", []):
        item_id = patch["id"]
        if patch.get("remove"):
            index.pop(item_id, None)
            continue
        current = index.setdefault(item_id, {})
        for key, value in patch.items():
            if key == "facts" and isinstance(value, dict):
                current.setdefault("facts", {}).update(value)
            elif key != "remove":
                current[key] = value
        current.setdefault("provenance", []).append({
            "source": "manual_override", "source_name": "Project-maintained manual override",
            "page": path.name, "retrieved_at": utc_now(), "importer_version": IMPORTER_VERSION,
        })
    return sorted(index.values(), key=lambda item: item["id"])


def _deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cargo may emit one template row per weapon/attachment pairing."""
    index: dict[str, dict[str, Any]] = {}
    for item in items:
        existing = index.get(item["id"])
        if existing is None:
            index[item["id"]] = item
            continue
        for key, value in item.get("facts", {}).items():
            prior = existing.setdefault("facts", {}).get(key)
            if prior is None:
                existing["facts"][key] = value
            elif prior != value:
                values = prior if isinstance(prior, list) else [prior]
                if value not in values:
                    values.append(value)
                existing["facts"][key] = values
    return sorted(index.values(), key=lambda item: item["id"])


def fetch_catalog(output_directory: Path, overrides_directory: Path, catalog_version: str, game_version: str = "unknown") -> dict[str, int]:
    client = WikiClient()
    retrieved_at = utc_now()
    rows_by_collection: dict[str, list[dict[str, Any]]] = {}
    all_pages: list[str] = []
    for collection, (table, fields) in TABLES.items():
        try:
            rows = client.cargo_rows(table, fields)
        except urllib.error.HTTPError as exc:
            if exc.code == 400 and collection in {"mission_types", "biomes"}:
                rows = []
            else:
                raise
        rows_by_collection[collection] = rows
        all_pages.extend(str(row.get("_pageName")) for row in rows if row.get("_pageName"))
    rows_by_collection["_boosters"] = client.category_members("Boosters")
    all_pages.extend(row["_pageName"] for row in rows_by_collection["_boosters"])
    revisions = client.revisions(sorted(set(all_pages)))
    output_directory.mkdir(parents=True, exist_ok=True)
    source = {"name": "The Helldivers Wiki", "url": "https://helldivers.wiki.gg/", "license": "CC BY-NC-SA 4.0", "retrieved_at": retrieved_at}
    counts: dict[str, int] = {}
    records_by_collection: dict[str, list[dict[str, Any]]] = {}
    for collection, filename in CATALOG_FILES.items():
        rows = rows_by_collection.get(collection, [])
        records = [_record(collection, row, revisions, retrieved_at) for row in rows]
        if collection == "weapons":
            records = [record for record in records if record["facts"].get("category") != "grenade"]
        elif collection == "grenades":
            matching = [row for row in rows_by_collection.get("weapons", []) if _weapon_category(row) == "grenade"]
            records = [_record(collection, row, revisions, retrieved_at) for row in matching]
        elif collection == "boosters":
            records = [_record(collection, row, revisions, retrieved_at) for row in rows_by_collection["_boosters"]]
        records = _merge_overrides(collection, _deduplicate(records), overrides_directory)
        counts[collection] = len(records)
        records_by_collection[collection] = records

    # Cross-catalog relationships (attachment -> weapon, reward -> Warbond,
    # support stratagem -> weapon) can only be normalized after every table is
    # present. The normalizer derives values solely from imported fields.
    from importer.normalize import normalize_collections
    normalize_collections(records_by_collection)

    for collection, filename in CATALOG_FILES.items():
        records = records_by_collection[collection]
        document = {"schema_version": SCHEMA_VERSION, "catalog_version": catalog_version, "game_version": game_version, "generated_at": retrieved_at, "sources": [source], "items": records}
        write_json(output_directory / filename, document)
    manifest = {"schema_version": SCHEMA_VERSION, "catalog_version": catalog_version, "game_version": game_version, "generated_at": retrieved_at, "importer_version": IMPORTER_VERSION, "normalizer_version": "1.0.0", "sources": [source], "files": {}}
    write_json(output_directory / "catalog_manifest.json", manifest)
    from hd2lib.catalog import update_manifest_hashes
    update_manifest_hashes(output_directory)
    return counts
