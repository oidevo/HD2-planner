from __future__ import annotations

from pathlib import Path
from typing import Any


def review_markdown(diff: dict[str, Any]) -> str:
    summary = diff["summary"]
    lines = ["# Catalog Update Review", "", f"Generated: {diff['generated_at']}", "", "## Summary", ""]
    for key in ("unchanged", "changed", "added", "removed", "requires_review"):
        lines.append(f"- {key.replace('_', ' ')}: {summary[key]}")
    for key in ("added", "changed", "removed", "requires_review"):
        lines.extend(["", f"## {key.replace('_', ' ').title()}", ""])
        lines.extend(f"- `{item_id}`" for item_id in diff[key]) if diff[key] else lines.append("_None._")
    lines.extend(["", "Review the JSON diff artifact for before/after records. Accept by replacing the catalog only after review.", ""])
    return "\n".join(lines)


def write_review(path: Path, diff: dict[str, Any]) -> None:
    path.write_text(review_markdown(diff), encoding="utf-8", newline="\n")

