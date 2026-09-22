# Changelog

## 0.2.1 — 2026-09-21

- Raised the supported runtime minimum to Python 3.12; the desktop interface now consistently directs users to a Tk-enabled Python 3.12+ installation and reports the executable and detected version when Tkinter is absent.
- Completed the Tkinter/ttk desktop inventory GUI, including canonical validated atomic autosave, character switching and isolation, filters and visible-only bulk state changes, weapon levels, attachment handling, preferences, observations, loadout validation, context generation, and offline-safe update checks.
- Kept profiles, loadouts, contexts, settings, migrations, and backups in external per-user data paths; the release ZIP contains examples only and excludes personal runtime data.
- Existing catalog version and profile schema version are unchanged. CLI-only workflows remain available on supported Python when no display is available.

- Added a Tkinter/ttk desktop checklist launched with `python3.12 hd2.py gui` or `python3.12 hd2_gui.py`.
- Added display-independent GUI service logic for canonical profile loading, validated atomic autosave, character switching, filtering, visible-only bulk changes, preferences, observations, and loadout validation.
- Added optional weapon-level metadata and compatible-attachment views without inventing unsupported per-weapon attachment progression.
- Reused the existing context exporter and update checker, kept all user data external, and included GUI files in release packages.
- Added automated GUI-service coverage for character isolation, state transitions, filters, persistence, CLI interoperability, export/update delegation, and external data paths.

## 0.2.0 — 2026-09-21

- Moved runtime personal data to a per-user OS data directory with a safe legacy-copy command.
- Added version reporting, GitHub Release checks, explicit profile migrations with backups, and release-safe packaging.

## Unreleased — planner-readiness audit

- Added deterministic catalog normalization with field-level provenance for planner-critical relationships and typed values.
- Distinguished player-equippable stratagems, support-weapon links, backpack use, armor slots/passives, attachment compatibility, Warbond reward links, ship-module prerequisites, and unambiguous faction IDs.
- Added explicit capability vocabulary, mechanical constraints, reviewed planner fixtures, stricter slot validation, and readiness tests.
- Documented blocking Warbond, attachment, enemy, mission, armor-passive, ship-effect, and biome gaps without adding recommendation logic.

## 0.1.0 — 2026-09-21

- Established offline JSON-first architecture and versioned catalog snapshot.
- Added multi-character profiles, inherited preferences, scoped observations, saved loadouts, interactive onboarding, ChatGPT onboarding import, context export, staleness checks, structured wiki ingestion, catalog review, packaging, and tests.
- Deliberately deferred recommendation and substitution logic.
