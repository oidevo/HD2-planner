# Changelog

## 0.5.0 — 2026-09-22

- Redesigned the inventory workspace around clearer category navigation, compact progress-oriented rows, responsive inspectors, and focused bulk actions so players can review and maintain a character's equipment with less visual friction.
- Added guided inventory review, Warbond ownership and known-content browsing, and richer character-resource editing while preserving the distinction between an unrecorded value and an explicit zero.
- Kept character data isolated, validated, and atomically written; compatible existing profiles continue to load and the catalog and profile-schema versions remain unchanged.
- Expanded the release workflow to publish both the ordinary offline source ZIP and the unsigned, self-contained Apple Silicon macOS app archive from the same GitHub Release. The macOS artifact is built and verified on Apple Silicon with the pinned Python.org Python 3.14.7, Tcl/Tk 9.0.4, and PyInstaller 6.22.3 baseline.

## 0.4.0 — 2026-09-21

- Added an unsigned, self-contained Apple Silicon `HD2 Planner.app` built with PyInstaller 6.22.3 and embedding tested Python 3.14.7 plus Tcl/Tk 9.0.4; the embedded app requires no external Python and ignores `HD2_PLANNER_PYTHON`.
- Raised the source baseline to Python 3.14, added frozen immutable-resource resolution, exact runtime versions in Settings, arm64/runtime/privacy verification, and an Apple-Silicon-specific app archive while preserving the ordinary offline ZIP.
- Kept all mutable player data in the established external directory and left profile/catalog schemas, catalog version, migrations, CLI behavior, and atomic writes unchanged.
- Redesigned the Tkinter/ttk interface as a focused inventory-planning workspace with compact grouped navigation, a clear active state, restrained native styling, responsive inventory inspectors, aligned filtering, review progress, and contextual bulk actions.
- Added focused character-resource editing for medals, requisition slips, super credits, and sample balances. Blank values remain unrecorded, zero remains explicit, character isolation is preserved, and writes continue through the validated atomic profile path.
- Reworked first-run setup, preferences, settings, update results, confirmations, and context-generation dialogs. Preferences now show explicit non-neutral choices instead of the neutral catalog default.
- Added resource balances to Markdown context snapshots and clarified that context generation creates local Markdown/JSON files for ChatGPT without calling ChatGPT or making recommendations.
- Expanded automated coverage for resource validation, blank-versus-zero behavior, atomic rollback, character isolation, context inclusion, explicit preferences, GUI persistence, CLI interoperability, dialogs, and release-package privacy.
- Kept the catalog version and profile schema version unchanged; existing external user-data locations and compatible profiles remain intact.

## 0.2.1 — 2026-09-21

- Raised the supported runtime minimum to Python 3.14; the desktop interface now consistently directs users to a Tk-enabled Python 3.14+ installation and reports the executable and detected version when Tkinter is absent.
- Completed the Tkinter/ttk desktop inventory GUI, including canonical validated atomic autosave, character switching and isolation, filters and visible-only bulk state changes, weapon levels, attachment handling, preferences, observations, loadout validation, context generation, and offline-safe update checks.
- Kept profiles, loadouts, contexts, settings, migrations, and backups in external per-user data paths; the release ZIP contains examples only and excludes personal runtime data.
- Existing catalog version and profile schema version are unchanged. CLI-only workflows remain available on supported Python when no display is available.

- Added a Tkinter/ttk desktop checklist launched with `python3.14 hd2.py gui` or `python3.14 hd2_gui.py`.
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
