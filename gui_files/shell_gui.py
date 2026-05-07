"""
shell_gui.py — Guichi Shell GUI
Tkinter-based GUI surface for the shell backend.
Reads registry on startup, displays packs/pages in a sidebar,
shows info panels in the content area.

Dev mode adds a persistent dev-loaded layer for manual .py file loading.
Dev-loaded items are stored in dev_loaded.json, separate from the registry.

Milestone: shell_sidepanel_control
  - Custom shell toolbar (collapsible, tied to left sidebar width)
  - Left sidebar (collapsible, default: navigation_sidebar)
  - Right sidebar (collapsible, default: jsondisplayer placeholder)
  - Layout state persistence
  - Same-sidepage duplication prevention
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import os
import sys
import json
import inspect
import traceback
import importlib.util
from datetime import datetime, timezone

# Ensure we can import sibling modules and guichi.py
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SHELL_DIR = os.path.dirname(_THIS_DIR)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
if _SHELL_DIR not in sys.path:
    sys.path.insert(0, _SHELL_DIR)

import guichi
import shell_registry
import sidewindow_registry
import shell_loader
import shell_theme
import interaction_support


# ── Sidebar ID separator and builders ───────────────────────
# Sidebar treeview item IDs encode type + identity fields.
# Uses null byte separator (cannot appear in filesystem paths
# or normal IDs). If this assumption is ever violated, the
# _make_sidebar_*_id and _parse_sidebar_id functions are the
# only places to fix.

_ID_SEP = "\x00"

# Fixed ID for the DEV LOADED section header node
_DEV_SECTION_ID = "_dev_section"


def _make_sidebar_pack_id(pack_id, source_path):
    """Build a sidebar treeview item ID for a pack."""
    return f"{pack_id}{_ID_SEP}{source_path}"


def _make_sidebar_page_id(pack_id, source_path, page_id):
    """Build a sidebar treeview item ID for a page."""
    return f"{pack_id}{_ID_SEP}{source_path}{_ID_SEP}{page_id}"


def _make_sidebar_dev_item_id(file_path, class_name):
    """Build a sidebar treeview item ID for a dev-loaded item."""
    return f"_dev_item{_ID_SEP}{file_path}{_ID_SEP}{class_name}"


def _parse_sidebar_id(item_id):
    """
    Parse a sidebar treeview item ID.
    Returns:
        ("pack", pack_id, source_path)
        ("page", pack_id, source_path, page_id)
        ("dev_section",)
        ("dev_item", file_path, class_name)
        None on failure
    """
    # Dev section header
    if item_id == _DEV_SECTION_ID:
        return ("dev_section",)

    # Dev-loaded item: _dev_item\x00file_path\x00class_name
    if item_id.startswith("_dev_item" + _ID_SEP):
        rest = item_id[len("_dev_item" + _ID_SEP):]
        parts = rest.split(_ID_SEP, 1)
        if len(parts) == 2:
            return ("dev_item", parts[0], parts[1])
        return None

    # Normal pack/page
    parts = item_id.split(_ID_SEP)
    if len(parts) == 2:
        return ("pack", parts[0], parts[1])
    elif len(parts) == 3:
        return ("page", parts[0], parts[1], parts[2])
    return None


_PAGE_GUI_METHODS = shell_loader._PAGE_GUI_METHODS  # canonical list lives in shell_loader


def _find_menu_index(menu, label):
    """Return the index of the first menu entry whose label matches, or None."""
    try:
        end = menu.index("end")
    except Exception:
        return None
    for i in range(end + 1):
        try:
            if menu.entrycget(i, "label") == label:
                return i
        except Exception:
            pass
    return None


SHORTCUT_ACTIONS = [
    ("discover_packs", "Discover packs", "Run pack discovery."),
    ("discover_broad", "Discover broad scan", "Run the broader discovery scan."),
    ("rebuild_registry", "Rebuild registry", "Rebuild the current registry."),
    ("clear_registry", "Clear registry/navigation", "Clear saved registry state."),
    ("toggle_left_sidebar", "Toggle left sidebar", "Open or collapse the left sidebar."),
    ("toggle_right_sidebar", "Toggle right sidebar", "Open or collapse the right sidebar."),
    ("toggle_toolbar", "Toggle toolbar mode", "Expand or collapse the toolbar."),
    ("focus_navigation", "Focus navigation", "Move keyboard focus to the navigation tree."),
    ("refresh_navigation", "Refresh navigation", "Rebuild the visible sidebar tree."),
    ("show_discovery_report", "Show discovery report", "Open the discovery report."),
    ("show_problems_report", "Show problems report", "Open the problems report."),
]

INTERACTION_CONFIG_KEYS = {
    "wheel_scroll_enabled": "interaction_wheel_scroll_enabled",
    "ctrl_a_enabled": "interaction_ctrl_a_enabled",
    "ctrl_c_enabled": "interaction_ctrl_c_enabled",
    "escape_dismiss_enabled": "interaction_escape_dismiss_enabled",
}


# ── Dev-loaded items persistence ────────────────────────────

DEV_LOADED_PATH = os.path.join(guichi.STATE_DIR, "dev_loaded.json")


def _load_dev_items():
    """Load dev-loaded items from disk. Returns list of item dicts."""
    if not os.path.isfile(DEV_LOADED_PATH):
        return []
    try:
        with open(DEV_LOADED_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data["items"]
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_dev_items(items):
    """Save dev-loaded items to disk."""
    os.makedirs(os.path.dirname(DEV_LOADED_PATH), exist_ok=True)
    with open(DEV_LOADED_PATH, "w", encoding="utf-8") as f:
        json.dump({"items": items}, f, indent=2, ensure_ascii=False)


def _find_dev_item(items, file_path, class_name):
    """Find index of a dev item by file_path + class_name. Returns index or -1."""
    for i, item in enumerate(items):
        if item.get("file_path") == file_path and item.get("class_name") == class_name:
            return i
    return -1


# ── Class scanning ──────────────────────────────────────────

def _scan_classes_in_file(file_path):
    """
    Lightweight scan of a .py file for class definitions.
    Returns (class_names_list, error_string_or_none).
    Classes are filtered to those defined in the file itself
    (not imported from other modules).
    """
    module_name = f"_dev_scan_{os.path.splitext(os.path.basename(file_path))[0]}"
    parent_dir = os.path.dirname(os.path.abspath(file_path))

    path_added = False
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
        path_added = True

    try:
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None:
            return [], f"could not build import spec for: {file_path}"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        classes = []
        for name in sorted(dir(module)):
            obj = getattr(module, name, None)
            if isinstance(obj, type) and getattr(obj, "__module__", None) == module.__name__:
                classes.append(name)
        return classes, None

    except Exception:
        return [], traceback.format_exc()
    finally:
        if path_added:
            try:
                sys.path.remove(parent_dir)
            except ValueError:
                pass


# ── Color and style constants ───────────────────────────────

STATUS_COLORS = {
    "ok":          {"fg": "#d0d0d0", "bg": ""},
    "warning":     {"fg": "#e8a838", "bg": ""},
    "unavailable": {"fg": "#e05050", "bg": ""},
    "hidden":      {"fg": "#707070", "bg": ""},
    "error":       {"fg": "#e05050", "bg": ""},
    "failed":      {"fg": "#e05050", "bg": ""},
    "dev_loaded":  {"fg": "#40c0c0", "bg": ""},
    "dev_section": {"fg": "#40c0c0", "bg": ""},
    "not_loaded":  {"fg": "#808080", "bg": ""},
}

INFO_LABEL_FONT = ("TkDefaultFont", 10, "bold")
INFO_VALUE_FONT = ("TkFixedFont", 10)
INFO_WARN_FONT = ("TkDefaultFont", 9)

WINDOW_TITLE = "Guichi Shell"
WINDOW_TITLE_DEV = "Guichi Shell \u2014 Dev Mode"
WINDOW_MIN_W = 800
WINDOW_MIN_H = 500
WINDOW_DEFAULT_GEOMETRY = "1100x650"
FONT_SCALE_PRESETS = [
    ("Small", 0.9),
    ("Default", 1.0),
    ("Large", 1.15),
    ("Extra Large", 1.3),
]

# ── Layout constants (shell_sidepanel_control milestone) ────

SIDEBAR_OPEN_W = 240
LEFT_COLLAPSED_W = 28
RIGHT_SIDEBAR_OPEN_W = 250
RIGHT_COLLAPSED_W = 24
TOOLBAR_HEIGHT = 32
TOOLBAR_MIN_W = 68                    # two buttons + padding
_T = shell_theme.get_theme()
COLLAPSED_BAR_BG     = _T["panel_bg"]
COLLAPSED_BAR_BORDER = _T["border"]
COLLAPSED_TEXT_COLOR = _T["text_muted"]
TOOLBAR_BG           = _T["topbar_bg"]
TOOLBAR_FG           = _T["text_main"]
TOOLBAR_BTN_FG       = _T["text_active"]
SIDEBAR_HEADER_BG        = _T["sidebar_bg"]
SIDEBAR_HEADER_FG        = _T["text_muted"]
SIDEBAR_HOTBAR_ACTIVE_BG = _T.get("accent", "#4ea0ff")
BUTTON_BG            = _T["button_bg"]
BUTTON_HOVER_BG      = _T["button_hover"]
BUTTON_ACTIVE_FG     = _T["button_active"]
STATUS_BG            = _T["panel_bg"]
STATUS_FG            = _T["text_main"]
TREE_BG              = _T["panel_bg"]
TREE_FG              = _T["text_main"]
TREE_SELECTED_BG     = _T["accent"]
TREE_SELECTED_FG     = _T["text_on_accent"]
TREE_FOCUS_RING      = _T["focus_ring"]

PACK_HOME_DESCRIPTIONS = {
    "pagepack_chilos": "Linux operations and desktop control tools. This pack is oriented around terminal workflows, routing, web bookmarks, and machine-side utility work.",
    "pagepack_chigit": "Git workflow tools for day-to-day repo updates, sync, SSH checks, branch tracking, and work-session context.",
    "pagepack_chigui": "Guichi shell controls and UI workshop tools. This pack is where display, theme, and interaction systems get shaped.",
    "pagepack_chitsheet": "Current:\n[x] Shows files and notes from project workshop, history workshop, and logs.\n[x] Acts as an early viewer surface for planning references.\n\nFuture:\n[ ] Grow into a cheat sheet / phase planner / guide for build ideas.\n[ ] Add a living checklist that updates as planning features land.\n[ ] Add a Q and A page to help dial in future builds.",
    "pagepack_pychiain": "AI-facing workspace pages for prompts, notes, Claude terminals, and model interaction surfaces.",
    "pagepack_chireader": "Reading and speech-oriented tools focused on text-to-speech and reading workflows.",
    "chiflippin0": "Flipper Zero and adjacent device workflows, including transport, storage, RPC, devboard, and connectivity surfaces.",
}

PAGE_HOME_DESCRIPTIONS = {
    "page_terminal_session": "Embedded terminal workspace for Linux command logging, reusable command records, and system-side task execution.",
    "page_audio_router": "Route live audio streams between outputs and manage default sinks with desktop-focused controls.",
    "page_browserdock": "Bookmark launcher for saved web tools, browser choices, quick-launch entries, and site notes.",
    "page_repo_update": "Focused daily-driver page for status, staging, commit, pull, and push without hopping between git tools.",
    "page_syncdock": "Broader git cockpit for repo sync tasks, file changes, commit flow, and supporting controls.",
    "page_sshdock": "SSH-oriented helper page for key, connection, and access troubleshooting around git workflows.",
    "page_branchledger": "Branch tracking and branch-oriented workflow support for more deliberate repo management.",
    "page_worksession": "Work session tracking and supporting repo context for longer-form git activity.",
    "page_global_page_controls": "Shell-wide interaction settings for scrolling, copy/select behaviors, and other global page controls.",
    "page_theme_organizer": "Interactive theme editor and preview surface for building and refining Guichi themes.",
    "page_dependency_tracker": "Live dependency and relationship map for current pychi pages, helpers, and runtime exception lanes.",
    "page_project_plans_viewer": "User-side viewer for 03 project-plan notes with frontmatter, links, and phase/build-cycle hooks.",
    "page_build_history_viewer": "Bridge raw user logs, machine audit logs, and related project-plan notes for pychi build-history retrieval.",
    "page_prompt_workshop": "Prompt-building and prompt-structure workspace for AI interaction drafting.",
    "page_markdown_notes": "Markdown note editing and working-note capture inside the shell.",
    "page_chilaude_terminal": "Long-running Claude terminal workflow page with transcript-oriented interaction.",
    "page_claude_cli_wrap": "Legacy launcher-style Claude page that opens or wraps external Claude CLI use.",
    "page_claude_workstation": "Claude-first terminal workspace for interactive CLI sessions and transcript work.",
    "page_ollama_ui": "Local model interaction surface for Ollama-backed workflows.",
    "page_qwen_tts": "Text-to-speech page for Qwen-based reading or spoken-output workflows.",
}
APP_BG               = _T["app_bg"]


# ── Main window ─────────────────────────────────────────────

class GuichiShell:
    """Main GUI shell window."""

    def __init__(self, root):
        self.root = root
        self.root.minsize(WINDOW_MIN_W, WINDOW_MIN_H)
        self.root.geometry(WINDOW_DEFAULT_GEOMETRY)
        interaction_support.install_root_bindings(self.root)

        # Shell state
        self.config = guichi.load_config()
        self.registry = shell_registry.load_registry(guichi.REGISTRY_PATH)

        # Dev-loaded items (persistent)
        self._dev_items = _load_dev_items()

        # UI state
        self.show_hidden = tk.BooleanVar(value=False)
        self.show_hidden.trace_add("write", lambda *_: self.refresh_sidebar())

        self._dev_mode_var = tk.BooleanVar(value=self.config.get("dev_mode", False))
        self._dev_mode_var.trace_add("write", lambda *_: self._on_dev_mode_toggle())

        self._theme_var = tk.StringVar(value=self.config.get("current_theme", shell_theme.DEFAULT_THEME))
        self._font_scale_var = tk.DoubleVar(value=float(self.config.get("font_scale", 1.0)))
        self._page_theme_global_var = tk.StringVar(
            value=self.config.get("page_theme_global") or ""
        )
        self._left_open_var = tk.BooleanVar(value=False)
        self._right_open_var = tk.BooleanVar(value=False)
        self._toolbar_full_var = tk.BooleanVar(value=False)
        self._fullscreen_var = tk.BooleanVar(value=bool(self.config.get("fullscreen", False)))

        # Track what's selected for context actions
        self._selected_pack_id = None
        self._selected_source_path = None
        self._selected_page_id = None
        self._current_page_pack_id = None
        self._current_page_source_path = None
        self._current_page_id = None
        self._current_page_theme_name = ""
        self._current_page_theme_scope = "inherit"
        self._active_page_instance = None

        # ── Layout state (three booleans, one apply path) ───
        self.left_open = self.config.get("left_sidebar_open", True)
        self.right_open = self.config.get("right_sidebar_open", False)
        self.toolbar_full = self.config.get("toolbar_full", True)
        self.left_sidebar_width = int(self.config.get("left_sidebar_width", SIDEBAR_OPEN_W))
        self.right_sidebar_width = int(self.config.get("right_sidebar_width", RIGHT_SIDEBAR_OPEN_W))

        # Sidepage tracking for same-sidepage prevention
        self._left_sidepage = "navigation_sidebar"
        self._right_sidepage = "guide_panel"

        # Sidewindow module ref and dynamic header label
        self._right_sw_mod = None
        self._right_sw_label_var = tk.StringVar(value="guide_panel")
        self.sw_registry = sidewindow_registry.load_registry(guichi.SIDEWINDOW_REGISTRY_PATH)

        self._apply_font_scale()
        self._apply_interaction_settings()
        self._build_ui()
        self._sync_display_state_vars()
        self._apply_window_mode()
        self._update_title()
        self.refresh_sidebar()
        self._load_right_sidebar_content()
        self._rebuild_sidepack_hotbar()
        self._apply_layout()
        self.set_status("ready")

    # ── UI construction ─────────────────────────────────────

    def _build_ui(self):
        """Build all UI elements."""
        self.root.configure(bg=APP_BG)
        self._build_menu()
        self._build_status_bar()       # pack bottom first
        self._build_toolbar()           # custom shell toolbar, pack top
        self._build_panes()             # three-column layout fills rest

    def get_interaction_settings(self):
        return {
            "wheel_scroll_enabled": bool(self.config.get("interaction_wheel_scroll_enabled", True)),
            "ctrl_a_enabled": bool(self.config.get("interaction_ctrl_a_enabled", True)),
            "ctrl_c_enabled": bool(self.config.get("interaction_ctrl_c_enabled", True)),
            "escape_dismiss_enabled": bool(self.config.get("interaction_escape_dismiss_enabled", True)),
        }

    def _apply_interaction_settings(self):
        self.root._guichi_interaction_settings = self.get_interaction_settings()

    def set_interaction_setting(self, key, value):
        config_key = INTERACTION_CONFIG_KEYS.get(key)
        if not config_key:
            return False
        self.config[config_key] = bool(value)
        guichi.save_config(self.config)
        self._apply_interaction_settings()
        return True

    def _build_menu(self):
        """Build menu objects used by the themed toolbar clone.
        Native OS/Tk menubar is intentionally not attached."""
        menubar = tk.Menu(self.root)

        # Shell menu
        shell_menu = tk.Menu(menubar, tearoff=0)
        self._populate_shell_menu(shell_menu)

        # View menu
        view_menu = tk.Menu(menubar, tearoff=0)
        self._populate_view_menu(view_menu)

        # Display menu
        self._display_menu = tk.Menu(menubar, tearoff=0)
        self._populate_display_menu(self._display_menu)

        # Dev Mode menu
        self._dev_menu = tk.Menu(menubar, tearoff=0)
        self._populate_dev_menu(self._dev_menu)

        # Store indices for gated items
        self._update_dev_menu_state()

        # Tools menu
        tools_menu = tk.Menu(menubar, tearoff=0)
        self._populate_tools_menu(tools_menu)

    def _populate_shell_menu(self, menu):
        menu.add_command(label="Discover packs...", command=self._on_discover)
        menu.add_command(
            label="Discover (broad scan)...",
            command=lambda: self._on_discover(scan_style=2),
        )
        menu.add_command(label="Rebuild registry", command=self._on_rebuild)
        menu.add_command(
            label="Clear registry/navigation...",
            command=self._on_clear_registry,
        )
        menu.add_separator()
        menu.add_command(label="Discover sidewindows...", command=self._on_discover_sidewindows)
        menu.add_separator()
        menu.add_command(label="Quit", command=self.root.quit)

    def _populate_view_menu(self, menu):
        menu.add_checkbutton(
            label="Show hidden packs",
            variable=self.show_hidden,
        )

    def _populate_dev_menu(self, menu):
        menu.add_checkbutton(
            label="Enable Dev Mode",
            variable=self._dev_mode_var,
        )
        menu.add_separator()
        menu.add_command(
            label="Load Python Page File\u2026",
            command=self._on_dev_load_py,
        )
        menu.add_command(
            label="Keyboard Shortcut Editor\u2026",
            command=self._on_shortcut_editor,
        )
        menu.add_separator()
        menu.add_command(
            label="Reset dev mode",
            command=self._on_dev_reset,
        )

    def _populate_tools_menu(self, menu):
        menu.add_command(label="Discovery report", command=self._on_report)
        menu.add_command(label="Problems report", command=self._on_problems_report)

    def _update_dev_menu_state(self):
        """Enable or disable dev-only menu items based on dev mode toggle."""
        state = tk.NORMAL if self._dev_mode_var.get() else tk.DISABLED
        _DEV_TOGGLE_LABELS = (
            "Load Python Page File\u2026",
            "Keyboard Shortcut Editor\u2026",
            "Reset dev mode",
        )
        for menu in (self._dev_menu,
                     getattr(self, "_toolbar_dev_menu", None)):
            if menu is None:
                continue
            for label in _DEV_TOGGLE_LABELS:
                idx = _find_menu_index(menu, label)
                if idx is not None:
                    menu.entryconfigure(idx, state=state)

    def _on_shortcut_editor(self):
        """Open the dev-mode keyboard shortcut editor."""
        if not self._dev_mode_var.get():
            self.set_status("enable dev mode to edit shortcuts")
            return

        win = tk.Toplevel(self.root)
        win.title("Keyboard Shortcut Editor")
        win.transient(self.root)
        win.geometry("760x520")
        win.minsize(680, 420)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)

        intro = tk.Label(
            win,
            text=(
                "Edit shortcut strings for Guichi actions. These are saved now for later binding work.\n"
                "Use Tk-style sequences like <Control-r> or <F5> when you are ready."
            ),
            anchor="w",
            justify=tk.LEFT,
        )
        intro.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))

        outer = ttk.Frame(win, padding=(10, 0, 10, 10))
        outer.grid(row=1, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        canvas = tk.Canvas(outer, highlightthickness=0)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=(0, 0, 6, 0))
        inner.columnconfigure(1, weight=1)

        canvas.configure(yscrollcommand=scroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _sync_scrollregion(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _fit_inner(event):
            canvas.itemconfigure(win_id, width=event.width)

        inner.bind("<Configure>", _sync_scrollregion)
        canvas.bind("<Configure>", _fit_inner)

        ttk.Label(inner, text="Action", font=INFO_LABEL_FONT).grid(
            row=0, column=0, sticky="w", padx=(0, 12), pady=(0, 6)
        )
        ttk.Label(inner, text="Shortcut", font=INFO_LABEL_FONT).grid(
            row=0, column=1, sticky="w", pady=(0, 6)
        )

        current = self.config.get("shortcut_overrides", {}) or {}
        vars_by_action = {}

        row = 1
        for action_id, label, description in SHORTCUT_ACTIONS:
            ttk.Label(inner, text=label).grid(
                row=row, column=0, sticky="nw", padx=(0, 12), pady=(0, 2)
            )
            var = tk.StringVar(value=current.get(action_id, ""))
            vars_by_action[action_id] = var
            ttk.Entry(inner, textvariable=var).grid(
                row=row, column=1, sticky="ew", pady=(0, 2)
            )
            row += 1
            ttk.Label(inner, text=description, foreground=shell_theme.get_theme()["text_muted"]).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(0, 8)
            )
            row += 1

        btns = ttk.Frame(win, padding=(10, 0, 10, 10))
        btns.grid(row=2, column=0, sticky="ew")

        def _save_shortcuts():
            payload = {}
            for action_id, var in vars_by_action.items():
                value = var.get().strip()
                if value:
                    payload[action_id] = value
            self.config["shortcut_overrides"] = payload
            try:
                guichi.save_config(self.config)
                self.set_status("shortcut editor saved")
                win.destroy()
            except Exception as e:
                messagebox.showerror(
                    "Keyboard Shortcut Editor",
                    f"Save failed:\n{e}",
                    parent=win,
                )

        def _clear_shortcuts():
            for var in vars_by_action.values():
                var.set("")

        ttk.Button(btns, text="Save", command=_save_shortcuts).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ttk.Button(btns, text="Close", command=win.destroy).pack(side=tk.RIGHT)
        ttk.Button(btns, text="Clear All", command=_clear_shortcuts).pack(side=tk.LEFT)

    def _sync_display_state_vars(self):
        self._left_open_var.set(bool(self.left_open))
        self._right_open_var.set(bool(self.right_open))
        self._toolbar_full_var.set(bool(self.toolbar_full))

    def _apply_window_mode(self):
        try:
            self.root.attributes("-fullscreen", self._fullscreen_var.get())
        except Exception:
            pass

    def _apply_font_scale(self):
        try:
            self.root.tk.call("tk", "scaling", float(self._font_scale_var.get()))
        except Exception:
            pass

    def _set_font_scale(self, scale_value):
        self._font_scale_var.set(float(scale_value))
        self._apply_font_scale()
        self.config["font_scale"] = float(self._font_scale_var.get())
        try:
            guichi.save_config(self.config)
        except Exception:
            pass
        self.set_status(f"font scale set to {self._font_scale_var.get():.2f}")

    def _page_theme_key_for_pack(self, pack_id, source_path):
        return f"{pack_id}|{source_path}"

    def _page_theme_key_for_page(self, pack_id, source_path, page_id):
        return f"{pack_id}|{source_path}|{page_id}"

    def _resolve_page_theme(self, pack_id=None, source_path=None, page_id=None):
        page_overrides = self.config.get("page_theme_page_overrides", {}) or {}
        pack_overrides = self.config.get("page_theme_pack_overrides", {}) or {}

        if pack_id and source_path and page_id:
            page_key = self._page_theme_key_for_page(pack_id, source_path, page_id)
            page_theme = page_overrides.get(page_key)
            if page_theme:
                return page_theme, "page"

        if pack_id and source_path:
            pack_key = self._page_theme_key_for_pack(pack_id, source_path)
            pack_theme = pack_overrides.get(pack_key)
            if pack_theme:
                return pack_theme, "pack"

        global_theme = self.config.get("page_theme_global")
        if global_theme:
            return global_theme, "global"

        return self.config.get("current_theme", shell_theme.DEFAULT_THEME), "shell"

    def get_current_page_theme_context(self):
        theme_name, scope = self._resolve_page_theme(
            self._current_page_pack_id,
            self._current_page_source_path,
            self._current_page_id,
        )
        return {
            "theme_name": theme_name,
            "theme_scope": scope,
            "tokens": shell_theme.get_named_theme(theme_name),
            "pack_id": self._current_page_pack_id,
            "source_path": self._current_page_source_path,
            "page_id": self._current_page_id,
        }

    def _apply_page_theme_choice(self, scope, theme_name):
        theme_name = theme_name or None
        if scope == "global":
            self.config["page_theme_global"] = theme_name
            self._page_theme_global_var.set(theme_name or "")
            target_label = "all pages"
        elif scope == "pack":
            if not self._current_page_pack_id or not self._current_page_source_path:
                self.set_status("load a page first to set a pack page theme")
                return
            pack_overrides = self.config.setdefault("page_theme_pack_overrides", {})
            pack_key = self._page_theme_key_for_pack(
                self._current_page_pack_id,
                self._current_page_source_path,
            )
            if theme_name:
                pack_overrides[pack_key] = theme_name
            else:
                pack_overrides.pop(pack_key, None)
            target_label = f"pack {self._current_page_pack_id}"
        elif scope == "page":
            if not self._current_page_pack_id or not self._current_page_source_path or not self._current_page_id:
                self.set_status("load a page first to set a page theme")
                return
            page_overrides = self.config.setdefault("page_theme_page_overrides", {})
            page_key = self._page_theme_key_for_page(
                self._current_page_pack_id,
                self._current_page_source_path,
                self._current_page_id,
            )
            if theme_name:
                page_overrides[page_key] = theme_name
            else:
                page_overrides.pop(page_key, None)
            target_label = f"page {self._current_page_id}"
        else:
            self.set_status("unknown page theme scope")
            return

        try:
            guichi.save_config(self.config)
        except Exception as e:
            self.set_status(f"page theme save failed: {e}")
            return

        resolved_name, resolved_scope = self._resolve_page_theme(
            self._current_page_pack_id,
            self._current_page_source_path,
            self._current_page_id,
        )
        self._current_page_theme_name = resolved_name
        self._current_page_theme_scope = resolved_scope
        self._reapply_active_page_theme()
        self.set_status(
            f"page theme set: {target_label} -> {theme_name or 'inherit shell theme'}"
        )

    def _set_fullscreen(self, enabled):
        self._fullscreen_var.set(bool(enabled))
        self._apply_window_mode()
        self._save_layout_state()
        self.set_status(
            f"fullscreen {'enabled' if self._fullscreen_var.get() else 'disabled'}"
        )

    def _set_left_sidebar_width(self, width):
        self.left_sidebar_width = int(width)
        self._apply_layout()
        self.set_status(f"left sidebar width set to {self.left_sidebar_width}")

    def _set_right_sidebar_width(self, width):
        self.right_sidebar_width = int(width)
        self._apply_layout()
        self.set_status(f"right sidebar width set to {self.right_sidebar_width}")

    def _reset_display_defaults(self):
        self.left_open = True
        self.right_open = False
        self.toolbar_full = True
        self.left_sidebar_width = SIDEBAR_OPEN_W
        self.right_sidebar_width = RIGHT_SIDEBAR_OPEN_W
        self._font_scale_var.set(1.0)
        self._fullscreen_var.set(False)
        self.config["page_theme_global"] = None
        self.config["page_theme_pack_overrides"] = {}
        self.config["page_theme_page_overrides"] = {}
        self._page_theme_global_var.set("")
        self.root.geometry(WINDOW_DEFAULT_GEOMETRY)
        self._apply_font_scale()
        self._apply_window_mode()
        self._apply_layout()
        self.set_status("display defaults restored")

    # ── Custom shell toolbar ────────────────────────────────

    def _build_toolbar(self):
        """Build the custom shell toolbar frame (below OS menu bar, above content).
        Collapses leftward tied to left sidebar state."""
        # Outer wrapper — always full width, provides the toolbar row
        self._toolbar_wrapper = tk.Frame(self.root, bg=TOOLBAR_BG)
        self._toolbar_wrapper.pack(side=tk.TOP, fill=tk.X)

        # Toolbar frame — visual toolbar with border, variable width
        self._toolbar_frame = tk.Frame(
            self._toolbar_wrapper, bg=TOOLBAR_BG,
            relief=tk.GROOVE, bd=1,
            height=TOOLBAR_HEIGHT,
        )
        self._toolbar_frame.pack_propagate(False)

        # ── Full toolbar content (shown when toolbar_full=True) ──
        self._toolbar_full_content = tk.Frame(self._toolbar_frame, bg=TOOLBAR_BG)

        self._btn_left_toggle_full = tk.Button(
            self._toolbar_full_content, text="\u2630", width=3,
            command=self._toggle_left,
            relief=tk.FLAT, bg=TOOLBAR_BG, fg=TOOLBAR_BTN_FG,
            activebackground=BUTTON_HOVER_BG, activeforeground=BUTTON_ACTIVE_FG,
            font=("TkDefaultFont", 11),
        )
        self._btn_left_toggle_full.pack(side=tk.LEFT, padx=(4, 2), pady=2)

        self._toolbar_label = tk.Label(
            self._toolbar_full_content,
            text=WINDOW_TITLE, bg=TOOLBAR_BG, fg=TOOLBAR_FG,
            font=("TkDefaultFont", 9),
        )
        self._toolbar_label.pack(side=tk.LEFT, padx=8)

        self._toolbar_menu_row = tk.Frame(self._toolbar_full_content, bg=TOOLBAR_BG)
        self._toolbar_menu_row.pack(side=tk.LEFT, padx=(6, 0))
        self._toolbar_menu_buttons = []

        self._toolbar_shell_menu = tk.Menu(self._toolbar_menu_row, tearoff=0)
        self._populate_shell_menu(self._toolbar_shell_menu)
        self._toolbar_shell_btn = self._create_toolbar_menu_button(
            self._toolbar_menu_row, "Shell", self._toolbar_shell_menu
        )

        self._toolbar_view_menu = tk.Menu(self._toolbar_menu_row, tearoff=0)
        self._populate_view_menu(self._toolbar_view_menu)
        self._toolbar_view_btn = self._create_toolbar_menu_button(
            self._toolbar_menu_row, "View", self._toolbar_view_menu
        )

        self._toolbar_display_menu = tk.Menu(self._toolbar_menu_row, tearoff=0)
        self._populate_display_menu(self._toolbar_display_menu)
        self._toolbar_display_btn = self._create_toolbar_menu_button(
            self._toolbar_menu_row, "Display", self._toolbar_display_menu
        )

        self._toolbar_dev_menu = tk.Menu(self._toolbar_menu_row, tearoff=0)
        self._populate_dev_menu(self._toolbar_dev_menu)
        self._toolbar_dev_btn = self._create_toolbar_menu_button(
            self._toolbar_menu_row, "Dev Mode", self._toolbar_dev_menu
        )

        self._toolbar_tools_menu = tk.Menu(self._toolbar_menu_row, tearoff=0)
        self._populate_tools_menu(self._toolbar_tools_menu)
        self._toolbar_tools_btn = self._create_toolbar_menu_button(
            self._toolbar_menu_row, "Tools", self._toolbar_tools_menu
        )

        self._btn_toolbar_collapse = tk.Button(
            self._toolbar_full_content, text="\u00ab", width=3,
            command=self._collapse_toolbar,
            relief=tk.FLAT, bg=TOOLBAR_BG, fg=TOOLBAR_BTN_FG,
            activebackground=BUTTON_HOVER_BG, activeforeground=BUTTON_ACTIVE_FG,
            font=("TkDefaultFont", 11),
        )
        self._btn_toolbar_collapse.pack(side=tk.RIGHT, padx=(2, 4), pady=2)

        self._btn_right_toggle_full = tk.Button(
            self._toolbar_full_content, text="\u25eb", width=3,
            command=self._toggle_right,
            relief=tk.FLAT, bg=TOOLBAR_BG, fg=TOOLBAR_BTN_FG,
            activebackground=BUTTON_HOVER_BG, activeforeground=BUTTON_ACTIVE_FG,
            font=("TkDefaultFont", 11),
        )
        self._btn_right_toggle_full.pack(side=tk.RIGHT, padx=2, pady=2)

        # ── Collapsed toolbar content (shown when toolbar_full=False) ──
        self._toolbar_min_content = tk.Frame(self._toolbar_frame, bg=TOOLBAR_BG)

        self._btn_left_toggle_min = tk.Button(
            self._toolbar_min_content, text="\u2630", width=3,
            command=self._toggle_left,
            relief=tk.FLAT, bg=TOOLBAR_BG, fg=TOOLBAR_BTN_FG,
            activebackground=BUTTON_HOVER_BG, activeforeground=BUTTON_ACTIVE_FG,
            font=("TkDefaultFont", 11),
        )
        self._btn_left_toggle_min.pack(side=tk.LEFT, padx=(4, 2), pady=2)

        self._btn_toolbar_expand = tk.Button(
            self._toolbar_min_content, text="\u00bb", width=3,
            command=self._expand_toolbar,
            relief=tk.FLAT, bg=TOOLBAR_BG, fg=TOOLBAR_BTN_FG,
            activebackground=BUTTON_HOVER_BG, activeforeground=BUTTON_ACTIVE_FG,
            font=("TkDefaultFont", 11),
        )
        self._btn_toolbar_expand.pack(side=tk.LEFT, padx=2, pady=2)

    def _create_toolbar_menu_button(self, parent, label, menu):
        btn = tk.Button(
            parent,
            text=label,
            relief=tk.FLAT,
            bg=TOOLBAR_BG,
            fg=TOOLBAR_BTN_FG,
            activebackground=BUTTON_HOVER_BG,
            activeforeground=BUTTON_ACTIVE_FG,
            font=("TkDefaultFont", 9),
            padx=8,
            pady=2,
            command=lambda m=menu: self._show_toolbar_popup_menu(btn, m),
        )
        btn.pack(side=tk.LEFT, padx=(0, 2), pady=2)
        self._toolbar_menu_buttons.append(btn)
        return btn

    def _show_toolbar_popup_menu(self, button, menu):
        """Post a toolbar-cloned menu directly under its button."""
        try:
            if menu is self._toolbar_display_menu:
                self._populate_display_menu(menu)
            elif menu is self._toolbar_dev_menu:
                menu.delete(0, "end")
                self._populate_dev_menu(menu)
                self._update_dev_menu_state()
        except Exception:
            pass

        interaction_support.show_popup_menu(
            self.root,
            menu,
            button.winfo_rootx(),
            button.winfo_rooty() + button.winfo_height(),
        )

    # ── Three-column layout ─────────────────────────────────

    def _build_panes(self):
        """Build the left sidebar | content | right sidebar layout."""
        self._main_frame = tk.Frame(self.root, bg=APP_BG)
        self._main_frame.pack(fill=tk.BOTH, expand=True)

        # ── Left panel container ────────────────────────────
        self._left_panel = tk.Frame(self._main_frame, width=SIDEBAR_OPEN_W, bg=COLLAPSED_BAR_BG)
        self._left_panel.pack_propagate(False)
        self._left_panel.pack(side=tk.LEFT, fill=tk.Y)

        # Left open content: header + sidebar treeview
        self._left_content = tk.Frame(self._left_panel, bg=SIDEBAR_HEADER_BG)

        self._left_header_frame = tk.Frame(self._left_content, bg=SIDEBAR_HEADER_BG)
        self._left_header_frame.pack(fill=tk.X)
        self._left_header_label = tk.Label(
            self._left_header_frame, text="navigation_sidebar",
            font=("TkDefaultFont", 8), bg=SIDEBAR_HEADER_BG,
            fg=SIDEBAR_HEADER_FG, anchor=tk.W,
        )
        self._left_header_label.pack(side=tk.LEFT, padx=6, pady=3)

        self._left_sidebar_frame = tk.Frame(self._left_content, bg=SIDEBAR_HEADER_BG)
        sidebar_frame = self._left_sidebar_frame
        sidebar_frame.pack(fill=tk.BOTH, expand=True)
        sidebar_frame.columnconfigure(0, weight=1)
        sidebar_frame.rowconfigure(0, weight=1)

        _tree_style = ttk.Style()
        _tree_style.configure(
            "GuichiSidebar.Treeview",
            background=TREE_BG,
            fieldbackground=TREE_BG,
            foreground=TREE_FG,
            borderwidth=0,
            focuscolor=TREE_FOCUS_RING,
        )
        _tree_style.map(
            "GuichiSidebar.Treeview",
            background=[("selected", TREE_SELECTED_BG)],
            foreground=[("selected", TREE_SELECTED_FG)],
        )

        self.sidebar_tree = ttk.Treeview(
            sidebar_frame,
            show="tree",
            selectmode="extended",
            style="GuichiSidebar.Treeview",
        )
        interaction_support.setup_treeview_widget(self.sidebar_tree)
        sidebar_scroll = ttk.Scrollbar(
            sidebar_frame, orient=tk.VERTICAL,
            command=self.sidebar_tree.yview,
        )
        self.sidebar_tree.configure(yscrollcommand=sidebar_scroll.set)
        self.sidebar_tree.grid(row=0, column=0, sticky="nsew")
        sidebar_scroll.grid(row=0, column=1, sticky="ns")

        self.sidebar_tree.bind("<<TreeviewSelect>>", self._on_sidebar_select)

        # Right-click context menu
        self.sidebar_tree.bind("<Button-3>", self._on_sidebar_right_click)
        self.sidebar_tree.bind("<Button-2>", self._on_sidebar_right_click)

        # Configure tag colors for treeview items
        for status, colors in STATUS_COLORS.items():
            self.sidebar_tree.tag_configure(status, foreground=colors["fg"])

        # Left collapsed bar
        self._left_collapsed = self._create_collapsed_bar(
            self._left_panel, "navigation_sidebar",
            LEFT_COLLAPSED_W, 90, self._toggle_left,
        )

        # ── Right panel container ───────────────────────────
        # Pack right panel BEFORE content frame so side=RIGHT works correctly
        self._right_panel = tk.Frame(self._main_frame, width=RIGHT_COLLAPSED_W, bg=COLLAPSED_BAR_BG)
        self._right_panel.pack_propagate(False)
        self._right_panel.pack(side=tk.RIGHT, fill=tk.Y)

        # Right open content: header + sidewindow host area
        self._right_content = tk.Frame(self._right_panel, bg=SIDEBAR_HEADER_BG)

        self._right_header_frame = tk.Frame(self._right_content, bg=SIDEBAR_HEADER_BG)
        self._right_header_frame.pack(fill=tk.X)
        self._right_header_label = tk.Label(
            self._right_header_frame, textvariable=self._right_sw_label_var,
            font=("TkDefaultFont", 8), bg=SIDEBAR_HEADER_BG,
            fg=SIDEBAR_HEADER_FG, anchor=tk.W,
        )
        self._right_header_label.pack(side=tk.LEFT, padx=6, pady=3)
        self._sw_hotbar_frame = tk.Frame(self._right_header_frame, bg=SIDEBAR_HEADER_BG)
        self._sw_hotbar_frame.pack(side=tk.RIGHT)

        # Sidewindow host area (jsondisplayer content goes here)
        self._right_sw_area = tk.Frame(self._right_content, bg=SIDEBAR_HEADER_BG)
        self._right_sw_area.pack(fill=tk.BOTH, expand=True)

        # Right collapsed bar
        self._right_collapsed = self._create_collapsed_bar(
            self._right_panel, "jsondisplayer",
            RIGHT_COLLAPSED_W, 270, self._toggle_right,
        )

        # ── Content frame (center page area) ────────────────
        self.content_frame = tk.Frame(self._main_frame)
        self.content_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._show_welcome()

    def _create_collapsed_bar(self, parent, codename, bar_width, text_angle, on_click):
        """
        Create a collapsed sidebar bar with vertical text inside a padded border.
        Returns the bar frame (not yet packed — _apply_layout manages visibility).
        """
        bar = tk.Frame(parent, bg=COLLAPSED_BAR_BG)

        # Inner canvas with border look
        inner = tk.Frame(bar, bg=COLLAPSED_BAR_BORDER, padx=1, pady=1)
        inner.pack(fill=tk.BOTH, expand=True, padx=2, pady=4)

        canvas = tk.Canvas(
            inner, width=max(bar_width - 8, 12),
            bg=COLLAPSED_BAR_BG, highlightthickness=0,
            cursor="hand2",
        )
        canvas.pack(fill=tk.BOTH, expand=True)

        text_id = canvas.create_text(
            max(bar_width - 8, 12) // 2, 50,
            text=codename, angle=text_angle,
            fill=COLLAPSED_TEXT_COLOR,
            font=("TkDefaultFont", _T.get("font_size_small", 8), "bold"),
            anchor="center",
        )

        def _reposition(event):
            cx = event.width // 2
            cy = event.height // 2
            canvas.coords(text_id, cx, cy)

        canvas.bind("<Configure>", _reposition)
        canvas.bind("<Button-1>", lambda e: on_click())

        # Store for _reapply_shell_colors
        bar._guichi_inner = inner
        bar._guichi_canvas = canvas
        bar._guichi_text_id = text_id

        return bar

    # ── Layout state machine ────────────────────────────────

    def _apply_layout(self):
        """
        Single layout update path. Reads left_open, right_open, toolbar_full
        and configures all panels + toolbar accordingly.
        """
        # ── Left panel ──────────────────────────────────────
        self._left_content.pack_forget()
        self._left_collapsed.pack_forget()

        if self.left_open:
            self._left_panel.configure(width=self.left_sidebar_width)
            self._left_content.pack(fill=tk.BOTH, expand=True)
        else:
            self._left_panel.configure(width=LEFT_COLLAPSED_W)
            self._left_collapsed.pack(fill=tk.BOTH, expand=True)

        # ── Right panel ─────────────────────────────────────
        self._right_content.pack_forget()
        self._right_collapsed.pack_forget()

        if self.right_open:
            self._right_panel.configure(width=self.right_sidebar_width)
            self._right_content.pack(fill=tk.BOTH, expand=True)
        else:
            self._right_panel.configure(width=RIGHT_COLLAPSED_W)
            self._right_collapsed.pack(fill=tk.BOTH, expand=True)

        # ── Custom toolbar ──────────────────────────────────
        self._toolbar_full_content.pack_forget()
        self._toolbar_min_content.pack_forget()
        self._toolbar_frame.pack_forget()

        if self.toolbar_full:
            self._toolbar_frame.pack_propagate(True)
            self._toolbar_frame.pack(fill=tk.X, expand=True, padx=0, pady=0)
            self._toolbar_full_content.pack(fill=tk.BOTH, expand=True)
        else:
            # Collapsed: toolbar width matches left sidebar (or minimum two buttons)
            if self.left_open:
                toolbar_w = self.left_sidebar_width
            else:
                toolbar_w = TOOLBAR_MIN_W
            self._toolbar_frame.configure(width=toolbar_w, height=TOOLBAR_HEIGHT)
            self._toolbar_frame.pack_propagate(False)
            self._toolbar_frame.pack(side=tk.LEFT, padx=0, pady=0)
            self._toolbar_min_content.pack(fill=tk.BOTH, expand=True)

        # ── Update toolbar label for dev mode ───────────────
        if self._dev_mode_var.get():
            self._toolbar_label.configure(text=WINDOW_TITLE_DEV)
        else:
            self._toolbar_label.configure(text=WINDOW_TITLE)

        # ── Persist layout state ────────────────────────────
        self._sync_display_state_vars()
        self._save_layout_state()

    def _toggle_left(self):
        """Toggle left sidebar open/collapsed."""
        self.left_open = not self.left_open
        self._apply_layout()

    def _toggle_right(self):
        """Toggle right sidebar open/collapsed."""
        self.right_open = not self.right_open
        self._apply_layout()

    def _collapse_toolbar(self):
        """Collapse toolbar to left-aligned minimum."""
        self.toolbar_full = False
        self._apply_layout()

    def _expand_toolbar(self):
        """Expand toolbar to full width."""
        self.toolbar_full = True
        self._apply_layout()

    def _save_layout_state(self):
        """Persist layout visibility booleans to config. Non-fatal on failure."""
        self.config["left_sidebar_open"] = self.left_open
        self.config["right_sidebar_open"] = self.right_open
        self.config["toolbar_full"] = self.toolbar_full
        self.config["left_sidebar_width"] = int(self.left_sidebar_width)
        self.config["right_sidebar_width"] = int(self.right_sidebar_width)
        self.config["font_scale"] = float(self._font_scale_var.get())
        self.config["fullscreen"] = bool(self._fullscreen_var.get())
        try:
            guichi.save_config(self.config)
        except Exception:
            pass  # never crash on persistence failure

    # ── Same-sidepage duplication guard ─────────────────────

    def _can_assign_sidepage(self, codename, target_side):
        """
        Check whether a sidepage with the given codename can be assigned to
        target_side ("left" or "right") without duplicating across panels.
        Returns True if assignment is allowed, False if it would duplicate.
        """
        if target_side == "left":
            return self._right_sidepage != codename
        else:
            return self._left_sidepage != codename

    # ── Right sidebar sidewindow loading ────────────────────

    def _load_right_sidebar_content(self):
        """
        Startup loader. Checks registry for configured default sidepack.
        If none configured or not found, shows a prompt to discover sidepacks.
        """
        configured_id = self.config.get("right_sidewindow_id")
        if configured_id:
            sidewindows = self.sw_registry.get("sidewindows", [])
            for sw in sidewindows:
                if sw.get("sidewindow_id") == configured_id and sw.get("status") == "ok":
                    init_path = sw.get("init_path", "")
                    if os.path.isfile(init_path):
                        self._load_right_sidebar_from_path(init_path, configured_id)
                        return

        self._show_right_sidebar_error(
            "No sidepacks loaded.\n\nShell \u2192 Discover sidewindows...\nor click \u22ef above"
        )

    def _load_right_sidebar_from_path(self, init_path, codename):
        """Load a sidewindow from an absolute init_path into the right sidebar."""
        if not self._can_assign_sidepage(codename, "right"):
            self._show_right_sidebar_error(
                f"{codename} is already loaded in the left sidebar.\n"
                "Same sidepage cannot be open on both sides."
            )
            return

        try:
            if not os.path.isfile(init_path):
                self._show_right_sidebar_error(
                    f"{codename} not found:\n{init_path}"
                )
                return

            spec = importlib.util.spec_from_file_location(
                f"guichi_sw_{codename}", init_path,
            )
            if spec is None:
                self._show_right_sidebar_error(
                    f"could not build import spec for {codename}"
                )
                return

            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            build_fn = getattr(mod, "build", None)
            if build_fn is None:
                self._show_right_sidebar_error(
                    f"{codename} module has no build() function"
                )
                return

            try:
                sig = inspect.signature(build_fn)
                if "shell" in sig.parameters:
                    build_fn(self._right_sw_area, shell=self)
                else:
                    build_fn(self._right_sw_area)
            except TypeError:
                build_fn(self._right_sw_area)

            self._right_sw_mod = mod
            self._right_sidepage = getattr(mod, "CODENAME", codename)
            self._right_sw_label_var.set(self._right_sidepage)

        except Exception:
            tb = traceback.format_exc()
            self._show_right_sidebar_error(
                f"{codename} load failed:\n{tb}"
            )

    def _rebuild_sidepack_hotbar(self):
        """Destroy and recreate hotbar buttons from sw_registry ok entries."""
        for child in self._sw_hotbar_frame.winfo_children():
            child.destroy()
        for sw in self.sw_registry.get("sidewindows", []):
            if sw.get("status") != "ok":
                continue
            label = sw.get("short_label") or sw.get("sidewindow_id", "?")[:2]
            is_active = (sw.get("sidewindow_id") == self._right_sidepage)
            bg = SIDEBAR_HOTBAR_ACTIVE_BG if is_active else SIDEBAR_HEADER_BG
            btn = tk.Button(
                self._sw_hotbar_frame, text=label,
                bg=bg, fg=SIDEBAR_HEADER_FG,
                relief=tk.FLAT, font=("TkDefaultFont", 7),
                padx=3,
                command=lambda s=sw: self._load_right_sidewindow_entry(s),
            )
            btn.pack(side=tk.LEFT, padx=1)
        tk.Button(
            self._sw_hotbar_frame, text="\u22ef",
            bg=SIDEBAR_HEADER_BG, fg=SIDEBAR_HEADER_FG,
            relief=tk.FLAT, font=("TkDefaultFont", 9),
            command=self._on_discover_sidewindows,
        ).pack(side=tk.LEFT, padx=(2, 4))

    def _load_right_sidewindow_entry(self, sw_entry):
        """Clear right sidebar area and load a sidewindow from a registry entry."""
        for child in self._right_sw_area.winfo_children():
            child.destroy()
        self._right_sw_mod = None
        init_path = sw_entry.get("init_path", "")
        codename  = sw_entry.get("sidewindow_id", "unknown")
        self._load_right_sidebar_from_path(init_path, codename)
        self.config["right_sidewindow_id"] = codename
        guichi.save_config(self.config)
        self._rebuild_sidepack_hotbar()

    def _show_right_sidebar_error(self, message):
        """Show an error/info message in the right sidebar content area."""
        for child in self._right_sw_area.winfo_children():
            child.destroy()

        _t = shell_theme.get_theme()
        tk.Label(
            self._right_sw_area, text="sidewindow error",
            font=("TkDefaultFont", 9, "bold"), fg=_t["text_error"],
            anchor=tk.W,
        ).pack(fill=tk.X, padx=6, pady=(8, 2))

        tk.Label(
            self._right_sw_area, text=message,
            font=("TkFixedFont", 8), fg=_t["text_muted"],
            anchor=tk.NW, wraplength=220, justify=tk.LEFT,
        ).pack(fill=tk.BOTH, padx=6, pady=4, expand=True)

        self.set_status("right sidebar: sidewindow load failed")

    # ── Status bar ──────────────────────────────────────────

    def _build_status_bar(self):
        """Build the bottom status bar."""
        self.status_var = tk.StringVar(value="")
        self.status_bar = tk.Label(
            self.root, textvariable=self.status_var,
            anchor=tk.W, relief=tk.SUNKEN, padx=6, pady=2,
            bg=STATUS_BG, fg=STATUS_FG,
        )
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def _update_title(self):
        """Set window title based on dev mode state."""
        if self._dev_mode_var.get():
            self.root.title(WINDOW_TITLE_DEV)
        else:
            self.root.title(WINDOW_TITLE)

    # ── Dev mode toggle ─────────────────────────────────────

    def _on_dev_mode_toggle(self):
        """Handle dev mode enable/disable toggle."""
        enabled = self._dev_mode_var.get()
        self.config["dev_mode"] = enabled
        guichi.save_config(self.config)
        self._update_title()
        self._update_dev_menu_state()
        # Also update toolbar label
        self._apply_layout()
        state_label = "enabled" if enabled else "disabled"
        self.set_status(f"dev mode {state_label}")

    # ── Theme selector ───────────────────────────────────────

    def _reapply_shell_colors(self):
        """Reconfigure shell structural widget colors from the current theme."""
        _t = shell_theme.get_theme()

        # Root and main frame
        self.root.configure(bg=_t["app_bg"])
        self._main_frame.configure(bg=_t["app_bg"])

        # Toolbar frames
        for w in (self._toolbar_wrapper, self._toolbar_frame,
                  self._toolbar_full_content, self._toolbar_min_content,
                  self._toolbar_menu_row):
            w.configure(bg=_t["topbar_bg"])
        self._toolbar_label.configure(bg=_t["topbar_bg"], fg=_t["text_main"])

        # Toolbar buttons
        _btn_kw = dict(bg=_t["topbar_bg"], fg=_t["text_active"],
                       activebackground=_t["button_hover"],
                       activeforeground=_t["button_active"])
        for btn in (self._btn_left_toggle_full, self._btn_right_toggle_full,
                    self._btn_toolbar_collapse, self._btn_left_toggle_min,
                    self._btn_toolbar_expand):
            btn.configure(**_btn_kw)
        for btn in self._toolbar_menu_buttons:
            btn.configure(**_btn_kw)

        # Status bar
        self.status_bar.configure(bg=_t["panel_bg"], fg=_t["text_main"])

        # Left sidebar
        self._left_panel.configure(bg=_t["panel_bg"])
        self._left_content.configure(bg=_t["sidebar_bg"])
        self._left_header_frame.configure(bg=_t["sidebar_bg"])
        self._left_header_label.configure(bg=_t["sidebar_bg"], fg=_t["text_muted"])
        self._left_sidebar_frame.configure(bg=_t["sidebar_bg"])

        # Treeview style
        _style = ttk.Style()
        _style.configure(
            "GuichiSidebar.Treeview",
            background=_t["panel_bg"],
            fieldbackground=_t["panel_bg"],
            foreground=_t["text_main"],
            focuscolor=_t["focus_ring"],
        )
        _style.map(
            "GuichiSidebar.Treeview",
            background=[("selected", _t["accent"])],
            foreground=[("selected", _t["text_on_accent"])],
        )
        for status, colors in STATUS_COLORS.items():
            self.sidebar_tree.tag_configure(status, foreground=colors["fg"])

        # Right sidebar
        self._right_panel.configure(bg=_t["panel_bg"])
        self._right_content.configure(bg=_t["sidebar_bg"])
        self._right_header_frame.configure(bg=_t["sidebar_bg"])
        self._right_header_label.configure(bg=_t["sidebar_bg"], fg=_t["text_muted"])
        self._sw_hotbar_frame.configure(bg=_t["sidebar_bg"])
        self._right_sw_area.configure(bg=_t["sidebar_bg"])

        # Collapsed bars
        for bar in (self._left_collapsed, self._right_collapsed):
            bar.configure(bg=_t["panel_bg"])
            inner = getattr(bar, "_guichi_inner", None)
            canvas = getattr(bar, "_guichi_canvas", None)
            text_id = getattr(bar, "_guichi_text_id", None)
            if inner:
                inner.configure(bg=_t["border"])
            if canvas:
                canvas.configure(bg=_t["panel_bg"])
                if text_id:
                    canvas.itemconfigure(text_id, fill=_t["text_muted"])

    def _on_theme_select(self, selected_name):
        """Save selected theme to config and live-apply shell colors."""
        try:
            self.config["current_theme"] = selected_name
            guichi.save_config(self.config)
            shell_theme.invalidate_themes_cache()
            self._reapply_shell_colors()
            resolved_name, resolved_scope = self._resolve_page_theme(
                self._current_page_pack_id,
                self._current_page_source_path,
                self._current_page_id,
            )
            self._current_page_theme_name = resolved_name
            self._current_page_theme_scope = resolved_scope
            self._reapply_active_page_theme()
            self.set_status(f"Theme applied: {selected_name}")
        except Exception as e:
            self.set_status(f"Theme save failed: {e}")

    def _show_display_menu(self):
        """Build and pop up the Display dropdown on demand.
        Menu is constructed fresh each click so no persistent tk.Menu widget
        exists for KDE Appmenu to surface in the Tk menu layer."""
        menu = tk.Menu(self.root, tearoff=0)
        self._populate_display_menu(menu)

        # Hold reference until next click so the menu isn't GC'd mid-popup.
        self._active_display_menu = menu
        interaction_support.show_popup_menu(
            self.root,
            menu,
            self.root.winfo_rootx() + 24,
            self.root.winfo_rooty() + 24,
        )

    def _populate_display_menu(self, menu):
        menu.delete(0, "end")

        menu.add_checkbutton(
            label="Left Sidebar",
            variable=self._left_open_var,
            command=self._toggle_left,
        )
        menu.add_checkbutton(
            label="Right Sidebar",
            variable=self._right_open_var,
            command=self._toggle_right,
        )
        menu.add_checkbutton(
            label="Expanded Toolbar",
            variable=self._toolbar_full_var,
            command=lambda: self._expand_toolbar() if not self.toolbar_full else self._collapse_toolbar(),
        )
        menu.add_checkbutton(
            label="Fullscreen",
            variable=self._fullscreen_var,
            command=lambda: self._set_fullscreen(self._fullscreen_var.get()),
        )
        menu.add_separator()

        theme_sub = tk.Menu(menu, tearoff=0)
        for _name in shell_theme.list_themes():
            theme_sub.add_radiobutton(
                label=_name,
                variable=self._theme_var,
                value=_name,
                command=lambda n=_name: self._on_theme_select(n),
            )
        menu.add_cascade(label="Theme", menu=theme_sub)

        font_sub = tk.Menu(menu, tearoff=0)
        for _label, _scale in FONT_SCALE_PRESETS:
            font_sub.add_radiobutton(
                label=_label,
                variable=self._font_scale_var,
                value=float(_scale),
                command=lambda s=_scale: self._set_font_scale(s),
            )
        menu.add_cascade(label="Font Size", menu=font_sub)

        page_theme_sub = tk.Menu(menu, tearoff=0)
        self._populate_page_theme_scope_menu(page_theme_sub, "page", "This Page")
        self._populate_page_theme_scope_menu(page_theme_sub, "pack", "This Pack")
        self._populate_page_theme_scope_menu(page_theme_sub, "global", "All Pages")
        menu.add_cascade(label="Page Theme", menu=page_theme_sub)

        left_width_sub = tk.Menu(menu, tearoff=0)
        for _label, _width in [
            ("Narrow", 200),
            ("Default", SIDEBAR_OPEN_W),
            ("Wide", 320),
        ]:
            left_width_sub.add_command(
                label=_label,
                command=lambda w=_width: self._set_left_sidebar_width(w),
            )
        menu.add_cascade(label="Left Sidebar Width", menu=left_width_sub)

        right_width_sub = tk.Menu(menu, tearoff=0)
        for _label, _width in [
            ("Narrow", 210),
            ("Default", RIGHT_SIDEBAR_OPEN_W),
            ("Wide", 340),
        ]:
            right_width_sub.add_command(
                label=_label,
                command=lambda w=_width: self._set_right_sidebar_width(w),
            )
        menu.add_cascade(label="Right Sidebar Width", menu=right_width_sub)

        size_sub = tk.Menu(menu, tearoff=0)
        for _label, _geo in [
            ("800 \u00d7 500  (minimum)",        "800x500"),
            ("1100 \u00d7 650  (default)",        WINDOW_DEFAULT_GEOMETRY),
            ("1280 \u00d7 720",                   "1280x720"),
            ("1600 \u00d7 900",                   "1600x900"),
            ("1920 \u00d7 1080  (FHD)",           "1920x1080"),
            ("2560 \u00d7 1080  (workbench wide)", "2560x1080"),
            ("2560 \u00d7 1440  (QHD)",           "2560x1440"),
            ("3200 \u00d7 1800",                  "3200x1800"),
            ("3840 \u00d7 2160  (4K UHD)",        "3840x2160"),
        ]:
            size_sub.add_command(
                label=_label,
                command=lambda g=_geo: self.root.geometry(g),
            )
        menu.add_cascade(label="Window Size", menu=size_sub)
        menu.add_separator()
        menu.add_command(label="Reset Display Defaults", command=self._reset_display_defaults)

    def _populate_page_theme_scope_menu(self, parent_menu, scope, label):
        sub = tk.Menu(parent_menu, tearoff=0)
        sub.add_command(
            label="Inherit Shell Theme",
            command=lambda s=scope: self._apply_page_theme_choice(s, None),
        )
        sub.add_separator()
        for theme_name in shell_theme.list_themes():
            sub.add_command(
                label=theme_name,
                command=lambda s=scope, n=theme_name: self._apply_page_theme_choice(s, n),
            )
        parent_menu.add_cascade(label=label, menu=sub)

    # ── Sidebar ─────────────────────────────────────────────

    def refresh_sidebar(self):
        """Rebuild the sidebar treeview from registry + dev-loaded items."""
        tree = self.sidebar_tree

        old_sel = tree.selection()

        for item in tree.get_children():
            tree.delete(item)

        # ── Normal registered packs ─────────────────────────
        include_hidden = self.show_hidden.get()
        packs = guichi.action_list(
            self.registry, include_hidden=include_hidden
        )

        pack_count = 0
        page_count = 0
        problem_count = 0

        for pack in packs:
            pack_id = pack.get("pack_id") or "(no id)"
            suffix = pack.get("display_suffix", "")
            status = pack.get("status", "ok")
            source_path = pack.get("source_path", "")
            hidden = pack.get("hidden", False)

            label_id = pack_id[len("pagepack_"):] if pack_id.startswith("pagepack_") else pack_id
            pack_label = pack.get("custom_nav_name") or label_id
            display_name = f"{pack_label}{suffix}"
            if hidden:
                display_name += "  [hidden]"

            if hidden:
                tag = "hidden"
            elif status == "unavailable":
                tag = "unavailable"
            elif status == "warning":
                tag = "warning"
            else:
                tag = "ok"

            if status in ("warning", "unavailable"):
                problem_count += 1

            item_id = _make_sidebar_pack_id(pack_id, source_path)

            tree.insert(
                "", tk.END,
                iid=item_id,
                text=display_name,
                tags=(tag,),
                open=True,
            )

            pack_count += 1

            for page in pack.get("pages", []):
                pid = page.get("page_id") or "(no id)"
                page_name = page.get("custom_nav_name") or page.get("page_name") or pid
                page_status = page.get("status", "ok")

                if page.get("errors") or page_status == "warning":
                    page_tag = "warning"
                else:
                    page_tag = tag

                page_item_id = _make_sidebar_page_id(pack_id, source_path, pid)

                tree.insert(
                    item_id, tk.END,
                    iid=page_item_id,
                    text=f"  {page_name}",
                    tags=(page_tag,),
                )
                page_count += 1

        # ── DEV LOADED section ──────────────────────────────
        if self._dev_items:
            tree.insert(
                "", tk.END,
                iid=_DEV_SECTION_ID,
                text="\u2500\u2500\u2500 DEV LOADED \u2500\u2500\u2500",
                tags=("dev_section",),
                open=True,
            )

            for dev_item in self._dev_items:
                fp = dev_item.get("file_path", "?")
                cn = dev_item.get("class_name", "?")
                display = dev_item.get("display_name", f"{os.path.basename(fp)} \u2192 {cn}")
                status = dev_item.get("status", "not_loaded")

                if status in ("ok", "warning"):
                    tag = "dev_loaded"
                elif status == "not_loaded":
                    tag = "not_loaded"
                else:
                    tag = "failed"

                dev_iid = _make_sidebar_dev_item_id(fp, cn)
                tree.insert(
                    _DEV_SECTION_ID, tk.END,
                    iid=dev_iid,
                    text=f"  {display}",
                    tags=(tag,),
                )

        # Restore selection
        for sel_id in old_sel:
            if tree.exists(sel_id):
                tree.selection_set(sel_id)
                break

        dev_count = len(self._dev_items)
        status_parts = [f"{pack_count} pack(s)", f"{page_count} page(s)", f"{problem_count} problem(s)"]
        if dev_count:
            status_parts.append(f"{dev_count} dev-loaded")
        self.set_status(", ".join(status_parts))

    def _resolve_pack_for_item(self, item_id):
        """
        Given a sidebar item ID (pack or page), resolve to pack identity.
        Returns (pack_id, source_path, is_hidden) or None.
        """
        parsed = _parse_sidebar_id(item_id)
        if parsed is None:
            return None

        if parsed[0] == "pack":
            pack_id, source_path = parsed[1], parsed[2]
        elif parsed[0] == "page":
            pack_id, source_path = parsed[1], parsed[2]
        else:
            return None

        matches = shell_registry.lookup_pack(
            self.registry, pack_id, source_path=source_path
        )
        if not matches:
            return None

        is_hidden = matches[0].get("hidden", False)
        return (pack_id, source_path, is_hidden)

    def _parse_sidebar_selection(self):
        """
        Parse the currently selected sidebar item.
        Sets self._selected_* fields.
        Returns ("pack", pack_entry), ("page", page_entry, pack_entry),
                ("dev_item", dev_item_dict), ("dev_section",), or None.
        """
        sel = self.sidebar_tree.selection()
        if not sel:
            self._selected_pack_id = None
            self._selected_source_path = None
            self._selected_page_id = None
            return None

        parsed = _parse_sidebar_id(sel[0])
        if parsed is None:
            self._selected_pack_id = None
            self._selected_source_path = None
            self._selected_page_id = None
            return None

        if parsed[0] == "dev_section":
            self._selected_pack_id = None
            self._selected_source_path = None
            self._selected_page_id = None
            return ("dev_section",)

        if parsed[0] == "dev_item":
            file_path, class_name = parsed[1], parsed[2]
            self._selected_pack_id = None
            self._selected_source_path = None
            self._selected_page_id = None
            idx = _find_dev_item(self._dev_items, file_path, class_name)
            if idx < 0:
                return None
            return ("dev_item", self._dev_items[idx])

        if parsed[0] == "page":
            _, pack_id, source_path, page_id = parsed
            self._selected_pack_id = pack_id
            self._selected_source_path = source_path
            self._selected_page_id = page_id

            matches = shell_registry.lookup_pack(
                self.registry, pack_id, source_path=source_path
            )
            if not matches:
                return None
            pack_entry = matches[0]
            for p in pack_entry.get("pages", []):
                if p.get("page_id") == page_id:
                    return ("page", p, pack_entry)
            return None

        if parsed[0] == "pack":
            _, pack_id, source_path = parsed
            self._selected_pack_id = pack_id
            self._selected_source_path = source_path
            self._selected_page_id = None

            matches = shell_registry.lookup_pack(
                self.registry, pack_id, source_path=source_path
            )
            if not matches:
                return None
            return ("pack", matches[0])

        return None

    def _on_sidebar_select(self, event=None):
        """Handle sidebar selection change."""
        sel = self.sidebar_tree.selection()
        if len(sel) > 1:
            self._selected_pack_id = None
            self._selected_source_path = None
            self._selected_page_id = None
            self.clear_content()
            msg = tk.Label(
                self.content_frame,
                text=f"{len(sel)} sidebar items selected.\n\n"
                     "Multi-select is available for navigation management.\n"
                     "Load and detail views still use single selection.",
                justify=tk.CENTER, pady=40,
            )
            msg.pack(expand=True)
            self.set_status(f"{len(sel)} sidebar items selected")
            return

        parsed = self._parse_sidebar_selection()
        if parsed is None:
            self._show_welcome()
            return

        kind = parsed[0]
        if kind == "pack":
            self._show_pack_info(parsed[1])
        elif kind == "page":
            pack_id     = self._selected_pack_id
            page_id     = self._selected_page_id
            source_path = self._selected_source_path
            key = (pack_id, page_id, source_path)
            # Guard against re-fire from refresh_sidebar's selection_set
            # restoring the same selection after a refresh.
            if key != getattr(self, "_last_autoloaded_page", None):
                self._last_autoloaded_page = key
                self._on_load_page(pack_id, page_id, source_path)
        elif kind == "dev_item":
            self._show_dev_item_info(parsed[1])
        elif kind == "dev_section":
            self._show_welcome()

    # ── Sidebar context menu ────────────────────────────────

    def _on_sidebar_right_click(self, event):
        """Show context menu on right-click over a sidebar item."""
        item_id = self.sidebar_tree.identify_row(event.y)
        if not item_id:
            return

        current_selection = self.sidebar_tree.selection()
        if item_id not in current_selection:
            self.sidebar_tree.selection_set(item_id)

        selection = self.sidebar_tree.selection()
        if len(selection) > 1:
            self._show_multi_select_menu(event, selection)
            return

        parsed = _parse_sidebar_id(item_id)
        if parsed is None:
            return

        menu = tk.Menu(self.sidebar_tree, tearoff=0)

        if parsed[0] == "dev_item":
            file_path, class_name = parsed[1], parsed[2]
            menu.add_command(
                label="Reload",
                command=lambda: self._on_dev_item_reload(file_path, class_name),
            )
            menu.add_command(
                label="Remove",
                command=lambda: self._on_dev_item_remove(file_path, class_name),
            )
            interaction_support.show_popup_menu(self.root, menu, event.x_root, event.y_root)
            return

        if parsed[0] == "dev_section":
            return  # no context menu on the section header

        # Normal pack/page context menu
        pack_info = self._resolve_pack_for_item(item_id)
        if pack_info is None:
            return

        pack_id, source_path, is_hidden = pack_info

        # Page-specific: offer Load
        if parsed[0] == "page":
            page_id = parsed[3]
            menu.add_command(
                label="Load page",
                command=lambda: self._on_load_page(pack_id, page_id, source_path),
            )
            menu.add_command(
                label="Rename...",
                command=lambda: self._on_rename_page(pack_id, source_path, page_id),
            )
            menu.add_command(
                label="Reset name",
                command=lambda: self._on_reset_page_name(pack_id, source_path, page_id),
            )
            menu.add_separator()
        elif parsed[0] == "pack":
            menu.add_command(
                label="Rename...",
                command=lambda: self._on_rename_pack(pack_id, source_path),
            )
            menu.add_command(
                label="Reset name",
                command=lambda: self._on_reset_pack_name(pack_id, source_path),
            )
            menu.add_separator()

        # Pack-level actions
        if is_hidden:
            menu.add_command(
                label="Unhide",
                command=lambda: self._on_unhide_pack(pack_id, source_path),
            )
        else:
            menu.add_command(
                label="Hide",
                command=lambda: self._on_hide_pack(pack_id, source_path),
            )

        menu.add_command(
            label="Remove\u2026",
            command=lambda: self._on_remove_pack(pack_id, source_path),
        )

        interaction_support.show_popup_menu(self.root, menu, event.x_root, event.y_root)

    def _show_multi_select_menu(self, event, selection):
        """Show a bulk-action menu for a multi-selection of pack items."""
        pack_rows = []
        for item_id in selection:
            parsed = _parse_sidebar_id(item_id)
            if parsed is None or parsed[0] != "pack":
                self.set_status("bulk actions currently support pack selections only")
                return
            pack_info = self._resolve_pack_for_item(item_id)
            if pack_info is None:
                self.set_status("bulk action failed: could not resolve selected pack")
                return
            pack_rows.append(pack_info)

        menu = tk.Menu(self.sidebar_tree, tearoff=0)
        menu.add_command(
            label=f"Hide selected ({len(pack_rows)})",
            command=lambda: self._on_bulk_pack_action(pack_rows, 3, "hidden"),
        )
        menu.add_command(
            label=f"Remove selected ({len(pack_rows)})",
            command=lambda: self._on_bulk_pack_action(pack_rows, 1, "removed"),
        )
        if any(info[2] for info in pack_rows):
            menu.add_command(
                label=f"Unhide selected ({len(pack_rows)})",
                command=lambda: self._on_bulk_unhide_packs(pack_rows),
            )
        interaction_support.show_popup_menu(self.root, menu, event.x_root, event.y_root)

    def _on_hide_pack(self, pack_id, source_path):
        """Hide a pack (shortcut for remove choice 3)."""
        result = guichi.action_apply_remove(self.registry, pack_id, source_path, 3)
        if result:
            self.refresh_sidebar()
            self._show_welcome()
            self.set_status(f"hidden: {pack_id}")
        else:
            self.set_status(f"hide failed: {pack_id} not found")

    def _on_unhide_pack(self, pack_id, source_path):
        """Unhide a previously hidden pack."""
        found = guichi.action_unhide(self.registry, pack_id, source_path)
        if found:
            self.refresh_sidebar()
            self._show_welcome()
            self.set_status(f"unhidden: {pack_id}")
        else:
            self.set_status(f"unhide failed: {pack_id} not found")

    def _on_clear_registry(self):
        """Clear the saved registry and empty the navigation sidebar."""
        pack_count = len(self.registry.get("packs", []))
        if not pack_count:
            self.set_status("registry already empty")
            self._show_welcome()
            return

        confirm = messagebox.askyesno(
            "Clear registry/navigation",
            f"Clear all {pack_count} registered pack entries from the shell registry?\n\n"
            "This clears the current navigation list and saved registry cache.\n"
            "It does not delete project files on disk.",
            parent=self.root,
        )
        if not confirm:
            return

        shell_registry.clear_registry(self.registry)
        shell_registry.save_registry(self.registry, guichi.REGISTRY_PATH)
        self.refresh_sidebar()
        self._show_welcome()
        self.set_status(f"registry cleared: removed {pack_count} pack entry(s)")

    def _on_bulk_pack_action(self, pack_rows, choice, action_label):
        """Apply a hide/remove action to multiple selected packs."""
        count = 0
        for pack_id, source_path, _is_hidden in pack_rows:
            result = shell_registry.apply_remove_action(self.registry, pack_id, source_path, choice)
            if result:
                count += 1
        shell_registry.save_registry(self.registry, guichi.REGISTRY_PATH)
        self.refresh_sidebar()
        self._show_welcome()
        self.set_status(f"{action_label} {count} pack(s)")

    def _on_bulk_unhide_packs(self, pack_rows):
        """Unhide multiple selected packs."""
        count = 0
        for pack_id, source_path, _is_hidden in pack_rows:
            if shell_registry.unhide_pack(self.registry, pack_id, source_path):
                count += 1
        shell_registry.save_registry(self.registry, guichi.REGISTRY_PATH)
        self.refresh_sidebar()
        self._show_welcome()
        self.set_status(f"unhid {count} pack(s)")

    def _on_rename_pack(self, pack_id, source_path):
        """Prompt for a custom nav name for a pack."""
        matches = shell_registry.lookup_pack(self.registry, pack_id, source_path=source_path)
        if not matches:
            self.set_status(f"rename failed: {pack_id} not found")
            return
        current = matches[0].get("custom_nav_name") or ""
        new_name = simpledialog.askstring(
            "Rename pack",
            "Custom navigation name:",
            initialvalue=current,
            parent=self.root,
        )
        if new_name is None:
            return
        if shell_registry.set_pack_custom_name(self.registry, pack_id, source_path, new_name.strip()):
            shell_registry.save_registry(self.registry, guichi.REGISTRY_PATH)
            self.refresh_sidebar()
            self.set_status(f"renamed pack: {pack_id}")

    def _on_reset_pack_name(self, pack_id, source_path):
        """Reset a pack custom nav name to default."""
        if shell_registry.set_pack_custom_name(self.registry, pack_id, source_path, None):
            shell_registry.save_registry(self.registry, guichi.REGISTRY_PATH)
            self.refresh_sidebar()
            self.set_status(f"reset pack name: {pack_id}")

    def _on_rename_page(self, pack_id, source_path, page_id):
        """Prompt for a custom nav name for a page."""
        matches = shell_registry.lookup_pack(self.registry, pack_id, source_path=source_path)
        if not matches:
            self.set_status(f"rename failed: {page_id} not found")
            return
        page_entry = next((p for p in matches[0].get("pages", []) if p.get("page_id") == page_id), None)
        if page_entry is None:
            self.set_status(f"rename failed: {page_id} not found")
            return
        current = page_entry.get("custom_nav_name") or ""
        new_name = simpledialog.askstring(
            "Rename page",
            "Custom navigation name:",
            initialvalue=current,
            parent=self.root,
        )
        if new_name is None:
            return
        if shell_registry.set_page_custom_name(self.registry, pack_id, source_path, page_id, new_name.strip()):
            shell_registry.save_registry(self.registry, guichi.REGISTRY_PATH)
            self.refresh_sidebar()
            self.set_status(f"renamed page: {page_id}")

    def _on_reset_page_name(self, pack_id, source_path, page_id):
        """Reset a page custom nav name to default."""
        if shell_registry.set_page_custom_name(self.registry, pack_id, source_path, page_id, None):
            shell_registry.save_registry(self.registry, guichi.REGISTRY_PATH)
            self.refresh_sidebar()
            self.set_status(f"reset page name: {page_id}")

    def _on_remove_pack(self, pack_id, source_path):
        """Show the three-choice remove dialog for a pack."""
        choice = _RemoveDialog.ask(self.root, pack_id, source_path)
        if choice is None:
            return

        result = guichi.action_apply_remove(self.registry, pack_id, source_path, choice)
        if result:
            self.refresh_sidebar()
            self._show_welcome()
            self.set_status(result)
        else:
            self.set_status(f"remove failed: {pack_id} not found")

    # ── Normal page loading ─────────────────────────────────

    def _on_load_page(self, pack_id, page_id, source_path):
        """Load a normal registered page."""
        self.set_status(f"loading: {page_id}...")
        self._current_page_pack_id = pack_id
        self._current_page_source_path = source_path
        self._current_page_id = page_id
        self._current_page_theme_name, self._current_page_theme_scope = self._resolve_page_theme(
            pack_id, source_path, page_id
        )
        self._apply_current_page_theme_to_shell_content()
        self._notify_sw_page_changed(page_id, pack_id)

        result = guichi.action_load_page(
            self.config, self.registry,
            pack_id, page_id,
            source_path=source_path,
            instantiate=False,
        )

        if result.get("status") == "failed":
            self.show_load_result(result)
            self.set_status(f"load failed: {page_id}")
            return

        page_class = result.get("page_class")

        if page_class is None:
            self.show_load_result(result)
            self.set_status(f"load failed: {page_id} (no class returned)")
            return

        embedded, method_used, embed_error = self._try_embed_page(page_class)

        if embedded:
            self.set_status(f"loaded: {page_id} (embedded via {method_used})")
            sel = self.sidebar_tree.selection()
            if sel:
                self.sidebar_tree.see(sel[0])
        elif embed_error:
            self.show_load_result_with_embed_error(result, method_used, embed_error)
            self.set_status(f"loaded: {page_id} (embed failed: {method_used})")
        else:
            self.show_load_result_with_no_gui(result)
            self.set_status(f"loaded: {page_id} (no GUI method found)")

    def _try_embed_page(self, page_class):
        """
        Instantiate page_class with content_frame as parent, then probe for
        a GUI mount method and call it. Clears content before instantiation so
        the new frame is a child of content_frame and survives clear_content()
        on subsequent loads.
        Returns:
            (True,  method_name, None)        — embedded successfully
            (False, method_name, error_str)   — instantiation or method raised
            (False, None,        None)        — no GUI method found
        """
        self.clear_content()
        try:
            page_instance = page_class(self.content_frame)
        except Exception:
            tb = traceback.format_exc()
            self._active_page_instance = None
            return (False, "instantiation", tb)

        page_theme_context = self.get_current_page_theme_context()
        try:
            setattr(page_instance, "guichi_shell", self)
            setattr(page_instance, "guichi_page_theme", page_theme_context)
            if hasattr(page_instance, "set_guichi_page_theme"):
                page_instance.set_guichi_page_theme(page_theme_context)
        except Exception:
            pass

        embedded, method_name, embed_err = shell_loader.probe_page_gui_method(
            page_instance, self.content_frame
        )
        self._active_page_instance = page_instance if embedded else None
        return (embedded, method_name, embed_err)

    def _reapply_active_page_theme(self):
        """Safely push current page-theme context into the live page instance."""
        self._apply_current_page_theme_to_shell_content()
        page_instance = getattr(self, "_active_page_instance", None)
        if page_instance is None:
            return

        page_theme_context = self.get_current_page_theme_context()
        try:
            setattr(page_instance, "guichi_shell", self)
            setattr(page_instance, "guichi_page_theme", page_theme_context)
            if hasattr(page_instance, "set_guichi_page_theme"):
                page_instance.set_guichi_page_theme(page_theme_context)
        except Exception:
            # Theme reapply must stay visual-only and never break page state.
            pass
        self._notify_sw_theme_changed()

    def _notify_sw_theme_changed(self):
        sw_mod = self._right_sw_mod
        if sw_mod is None:
            return
        fn = getattr(sw_mod, "set_theme", None)
        if callable(fn):
            try:
                fn(shell_theme.get_theme())
            except Exception:
                pass

    def _apply_current_page_theme_to_shell_content(self):
        context = self.get_current_page_theme_context()
        tokens = context.get("tokens") or {}
        bg = tokens.get("content_bg") or tokens.get("app_bg") or APP_BG
        try:
            self.content_frame.configure(bg=bg)
        except Exception:
            pass

    # ── Dev mode: load .py file ─────────────────────────────

    def _on_dev_load_py(self):
        """Open file dialog, scan for classes, add to dev-loaded items, attempt load."""
        file_path = filedialog.askopenfilename(
            parent=self.root,
            title="Load Python Page File (dev mode)",
            filetypes=[("Python files", "*.py"), ("All files", "*.*")],
        )
        if not file_path:
            return

        file_path = os.path.abspath(file_path)

        # Scan for classes
        self.set_status(f"scanning: {os.path.basename(file_path)}...")
        classes, scan_error = _scan_classes_in_file(file_path)

        if scan_error:
            self.set_status(f"scan failed: {os.path.basename(file_path)}")
            self._show_dev_scan_error(file_path, scan_error)
            return

        if not classes:
            self.set_status(f"no classes found: {os.path.basename(file_path)}")
            self._show_dev_scan_error(
                file_path,
                "No class definitions found in this file.\n"
                "The file may be a utility module or data file.",
            )
            return

        # Choose class
        if len(classes) == 1:
            class_name = classes[0]
        else:
            class_name = _ClassChooserDialog.ask(
                self.root, file_path, classes
            )
            if class_name is None:
                return  # cancelled

        # Add to dev items
        display_name = f"{os.path.basename(file_path)} \u2192 {class_name}"

        # Check for existing entry with same identity — replace it
        idx = _find_dev_item(self._dev_items, file_path, class_name)
        new_entry = {
            "file_path": file_path,
            "class_name": class_name,
            "display_name": display_name,
            "status": "not_loaded",
            "message": "not yet loaded",
            "added_at": datetime.now(timezone.utc).isoformat(),
        }
        if idx >= 0:
            self._dev_items[idx] = new_entry
        else:
            self._dev_items.append(new_entry)

        _save_dev_items(self._dev_items)
        self.refresh_sidebar()

        # Immediately load it
        self._dev_load_and_show(file_path, class_name)

    def _dev_load_and_show(self, file_path, class_name):
        """
        Load a dev .py file via shell_loader.load_page with synthetic entries.
        Updates the dev item's status/message and shows the result.
        """
        self.set_status(f"loading: {os.path.basename(file_path)} \u2192 {class_name}...")

        # Construct synthetic entries for shell_loader
        synthetic_pack = {
            "pack_id": f"dev_{os.path.splitext(os.path.basename(file_path))[0]}",
            "source_path": os.path.dirname(file_path),
        }
        synthetic_page = {
            "page_id": f"dev_{os.path.splitext(os.path.basename(file_path))[0]}_{class_name}",
            "page_name": f"{os.path.basename(file_path)} \u2192 {class_name}",
            "page_path": os.path.basename(file_path),
            "page_class": class_name,
        }

        result = shell_loader.load_page(
            synthetic_pack, synthetic_page,
            dev_mode=True, instantiate=False,
        )

        # Update persisted status
        idx = _find_dev_item(self._dev_items, file_path, class_name)
        if idx >= 0:
            self._dev_items[idx]["status"] = result.get("status", "failed")
            self._dev_items[idx]["message"] = result.get("message", "")
            _save_dev_items(self._dev_items)
            self.refresh_sidebar()

        # Show result
        if result.get("status") == "failed":
            self.show_load_result(result)
            self.set_status(f"dev load failed: {class_name}")
            return

        page_class = result.get("page_class")
        if page_class is None:
            self.show_load_result(result)
            self.set_status(f"dev load failed: {class_name} (no class returned)")
            return

        embedded, method_used, embed_error = self._try_embed_page(page_class)

        if embedded:
            self.set_status(f"dev loaded: {class_name} (embedded via {method_used})")
        elif embed_error:
            self.show_load_result_with_embed_error(result, method_used, embed_error)
            self.set_status(f"dev loaded: {class_name} (embed failed: {method_used})")
        else:
            self.show_load_result_with_no_gui(result)
            self.set_status(f"dev loaded: {class_name} (no GUI method found)")

    def _on_dev_item_reload(self, file_path, class_name):
        """Reload a dev-loaded item (re-import, re-instantiate, re-embed)."""
        self._dev_load_and_show(file_path, class_name)

    def _on_dev_item_remove(self, file_path, class_name):
        """Remove a single dev-loaded item."""
        idx = _find_dev_item(self._dev_items, file_path, class_name)
        if idx >= 0:
            self._dev_items.pop(idx)
            _save_dev_items(self._dev_items)
            self.refresh_sidebar()
            self._show_welcome()
            self.set_status(f"removed dev item: {class_name}")

    def _on_dev_reset(self):
        """Master dev-mode reset: clear all dev-loaded items."""
        if not self._dev_items:
            self.set_status("dev reset: nothing to clear")
            return

        count = len(self._dev_items)
        confirm = messagebox.askyesno(
            "Reset dev mode",
            f"Remove all {count} dev-loaded item(s)?\n\n"
            "This clears the dev-loaded layer only.\n"
            "Normal registered packs are not affected.",
            parent=self.root,
        )
        if not confirm:
            return

        self._dev_items.clear()
        _save_dev_items(self._dev_items)
        self.refresh_sidebar()
        self._show_welcome()
        self.set_status(f"dev reset: cleared {count} item(s)")

    def _show_dev_scan_error(self, file_path, error_text):
        """Show a scan error for a dev .py file load attempt."""
        self.clear_content()
        frame = tk.Frame(self.content_frame, padx=12, pady=12)
        frame.pack(fill=tk.BOTH, expand=True, anchor=tk.NW)

        tk.Label(
            frame, text="Dev Load: scan failed",
            font=("TkDefaultFont", 14, "bold"), anchor=tk.W,
        ).pack(fill=tk.X)

        tk.Label(
            frame, text=f"file: {file_path}",
            font=INFO_VALUE_FONT, anchor=tk.W,
        ).pack(fill=tk.X, pady=(4, 0))

        self._render_detail_text(frame, error_text)

    # ── Content area ────────────────────────────────────────

    def clear_content(self):
        """Remove all widgets from the content frame."""
        self._active_page_instance = None
        for child in self.content_frame.winfo_children():
            child.destroy()

    def _show_welcome(self):
        """Show the empty/welcome state in the content area.
        Also clears selection tracking."""
        self.clear_content()
        self._selected_pack_id = None
        self._selected_source_path = None
        self._selected_page_id = None
        self._current_page_pack_id = None
        self._current_page_source_path = None
        self._current_page_id = None
        self._current_page_theme_name, self._current_page_theme_scope = self._resolve_page_theme()
        self._apply_current_page_theme_to_shell_content()
        self._notify_sw_page_changed(None, None)
        _t = shell_theme.get_theme()
        card = tk.Frame(
            self.content_frame,
            bg=_t["panel_bg"],
            highlightthickness=1,
            highlightbackground=_t["border"],
            padx=24,
            pady=24,
        )
        card.pack(expand=True)
        tk.Label(
            card,
            text="Guichi",
            bg=_t["panel_bg"],
            fg=_t["accent"],
            font=("TkDefaultFont", 16, "bold"),
        ).pack()
        tk.Label(
            card,
            text="Select a page from the navigation sidebar.",
            bg=_t["panel_bg"],
            fg=_t["text_muted"],
            font=("TkDefaultFont", _t.get("font_size_main", 10)),
        ).pack(pady=(8, 0))

    def _notify_sw_page_changed(self, page_id, pack_id):
        """Notify the active sidewindow module that the current page changed."""
        sw_mod = self._right_sw_mod
        if sw_mod is None:
            return
        notify = getattr(sw_mod, "on_page_changed", None)
        if not callable(notify):
            return
        desc = PAGE_HOME_DESCRIPTIONS.get(page_id, "") if page_id else ""
        try:
            notify(page_id, pack_id, desc)
        except Exception:
            pass

    def _format_pack_home_title(self, pack_entry):
        pack_id = pack_entry.get("pack_id") or "(no pack_id)"
        raw = pack_entry.get("pack_name") or pack_entry.get("module_title") or pack_id
        cleaned = raw.replace("pagepack_", "").replace("_", " ").strip()
        if not cleaned:
            cleaned = pack_id
        return cleaned

    def _pack_home_description(self, pack_entry):
        pack_id = pack_entry.get("pack_id") or ""
        manifest_desc = pack_entry.get("home_description") or pack_entry.get("description")
        if manifest_desc:
            return manifest_desc
        return PACK_HOME_DESCRIPTIONS.get(
            pack_id,
            "This pack contains related Guichi pages. Select a page from the list below to load it directly.",
        )

    def _page_home_description(self, page_entry):
        page_id = page_entry.get("page_id") or ""
        if page_entry.get("page_title"):
            title = page_entry.get("page_title")
        else:
            title = page_entry.get("page_name") or page_id
        fallback = f"{title} page in this pack."
        return PAGE_HOME_DESCRIPTIONS.get(page_id, fallback)

    def _pack_logo_text(self, pack_entry):
        raw = self._format_pack_home_title(pack_entry)
        letters = [part[0] for part in raw.split() if part and part[0].isalnum()]
        if not letters:
            return "PK"
        return "".join(letters[:3]).upper()

    def _show_pack_info(self, pack_entry):
        """Show pack information in the content area."""
        self.clear_content()
        frame = tk.Frame(self.content_frame, padx=18, pady=18, bg=_T["content_bg"])
        frame.pack(fill=tk.BOTH, expand=True, anchor=tk.NW)

        pack_id = pack_entry.get("pack_id") or "(no pack_id)"
        suffix = pack_entry.get("display_suffix", "")
        status = pack_entry.get("status", "?")
        source_path = pack_entry.get("source_path", "?")
        hidden = pack_entry.get("hidden", False)
        pages = pack_entry.get("pages", [])
        status_color = STATUS_COLORS.get(status, STATUS_COLORS["ok"])["fg"]

        hero = tk.Frame(frame, bg=_T["content_bg"])
        hero.pack(fill=tk.X, pady=(0, 14))

        badge = tk.Canvas(
            hero,
            width=92,
            height=92,
            bg=_T["content_bg"],
            highlightthickness=0,
        )
        badge.pack(side=tk.LEFT, padx=(0, 14))
        badge.create_oval(6, 6, 86, 86, fill=_T["accent"], outline="")
        badge.create_text(
            46, 46,
            text=self._pack_logo_text(pack_entry),
            fill=_T["text_on_accent"],
            font=("TkDefaultFont", 20, "bold"),
        )

        hero_text = tk.Frame(hero, bg=_T["content_bg"])
        hero_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(
            hero_text,
            text=f"{self._format_pack_home_title(pack_entry)}{suffix}",
            font=("TkDefaultFont", 18, "bold"),
            anchor=tk.W,
            bg=_T["content_bg"],
            fg=_T["text_main"],
        ).pack(fill=tk.X)

        status_text = f"status: {status}"
        if hidden:
            status_text += "  (hidden)"
        tk.Label(
            hero_text,
            text=status_text,
            fg=status_color,
            bg=_T["content_bg"],
            anchor=tk.W,
        ).pack(fill=tk.X, pady=(2, 0))

        tk.Label(
            hero_text,
            text=self._pack_home_description(pack_entry),
            justify=tk.LEFT,
            wraplength=760,
            anchor=tk.W,
            bg=_T["content_bg"],
            fg=_T["text_main"],
        ).pack(fill=tk.X, pady=(10, 0))

        meta = tk.Frame(frame, bg=_T["panel_bg"], bd=1, highlightthickness=1,
                        highlightbackground=_T["border"])
        meta.pack(fill=tk.X, pady=(0, 14))

        for text in (
            f"Source: {source_path}",
            f"Last scanned: {pack_entry.get('last_scanned', '?')}",
            f"Pages: {len(pages)}",
        ):
            tk.Label(
                meta,
                text=text,
                font=INFO_VALUE_FONT,
                anchor=tk.W,
                bg=_T["panel_bg"],
                fg=_T["text_main"],
                padx=10,
                pady=6,
            ).pack(fill=tk.X)

        tk.Label(
            frame,
            text="Pages In This Pack",
            font=("TkDefaultFont", 12, "bold"),
            anchor=tk.W,
            bg=_T["content_bg"],
            fg=_T["text_main"],
        ).pack(fill=tk.X, pady=(0, 8))

        for page in pages:
            pid = page.get("page_id") or "(no id)"
            page_name = page.get("page_title") or page.get("page_name") or pid
            page_status = page.get("status", "ok")
            page_status_color = STATUS_COLORS.get(page_status, STATUS_COLORS["ok"])["fg"]

            card = tk.Frame(
                frame,
                bg=_T["panel_bg"],
                bd=1,
                highlightthickness=1,
                highlightbackground=_T["border"],
                padx=10,
                pady=8,
            )
            card.pack(fill=tk.X, pady=(0, 8))

            top = tk.Frame(card, bg=_T["panel_bg"])
            top.pack(fill=tk.X)

            tk.Label(
                top,
                text=page_name,
                font=("TkDefaultFont", 11, "bold"),
                anchor=tk.W,
                bg=_T["panel_bg"],
                fg=_T["text_main"],
            ).pack(side=tk.LEFT, fill=tk.X, expand=True)

            tk.Button(
                top,
                text="Load page",
                command=lambda p=pid, sid=source_path, pack=pack_id: self._on_load_page(pack, p, sid),
                padx=8,
                bg=_T["button_bg"],
                fg=_T["text_main"],
                activebackground=_T["button_hover"],
                activeforeground=_T["text_active"],
            ).pack(side=tk.RIGHT)

            tk.Label(
                card,
                text=self._page_home_description(page),
                justify=tk.LEFT,
                wraplength=760,
                anchor=tk.W,
                bg=_T["panel_bg"],
                fg=_T["text_main"],
            ).pack(fill=tk.X, pady=(6, 0))

            tk.Label(
                card,
                text=f"{pid}  [{page_status}]",
                anchor=tk.W,
                bg=_T["panel_bg"],
                fg=page_status_color,
            ).pack(fill=tk.X, pady=(6, 0))

        self._render_warnings_errors(frame, pack_entry)

    def _show_page_info(self, page_entry, pack_entry):
        """Show page information in the content area, with a Load button."""
        self.clear_content()
        frame = tk.Frame(self.content_frame, padx=12, pady=12)
        frame.pack(fill=tk.BOTH, expand=True, anchor=tk.NW)

        page_id = page_entry.get("page_id") or "(no page_id)"
        page_name = page_entry.get("page_name") or "(no name)"
        page_status = page_entry.get("status", "?")
        pack_id = pack_entry.get("pack_id") or "(no pack_id)"
        source_path = pack_entry.get("source_path") or "?"

        header_row = tk.Frame(frame)
        header_row.pack(fill=tk.X)

        tk.Label(
            header_row, text=page_name,
            font=("TkDefaultFont", 14, "bold"), anchor=tk.W,
        ).pack(side=tk.LEFT)

        tk.Button(
            header_row, text="Load page",
            command=lambda: self._on_load_page(pack_id, page_id, source_path),
            padx=8,
        ).pack(side=tk.RIGHT)

        status_color = STATUS_COLORS.get(page_status, STATUS_COLORS["ok"])["fg"]
        tk.Label(frame, text=f"status: {page_status}", fg=status_color, anchor=tk.W).pack(fill=tk.X)

        fields = [
            ("page_id", page_id),
            ("page_path", page_entry.get("page_path") or "(no path)"),
            ("page_class", page_entry.get("page_class") or "(no class)"),
            ("pack", f"{pack_id} at {source_path}"),
        ]
        for opt in ("page_title", "page_folder_path", "page_config_path"):
            val = page_entry.get(opt)
            if val:
                fields.append((opt, val))

        for label, value in fields:
            row = tk.Frame(frame)
            row.pack(fill=tk.X, pady=1)
            tk.Label(row, text=f"{label}:", font=INFO_LABEL_FONT, anchor=tk.W, width=18).pack(side=tk.LEFT)
            tk.Label(row, text=value, font=INFO_VALUE_FONT, anchor=tk.W).pack(side=tk.LEFT, fill=tk.X)

        self._render_warnings_errors(frame, page_entry)

    def _show_dev_item_info(self, dev_item):
        """Show dev-loaded item info in the content area, with a Load button."""
        self.clear_content()
        frame = tk.Frame(self.content_frame, padx=12, pady=12)
        frame.pack(fill=tk.BOTH, expand=True, anchor=tk.NW)

        file_path = dev_item.get("file_path", "?")
        class_name = dev_item.get("class_name", "?")
        display_name = dev_item.get("display_name", "?")
        status = dev_item.get("status", "not_loaded")
        message = dev_item.get("message", "")
        added_at = dev_item.get("added_at", "?")

        # Header with Load button
        header_row = tk.Frame(frame)
        header_row.pack(fill=tk.X)

        tk.Label(
            header_row, text=display_name,
            font=("TkDefaultFont", 14, "bold"), anchor=tk.W,
            fg=STATUS_COLORS["dev_loaded"]["fg"],
        ).pack(side=tk.LEFT)

        tk.Button(
            header_row, text="Load page",
            command=lambda: self._dev_load_and_show(file_path, class_name),
            padx=8,
        ).pack(side=tk.RIGHT)

        # Dev-loaded marker
        tk.Label(
            frame, text="[dev-loaded \u2014 not canonically registered]",
            fg=STATUS_COLORS["dev_loaded"]["fg"], anchor=tk.W,
        ).pack(fill=tk.X)

        # Status
        status_color = STATUS_COLORS.get(status, STATUS_COLORS["not_loaded"])["fg"]
        tk.Label(frame, text=f"status: {status}", fg=status_color, anchor=tk.W).pack(fill=tk.X)

        # Fields
        fields = [
            ("file", file_path),
            ("class", class_name),
            ("added", added_at),
        ]
        if message:
            fields.append(("message", message))

        for label, value in fields:
            row = tk.Frame(frame)
            row.pack(fill=tk.X, pady=1)
            tk.Label(row, text=f"{label}:", font=INFO_LABEL_FONT, anchor=tk.W, width=12).pack(side=tk.LEFT)
            tk.Label(row, text=value, font=INFO_VALUE_FONT, anchor=tk.W).pack(side=tk.LEFT, fill=tk.X)

    def _render_warnings_errors(self, parent, entry):
        """Render warnings and errors from a pack or page entry dict."""
        warnings = entry.get("warnings", [])
        if warnings:
            tk.Label(
                parent, text="warnings:", font=INFO_LABEL_FONT,
                anchor=tk.W, pady=(8, 0),
            ).pack(fill=tk.X)
            for w in warnings:
                tk.Label(
                    parent, text=f"  {w}", font=INFO_WARN_FONT,
                    fg=shell_theme.get_theme()["text_warn"], anchor=tk.W, wraplength=500,
                ).pack(fill=tk.X)

        errors = entry.get("errors", [])
        if errors:
            tk.Label(
                parent, text="errors:", font=INFO_LABEL_FONT,
                anchor=tk.W, pady=(8, 0),
            ).pack(fill=tk.X)
            for e in errors:
                tk.Label(
                    parent, text=f"  {e}", font=INFO_WARN_FONT,
                    fg=shell_theme.get_theme()["text_error"], anchor=tk.W, wraplength=500,
                ).pack(fill=tk.X)

    def show_load_result(self, result):
        """Show a load result in the content area. Fallback for failed loads."""
        self.clear_content()
        _t = shell_theme.get_theme()
        card = tk.Frame(
            self.content_frame,
            bg=_t["panel_bg"],
            highlightthickness=1,
            highlightbackground=_t["border"],
            padx=16,
            pady=16,
        )
        card.pack(anchor=tk.NW, padx=12, pady=12)

        status = result.get("status", "?")
        page_id = result.get("page_id") or "(no id)"
        page_name = result.get("page_name") or ""
        message = result.get("message") or ""
        error_detail = result.get("error_detail") or ""
        page_path = result.get("page_path") or ""

        tk.Label(
            card,
            text="Load failed" if status == "failed" else f"Load: {page_name or page_id}",
            bg=_t["panel_bg"],
            fg=_t["text_error"] if status == "failed" else _t["text_main"],
            font=("TkDefaultFont", 14, "bold"),
            anchor=tk.W,
        ).pack(fill=tk.X)

        if page_path:
            tk.Label(
                card,
                text=page_path,
                bg=_t["panel_bg"],
                fg=_t["text_muted"],
                font=INFO_VALUE_FONT,
                anchor=tk.W,
            ).pack(fill=tk.X, pady=(2, 0))

        status_color = STATUS_COLORS.get(status, STATUS_COLORS["ok"])["fg"]
        tk.Label(
            card, text=f"status: {status}",
            fg=status_color, bg=_t["panel_bg"], anchor=tk.W,
        ).pack(fill=tk.X, pady=(4, 0))

        if message:
            tk.Label(
                card, text=message,
                bg=_t["panel_bg"], fg=_t["text_muted"],
                anchor=tk.W, wraplength=500,
            ).pack(fill=tk.X, pady=(4, 0))

        if error_detail:
            tk.Button(
                card,
                text="Copy error",
                bg=_t["button_bg"],
                fg=_t["text_main"],
                relief=tk.FLAT,
                padx=8,
                command=lambda: (self.root.clipboard_clear(),
                                 self.root.clipboard_append(error_detail)),
            ).pack(anchor=tk.W, pady=(8, 4))
            self._render_detail_text(card, error_detail)

    def show_load_result_with_no_gui(self, result):
        """Show a successful load result where no GUI method was found."""
        self.clear_content()
        frame = tk.Frame(self.content_frame, padx=12, pady=12)
        frame.pack(fill=tk.BOTH, expand=True, anchor=tk.NW)

        page_name = result.get("page_name") or result.get("page_id") or "(unknown)"

        tk.Label(
            frame, text=f"Loaded: {page_name}",
            font=("TkDefaultFont", 14, "bold"), anchor=tk.W,
        ).pack(fill=tk.X)

        tk.Label(
            frame, text="status: ok (class loaded, no GUI method found)",
            fg=STATUS_COLORS["warning"]["fg"], anchor=tk.W,
        ).pack(fill=tk.X)

        tk.Label(
            frame,
            text=f"probed methods: {', '.join(_PAGE_GUI_METHODS)}",
            font=INFO_VALUE_FONT, anchor=tk.W,
        ).pack(fill=tk.X, pady=(8, 0))

        tk.Label(
            frame,
            text="The page loaded successfully but does not expose a GUI mount method.\n"
                 "This is normal for non-visual pages.",
            anchor=tk.W, wraplength=500, justify=tk.LEFT,
        ).pack(fill=tk.X, pady=(8, 0))

        message = result.get("message")
        if message:
            tk.Label(frame, text=message, font=INFO_VALUE_FONT, anchor=tk.W).pack(fill=tk.X, pady=(8, 0))

    def show_load_result_with_embed_error(self, result, method_name, error_detail):
        """Show a load result where a GUI method was found but raised an error."""
        self.clear_content()
        _t = shell_theme.get_theme()
        card = tk.Frame(
            self.content_frame,
            bg=_t["panel_bg"],
            highlightthickness=1,
            highlightbackground=_t["border"],
            padx=16,
            pady=16,
        )
        card.pack(anchor=tk.NW, padx=12, pady=12)

        page_name = result.get("page_name") or result.get("page_id") or "(unknown)"
        page_path = result.get("page_path") or ""

        tk.Label(
            card,
            text=f"Embed failed: {page_name}",
            bg=_t["panel_bg"],
            fg=_t["text_error"],
            font=("TkDefaultFont", 14, "bold"),
            anchor=tk.W,
        ).pack(fill=tk.X)

        if page_path:
            tk.Label(
                card,
                text=page_path,
                bg=_t["panel_bg"],
                fg=_t["text_muted"],
                font=INFO_VALUE_FONT,
                anchor=tk.W,
            ).pack(fill=tk.X, pady=(2, 0))

        tk.Label(
            card,
            text=f"status: {method_name}() raised an error",
            fg=STATUS_COLORS["error"]["fg"],
            bg=_t["panel_bg"],
            anchor=tk.W,
        ).pack(fill=tk.X, pady=(4, 0))

        tk.Label(
            card,
            text=f"The page class loaded and instantiated, but {method_name}(parent) failed.",
            bg=_t["panel_bg"],
            fg=_t["text_muted"],
            anchor=tk.W,
            wraplength=500,
        ).pack(fill=tk.X, pady=(8, 0))

        tk.Button(
            card,
            text="Copy error",
            bg=_t["button_bg"],
            fg=_t["text_main"],
            relief=tk.FLAT,
            padx=8,
            command=lambda: (self.root.clipboard_clear(),
                             self.root.clipboard_append(error_detail)),
        ).pack(anchor=tk.W, pady=(8, 4))
        self._render_detail_text(card, error_detail)

    def _render_detail_text(self, parent, text):
        """Render a scrollable read-only detail/traceback text block."""
        tk.Label(
            parent, text="detail:", font=INFO_LABEL_FONT,
            anchor=tk.W, pady=(8, 0),
        ).pack(fill=tk.X)
        detail_frame = tk.Frame(parent)
        detail_frame.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.rowconfigure(0, weight=1)
        detail_scroll = ttk.Scrollbar(detail_frame, orient=tk.VERTICAL)
        detail_widget = tk.Text(
            detail_frame, height=10, wrap=tk.WORD, font=INFO_VALUE_FONT,
            yscrollcommand=detail_scroll.set,
        )
        detail_scroll.configure(command=detail_widget.yview)
        detail_widget.grid(row=0, column=0, sticky="nsew")
        detail_scroll.grid(row=0, column=1, sticky="ns")
        detail_widget.insert(tk.END, text)
        detail_widget.configure(state=tk.DISABLED)

    # ── Status bar ──────────────────────────────────────────

    def set_status(self, text):
        """Update the status bar text."""
        self.status_var.set(text)

    # ── Discover ────────────────────────────────────────────

    def _on_discover(self, scan_style=None):
        """Run pack discovery from a user-chosen root directory."""
        if scan_style is None:
            scan_style = self.config.get("default_scan_style", 1)

        initial_dir = self.config.get("last_selected_root") or guichi.SHELL_DIR
        if not os.path.isdir(initial_dir):
            initial_dir = guichi.SHELL_DIR

        root_path = filedialog.askdirectory(
            parent=self.root,
            title=f"Select Guichi root to scan (style {scan_style})",
            initialdir=initial_dir,
        )
        if not root_path:
            return

        result, merge_actions = guichi.action_discover(
            self.config, self.registry, root=root_path, scan_style=scan_style,
        )

        self.refresh_sidebar()

        if result.get("scan_errors"):
            err_text = "\n".join(result["scan_errors"])
            messagebox.showerror("Scan errors", err_text, parent=self.root)
            self.set_status(f"discover: {len(result['scan_errors'])} error(s)")
        else:
            found = len(result.get("findings", []))
            added = sum(1 for a in merge_actions if a["action"] in ("added", "added_no_id"))
            updated = sum(1 for a in merge_actions if a["action"] == "updated")
            self.set_status(
                f"discovered {found} pack(s) in {root_path} "
                f"({added} new, {updated} updated)"
            )

    def _on_rebuild(self):
        """Rebuild the registry by re-walking all known source paths."""
        actions = guichi.action_rebuild(self.config, self.registry)
        self.refresh_sidebar()

        refreshed = sum(1 for a in actions if a["action"] == "refreshed")
        unavail = sum(1 for a in actions if a["action"] == "marked_unavailable")
        self.set_status(
            f"rebuild complete: {refreshed} refreshed, {unavail} unavailable"
        )

    def _on_discover_sidewindows(self):
        """Scan a directory for chiside_* sidewindow packs."""
        root = filedialog.askdirectory(
            title="Select root to scan for chiside_* folders",
            parent=self.root,
        )
        if not root:
            return
        result, _ = guichi.action_discover_sidewindows(self.config, self.sw_registry, root=root)
        self.sw_registry = sidewindow_registry.load_registry(guichi.SIDEWINDOW_REGISTRY_PATH)
        found = sum(1 for sw in self.sw_registry.get("sidewindows", []) if sw.get("status") == "ok")
        self._rebuild_sidepack_hotbar()
        errors = result.get("scan_errors", [])
        if errors:
            self.set_status(f"sidewindow scan error: {errors[0]}")
        else:
            self.set_status(f"sidewindow discovery done — {found} available")

    # ── Report viewer ───────────────────────────────────────

    def _on_report(self):
        """Show the full discovery report in a viewer window."""
        report_text = guichi.action_report(
            self.registry,
            include_hidden=self.show_hidden.get(),
        )
        self._open_report_window("Discovery Report", report_text)

    def _on_problems_report(self):
        """Show the problems-only report in a viewer window."""
        report_text = guichi.action_report(
            self.registry,
            problems_only=True,
            include_hidden=self.show_hidden.get(),
        )
        self._open_report_window("Problems Report", report_text)

    def _open_report_window(self, title, report_text):
        """Open a top-level window displaying a copyable text report."""
        win = tk.Toplevel(self.root)
        win.title(f"Guichi \u2014 {title}")
        win.geometry("700x500")
        win.minsize(400, 300)

        text_frame = tk.Frame(win)
        text_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL)
        text_widget = tk.Text(
            text_frame, wrap=tk.WORD, font=INFO_VALUE_FONT,
            yscrollcommand=scrollbar.set,
        )
        scrollbar.configure(command=text_widget.yview)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        text_widget.insert(tk.END, report_text)
        text_widget.configure(state=tk.DISABLED)

        btn_frame = tk.Frame(win, pady=6, padx=6)
        btn_frame.pack(fill=tk.X)

        def copy_report():
            win.clipboard_clear()
            win.clipboard_append(report_text)
            copy_btn.configure(text="copied")
            win.after(1500, lambda: copy_btn.configure(text="Copy to clipboard"))

        copy_btn = tk.Button(btn_frame, text="Copy to clipboard", command=copy_report)
        copy_btn.pack(side=tk.LEFT)

        tk.Button(btn_frame, text="Close", command=win.destroy).pack(side=tk.RIGHT)

        self.set_status(f"opened: {title}")


# ── Remove dialog ───────────────────────────────────────────

class _RemoveDialog(tk.Toplevel):
    """Modal dialog for the three-choice remove/hide action."""

    def __init__(self, parent, pack_id, source_path):
        super().__init__(parent)
        self.title("Remove / Hide pack")
        self.resizable(False, False)
        self.result = None

        self.transient(parent)
        self.grab_set()

        frame = tk.Frame(self, padx=16, pady=12)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            frame, text=f"Pack: {pack_id}",
            font=("TkDefaultFont", 11, "bold"), anchor=tk.W,
        ).pack(fill=tk.X)

        tk.Label(
            frame, text=source_path,
            font=INFO_VALUE_FONT, anchor=tk.W, fg="#888888",
        ).pack(fill=tk.X, pady=(0, 12))

        choices = [
            (1, "Remove from shell list only"),
            (2, "Remove and forget saved state"),
            (3, "Hide instead"),
        ]

        for num, label in choices:
            tk.Button(
                frame, text=label, anchor=tk.W, padx=8, pady=4,
                command=lambda n=num: self._choose(n),
            ).pack(fill=tk.X, pady=2)

        tk.Button(
            frame, text="Cancel", padx=8, pady=4,
            command=self._cancel,
        ).pack(fill=tk.X, pady=(8, 0))

        self.update_idletasks()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_x()
        py = parent.winfo_y()
        w = self.winfo_width()
        h = self.winfo_height()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        self.geometry(f"+{x}+{y}")

        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def _choose(self, choice):
        self.result = choice
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()

    @classmethod
    def ask(cls, parent, pack_id, source_path):
        dlg = cls(parent, pack_id, source_path)
        dlg.wait_window()
        return dlg.result


# ── Class chooser dialog ────────────────────────────────────

class _ClassChooserDialog(tk.Toplevel):
    """
    Modal dialog for choosing a class from a .py file
    when multiple classes are found.
    Returns the chosen class name or None if cancelled.
    """

    def __init__(self, parent, file_path, class_names):
        super().__init__(parent)
        self.title("Choose class")
        self.resizable(False, False)
        self.result = None

        self.transient(parent)
        self.grab_set()

        frame = tk.Frame(self, padx=16, pady=12)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            frame, text=os.path.basename(file_path),
            font=("TkDefaultFont", 11, "bold"), anchor=tk.W,
        ).pack(fill=tk.X)

        tk.Label(
            frame, text=f"{len(class_names)} classes found \u2014 choose one:",
            anchor=tk.W,
        ).pack(fill=tk.X, pady=(0, 8))

        for name in class_names:
            tk.Button(
                frame, text=name, anchor=tk.W, padx=8, pady=4,
                command=lambda n=name: self._choose(n),
            ).pack(fill=tk.X, pady=2)

        tk.Button(
            frame, text="Cancel", padx=8, pady=4,
            command=self._cancel,
        ).pack(fill=tk.X, pady=(8, 0))

        self.update_idletasks()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_x()
        py = parent.winfo_y()
        w = self.winfo_width()
        h = self.winfo_height()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        self.geometry(f"+{x}+{y}")

        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def _choose(self, name):
        self.result = name
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()

    @classmethod
    def ask(cls, parent, file_path, class_names):
        dlg = cls(parent, file_path, class_names)
        dlg.wait_window()
        return dlg.result


# ── Launch function (called from guichi.py) ─────────────────

def launch():
    """Create and run the GUI shell."""
    root = tk.Tk()
    app = GuichiShell(root)
    root.mainloop()


if __name__ == "__main__":
    launch()
