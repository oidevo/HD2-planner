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
from tkinter import ttk

from .appearance import APPEARANCE_CHOICES, load_appearance, resolved_appearance, save_appearance, semantic_tokens
from .constants import INVENTORY_TO_CATALOG
from .gui_model import RESOURCE_FIELDS, InventoryRow, PlannerService
from .presentation import inspector_facts
from .profile import ProfileError
from .storage import read_json, write_json
from .update import repository
from .gui_runtime import runtime_versions
from .version import PROFILE_SCHEMA_VERSION, application_version


STATUS_SYMBOLS = {"unlocked": "☑", "unknown": "?", "locked": "☐"}
STATUS_LABELS = {"unlocked": "Owned", "unknown": "Unreviewed", "locked": "Not owned"}
STATUS_FILTERS = {"All": "all", "Owned": "unlocked", "Not owned": "locked", "Unreviewed": "unknown"}
BULK_UNREVIEWED_LABEL = "Mark unreviewed visible items not owned…"
CATEGORIES = [
    ("Warbonds", "warbonds"), ("Primaries", "primary_weapons"),
    ("Secondaries", "secondary_weapons"), ("Grenades", "grenades"),
    ("Armor", "armor"), ("Boosters", "boosters"),
    ("Stratagems", "stratagems"), ("Support Weapons", "support_weapons"),
    ("Ship Modules", "ship_modules"),
]


