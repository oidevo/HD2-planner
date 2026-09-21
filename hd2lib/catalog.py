from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterable

from .constants import CATALOG_DIR, CATALOG_FILES, SCHEMA_VERSION
from .storage import fingerprint, read_json, utc_now, write_json


class CatalogError(ValueError):
    pass


def load_catalog(directory: Path = CATALOG_DIR) -> dict[str, Any]:
    manifest_path = directory / "catalog_manifest.json"
    manifest = read_json(manifest_path)
    collections: dict[str, list[dict[str, Any]]] = {}
    integrity_errors: list[str] = []
    for collection, filename in CATALOG_FILES.items():
        path = directory / filename
        if not path.exists():
            raise CatalogError(f"Missing catalog file: {path}")
        document = read_json(path)
        expected_hash = manifest.get("files", {}).get(collection, {}).get("hash")
        if expected_hash and fingerprint(document) != expected_hash:
            integrity_errors.append(f"{collection}: content does not match catalog manifest hash")
        collections[collection] = document.get("items", [])
    result = {"manifest": manifest, "collections": collections}
    errors = integrity_errors + validate_catalog(result)
    if errors:
        raise CatalogError("; ".join(errors))
    return result


def validate_catalog(catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    manifest = catalog.get("manifest", {})
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"Unsupported catalog schema_version: {manifest.get('schema_version')!r}")
    seen: dict[str, str] = {}
    for collection, items in catalog.get("collections", {}).items():
        if not isinstance(items, list):
            errors.append(f"{collection}: items must be an array")
            continue
        for item in items:
            item_id = item.get("id") if isinstance(item, dict) else None
            if not item_id or not isinstance(item_id, str):
                errors.append(f"{collection}: item missing stable string id")
                continue
            if item_id in seen:
                errors.append(f"Duplicate item id {item_id!r} in {collection} and {seen[item_id]}")
            seen[item_id] = collection
            if not item.get("name"):
                errors.append(f"{collection}/{item_id}: missing name")
            provenance = item.get("provenance")
            if provenance is not None and not isinstance(provenance, list):
                errors.append(f"{collection}/{item_id}: provenance must be an array")
            if "planner_tags" in item:
                for tag in item["planner_tags"]:
                    if not isinstance(tag, dict) or not {"tag", "origin", "provenance_kind"} <= set(tag):
                        errors.append(f"{collection}/{item_id}: planner tag lacks tag, origin, or provenance_kind")
                    elif tag["provenance_kind"] not in {"imported", "derived", "manually_curated"}:
                        errors.append(f"{collection}/{item_id}: invalid planner tag provenance_kind")
            for field, evidence in item.get("fact_provenance", {}).items():
                if not isinstance(evidence, dict) or evidence.get("kind") not in {"imported", "derived", "manually_curated"}:
                    errors.append(f"{collection}/{item_id}: invalid fact provenance for {field!r}")
    return errors


def catalog_index(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["id"]: {**item, "_collection": collection}
        for collection, items in catalog["collections"].items()
        for item in items
    }


def catalog_hash(catalog: dict[str, Any]) -> str:
    payload = {
        "manifest": catalog["manifest"],
        "collections": catalog["collections"],
    }
    return fingerprint(payload)


def _semantic_item(item: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(item)
    for source in value.get("provenance", []):
        source.pop("retrieved_at", None)
    return value


def compare_catalogs(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    old_index = catalog_index(old)
    new_index = catalog_index(new)
    old_ids, new_ids = set(old_index), set(new_index)
    added = sorted(new_ids - old_ids)
    removed = sorted(old_ids - new_ids)
    changed = sorted(
        item_id for item_id in old_ids & new_ids
        if _semantic_item(old_index[item_id]) != _semantic_item(new_index[item_id])
    )
    unchanged = sorted((old_ids & new_ids) - set(changed))
    review = sorted(set(removed) | {
        item_id for item_id in changed
        if old_index[item_id].get("facts", {}).get("category") != new_index[item_id].get("facts", {}).get("category")
    })
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "summary": {
            "unchanged": len(unchanged), "changed": len(changed), "added": len(added),
            "removed": len(removed), "requires_review": len(review),
        },
        "unchanged": unchanged, "changed": changed, "added": added, "removed": removed,
        "requires_review": review,
        "details": {
            item_id: {"before": old_index.get(item_id), "after": new_index.get(item_id)}
            for item_id in sorted(set(added + removed + changed))
        },
    }


def load_catalog_from_documents(directory: Path) -> dict[str, Any]:
    return load_catalog(directory)


def update_manifest_hashes(directory: Path) -> dict[str, Any]:
    manifest_path = directory / "catalog_manifest.json"
    manifest = read_json(manifest_path)
    manifest["files"] = {
        key: {"path": filename, "hash": fingerprint(read_json(directory / filename))}
        for key, filename in CATALOG_FILES.items()
    }
    write_json(manifest_path, manifest)
    return manifest
