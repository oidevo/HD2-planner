# Local setup walkthrough

The recommended Apple Silicon macOS download is `HD2 Planner.app`. It embeds the tested Python 3.14.7 and Tcl/Tk 9.0.4 runtimes, needs no Homebrew, Terminal, or separately installed Python, and remains offline-first. The app stores mutable data externally under `~/Library/Application Support/HD2 Planner/`, so replacing the app preserves profiles and generated context.

Source and CLI use require Python 3.14 or newer. The desktop GUI additionally needs matching Tk support from that Python installation. No server, account, or network connection is needed for normal use.

Profiles, loadouts, and generated context are stored in your operating system's HD2 Planner data directory, not alongside the downloaded application. Print it with `python3.14 hd2.py data-dir`.

Verify a Tk-enabled runtime before launching the GUI:

```text
python3.14 --version
python3.14 -c "import sys, tkinter; print(sys.executable); print(sys.version); print(tkinter.TkVersion)"
python3.14 hd2.py gui
```

## Apple Silicon macOS app

To build the double-clickable self-contained app, create an isolated build environment with the pinned build-only dependency:

For a release build, `python3.14` must resolve to the official Python.org 3.14.7 arm64 runtime with its matching Tk package. The packager rejects Homebrew-origin interpreters so their installation prefixes cannot enter the app.

```text
python3.14 -m venv .build/macos
.build/macos/bin/python -m pip install -r requirements-build-macos.txt
.build/macos/bin/python -c "import tkinter, _tkinter; print('Tk OK')"
.build/macos/bin/python hd2.py package --macos-app
```

It builds the normal offline ZIP plus `dist/HD2 Planner.app` and `dist/hd2-planner-<version>-macos-arm64.zip`. Move or copy `HD2 Planner.app` to Applications or the Desktop and open it in Finder; no Terminal is needed for normal launches. The embedded runtime is authoritative and ignores `HD2_PLANNER_PYTHON`.

This release is intentionally unsigned and unnotarized. Gatekeeper may ask you to use Finder's contextual **Open** action once after download. Keep Gatekeeper enabled; do not remove quarantine attributes or bypass macOS security protections.

The app bundle is immutable and does not contain personal profiles, generated context, settings, backups, migration state, logs, or caches. The tested build uses the official Python.org Python 3.14.7 runtime, Tcl/Tk 9.0.4, PyInstaller 6.22.3, arm64, and minimum macOS 11.0. Settings displays the exact embedded Python and Tcl/Tk patch versions.

The CLI-only workflow below remains usable without a display server when the supported Python version is installed.

From the project folder run:

```text
python3.14 hd2.py setup
```

The flow creates the profile immediately, saves after every character and inventory answer, and lets you skip a section or quit safely. Resume a section with:

```text
python3.14 hd2.py inventory review --player your_id --character main --category primaries
python3.14 hd2.py inventory review --player your_id --character main --category stratagems
python3.14 hd2.py inventory review --player your_id --character main --category primaries --warbond cutting_edge
```

Inventory commands use `u` for unlocked, `l` for locked, `?` for unknown, `f` for favorite and unlocked, and `d` for dislike without changing availability. Enter `q` during an item review to stop setup immediately; prior answers are retained and the current category remains incomplete. Preference and unlock state are intentionally independent.

Example abbreviated session:

```text
$ python3.14 hd2.py setup
Player display name: Alex
Portable player id (blank to derive from name): alex
Character id (for example main, pc, xbox): pc
Platform: PC
Level (blank for 0): 33
Add another independent character? [y/N]: y
Character id (for example main, pc, xbox): xbox
Platform: Xbox
Level (blank for 0): 1
Add another independent character? [y/N]: n
Review warbonds now? [Y/n/quit]: y
Cutting Edge [unknown; neutral]: u
... current answer is saved ...
Review primary weapons now? [Y/n/quit]: quit
Stopped safely. Resume with: python3.14 hd2.py inventory review --player alex --character pc --category primary_weapons
```

When finished, export a self-contained context:

```text
python3.14 hd2.py export-context --player alex --character pc
```
