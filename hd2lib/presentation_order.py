"""Curated, versioned UI ordering that remains separate from game facts."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, TypeVar, Callable

from .resources import resource_root
from .storage import read_json


PRESENTATION_ORDER_PATH = resource_root() / "planner" / "presentation_order.json"
PRESENTATION_ORDER_SCHEMA_VERSION = "1.0.0"


class PresentationOrderError(ValueError):
    pass


@dataclass(frozen=True)
class PresentationOrder:
    document: dict[str, Any]

    @property
    def source_catalog_version(self) -> str:
        return str(self.document["source_catalog_version"])

    def screen(self, screen_id: str) -> dict[str, Any] | None:
        return next(
            (screen for screen in self.document.get("screens", []) if screen.get("id") == screen_id),
            None,
        )

    def group_rank(self, screen_id: str, group_id: str | None) -> int:
        screen = self.screen(screen_id) or {}
        groups = screen.get("groups", [])
        return next((index for index, group in enumerate(groups) if group.get("id") == group_id), len(groups))

    def item_rank(self, screen_id: str, item_id: str, group_id: str | None = None) -> tuple[int, int]:
        screen = self.screen(screen_id) or {}
        groups = screen.get("groups", [])
        if group_id is not None:
            groups = [group for group in groups if group.get("id") == group_id]
        for group_index, group in enumerate(groups):
            try:
                return group_index, group.get("item_ids", []).index(item_id)
            except ValueError:
                continue
        return len(groups), 2**31 - 1

    def verification_message(self, screen_id: str) -> str:
        screen = self.screen(screen_id)
        if not screen or screen.get("verification") != "verified":
            return "Game display order is being verified; unconfirmed items follow a fallback order."
        if any(group.get("verification") != "verified" for group in screen.get("groups", [])):
            return "Some game display groups are still being verified; unconfirmed items follow a fallback order."
        return "Order verified against the evidence references recorded in the presentation-order document."


T = TypeVar("T")


def sort_with_presentation_order(
    values: Iterable[T],
    order: PresentationOrder,
    screen_id: str,
    *,
    item_id: Callable[[T], str],
    group_id: Callable[[T], str | None],
    fallback: Callable[[T], tuple[Any, ...]],
) -> list[T]:
    """Sort confirmed IDs first and use an explicit deterministic fallback."""
    def key(value: T) -> tuple[Any, ...]:
        group = group_id(value)
        group_rank = order.group_rank(screen_id, group)
        _matched_group, item_rank = order.item_rank(screen_id, item_id(value), group)
        confirmed = item_rank != 2**31 - 1
        return group_rank, 0 if confirmed else 1, item_rank, fallback(value)

    return sorted(values, key=key)


def load_presentation_order(
    path: Path = PRESENTATION_ORDER_PATH,
    *,
    catalog_version: str | None = None,
    known_item_ids: set[str] | None = None,
) -> PresentationOrder:
    document = read_json(path)
    errors: list[str] = []
    if document.get("schema_version") != PRESENTATION_ORDER_SCHEMA_VERSION:
        errors.append(f"unsupported schema_version {document.get('schema_version')!r}")
    source_version = document.get("source_catalog_version")
    if not isinstance(source_version, str) or not source_version:
        errors.append("source_catalog_version is required")
    if catalog_version is not None and source_version != catalog_version:
        errors.append(f"source catalog version {source_version!r} does not match {catalog_version!r}")
    capture = document.get("capture")
    if not isinstance(capture, dict):
        errors.append("capture metadata is required")
    else:
        if capture.get("captured_at") is not None and not isinstance(capture.get("captured_at"), str):
            errors.append("capture.captured_at must be a date string or null")
        if not isinstance(capture.get("game_build"), str) or not capture.get("game_build"):
            errors.append("capture.game_build is required (use 'unknown' when unavailable)")
        evidence = capture.get("evidence_references")
        if not isinstance(evidence, list) or not all(isinstance(value, str) for value in evidence):
            errors.append("capture.evidence_references must be a string array")
    seen_screens: set[str] = set()
    ordered_ids: set[str] = set()
    for screen in document.get("screens", []):
        screen_id = screen.get("id")
        if not isinstance(screen_id, str) or not screen_id or screen_id in seen_screens:
            errors.append(f"invalid or duplicate screen id {screen_id!r}")
            continue
        seen_screens.add(screen_id)
        if screen.get("verification") not in {"verified", "partial", "unverified"}:
            errors.append(f"{screen_id}: invalid verification state")
        seen_groups: set[str] = set()
        for group in screen.get("groups", []):
            group_id = group.get("id")
            if not isinstance(group_id, str) or not group_id or group_id in seen_groups:
                errors.append(f"{screen_id}: invalid or duplicate group id {group_id!r}")
                continue
            seen_groups.add(group_id)
            if group.get("verification") not in {"verified", "partial", "unverified"}:
                errors.append(f"{screen_id}/{group_id}: invalid verification state")
            item_ids = group.get("item_ids")
            if not isinstance(item_ids, list) or not all(isinstance(value, str) for value in item_ids):
                errors.append(f"{screen_id}/{group_id}: item_ids must be a string array")
                continue
            duplicates = ordered_ids.intersection(item_ids)
            if duplicates:
                errors.append(f"stable IDs ordered more than once: {', '.join(sorted(duplicates))}")
            ordered_ids.update(item_ids)
    if known_item_ids is not None:
        unknown = ordered_ids - known_item_ids
        if unknown:
            errors.append(f"unknown stable IDs: {', '.join(sorted(unknown))}")
    if errors:
        raise PresentationOrderError("Invalid presentation order:\n- " + "\n- ".join(errors))
    return PresentationOrder(document)
