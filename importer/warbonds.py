"""Import reward facts from the wiki's structured Warbond tables."""

from __future__ import annotations

import html
import re
from urllib.parse import quote

from hd2lib.onboarding import items_for_inventory_category
from hd2lib.storage import slugify


PAGE_HEADING = re.compile(r"^===\s*Page[_ ]+(\d+)\s*===\s*$", re.MULTILINE | re.IGNORECASE)
REWARD_TABLE = re.compile(r"^!Icon!!Item!!Type!!Cost[^\n]*\n(.*?)^\|}", re.MULTILINE | re.DOTALL)
REWARD_ROW = re.compile(r"^\|-\s*\n", re.MULTILINE)
TILE_COST = re.compile(r"^\s*\|\s*\d+_cost\s*=\s*([0-9,]+)", re.MULTILINE)
MEDAL_COST = re.compile(r"\{\{Currency\|Medals?\|([0-9,]+)(?:\|notext)?\}\}")
WIKI_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
WIKI_LINK = re.compile(r"\[\[([^|\]]+)(?:\|([^\]]+))?\]\]")

GEAR_CATEGORIES = ("primary_weapons", "secondary_weapons", "grenades", "armor", "boosters", "stratagems")
WARBOND_ONLY_TYPES = {"Currency", "Helmet", "Cape", "Player Card", "Victory Pose", "Emote", "Pattern", "Title"}
# The table's display text or link can differ from the accepted catalog's name.
REWARD_ALIASES = {
    "ax_flam_75_guard_dog_hot_dog": "ax_flam_75_hot_dog",
    "ax_tx_13_guard_dog_dog_breath": "ax_tx_13_dog_breath",
    "las_16_trident": "las_13_trident",
}


def _display_text(value: str) -> str:
    return html.unescape(WIKI_LINK.sub(lambda match: match[2] or match[1], value)).strip()


def _parse_rewards(source: str, title: str) -> list[tuple[int, str, str, str, int | None]]:
    parts = PAGE_HEADING.split(WIKI_COMMENT.sub("", source))
    page_numbers = [int(page) for page in parts[1::2]]
    if not page_numbers or page_numbers != list(range(1, len(page_numbers) + 1)):
        raise ValueError(f"{title}: expected consecutively numbered reward pages")
    rewards = []
    for page, section in zip(page_numbers, parts[2::2], strict=True):
        tables = REWARD_TABLE.findall(section)
        if len(tables) != 1:
            raise ValueError(f"{title} page {page}: expected one reward table")
        page_rewards = []
        for raw in REWARD_ROW.split(tables[0])[1:]:
            if not raw.strip():
                continue
            cells = raw.strip().removeprefix("|").split("||")
            if len(cells) != 4 or not (cost := MEDAL_COST.fullmatch(cells[-1].strip())):
                raise ValueError(f"{title} page {page}: unrecognized reward table row")
            _, item, kind, _ = cells
            link = WIKI_LINK.search(item)
            target = link[1].split("#", 1)[0] if link else item
            medals = int(cost[1].replace(",", ""))
            page_rewards.append((_display_text(item), target, _display_text(kind), medals))
        # Compare with the separate tile layout to catch partial tables. Some
        # revisions disagree on costs, so omit those prices for the whole page.
        tile_costs = [int(cost.replace(",", "")) for cost in TILE_COST.findall(section)]
        if not page_rewards or len(tile_costs) != len(page_rewards):
            raise ValueError(f"{title} page {page}: reward table and tile counts disagree")
        prices_agree = sorted(tile_costs) == sorted(medals for _, _, _, medals in page_rewards)
        rewards.extend((page, name, target, kind, medals if prices_agree else None)
                       for name, target, kind, medals in page_rewards)
    return rewards


def warbond_reward_records(
    collections: dict, pages: dict[str, dict], retrieved_at: str, importer_version: str,
) -> list[dict]:
    """Convert reward tables to records and link existing gear by reviewed names."""
    by_name = {}
    for category in GEAR_CATEGORIES:
        for item in items_for_inventory_category({"collections": collections}, category):
            keys = {slugify(item["name"])}
            keys.update(slugify(ref["page"]) for ref in item["provenance"]
                        if ref.get("source") == "helldivers_wiki" and ref.get("page"))
            for key in keys:
                by_name.setdefault(key, set()).add((category, item["id"]))

    records = []
    for warbond in collections["warbonds"]:
        title = next(ref["page"] for ref in warbond["provenance"] if ref["source"] == "helldivers_wiki")
        revision = pages[title.replace("_", " ")]
        source_url = f"https://helldivers.wiki.gg/wiki/{quote(title.replace(' ', '_'))}"
        for page, name, target, kind, medals in _parse_rewards(revision["slots"]["main"]["content"], title):
            fact_provenance = {}
            facts = {
                "warbond_id": warbond["id"], "warbond_page": page,
                "reward_type": kind,
            }
            if medals is not None:
                facts["unlock_cost_normalized"] = {"amount": medals, "currency": "medals"}
            if kind not in WARBOND_ONLY_TYPES:
                keys = {slugify(name), slugify(target)}
                candidates = set().union(*(by_name.get(REWARD_ALIASES.get(key, key), set()) for key in keys))
                if len(candidates) != 1:
                    raise ValueError(f"{title}: expected one inventory match for {name!r}, found {sorted(candidates)}")
                category, item_id = candidates.pop()
                facts["inventory_ref"] = {"category": category, "item_id": item_id}
                fact_provenance["inventory_ref"] = {
                    "kind": "manually_curated" if keys & REWARD_ALIASES.keys() else "derived",
                    "from": ["name", "facts.reward_type", "catalog inventory names"],
                }
            # Super Credits can repeat across pages and each claim is independent.
            suffix = f"_p{page}" if kind == "Currency" else ""
            item_id = f"warbond_{warbond['id']}_{slugify(kind)}_{slugify(name)}{suffix}"
            records.append({
                "id": item_id, "name": name, "facts": facts, "planner_tags": [],
                **({"fact_provenance": fact_provenance} if fact_provenance else {}),
                "provenance": [{
                    "source": "helldivers_wiki", "source_name": "The Helldivers Wiki",
                    "page": title, "source_url": source_url, "retrieved_at": retrieved_at,
                    "revision_id": revision["revid"], "revision_timestamp": revision["timestamp"],
                    "importer_version": importer_version,
                }],
            })
    return sorted(records, key=lambda reward: reward["id"])


def fetch_warbond_rewards(client, collections: dict, retrieved_at: str, importer_version: str) -> list[dict]:
    titles = [next(ref["page"] for ref in item["provenance"] if ref["source"] == "helldivers_wiki")
              for item in collections["warbonds"]]
    pages = {}
    for start in range(0, len(titles), 20):
        result = client.get({
            "action": "query", "prop": "revisions", "rvprop": "ids|timestamp|content",
            "rvslots": "main", "redirects": 1, "titles": "|".join(titles[start:start + 20]),
            "formatversion": 2,
        })["query"]
        pages.update({page["title"]: page["revisions"][0] for page in result["pages"]})
        for redirect in result.get("redirects", []):
            pages[redirect["from"]] = pages[redirect["to"]]
    return warbond_reward_records(collections, pages, retrieved_at, importer_version)
