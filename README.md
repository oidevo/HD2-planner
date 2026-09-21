# Helldivers 2 Inventory Tracker and Loadout Planner

An offline-first, local Python tool for recording independent Helldivers 2 characters, validating saved loadouts, and generating concise files that humans or ChatGPT can use for loadout planning. Pass 1 establishes the data foundation; it intentionally does **not** contain a sophisticated recommendation engine.

The ordinary workflow is completely offline and uses only Python’s standard library. There is no web server, database server, Docker container, cloud account, authentication, or telemetry.

> **Canonical-data rule:** JSON is canonical. Markdown is generated. Never maintain the same state independently in both formats.

## Quick start

Install Python 3.10 or newer, download or unzip this project, open a terminal in the project folder, and run:

```text
python hd2.py setup
python hd2.py export-context --player your_id --character main
```

Windows users may use `py hd2.py ...`. Setup saves after each section and can be stopped and resumed. See [onboarding/LOCAL_SETUP.md](onboarding/LOCAL_SETUP.md) for a transcript and command details.

Generated files appear under `generated/<player-id>/`. Upload either the Markdown or JSON context to ChatGPT; both are self-contained enough to interpret basic inventory without the catalog.

## Architecture

The repository deliberately separates:

- `catalog/`: versioned game facts and first-class provenance.
- `profiles/`: canonical player state, preferences, scoped experiences, and an example profile. Each character has an independent inventory.
- `community/`: dated third-party/meta observations, separate from facts.
- `planner/`: explicit planner policy and later assessments, separate from facts and community opinion.
- `schemas/`: JSON Schema documentation for catalog, profile, loadout, community, rules, and generated context.
- `generated/`: disposable JSON/Markdown presentation snapshots. Every export contains source fingerprints and a do-not-edit warning.
- `importer/`: maintainer-only Cargo/MediaWiki updater and review workflow. Normal use never invokes it.
- `onboarding/`: local and ChatGPT-assisted onboarding guidance.
- `tests/`: standard-library automated tests.

Catalog items have stable machine IDs such as `mg_43_machine_gun`; display names are not keys. Factual fields live in `facts`. Subjective semantic tags live in `planner_tags` and carry an origin. Imported records retain source page, URL, MediaWiki revision, retrieval time, and importer version.

Catalog metadata keeps `schema_version`, `catalog_version`, `game_version`, and `generated_at` distinct. `game_version` is `unknown` in the initial snapshot because the structured source did not expose a single reliable current game-build identifier; the retrieval and catalog versions remain precise.

## Multiple characters and preferences

One profile represents a player and can hold any number of independent characters, such as PC and Xbox. Nothing is copied between their inventories. Player-level preferences are inherited; a character’s `preference_overrides` wins for that character. Unlock status (`unknown`, `locked`, `unlocked`) is independent from preference (`favorite`, `like`, `neutral`, `dislike`, `avoid`).

Optional resource balances may record medals, requisition, samples, and super credits. They are never required.

## Local onboarding and inventory maintenance

Start or resume with:

```text
python hd2.py setup
python hd2.py inventory review --player alex --character pc --category primaries
python hd2.py inventory review --player alex --character pc --category stratagems
python hd2.py inventory review --player alex --character pc --category primaries --warbond cutting_edge
```

An entire category can be skipped. Setup distinguishes an unanswered item from a known locked item and writes progress atomically, reducing the chance of a partial/corrupt profile.

## ChatGPT-assisted onboarding

Paste [onboarding/CHATGPT_ONBOARDING_PROMPT.md](onboarding/CHATGPT_ONBOARDING_PROMPT.md) into ChatGPT. It directs ChatGPT to interview in manageable sections, preserve character independence, avoid inferred unlocks, and return schema-compatible JSON. Save that JSON and import it:

```text
python hd2.py profile import onboarding-result.json
```

The candidate is fully validated before any profile is modified. Existing profiles require explicit `--overwrite`.

## Context export and integrity

```text
python hd2.py export-context --player alex --character pc
python hd2.py validate-generated generated/alex/pc-context.md --player alex
python hd2.py validate-generated generated/alex/pc-context.json --player alex
```

The denormalized JSON contains player, character, inventory names and statuses, preferences, resources, observations, loadouts, versions, and timestamps. Markdown is shorter and organized for an LLM. Both embed SHA-256 fingerprints of the canonical profile and catalog. Validation returns nonzero when either source changed after export.

## Saved loadouts

Loadouts are portable JSON containing only stable item IDs and planning context. They are character-independent until validated:

```text
python hd2.py loadout validate profiles/loadouts/example_illuminate_general.json --player example_player --character main
```

The result separates usable, locked/missing, and unknown items. No substitution or recommendation logic is attempted. Share a loadout file directly with a friend; their validation result reflects their own character inventory.

## Catalog updates (maintainers)

The packaged catalog is a known-good offline snapshot. Updating it is a deliberate review operation:

```text
python hd2.py catalog fetch --output catalog-staging --catalog-version 2026.09.21.2 --game-version unknown
python hd2.py catalog compare catalog catalog-staging --output catalog-review
python hd2.py catalog validate catalog-staging
```

The importer prefers Cargo, uses MediaWiki page/category data only for gaps, serializes requests, backs off on rate limits, and does not crawl general HTML. It does not overwrite the accepted catalog. The review contains unchanged/changed/added/removed/requires-review counts and before/after JSON. Manual overrides in `importer/overrides/` retain separate provenance.

## Sharing and packaging

```text
python hd2.py package
```

This creates `dist/helldivers-planner-0.1.0.zip` with the application, catalog snapshot, example profile/loadout, onboarding documents, schemas, tests, README, and attribution. It excludes caches, staging/raw importer data, generated files, and every non-example profile. Friends unzip it, run setup, export context, and work offline.

## Tests

```text
python -m unittest discover -s tests -v
```

The suite covers independent character inventories, preference inheritance/overrides, state distinctions, schema validation, bad IDs, loadout availability, deterministic exports, stale detection, atomic onboarding import, provenance, catalog diffs, package privacy, and offline operation.

## Known limitations

- The initial catalog is broad but not guaranteed complete; wiki data changes and some progression relationships are embedded in source wikitext rather than normalized fields.
- Attachment compatibility is normalized to weapon IDs, but attachment costs, per-weapon effects, progression requirements, and per-weapon unlock state were not exposed reliably by the structured table.
- Warbond reward-side page/cost relationships are partially normalized. Page gates, dependencies, complete rewards, and player claim state remain unavailable; no prose was copied to fill gaps.
- The current snapshot’s exact game build is unknown and is not fabricated.
- The snapshot distinguishes 109 body armor records from 110 helmets; no cape records were imported. The inventory UI currently reviews armor records in one category.
- There is no GUI, automatic save-game import, live meta feed, recommendation engine, or loadout substitution engine in Pass 1.

## Second-pass direction

Follow the gate in `docs/PLANNER_READINESS.md`. A first recommendation slice may use the reviewed fixture, normalized facts, explicit constraints, and curated capability tags. Keep attachment progression, Warbond strategy, and general enemy threat scoring blocked until their source data is repaired. Keep personal experience and dated community evidence as scoped inputs—not facts.
