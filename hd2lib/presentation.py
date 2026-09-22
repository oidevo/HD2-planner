"""Safe, category-aware presentation of catalog facts."""
from __future__ import annotations

from typing import Any


_MARKUP_MARKERS = ("[[", "]]", "<", ">", "&nbsp;", "{{", "}}")
_CURRENCY_LABELS = {
    "medals": "Medals",
    "super_credits": "Super credits",
    "requisition": "Requisition slips",
    "common_samples": "Common samples",
    "rare_samples": "Rare samples",
    "super_samples": "Super samples",
}


def _clean_scalar(value: Any) -> str | None:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if not isinstance(value, (str, int, float)):
        return None
    text = str(value).strip()
    if not text or any(marker in text for marker in _MARKUP_MARKERS):
        return None
    return text


def _title(value: Any) -> str | None:
    text = _clean_scalar(value)
    return text.replace("_", " ").title() if text else None


def _cost(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    amount = value.get("amount")
    currency = value.get("currency")
    if not isinstance(amount, int) or isinstance(amount, bool) or currency not in _CURRENCY_LABELS:
        return None
    return f"{amount:,} {_CURRENCY_LABELS[currency]}"


def _costs(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    values = [_cost(item) for item in value]
    return ", ".join(item for item in values if item) or None


def inspector_facts(category: str, facts: dict[str, Any]) -> list[tuple[str, str]]:
    """Return only approved normalized facts; raw audit values never pass through."""
    candidates: list[tuple[str, str | None]] = []
    if category == "warbonds":
        candidates = [
            ("Type", _title(facts.get("type"))),
            ("Released", _clean_scalar(facts.get("date"))),
            ("Purchase cost", _cost(facts.get("purchase_cost"))),
            ("Known total medal cost", _cost(facts.get("total_reward_medal_cost"))),
            ("Included Super Credits", _cost(facts.get("included_super_credits"))),
        ]
    elif category in {"primary_weapons", "secondary_weapons", "support_weapons"}:
        candidates = [
            ("Category", _title(facts.get("category"))),
            ("Type", _clean_scalar(facts.get("weapon_type"))),
            ("Warbond page", _clean_scalar(facts.get("warbond_page"))),
            ("Known cost", _cost(facts.get("unlock_cost_normalized"))),
            ("Capacity", _clean_scalar(facts.get("capacity_count"))),
            ("Armor penetration", _title(facts.get("armor_penetration"))),
        ]
    elif category == "stratagems":
        candidates = [
            ("Category", _title(facts.get("category"))),
            ("Type", _clean_scalar(facts.get("stratagem_type"))),
            ("Cooldown", f"{facts['cooldown_seconds']} seconds" if isinstance(facts.get("cooldown_seconds"), int) else None),
            ("Unlock level", _clean_scalar(facts.get("unlock_level"))),
            ("Warbond page", _clean_scalar(facts.get("warbond_page"))),
            ("Known cost", _cost(facts.get("unlock_cost_normalized"))),
        ]
    elif category == "ship_modules":
        candidates = [
            ("Category", _clean_scalar(facts.get("section"))),
            ("Tier", _clean_scalar(facts.get("tier"))),
            ("Known cost", _costs(facts.get("costs_normalized"))),
        ]
    elif category == "armor":
        candidates = [
            ("Type", _clean_scalar(facts.get("type"))),
            ("Category", _title(facts.get("armor_class"))),
            ("Passive", _title(facts.get("passive_id"))),
            ("Warbond page", _clean_scalar(facts.get("warbond_page"))),
            ("Known cost", _cost(facts.get("unlock_cost_normalized"))),
        ]
    elif category == "grenades":
        candidates = [
            ("Type", _clean_scalar(facts.get("weapon_type"))),
            ("Capacity", _clean_scalar(facts.get("capacity_count"))),
            ("Warbond page", _clean_scalar(facts.get("warbond_page"))),
            ("Known cost", _cost(facts.get("unlock_cost_normalized"))),
        ]
    elif category == "weapon_attachments":
        candidates = [
            ("Category", _title(facts.get("slot"))),
            ("Type", _clean_scalar(facts.get("type"))),
            ("Optic range", _clean_scalar(facts.get("optic_range"))),
            ("Ergonomics", _clean_scalar(facts.get("ergonomics"))),
        ]
    else:
        candidates = [
            ("Type", _clean_scalar(facts.get("type"))),
            ("Category", _title(facts.get("category"))),
            ("Warbond page", _clean_scalar(facts.get("warbond_page"))),
            ("Known cost", _cost(facts.get("unlock_cost_normalized"))),
        ]
    return [(label, value) for label, value in candidates if value is not None]
