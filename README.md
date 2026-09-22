# Helldivers 2 Inventory Tracker and Loadout Planner

An offline-first, local Python tool for recording independent Helldivers 2 characters, validating saved loadouts, and generating concise files that humans or ChatGPT can use for loadout planning. Pass 1 establishes the data foundation; it intentionally does **not** contain a sophisticated recommendation engine.

The ordinary workflow is completely offline and uses only Python’s standard library. There is no web server, database server, Docker container, cloud account, authentication, or telemetry.

> **Canonical-data rule:** JSON is canonical. Markdown is generated. Never maintain the same state independently in both formats.

## Quick start

For Apple Silicon macOS, the recommended download is the self-contained `HD2 Planner.app`. It embeds Python 3.14.7 and Tcl/Tk 9.0.4, opens from Finder without a Terminal window, and does not require Homebrew or a separately installed Python. It is offline-first: launch does not contact the network, and all mutable player data remains in the external HD2 Planner data directory so it survives app replacement.

Maintainers and source/CLI users need a Tk-enabled Python 3.14 or newer. Verify the selected interpreter before running from source:

```text
python3.14 --version
python3.14 -c "import sys, tkinter; print(sys.executable); print(sys.version); print(tkinter.TkVersion)"
```

Then run:

```text
python3.14 hd2.py gui
```

### Apple Silicon macOS app

Build the ordinary source ZIP and self-contained app from a build-only virtual environment:

For the release build, `python3.14` must be the official Python.org 3.14.7 arm64 runtime with its matching Tk package. The packager rejects Homebrew-origin interpreters so their installation prefixes cannot leak into the distributable.

```text
python3.14 -m venv .build/macos
.build/macos/bin/python -m pip install -r requirements-build-macos.txt
.build/macos/bin/python -c "import tkinter, _tkinter; print('Tk OK')"
.build/macos/bin/python hd2.py package --macos-app
```

This creates `dist/HD2 Planner.app`, `dist/hd2-planner-<version>-macos-arm64.zip`, and the ordinary offline ZIP. Copy the app to Applications or the Desktop and double-click it. The bundle embeds its own arm64 Python/Tk runtime, immutable application and catalog, schemas, planner data, onboarding material, examples, and required licenses. It never reads `HD2_PLANNER_PYTHON`, invokes `/usr/bin/python3`, or depends on Homebrew at runtime. It never stores profiles, generated contexts, settings, backups, migration state, logs, or caches inside itself.

The tested embedded baseline is the official Python.org Python 3.14.7 runtime with Tcl/Tk 9.0.4, PyInstaller 6.22.3, arm64, and minimum macOS 11.0. The minimum follows the arm64 deployment target of the selected runtime. Settings reports the exact embedded Python and Tcl/Tk versions.

The app is intentionally unsigned and unnotarized. After download, Gatekeeper may require a one-time Finder contextual **Open** action. Keep Gatekeeper enabled; do not remove quarantine attributes or otherwise bypass macOS security protections.

The desktop checklist creates a player and character on first launch, saves inventory changes automatically, and can generate ChatGPT context files without command-line inventory entry. For source use, `python3.14 hd2_gui.py` is equivalent to `python3.14 hd2.py gui`. Tkinter comes from the Python installation rather than an ordinary runtime dependency.

The CLI remains available for scripted and terminal workflows, including machines with no display server, as long as the supported Python version is installed:

```text
python3.14 hd2.py setup
python3.14 hd2.py export-context --player your_id --character main
```

CLI setup saves after each section and can be stopped and resumed. See [onboarding/LOCAL_SETUP.md](onboarding/LOCAL_SETUP.md) for a transcript and command details.

Player-owned data is stored outside the downloaded application folder. Run `python3.14 hd2.py data-dir` to see its exact location. Generated files appear under `<data-dir>/generated/<player-id>/`. Upload either the Markdown or JSON context to ChatGPT; both are self-contained enough to interpret basic inventory without the catalog.

## Updating HD2 Planner

Run `python3.14 hd2.py update-check`. If an update is available, it prints the matching GitHub Release page. Download its `helldivers-planner-<version>.zip`, unzip it, and replace the old application folder; then run `python3.14 hd2.py version` and start normally. The app never downloads or installs an update itself.

Your profiles, loadouts, preferences, observations, generated contexts, settings, migration records, and backups live separately and are not affected by replacing the application folder. Supported older profiles are migrated when opened after a timestamped backup is made. To explicitly process all profile migrations, run `python3.14 hd2.py migrate`.

Pre-0.2 checkouts may contain personal files under `profiles/` or `generated/`. Run `python3.14 hd2.py migrate-local-data` once to copy those files into the persistent location. It never deletes the originals and never overwrites an existing destination file; collisions are reported.

