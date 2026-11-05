# Presentation-order evidence and status

`planner/presentation_order.json` is versioned presentation metadata. It is
separate from catalog facts, player profiles, and planner rules; the packaged
app uses it only to arrange supported inventory views.

## Current status

No complete in-game screenshots or recordings were supplied for this release.
Every shipped screen and group is therefore `unverified`, with empty explicit
item-order lists. The app uses a deterministic name/ID fallback for items that
do not have confirmed positions and says that the display order is still being
verified. It does not claim that the fallback matches the game.

The catalog version linked by the document is `2026.09.21.2`. Its game build is
recorded as `unknown`; it must not be guessed from a catalog retrieval date.

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

## Navigation references and captures needed

Official references place Stratagems and upgrades in Ship Management, place
Warbonds and their numbered reward pages in the Acquisition Center, and describe
leveling individual primary weapons to unlock attachments. The full tab labels,
group positions, and item sequences still need complete captures.
[Arrowhead's currency guide](https://arrowhead.zendesk.com/hc/en-us/articles/12517746921756-What-type-of-currencies-are-in-the-game) ·
[PlayStation's cadet guide](https://www.playstation.com/en-us/editorial/a-beginner-s-guide-to-helldivers-2/) ·
[Arrowhead's weapon customization announcement](https://blog.playstation.com/2025/05/13/helldivers-2-illuminate-set-sights-on-super-earth-new-enemy-types-deployed/)

- **Ship Management → Stratagems** needs the full department headings and item
  lists, including support-weapon placements and Warbond-linked Stratagems.
  The planner groups recognized sources by the department names in the catalog
  and provides a separate list for existing support-weapon records.
- **Ship Management → Ship Modules** needs the full department order and each
  department's upgrade sequence.
- **Armory → Weaponry** needs Primary, Secondary, and Throwables, including
  weapon-group headings and the Customize attachment slots and lists for
  compatible weapons. **Armory → Armory** needs the tracked Body Armor list.
  **Armory → Booster** needs the full booster list.
- **Acquisition Center → Warbonds** needs the full Warbond list, each Warbond's
  reward pages and layout, and any visible page-access requirements. Catalog
  page numbers help navigation. Page access remains unverified.

The app retains the deterministic item fallback within each displayed section.
