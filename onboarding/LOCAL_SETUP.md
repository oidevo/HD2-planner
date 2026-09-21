# Local setup walkthrough

Requirements: Python 3.10 or newer. No third-party packages, server, account, or network connection are needed.

From the project folder run:

```text
python hd2.py setup
```

On Windows, `py hd2.py setup` may be more convenient. The flow creates the profile immediately, saves after every character and inventory answer, and lets you skip a section or quit safely. Resume a section with:

```text
python hd2.py inventory review --player your_id --character main --category primaries
python hd2.py inventory review --player your_id --character main --category stratagems
python hd2.py inventory review --player your_id --character main --category primaries --warbond cutting_edge
```

Inventory commands use `u` for unlocked, `l` for locked, `?` for unknown, `f` for favorite and unlocked, and `d` for dislike without changing availability. Preference and unlock state are intentionally independent.

Example abbreviated session:

```text
$ python hd2.py setup
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
Stopped safely. Resume with: python hd2.py inventory review --player alex --character pc --category primary_weapons
```

When finished, export a self-contained context:

```text
python hd2.py export-context --player alex --character pc
```