## Architecture

The repository deliberately separates:

- `catalog/`: versioned game facts and first-class provenance.
- `<data-dir>/profiles/`: canonical player state, preferences, and scoped experiences. Each character has an independent inventory.
- `<data-dir>/loadouts/`, `<data-dir>/generated/`, `<data-dir>/settings.json`, `<data-dir>/backups/`, and `<data-dir>/migrations/`: persistent personal state. `profiles/example_player.json` is source-controlled sample data only.
- `community/`: dated third-party/meta observations, separate from facts.
- `planner/`: explicit planner policy and later assessments, separate from facts and community opinion.
- `schemas/`: JSON Schema documentation for catalog, profile, loadout, community, rules, and generated context.
- `<data-dir>/generated/`: disposable JSON/Markdown presentation snapshots. Every export contains source fingerprints and a do-not-edit warning.
- `importer/`: maintainer-only Cargo/MediaWiki updater and review workflow. Normal use never invokes it.
- `onboarding/`: local and ChatGPT-assisted onboarding guidance.
- `tests/`: standard-library automated tests.

Catalog items have stable machine IDs such as `mg_43_machine_gun`; display names are not keys. Factual fields live in `facts`. Subjective semantic tags live in `planner_tags` and carry an origin. Imported records retain source page, URL, MediaWiki revision, retrieval time, and importer version.

Catalog metadata keeps `schema_version`, `catalog_version`, `game_version`, and `generated_at` distinct. `game_version` is `unknown` in the initial snapshot because the structured source did not expose a single reliable current game-build identifier; the retrieval and catalog versions remain precise.

`python3.14 hd2.py version` reports three independent values: application version (from `VERSION`), catalog version (from `catalog/catalog_manifest.json`), and profile schema version. `HD2_PLANNER_DATA_DIR` can override the data directory for portable/testing use. The release endpoint defaults to `oidevo/HD2-planner` and can be changed with `HD2_PLANNER_REPOSITORY=owner/repo`; private repositories require a publicly accessible release endpoint because update checks intentionally do not authenticate.

### Persistent data location

- macOS: `~/Library/Application Support/HD2 Planner/`

### Maintainer release workflow

1. Update `VERSION` and relevant changelog/catalog metadata.
2. Run the Python 3.14 source tests, catalog/example validation, app build, static bundle inspection, restricted-environment GUI smoke test, and extracted-package tests in [docs/MACOS_APP.md](docs/MACOS_APP.md).
3. Signing, notarization, tagging, pushing, and GitHub Release creation are separate, explicitly authorized release operations.

## Multiple characters and preferences

One profile represents a player and can hold any number of independent characters, such as PC and Xbox. Nothing is copied between their inventories. Player-level preferences are inherited; a character’s `preference_overrides` wins for that character. Unlock status (`unknown`, `locked`, `unlocked`) is independent from preference (`favorite`, `like`, `neutral`, `dislike`, `avoid`).

Optional resource balances may record medals, requisition, samples, and super credits. They are never required.

## Local onboarding and inventory maintenance

The recommended interactive workflow is the desktop checklist:

```text
python3.14 hd2.py gui
```

Its compact navigation rail switches independent characters without restarting. Inventory screens provide live search, status/Warbond/group filters, visible-only bulk actions, a responsive item inspector, and explicit `unlocked`, `locked`, and `unknown` states. Double-click or Space toggles an item between unlocked and unknown; right-click exposes all three states. Character levels and optional resource balances can be edited directly from the character card. Every mutation is validated and written atomically to the same external JSON profile used by the CLI.

The Primaries, Secondaries, and Support Weapons screens can record an optional weapon level. Compatible attachments are shown from catalog relationships; their current ownership state remains global because the catalog does not reliably expose per-weapon attachment progression. Preferences, gameplay observations, saved-loadout validation, context generation, update checking, and data-directory information are available as lightweight secondary screens.

The equivalent CLI workflow starts or resumes with:

Start or resume with:

```text
python3.14 hd2.py setup
python3.14 hd2.py inventory review --player alex --character pc --category primaries
python3.14 hd2.py inventory review --player alex --character pc --category stratagems
python3.14 hd2.py inventory review --player alex --character pc --category primaries --warbond cutting_edge
```

An entire category can be skipped. Enter `q` while reviewing an item to stop setup immediately; answers already entered are saved and that category remains incomplete so it can be resumed. Setup distinguishes an unanswered item from a known locked item and writes progress atomically, reducing the chance of a partial/corrupt profile.

## ChatGPT-assisted onboarding

Paste [onboarding/CHATGPT_ONBOARDING_PROMPT.md](onboarding/CHATGPT_ONBOARDING_PROMPT.md) into ChatGPT. It directs ChatGPT to interview in manageable sections, preserve character independence, avoid inferred unlocks, and return schema-compatible JSON. Save that JSON and import it:

