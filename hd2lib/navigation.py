"""Display-independent navigation model mirroring the Super Destroyer terminals.

The desktop interface arranges the inventory the app already tracks under the
three Super Destroyer terminals a Helldivers 2 player visits in the game:
Armory, Ship Management, and Acquisition Center. Planning-only features
(preferences, observations, saved loadouts, context export) live in a separate
Planner area because they have no in-game terminal.

Terminal and tab labels follow the structure requested for this redesign. Item
order inside each tab is governed separately by ``planner/presentation_order.json``
and stays unverified until in-game captures meet the documented standard; this
module never claims game order.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Tab:
    id: str
    label: str
    category: str | None = None
    """Inventory category shown by the tab, or None for planner pages."""
    description: str = ""


@dataclass(frozen=True)
class Terminal:
    id: str
    label: str
    tabs: tuple[Tab, ...]
    short: str
    description: str = ""
    planner: bool = False

    def tab(self, tab_id: str) -> Tab | None:
        return next((tab for tab in self.tabs if tab.id == tab_id), None)


@dataclass(frozen=True)
class Location:
    terminal: Terminal
    tab: Tab
    trail: tuple[str, ...] = field(default_factory=tuple)
    """Extra breadcrumb segments after the tab (for drill-in views)."""

    def breadcrumb(self, separator: str = " › ") -> str:
        return separator.join((self.terminal.label, self.tab.label, *self.trail))


ARMORY = Terminal(
    "armory", "Armory", short="AR",
    description="Equipment carried by this character: weapons, grenades, armor, and boosters. Customize a weapon from its own entry.",
    tabs=(
        Tab("primary_weapons", "Primary", "primary_weapons"),
        Tab("secondary_weapons", "Secondary", "secondary_weapons"),
        Tab("grenades", "Grenade", "grenades"),
        Tab("armor", "Armor", "armor"),
        Tab("boosters", "Booster", "boosters"),
    ),
)

SHIP_MANAGEMENT = Terminal(
    "ship_management", "Ship Management", short="SM",
    description="Stratagems called in from the Super Destroyer, including support weapons, and the ship's module upgrades.",
    tabs=(
        Tab("stratagems", "Stratagems", "stratagems"),
        Tab("ship_modules", "Ship Modules", "ship_modules"),
    ),
)

ACQUISITION_CENTER = Terminal(
    "acquisition_center", "Acquisition Center", short="AC",
    description="Warbonds and the rewards they contain. Warbond ownership, reward ownership, and page access are separate records.",
    tabs=(
        Tab("warbonds", "Warbonds", "warbonds"),
    ),
)

PLANNER = Terminal(
    "planner", "Planner", short="PL", planner=True,
    description="Planning records that have no in-game terminal: preferences, observations, saved loadouts, and ChatGPT context export.",
    tabs=(
        Tab("preferences", "Preferences"),
        Tab("observations", "Observations"),
        Tab("loadouts", "Saved Loadouts"),
        Tab("context_export", "Context Export"),
    ),
)

TERMINALS: tuple[Terminal, ...] = (ARMORY, SHIP_MANAGEMENT, ACQUISITION_CENTER, PLANNER)
SUPER_DESTROYER_TERMINALS: tuple[Terminal, ...] = tuple(terminal for terminal in TERMINALS if not terminal.planner)

# Views that belong to a tab without being a tab themselves. Each maps a route
# name to (terminal id, tab id, breadcrumb segment).
SUBVIEWS: dict[str, tuple[str, str, str]] = {
    "support_weapons": ("ship_management", "stratagems", "Support weapon records"),
    "warbond_contents": ("acquisition_center", "warbonds", "Warbond contents"),
    "weapon_customization": ("armory", "primary_weapons", "Customize"),
    "legacy_attachments": ("armory", "primary_weapons", "Legacy mod answers"),
}

# Presentation-order screens keyed by the inventory category they arrange.
PRESENTATION_SCREENS: dict[str, str] = {
    "warbonds": "acquisition_center_warbonds",
    "stratagems": "ship_management_stratagems",
    "support_weapons": "ship_management_stratagems",
    "ship_modules": "ship_management_ship_modules",
}
DEFAULT_PRESENTATION_SCREEN = "armory"


def terminal(terminal_id: str) -> Terminal | None:
    return next((value for value in TERMINALS if value.id == terminal_id), None)


def tab_for_category(category: str) -> tuple[Terminal, Tab] | None:
    for value in TERMINALS:
        for tab in value.tabs:
            if tab.category == category or tab.id == category:
                return value, tab
    return None


def location_for(route: str, *, category: str | None = None, trail: tuple[str, ...] = ()) -> Location | None:
    """Resolve a GUI route to the terminal and tab that should appear active."""
    direct = tab_for_category(route)
    if direct is not None:
        value, tab = direct
        return Location(value, tab, trail)
    if route in SUBVIEWS:
        terminal_id, tab_id, segment = SUBVIEWS[route]
        if route == "weapon_customization" and category:
            placed = tab_for_category(category)
            if placed is not None:
                terminal_id, tab_id = placed[0].id, placed[1].id
            elif category in SUBVIEWS:
                terminal_id, tab_id = SUBVIEWS[category][0], SUBVIEWS[category][1]
        value = terminal(terminal_id)
        if value is None:
            return None
        tab = value.tab(tab_id)
        if tab is None:
            return None
        return Location(value, tab, (segment, *trail) if not trail else trail)
    return None


def presentation_screen(category: str) -> str:
    return PRESENTATION_SCREENS.get(category, DEFAULT_PRESENTATION_SCREEN)


def tracked_categories() -> set[str]:
    """Inventory categories reachable through a terminal tab or a subview."""
    reached = {tab.category for value in TERMINALS for tab in value.tabs if tab.category}
    reached.update(route for route in SUBVIEWS if route in {"support_weapons"})
    return reached
