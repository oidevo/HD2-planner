# Local setup walkthrough

Requirements: a supported Python 3.12+ installation. Use `python3.12` below (or `py -3.12` on Windows) so the intended interpreter is unambiguous. The desktop GUI additionally needs Tkinter, which comes from the Python installation rather than `pip`; on macOS with Homebrew, install it with `brew install python@3.12 python-tk@3.12`. Do not use the macOS system Python. No third-party Python packages, server, account, or network connection are needed.

Profiles, loadouts, and generated context are stored in your operating system's HD2 Planner data directory, not alongside the downloaded application. Print it with `python3.12 hd2.py data-dir`.

Verify a Tk-enabled runtime before launching the GUI:

```text
python3.12 --version
python3.12 -c "import sys, tkinter; print(sys.executable); print(sys.version); print(tkinter.TkVersion)"
python3.12 hd2.py gui
```

The CLI-only workflow below remains usable without a display server when the supported Python version is installed.

From the project folder run:

```text
python3.12 hd2.py setup
```

On Windows, `py hd2.py setup` may be more convenient. The flow creates the profile immediately, saves after every character and inventory answer, and lets you skip a section or quit safely. Resume a section with:

```text
python3.12 hd2.py inventory review --player your_id --character main --category primaries
python3.12 hd2.py inventory review --player your_id --character main --category stratagems
python3.12 hd2.py inventory review --player your_id --character main --category primaries --warbond cutting_edge
```

Inventory commands use `u` for unlocked, `l` for locked, `?` for unknown, `f` for favorite and unlocked, and `d` for dislike without changing availability. Enter `q` during an item review to stop setup immediately; prior answers are retained and the current category remains incomplete. Preference and unlock state are intentionally independent.

Example abbreviated session:

```text
$ python3.12 hd2.py setup
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
Stopped safely. Resume with: python3.12 hd2.py inventory review --player alex --character pc --category primary_weapons
```

When finished, export a self-contained context:

```text
python3.12 hd2.py export-context --player alex --character pc
```
