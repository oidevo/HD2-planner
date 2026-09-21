# Catalog snapshot

Catalog version: `2026.09.21.2`  
Schema version: `1.0.0`  
Game version: `unknown` (not inferred)  
Source retrieval date: 2026-09-21

The accepted snapshot contains 114 weapons, 30 distinct attachment records, 23 grenades, 109 body armor records, 110 helmets, no capes, 31 armor passives, 20 boosters, 115 stratagems, 30 ship modules, 24 warbonds, 115 enemies, 97 mission types/variants, and 31 biomes.

JSON in this directory is canonical game-data state. Facts, subjective planner tags, and provenance are separate fields. Do not edit generated context to correct catalog data; update an importer override, fetch a candidate catalog, compare it with this snapshot, review the diff, and only then accept it.

Deterministic derived fields carry field-level provenance; raw imported values remain for audit. Known gaps include complete Warbond reward graphs, attachment-specific effects/progression, enemy threat semantics, armor-passive effects, and environment mechanics. See `docs/PLANNER_READINESS.md`.