def bulk_confirmation_copy(count: int, status: str, only_unknown: bool) -> tuple[str, str]:
    description = "unreviewed visible" if only_unknown else "visible"
    explanation = ("This records Not owned for the selected unreviewed items. " if only_unknown else "")
    return (
        f"Set {count} {description} items to {STATUS_LABELS[status]}?",
        explanation + f"Exactly {count} currently filtered rows will change to {STATUS_LABELS[status]}. Other rows are untouched.",
    )


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
        self.appearance_choice = load_appearance(self.service.paths.settings)
        self.resolved_appearance = resolved_appearance(self.appearance_choice)
        self._warbond_context: str | None = None
        self._undo_change: tuple[str, str, str, str, str | None] | None = None
        self._undo_job: str | None = None
        self._nav_close_job: str | None = None
        try:
            settings = read_json(self.service.paths.settings)
        except (OSError, ValueError):
            settings = {}
        self._nav_pinned = bool(settings.get("nav_pinned", True))
        try:
            self._inspector_width = max(320, int(settings.get("inspector_width", 440)))
        except (TypeError, ValueError):
            self._inspector_width = 440
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
        self.root.after(1500, self._poll_system_appearance)

    def _configure_style(self) -> None:
        self.root.title("HD2 Planner")
        self.root.geometry("1280x800")
        self.root.minsize(720, 640)
        self._apply_appearance()

    def _apply_appearance(self, *, refresh: bool = False) -> None:
        self.resolved_appearance = resolved_appearance(self.appearance_choice)
        tokens = semantic_tokens(self.resolved_appearance)
        self.colors = {
            **tokens, "ink": tokens["text"], "muted": tokens["muted_text"],
            "surface": tokens["canvas"], "gold": tokens["accent"],
            "gold_soft": tokens["accent_soft"], "danger": tokens["error"],
            "success": tokens["unlocked"],
        }
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        self.root.configure(background=tokens["canvas"])
        self.root.option_add("*TCombobox*Listbox.background", tokens["input"])
        self.root.option_add("*TCombobox*Listbox.foreground", tokens["input_text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", tokens["selection"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", tokens["selection_text"])
        self.root.option_add("*Menu.background", tokens["menu"])
        self.root.option_add("*Menu.foreground", tokens["menu_text"])
        self.root.option_add("*Menu.activeBackground", tokens["selection"])
        self.root.option_add("*Menu.activeForeground", tokens["selection_text"])
        style.configure("TFrame", background=tokens["canvas"])
        style.configure("TLabel", background=tokens["canvas"], foreground=tokens["text"])
        style.configure("TButton", background=tokens["button"], foreground=tokens["button_text"],
                        bordercolor=tokens["divider"], lightcolor=tokens["button"], darkcolor=tokens["button"])
        style.map("TButton", background=[("active", tokens["button_active"]), ("disabled", tokens["canvas"])],
                  foreground=[("disabled", tokens["disabled"])])
        style.configure("TEntry", fieldbackground=tokens["input"], foreground=tokens["input_text"],
                        insertcolor=tokens["input_text"], bordercolor=tokens["divider"])
        style.configure("TCombobox", fieldbackground=tokens["input"], background=tokens["button"],
                        foreground=tokens["input_text"], arrowcolor=tokens["text"])
        style.map("TCombobox", fieldbackground=[("readonly", tokens["input"]), ("disabled", tokens["canvas"])],
                  foreground=[("readonly", tokens["input_text"]), ("disabled", tokens["disabled"])],
                  selectbackground=[("readonly", tokens["selection"])],
                  selectforeground=[("readonly", tokens["selection_text"])])
        style.configure("Treeview", background=tokens["card"], fieldbackground=tokens["card"],
                        foreground=tokens["text"], bordercolor=tokens["divider"], rowheight=28)
        style.map("Treeview", background=[("selected", tokens["selection"])],
                  foreground=[("selected", tokens["selection_text"])])
        style.configure("Treeview.Heading", background=tokens["button"], foreground=tokens["heading"],
                        bordercolor=tokens["divider"], font=("TkDefaultFont", 10, "bold"))
        style.map("Treeview.Heading", background=[("active", tokens["button_active"])])
        style.configure("TSeparator", background=tokens["divider"])
        style.configure("TLabelframe", background=tokens["card"], bordercolor=tokens["divider"])
        style.configure("TLabelframe.Label", background=tokens["card"], foreground=tokens["heading"])
        style.configure("TRadiobutton", background=tokens["canvas"], foreground=tokens["text"])
        style.map("TRadiobutton", foreground=[("disabled", tokens["disabled"])])
        style.configure("App.TFrame", background=tokens["canvas"])
        style.configure("Rail.TFrame", background=self.colors["rail"])
        style.configure("Card.TFrame", background=self.colors["card"], relief="solid", borderwidth=1)
        style.configure("Card.TLabelframe", background=self.colors["card"], bordercolor=self.colors["divider"])
        style.configure("Card.TLabelframe.Label", background=self.colors["card"], foreground=self.colors["ink"], font=("TkDefaultFont", 11, "bold"))
        style.configure("Title.TLabel", background=tokens["canvas"], foreground=tokens["heading"], font=("TkDefaultFont", 22, "bold"))
        style.configure("Heading.TLabel", background=tokens["canvas"], foreground=tokens["heading"], font=("TkDefaultFont", 13, "bold"))
        style.configure("Muted.TLabel", background=tokens["canvas"], foreground=tokens["muted_text"])
        style.configure("BannerHeading.TLabel", background=tokens["card"], foreground=tokens["heading"], font=("TkDefaultFont", 13, "bold"))
        style.configure("BannerMuted.TLabel", background=tokens["card"], foreground=tokens["muted_text"])
        style.configure("Rail.TLabel", background=self.colors["rail"], foreground=self.colors["ink"])
        style.configure("RailMuted.TLabel", background=self.colors["rail"], foreground=self.colors["muted"])
        style.configure("RailHeading.TLabel", background=self.colors["rail"], foreground=self.colors["muted"], font=("TkDefaultFont", 9, "bold"))
        style.configure("Rail.TButton", anchor=tk.W, padding=(8, 4), relief="flat", borderwidth=0)
        style.configure("ActiveRail.TButton", anchor=tk.W, padding=(8, 4), relief="flat", borderwidth=0, font=("TkDefaultFont", 10, "bold"), foreground=self.colors["ink"], background=self.colors["gold_soft"])
        style.map("ActiveRail.TButton", background=[("active", self.colors["gold_soft"]), ("!disabled", self.colors["gold_soft"])])
        style.configure("Accent.TButton", background=tokens["accent_soft"], foreground=tokens["text"], font=("TkDefaultFont", 10, "bold"))
        style.map("Accent.TButton", background=[("active", tokens["accent"]), ("!disabled", tokens["accent_soft"])], foreground=[("disabled", tokens["disabled"])])
        style.configure("Inspector.TFrame", background=self.colors["card"], relief="solid", borderwidth=1)
        style.configure("Inspector.TLabel", background=self.colors["card"], foreground=self.colors["ink"])
        style.configure("InspectorMuted.TLabel", background=self.colors["card"], foreground=self.colors["muted"])
        style.configure("Danger.TLabel", background=tokens["canvas"], foreground=tokens["error"])
        if refresh and self.service.profile is not None and hasattr(self, "content"):
            self._show_current_route()

    def _poll_system_appearance(self) -> None:
        if self.appearance_choice == "System":
            current = resolved_appearance("System")
            if current != self.resolved_appearance:
                self._apply_appearance(refresh=True)
        self.root.after(1500, self._poll_system_appearance)

    def _menu(self, parent: tk.Misc) -> tk.Menu:
        return tk.Menu(parent, tearoff=False, background=self.colors["menu"], foreground=self.colors["menu_text"],
                       activebackground=self.colors["selection"], activeforeground=self.colors["selection_text"],
                       disabledforeground=self.colors["disabled"], borderwidth=1)

    def _style_text(self, widget: tk.Text) -> None:
        widget.configure(background=self.colors["input"], foreground=self.colors["input_text"],
                         insertbackground=self.colors["input_text"], selectbackground=self.colors["selection"],
                         selectforeground=self.colors["selection_text"], highlightbackground=self.colors["divider"],
                         highlightcolor=self.colors["focus"])

    def _build_shell(self) -> None:
        self.shell = ttk.Frame(self.root, style="App.TFrame")
        self.shell.pack(fill=tk.BOTH, expand=True)
        self.banner = ttk.Frame(self.shell, style="Card.TFrame", padding=(16, 10))
        self.banner.pack(side=tk.TOP, fill=tk.X)
        identity = ttk.Frame(self.banner, style="Card.TFrame")
        identity.pack(fill=tk.X)
        self.player_label = ttk.Label(identity, text="No profile", style="BannerHeading.TLabel", wraplength=220)
        self.player_label.pack(side=tk.LEFT, padx=(0, 16))
        self.character_meta = ttk.Label(identity, text="No character", style="BannerMuted.TLabel", wraplength=230)
        self.character_meta.pack(side=tk.LEFT, padx=(0, 8))
        self.level_button = ttk.Button(identity, text="Level —", command=lambda: self._edit_banner_value("level"))
        self.level_button.pack(side=tk.LEFT, padx=(0, 12))
        switch_row = ttk.Frame(self.banner, style="Card.TFrame")
        switch_row.pack(fill=tk.X, pady=(5, 0))
        self.character_var = tk.StringVar()
        ttk.Label(switch_row, text="Active character", style="BannerMuted.TLabel").pack(side=tk.LEFT, padx=(0, 7))
        self.character_combo = ttk.Combobox(switch_row, textvariable=self.character_var, state="readonly", width=26)
        self.character_combo.pack(side=tk.LEFT)
        self.character_combo.bind("<<ComboboxSelected>>", self._select_character)
        character_menu_button = ttk.Menubutton(switch_row, text="Characters ▾")
        character_menu = self._menu(character_menu_button)
        character_menu.add_command(label="Add character…", command=self._new_character)
        character_menu.add_command(label="Edit character…", command=self._edit_character)
        character_menu.add_command(label="Delete character…", command=self._delete_character)
        character_menu_button.configure(menu=character_menu)
        character_menu_button.pack(side=tk.LEFT, padx=(7, 0))
        self.undo_button = ttk.Button(switch_row, text="Undo ownership change", command=self._undo_inventory_change, state=tk.DISABLED)
        self.undo_button.pack(side=tk.RIGHT)
        self.legacy_review_button = ttk.Button(switch_row, text="Review legacy mods", command=self.show_legacy_attachments)
        self.banner_resources = ttk.Frame(self.banner, style="Card.TFrame")
        self.banner_resources.pack(fill=tk.X, pady=(8, 0))
        self.resource_buttons: dict[str, ttk.Button] = {}
        for index, (key, label) in enumerate(RESOURCE_FIELDS):
            button = ttk.Button(self.banner_resources, text=f"{label}: —", compound=tk.LEFT, command=lambda value=key: self._edit_banner_value(value))
            button.grid(row=index // 3, column=index % 3, sticky=tk.EW, padx=(0, 8), pady=2)
            self.resource_buttons[key] = button
        for column in range(3): self.banner_resources.columnconfigure(column, weight=1)

        self.main_area = ttk.Frame(self.shell, style="App.TFrame")
        self.main_area.pack(fill=tk.BOTH, expand=True)
        self.sidebar = ttk.Frame(self.main_area, style="Rail.TFrame", width=238, padding=(8, 10, 8, 10))
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)
        ttk.Separator(self.main_area, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        self.content = ttk.Frame(self.main_area, style="App.TFrame", padding=(18, 14, 18, 14))
        self.content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.nav_toggle = ttk.Button(self.sidebar, text="☰  Menu", command=self._toggle_nav)
        self.nav_toggle.pack(fill=tk.X, pady=(0, 8))
        self.nav_heading = ttk.Label(self.sidebar, text="HD2 PLANNER", style="Rail.TLabel", font=("TkDefaultFont", 13, "bold"))
        self.nav_heading.pack(anchor=tk.W, padx=4)

        nav = ttk.Frame(self.sidebar, style="Rail.TFrame")
        nav.pack(fill=tk.BOTH, expand=True)
        self._nav_heading_targets: list[tuple[ttk.Label, ttk.Button]] = []
        self._nav_group(nav, "REQUISITIONS", [("Warbonds", "warbonds", lambda: self.show_inventory("warbonds"))])
        self._nav_group(nav, "STRATAGEMS", [("Stratagems", "stratagems", lambda: self.show_inventory("stratagems"))])
        self._nav_group(nav, "SHIP MANAGEMENT", [("Ship Modules", "ship_modules", lambda: self.show_inventory("ship_modules"))])
        armory = [(label, category, lambda value=category: self.show_inventory(value)) for label, category in CATEGORIES
                  if category not in {"warbonds", "stratagems", "ship_modules"}]
        self._nav_group(nav, "ARMORY", armory)
        self._nav_group(nav, "PLANNING", [
            ("Preferences", "preferences", self.show_preferences),
            ("Observations", "observations", self.show_observations),
            ("Saved Loadouts", "loadouts", self.show_loadouts),
        ])

        footer = ttk.Frame(self.sidebar, style="Rail.TFrame")
        footer.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Separator(footer).pack(fill=tk.X, pady=(8, 8))
        self.nav_context_button = ttk.Button(footer, text="Generate ChatGPT Context", style="Rail.TButton", command=self.generate_context)
        self.nav_context_button.pack(fill=tk.X)
        settings = ttk.Button(footer, text="Settings", style="Rail.TButton", command=self.show_settings)
        settings.pack(fill=tk.X)
        self.nav_buttons["settings"] = (settings, "Settings")
        self.save_status = tk.StringVar(value="Ready")
        self.nav_save_label = ttk.Label(footer, textvariable=self.save_status, style="RailMuted.TLabel", wraplength=204)
        self.nav_save_label.pack(anchor=tk.W, padx=8, pady=(9, 0))
        self._nav_headings = [child for child in nav.winfo_children() if isinstance(child, ttk.Label)]
        self.sidebar.bind("<Enter>", self._nav_enter)
        self.sidebar.bind("<Leave>", self._nav_leave)
        self._set_nav_open(self._nav_pinned)

    def _nav_group(self, parent: ttk.Frame, heading: str, routes: list[tuple[str, str, Callable[[], None]]]) -> None:
        heading_widget = ttk.Label(parent, text=heading, style="RailHeading.TLabel")
        heading_widget.pack(anchor=tk.W, padx=8, pady=(6, 3))
        for label, key, callback in routes:
            button = ttk.Button(parent, text=f"   {label}", style="Rail.TButton", command=callback)
            button.pack(fill=tk.X)
            button.bind("<FocusIn>", self._nav_enter)
            button.bind("<FocusOut>", self._nav_leave)
            self.nav_buttons[key] = (button, label)
        if routes:
            self._nav_heading_targets.append((heading_widget, self.nav_buttons[routes[0][1]][0]))

    def _activate_route(self, route: str) -> None:
        self.current_view = route
        collapsed_labels = {"warbonds": "WB", "stratagems": "ST", "ship_modules": "SM", "primary_weapons": "P", "secondary_weapons": "2", "grenades": "G", "armor": "A", "boosters": "B", "support_weapons": "SW", "preferences": "♥", "observations": "OB", "loadouts": "LO", "settings": "⚙"}
        for key, (button, label) in self.nav_buttons.items():
            active = key == route or (route == "warbond_contents" and key == "warbonds")
            button.configure(style="ActiveRail.TButton" if active else "Rail.TButton", text=(f"›  {label}" if active else f"   {label}") if self._nav_open else collapsed_labels.get(key, label[:2].upper()))

    def _save_ui_settings(self, **changes: Any) -> None:
        try:
            values = read_json(self.service.paths.settings)
        except (OSError, ValueError):
            values = {}
        values.update(changes)
        write_json(self.service.paths.settings, values)

    def _set_nav_open(self, opened: bool) -> None:
        self._nav_open = opened
        self.sidebar.configure(width=238 if opened else 58)
        self.nav_toggle.configure(text="☰  Menu" if opened else "☰", width=0)
        self.nav_context_button.configure(text="Export" if not opened else "Generate ChatGPT Context")
        self.nav_buttons["settings"][0].configure(text="⚙" if not opened else "Settings")
        if opened:
            self.nav_heading.pack(anchor=tk.W, padx=4)
            for heading, target in self._nav_heading_targets: heading.pack(anchor=tk.W, padx=8, pady=(6, 3), before=target)
            self.nav_save_label.pack(anchor=tk.W, padx=8, pady=(9, 0))
        else:
            self.nav_heading.pack_forget()
            for heading in self._nav_headings: heading.pack_forget()
            self.nav_save_label.pack_forget()
        self._activate_route(self.current_view)

    def _toggle_nav(self) -> None:
        self._nav_pinned = not self._nav_pinned
        self._set_nav_open(self._nav_pinned)
        self._save_ui_settings(nav_pinned=self._nav_pinned)

    def _nav_enter(self, _event: tk.Event[Any]) -> None:
        if self._nav_close_job:
            self.root.after_cancel(self._nav_close_job); self._nav_close_job = None
        if not self._nav_pinned: self._set_nav_open(True)

    def _nav_leave(self, _event: tk.Event[Any]) -> None:
        if not self._nav_pinned:
            def close_if_outside() -> None:
                x, y = self.root.winfo_pointerxy()
                inside = self.sidebar.winfo_rootx() <= x < self.sidebar.winfo_rootx() + self.sidebar.winfo_width() and self.sidebar.winfo_rooty() <= y < self.sidebar.winfo_rooty() + self.sidebar.winfo_height()
                if not inside and not self._nav_pinned: self._set_nav_open(False)
            self._nav_close_job = self.root.after(350, close_if_outside)

    def _bind_shortcuts(self) -> None:
        self.root.bind_all("<Control-f>", lambda _event: self._focus_search())
        self.root.bind_all("<Command-f>", lambda _event: self._focus_search())
        self.root.bind_all("<Control-b>", lambda _event: self._toggle_nav())
        self.root.bind_all("<Command-b>", lambda _event: self._toggle_nav())
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
        self.character_meta.configure(text=f"{character.get('display_name', '')} · {character.get('platform', 'unknown')}")
        self.level_button.configure(text=f"Level: {character.get('level', 0)}")
        choices = self.service.character_choices()
        self._character_ids_by_label = {label: character_id for character_id, label in choices}
        labels = list(self._character_ids_by_label)
        self.character_combo.configure(values=labels)
        self.character_var.set(self.service.character_label())
        resources = self.service.resources()
        for key, label in RESOURCE_FIELDS:
            value = resources.get(key)
            self.resource_buttons[key].configure(text=f"{label}: {value:,}" if isinstance(value, int) else f"{label}: —")
        legacy_count = len(character.get("legacy_attachment_review", {}))
        if legacy_count:
            self.legacy_review_button.configure(text=f"Review {legacy_count} legacy mod{'s' if legacy_count != 1 else ''}")
            self.legacy_review_button.pack(side=tk.RIGHT, padx=(0, 8))
        else:
            self.legacy_review_button.pack_forget()
        self.save_status.set("Ready")

    def _edit_banner_value(self, key: str) -> None:
        if self.service.profile is None: return
        button = self.level_button if key == "level" else self.resource_buttons[key]
        parent = button.master
        if key == "level":
            character = self.service.character()
            original = str(character.get("level", 0))
            manager = "pack"
            info = button.pack_info()
        else:
            value = self.service.resources().get(key)
            original = "" if value is None else str(value)
            manager = "grid"
            info = button.grid_info()
        if manager == "pack": button.pack_forget()
        else: button.grid_remove()
        entry = ttk.Entry(parent, width=12)
        entry.insert(0, original)
        if manager == "pack": entry.pack(side=tk.LEFT, padx=(0, 12))
        else: entry.grid(row=info["row"], column=info["column"], sticky=tk.EW, padx=(0, 8))
        entry.focus_set(); entry.select_range(0, tk.END)

        def finish(save: bool) -> None:
            if save:
                raw = entry.get().strip()
                try:
                    if raw and (not raw.isdecimal() or int(raw) < 0):
                        raise ProfileError("Enter a non-negative whole number, or leave a resource blank.")
                    if key == "level":
                        if not raw: raise ProfileError("Level cannot be blank")
                        character = self.service.character()
                        self.service.edit_character(character.get("display_name", ""), character.get("platform", "unknown"), int(raw))
                    else:
                        self.service.set_resources({key: None if not raw else int(raw)})
                except (ValueError, ProfileError, OSError) as exc:
                    self.save_status.set(str(exc)); entry.focus_set(); return
            entry.destroy()
            if manager == "pack": button.pack(**info)
            else: button.grid()
            self._profile_opened()
            if save: self._saved()

        entry.bind("<Return>", lambda _event: finish(True))
        entry.bind("<Escape>", lambda _event: finish(False))

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

    def _delete_character(self) -> None:
        if self.service.profile is None:
            return
        character_id = self.service.character_id or ""
        character = self.service.character()
        display_name = str(character.get("display_name", character_id))
        if len(self.service.profile.get("characters", {})) <= 1:
            self._show_notice("Delete Character", "The final character cannot be deleted", "This command removes one character only. Deleting the player profile would require a separate workflow, which is not provided here.")
            return
        dialog = self._dialog("Delete Character", width=540); body = ttk.Frame(dialog, padding=20); body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text="Delete character", style="Heading.TLabel").pack(anchor=tk.W)
        ttk.Label(body, text=f"{display_name} · {character.get('platform', 'unknown')} · Level {character.get('level', 0)}", style="Muted.TLabel").pack(anchor=tk.W, pady=(3, 12))
        impact = ("A timestamped profile backup will be created first. This removes only this character, its inventory, resources, overrides, onboarding state, and character-scoped gameplay observations. "
                  "Player preferences, other characters, unscoped observations, saved loadouts, catalog data, and application settings remain unchanged.")
        ttk.Label(body, text=impact, wraplength=490, justify=tk.LEFT).pack(anchor=tk.W)
        ttk.Label(body, text=f"Type {display_name!r} or the ID {character_id!r} to confirm:").pack(anchor=tk.W, pady=(15, 5))
        confirmation = tk.StringVar(); entry = ttk.Entry(body, textvariable=confirmation); entry.pack(fill=tk.X)
        error_var = tk.StringVar(); ttk.Label(body, textvariable=error_var, style="Danger.TLabel", wraplength=490).pack(anchor=tk.W, pady=(7, 0))
        actions = ttk.Frame(body); actions.pack(fill=tk.X, pady=(18, 0)); delete_button = ttk.Button(actions, text="Delete character", state=tk.DISABLED); delete_button.pack(side=tk.RIGHT); ttk.Button(actions, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT, padx=(0, 7))
        def update_button(*_args: Any) -> None:
            delete_button.configure(state=tk.NORMAL if confirmation.get() in {display_name, character_id} else tk.DISABLED)
        def delete() -> None:
            try: backup, _next_character = self.service.delete_character(confirmation.get())
            except (ProfileError, OSError, ValueError) as exc: error_var.set(f"Nothing was deleted. {exc}"); return
            dialog.destroy(); self._profile_opened(); self.show_inventory("warbonds"); self._show_notice("Character deleted", f"{display_name} was deleted", f"The remaining profile is active. Backup: {backup}")
        confirmation.trace_add("write", update_button); delete_button.configure(command=delete); entry.focus_set(); self._run_dialog(dialog)

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
            self._clear_undo()
            self.service.select_character(character_id); self._profile_opened(); self._show_current_route()

    def _show_current_route(self) -> None:
        if self.current_view in {category for _label, category in CATEGORIES}: self.show_inventory(self.current_view)
        elif self.current_view == "warbond_contents" and self._warbond_context: self.show_warbond_contents(self._warbond_context)
        elif self.current_view == "preferences": self.show_preferences()
        elif self.current_view == "legacy_attachments": self.show_legacy_attachments()
        elif self.current_view == "observations": self.show_observations()
        elif self.current_view == "loadouts": self.show_loadouts()
        else: self.show_settings()

    def show_legacy_attachments(self) -> None:
        self._activate_route("legacy_attachments"); self._clear_content()
        self._page_header("Legacy attachment answers", "Old global answers are preserved here. Choose a compatible weapon before applying one; the original answer remains for further review.")
        legacy = self.service.character().get("legacy_attachment_review", {})
        if not legacy:
            ttk.Label(self.content, text="No legacy attachment answers for this character.").pack(anchor=tk.W)
            return
        table = ttk.Treeview(self.content, columns=("name", "answer", "weapons"), show="headings", selectmode="browse")
        for key, title, width in (("name", "Attachment", 260), ("answer", "Old answer", 130), ("weapons", "Compatible weapons", 460)):
            table.heading(key, text=title); table.column(key, width=width, minwidth=100, stretch=key == "weapons")
        for attachment_id, state in sorted(legacy.items()):
            item = self.service.index[attachment_id]
            weapons = item.get("facts", {}).get("compatible_weapon_ids", [])
            names = ", ".join(self.service.index[weapon_id]["name"] for weapon_id in weapons if weapon_id in self.service.index)
            table.insert("", tk.END, iid=attachment_id, values=(item["name"], STATUS_LABELS[state["status"]], names or "No compatible weapon linked"))
        table.pack(fill=tk.BOTH, expand=True)
        actions = ttk.Frame(self.content); actions.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(actions, text="Apply to weapon").pack(side=tk.LEFT)
        weapon_var = tk.StringVar()
        weapon_combo = ttk.Combobox(actions, textvariable=weapon_var, state="readonly", width=38)
        weapon_combo.pack(side=tk.LEFT, padx=(6, 8))
        weapon_ids: dict[str, str] = {}

        def choose(_event: tk.Event[Any] | None = None) -> None:
            weapon_ids.clear(); weapon_var.set("")
            if not table.selection(): weapon_combo.configure(values=[]); return
            attachment_id = table.selection()[0]
            for weapon_id in self.service.index[attachment_id].get("facts", {}).get("compatible_weapon_ids", []):
                if weapon_id in self.service.index:
                    label = f"{self.service.index[weapon_id]['name']} [{weapon_id}]"
                    weapon_ids[label] = weapon_id
            weapon_combo.configure(values=list(weapon_ids))
            if weapon_ids: weapon_var.set(next(iter(weapon_ids)))

        def apply() -> None:
            if not table.selection() or weapon_var.get() not in weapon_ids: return
            attachment_id = table.selection()[0]; weapon_id = weapon_ids[weapon_var.get()]
            prior = self.service.attachment_status(weapon_id, attachment_id)
            status = legacy[attachment_id]["status"]
            try:
                self.service.set_attachment_status(weapon_id, attachment_id, status)
                self._remember_undo("weapon_attachments", attachment_id, prior, weapon_id=weapon_id)
                self._saved("Legacy answer applied to one weapon · Undo available")
            except (ProfileError, ValueError, OSError) as exc: self._save_failed(exc)

        table.bind("<<TreeviewSelect>>", choose)
        ttk.Button(actions, text="Apply answer to this weapon", command=apply).pack(side=tk.LEFT)
        ttk.Button(actions, text="Back to inventory", command=lambda: self.show_inventory("primary_weapons")).pack(side=tk.RIGHT)

    def show_inventory(self, category: str, *, warbond_context: str | None = None) -> None:
        if self.service.profile is None:
            return
        self.current_category = category; self._activate_route(category); self._clear_content()
        label = next((label for label, key in CATEGORIES if key == category), category.replace("_", " ").title())
        if category == "warbonds":
            subtitle = "Check the box to record Warbond ownership. Open a row for known rewards; reward ownership stays separate."
        else:
            subtitle = "Click the checkmark to change ownership; click the row for details. ? means unreviewed. Space toggles the selected item."
        subtitle += " " + self.service.ordering_message(category)
        header = self._page_header(label, subtitle); self.review_var = tk.StringVar(); ttk.Label(header, textvariable=self.review_var, style="Muted.TLabel").pack(side=tk.RIGHT, anchor=tk.N, pady=8)

        toolbar = ttk.LabelFrame(self.content, text="Find and filter", style="Card.TLabelframe", padding=(10, 7)); toolbar.pack(fill=tk.X, pady=(0, 10))
        self.search_var = tk.StringVar(); self.search_entry = ttk.Entry(toolbar, textvariable=self.search_var)
        ttk.Label(toolbar, text="Search").grid(row=0, column=0, sticky=tk.W, padx=(0, 5)); self.search_entry.grid(row=0, column=1, sticky=tk.EW, padx=(0, 12)); self.search_var.trace_add("write", lambda *_args: self._schedule_filter())
        self.status_var = tk.StringVar(value="All"); ttk.Label(toolbar, text="Status").grid(row=0, column=2, sticky=tk.W, padx=(0, 5))
        status_combo = ttk.Combobox(toolbar, textvariable=self.status_var, values=list(STATUS_FILTERS), state="readonly", width=13); status_combo.grid(row=0, column=3, sticky=tk.EW, padx=(0, 12)); status_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_inventory())
        self.warbond_var = tk.StringVar(value="All"); self._warbond_ids: dict[str, str | None] = {"All": None}; warbond_column = 0
        if category not in {"warbonds", "ship_modules", "weapon_attachments"}:
            for item in self.service.catalog["collections"]["warbonds"]: self._warbond_ids[item["name"]] = item["id"]
            ttk.Label(toolbar, text="Warbond").grid(row=1, column=warbond_column, sticky=tk.W, padx=(0, 5), pady=(6, 0))
            combo = ttk.Combobox(toolbar, textvariable=self.warbond_var, values=list(self._warbond_ids), state="readonly", width=20); combo.grid(row=1, column=warbond_column + 1, sticky=tk.EW, padx=(0, 12), pady=(6, 0)); combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_inventory()); warbond_column += 2
            if warbond_context:
                label_for_context = next((label for label, value in self._warbond_ids.items() if value == warbond_context), None)
                if label_for_context: self.warbond_var.set(label_for_context)
        self.group_var = tk.StringVar(value="All"); groups = self._groups_for(category); self._group_ids = {"All": None, **{value.replace("_", " ").title(): value for value in groups}}
        if groups:
            ttk.Label(toolbar, text="Group").grid(row=1, column=warbond_column, sticky=tk.W, padx=(0, 5), pady=(6, 0))
            combo = ttk.Combobox(toolbar, textvariable=self.group_var, values=list(self._group_ids), state="readonly", width=17); combo.grid(row=1, column=warbond_column + 1, sticky=tk.EW, pady=(6, 0)); combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_inventory())
        toolbar.columnconfigure(1, weight=1, minsize=150)

        self.inventory_workspace = ttk.Frame(self.content, style="App.TFrame"); self.inventory_workspace.pack(fill=tk.BOTH, expand=True)
        self.inventory_split = tk.PanedWindow(self.inventory_workspace, orient=tk.HORIZONTAL, sashwidth=8, bg=self.colors["divider"], relief=tk.FLAT)
        self.inventory_split.pack(fill=tk.BOTH, expand=True)
        self.table_panel = ttk.Frame(self.inventory_split, style="App.TFrame")
        columns = ("state", "name", "detail", "source"); self.inventory_tree = ttk.Treeview(self.table_panel, columns=columns, show="headings", selectmode="extended")
        for key, title in (("state", "Owned?"), ("name", "Name"), ("detail", "Details"), ("source", "Warbond / Source")): self.inventory_tree.heading(key, text=title)
        self.inventory_tree.column("state", width=125, minwidth=115, stretch=False, anchor=tk.W); self.inventory_tree.column("name", width=250, minwidth=160, stretch=True); self.inventory_tree.column("detail", width=180, minwidth=100, stretch=True); self.inventory_tree.column("source", width=150, minwidth=95, stretch=True)
        scrollbar = ttk.Scrollbar(self.table_panel, orient=tk.VERTICAL, command=self.inventory_tree.yview); self.inventory_tree.configure(yscrollcommand=scrollbar.set); self.inventory_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.inventory_tree.tag_configure("unlocked", foreground=self.colors["success"]); self.inventory_tree.tag_configure("locked", foreground=self.colors["danger"]); self.inventory_tree.tag_configure("unknown", foreground=self.colors["muted"])
        self.inventory_tree.bind("<Button-1>", self._inventory_click); self.inventory_tree.bind("<Double-1>", self._inventory_open); self.inventory_tree.bind("<space>", self._toggle_selected); self.inventory_tree.bind("<<TreeviewSelect>>", self._inventory_selection_changed); self.inventory_tree.bind("<Button-3>", self._inventory_context_menu)
        if sys.platform == "darwin": self.inventory_tree.bind("<Button-2>", self._inventory_context_menu)

        self.inspector = ttk.Frame(self.inventory_split, style="Inspector.TFrame", padding=14, width=self._inspector_width); self._show_inspector_empty()
        self.inventory_split.add(self.table_panel, minsize=260); self.inventory_split.add(self.inspector, minsize=280)
        self._inventory_layout_wide: bool | None = None; self.inventory_workspace.bind("<Configure>", self._layout_inventory_workspace)
        self.inventory_split.bind("<ButtonRelease-1>", self._remember_inspector_width)

        footer = ttk.Frame(self.content, style="App.TFrame"); footer.pack(fill=tk.X, pady=(9, 0)); self.bulk_summary_var = tk.StringVar(); ttk.Label(footer, textvariable=self.bulk_summary_var, style="Muted.TLabel").pack(side=tk.LEFT)
        bulk = ttk.Menubutton(footer, text="Bulk actions"); menu = self._menu(bulk)
        menu.add_command(label=BULK_UNREVIEWED_LABEL, command=self._bulk_lock_unknown)
        menu.add_separator()
        menu.add_command(label="Mark all visible items owned…", command=lambda: self._bulk_set("unlocked", False)); menu.add_command(label="Mark all visible items unreviewed…", command=lambda: self._bulk_set("unknown", False)); menu.add_command(label="Mark all visible items not owned…", command=lambda: self._bulk_set("locked", False)); menu.add_separator(); menu.add_command(label="Reload profile from disk", command=self._reload)
        bulk.configure(menu=menu); bulk.pack(side=tk.RIGHT)
        self._refresh_inventory()

    def _layout_inventory_workspace(self, event: tk.Event[Any]) -> None:
        wide = event.width >= 970
        if wide == self._inventory_layout_wide: return
        self._inventory_layout_wide = wide
        self.inventory_split.configure(orient=tk.HORIZONTAL if wide else tk.VERTICAL)
        if wide:
            self.root.after_idle(lambda: self.inventory_split.sash_place(0, max(470, self.inventory_split.winfo_width() - self._inspector_width), 1) if self.inventory_split.winfo_exists() else None)
        else:
            self.root.after_idle(lambda: self.inventory_split.sash_place(0, 1, max(220, self.inventory_split.winfo_height() - 250)) if self.inventory_split.winfo_exists() else None)

    def _remember_inspector_width(self, _event: tk.Event[Any]) -> None:
        if self._inventory_layout_wide and self.inventory_split.winfo_exists():
            width = self.inventory_split.winfo_width() - self.inventory_split.sash_coord(0)[0]
            self._inspector_width = max(280, width)
            self._save_ui_settings(inspector_width=self._inspector_width)

    def _groups_for(self, category: str) -> list[str]:
        return sorted({row.group for row in self.service.inventory_rows(category) if row.group}, key=str.casefold)

    def _schedule_filter(self) -> None:
        if self._filter_job: self.root.after_cancel(self._filter_job)
        self._filter_job = self.root.after(100, self._refresh_inventory)

    def _refresh_inventory(self) -> None:
        if not hasattr(self, "inventory_tree") or not self.inventory_tree.winfo_exists(): return
        selected = set(self._selected_ids()); status = STATUS_FILTERS[self.status_var.get()]
        self.visible_rows = self.service.inventory_rows(self.current_category, search=self.search_var.get(), status=status, warbond_id=self._warbond_ids.get(self.warbond_var.get()), group=self._group_ids.get(self.group_var.get()))
        self.inventory_tree.delete(*self.inventory_tree.get_children()); warbond_names = {item["id"]: item["name"] for item in self.service.catalog["collections"]["warbonds"]}
        for row in self.visible_rows:
            state = f"{STATUS_SYMBOLS[row.status]}  {STATUS_LABELS[row.status]}"; detail = row.detail + (f" · Level {row.level}" if row.level is not None else "")
            if row.warbond_id and row.category != "warbonds": detail = (detail + " · " + self.service.reward_access(row)).strip(" ·")
            self.inventory_tree.insert("", tk.END, iid=row.item_id, values=(state, row.name, detail, warbond_names.get(row.warbond_id, "")), tags=(row.status,))
            if row.item_id in selected: self.inventory_tree.selection_add(row.item_id)
        all_rows = self.service.inventory_rows(self.current_category); reviewed = sum(row.status != "unknown" for row in all_rows); self.review_var.set(f"Reviewed {reviewed} of {len(all_rows)}")
        unknown_visible = sum(row.status == "unknown" for row in self.visible_rows); self.bulk_summary_var.set(f"{unknown_visible} unreviewed · {len(self.visible_rows)} visible · Bulk actions affect visible rows only")
        if not self.inventory_tree.selection(): self._show_inspector_empty()

    def _show_inspector_empty(self) -> None:
        for child in self.inspector.winfo_children(): child.destroy()
        ttk.Label(self.inspector, text="Item details", style="Inspector.TLabel", font=("TkDefaultFont", 12, "bold")).pack(anchor=tk.W)
        message = "Select an item to review ownership, preference, source, and catalog facts."
        ttk.Label(self.inspector, text=message, style="InspectorMuted.TLabel", wraplength=240, justify=tk.LEFT).pack(anchor=tk.W, pady=(5, 0))

    def _selected_ids(self) -> list[str]: return list(self.inventory_tree.selection())

    @staticmethod
    def click_action(region: str, column: str, item_id: str) -> str:
        if not item_id or region != "cell": return "none"
        return "toggle" if column == "#1" else "select"

    def _inventory_click(self, event: tk.Event[Any]) -> str | None:
        item_id = self.inventory_tree.identify_row(event.y)
        action = self.click_action(self.inventory_tree.identify_region(event.x, event.y), self.inventory_tree.identify_column(event.x), item_id)
        if action == "toggle":
            self._toggle_item(item_id)
            return "break"
        return None

    def _inventory_open(self, event: tk.Event[Any]) -> str | None:
        if self.inventory_tree.identify_column(event.x) == "#1": return "break"
        item_id = self.inventory_tree.identify_row(event.y)
        if self.current_category == "warbonds" and item_id:
            self.show_warbond_contents(item_id)
            return "break"
        return None

    def _toggle_item(self, item_id: str) -> None:
        prior = self.service.inventory_status(self.current_category, item_id)
        next_status = "locked" if prior == "unlocked" else "unlocked"
        try:
            self.service.set_inventory_status(self.current_category, item_id, next_status)
            self._remember_undo(self.current_category, item_id, prior)
            self._saved(f"{STATUS_LABELS[next_status]} · Undo available")
            self._refresh_inventory(); self._inventory_selection_changed()
        except (ProfileError, ValueError, OSError) as exc: self._save_failed(exc)

    def _remember_undo(self, category: str, item_id: str, prior: str, *, weapon_id: str | None = None) -> None:
        self._undo_change = (self.service.character_id or "", category, item_id, prior, weapon_id)
        if self._undo_job: self.root.after_cancel(self._undo_job)
        self._undo_job = self.root.after(7000, self._clear_undo)
        self.undo_button.configure(state=tk.NORMAL)

    def _clear_undo(self) -> None:
        self._undo_change = None; self._undo_job = None
        if hasattr(self, "undo_button") and self.undo_button.winfo_exists(): self.undo_button.configure(state=tk.DISABLED)

    def _undo_inventory_change(self) -> None:
        change = self._undo_change
        if not change: return
        character_id, category, item_id, prior, weapon_id = change
        if self.service.character_id != character_id: self._clear_undo(); return
        try:
            if weapon_id: self.service.set_attachment_status(weapon_id, item_id, prior)
            else: self.service.set_inventory_status(category, item_id, prior)
            self._clear_undo(); self._saved("Change undone")
            if self.current_view == "warbond_contents" and self._warbond_context: self.show_warbond_contents(self._warbond_context)
            elif self.current_view == "legacy_attachments": self.show_legacy_attachments()
            else: self._refresh_inventory(); self._inventory_selection_changed()
        except (ProfileError, ValueError, OSError) as exc: self._save_failed(exc)

    def _toggle_selected(self, _event: tk.Event[Any] | None = None) -> str:
        selected = self._selected_ids()
        if not selected: return "break"
        if len(selected) == 1: self._toggle_item(selected[0])
        return "break"

    def _inventory_context_menu(self, event: tk.Event[Any]) -> None:
        row = self.inventory_tree.identify_row(event.y)
        if row and row not in self.inventory_tree.selection(): self.inventory_tree.selection_set(row)
        menu = self._menu(self.root)
        for status in ("unlocked", "unknown", "locked"): menu.add_command(label=f"Set {STATUS_LABELS[status]}", command=lambda value=status: self._set_selected(value))
        try: menu.tk_popup(event.x_root, event.y_root)
        finally: menu.grab_release()

    def _set_selected(self, status: str) -> None:
        try: self.service.bulk_set_status(self.current_category, self._selected_ids(), status); self._saved(); self._refresh_inventory()
        except (ProfileError, ValueError, OSError) as exc: self._save_failed(exc)

    def _bulk_lock_unknown(self) -> None: self._bulk_set("locked", True)

    def _bulk_set(self, status: str, only_unknown: bool) -> None:
        ids = [row.item_id for row in self.visible_rows if row.status != status and (not only_unknown or row.status == "unknown")]
        if not ids: self._show_notice("No changes", "Nothing to update", "No matching visible items need this change."); return
        heading, message = bulk_confirmation_copy(len(ids), status, only_unknown)
        if not self._confirm("Confirm bulk change", heading, message): return
        try:
            changed = self.service.bulk_set_status(self.current_category, ids, status, only_unknown=only_unknown); self._saved(f"Saved {changed} item changes"); self._refresh_inventory()
        except (ProfileError, ValueError, OSError) as exc: self._save_failed(exc)

    def _inventory_selection_changed(self, _event: tk.Event[Any] | None = None) -> None:
        selected = self._selected_ids()
        if not selected: self._show_inspector_empty(); return
        if len(selected) > 1:
            for child in self.inspector.winfo_children(): child.destroy()
            ttk.Label(self.inspector, text=f"{len(selected)} items selected", style="Inspector.TLabel", font=("TkDefaultFont", 12, "bold")).pack(anchor=tk.W); ttk.Label(self.inspector, text="Use the context menu to set ownership for this selection.", style="InspectorMuted.TLabel", wraplength=240).pack(anchor=tk.W, pady=(5, 8)); return
        row = next((value for value in self.visible_rows if value.item_id == selected[0]), None)
        if row is None: return
        for child in self.inspector.winfo_children(): child.destroy()
        ttk.Label(self.inspector, text=row.name, style="Inspector.TLabel", font=("TkDefaultFont", 13, "bold"), wraplength=410).pack(anchor=tk.W)
        ttk.Label(self.inspector, text=f"{STATUS_SYMBOLS[row.status]}  {STATUS_LABELS[row.status]}", style="Inspector.TLabel").pack(anchor=tk.W, pady=(5, 0)); ttk.Label(self.inspector, text=f"Preference: {self.service.item_preference(row.item_id).title()}", style="InspectorMuted.TLabel").pack(anchor=tk.W, pady=(2, 0))
        warbond_names = {item["id"]: item["name"] for item in self.service.catalog["collections"]["warbonds"]}; source = warbond_names.get(row.warbond_id) or "Catalog / base item"
        ttk.Label(self.inspector, text=f"Source: {source}", style="InspectorMuted.TLabel", wraplength=240).pack(anchor=tk.W, pady=(2, 10))
        if row.warbond_id and self.current_category != "warbonds":
            ttk.Label(self.inspector, text=self.service.reward_access(row), style="InspectorMuted.TLabel", wraplength=410).pack(anchor=tk.W, pady=(0, 5))
        facts = [f"{label}: {value}" for label, value in inspector_facts(self.current_category, row.facts)]
        if row.level is not None: facts.insert(0, f"Recorded weapon level: {row.level}")
        if facts:
            ttk.Separator(self.inspector).pack(fill=tk.X, pady=(0, 9)); ttk.Label(self.inspector, text="Relevant facts", style="Inspector.TLabel", font=("TkDefaultFont", 10, "bold")).pack(anchor=tk.W); ttk.Label(self.inspector, text="\n".join(facts), style="InspectorMuted.TLabel", wraplength=410, justify=tk.LEFT).pack(anchor=tk.W, pady=(4, 10))
        if self.current_category in {"primary_weapons", "secondary_weapons", "support_weapons"}:
            self._weapon_progression_inline(row)
        actions = ttk.Frame(self.inspector, style="Inspector.TFrame"); actions.pack(fill=tk.X, side=tk.BOTTOM)
        if self.current_category == "warbonds":
            ttk.Label(actions, text="Owning a Warbond does not mean every reward is owned. Reward ownership stays separate.", style="InspectorMuted.TLabel", wraplength=410, justify=tk.LEFT).pack(fill=tk.X, pady=(0, 7))
            ttk.Button(actions, text="Browse known contents", style="Accent.TButton", command=lambda: self.show_warbond_contents(row.item_id)).pack(fill=tk.X, pady=(0, 5))
        ttk.Button(actions, text="Set ownership…", command=lambda: self._availability_dialog(row)).pack(fill=tk.X); ttk.Button(actions, text="Set preference…", command=lambda: self._preference_dialog(row.item_id)).pack(fill=tk.X, pady=(5, 0))
        ttk.Label(actions, text="Ownership and preference are separate records.", style="InspectorMuted.TLabel", wraplength=410, justify=tk.LEFT).pack(fill=tk.X, pady=(7, 0))
    def _weapon_progression_inline(self, weapon: InventoryRow) -> None:
        level_row = ttk.Frame(self.inspector, style="Inspector.TFrame")
        level_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(level_row, text="Weapon level", style="Inspector.TLabel").pack(side=tk.LEFT, padx=(0, 6))
        level_entry = ttk.Entry(level_row, width=7)
        if weapon.level is not None: level_entry.insert(0, str(weapon.level))
        level_entry.pack(side=tk.LEFT)
        def save_level(_event: tk.Event[Any] | None = None) -> str:
            raw = level_entry.get().strip()
            try:
                if raw and not raw.isdecimal(): raise ProfileError("Weapon level must be a non-negative whole number")
                self.service.set_weapon_level(weapon.category, weapon.item_id, int(raw) if raw else None)
                self._saved("Weapon level saved")
                self._refresh_inventory()
            except (ProfileError, ValueError, OSError) as exc: self._save_failed(exc)
            return "break"
        level_entry.bind("<Return>", save_level)
        level_entry.bind("<Escape>", lambda _event: (level_entry.delete(0, tk.END), level_entry.insert(0, "" if weapon.level is None else str(weapon.level)), "break")[2])
        ttk.Button(level_row, text="Save", command=save_level).pack(side=tk.LEFT, padx=(5, 0))
        section = ttk.LabelFrame(self.inspector, text="Compatible attachments · this weapon", padding=7)
        section.pack(fill=tk.BOTH, expand=True, pady=(6, 8))
        rows = self.service.inventory_rows("weapon_attachments", compatible_weapon_id=weapon.item_id)
        if not rows:
            ttk.Label(section, text="No compatible attachments linked in the catalog.").pack(anchor=tk.W)
            return
        tree = ttk.Treeview(section, columns=("owned", "name", "slot"), show="headings", height=min(7, len(rows)), selectmode="browse")
        for key, title, width in (("owned", "Owned?", 110), ("name", "Attachment", 230), ("slot", "Slot", 100)):
            tree.heading(key, text=title); tree.column(key, width=width, minwidth=75, stretch=key == "name")
        for item in rows:
            legacy = self.service.legacy_attachment_status(item.item_id)
            state = self.service.attachment_status(weapon.item_id, item.item_id)
            name = item.name + (f" · legacy {STATUS_LABELS[legacy]}" if legacy else "")
            tree.insert("", tk.END, iid=item.item_id, values=(f"{STATUS_SYMBOLS[state]} {STATUS_LABELS[state]}", name, item.group or ""))
        tree.pack(fill=tk.BOTH, expand=True)

        def update(attachment_id: str, status: str) -> None:
            try:
                prior = self.service.attachment_status(weapon.item_id, attachment_id)
                self.service.set_attachment_status(weapon.item_id, attachment_id, status)
                self._remember_undo("weapon_attachments", attachment_id, prior, weapon_id=weapon.item_id)
                tree.set(attachment_id, "owned", f"{STATUS_SYMBOLS[status]} {STATUS_LABELS[status]}")
                self._saved("Weapon attachment saved · Undo available")
            except (ProfileError, ValueError, OSError) as exc: self._save_failed(exc)

        def click(event: tk.Event[Any]) -> str | None:
            attachment_id = tree.identify_row(event.y)
            if attachment_id and tree.identify_column(event.x) == "#1":
                state = self.service.attachment_status(weapon.item_id, attachment_id)
                update(attachment_id, "locked" if state == "unlocked" else "unlocked")
                return "break"
            return None

        tree.bind("<Button-1>", click)
        tree.bind("<space>", lambda _event: (update(tree.selection()[0], "locked" if self.service.attachment_status(weapon.item_id, tree.selection()[0]) == "unlocked" else "unlocked"), "break")[1] if tree.selection() else "break")
        actions = ttk.Frame(section); actions.pack(fill=tk.X, pady=(5, 0))
        ttk.Button(actions, text="Set unreviewed", command=lambda: update(tree.selection()[0], "unknown") if tree.selection() else None).pack(side=tk.LEFT)
        ttk.Button(actions, text="Use legacy answer for this weapon", command=lambda: update(tree.selection()[0], self.service.legacy_attachment_status(tree.selection()[0])) if tree.selection() and self.service.legacy_attachment_status(tree.selection()[0]) else None).pack(side=tk.LEFT, padx=(5, 0))

    def _availability_dialog(self, row: InventoryRow) -> None:
        value = self._choice_dialog("Set Ownership", row.name, [(label, status) for status, label in STATUS_LABELS.items()], row.status)
        if value: self._set_selected(value)

    def show_warbond_contents(self, warbond_id: str) -> None:
        self._warbond_context = warbond_id; self._activate_route("warbond_contents"); self._clear_content()
        warbond = next((item for item in self.service.catalog["collections"]["warbonds"] if item["id"] == warbond_id), None)
        if warbond is None:
            self._show_error("Warbond Contents", "The selected Warbond is no longer in the catalog."); return
        header = self._page_header(
            "Known catalog-linked contents",
            f"{warbond['name']} · Linked rewards only. Page labels come from catalog facts; page gates and Medals spent are unverified. Unmapped rewards may be missing.",
        )
        ttk.Button(header, text="Back to Warbonds", command=lambda: self.show_inventory("warbonds")).pack(side=tk.RIGHT, anchor=tk.N, pady=5)
        filters = ttk.LabelFrame(self.content, text="Filter known links", style="Card.TLabelframe", padding=(10, 7)); filters.pack(fill=tk.X, pady=(0, 10))
        category_labels = {
            "All supported categories": "all", "Primary weapons": "primary_weapons", "Secondary weapons": "secondary_weapons",
            "Support weapons": "support_weapons", "Grenades": "grenades", "Armor": "armor", "Boosters": "boosters",
            "Stratagems": "stratagems", "Ship modules": "ship_modules",
        }
        category_var = tk.StringVar(value="All supported categories"); status_var = tk.StringVar(value="All")
        ttk.Label(filters, text="Category").pack(side=tk.LEFT); category_combo = ttk.Combobox(filters, textvariable=category_var, values=list(category_labels), state="readonly", width=24); category_combo.pack(side=tk.LEFT, padx=(6, 16))
        ttk.Label(filters, text="Ownership").pack(side=tk.LEFT); status_combo = ttk.Combobox(filters, textvariable=status_var, values=list(STATUS_FILTERS), state="readonly", width=13); status_combo.pack(side=tk.LEFT, padx=(6, 0))
        tree = ttk.Treeview(self.content, columns=("category", "name", "page", "availability", "access"), show="headings", selectmode="browse")
        for key, title, width in (("category", "Category", 140), ("name", "Item", 250), ("page", "Catalog page", 100), ("availability", "Owned?", 130), ("access", "Purchase access", 240)):
            tree.heading(key, text=title); tree.column(key, width=width, minwidth=80, stretch=key in {"name", "access"})
        tree.pack(fill=tk.BOTH, expand=True)
        rows_by_id: dict[str, InventoryRow] = {}
        category_names = {value: label for label, value in category_labels.items()}

        def refresh() -> None:
            nonlocal rows_by_id
            rows = self.service.warbond_contents(warbond_id, category=category_labels[category_var.get()], status=STATUS_FILTERS[status_var.get()])
            rows_by_id = {row.item_id: row for row in rows}; tree.delete(*tree.get_children())
            pages = sorted({row.facts.get("warbond_page") for row in rows if isinstance(row.facts.get("warbond_page"), int)})
            for page in [*pages, None]:
                members = [row for row in rows if (row.facts.get("warbond_page") if isinstance(row.facts.get("warbond_page"), int) else None) == page]
                if not members: continue
                title = f"Catalog page {page} · access unverified" if page is not None else "Page unverified / not mapped"
                tree.insert("", tk.END, iid=f"group-{page}", values=(title, "", "", "", ""), tags=("group",))
                for row in members:
                    tree.insert("", tk.END, iid=row.item_id, values=(category_names.get(row.category, row.category.replace("_", " ").title()), row.name, page or "Unverified", f"{STATUS_SYMBOLS[row.status]} {STATUS_LABELS[row.status]}", self.service.reward_access(row)), tags=(row.status,))
            count_var.set(f"{len(rows)} catalog-linked items shown · unmapped rewards are not counted · page gates unverified")

        category_combo.bind("<<ComboboxSelected>>", lambda _event: refresh()); status_combo.bind("<<ComboboxSelected>>", lambda _event: refresh())
        for status, color in (("unlocked", self.colors["unlocked"]), ("locked", self.colors["locked"]), ("unknown", self.colors["unknown"])): tree.tag_configure(status, foreground=color)
        tree.tag_configure("group", foreground=self.colors["accent"])
        controls = ttk.Frame(self.content); controls.pack(fill=tk.X, pady=(9, 0)); count_var = tk.StringVar(); ttk.Label(controls, textvariable=count_var, style="Muted.TLabel").pack(side=tk.LEFT)

        def set_selected(status: str) -> None:
            selected = tree.selection()
            if not selected or selected[0] not in rows_by_id: return
            row = rows_by_id[selected[0]]
            try: self.service.set_inventory_status(row.category, row.item_id, status); self._saved(); refresh()
            except (ProfileError, ValueError, OSError) as exc: self._save_failed(exc)

        def open_category() -> None:
            selected = tree.selection()
            if selected and selected[0] in rows_by_id:
                self.show_inventory(rows_by_id[selected[0]].category, warbond_context=warbond_id)

        open_button = ttk.Button(controls, text="Open category with this Warbond filter", command=open_category, state=tk.DISABLED); open_button.pack(side=tk.RIGHT)
        availability = ttk.Menubutton(controls, text="Set item ownership", state=tk.DISABLED); availability_menu = self._menu(availability)
        for status in ("unlocked", "unknown", "locked"): availability_menu.add_command(label=STATUS_LABELS[status], command=lambda value=status: set_selected(value))
        availability.configure(menu=availability_menu); availability.pack(side=tk.RIGHT, padx=(0, 7))
        def selection_changed(_event: tk.Event[Any] | None = None) -> None:
            state = tk.NORMAL if tree.selection() and tree.selection()[0] in rows_by_id else tk.DISABLED; availability.configure(state=state); open_button.configure(state=state)
        tree.bind("<<TreeviewSelect>>", selection_changed); refresh()
        def click(event: tk.Event[Any]) -> str | None:
            item_id = tree.identify_row(event.y)
            if item_id in rows_by_id and tree.identify_column(event.x) == "#4":
                row = rows_by_id[item_id]
                next_status = "locked" if row.status == "unlocked" else "unlocked"
                try:
                    self.service.set_inventory_status(row.category, row.item_id, next_status)
                    self._remember_undo(row.category, row.item_id, row.status)
                    self._saved("Reward ownership saved · Undo available"); refresh()
                except (ProfileError, ValueError, OSError) as exc: self._save_failed(exc)
                return "break"
            return None
        tree.bind("<Button-1>", click)
        tree.bind("<space>", lambda _event: (set_selected("locked" if rows_by_id[tree.selection()[0]].status == "unlocked" else "unlocked"), "break")[1] if tree.selection() and tree.selection()[0] in rows_by_id else "break")
        tree.bind("<Return>", lambda _event: (open_category(), "break")[1])

    def show_preferences(self) -> None:
        self._activate_route("preferences"); self._clear_content(); self._page_header("Preferences", "Personal planning signals included in ChatGPT context. They may guide later planning, but do not score items, change availability, or alter a loadout today. Only explicit non-neutral choices appear.")
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
        tools = ttk.Frame(item_frame); tools.pack(fill=tk.X, pady=(0, 8)); search = tk.StringVar(); ttk.Label(tools, text="Search explicit preferences").pack(side=tk.LEFT); search_entry = ttk.Entry(tools, textvariable=search, width=32); search_entry.pack(side=tk.LEFT, padx=(6, 8)); ttk.Button(tools, text="Add preference…", style="Accent.TButton", command=self._preference_dialog).pack(side=tk.RIGHT)
        tree = ttk.Treeview(item_frame, columns=("name", "preference", "scope"), show="headings", selectmode="browse"); tree.heading("name", text="Item"); tree.heading("preference", text="Preference"); tree.heading("scope", text="Source"); tree.column("name", width=460, minwidth=220); tree.column("preference", width=150, minwidth=120); tree.column("scope", width=180, minwidth=150); tree.pack(fill=tk.BOTH, expand=True)
        empty_var = tk.StringVar(); ttk.Label(item_frame, textvariable=empty_var, style="Muted.TLabel").pack(anchor=tk.W, pady=(6, 0))

        def redraw(*_args: Any) -> None:
            tree.delete(*tree.get_children()); rows = self.service.explicit_item_preferences(search=search.get())
            for row in rows: tree.insert("", tk.END, iid=row.item_id, values=(row.name, row.preference.title(), row.scope))
            empty_var.set("No explicit item preferences match. Add one when an item matters to your planning." if not rows else f"{len(rows)} explicit preference{'s' if len(rows) != 1 else ''}")

        search.trace_add("write", redraw); redraw(); controls = ttk.Frame(item_frame); controls.pack(fill=tk.X, pady=(8, 0))
        edit_button = ttk.Button(controls, text="Edit selected…", command=lambda: self._preference_dialog(tree.selection()[0]) if tree.selection() else None)
        edit_button.pack(side=tk.RIGHT)
        remove_button = ttk.Button(controls, text="Remove explicit preference", command=lambda: self._remove_preference(tree.selection()[0]) if tree.selection() else None)
        remove_button.pack(side=tk.RIGHT, padx=(0, 6))

        def preference_selection_changed(_event: tk.Event[Any] | None = None) -> None:
            selected = tree.selection()
            edit_button.configure(state=tk.NORMAL if selected else tk.DISABLED)
            remove_button.configure(state=tk.NORMAL if selected else tk.DISABLED)

        tree.bind("<<TreeviewSelect>>", preference_selection_changed)
        preference_selection_changed()

    def _preference_dialog(self, item_id: str | None = None) -> None:
        candidates: dict[str, str] = {}
        for category in INVENTORY_TO_CATALOG:
            for row in self.service.inventory_rows(category): candidates[row.item_id] = row.name
        item_map = {f"{name}  [{item_id}]": item_id for item_id, name in sorted(candidates.items(), key=lambda value: value[1].casefold())}; reverse = {value: key for key, value in item_map.items()}
        dialog = self._dialog("Item Preference", width=520); body = ttk.Frame(dialog, padding=18); body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text="Set an item preference", style="Heading.TLabel").grid(row=0, column=0, columnspan=2, sticky=tk.W); ttk.Label(body, text="This optional planning signal is exported to ChatGPT context. It does not score items, change availability, or alter loadouts.", style="Muted.TLabel", wraplength=460).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(2, 12))
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
        form.columnconfigure(1, weight=1); ttk.Label(form, text="Notes").grid(row=len(rows), column=0, sticky=tk.NW, pady=5); notes = tk.Text(form, height=7, wrap=tk.WORD, relief=tk.SOLID, borderwidth=1); self._style_text(notes); notes.grid(row=len(rows), column=1, sticky=tk.EW, padx=(12, 0), pady=5)

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
        tree.pack(fill=tk.BOTH, expand=True); detail = tk.Text(self.content, height=8, wrap=tk.WORD, state=tk.DISABLED, relief=tk.SOLID, borderwidth=1); self._style_text(detail); detail.pack(fill=tk.X, pady=(9, 0))

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
        appearance = ttk.LabelFrame(self.content, text="Appearance", style="Card.TLabelframe", padding=12); appearance.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(appearance, text="System follows macOS and updates while the app is running. Light and Dark remain fixed.", style="Muted.TLabel").pack(anchor=tk.W, pady=(0, 6))
        choice = tk.StringVar(value=self.appearance_choice)
        def set_appearance() -> None:
            try: save_appearance(self.service.paths.settings, choice.get())
            except (OSError, ValueError) as exc: self._show_error("Could not save appearance", exc); return
            self.appearance_choice = choice.get(); self._apply_appearance(refresh=True); self._saved(f"Appearance: {self.appearance_choice}")
        for label in APPEARANCE_CHOICES: ttk.Radiobutton(appearance, text=label, variable=choice, value=label, command=set_appearance).pack(side=tk.LEFT, padx=(0, 16))
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
        dialog = tk.Toplevel(self.root); dialog.configure(background=self.colors["dialog"]); dialog.title(title); dialog.transient(self.root); dialog.resizable(height is not None, height is not None); dialog.geometry(f"{width}x{height}" if height else f"{width}x1"); dialog.bind("<Escape>", lambda _event: dialog.destroy()); return dialog

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
