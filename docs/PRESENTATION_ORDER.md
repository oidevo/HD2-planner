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

Needed coverage includes Requisitions/Warbonds, Stratagems and its headings,
Ship Management, and every Armory category. This is a presentation-evidence
task, not a catalog or progression migration.