```text
python3.14 hd2.py profile import onboarding-result.json
```

The candidate is fully validated before any profile is modified. Existing profiles require explicit `--overwrite`.

## Context export and integrity

```text
python3.14 hd2.py export-context --player alex --character pc
python3.14 hd2.py validate-generated <data-dir>/generated/alex/pc-context.md --player alex
python3.14 hd2.py validate-generated <data-dir>/generated/alex/pc-context.json --player alex
```

The denormalized JSON contains player, character, inventory names and statuses, preferences, resources, observations, loadouts, versions, and timestamps. Markdown is shorter and organized for an LLM. Both embed SHA-256 fingerprints of the canonical profile and catalog. Export validates the full profile first; fix every reported error with `python3.14 hd2.py profile validate <data-dir>/profiles/your_id.json` before retrying. Validation returns nonzero when either source changed after export.

## Saved loadouts

Loadouts are portable JSON containing only stable item IDs and planning context. They are character-independent until validated:

```text
python3.14 hd2.py loadout validate examples/profiles/loadouts/example_illuminate_general.json --player example_player --character main
```

The result separates usable, locked/missing, and unknown items. No substitution or recommendation logic is attempted. Share a loadout file directly with a friend; their validation result reflects their own character inventory.

## Catalog updates (maintainers)

The packaged catalog is a known-good offline snapshot. Updating it is a deliberate review operation:

```text
python3.14 hd2.py catalog fetch --output catalog-staging --catalog-version 2026.09.21.2 --game-version unknown
python3.14 hd2.py catalog compare catalog catalog-staging --output catalog-review
python3.14 hd2.py catalog validate catalog-staging
```

The importer prefers Cargo, uses MediaWiki page/category data only for gaps, serializes requests, backs off on rate limits, and does not crawl general HTML. It does not overwrite the accepted catalog. The review contains unchanged/changed/added/removed/requires-review counts and before/after JSON. Manual overrides in `importer/overrides/` retain separate provenance.

## Sharing and packaging

```text
python3.14 hd2.py package
```

This creates `dist/helldivers-planner-<version>.zip` with the application, catalog snapshot, example profile/loadout under `examples/`, onboarding documents, schemas, tests, README, and attribution. It excludes all real profiles, loadouts, generated contexts, settings, backups, caches, staging/raw importer data, and virtual environments. Friends unzip it, run setup, export context, and work offline.

To additionally create the self-contained Apple Silicon app and its copyable archive, run `python3.14 hd2.py package --macos-app` from the activated build environment. See [Apple Silicon macOS app](#apple-silicon-macos-app) and [docs/MACOS_APP.md](docs/MACOS_APP.md).

## Tests

```text
python3.14 -m unittest discover -s tests -v
```

The suite covers independent character inventories, GUI filtering and bulk state changes, GUI/CLI profile interoperability, autosave, weapon progression and attachment state, preference inheritance/overrides, state distinctions, schema validation, bad IDs, loadout availability, deterministic exports, update-service delegation, stale detection, atomic onboarding import, provenance, catalog diffs, package privacy, and offline operation. Most GUI behaviour is tested through the display-independent application service.

## Known limitations

- The initial catalog is broad but not guaranteed complete; wiki data changes and some progression relationships are embedded in source wikitext rather than normalized fields.
- Attachment compatibility is normalized to weapon IDs, but attachment costs, per-weapon effects, progression requirements, and per-weapon unlock state were not exposed reliably by the structured table.
- Warbond reward-side page/cost relationships are partially normalized. Page gates, dependencies, complete rewards, and player claim state remain unavailable; no prose was copied to fill gaps.
- The current snapshot’s exact game build is unknown and is not fabricated.
- The snapshot distinguishes 109 body armor records from 110 helmets; no cape records were imported. The armor inventory UI records body armor only.
- This release artifact supports Apple Silicon macOS only, with minimum macOS 11.0 for the selected embedded runtime. It is not an Intel or universal app.
- The app is unsigned and unnotarized, so downloaded copies may require the one-time Finder contextual **Open** action.
- The ordinary ZIP is a source/developer artifact that requires a suitable Python 3.14 environment; it is not the recommended Mac end-user download.
- There is no automatic save-game import, live meta feed, recommendation engine, or loadout substitution engine.

## Second-pass direction

Follow the gate in `docs/PLANNER_READINESS.md`. A first recommendation slice may use the reviewed fixture, normalized facts, explicit constraints, and curated capability tags. Keep attachment progression, Warbond strategy, and general enemy threat scoring blocked until their source data is repaired. Keep personal experience and dated community evidence as scoped inputs—not facts.
