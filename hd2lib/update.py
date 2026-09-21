"""Explicit, opt-in GitHub Release checks; normal commands never call this."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .version import application_version

DEFAULT_REPOSITORY = "oidevo/HD2-planner"
REPOSITORY_ENV = "HD2_PLANNER_REPOSITORY"


def repository() -> str:
    return os.environ.get(REPOSITORY_ENV, DEFAULT_REPOSITORY)


def semantic_version(value: str) -> tuple[int, int, int, tuple[str, ...]]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?", value.strip())
    if not match:
        raise ValueError(f"Not a supported semantic version: {value!r}")
    suffix = tuple(match.group(4).split(".")) if match.group(4) else ()
    return int(match.group(1)), int(match.group(2)), int(match.group(3)), suffix


def is_newer(candidate: str, installed: str) -> bool:
    c, i = semantic_version(candidate), semantic_version(installed)
    if c[:3] != i[:3]:
        return c[:3] > i[:3]
    if not c[3]: return bool(i[3])
    if not i[3]: return False
    for left, right in zip(c[3], i[3]):
        if left == right: continue
        left_number, right_number = left.isdigit(), right.isdigit()
        if left_number and right_number: return int(left) > int(right)
        if left_number != right_number: return not left_number  # numeric identifiers sort before text
        return left > right
    return len(c[3]) > len(i[3])


@dataclass(frozen=True)
class UpdateResult:
    installed: str
    latest: str | None
    url: str | None
    available: bool
    error: str | None = None


def check_for_update(repo: str | None = None, *, timeout: float = 5.0) -> UpdateResult:
    repo = repo or repository()
    installed = application_version()
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "HD2-Planner-update-check"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            release = json.load(response)
        latest = str(release.get("tag_name", "")).lstrip("v")
        release_url = release.get("html_url")
        if not latest or not release_url:
            raise ValueError("GitHub returned a release without a tag or URL")
        return UpdateResult(installed, latest, str(release_url), is_newer(latest, installed))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        return UpdateResult(installed, None, None, False, f"Could not check for updates: {exc}")
