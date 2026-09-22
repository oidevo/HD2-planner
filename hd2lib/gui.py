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
from tkinter import messagebox, simpledialog, ttk

from .constants import INVENTORY_TO_CATALOG, PREFERENCE_STATES
from .gui_model import InventoryRow, PlannerService
from .profile import ProfileError
from .update import repository
from .version import PROFILE_SCHEMA_VERSION, application_version


STATUS_SYMBOLS = {"unlocked": "✓", "unknown": "?", "locked": "✕"}
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
        self.visible_rows: list[InventoryRow] = []
        self._filter_job: str | None = None
        self._character_ids_by_label: dict[str, str] = {}
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
            if open_errors:
                self.root.after(25, lambda: messagebox.showwarning(
                    "Profiles could not be opened",
                    "Existing profile files were left unchanged. You can create a new profile.\n\n" + "\n".join(open_errors),
                    parent=self.root,
                ))
            self.root.after(50, self._first_run)

    def _build_shell(self) -> None:
        self.root.title("HD2 Planner")
        self.root.geometry("1180x760")
        self.root.minsize(900, 600)
        style = ttk.Style(self.root)
        if "clam" in style.theme_names() and sys.platform != "darwin":
            style.theme_use("clam")
        style.configure("Sidebar.TFrame", background="#eef1f4")
        style.configure("Title.TLabel", font=("TkDefaultFont", 18, "bold"))
        style.configure("Heading.TLabel", font=("TkDefaultFont", 13, "bold"))
        style.configure("Muted.TLabel", foreground="#59636e")

        outer = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True)
        self.sidebar = ttk.Frame(outer, style="Sidebar.TFrame", padding=12, width=230)
        self.content = ttk.Frame(outer, padding=16)
        outer.add(self.sidebar, weight=0)
        outer.add(self.content, weight=1)

        ttk.Label(self.sidebar, text="HD2 Planner", style="Title.TLabel").pack(anchor=tk.W, pady=(0, 14))
        ttk.Label(self.sidebar, text="Character", style="Heading.TLabel").pack(anchor=tk.W)
        self.player_label = ttk.Label(self.sidebar, text="No profile", style="Muted.TLabel")
        self.player_label.pack(anchor=tk.W, pady=(3, 4))
        self.character_var = tk.StringVar()
        self.character_combo = ttk.Combobox(self.sidebar, textvariable=self.character_var, state="readonly", width=27)
        self.character_combo.pack(fill=tk.X)
        self.character_combo.bind("<<ComboboxSelected>>", self._select_character)
        character_actions = ttk.Frame(self.sidebar)
        character_actions.pack(fill=tk.X, pady=(5, 12))
        ttk.Button(character_actions, text="New", command=self._new_character).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(character_actions, text="Edit", command=self._edit_character).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        ttk.Label(self.sidebar, text="Inventory", style="Heading.TLabel").pack(anchor=tk.W, pady=(2, 3))
        for label, category in CATEGORIES:
            ttk.Button(self.sidebar, text=label, command=lambda value=category: self.show_inventory(value)).pack(fill=tk.X, pady=1)

        secondary = ttk.Frame(self.sidebar)
        secondary.pack(fill=tk.X, pady=(12, 0))
        for label, callback in (
            ("Preferences", self.show_preferences), ("Observations", self.show_observations),
            ("Saved Loadouts", self.show_loadouts),
        ):
            ttk.Button(secondary, text=label, command=callback).pack(fill=tk.X, pady=1)
        ttk.Separator(self.sidebar).pack(fill=tk.X, pady=12)
        ttk.Button(self.sidebar, text="Generate ChatGPT Context", command=self.generate_context).pack(fill=tk.X, pady=2)
        ttk.Button(self.sidebar, text="Check for Updates", command=self.check_updates).pack(fill=tk.X, pady=2)
        ttk.Button(self.sidebar, text="Settings", command=self.show_settings).pack(fill=tk.X, pady=2)
        ttk.Button(self.sidebar, text="New Player…", command=self._new_player).pack(fill=tk.X, pady=(10, 2))

        self.save_status = tk.StringVar(value="Ready")
        ttk.Label(self.sidebar, textvariable=self.save_status, style="Muted.TLabel", wraplength=200).pack(side=tk.BOTTOM, anchor=tk.W, pady=(12, 0))

    def _bind_shortcuts(self) -> None:
        self.root.bind_all("<Control-f>", lambda _event: self._focus_search())
        self.root.bind_all("<Command-f>", lambda _event: self._focus_search())
        self.root.bind_all("<Escape>", lambda _event: self.root.focus_set())

    def _clear_content(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()

    def _profile_opened(self) -> None:
        profile = self.service.profile
        assert profile is not None
        self.player_label.configure(text=profile["player"]["display_name"])
        choices = self.service.character_choices()
        self._character_ids_by_label = {label: character_id for character_id, label in choices}
        labels = list(self._character_ids_by_label)
        self.character_combo.configure(values=labels)
        selected = self.service.character_label()
        self.character_var.set(selected)
        self.save_status.set(f"Data: {self.service.paths.root}")

    def _first_run(self) -> None:
        if not self._profile_dialog(first_run=True):
            self.root.destroy()
            return
        self._profile_opened()
        self.show_inventory("warbonds")
        messagebox.showinfo(
            "Welcome to HD2 Planner",
            "Start by checking the Warbonds you own, then review your inventory.\n\nChanges save automatically.",
            parent=self.root,
        )

    def _profile_dialog(self, *, first_run: bool = False) -> bool:
        title = "Set up HD2 Planner" if first_run else "New Player"
        result = self._form_dialog(title, [
            ("Player/display name", ""), ("Character name", "Main"),
            ("Platform", "PC"), ("Level", "0"),
        ])
        if result is None:
            return False
        try:
            self.service.create_profile(result[0], result[1], result[2], int(result[3]))
            return True
        except (ValueError, ProfileError, OSError) as exc:
            messagebox.showerror("Could not create profile", str(exc), parent=self.root)
            return False

    def _new_player(self) -> None:
        if self._profile_dialog():
            self._profile_opened()
            self.show_inventory("warbonds")

    def _new_character(self) -> None:
        if self.service.profile is None:
            return
        result = self._form_dialog("New Character", [("Character name", ""), ("Platform", "PC"), ("Level", "0")])
        if result is None:
            return
        try:
            self.service.add_character(result[0], result[1], int(result[2]))
            self._profile_opened()
            self.show_inventory(self.current_category)
        except (ValueError, ProfileError, OSError) as exc:
            messagebox.showerror("Could not add character", str(exc), parent=self.root)

    def _edit_character(self) -> None:
        if self.service.profile is None:
            return
        character = self.service.character()
        result = self._form_dialog("Edit Character", [
            ("Character name", character.get("display_name", "")),
            ("Platform", character.get("platform", "")), ("Level", str(character.get("level", 0))),
        ])
        if result is None:
            return
        try:
            self.service.edit_character(result[0], result[1], int(result[2]))
            self._saved()
            self._profile_opened()
        except (ValueError, ProfileError, OSError) as exc:
            self._save_failed(exc)

    def _form_dialog(self, title: str, fields: list[tuple[str, str]]) -> list[str] | None:
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        entries: list[ttk.Entry] = []
        for row, (label, initial) in enumerate(fields):
            ttk.Label(dialog, text=label).grid(row=row, column=0, sticky=tk.W, padx=12, pady=6)
            entry = ttk.Entry(dialog, width=34)
            entry.insert(0, initial)
            entry.grid(row=row, column=1, padx=12, pady=6)
            entries.append(entry)
        result: list[str] | None = None

        def accept() -> None:
            nonlocal result
            result = [entry.get().strip() for entry in entries]
            dialog.destroy()

        buttons = ttk.Frame(dialog)
        buttons.grid(row=len(fields), column=0, columnspan=2, sticky=tk.E, padx=12, pady=12)
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=4)
        ttk.Button(buttons, text="Save", command=accept).pack(side=tk.LEFT)
        dialog.bind("<Return>", lambda _event: accept())
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        entries[0].focus_set()
        dialog.grab_set()
        self.root.wait_window(dialog)
        return result

    def _select_character(self, _event: tk.Event[Any] | None = None) -> None:
        character_id = self._character_ids_by_label.get(self.character_var.get())
        if character_id:
            self.service.select_character(character_id)
            self.show_inventory(self.current_category)

    def show_inventory(self, category: str) -> None:
        if self.service.profile is None:
            return
        self.current_category = category
        self._clear_content()
        label = next((label for label, key in CATEGORIES if key == category), category.replace("_", " ").title())
        ttk.Label(self.content, text=label, style="Title.TLabel").pack(anchor=tk.W)
        if category == "weapon_attachments":
            ttk.Label(
                self.content,
                text="Attachment compatibility is catalog-backed. Ownership is global because per-weapon progression is not reliably available.",
                style="Muted.TLabel", wraplength=850,
            ).pack(anchor=tk.W, pady=(2, 8))
        else:
            ttk.Label(self.content, text="Double-click an item or press Space to toggle unlocked. Right-click for all states.", style="Muted.TLabel").pack(anchor=tk.W, pady=(2, 8))

        filters = ttk.Frame(self.content)
        filters.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(filters, text="Search:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(filters, textvariable=self.search_var, width=30)
        self.search_entry.pack(side=tk.LEFT, padx=(5, 12))
        self.search_var.trace_add("write", lambda *_args: self._schedule_filter())
        ttk.Label(filters, text="Status:").pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="All")
        status_combo = ttk.Combobox(filters, textvariable=self.status_var, values=("All", "Unlocked", "Locked", "Unknown"), state="readonly", width=11)
        status_combo.pack(side=tk.LEFT, padx=(5, 12))
        status_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_inventory())

        self.warbond_var = tk.StringVar(value="All")
        self._warbond_ids: dict[str, str | None] = {"All": None}
        if category not in {"warbonds", "ship_modules", "weapon_attachments"}:
            for item in self.service.catalog["collections"]["warbonds"]:
                self._warbond_ids[item["name"]] = item["id"]
            ttk.Label(filters, text="Warbond:").pack(side=tk.LEFT)
            combo = ttk.Combobox(filters, textvariable=self.warbond_var, values=list(self._warbond_ids), state="readonly", width=22)
            combo.pack(side=tk.LEFT, padx=(5, 12))
            combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_inventory())

        self.group_var = tk.StringVar(value="All")
        groups = self._groups_for(category)
        self._group_ids = {"All": None, **{value.replace("_", " ").title(): value for value in groups}}
        if groups:
            ttk.Label(filters, text="Group:").pack(side=tk.LEFT)
            combo = ttk.Combobox(filters, textvariable=self.group_var, values=list(self._group_ids), state="readonly", width=18)
            combo.pack(side=tk.LEFT, padx=(5, 0))
            combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_inventory())

        table_frame = ttk.Frame(self.content)
        table_frame.pack(fill=tk.BOTH, expand=True)
        columns = ("state", "name", "detail", "source")
        self.inventory_tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        self.inventory_tree.heading("state", text="State")
        self.inventory_tree.heading("name", text="Name")
        self.inventory_tree.heading("detail", text="Details")
        self.inventory_tree.heading("source", text="Warbond / Source")
        self.inventory_tree.column("state", width=90, minwidth=80, stretch=False, anchor=tk.CENTER)
        self.inventory_tree.column("name", width=320, minwidth=190)
        self.inventory_tree.column("detail", width=260, minwidth=120)
        self.inventory_tree.column("source", width=200, minwidth=100)
        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.inventory_tree.yview)
        self.inventory_tree.configure(yscrollcommand=scrollbar.set)
        self.inventory_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.inventory_tree.tag_configure("unlocked", foreground="#16703b")
        self.inventory_tree.tag_configure("locked", foreground="#a12d2d")
        self.inventory_tree.tag_configure("unknown", foreground="#59636e")
        self.inventory_tree.bind("<Double-1>", self._toggle_selected)
        self.inventory_tree.bind("<space>", self._toggle_selected)
        self.inventory_tree.bind("<<TreeviewSelect>>", self._inventory_selection_changed)
        self.inventory_tree.bind("<Button-3>", self._inventory_context_menu)
        if sys.platform == "darwin":
            self.inventory_tree.bind("<Button-2>", self._inventory_context_menu)

        actions = ttk.Frame(self.content)
        actions.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(actions, text="Mark Remaining Visible as Locked", command=self._bulk_lock_unknown).pack(side=tk.LEFT)
        ttk.Button(actions, text="Mark Visible as Unknown", command=lambda: self._bulk_set("unknown", False)).pack(side=tk.LEFT, padx=5)
        ttk.Button(actions, text="Mark Visible as Unlocked", command=lambda: self._bulk_set("unlocked", False)).pack(side=tk.LEFT)
        ttk.Button(actions, text="Reload from Disk", command=self._reload).pack(side=tk.RIGHT)
        self.count_var = tk.StringVar()
        ttk.Label(actions, textvariable=self.count_var, style="Muted.TLabel").pack(side=tk.RIGHT, padx=12)

        self.detail_frame = ttk.LabelFrame(self.content, text="Selected item", padding=8)
        self.detail_frame.pack(fill=tk.X, pady=(8, 0))
        self.detail_label = ttk.Label(self.detail_frame, text="Select an item for details.", style="Muted.TLabel")
        self.detail_label.pack(side=tk.LEFT)
        self._refresh_inventory()

    def _groups_for(self, category: str) -> list[str]:
        values: set[str] = set()
        for row in self.service.inventory_rows(category):
            if row.group:
                values.add(row.group)
        return sorted(values, key=str.casefold)

    def _schedule_filter(self) -> None:
        if self._filter_job:
            self.root.after_cancel(self._filter_job)
        self._filter_job = self.root.after(100, self._refresh_inventory)

    def _refresh_inventory(self) -> None:
        if not hasattr(self, "inventory_tree") or not self.inventory_tree.winfo_exists():
            return
        status = self.status_var.get().casefold()
        group = self._group_ids.get(self.group_var.get())
        warbond = self._warbond_ids.get(self.warbond_var.get())
        self.visible_rows = self.service.inventory_rows(
            self.current_category, search=self.search_var.get(), status=status,
            warbond_id=warbond, group=group,
        )
        self.inventory_tree.delete(*self.inventory_tree.get_children())
        warbond_names = {item["id"]: item["name"] for item in self.service.catalog["collections"]["warbonds"]}
        for row in self.visible_rows:
            state = f"{STATUS_SYMBOLS[row.status]} {STATUS_LABELS[row.status]}"
            detail = row.detail + (f" • Level {row.level}" if row.level is not None else "")
            self.inventory_tree.insert("", tk.END, iid=row.item_id, values=(state, row.name, detail, warbond_names.get(row.warbond_id, "")), tags=(row.status,))
        self.count_var.set(f"{len(self.visible_rows)} visible")
        for child in self.detail_frame.winfo_children():
            child.destroy()
        self.detail_label = ttk.Label(self.detail_frame, text="Select an item for details.", style="Muted.TLabel")
        self.detail_label.pack(side=tk.LEFT)
        if self.current_category == "warbonds":
            self._show_warbond_helper()

    def _show_warbond_helper(self) -> None:
        count = len(self.service.locked_warbond_unknown_items())
        if count:
            self.detail_label.configure(text=f"{count} unknown catalog items belong to Warbonds marked locked.")
            ttk.Button(self.detail_frame, text="Mark These Items Locked", command=self._lock_warbond_items).pack(side=tk.RIGHT)

    def _selected_ids(self) -> list[str]:
        return list(self.inventory_tree.selection())

    def _toggle_selected(self, _event: tk.Event[Any] | None = None) -> str:
        selected = self._selected_ids()
        if not selected:
            return "break"
        try:
            for item_id in selected:
                current = self.service.inventory_status(self.current_category, item_id)
                self.service.set_inventory_status(self.current_category, item_id, "unknown" if current == "unlocked" else "unlocked")
            self._saved()
            self._refresh_inventory()
        except (ProfileError, ValueError, OSError) as exc:
            self._save_failed(exc)
        return "break"

    def _inventory_context_menu(self, event: tk.Event[Any]) -> None:
        row = self.inventory_tree.identify_row(event.y)
        if row and row not in self.inventory_tree.selection():
            self.inventory_tree.selection_set(row)
        menu = tk.Menu(self.root, tearoff=False)
        for status in ("unlocked", "locked", "unknown"):
            menu.add_command(label=f"Set {STATUS_LABELS[status]}", command=lambda value=status: self._set_selected(value))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _set_selected(self, status: str) -> None:
        try:
            self.service.bulk_set_status(self.current_category, self._selected_ids(), status)
            self._saved()
            self._refresh_inventory()
        except (ProfileError, ValueError, OSError) as exc:
            self._save_failed(exc)

    def _bulk_lock_unknown(self) -> None:
        self._bulk_set("locked", True)

    def _bulk_set(self, status: str, only_unknown: bool) -> None:
        ids = [row.item_id for row in self.visible_rows if not only_unknown or row.status == "unknown"]
        if not ids:
            messagebox.showinfo("No changes", "No matching visible items need this change.", parent=self.root)
            return
        description = "currently visible unknown" if only_unknown else "currently visible"
        if len(ids) >= 10 and not messagebox.askokcancel(
            "Confirm bulk change", f"Mark {len(ids)} {description} items as {status}?", parent=self.root,
        ):
            return
        try:
            changed = self.service.bulk_set_status(self.current_category, ids, status, only_unknown=only_unknown)
            self._saved(f"Saved {changed} item changes")
            self._refresh_inventory()
        except (ProfileError, ValueError, OSError) as exc:
            self._save_failed(exc)

    def _inventory_selection_changed(self, _event: tk.Event[Any] | None = None) -> None:
        selected = self._selected_ids()
        if not selected:
            return
        row = next((row for row in self.visible_rows if row.item_id == selected[0]), None)
        if row is None:
            return
        for child in self.detail_frame.winfo_children():
            child.destroy()
        ttk.Label(self.detail_frame, text=f"{row.name} — {STATUS_LABELS[row.status]}").pack(side=tk.LEFT)
        if self.current_category in {"primary_weapons", "secondary_weapons", "support_weapons"}:
            ttk.Button(self.detail_frame, text="Compatible Mods…", command=lambda: self._weapon_mods(row)).pack(side=tk.RIGHT)
            ttk.Button(self.detail_frame, text="Set Level…", command=lambda: self._weapon_level(row)).pack(side=tk.RIGHT, padx=5)
            ttk.Label(self.detail_frame, text=f"Level: {row.level if row.level is not None else 'unknown'}", style="Muted.TLabel").pack(side=tk.RIGHT, padx=8)

    def _weapon_level(self, row: InventoryRow) -> None:
        value = simpledialog.askstring("Weapon level", f"Level for {row.name} (blank = unknown):", initialvalue="" if row.level is None else str(row.level), parent=self.root)
        if value is None:
            return
        try:
            level = None if not value.strip() else int(value)
            self.service.set_weapon_level(self.current_category, row.item_id, level)
            self._saved()
            self._refresh_inventory()
        except (ValueError, ProfileError, OSError) as exc:
            self._save_failed(exc)

    def _weapon_mods(self, weapon: InventoryRow) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Weapon Mods — {weapon.name}")
        dialog.geometry("650x480")
        ttk.Label(dialog, text=weapon.name, style="Title.TLabel").pack(anchor=tk.W, padx=14, pady=(14, 2))
        ttk.Label(dialog, text="Compatible attachments; unlock state is global, not per-weapon progression.", style="Muted.TLabel").pack(anchor=tk.W, padx=14, pady=(0, 8))
        tree = ttk.Treeview(dialog, columns=("state", "name", "slot"), show="headings")
        for key, title, width in (("state", "State", 100), ("name", "Attachment", 330), ("slot", "Slot", 160)):
            tree.heading(key, text=title); tree.column(key, width=width)
        rows = self.service.inventory_rows("weapon_attachments", compatible_weapon_id=weapon.item_id)
        for row in rows:
            tree.insert("", tk.END, iid=row.item_id, values=(f"{STATUS_SYMBOLS[row.status]} {STATUS_LABELS[row.status]}", row.name, row.group or "Unknown"))
        tree.pack(fill=tk.BOTH, expand=True, padx=14, pady=8)

        def set_status(status: str) -> None:
            if not tree.selection():
                return
            try:
                self.service.bulk_set_status("weapon_attachments", tree.selection(), status)
                for item_id in tree.selection():
                    row = next(value for value in rows if value.item_id == item_id)
                    tree.set(item_id, "state", f"{STATUS_SYMBOLS[status]} {STATUS_LABELS[status]}")
                    rows[rows.index(row)] = InventoryRow(**{**row.__dict__, "status": status})
                self._saved()
            except (ProfileError, ValueError, OSError) as exc:
                self._save_failed(exc)

        buttons = ttk.Frame(dialog)
        buttons.pack(fill=tk.X, padx=14, pady=(0, 14))
        for status in ("unlocked", "locked", "unknown"):
            ttk.Button(buttons, text=f"Set {STATUS_LABELS[status]}", command=lambda value=status: set_status(value)).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(buttons, text="Close", command=dialog.destroy).pack(side=tk.RIGHT)
        dialog.bind("<Escape>", lambda _event: dialog.destroy())

    def _lock_warbond_items(self) -> None:
        count = len(self.service.locked_warbond_unknown_items())
        if not messagebox.askokcancel("Confirm Warbond helper", f"Mark {count} unknown items linked to locked Warbonds as locked?", parent=self.root):
            return
        try:
            changed = self.service.lock_items_from_locked_warbonds()
            self._saved(f"Saved {changed} item changes")
            self._refresh_inventory()
        except (ProfileError, OSError) as exc:
            self._save_failed(exc)

    def show_preferences(self) -> None:
        self._clear_content()
        ttk.Label(self.content, text="Preferences", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(self.content, text="Preferences are optional and independent from unlock state. Item choices below are character overrides.", style="Muted.TLabel").pack(anchor=tk.W, pady=(2, 8))
        general = ttk.LabelFrame(self.content, text="General character preferences", padding=8)
        general.pack(fill=tk.X)
        prefs = self.service.character().setdefault("preference_overrides", {}).setdefault("general", {})
        ttk.Label(general, text=json.dumps(prefs, ensure_ascii=False) if prefs else "None recorded").pack(side=tk.LEFT)

        def add_general() -> None:
            result = self._form_dialog("General Preference", [("Preference name", ""), ("Value", "")])
            if result:
                try:
                    self.service.set_general_preference(result[0], result[1]); self._saved(); self.show_preferences()
                except (ProfileError, OSError) as exc:
                    self._save_failed(exc)

        ttk.Button(general, text="Add / Edit…", command=add_general).pack(side=tk.RIGHT)
        item_frame = ttk.LabelFrame(self.content, text="Item-specific preferences", padding=8)
        item_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        search = tk.StringVar()
        ttk.Entry(item_frame, textvariable=search).pack(fill=tk.X, pady=(0, 6))
        tree = ttk.Treeview(item_frame, columns=("name", "preference"), show="headings")
        tree.heading("name", text="Item"); tree.heading("preference", text="Preference")
        tree.column("name", width=520); tree.column("preference", width=150)
        tree.pack(fill=tk.BOTH, expand=True)
        seen: dict[str, str] = {}
        for category in INVENTORY_TO_CATALOG:
            for row in self.service.inventory_rows(category):
                seen[row.item_id] = row.name

        def redraw(*_args: Any) -> None:
            tree.delete(*tree.get_children())
            query = search.get().casefold()
            overrides = self.service.character().get("preference_overrides", {}).get("item_preferences", {})
            base = (self.service.profile or {}).get("preferences", {}).get("item_preferences", {})
            for item_id, name in sorted(seen.items(), key=lambda pair: pair[1].casefold()):
                if query and query not in name.casefold():
                    continue
                value = overrides.get(item_id, base.get(item_id, "neutral"))
                tree.insert("", tk.END, iid=item_id, values=(name, value))

        search.trace_add("write", redraw)
        redraw()
        controls = ttk.Frame(item_frame)
        controls.pack(fill=tk.X, pady=(6, 0))
        preference = tk.StringVar(value="neutral")
        ttk.Combobox(controls, textvariable=preference, values=sorted(PREFERENCE_STATES), state="readonly").pack(side=tk.LEFT)

        def save_preference() -> None:
            if not tree.selection():
                return
            try:
                for item_id in tree.selection():
                    self.service.set_item_preference(item_id, preference.get())
                self._saved(); redraw()
            except (ProfileError, OSError) as exc:
                self._save_failed(exc)

        ttk.Button(controls, text="Apply to Selected", command=save_preference).pack(side=tk.LEFT, padx=5)

    def show_observations(self) -> None:
        self._clear_content()
        ttk.Label(self.content, text="Gameplay Observations", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(self.content, text="Capture experience without interpreting or scoring it.", style="Muted.TLabel").pack(anchor=tk.W, pady=(2, 10))
        form = ttk.Frame(self.content)
        form.pack(fill=tk.X)
        item_map = {"(General / loadout)": None}
        for item in sorted(self.service.index.values(), key=lambda value: value["name"].casefold()):
            item_map[f"{item['name']} [{item['id']}]"] = item["id"]
        variables = {
            "faction": tk.StringVar(), "difficulty": tk.StringVar(), "mission": tk.StringVar(),
            "item": tk.StringVar(value="(General / loadout)"), "rating": tk.StringVar(value="neutral"),
            "confidence": tk.StringVar(value="low"),
        }
        rows = [
            ("Faction", ttk.Combobox(form, textvariable=variables["faction"], values=("", "terminids", "automatons", "illuminate"))),
            ("Difficulty", ttk.Combobox(form, textvariable=variables["difficulty"], values=("", *map(str, range(1, 11))))),
            ("Mission (optional)", ttk.Entry(form, textvariable=variables["mission"])),
            ("Item / loadout", ttk.Combobox(form, textvariable=variables["item"], values=list(item_map))),
            ("Rating", ttk.Combobox(form, textvariable=variables["rating"], values=("great", "good", "neutral", "poor"), state="readonly")),
            ("Confidence", ttk.Combobox(form, textvariable=variables["confidence"], values=("low", "medium", "high"), state="readonly")),
        ]
        for number, (label, widget) in enumerate(rows):
            ttk.Label(form, text=label).grid(row=number, column=0, sticky=tk.W, pady=5)
            widget.grid(row=number, column=1, sticky=tk.EW, padx=(10, 0), pady=5)
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="Notes").grid(row=len(rows), column=0, sticky=tk.NW, pady=5)
        notes = tk.Text(form, height=7, wrap=tk.WORD)
        notes.grid(row=len(rows), column=1, sticky=tk.EW, padx=(10, 0), pady=5)

        def save_observation() -> None:
            try:
                difficulty = int(variables["difficulty"].get()) if variables["difficulty"].get() else None
                self.service.add_observation(
                    item_id=item_map.get(variables["item"].get()), faction=variables["faction"].get() or None,
                    difficulty=difficulty, mission_type=variables["mission"].get() or None,
                    rating=variables["rating"].get(), confidence=variables["confidence"].get(),
                    notes=notes.get("1.0", tk.END),
                )
                notes.delete("1.0", tk.END); self._saved("Observation saved")
                messagebox.showinfo("Observation saved", "The gameplay observation was saved to the canonical profile.", parent=self.root)
            except (ValueError, ProfileError, OSError) as exc:
                self._save_failed(exc)

        ttk.Button(self.content, text="Save Observation", command=save_observation).pack(anchor=tk.E, pady=10)

    def show_loadouts(self) -> None:
        self._clear_content()
        ttk.Label(self.content, text="Saved Loadouts", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(self.content, text="Loadouts are validated against the currently selected character.", style="Muted.TLabel").pack(anchor=tk.W, pady=(2, 8))
        tree = ttk.Treeview(self.content, columns=("name", "result", "unavailable"), show="headings")
        tree.heading("name", text="Loadout"); tree.heading("result", text="Validation"); tree.heading("unavailable", text="Unavailable / Unknown")
        tree.column("name", width=280); tree.column("result", width=160); tree.column("unavailable", width=420)
        entries = self.service.saved_loadouts()
        for number, entry in enumerate(entries):
            result = self.service.validate_loadout(entry)
            if result["errors"]:
                status = "Invalid"
                detail = "; ".join(result["errors"])
            else:
                status = f"{len(result['usable'])}/{result['total']} usable"
                detail = ", ".join(item["name"] for item in [*result["missing"], *result["unknown"]]) or "None"
            tree.insert("", tk.END, iid=str(number), values=(entry["loadout"].get("name", "Unnamed"), status, detail))
        tree.pack(fill=tk.BOTH, expand=True)
        detail = tk.Text(self.content, height=9, wrap=tk.WORD, state=tk.DISABLED)
        detail.pack(fill=tk.X, pady=(8, 0))

        def show_detail(_event: tk.Event[Any] | None = None) -> None:
            if not tree.selection():
                return
            entry = entries[int(tree.selection()[0])]
            result = self.service.validate_loadout(entry)
            text = json.dumps({"loadout": entry["loadout"], "validation": result}, indent=2, ensure_ascii=False)
            detail.configure(state=tk.NORMAL); detail.delete("1.0", tk.END); detail.insert("1.0", text); detail.configure(state=tk.DISABLED)

        tree.bind("<<TreeviewSelect>>", show_detail)
        controls = ttk.Frame(self.content)
        controls.pack(fill=tk.X, pady=8)

        def delete_selected() -> None:
            if not tree.selection():
                return
            entry = entries[int(tree.selection()[0])]
            name = entry["loadout"].get("name", "Unnamed")
            if not messagebox.askyesno("Delete saved loadout", f"Remove {name!r} from this profile?\n\nLinked files are not deleted from disk.", parent=self.root):
                return
            try:
                self.service.delete_loadout(entry["source"], entry["key"]); self._saved(); self.show_loadouts()
            except (ProfileError, OSError, ValueError) as exc:
                self._save_failed(exc)

        ttk.Button(controls, text="Delete…", command=delete_selected).pack(side=tk.RIGHT)

    def generate_context(self) -> None:
        try:
            json_path, markdown_path = self.service.generate_context()
        except (ProfileError, ValueError, OSError) as exc:
            messagebox.showerror("Context generation failed", str(exc), parent=self.root)
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Context Generated")
        dialog.transient(self.root)
        ttk.Label(dialog, text="Context generated successfully.", style="Heading.TLabel").pack(anchor=tk.W, padx=16, pady=(16, 8))
        profile = self.service.profile or {}
        details = (
            f"Player: {profile.get('player', {}).get('display_name', '')}\n"
            f"Character: {self.service.character_label()}\n"
            f"Catalog: {self.service.catalog['manifest'].get('catalog_version')}\n\n"
            f"Markdown:\n{markdown_path}\n\nJSON:\n{json_path}"
        )
        ttk.Label(dialog, text=details, justify=tk.LEFT, wraplength=650).pack(anchor=tk.W, padx=16)
        buttons = ttk.Frame(dialog)
        buttons.pack(fill=tk.X, padx=16, pady=16)
        ttk.Button(buttons, text="Open Markdown", command=lambda: self._open_safely(markdown_path)).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Open Folder", command=lambda: self._open_safely(markdown_path.parent)).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons, text="Copy File Path", command=lambda: self._copy_path(markdown_path)).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Close", command=dialog.destroy).pack(side=tk.RIGHT)

    def check_updates(self) -> None:
        self.save_status.set("Checking for updates…")

        def work() -> None:
            result = self.service.check_updates()
            self.root.after(0, lambda: self._show_update_result(result))

        threading.Thread(target=work, daemon=True).start()

    def _show_update_result(self, result: Any) -> None:
        self.save_status.set("Ready")
        if result.error:
            messagebox.showinfo("Update Check", f"Unable to check for updates.\n\n{result.error}\n\nHD2 Planner remains fully usable offline.", parent=self.root)
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Check for Updates")
        message = f"HD2 Planner\n\nInstalled: {result.installed}\nLatest:    {result.latest}\n\n"
        message += "An update is available." if result.available else "You are up to date."
        ttk.Label(dialog, text=message, justify=tk.LEFT).pack(anchor=tk.W, padx=18, pady=18)
        buttons = ttk.Frame(dialog); buttons.pack(fill=tk.X, padx=18, pady=(0, 18))
        if result.url:
            ttk.Button(buttons, text="Open Release Page", command=lambda: webbrowser.open(result.url)).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Close", command=dialog.destroy).pack(side=tk.RIGHT)

    def show_settings(self) -> None:
        self._clear_content()
        ttk.Label(self.content, text="Settings", style="Title.TLabel").pack(anchor=tk.W)
        profile = self.service.profile or {}
        info = (
            f"App version: {application_version()}\n"
            f"Catalog version: {self.service.catalog['manifest'].get('catalog_version', 'unknown')}\n"
            f"Profile schema: {PROFILE_SCHEMA_VERSION}\n"
            f"Current player: {profile.get('player', {}).get('display_name', 'None')}\n"
            f"User-data directory: {self.service.paths.root}\n"
            f"Environment override: {os.environ.get('HD2_PLANNER_DATA_DIR', 'not set')}\n"
            f"Update source: https://github.com/{repository()}"
        )
        ttk.Label(self.content, text=info, justify=tk.LEFT, wraplength=850).pack(anchor=tk.W, pady=10)
        actions = ttk.Frame(self.content); actions.pack(anchor=tk.W)
        ttk.Button(actions, text="Open User-Data Directory", command=lambda: self._open_safely(self.service.paths.root)).pack(side=tk.LEFT)
        ttk.Button(actions, text="Copy Path", command=lambda: self._copy_path(self.service.paths.root)).pack(side=tk.LEFT, padx=5)
        profiles = self.service.profiles()
        if len(profiles) > 1:
            switch = ttk.LabelFrame(self.content, text="Switch player", padding=8)
            switch.pack(fill=tk.X, pady=15)
            player_names = {f"{value.display_name} [{value.player_id}]": value.player_id for value in profiles}
            selected = tk.StringVar(value=next((label for label, value in player_names.items() if value == profile.get("player", {}).get("id")), ""))
            combo = ttk.Combobox(switch, textvariable=selected, values=list(player_names), state="readonly")
            combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

            def change_player() -> None:
                try:
                    self.service.open_profile(player_names[selected.get()]); self._profile_opened(); self.show_inventory("warbonds")
                except (ProfileError, OSError, ValueError) as exc:
                    messagebox.showerror("Could not open profile", str(exc), parent=self.root)

            ttk.Button(switch, text="Switch", command=change_player).pack(side=tk.LEFT, padx=(5, 0))

    def _reload(self) -> None:
        try:
            self.service.reload(); self._profile_opened(); self._refresh_inventory(); self.save_status.set("Reloaded from disk")
        except (ProfileError, OSError, ValueError) as exc:
            self._save_failed(exc)

    def _saved(self, message: str = "Saved") -> None:
        self.save_status.set(message)
        self.root.after(2500, lambda: self.save_status.set("Ready") if self.save_status.get() == message else None)

    def _save_failed(self, exc: BaseException) -> None:
        self.save_status.set("Save failed")
        messagebox.showerror("Could not save change", f"Your change was not written.\n\n{exc}", parent=self.root)

    def _focus_search(self) -> None:
        if hasattr(self, "search_entry") and self.search_entry.winfo_exists():
            self.search_entry.focus_set(); self.search_entry.selection_range(0, tk.END)

    def _copy_path(self, path: Path) -> None:
        self.root.clipboard_clear(); self.root.clipboard_append(str(path)); self.save_status.set("Path copied")

    def _open_safely(self, path: Path) -> None:
        try:
            open_path(path)
        except OSError as exc:
            messagebox.showerror("Could not open path", f"{path}\n\n{exc}", parent=self.root)


def launch_gui(service: PlannerService | None = None) -> int:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise RuntimeError(f"Could not start the desktop interface: {exc}") from exc
    HD2PlannerApp(root, service)
    root.mainloop()
    return 0
