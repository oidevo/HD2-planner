# Apple Silicon macOS application

`HD2 Planner.app` is the recommended Mac end-user artifact. It is a self-contained, windowed Apple Silicon application: users can double-click it without Homebrew, Terminal, `HD2_PLANNER_PYTHON`, or a separately installed Python. Normal launch is offline and does not write inside the app bundle.

## Tested build baseline

- Application version: read from the canonical `VERSION` file
- Bundle identifier: `com.oidevo.hd2-planner`
- Architecture: `arm64` only
- Minimum macOS: 11.0
- Embedded Python: 3.14.7
- Embedded Tcl/Tk: 9.0.4
- Build-only PyInstaller: 6.22.3
- Signing/notarization: no Developer ID signature and no notarization

The minimum macOS version reflects the arm64 deployment target declared by the official Python.org Python and Tk binaries used for this build.

## Build

Use the official Python.org Python 3.14.7 arm64 runtime with its matching Tk package and a clean local virtual environment, so PyInstaller is never installed as an application runtime dependency or globally. The packager rejects Homebrew-origin interpreters to prevent their installation prefixes from entering the distributable.

```text
python3.14 -m venv .build/macos
.build/macos/bin/python -m pip install -r requirements-build-macos.txt
.build/macos/bin/python -c "import sys, tkinter, _tkinter; print(sys.version); print(tkinter.Tcl().eval('info patchlevel'))"
.build/macos/bin/python hd2.py package --macos-app
```

The command creates the ordinary offline source ZIP plus:

- `dist/HD2 Planner.app`
- `dist/hd2-planner-<version>-macos-arm64.zip`

The PyInstaller specification is `build-support/macos/hd2_planner.spec`. Generated bundles, virtual environments, work directories, and caches are ignored by Git.

## Data and privacy boundary

Immutable catalog, schemas, planner inputs, onboarding documentation, examples, version metadata, application code, and license material are read from the frozen bundle. Profiles, loadouts, generated contexts, preferences/settings, backups, migration state, logs, and caches remain exclusively in the established external data directory. Replacing the app therefore does not replace user data. `HD2_PLANNER_DATA_DIR` remains available for isolated testing and CLI/source workflows; `HD2_PLANNER_PYTHON` has no effect on the embedded app.

The frozen resources include `planner/presentation_order.json`; it is immutable presentation metadata linked to the packaged catalog version, not a player-data file or a game-fact catalog. Appearance, pinned navigation, and inspector width are stored only in the external `settings.json`. Character deletion and profile migration backups are written only to the external `backups/` directory.

The archive and app must not include real profiles, generated output, settings, backups, migration state, logs, caches, tests, fixtures, build tools, virtual environments, Git data, or machine-specific paths.

The official runtime contains compiler-host source paths for diagnostics. Packaging replaces only those fixed-length home-directory prefixes with neutral embedded-source prefixes, then applies the ad-hoc signatures required for arm64 loading. It does not add a Developer ID signature or notarization.

## Verification checklist

Run every check with the selected Tk-enabled Python 3.14.7 build environment:

1. `python -m unittest discover -s tests -v`
2. `python hd2.py catalog validate catalog`
3. `python hd2.py profile validate profiles/example_player.json`
4. `python hd2.py package --macos-app`
5. Set `HD2_TEST_MACOS_APP` to the final app path and rerun the tests.
6. Inspect all Mach-O files with `file`, `lipo`, and `otool -L`; require arm64 only and no Homebrew, user-home, or system-Python dependency.
7. Copy the app outside the repository, record its digest, and launch it with a restricted `PATH` and an invalid `HD2_PLANNER_PYTHON` value.
8. Exercise System, Light, and Dark appearance, including navigation, tables, inspector, dialogs, menus, selections, and disabled controls. Confirm a real dark-mode launch is readable and System follows a live macOS appearance change.
9. Exercise profile creation/opening, level, resources, inventory, Warbond ownership and known-content browsing, preferences, character deletion/backup/cancellation, context generation, restart persistence, and CLI interoperability against disposable external data. The frozen entry point exposes `--release-verify-seed` and `--release-verify-reopen` solely for this isolated release check; both refuse to run without an explicit `HD2_PLANNER_DATA_DIR`.
10. Confirm the app digest did not change.
11. Extract the ordinary ZIP and run its complete test suite.
12. Run `git diff --check` and inspect the final diff/status for generated or private data.

## Unsigned distribution

The app is intentionally unsigned with an Apple Developer identity and unnotarized. PyInstaller may apply ad-hoc signatures required for local Apple Silicon Mach-O loading; these do not establish developer identity or Gatekeeper trust. A downloaded copy may require the user to choose Finder’s contextual **Open** action once. Do not advise users to disable Gatekeeper, remove quarantine attributes, or otherwise bypass macOS protections.

No Intel, universal, Windows, or Linux release artifact is produced by this workflow.
