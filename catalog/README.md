# Catalog snapshot

Catalog version: `2026.11.05.1`\
Schema version: `1.0.0`  
Game version: `unknown` (not inferred)  
Base snapshot retrieved 2026-09-21. Warbond reward tables retrieved 2026-11-05.

The accepted snapshot contains 114 weapons, 30 distinct attachment records, 23 grenades, 109 body armor records, 110 helmets, 31 armor passives, 20 boosters, 115 stratagems, 30 ship modules, 24 Warbonds, 562 Warbond rewards, 115 enemies, 97 mission types/variants, and 31 biomes. Reward rows with inventory links use the original equipment IDs for ownership. Warbond-only rows cover items such as capes and individual Super Credits claims.

JSON in this directory is canonical game-data state. Facts, subjective planner tags, and provenance are separate fields. Do not edit generated context to correct catalog data; update an importer override, fetch a candidate catalog, compare it with this snapshot, review the diff, and only then accept it.

Deterministic derived fields carry field-level provenance. Raw imported values remain for audit. Known gaps include Warbond page access, attachment-specific effects and progression, enemy threat semantics, armor-passive effects, and environment mechanics. See `docs/PLANNER_READINESS.md`.
