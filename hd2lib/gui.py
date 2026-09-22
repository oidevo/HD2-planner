"""Tkinter desktop interface for HD2 Planner."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any, Callable

import tkinter as tk
from tkinter import simpledialog, ttk

from .constants import INVENTORY_TO_CATALOG
from .gui_model import RESOURCE_FIELDS, InventoryRow, PlannerService
from .profile import ProfileError
from .update import repository
from .gui_runtime import runtime_versions
from .version import PROFILE_SCHEMA_VERSION, application_version


STATUS_SYMBOLS = {"unlocked": "●", "unknown": "◐", "locked": "○"}
STATUS_LABELS = {"unlocked": "Unlocked", "unknown": "Unknown", "locked": "Locked"}
CATEGORIES = [
    ("Warbonds", "warbonds"), ("Primaries", "primary_weapons"),
    ("Secondaries", "secondary_weapons"), ("Grenades", "grenades"),
    ("Armor", "armor"), ("Boosters", "boosters"),
    ("Stratagems", "stratagems"), ("Support Weapons", "support_weapons"),
    ("Ship Modules", "ship_modules"), ("Weapon Mods", "weapon_attachments"),
]


def open_path(path: Path) -> None:
    """Open a file or directory with the platform's normal handler."""
    path = path.resolve()
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class HD2PlannerApp:
    def __init__(self, root: tk.Tk, service: PlannerService | None = None) -> None:
        self.root = root
        self.service = service or PlannerService()
        self.current_category = "warbonds"
        self.current_view = "warbonds"
        self.visible_rows: list[InventoryRow] = []
        self._filter_job: str | None = None
        self._character_ids_by_label: dict[str, str] = {}
        self.nav_buttons: dict[str, tuple[ttk.Button, str]] = {}
        self._configure_style()
        self._build_shell()
        self._bind_shortcuts()
        opened = False
        open_errors: list[str] = []
        for choice in self.service.profiles():
            try:
                self.service.open_profile(choice.player_id)
                opened = True
                break
            except (ProfileError, OSError, ValueError) as exc:
                open_errors.append(f"{choice.display_name}: {exc}")
        if opened:
            self._profile_opened()
            self.show_inventory("warbonds")
        else:
            self.root.after(40, lambda: self._show_welcome(open_errors))

    def _configure_style(self) -> None:
        self.root.title("HD2 Planner")
        self.root.geometry("1280x800")
        self.root.minsize(920, 640)
        self.colors = {
            "ink": "#202833", "muted": "#65707c", "surface": "#f7f8fa",
            "rail": "#e9edf1", "card": "#ffffff", "divider": "#d8dde3",
            "gold": "#9a7422", "gold_soft": "#eee4c8", "danger": "#973c3c",
            "success": "#397354",
        }
        style = ttk.Style(self.root)
        if "aqua" not in style.theme_names() and "clam" in style.theme_names():
            style.theme_use("clam")
        self.root.configure(background=self.colors["surface"])
        style.configure("App.TFrame", background=self.colors["surface"])
        style.configure("Rail.TFrame", background=self.colors["rail"])
        style.configure("Card.TFrame", background=self.colors["card"], relief="solid", borderwidth=1)
        style.configure("Card.TLabelframe", background=self.colors["card"], bordercolor=self.colors["divider"])
        style.configure("Card.TLabelframe.Label", background=self.colors["card"], foreground=self.colors["ink"], font=("TkDefaultFont", 11, "bold"))
        style.configure("Title.TLabel", foreground=self.colors["ink"], font=("TkDefaultFont", 22, "bold"))
        style.configure("Heading.TLabel", foreground=self.colors["ink"], font=("TkDefaultFont", 13, "bold"))
        style.configure("Muted.TLabel", foreground=self.colors["muted"])
        style.configure("Rail.TLabel", background=self.colors["rail"], foreground=self.colors["ink"])
        style.configure("RailMuted.TLabel", background=self.colors["rail"], foreground=self.colors["muted"])
        style.configure("RailHeading.TLabel", background=self.colors["rail"], foreground=self.colors["muted"], font=("TkDefaultFont", 9, "bold"))
        style.configure("Rail.TButton", anchor=tk.W, padding=(8, 4), relief="flat", borderwidth=0)
        style.configure("ActiveRail.TButton", anchor=tk.W, padding=(8, 4), relief="flat", borderwidth=0, font=("TkDefaultFont", 10, "bold"), foreground=self.colors["ink"], background=self.colors["gold_soft"])
        style.map("ActiveRail.TButton", background=[("active", self.colors["gold_soft"]), ("!disabled", self.colors["gold_soft"])])
        style.configure("Accent.TButton", font=("TkDefaultFont", 10, "bold"))
        style.configure("Inspector.TFrame", background=self.colors["card"], relief="solid", borderwidth=1)
        style.configure("Inspector.TLabel", background=self.colors["card"], foreground=self.colors["ink"])
        style.configure("InspectorMuted.TLabel", background=self.colors["card"], foreground=self.colors["muted"])
        style.configure("Treeview", rowheight=28)
        style.configure("Treeview.Heading", font=("TkDefaultFont", 10, "bold"))

    def _build_shell(self) -> None:
        self.shell = ttk.Frame(self.root, style="App.TFrame")
        self.shell.pack(fill=tk.BOTH, expand=True)
        self.sidebar = ttk.Frame(self.shell, style="Rail.TFrame", width=238, padding=(14, 14, 12, 12))
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)
        ttk.Separator(self.shell, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.content = ttk.Frame(self.shell, style="App.TFrame", padding=(24, 20, 24, 18))
        self.content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ttk.Label(self.sidebar, text="HD2 PLANNER", style="Rail.TLabel", font=("TkDefaultFont", 15, "bold")).pack(anchor=tk.W, padx=4)
        ttk.Label(self.sidebar, text="Inventory workspace", style="RailMuted.TLabel").pack(anchor=tk.W, padx=4, pady=(1, 12))

        card = ttk.Frame(self.sidebar, style="Card.TFrame", padding=10)
        card.pack(fill=tk.X, pady=(0, 12))
        self.player_label = ttk.Label(card, text="No profile", style="Heading.TLabel")
        self.player_label.pack(anchor=tk.W)
        self.character_meta = ttk.Label(card, text="No character", style="Muted.TLabel")
        self.character_meta.pack(anchor=tk.W, pady=(1, 6))
        self.character_var = tk.StringVar()
        self.character_combo = ttk.Combobox(card, textvariable=self.character_var, state="readonly")
        self.character_combo.pack(fill=tk.X)
        self.character_combo.bind("<<ComboboxSelected>>", self._select_character)
        self.resource_summary = ttk.Label(card, text="Resources not recorded", style="Muted.TLabel", wraplength=190, justify=tk.LEFT)
        self.resource_summary.pack(anchor=tk.W, pady=(8, 6))
        card_actions = ttk.Frame(card)
        card_actions.pack(fill=tk.X)
        ttk.Button(card_actions, text="Edit Character", command=self._edit_character).pack(side=tk.LEFT)
        ttk.Button(card_actions, text="+", width=3, command=self._new_character).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(card, text="Edit resources…", command=self._edit_resources).pack(anchor=tk.W, pady=(6, 0))

        nav = ttk.Frame(self.sidebar, style="Rail.TFrame")
        nav.pack(fill=tk.BOTH, expand=True)
        self._nav_group(nav, "INVENTORY", [(label, category, lambda value=category: self.show_inventory(value)) for label, category in CATEGORIES])
        self._nav_group(nav, "PLANNING", [
            ("Preferences", "preferences", self.show_preferences),
            ("Observations", "observations", self.show_observations),
            ("Saved Loadouts", "loadouts", self.show_loadouts),
        ])

        footer = ttk.Frame(self.sidebar, style="Rail.TFrame")
        footer.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Separator(footer).pack(fill=tk.X, pady=(8, 8))
        ttk.Button(footer, text="Generate ChatGPT Context", style="Rail.TButton", command=self.generate_context).pack(fill=tk.X)
        settings = ttk.Button(footer, text="Settings", style="Rail.TButton", command=self.show_settings)
        settings.pack(fill=tk.X)
        self.nav_buttons["settings"] = (settings, "Settings")
        self.save_status = tk.StringVar(value="Ready")
        ttk.Label(footer, textvariable=self.save_status, style="RailMuted.TLabel", wraplength=204).pack(anchor=tk.W, padx=8, pady=(9, 0))

    def _nav_group(self, parent: ttk.Frame, heading: str, routes: list[tuple[str, str, Callable[[], None]]]) -> None:
        ttk.Label(parent, text=heading, style="RailHeading.TLabel").pack(anchor=tk.W, padx=8, pady=(6, 3))
        for label, key, callback in routes:
            button = ttk.Button(parent, text=f"   {label}", style="Rail.TButton", command=callback)
            button.pack(fill=tk.X)
            self.nav_buttons[key] = (button, label)

    def _activate_route(self, route: str) -> None:
        self.current_view = route
        for key, (button, label) in self.nav_buttons.items():
            active = key == route
            button.configure(style="ActiveRail.TButton" if active else "Rail.TButton", text=f"›  {label}" if active else f"   {label}")

    def _bind_shortcuts(self) -> None:
        self.root.bind_all("<Control-f>", lambda _event: self._focus_search())
        self.root.bind_all("<Command-f>", lambda _event: self._focus_search())
        self.root.bind_all("<Escape>", lambda _event: self.root.focus_set())

    def _clear_content(self) -> None:
        self.content.unbind("<Configure>")
        for child in self.content.winfo_children():
            child.destroy()

    def _page_header(self, title: str, subtitle: str) -> ttk.Frame:
        header = ttk.Frame(self.content, style="App.TFrame")
        header.pack(fill=tk.X, pady=(0, 14))
        text = ttk.Frame(header, style="App.TFrame")
        text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(text, text=title, style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(text, text=subtitle, style="Muted.TLabel", wraplength=760).pack(anchor=tk.W, pady=(2, 0))
        return header

    def _profile_opened(self) -> None:
        profile = self.service.profile
        assert profile is not None
        character = self.service.character()
        self.player_label.configure(text=profile["player"]["display_name"])
        self.character_meta.configure(text=f"{character.get('display_name', '')} · {character.get('platform', 'unknown')} · Level {character.get('level', 0)}")
        choices = self.service.character_choices()
        self._character_ids_by_label = {label: character_id for character_id, label in choices}
        labels = list(self._character_ids_by_label)
        self.character_combo.configure(values=labels)
        self.character_var.set(self.service.character_label())
        resources = self.service.resources()
        recorded = [(label, resources[key]) for key, label in RESOURCE_FIELDS if key in resources]
        self.resource_summary.configure(text=("  ·  ".join(f"{label} {value:,}" if isinstance(value, int) else f"{label} {value}" for label, value in recorded) if recorded else "Resources not recorded"))
        self.save_status.set("Ready")

    def _show_welcome(self, open_errors: list[str]) -> None:
        self.shell.pack_forget()
        welcome = ttk.Frame(self.root, style="App.TFrame", padding=36)
        welcome.pack(fill=tk.BOTH, expand=True)
        panel = ttk.Frame(welcome, style="Card.TFrame", padding=28)
        panel.place(relx=.5, rely=.48, anchor=tk.CENTER, width=560)
        ttk.Label(panel, text="Welcome to HD2 Planner", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky=tk.W)
        ttk.Label(panel, text="Create a local player profile to start reviewing inventory. Changes save automatically to your external user-data directory.", style="Muted.TLabel", wraplength=480, justify=tk.LEFT).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(4, 18))
        fields = [("Player name", ""), ("Character name", "Main"), ("Platform", "PC"), ("Level", "0")]
        entries: list[ttk.Entry] = []
        for row, (label, initial) in enumerate(fields, 2):
            ttk.Label(panel, text=label).grid(row=row, column=0, sticky=tk.W, pady=6, padx=(0, 16))
            entry = ttk.Entry(panel); entry.insert(0, initial); entry.grid(row=row, column=1, sticky=tk.EW, pady=6); entries.append(entry)
        panel.columnconfigure(1, weight=1)
        error_var = tk.StringVar(value=("Some existing profiles could not be opened; those files were left unchanged." if open_errors else ""))
        ttk.Label(panel, textvariable=error_var, foreground=self.colors["danger"], wraplength=480).grid(row=6, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))

        def create() -> None:
            values = [entry.get().strip() for entry in entries]
            try:
                self.service.create_profile(values[0], values[1], values[2], int(values[3]))
            except (ValueError, ProfileError, OSError) as exc:
                error_var.set(str(exc)); return
            welcome.destroy(); self.shell.pack(fill=tk.BOTH, expand=True)
            self._profile_opened(); self.show_inventory("warbonds")
            self._show_notice("Welcome", "Your workspace is ready", "Start with Warbonds, then review each inventory section. Every accepted change saves automatically.")

        ttk.Button(panel, text="Create workspace", style="Accent.TButton", command=create).grid(row=7, column=0, columnspan=2, sticky=tk.E, pady=(18, 0))
        entries[0].focus_set(); entries[-1].bind("<Return>", lambda _event: create())

    def _new_player(self) -> None:
        result = self._form_dialog("New Player", "Create a separate player profile.", [("Player name", ""), ("Character name", "Main"), ("Platform", "PC"), ("Level", "0")], primary="Create")
        if result is None:
            return
        try:
            self.service.create_profile(result[0], result[1], result[2], int(result[3])); self._profile_opened(); self.show_inventory("warbonds")
        except (ValueError, ProfileError, OSError) as exc:
            self._show_error("Could not create player", exc)

    def _new_character(self) -> None:
        if self.service.profile is None:
            return
        result = self._form_dialog("New Character", "Characters keep independent inventory and resources.", [("Character name", ""), ("Platform", "PC"), ("Level", "0")], primary="Add Character")
        if result is None:
            return
        try:
            self.service.add_character(result[0], result[1], int(result[2])); self._profile_opened(); self._show_current_route()
        except (ValueError, ProfileError, OSError) as exc:
            self._show_error("Could not add character", exc)

    def _edit_character(self) -> None:
        if self.service.profile is None:
            return
        character = self.service.character()
        result = self._form_dialog("Edit Character", "Level and platform apply only to this character.", [("Character name", character.get("display_name", "")), ("Platform", character.get("platform", "")), ("Level", str(character.get("level", 0)))])
        if result is None:
            return
        try:
            self.service.edit_character(result[0], result[1], int(result[2])); self._saved("Character saved"); self._profile_opened(); self._show_current_route()
        except (ValueError, ProfileError, OSError) as exc:
            self._save_failed(exc)

    def _edit_resources(self) -> None:
        if self.service.profile is None:
            return
        dialog = self._dialog("Edit Resources", width=460)
        body = ttk.Frame(dialog, padding=18); body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text="Resource balances", style="Heading.TLabel").grid(row=0, column=0, columnspan=2, sticky=tk.W)
        ttk.Label(body, text="Enter non-negative whole numbers. Leave a field blank when it is not recorded.", style="Muted.TLabel", wraplength=410).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(2, 12))
        recorded = self.service.resources(); entries: dict[str, ttk.Entry] = {}
        for row, (key, label) in enumerate(RESOURCE_FIELDS, 2):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky=tk.W, pady=5, padx=(0, 14))
            entry = ttk.Entry(body, width=18)
            if key in recorded: entry.insert(0, str(recorded[key]))
            entry.grid(row=row, column=1, sticky=tk.EW, pady=5); entries[key] = entry
        body.columnconfigure(1, weight=1)
        error_var = tk.StringVar()
        ttk.Label(body, textvariable=error_var, foreground=self.colors["danger"], wraplength=410).grid(row=8, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))
        actions = ttk.Frame(body); actions.grid(row=9, column=0, columnspan=2, sticky=tk.E, pady=(16, 0))

        def save() -> None:
            try:
                values = self.service.parse_resource_inputs({key: entry.get() for key, entry in entries.items()}); self.service.set_resources(values)
            except (ProfileError, OSError, ValueError) as exc:
                error_var.set(f"Nothing was changed. {exc}"); return
            dialog.destroy(); self._profile_opened(); self._saved("Resources saved")

        ttk.Button(actions, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(actions, text="Save resources", style="Accent.TButton", command=save).pack(side=tk.LEFT)
        dialog.bind("<Return>", lambda _event: save()); entries[RESOURCE_FIELDS[0][0]].focus_set(); self._run_dialog(dialog)

    def _form_dialog(self, title: str, helper: str, fields: list[tuple[str, str]], *, primary: str = "Save") -> list[str] | None:
        dialog = self._dialog(title, width=470)
        body = ttk.Frame(dialog, padding=18); body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text=title, style="Heading.TLabel").grid(row=0, column=0, columnspan=2, sticky=tk.W)
        ttk.Label(body, text=helper, style="Muted.TLabel", wraplength=420).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(2, 12))
        entries: list[ttk.Entry] = []
        for row, (label, initial) in enumerate(fields, 2):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky=tk.W, padx=(0, 14), pady=6)
            entry = ttk.Entry(body); entry.insert(0, initial); entry.grid(row=row, column=1, sticky=tk.EW, pady=6); entries.append(entry)
        body.columnconfigure(1, weight=1); result: list[str] | None = None

        def accept() -> None:
            nonlocal result
            result = [entry.get().strip() for entry in entries]; dialog.destroy()

        actions = ttk.Frame(body); actions.grid(row=len(fields) + 2, column=0, columnspan=2, sticky=tk.E, pady=(16, 0))
        ttk.Button(actions, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(actions, text=primary, style="Accent.TButton", command=accept).pack(side=tk.LEFT)
        dialog.bind("<Return>", lambda _event: accept()); entries[0].focus_set(); self._run_dialog(dialog); return result

    def _select_character(self, _event: tk.Event[Any] | None = None) -> None:
        character_id = self._character_ids_by_label.get(self.character_var.get())
        if character_id:
            self.service.select_character(character_id); self._profile_opened(); self._show_current_route()

    def _show_current_route(self) -> None:
        if self.current_view in {category for _label, category in CATEGORIES}: self.show_inventory(self.current_view)
        elif self.current_view == "preferences": self.show_preferences()
        elif self.current_view == "observations": self.show_observations()
        elif self.current_view == "loadouts": self.show_loadouts()
        else: self.show_settings()

    def show_inventory(self, category: str) -> None:
        if self.service.profile is None:
            return
        self.current_category = category; self._activate_route(category); self._clear_content()
        label = next((label for label, key in CATEGORIES if key == category), category.replace("_", " ").title())
        subtitle = ("Attachment compatibility comes from the catalog; ownership remains global rather than per-weapon." if category == "weapon_attachments" else "Double-click or press Space to toggle unlocked. Right-click an item to choose any availability state.")
        header = self._page_header(label, subtitle); self.review_var = tk.StringVar(); ttk.Label(header, textvariable=self.review_var, style="Muted.TLabel").pack(side=tk.RIGHT, anchor=tk.N, pady=8)

        toolbar = ttk.LabelFrame(self.content, text="Find and filter", style="Card.TLabelframe", padding=(10, 7)); toolbar.pack(fill=tk.X, pady=(0, 10))
        self.search_var = tk.StringVar(); self.search_entry = ttk.Entry(toolbar, textvariable=self.search_var)
        ttk.Label(toolbar, text="Search").grid(row=0, column=0, sticky=tk.W, padx=(0, 5)); self.search_entry.grid(row=0, column=1, sticky=tk.EW, padx=(0, 12)); self.search_var.trace_add("write", lambda *_args: self._schedule_filter())
        self.status_var = tk.StringVar(value="All"); ttk.Label(toolbar, text="Status").grid(row=0, column=2, sticky=tk.W, padx=(0, 5))
        status_combo = ttk.Combobox(toolbar, textvariable=self.status_var, values=("All", "Unlocked", "Locked", "Unknown"), state="readonly", width=11); status_combo.grid(row=0, column=3, sticky=tk.EW, padx=(0, 12)); status_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_inventory())
        self.warbond_var = tk.StringVar(value="All"); self._warbond_ids: dict[str, str | None] = {"All": None}; warbond_column = 0
        if category not in {"warbonds", "ship_modules", "weapon_attachments"}:
            for item in self.service.catalog["collections"]["warbonds"]: self._warbond_ids[item["name"]] = item["id"]
            ttk.Label(toolbar, text="Warbond").grid(row=1, column=warbond_column, sticky=tk.W, padx=(0, 5), pady=(6, 0))
            combo = ttk.Combobox(toolbar, textvariable=self.warbond_var, values=list(self._warbond_ids), state="readonly", width=20); combo.grid(row=1, column=warbond_column + 1, sticky=tk.EW, padx=(0, 12), pady=(6, 0)); combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_inventory()); warbond_column += 2
        self.group_var = tk.StringVar(value="All"); groups = self._groups_for(category); self._group_ids = {"All": None, **{value.replace("_", " ").title(): value for value in groups}}
        if groups:
            ttk.Label(toolbar, text="Group").grid(row=1, column=warbond_column, sticky=tk.W, padx=(0, 5), pady=(6, 0))
            combo = ttk.Combobox(toolbar, textvariable=self.group_var, values=list(self._group_ids), state="readonly", width=17); combo.grid(row=1, column=warbond_column + 1, sticky=tk.EW, pady=(6, 0)); combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_inventory())
        toolbar.columnconfigure(1, weight=1, minsize=150)

        self.inventory_workspace = ttk.Frame(self.content, style="App.TFrame"); self.inventory_workspace.pack(fill=tk.BOTH, expand=True)
        self.table_panel = ttk.Frame(self.inventory_workspace, style="App.TFrame")
        columns = ("state", "name", "detail", "source"); self.inventory_tree = ttk.Treeview(self.table_panel, columns=columns, show="headings", selectmode="extended")
        for key, title in (("state", "Availability"), ("name", "Name"), ("detail", "Details"), ("source", "Warbond / Source")): self.inventory_tree.heading(key, text=title)
        self.inventory_tree.column("state", width=110, minwidth=105, stretch=False, anchor=tk.W); self.inventory_tree.column("name", width=280, minwidth=180, stretch=True); self.inventory_tree.column("detail", width=230, minwidth=120, stretch=True); self.inventory_tree.column("source", width=180, minwidth=105, stretch=True)
        scrollbar = ttk.Scrollbar(self.table_panel, orient=tk.VERTICAL, command=self.inventory_tree.yview); self.inventory_tree.configure(yscrollcommand=scrollbar.set); self.inventory_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.inventory_tree.tag_configure("unlocked", foreground=self.colors["success"]); self.inventory_tree.tag_configure("locked", foreground=self.colors["danger"]); self.inventory_tree.tag_configure("unknown", foreground=self.colors["muted"])
        self.inventory_tree.bind("<Double-1>", self._toggle_selected); self.inventory_tree.bind("<space>", self._toggle_selected); self.inventory_tree.bind("<<TreeviewSelect>>", self._inventory_selection_changed); self.inventory_tree.bind("<Button-3>", self._inventory_context_menu)
        if sys.platform == "darwin": self.inventory_tree.bind("<Button-2>", self._inventory_context_menu)

        self.inspector = ttk.Frame(self.inventory_workspace, style="Inspector.TFrame", padding=14, width=270); self.inspector.grid_propagate(False); self._show_inspector_empty()
        self.inventory_workspace.columnconfigure(0, weight=1); self.inventory_workspace.rowconfigure(0, weight=1); self._inventory_layout_wide: bool | None = None; self.inventory_workspace.bind("<Configure>", self._layout_inventory_workspace)

        footer = ttk.Frame(self.content, style="App.TFrame"); footer.pack(fill=tk.X, pady=(9, 0)); self.bulk_summary_var = tk.StringVar(); ttk.Label(footer, textvariable=self.bulk_summary_var, style="Muted.TLabel").pack(side=tk.LEFT)
        ttk.Button(footer, text="Mark unknown visible as locked", style="Accent.TButton", command=self._bulk_lock_unknown).pack(side=tk.RIGHT)
        more = ttk.Menubutton(footer, text="More visible actions"); menu = tk.Menu(more, tearoff=False)
        menu.add_command(label="Mark all visible unlocked", command=lambda: self._bulk_set("unlocked", False)); menu.add_command(label="Mark all visible unknown", command=lambda: self._bulk_set("unknown", False)); menu.add_command(label="Mark all visible locked", command=lambda: self._bulk_set("locked", False)); menu.add_separator(); menu.add_command(label="Reload profile from disk", command=self._reload)
        more.configure(menu=menu); more.pack(side=tk.RIGHT, padx=(0, 7)); self._refresh_inventory()

    def _layout_inventory_workspace(self, event: tk.Event[Any]) -> None:
        wide = event.width >= 880
        if wide == self._inventory_layout_wide: return
        self._inventory_layout_wide = wide; self.table_panel.grid_forget(); self.inspector.grid_forget()
        if wide:
            self.inventory_workspace.columnconfigure(0, weight=1); self.inventory_workspace.columnconfigure(1, weight=0, minsize=270); self.inventory_workspace.rowconfigure(0, weight=1); self.inventory_workspace.rowconfigure(1, weight=0)
            self.table_panel.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 10)); self.inspector.grid(row=0, column=1, sticky=tk.NSEW)
        else:
            self.inventory_workspace.columnconfigure(1, weight=0, minsize=0); self.inventory_workspace.rowconfigure(0, weight=1); self.inventory_workspace.rowconfigure(1, weight=0)
            self.table_panel.grid(row=0, column=0, sticky=tk.NSEW); self.inspector.grid(row=1, column=0, sticky=tk.EW, pady=(10, 0))

    def _groups_for(self, category: str) -> list[str]:
        return sorted({row.group for row in self.service.inventory_rows(category) if row.group}, key=str.casefold)

    def _schedule_filter(self) -> None:
        if self._filter_job: self.root.after_cancel(self._filter_job)
        self._filter_job = self.root.after(100, self._refresh_inventory)

    def _refresh_inventory(self) -> None:
        if not hasattr(self, "inventory_tree") or not self.inventory_tree.winfo_exists(): return
        selected = set(self._selected_ids()); status = self.status_var.get().casefold()
        self.visible_rows = self.service.inventory_rows(self.current_category, search=self.search_var.get(), status=status, warbond_id=self._warbond_ids.get(self.warbond_var.get()), group=self._group_ids.get(self.group_var.get()))
        self.inventory_tree.delete(*self.inventory_tree.get_children()); warbond_names = {item["id"]: item["name"] for item in self.service.catalog["collections"]["warbonds"]}
        for row in self.visible_rows:
            state = f"{STATUS_SYMBOLS[row.status]}  {STATUS_LABELS[row.status]}"; detail = row.detail + (f" · Level {row.level}" if row.level is not None else "")
            self.inventory_tree.insert("", tk.END, iid=row.item_id, values=(state, row.name, detail, warbond_names.get(row.warbond_id, "")), tags=(row.status,))
            if row.item_id in selected: self.inventory_tree.selection_add(row.item_id)
        all_rows = self.service.inventory_rows(self.current_category); reviewed = sum(row.status != "unknown" for row in all_rows); self.review_var.set(f"Reviewed {reviewed} of {len(all_rows)}")
        unknown_visible = sum(row.status == "unknown" for row in self.visible_rows); self.bulk_summary_var.set(f"{unknown_visible} of {len(self.visible_rows)} visible items will be affected")
        if not self.inventory_tree.selection(): self._show_inspector_empty()

    def _show_inspector_empty(self) -> None:
        for child in self.inspector.winfo_children(): child.destroy()
        ttk.Label(self.inspector, text="Item details", style="Inspector.TLabel", font=("TkDefaultFont", 12, "bold")).pack(anchor=tk.W)
        message = "Select an item to review its availability, preference, source, and catalog facts."
        if self.current_category == "warbonds" and self.service.profile is not None:
            count = len(self.service.locked_warbond_unknown_items())
            if count:
                message = f"{count} unknown catalog items are linked to Warbonds marked locked."; ttk.Button(self.inspector, text="Mark linked items locked", command=self._lock_warbond_items).pack(side=tk.BOTTOM, anchor=tk.W, pady=(10, 0))
        ttk.Label(self.inspector, text=message, style="InspectorMuted.TLabel", wraplength=240, justify=tk.LEFT).pack(anchor=tk.W, pady=(5, 0))

    def _selected_ids(self) -> list[str]: return list(self.inventory_tree.selection())

    def _toggle_selected(self, _event: tk.Event[Any] | None = None) -> str:
        selected = self._selected_ids()
        if not selected: return "break"
        try:
            for item_id in selected:
                current = self.service.inventory_status(self.current_category, item_id); self.service.set_inventory_status(self.current_category, item_id, "unknown" if current == "unlocked" else "unlocked")
            self._saved(); self._refresh_inventory()
        except (ProfileError, ValueError, OSError) as exc: self._save_failed(exc)
        return "break"

    def _inventory_context_menu(self, event: tk.Event[Any]) -> None:
        row = self.inventory_tree.identify_row(event.y)
        if row and row not in self.inventory_tree.selection(): self.inventory_tree.selection_set(row)
        menu = tk.Menu(self.root, tearoff=False)
        for status in ("unlocked", "unknown", "locked"): menu.add_command(label=f"Set {STATUS_LABELS[status]}", command=lambda value=status: self._set_selected(value))
        try: menu.tk_popup(event.x_root, event.y_root)
        finally: menu.grab_release()

    def _set_selected(self, status: str) -> None:
        try: self.service.bulk_set_status(self.current_category, self._selected_ids(), status); self._saved(); self._refresh_inventory()
        except (ProfileError, ValueError, OSError) as exc: self._save_failed(exc)

    def _bulk_lock_unknown(self) -> None: self._bulk_set("locked", True)

    def _bulk_set(self, status: str, only_unknown: bool) -> None:
        ids = [row.item_id for row in self.visible_rows if not only_unknown or row.status == "unknown"]
        if not ids: self._show_notice("No changes", "Nothing to update", "No matching visible items need this change."); return
        description = "visible unknown" if only_unknown else "visible"
        if len(ids) >= 10 and not self._confirm("Confirm bulk change", f"Mark {len(ids)} {description} items as {status}?", "Only the currently filtered rows will change."): return
        try:
            changed = self.service.bulk_set_status(self.current_category, ids, status, only_unknown=only_unknown); self._saved(f"Saved {changed} item changes"); self._refresh_inventory()
        except (ProfileError, ValueError, OSError) as exc: self._save_failed(exc)

    def _inventory_selection_changed(self, _event: tk.Event[Any] | None = None) -> None:
        selected = self._selected_ids()
        if not selected: self._show_inspector_empty(); return
        if len(selected) > 1:
            for child in self.inspector.winfo_children(): child.destroy()
            ttk.Label(self.inspector, text=f"{len(selected)} items selected", style="Inspector.TLabel", font=("TkDefaultFont", 12, "bold")).pack(anchor=tk.W); ttk.Label(self.inspector, text="Use the context menu to set availability for this selection.", style="InspectorMuted.TLabel", wraplength=240).pack(anchor=tk.W, pady=(5, 8)); return
        row = next((value for value in self.visible_rows if value.item_id == selected[0]), None)
        if row is None: return
        for child in self.inspector.winfo_children(): child.destroy()
        ttk.Label(self.inspector, text=row.name, style="Inspector.TLabel", font=("TkDefaultFont", 13, "bold"), wraplength=240).pack(anchor=tk.W)
        ttk.Label(self.inspector, text=f"{STATUS_SYMBOLS[row.status]}  {STATUS_LABELS[row.status]}", style="Inspector.TLabel").pack(anchor=tk.W, pady=(5, 0)); ttk.Label(self.inspector, text=f"Preference: {self.service.item_preference(row.item_id).title()}", style="InspectorMuted.TLabel").pack(anchor=tk.W, pady=(2, 0))
        warbond_names = {item["id"]: item["name"] for item in self.service.catalog["collections"]["warbonds"]}; source = warbond_names.get(row.warbond_id) or "Catalog / base availability"
        ttk.Label(self.inspector, text=f"Source: {source}", style="InspectorMuted.TLabel", wraplength=240).pack(anchor=tk.W, pady=(2, 10))
        facts = []
        for key, value in row.facts.items():
            if key in {"warbond_id", "compatible_weapon_ids"} or value in (None, "", [], {}): continue
            if isinstance(value, (str, int, float, bool)): facts.append(f"{key.replace('_', ' ').title()}: {value}")
            if len(facts) == 6: break
        if row.level is not None: facts.insert(0, f"Recorded weapon level: {row.level}")
        if facts:
            ttk.Separator(self.inspector).pack(fill=tk.X, pady=(0, 9)); ttk.Label(self.inspector, text="Relevant facts", style="Inspector.TLabel", font=("TkDefaultFont", 10, "bold")).pack(anchor=tk.W); ttk.Label(self.inspector, text="\n".join(facts), style="InspectorMuted.TLabel", wraplength=240, justify=tk.LEFT).pack(anchor=tk.W, pady=(4, 10))
        actions = ttk.Frame(self.inspector, style="Inspector.TFrame"); actions.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Button(actions, text="Set availability…", command=lambda: self._availability_dialog(row)).pack(fill=tk.X); ttk.Button(actions, text="Set preference…", command=lambda: self._preference_dialog(row.item_id)).pack(fill=tk.X, pady=(5, 0))
        if self.current_category in {"primary_weapons", "secondary_weapons", "support_weapons"}:
            ttk.Button(actions, text="Set weapon level…", command=lambda: self._weapon_level(row)).pack(fill=tk.X, pady=(5, 0)); ttk.Button(actions, text="Compatible mods…", command=lambda: self._weapon_mods(row)).pack(fill=tk.X, pady=(5, 0))

    def _availability_dialog(self, row: InventoryRow) -> None:
        value = self._choice_dialog("Set Availability", row.name, [(label, status) for status, label in STATUS_LABELS.items()], row.status)
        if value: self._set_selected(value)

    def _weapon_level(self, row: InventoryRow) -> None:
        value = simpledialog.askstring("Weapon level", f"Level for {row.name}\nLeave blank when not recorded.", initialvalue="" if row.level is None else str(row.level), parent=self.root)
        if value is None: return
        try:
            self.service.set_weapon_level(self.current_category, row.item_id, None if not value.strip() else int(value)); self._saved(); self._refresh_inventory()
        except (ValueError, ProfileError, OSError) as exc: self._save_failed(exc)

    def _weapon_mods(self, weapon: InventoryRow) -> None:
        dialog = self._dialog(f"Weapon Mods — {weapon.name}", width=680, height=500); body = ttk.Frame(dialog, padding=16); body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text=weapon.name, style="Heading.TLabel").pack(anchor=tk.W); ttk.Label(body, text="Compatible attachments; unlock state is global, not per-weapon progression.", style="Muted.TLabel").pack(anchor=tk.W, pady=(2, 10))
        tree = ttk.Treeview(body, columns=("state", "name", "slot"), show="headings")
        for key, title, width in (("state", "Availability", 120), ("name", "Attachment", 330), ("slot", "Slot", 160)): tree.heading(key, text=title); tree.column(key, width=width)
        rows = self.service.inventory_rows("weapon_attachments", compatible_weapon_id=weapon.item_id)
        for row in rows: tree.insert("", tk.END, iid=row.item_id, values=(f"{STATUS_SYMBOLS[row.status]}  {STATUS_LABELS[row.status]}", row.name, row.group or "Unknown"))
        tree.pack(fill=tk.BOTH, expand=True)

        def set_status(status: str) -> None:
            if not tree.selection(): return
            try:
                self.service.bulk_set_status("weapon_attachments", tree.selection(), status)
                for item_id in tree.selection(): tree.set(item_id, "state", f"{STATUS_SYMBOLS[status]}  {STATUS_LABELS[status]}")
                self._saved()
            except (ProfileError, ValueError, OSError) as exc: self._save_failed(exc)

        buttons = ttk.Frame(body); buttons.pack(fill=tk.X, pady=(10, 0))
        for status in ("unlocked", "unknown", "locked"): ttk.Button(buttons, text=f"Set {STATUS_LABELS[status]}", command=lambda value=status: set_status(value)).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(buttons, text="Done", command=dialog.destroy).pack(side=tk.RIGHT); self._run_dialog(dialog)

    def _lock_warbond_items(self) -> None:
        count = len(self.service.locked_warbond_unknown_items())
        if not self._confirm("Apply Warbond availability", f"Mark {count} linked unknown items as locked?", "Only catalog items explicitly linked to locked Warbonds will change."): return
        try: changed = self.service.lock_items_from_locked_warbonds(); self._saved(f"Saved {changed} item changes"); self._refresh_inventory()
        except (ProfileError, OSError) as exc: self._save_failed(exc)

    def show_preferences(self) -> None:
        self._activate_route("preferences"); self._clear_content(); self._page_header("Preferences", "Optional preferences are independent from unlock state. Only explicit, non-neutral choices appear here.")
        general = ttk.LabelFrame(self.content, text="General character preferences", style="Card.TLabelframe", padding=10); general.pack(fill=tk.X, pady=(0, 10))
        base_general = (self.service.profile or {}).get("preferences", {}).get("general", {}); overrides_general = self.service.character().get("preference_overrides", {}).get("general", {}); prefs = dict(base_general); prefs.update(overrides_general)
        general_tree = ttk.Treeview(general, columns=("name", "value", "scope"), show="headings", height=min(max(len(prefs), 1), 4)); general_tree.heading("name", text="Preference"); general_tree.heading("value", text="Value"); general_tree.heading("scope", text="Source"); general_tree.column("name", width=230); general_tree.column("value", width=420); general_tree.column("scope", width=170)
        for key, value in sorted(prefs.items()): general_tree.insert("", tk.END, iid=key, values=(key, value, "Character override" if key in overrides_general else "Player preference"))
        general_tree.pack(side=tk.LEFT, fill=tk.X, expand=True); general_actions = ttk.Frame(general); general_actions.pack(side=tk.RIGHT, padx=(10, 0))

        def edit_general(existing: str | None = None) -> None:
            result = self._form_dialog("General Preference", "Use a short name and value. Clear the value to remove it.", [("Preference name", existing or ""), ("Value", prefs.get(existing or "", ""))])
            if result is None: return
            try: self.service.set_general_preference(result[0], result[1]); self._saved(); self.show_preferences()
            except (ProfileError, OSError) as exc: self._save_failed(exc)

        ttk.Button(general_actions, text="Add…", command=edit_general).pack(fill=tk.X); ttk.Button(general_actions, text="Edit selected…", command=lambda: edit_general(general_tree.selection()[0]) if general_tree.selection() else None).pack(fill=tk.X, pady=(5, 0))
        item_frame = ttk.LabelFrame(self.content, text="Item preferences", style="Card.TLabelframe", padding=10); item_frame.pack(fill=tk.BOTH, expand=True)
        tools = ttk.Frame(item_frame); tools.pack(fill=tk.X, pady=(0, 8)); search = tk.StringVar(); ttk.Label(tools, text="Search overrides").pack(side=tk.LEFT); search_entry = ttk.Entry(tools, textvariable=search, width=32); search_entry.pack(side=tk.LEFT, padx=(6, 8)); ttk.Button(tools, text="Add preference…", style="Accent.TButton", command=self._preference_dialog).pack(side=tk.RIGHT)
        tree = ttk.Treeview(item_frame, columns=("name", "preference", "scope"), show="headings", selectmode="browse"); tree.heading("name", text="Item"); tree.heading("preference", text="Preference"); tree.heading("scope", text="Source"); tree.column("name", width=460, minwidth=220); tree.column("preference", width=150, minwidth=120); tree.column("scope", width=180, minwidth=150); tree.pack(fill=tk.BOTH, expand=True)
        empty_var = tk.StringVar(); ttk.Label(item_frame, textvariable=empty_var, style="Muted.TLabel").pack(anchor=tk.W, pady=(6, 0))

        def redraw(*_args: Any) -> None:
            tree.delete(*tree.get_children()); rows = self.service.explicit_item_preferences(search=search.get())
            for row in rows: tree.insert("", tk.END, iid=row.item_id, values=(row.name, row.preference.title(), row.scope))
            empty_var.set("No explicit item preferences match. Add one when an item matters to your planning." if not rows else f"{len(rows)} explicit preference{'s' if len(rows) != 1 else ''}")

        search.trace_add("write", redraw); redraw(); controls = ttk.Frame(item_frame); controls.pack(fill=tk.X, pady=(8, 0))
        edit_button = ttk.Button(controls, text="Edit selected…", command=lambda: self._preference_dialog(tree.selection()[0]) if tree.selection() else None)
        edit_button.pack(side=tk.RIGHT)
        remove_button = ttk.Button(controls, text="Remove override", command=lambda: self._remove_preference(tree.selection()[0]) if tree.selection() else None)
        remove_button.pack(side=tk.RIGHT, padx=(0, 6))

        def preference_selection_changed(_event: tk.Event[Any] | None = None) -> None:
            selected = tree.selection()
            edit_button.configure(state=tk.NORMAL if selected else tk.DISABLED)
            overrides = self.service.character().get("preference_overrides", {}).get("item_preferences", {})
            remove_button.configure(state=tk.NORMAL if selected and selected[0] in overrides else tk.DISABLED)

        tree.bind("<<TreeviewSelect>>", preference_selection_changed)
        preference_selection_changed()

    def _preference_dialog(self, item_id: str | None = None) -> None:
        candidates: dict[str, str] = {}
        for category in INVENTORY_TO_CATALOG:
            for row in self.service.inventory_rows(category): candidates[row.item_id] = row.name
        item_map = {f"{name}  [{item_id}]": item_id for item_id, name in sorted(candidates.items(), key=lambda value: value[1].casefold())}; reverse = {value: key for key, value in item_map.items()}
        dialog = self._dialog("Item Preference", width=520); body = ttk.Frame(dialog, padding=18); body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text="Set an item preference", style="Heading.TLabel").grid(row=0, column=0, columnspan=2, sticky=tk.W); ttk.Label(body, text="This choice is optional and does not change availability.", style="Muted.TLabel").grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(2, 12))
        item_var = tk.StringVar(value=reverse.get(item_id, "")); pref_var = tk.StringVar(value=self.service.item_preference(item_id) if item_id else "like")
        ttk.Label(body, text="Item").grid(row=2, column=0, sticky=tk.W, padx=(0, 12), pady=6); combo = ttk.Combobox(body, textvariable=item_var, values=list(item_map), state="readonly"); combo.grid(row=2, column=1, sticky=tk.EW, pady=6)
        if item_id: combo.configure(state="disabled")
        ttk.Label(body, text="Preference").grid(row=3, column=0, sticky=tk.W, padx=(0, 12), pady=6); ttk.Combobox(body, textvariable=pref_var, values=("favorite", "like", "dislike", "avoid"), state="readonly").grid(row=3, column=1, sticky=tk.EW, pady=6); body.columnconfigure(1, weight=1)
        error_var = tk.StringVar(); ttk.Label(body, textvariable=error_var, foreground=self.colors["danger"]).grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=(6, 0)); actions = ttk.Frame(body); actions.grid(row=5, column=0, columnspan=2, sticky=tk.E, pady=(15, 0))

        def save() -> None:
            selected = item_id or item_map.get(item_var.get())
            if not selected: error_var.set("Choose an item."); return
            try: self.service.set_item_preference(selected, pref_var.get())
            except (ProfileError, OSError) as exc: error_var.set(str(exc)); return
            dialog.destroy(); self._saved("Preference saved")
            if self.current_view == "preferences": self.show_preferences()
            elif self.current_view == self.current_category: self._refresh_inventory(); self._inventory_selection_changed()

        ttk.Button(actions, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=(0, 6)); ttk.Button(actions, text="Save preference", style="Accent.TButton", command=save).pack(side=tk.LEFT); self._run_dialog(dialog)

    def _remove_preference(self, item_id: str) -> None:
        try: self.service.set_item_preference(item_id, "neutral"); self._saved("Preference removed"); self.show_preferences()
        except (ProfileError, OSError) as exc: self._save_failed(exc)

    def show_observations(self) -> None:
        self._activate_route("observations"); self._clear_content(); self._page_header("Gameplay Observations", "Capture experience as character-specific evidence without interpreting or scoring the catalog.")
        form = ttk.LabelFrame(self.content, text="New observation", style="Card.TLabelframe", padding=12); form.pack(fill=tk.X); item_map = {"(General / loadout)": None}
        for item in sorted(self.service.index.values(), key=lambda value: value["name"].casefold()): item_map[f"{item['name']} [{item['id']}]" ] = item["id"]
        variables = {"faction": tk.StringVar(), "difficulty": tk.StringVar(), "mission": tk.StringVar(), "item": tk.StringVar(value="(General / loadout)"), "rating": tk.StringVar(value="neutral"), "confidence": tk.StringVar(value="low")}
        rows = [("Faction", ttk.Combobox(form, textvariable=variables["faction"], values=("", "terminids", "automatons", "illuminate"))), ("Difficulty", ttk.Combobox(form, textvariable=variables["difficulty"], values=("", *map(str, range(1, 11))))), ("Mission (optional)", ttk.Entry(form, textvariable=variables["mission"])), ("Item / loadout", ttk.Combobox(form, textvariable=variables["item"], values=list(item_map))), ("Rating", ttk.Combobox(form, textvariable=variables["rating"], values=("great", "good", "neutral", "poor"), state="readonly")), ("Confidence", ttk.Combobox(form, textvariable=variables["confidence"], values=("low", "medium", "high"), state="readonly"))]
        for number, (label, widget) in enumerate(rows): ttk.Label(form, text=label).grid(row=number, column=0, sticky=tk.W, pady=5); widget.grid(row=number, column=1, sticky=tk.EW, padx=(12, 0), pady=5)
        form.columnconfigure(1, weight=1); ttk.Label(form, text="Notes").grid(row=len(rows), column=0, sticky=tk.NW, pady=5); notes = tk.Text(form, height=7, wrap=tk.WORD, relief=tk.SOLID, borderwidth=1); notes.grid(row=len(rows), column=1, sticky=tk.EW, padx=(12, 0), pady=5)

        def save_observation() -> None:
            try:
                difficulty = int(variables["difficulty"].get()) if variables["difficulty"].get() else None
                self.service.add_observation(item_id=item_map.get(variables["item"].get()), faction=variables["faction"].get() or None, difficulty=difficulty, mission_type=variables["mission"].get() or None, rating=variables["rating"].get(), confidence=variables["confidence"].get(), notes=notes.get("1.0", tk.END))
                notes.delete("1.0", tk.END); self._saved("Observation saved"); self._show_notice("Observation saved", "Added to this character", "The observation is stored in the canonical profile and will appear in the next context export.")
            except (ValueError, ProfileError, OSError) as exc: self._save_failed(exc)

        ttk.Button(self.content, text="Save observation", style="Accent.TButton", command=save_observation).pack(anchor=tk.E, pady=10)

    def show_loadouts(self) -> None:
        self._activate_route("loadouts"); self._clear_content(); self._page_header("Saved Loadouts", "Loadouts are validated against the currently selected character without changing them.")
        tree = ttk.Treeview(self.content, columns=("name", "result", "unavailable"), show="headings"); tree.heading("name", text="Loadout"); tree.heading("result", text="Validation"); tree.heading("unavailable", text="Unavailable / Unknown"); tree.column("name", width=280); tree.column("result", width=160); tree.column("unavailable", width=420)
        entries = self.service.saved_loadouts()
        for number, entry in enumerate(entries):
            result = self.service.validate_loadout(entry); status = "Invalid" if result["errors"] else f"{len(result['usable'])}/{result['total']} usable"; detail_text = "; ".join(result["errors"]) if result["errors"] else ", ".join(item["name"] for item in [*result["missing"], *result["unknown"]]) or "None"; tree.insert("", tk.END, iid=str(number), values=(entry["loadout"].get("name", "Unnamed"), status, detail_text))
        tree.pack(fill=tk.BOTH, expand=True); detail = tk.Text(self.content, height=8, wrap=tk.WORD, state=tk.DISABLED, relief=tk.SOLID, borderwidth=1); detail.pack(fill=tk.X, pady=(9, 0))

        def show_detail(_event: tk.Event[Any] | None = None) -> None:
            if not tree.selection(): return
            entry = entries[int(tree.selection()[0])]; text = json.dumps({"loadout": entry["loadout"], "validation": self.service.validate_loadout(entry)}, indent=2, ensure_ascii=False); detail.configure(state=tk.NORMAL); detail.delete("1.0", tk.END); detail.insert("1.0", text); detail.configure(state=tk.DISABLED)

        tree.bind("<<TreeviewSelect>>", show_detail)

        def delete_selected() -> None:
            if not tree.selection(): return
            entry = entries[int(tree.selection()[0])]; name = entry["loadout"].get("name", "Unnamed")
            if not self._confirm("Remove saved loadout", f"Remove {name!r} from this profile?", "Linked files will remain on disk."): return
            try: self.service.delete_loadout(entry["source"], entry["key"]); self._saved(); self.show_loadouts()
            except (ProfileError, OSError, ValueError) as exc: self._save_failed(exc)

        ttk.Button(self.content, text="Remove selected…", command=delete_selected).pack(anchor=tk.E, pady=(8, 0))

    def generate_context(self) -> None:
        try: json_path, markdown_path = self.service.generate_context()
        except (ProfileError, ValueError, OSError) as exc: self._show_error("Context generation failed", exc); return
        dialog = self._dialog("Context Generated", width=600); body = ttk.Frame(dialog, padding=20); body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text="ChatGPT context is ready", style="Heading.TLabel").pack(anchor=tk.W)
        ttk.Label(body, text=("Created Markdown and JSON snapshots for the selected character. They include inventory availability, preferences, resources, observations, saved loadouts, and source fingerprints.\n\nUpload or paste the Markdown into ChatGPT. HD2 Planner did not call ChatGPT, alter your data, or make recommendations. Regenerate after meaningful profile changes."), style="Muted.TLabel", wraplength=540, justify=tk.LEFT).pack(anchor=tk.W, pady=(5, 16))
        ttk.Label(body, text=f"Character: {self.service.character_label()}").pack(anchor=tk.W); ttk.Label(body, text=f"Catalog: {self.service.catalog['manifest'].get('catalog_version')}", style="Muted.TLabel").pack(anchor=tk.W, pady=(2, 0))
        buttons = ttk.Frame(body); buttons.pack(fill=tk.X, pady=(18, 0)); ttk.Button(buttons, text="Open Markdown", style="Accent.TButton", command=lambda: self._open_safely(markdown_path)).pack(side=tk.LEFT); ttk.Button(buttons, text="Reveal in Finder" if sys.platform == "darwin" else "Open Folder", command=lambda: self._open_safely(markdown_path.parent)).pack(side=tk.LEFT, padx=6); ttk.Button(buttons, text="Copy Path", command=lambda: self._copy_path(markdown_path)).pack(side=tk.LEFT); ttk.Button(buttons, text="Done", command=dialog.destroy).pack(side=tk.RIGHT); self._run_dialog(dialog)

    def check_updates(self) -> None:
        self.save_status.set("Checking for updates…")
        def work() -> None:
            result = self.service.check_updates(); self.root.after(0, lambda: self._show_update_result(result))
        threading.Thread(target=work, daemon=True).start()

    def _show_update_result(self, result: Any) -> None:
        self.save_status.set("Ready")
        if result.error: self._show_notice("Update check", "Could not check for updates", f"{result.error}\n\nHD2 Planner remains fully usable offline."); return
        message = f"Installed: {result.installed}\nLatest: {result.latest}\n\n" + ("An update is available." if result.available else "You are up to date.")
        dialog = self._dialog("Check for Updates", width=430); body = ttk.Frame(dialog, padding=18); body.pack(fill=tk.BOTH, expand=True); ttk.Label(body, text="Update available" if result.available else "HD2 Planner is current", style="Heading.TLabel").pack(anchor=tk.W); ttk.Label(body, text=message, justify=tk.LEFT, style="Muted.TLabel").pack(anchor=tk.W, pady=(5, 14)); actions = ttk.Frame(body); actions.pack(fill=tk.X)
        if result.url: ttk.Button(actions, text="Open Release Page", command=lambda: webbrowser.open(result.url)).pack(side=tk.LEFT)
        ttk.Button(actions, text="Done", command=dialog.destroy).pack(side=tk.RIGHT); self._run_dialog(dialog)

    def show_settings(self) -> None:
        self._activate_route("settings"); self._clear_content(); self._page_header("Settings", "Application information, storage location, updates, and player management.")
        info = ttk.LabelFrame(self.content, text="Application", style="Card.TLabelframe", padding=12); info.pack(fill=tk.X)
        python_version, tk_version = runtime_versions(self.root.tk)
        values = [("Application version", application_version()), ("Embedded Python", python_version), ("Embedded Tcl/Tk", tk_version), ("Catalog version", self.service.catalog["manifest"].get("catalog_version", "unknown")), ("Profile schema", PROFILE_SCHEMA_VERSION), ("Update source", f"github.com/{repository()}")]
        for row, (label, value) in enumerate(values): ttk.Label(info, text=label, style="Muted.TLabel").grid(row=row, column=0, sticky=tk.W, pady=3, padx=(0, 24)); ttk.Label(info, text=value).grid(row=row, column=1, sticky=tk.W, pady=3)
        ttk.Button(info, text="Check for updates…", command=self.check_updates).grid(row=0, column=2, rowspan=2, sticky=tk.NE, padx=(24, 0)); info.columnconfigure(1, weight=1)
        storage = ttk.LabelFrame(self.content, text="Local data", style="Card.TLabelframe", padding=12); storage.pack(fill=tk.X, pady=(10, 0)); ttk.Label(storage, text="User-data directory", style="Muted.TLabel").pack(anchor=tk.W); ttk.Label(storage, text=str(self.service.paths.root), wraplength=840).pack(anchor=tk.W, pady=(2, 8)); buttons = ttk.Frame(storage); buttons.pack(anchor=tk.W); ttk.Button(buttons, text="Open directory", command=lambda: self._open_safely(self.service.paths.root)).pack(side=tk.LEFT); ttk.Button(buttons, text="Copy path", command=lambda: self._copy_path(self.service.paths.root)).pack(side=tk.LEFT, padx=6); override = os.environ.get("HD2_PLANNER_DATA_DIR"); ttk.Label(storage, text=f"Environment override: {override or 'not set'}", style="Muted.TLabel").pack(anchor=tk.W, pady=(8, 0))
        profiles = self.service.profiles(); players = ttk.LabelFrame(self.content, text="Players", style="Card.TLabelframe", padding=12); players.pack(fill=tk.X, pady=(10, 0)); profile = self.service.profile or {}; player_names = {f"{value.display_name} [{value.player_id}]": value.player_id for value in profiles}; selected = tk.StringVar(value=next((label for label, value in player_names.items() if value == profile.get("player", {}).get("id")), "")); combo = ttk.Combobox(players, textvariable=selected, values=list(player_names), state="readonly"); combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

        def change_player() -> None:
            try: self.service.open_profile(player_names[selected.get()]); self._profile_opened(); self.show_inventory("warbonds")
            except (ProfileError, OSError, ValueError) as exc: self._show_error("Could not open player", exc)

        ttk.Button(players, text="Switch", command=change_player).pack(side=tk.LEFT, padx=(6, 0)); ttk.Button(players, text="New player…", command=self._new_player).pack(side=tk.LEFT, padx=(6, 0))

    def _reload(self) -> None:
        try: self.service.reload(); self._profile_opened(); self._show_current_route(); self.save_status.set("Reloaded from disk")
        except (ProfileError, OSError, ValueError) as exc: self._save_failed(exc)

    def _saved(self, message: str = "Saved") -> None:
        self.save_status.set(message); self.root.after(2500, lambda: self.save_status.set("Ready") if self.save_status.get() == message else None)

    def _save_failed(self, exc: BaseException) -> None:
        self.save_status.set("Save failed"); self._show_error("Could not save change", f"Your change was not written. The previous profile data is still displayed.\n\n{exc}")

    def _focus_search(self) -> None:
        if hasattr(self, "search_entry") and self.search_entry.winfo_exists(): self.search_entry.focus_set(); self.search_entry.selection_range(0, tk.END)

    def _copy_path(self, path: Path) -> None:
        self.root.clipboard_clear(); self.root.clipboard_append(str(path)); self.save_status.set("Path copied")

    def _open_safely(self, path: Path) -> None:
        try: open_path(path)
        except OSError as exc: self._show_error("Could not open path", f"{path}\n\n{exc}")

    def _dialog(self, title: str, *, width: int = 460, height: int | None = None) -> tk.Toplevel:
        dialog = tk.Toplevel(self.root); dialog.title(title); dialog.transient(self.root); dialog.resizable(height is not None, height is not None); dialog.geometry(f"{width}x{height}" if height else f"{width}x1"); dialog.bind("<Escape>", lambda _event: dialog.destroy()); return dialog

    def _run_dialog(self, dialog: tk.Toplevel) -> None:
        dialog.update_idletasks()
        if dialog.winfo_height() <= 1: dialog.geometry(""); dialog.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - dialog.winfo_width()) // 2); y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - dialog.winfo_height()) // 3); dialog.geometry(f"+{x}+{y}"); dialog.grab_set(); self.root.wait_window(dialog)

    def _show_notice(self, title: str, heading: str, message: str) -> None:
        dialog = self._dialog(title, width=470); body = ttk.Frame(dialog, padding=18); body.pack(fill=tk.BOTH, expand=True); ttk.Label(body, text=heading, style="Heading.TLabel").pack(anchor=tk.W); ttk.Label(body, text=message, style="Muted.TLabel", wraplength=420, justify=tk.LEFT).pack(anchor=tk.W, pady=(5, 16)); ttk.Button(body, text="OK", command=dialog.destroy).pack(anchor=tk.E); self._run_dialog(dialog)

    def _show_error(self, title: str, error: BaseException | str) -> None: self._show_notice(title, "The action could not be completed", str(error))

    def _confirm(self, title: str, heading: str, message: str) -> bool:
        dialog = self._dialog(title, width=470); body = ttk.Frame(dialog, padding=18); body.pack(fill=tk.BOTH, expand=True); ttk.Label(body, text=heading, style="Heading.TLabel", wraplength=420).pack(anchor=tk.W); ttk.Label(body, text=message, style="Muted.TLabel", wraplength=420).pack(anchor=tk.W, pady=(5, 16)); accepted = False
        def accept() -> None:
            nonlocal accepted
            accepted = True; dialog.destroy()
        actions = ttk.Frame(body); actions.pack(fill=tk.X); ttk.Button(actions, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT); ttk.Button(actions, text="Continue", style="Accent.TButton", command=accept).pack(side=tk.RIGHT, padx=(0, 6)); self._run_dialog(dialog); return accepted

    def _choice_dialog(self, title: str, heading: str, choices: list[tuple[str, str]], initial: str) -> str | None:
        dialog = self._dialog(title, width=410); body = ttk.Frame(dialog, padding=18); body.pack(fill=tk.BOTH, expand=True); ttk.Label(body, text=heading, style="Heading.TLabel", wraplength=360).pack(anchor=tk.W); value = tk.StringVar(value=initial)
        for label, key in choices: ttk.Radiobutton(body, text=label, variable=value, value=key).pack(anchor=tk.W, pady=(7, 0))
        result: str | None = None
        def accept() -> None:
            nonlocal result
            result = value.get(); dialog.destroy()
        actions = ttk.Frame(body); actions.pack(fill=tk.X, pady=(16, 0)); ttk.Button(actions, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT); ttk.Button(actions, text="Apply", style="Accent.TButton", command=accept).pack(side=tk.RIGHT, padx=(0, 6)); self._run_dialog(dialog); return result


def launch_gui(service: PlannerService | None = None, *, close_after_ms: int | None = None) -> int:
    try: root = tk.Tk()
    except tk.TclError as exc: raise RuntimeError(f"Could not start the desktop interface: {exc}") from exc
    HD2PlannerApp(root, service)
    if close_after_ms is not None:
        root.after(close_after_ms, root.destroy)
    root.mainloop()
    return 0
