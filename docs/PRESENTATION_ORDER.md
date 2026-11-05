# Presentation-order evidence and status

`planner/presentation_order.json` is versioned presentation metadata. It is
separate from catalog facts, player profiles, and planner rules; the packaged
app uses it only to arrange supported inventory views.

## Screens

Screens follow the Super Destroyer terminal and tab the desktop interface
shows them under (see `hd2lib/navigation.py`):

| Screen id | Terminal › tab | Groups (from catalog facts) |
| --- | --- | --- |
| `acquisition_center_warbonds` | Acquisition Center › Warbonds | Warbonds |
| `ship_management_stratagems` | Ship Management › Stratagems | Stratagem type (`facts.category`): Support Weapons, Backpacks, Eagle, Orbital, Sentries, Emplacements, Vehicles, Other. Support weapon records share the Support Weapons group. |
| `ship_management_ship_modules` | Ship Management › Ship Modules | Department (`facts.path_id`): Patriotic Administration Center, Orbital Cannons, Hangar, Bridge, Engineering Bay, Robotics Workshop |
| `armory` | Armory › Primary / Secondary / Grenade / Armor / Booster, plus per-weapon Customize | One group per tab, plus Weapon customization |

The terminal and tab structure is the navigation layout requested for the
planner. It is not itself evidence of in-game item order, and the stratagem
type grouping is the catalog's grouping, not a claim about how the in-game
Stratagems tab arranges its headings.

## Current status

No complete in-game screenshots or recordings have been supplied. Every
shipped screen and group is therefore `unverified`, with empty explicit
item-order lists. The app uses a deterministic name/ID fallback (ship modules
additionally by tier) for items that do not have confirmed positions and says
that the display order is still being verified. It does not claim that the
fallback matches the game.

The catalog version linked by the document is `2026.09.21.2`. Its game build is
recorded as `unknown`; it must not be guessed from a catalog retrieval date.

## Screens that still need captures

Each of the following needs a complete, legible capture before any item order
can be recorded:

1. **Acquisition Center › Warbonds** — the Warbond list in its on-screen order.
2. **Acquisition Center › Warbonds › each Warbond** — every page of each
   Warbond, to confirm page membership, page order, and the on-page item order.
3. **Ship Management › Stratagems** — every heading and the item order under
   each, with enough scrolling to show the full sequence.
4. **Ship Management › Ship Modules** — each department and its module order.
5. **Armory › Primary, Secondary, Grenade, Armor, Booster** — each tab's full
   list.
6. **Armory › (weapon) › Customize** — the customization screen for at least
   one weapon per weapon family, to confirm slot headings and mod order.

Where network access allows, current official game references may help plan a
capture session, but they do not replace captures: the repository standard
below requires in-game evidence.

## Evidence required to verify an order

Use complete, legible in-game screenshots or recordings for the relevant
screen, including every visible group and enough scrolling to establish its
full sequence. Before marking a screen or group `verified`:

1. Record the capture date, game build when known, and a durable evidence
   reference in `capture`.
2. Match entries to existing stable catalog IDs; do not derive IDs from display
   names or add catalog facts here.
3. Fill only the observed group headings and `item_ids`, then mark only the
   supported group and screen verified.
4. Leave incomplete groups unverified and keep unobserved IDs out of the
   explicit order so their deterministic fallback remains honest.
5. Run the test suite and package checks; the document must continue to match
   the accepted catalog version and known item IDs.

This is a presentation-evidence task, not a catalog or progression migration.
