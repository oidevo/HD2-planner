# Helldivers 2 Inventory Tracker and Loadout Planner

An offline, local-first Helldivers 2 inventory tracker. It records what each
of your characters owns and exports that inventory plus planning preferences as
ChatGPT context—without sending it anywhere itself.

## Releases

The supported end-user release is a self-contained, unsigned Apple Silicon
macOS app (`HD2 Planner.app`). It runs locally and does not need Homebrew,
Terminal, or a separate Python installation. The project also provides an
ordinary offline source ZIP for people who want to run or inspect the source.
Python 3.14 is required only for source and developer workflows.

### Download and run on macOS

Download the Apple Silicon `.app` archive from the matching GitHub Release,
unzip it, then move `HD2 Planner.app` to Applications or another folder you
control. If macOS blocks the first launch because the app is unsigned, keep
Gatekeeper enabled: in Finder, Control-click the app, choose **Open**, and
confirm the one-time prompt. Do not disable Gatekeeper or remove quarantine
attributes.

The bundle is replaceable application code. Your profiles, loadouts, settings,
backups, and generated context stay outside it at:

```text
~/Library/Application Support/HD2 Planner/
```

Replacing the app therefore preserves your data. The app’s **Data directory**
screen and `python3.14 hd2.py data-dir` show the active location.

For build details, release verification, architecture, and the unsigned-app
boundary, see [Apple Silicon macOS app documentation](docs/MACOS_APP.md).

## What it does today

- Tracks independent inventories for multiple characters/accounts.
- Records player and character preferences, optional resource balances,
  weapon levels, scoped observations, and saved loadouts.
- Uses explicit availability: **unlocked** is known usable now, **locked** is
  known unavailable, and **unknown** has not been recorded. Availability and
  preference are deliberately separate.
- Provides a local GUI plus resumable CLI onboarding and inventory review.
- Exports self-contained Markdown and JSON context files for ChatGPT. Upload a
  file yourself when you want to use it; the app never calls ChatGPT.
- Packages an ordinary offline source ZIP and a separate Apple Silicon app
  archive for GitHub Releases.

The GUI is an inventory workspace, not an advisor. It has no recommendation or
scoring engine and does not automatically choose or modify a loadout.

### Warbonds and presentation order

Marking a Warbond unlocked means that the Warbond itself is owned. It does not
unlock linked rewards: the catalog does not yet contain a complete reward,
page-gate, dependency, or claim-state graph.

Game-screen order is tracked separately from catalog facts. No complete
in-game captures were supplied for this release, so the shipped presentation
order remains unverified and the UI uses an honest deterministic fallback. It
does **not** claim that this fallback is the game’s order. See
[presentation-order evidence and status](docs/PRESENTATION_ORDER.md).

## Privacy and offline behavior

Normal inventory, profile, export, and GUI workflows work offline. Personal
data is written only to the external data directory using validated atomic
writes. The accepted catalog is a bundled snapshot. Network access is limited
to explicit maintainer catalog-import commands and the opt-in update check;
neither downloads or installs anything automatically.

## Get started from source

For a source checkout or the ordinary source ZIP, install Python 3.14 with Tk
support for the GUI, then run:

```text
python3.14 hd2.py gui
```

Or begin in the CLI:

```text
python3.14 hd2.py setup
python3.14 hd2.py export-context --player your_id --character main
```

The [local setup and developer walkthrough](onboarding/LOCAL_SETUP.md) covers
the setup flow, data location, CLI review commands, and macOS build environment.
The [ChatGPT-assisted onboarding prompt](onboarding/CHATGPT_ONBOARDING_PROMPT.md)
is available if you prefer to create an importable profile through a guided
conversation.

### Build from source

Build the ordinary offline source ZIP with Python 3.14:

```text
python3.14 hd2.py package
```

This creates `dist/helldivers-planner-<version>.zip`. It includes the durable
source, documentation, catalog, schemas, planner data, examples, tests, and
licenses; it excludes personal profiles, generated context, caches, virtual
environments, staging data, and release build output.

To additionally build the self-contained Apple Silicon app and app archive,
use the exact Python.org 3.14.7 arm64/Tk environment described in
[docs/MACOS_APP.md](docs/MACOS_APP.md):

```text
.build/macos/bin/python hd2.py package --macos-app
```

The generated ZIPs and `.app` bundle belong in GitHub Releases, not in the
repository.

### Run tests and validate data

```text
python3.14 -m unittest discover -s tests -v
python3.14 hd2.py catalog validate catalog
python3.14 hd2.py profile validate profiles/example_player.json
```

## Repository layout

```text
build-support/macos/  PyInstaller input for the Apple Silicon app
catalog/              Accepted offline catalog snapshot and provenance
community/            Separate, dated community-observation structure
docs/                 Focused release, readiness, and order documentation
hd2lib/               Application, CLI, profile, export, and packaging code
importer/             Maintainer-only catalog import and review tooling
onboarding/           Local setup and ChatGPT-assisted profile guidance
planner/              Rules, constraints, capabilities, and order metadata
profiles/             Source-controlled example profile and loadout only
schemas/              Versioned JSON schemas
tests/                Regression and packaging coverage
```

See [catalog documentation](catalog/README.md),
[importer documentation](importer/README.md),
[planner readiness](docs/PLANNER_READINESS.md), and
[planner data notes](planner/README.md) for the focused details.

## Project limitations

- There is no recommendation, ranking, or loadout-substitution engine.
- Complete Warbond reward dependencies, page gates, and reward claim state are
  not modeled.
- No verified in-game presentation order is shipped until complete captures
  are supplied and recorded as evidence.
- Some catalog relationships—especially attachment progression/effects,
  enemy semantics, armor-passive mechanics, and environment mechanics—remain
  incomplete or intentionally unscored.
- The supported packaged release is Apple Silicon macOS (minimum macOS 11);
  there is no Windows or Linux release.

The project does not fabricate missing catalog facts or game-order claims to
fill those gaps.
