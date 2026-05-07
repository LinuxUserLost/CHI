"""
page_network_control / network_control_page.py
──────────────────────────────────────────────────────────────────────────────
Network Control page for pagepack_chilos.

Design goals:
    - keep the interaction simpler and quieter than terminal_session
    - reuse the shared linuxcommands/ JSON library shape
    - keep a visible terminal-style output pane so command flow is teachable
    - never inspect system WireGuard config locations directly
"""

from __future__ import annotations

import datetime
import json
import os
import queue
import re
import shlex
import shutil
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from gui_files import interaction_support


_DEFAULT_PAGE_THEME = {
    "app_bg": "#1e1e1e",
    "content_bg": "#1e1e1e",
    "panel_bg": "#2e2e2e",
    "sidebar_bg": "#252525",
    "text_main": "#d0d0d0",
    "text_muted": "#909090",
    "text_active": "#f0f0f0",
    "text_on_accent": "#ffffff",
    "button_bg": "#333333",
    "button_hover": "#444444",
    "button_active": "#ffffff",
    "button_disabled": "#666666",
    "accent": "#4ea0ff",
    "border": "#4a4a4a",
}

_ANSI_CSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
_ANSI_OSC_RE = re.compile(r"\x1B\][^\x07\x1B]*(?:\x07|\x1B\\)")
_ANSI_OTHER_RE = re.compile(r"\x1B[@-Z\\-_]")


def _bind_scroll(widget):
    interaction_support.bind_wheel_scroll(widget)


def _bind_text_shortcuts(widget):
    if isinstance(widget, tk.Text):
        interaction_support.setup_text_widget(widget, wheel=False)
    else:
        interaction_support.setup_entry_widget(widget)


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _strip_ansi(text: str) -> str:
    text = _ANSI_OSC_RE.sub("", text)
    text = _ANSI_CSI_RE.sub("", text)
    text = _ANSI_OTHER_RE.sub("", text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _find_project_root() -> str:
    here = Path(__file__).resolve()
    for candidate in [here.parent, *here.parents]:
        if (candidate / "guichi.py").exists():
            return str(candidate)
    try:
        return os.getcwd()
    except Exception:
        return os.path.expanduser("~")


def _find_pack_root() -> str:
    here = Path(__file__).resolve()
    for candidate in [here.parent, *here.parents]:
        if (candidate / "module_manifest.json").exists() and (candidate / "pages.json").exists():
            return str(candidate)
    return str(here.parent.parent)


def _default_config() -> dict:
    return {
        "next_profile_id": 1,
        "profiles": {"1m": [], "1a": []},
        "active_profile": None,
        "health": {
            "latest_speed_test": None,
            "latest_latency": None,
            "latest_public_ip": None,
            "last_report_path": None,
        },
    }


class PageNetworkControl:
    PAGE_NAME = "network_control"

    def __init__(self, parent, app=None, page_key="", page_folder="", *args, **kwargs):
        app = kwargs.pop("controller", app)
        page_key = kwargs.pop("page_context", page_key)
        page_folder = kwargs.pop("page_folder", page_folder)

        self.parent = parent
        self.app = app
        self.page_key = page_key
        self.page_folder = page_folder
        self.guichi_page_theme = None
        self._theme_tokens = dict(_DEFAULT_PAGE_THEME)
        self._style_prefix = f"NetworkControl.{id(self)}"

        self.pack_root = ""
        self.linuxcommands_dir = ""
        self.network_reports_dir = ""
        self._config_path = Path(__file__).with_name("page_network_control_config.json")
        self._config = _default_config()
        self._profile_lists = {"1m": [], "1a": []}
        self._active_profile = None
        self._health_state = dict(_default_config()["health"])
        self._selected_category = None
        self._runner_thread = None
        self._runner_proc = None
        self._runner_lock = threading.Lock()
        self._runner_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._runner_after_id = None
        self._runner_busy = False
        self._current_action = None
        self._runner_target = "wireguard"
        self._runner_output_chunks: list[str] = []

        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)

        self._build_top_bar()
        self._build_notebook()
        self._build_status_bar()
        self._apply_theme()

        self.frame.after(100, self._auto_find_root)

    def _embed_into_parent(self, parent=None):
        container = parent or self.parent
        try:
            if container is not None and self.frame.master is not container:
                self.frame.destroy()
                self.parent = container
                self.frame = ttk.Frame(container)
                self.frame.columnconfigure(0, weight=1)
                self.frame.rowconfigure(1, weight=1)
                self._build_top_bar()
                self._build_notebook()
                self._build_status_bar()
                self._apply_theme()
                self.frame.after(100, self._auto_find_root)
        except Exception:
            pass
        try:
            self.frame.pack(fill="both", expand=True)
        except Exception:
            try:
                self.frame.grid(row=0, column=0, sticky="nsew")
            except Exception:
                pass
        return self.frame

    def build(self, parent=None):
        return self._embed_into_parent(parent)

    def create_widgets(self, parent=None):
        return self._embed_into_parent(parent)

    def mount(self, parent=None):
        return self._embed_into_parent(parent)

    def render(self, parent=None):
        return self._embed_into_parent(parent)

    def _build_top_bar(self):
        bar = ttk.Frame(self.frame, padding=(4, 4))
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(99, weight=1)
        self._top_bar = bar

        ttk.Button(bar, text="Auto-Find Root", width=15, command=self._auto_find_root).grid(
            row=0, column=0, padx=2
        )
        ttk.Button(bar, text="Choose Root…", width=13, command=self._choose_root).grid(
            row=0, column=1, padx=2
        )
        self._btn_stop_runner = ttk.Button(
            bar, text="Stop Running", width=13, command=self._stop_running, state="disabled"
        )
        self._btn_stop_runner.grid(row=0, column=2, padx=(10, 2))

        self._runner_status_var = tk.StringVar(value="runner: idle")
        self._runner_status_label = ttk.Label(
            bar, textvariable=self._runner_status_var, foreground="#666", font=("", 8), anchor="w"
        )
        self._runner_status_label.grid(row=0, column=3, sticky="w", padx=(8, 4))

        self._root_var = tk.StringVar(value="Root: (not set)")
        self._root_label = ttk.Label(
            bar, textvariable=self._root_var, foreground="#666", font=("", 8), anchor="w"
        )
        self._root_label.grid(row=0, column=99, sticky="ew", padx=8)

    def _build_notebook(self):
        workspace = ttk.Frame(self.frame)
        workspace.grid(row=1, column=0, sticky="nsew", padx=4, pady=(2, 0))
        workspace.columnconfigure(0, weight=1)
        workspace.rowconfigure(0, weight=1)
        self._workspace = workspace

        self._notebook = ttk.Notebook(workspace)
        self._notebook.grid(row=0, column=0, sticky="nsew")

        wireguard_tab = ttk.Frame(self._notebook, padding=8)
        wireguard_tab.columnconfigure(0, weight=1)
        wireguard_tab.rowconfigure(3, weight=1)
        self._notebook.add(wireguard_tab, text="WireGuard")
        self._build_wireguard_tab(wireguard_tab)

        speed_tab = ttk.Frame(self._notebook, padding=8)
        speed_tab.columnconfigure(0, weight=1)
        speed_tab.rowconfigure(3, weight=1)
        self._notebook.add(speed_tab, text="Speed Test")
        self._build_speed_test_tab(speed_tab)

    def _build_wireguard_tab(self, parent):
        summary = ttk.LabelFrame(parent, text="WireGuard Summary", padding=(8, 6))
        summary.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        summary.columnconfigure(1, weight=1)

        self._active_var = tk.StringVar(value="Active: (none)")
        self._selected_var = tk.StringVar(value="Selected: (none)")
        self._note_var = tk.StringVar(
            value="Profiles are loaded manually. This page does not inspect WireGuard config directories."
        )

        ttk.Label(summary, text="Local Active:", font=("", 9, "bold")).grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        ttk.Label(summary, textvariable=self._active_var).grid(row=0, column=1, sticky="w")
        ttk.Label(summary, text="Current Selection:", font=("", 9, "bold")).grid(
            row=1, column=0, sticky="w", padx=(0, 6)
        )
        ttk.Label(summary, textvariable=self._selected_var).grid(row=1, column=1, sticky="w")
        ttk.Label(summary, textvariable=self._note_var, foreground="#777").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )

        body = ttk.PanedWindow(parent, orient="horizontal")
        body.grid(row=1, column=0, sticky="nsew", pady=(0, 6))
        parent.rowconfigure(1, weight=1)

        self._profile_lbs = {}
        body.add(self._build_profile_pane(body, "1m", "1m Profiles"), weight=1)
        body.add(self._build_profile_pane(body, "1a", "1a Profiles"), weight=1)

        actions = ttk.LabelFrame(parent, text="Actions", padding=(8, 6))
        actions.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        self._btn_show_status = ttk.Button(actions, text="Show Status", width=14, command=self._run_show_status)
        self._btn_show_status.pack(side="left", padx=2)
        self._btn_apply_selected = ttk.Button(
            actions, text="Apply Selected", width=16, command=self._run_apply_selected
        )
        self._btn_apply_selected.pack(side="left", padx=2)
        self._btn_disconnect_active = ttk.Button(
            actions, text="Disconnect Active", width=18, command=self._run_disconnect_active
        )
        self._btn_disconnect_active.pack(side="left", padx=2)

        bottom = ttk.PanedWindow(parent, orient="vertical")
        bottom.grid(row=3, column=0, sticky="nsew")
        parent.rowconfigure(3, weight=1)

        preview_frame = ttk.LabelFrame(bottom, text="Command Preview", padding=4)
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        mono = ("Consolas", 10) if os.name == "nt" else ("monospace", 10)
        self._preview_text = tk.Text(
            preview_frame, wrap="word", height=5, state="disabled", relief="flat", borderwidth=0, font=mono
        )
        self._preview_text.grid(row=0, column=0, sticky="nsew")
        _bind_scroll(self._preview_text)
        _bind_text_shortcuts(self._preview_text)
        bottom.add(preview_frame, weight=1)

        output_frame = ttk.LabelFrame(bottom, text="Terminal Output", padding=4)
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)
        self._output_text = tk.Text(
            output_frame, wrap="word", state="disabled", relief="flat", borderwidth=0, font=mono, padx=8, pady=6
        )
        output_scroll = ttk.Scrollbar(output_frame, orient="vertical", command=self._output_text.yview)
        self._output_text.configure(yscrollcommand=output_scroll.set)
        self._output_text.grid(row=0, column=0, sticky="nsew")
        output_scroll.grid(row=0, column=1, sticky="ns")
        _bind_scroll(self._output_text)
        _bind_text_shortcuts(self._output_text)
        self._output_text.tag_configure("cmd_header", foreground="#2563eb")
        self._output_text.tag_configure("cmd_text", foreground="#16a34a")
        self._output_text.tag_configure("terminal_output", foreground="#d0d0d0")
        self._output_text.tag_configure("runner_marker", foreground="#909090")
        bottom.add(output_frame, weight=3)

    def _build_speed_test_tab(self, parent):
        summary = ttk.LabelFrame(parent, text="Connection Health Summary", padding=(8, 6))
        summary.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        summary.columnconfigure(1, weight=1)

        self._speed_latest_var = tk.StringVar(value="(not run yet)")
        self._latency_latest_var = tk.StringVar(value="(not run yet)")
        self._public_ip_latest_var = tk.StringVar(value="(not run yet)")
        self._last_report_var = tk.StringVar(value="(none saved)")

        rows = [
            ("Latest Speed:", self._speed_latest_var),
            ("Latest Latency:", self._latency_latest_var),
            ("Public IP / Provider:", self._public_ip_latest_var),
            ("Last Saved Report:", self._last_report_var),
        ]
        for idx, (label, var) in enumerate(rows):
            ttk.Label(summary, text=label, font=("", 9, "bold")).grid(
                row=idx, column=0, sticky="w", padx=(0, 6), pady=(0, 2)
            )
            ttk.Label(summary, textvariable=var).grid(row=idx, column=1, sticky="w", pady=(0, 2))

        actions = ttk.LabelFrame(parent, text="Actions", padding=(8, 6))
        actions.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self._btn_speed_test = ttk.Button(actions, text="Run Speed Test", width=16, command=self._run_speed_test)
        self._btn_speed_test.pack(side="left", padx=2)
        self._btn_latency_check = ttk.Button(
            actions, text="Run Latency Check", width=18, command=self._run_latency_check
        )
        self._btn_latency_check.pack(side="left", padx=2)
        self._btn_public_ip = ttk.Button(
            actions, text="Show Public IP / Provider", width=24, command=self._run_public_ip_check
        )
        self._btn_public_ip.pack(side="left", padx=2)
        self._btn_save_report = ttk.Button(actions, text="Save Report", width=14, command=self._save_speed_report)
        self._btn_save_report.pack(side="left", padx=2)

        body = ttk.PanedWindow(parent, orient="horizontal")
        body.grid(row=2, column=0, sticky="nsew", pady=(0, 6))

        reports = ttk.LabelFrame(body, text="Saved Reports", padding=6)
        reports.columnconfigure(0, weight=1)
        reports.rowconfigure(1, weight=1)
        report_btns = ttk.Frame(reports)
        report_btns.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        ttk.Button(report_btns, text="Refresh", width=9, command=self._refresh_speed_report_list).pack(
            side="left", padx=2
        )
        lb_frame = ttk.Frame(reports)
        lb_frame.grid(row=1, column=0, sticky="nsew")
        lb_frame.columnconfigure(0, weight=1)
        lb_frame.rowconfigure(0, weight=1)
        self._speed_report_lb = tk.Listbox(lb_frame, exportselection=False, activestyle="dotbox", height=8)
        report_sb = ttk.Scrollbar(lb_frame, orient="vertical", command=self._speed_report_lb.yview)
        self._speed_report_lb.configure(yscrollcommand=report_sb.set)
        self._speed_report_lb.grid(row=0, column=0, sticky="nsew")
        report_sb.grid(row=0, column=1, sticky="ns")
        self._speed_report_lb.bind("<<ListboxSelect>>", self._on_speed_report_select)
        _bind_scroll(self._speed_report_lb)
        self._speed_report_path_var = tk.StringVar(value="No saved report selected.")
        ttk.Label(reports, textvariable=self._speed_report_path_var, foreground="#777", wraplength=280).grid(
            row=2, column=0, sticky="ew", pady=(6, 0)
        )
        body.add(reports, weight=1)

        bottom = ttk.PanedWindow(body, orient="vertical")
        body.add(bottom, weight=3)

        preview_frame = ttk.LabelFrame(bottom, text="Command Preview", padding=4)
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        mono = ("Consolas", 10) if os.name == "nt" else ("monospace", 10)
        self._speed_preview_text = tk.Text(
            preview_frame, wrap="word", height=5, state="disabled", relief="flat", borderwidth=0, font=mono
        )
        self._speed_preview_text.grid(row=0, column=0, sticky="nsew")
        _bind_scroll(self._speed_preview_text)
        _bind_text_shortcuts(self._speed_preview_text)
        bottom.add(preview_frame, weight=1)

        output_frame = ttk.LabelFrame(bottom, text="Terminal Output", padding=4)
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)
        self._speed_output_text = tk.Text(
            output_frame, wrap="word", state="disabled", relief="flat", borderwidth=0, font=mono, padx=8, pady=6
        )
        output_scroll = ttk.Scrollbar(output_frame, orient="vertical", command=self._speed_output_text.yview)
        self._speed_output_text.configure(yscrollcommand=output_scroll.set)
        self._speed_output_text.grid(row=0, column=0, sticky="nsew")
        output_scroll.grid(row=0, column=1, sticky="ns")
        _bind_scroll(self._speed_output_text)
        _bind_text_shortcuts(self._speed_output_text)
        self._speed_output_text.tag_configure("cmd_header", foreground="#2563eb")
        self._speed_output_text.tag_configure("cmd_text", foreground="#16a34a")
        self._speed_output_text.tag_configure("terminal_output", foreground="#d0d0d0")
        self._speed_output_text.tag_configure("runner_marker", foreground="#909090")
        bottom.add(output_frame, weight=3)

    def _build_profile_pane(self, parent, category, title):
        outer = ttk.LabelFrame(parent, text=title, padding=6)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        buttons = ttk.Frame(outer)
        buttons.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        ttk.Button(buttons, text="Add Files…", width=11, command=lambda c=category: self._add_files(c)).pack(
            side="left", padx=2
        )
        ttk.Button(
            buttons, text="Rename…", width=9, command=lambda c=category: self._rename_selected(c)
        ).pack(side="left", padx=2)
        ttk.Button(
            buttons, text="Remove", width=8, command=lambda c=category: self._remove_selected(c)
        ).pack(side="left", padx=2)
        ttk.Button(buttons, text="▲", width=3, command=lambda c=category: self._move_selected(c, -1)).pack(
            side="left", padx=2
        )
        ttk.Button(buttons, text="▼", width=3, command=lambda c=category: self._move_selected(c, 1)).pack(
            side="left", padx=2
        )

        list_frame = ttk.Frame(outer)
        list_frame.grid(row=1, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        lb = tk.Listbox(list_frame, exportselection=False, activestyle="dotbox")
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        lb.bind("<<ListboxSelect>>", lambda _e, c=category: self._on_profile_select(c))
        _bind_scroll(lb)
        self._profile_lbs[category] = lb

        detail_var = tk.StringVar(value="No profile selected.")
        setattr(self, f"_{category}_detail_var", detail_var)
        ttk.Label(outer, textvariable=detail_var, foreground="#777", wraplength=280).grid(
            row=2, column=0, sticky="ew", pady=(6, 0)
        )
        return outer

    def _build_status_bar(self):
        bar = ttk.Frame(self.frame, padding=(4, 2))
        bar.grid(row=2, column=0, sticky="ew")
        bar.columnconfigure(0, weight=1)
        self._status_var = tk.StringVar(value="Ready")
        self._status_label = ttk.Label(bar, textvariable=self._status_var, anchor="w", foreground="#666")
        self._status_label.grid(row=0, column=0, sticky="ew")

    def _set_status(self, text):
        self._status_var.set(text)

    def set_guichi_page_theme(self, context):
        self.guichi_page_theme = context
        tokens = dict(_DEFAULT_PAGE_THEME)
        tokens.update((context or {}).get("tokens") or {})
        self._theme_tokens = tokens
        self._apply_theme()

    def _apply_theme(self):
        tokens = self._theme_tokens
        try:
            style = ttk.Style(self.frame)
            style.configure(f"{self._style_prefix}.TFrame", background=tokens["content_bg"])
            style.configure(f"{self._style_prefix}.TLabelframe", background=tokens["panel_bg"], bordercolor=tokens["border"])
            style.configure(
                f"{self._style_prefix}.TLabelframe.Label",
                background=tokens["panel_bg"],
                foreground=tokens["text_main"],
            )
            style.configure(f"{self._style_prefix}.TLabel", background=tokens["content_bg"], foreground=tokens["text_main"])
            style.configure(
                f"{self._style_prefix}.Muted.TLabel",
                background=tokens["content_bg"],
                foreground=tokens["text_muted"],
            )
            style.configure(f"{self._style_prefix}.TButton", background=tokens["button_bg"], foreground=tokens["text_main"])
            style.map(
                f"{self._style_prefix}.TButton",
                background=[("active", tokens["button_hover"])],
                foreground=[("active", tokens["text_active"]), ("disabled", tokens["button_disabled"])],
            )
            style.configure(f"{self._style_prefix}.TNotebook", background=tokens["content_bg"], bordercolor=tokens["border"])
            style.configure(
                f"{self._style_prefix}.TNotebook.Tab",
                background=tokens["button_bg"],
                foreground=tokens["text_main"],
            )
            style.map(
                f"{self._style_prefix}.TNotebook.Tab",
                background=[("selected", tokens["panel_bg"]), ("active", tokens["button_hover"])],
                foreground=[("selected", tokens["text_active"])],
            )
            if hasattr(self, "_notebook"):
                self._notebook.configure(style=f"{self._style_prefix}.TNotebook")
        except Exception:
            pass

        self._apply_ttk_theme_tree(self.frame)
        for widget in [
            getattr(self, "_output_text", None),
            getattr(self, "_preview_text", None),
            getattr(self, "_speed_output_text", None),
            getattr(self, "_speed_preview_text", None),
        ]:
            if widget is None:
                continue
            try:
                widget.configure(
                    background=tokens["panel_bg"],
                    foreground=tokens["text_main"],
                    insertbackground=tokens["text_main"],
                    selectbackground=tokens["accent"],
                    selectforeground=tokens["text_on_accent"],
                    highlightbackground=tokens["border"],
                    highlightcolor=tokens["accent"],
                )
            except Exception:
                pass

        for widget in self._profile_lbs.values():
            try:
                widget.configure(
                    background=tokens["panel_bg"],
                    foreground=tokens["text_main"],
                    selectbackground=tokens["accent"],
                    selectforeground=tokens["text_on_accent"],
                    highlightbackground=tokens["border"],
                    highlightcolor=tokens["accent"],
                )
            except Exception:
                pass

        for widget in [getattr(self, "_speed_report_lb", None)]:
            if widget is None:
                continue
            try:
                widget.configure(
                    background=tokens["panel_bg"],
                    foreground=tokens["text_main"],
                    selectbackground=tokens["accent"],
                    selectforeground=tokens["text_on_accent"],
                    highlightbackground=tokens["border"],
                    highlightcolor=tokens["accent"],
                )
            except Exception:
                pass

        for widget in [getattr(self, "_runner_status_label", None), getattr(self, "_root_label", None), getattr(self, "_status_label", None)]:
            if widget is None:
                continue
            try:
                widget.configure(style=f"{self._style_prefix}.Muted.TLabel")
            except Exception:
                pass

    def _apply_ttk_theme_tree(self, widget):
        for child in widget.winfo_children():
            try:
                if isinstance(child, ttk.LabelFrame):
                    child.configure(style=f"{self._style_prefix}.TLabelframe")
                elif isinstance(child, ttk.Button):
                    child.configure(style=f"{self._style_prefix}.TButton")
                elif isinstance(child, ttk.Label):
                    child.configure(style=f"{self._style_prefix}.TLabel")
                elif isinstance(child, ttk.Frame):
                    child.configure(style=f"{self._style_prefix}.TFrame")
            except Exception:
                pass
            self._apply_ttk_theme_tree(child)

    def _auto_find_root(self):
        guessed = _find_pack_root()
        if os.path.isdir(guessed):
            self._set_root(guessed)
            return
        self._set_status("Pack root not found — use Choose Root.")

    def _choose_root(self):
        directory = filedialog.askdirectory(title="Select chi_los pack root")
        if directory:
            self._set_root(directory)

    def _set_root(self, pack_path):
        self.pack_root = pack_path
        self.linuxcommands_dir = os.path.join(pack_path, "linuxcommands")
        self.network_reports_dir = os.path.join(pack_path, "network_reports")
        os.makedirs(self.linuxcommands_dir, exist_ok=True)
        os.makedirs(self.network_reports_dir, exist_ok=True)
        short = pack_path if len(pack_path) <= 60 else "…" + pack_path[-57:]
        self._root_var.set(f"Root: {short}")
        self._load_config()
        self._refresh_all_lists()
        self._refresh_summary()
        self._preview_show_status()
        self._refresh_speed_summary()
        self._refresh_speed_report_list()
        self._preview_speed_test()
        self._set_status(f"Root: {pack_path}")

    def _load_config(self):
        config = _default_config()
        try:
            if self._config_path.exists():
                loaded = json.loads(self._config_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    config.update(loaded)
        except Exception:
            pass
        profiles = config.get("profiles") or {}
        self._profile_lists = {
            "1m": list(profiles.get("1m") or []),
            "1a": list(profiles.get("1a") or []),
        }
        self._active_profile = config.get("active_profile")
        health = config.get("health") or {}
        merged_health = dict(_default_config()["health"])
        merged_health.update(health)
        self._health_state = merged_health
        self._config = config

    def _save_config(self):
        payload = {
            "next_profile_id": self._config.get("next_profile_id", 1),
            "profiles": self._profile_lists,
            "active_profile": self._active_profile,
            "health": self._health_state,
        }
        self._config = payload
        try:
            self._config_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception as exc:
            self._set_status(f"Could not save page config: {exc}")

    def _next_profile_id(self) -> str:
        next_id = int(self._config.get("next_profile_id", 1))
        self._config["next_profile_id"] = next_id + 1
        return f"profile_{next_id}"

    def _profile_display(self, profile):
        nickname = (profile.get("nickname") or "").strip() or Path(profile.get("path", "")).stem or "unnamed"
        filename = Path(profile.get("path", "")).name or "(missing)"
        active = self._active_profile
        is_active = bool(active and active.get("category") == profile.get("category") and active.get("path") == profile.get("path"))
        marker = "* " if is_active else "  "
        return f"{marker}{nickname} [{filename}]"

    def _refresh_all_lists(self):
        for category in ("1m", "1a"):
            self._refresh_profile_list(category)

    def _refresh_profile_list(self, category):
        lb = self._profile_lbs[category]
        current = lb.curselection()
        current_idx = current[0] if current else None
        lb.delete(0, "end")
        for profile in self._profile_lists[category]:
            lb.insert("end", self._profile_display(profile))
        if current_idx is not None and current_idx < lb.size():
            lb.selection_set(current_idx)
        self._update_detail(category)

    def _update_detail(self, category):
        lb = self._profile_lbs[category]
        var = getattr(self, f"_{category}_detail_var")
        selection = lb.curselection()
        if not selection:
            var.set("No profile selected.")
            return
        profile = self._profile_lists[category][selection[0]]
        nickname = profile.get("nickname") or Path(profile.get("path", "")).stem
        var.set(f"{nickname} → {profile.get('path', '')}")

    def _on_profile_select(self, category):
        other = "1a" if category == "1m" else "1m"
        self._profile_lbs[other].selection_clear(0, "end")
        self._selected_category = category
        self._update_detail(category)
        self._update_detail(other)
        self._refresh_summary()
        self._preview_apply_selected()

    def _selected_profile(self):
        for category in ("1m", "1a"):
            selection = self._profile_lbs[category].curselection()
            if selection:
                idx = selection[0]
                if idx < len(self._profile_lists[category]):
                    return category, self._profile_lists[category][idx]
        return None, None

    def _refresh_summary(self):
        if self._active_profile:
            active_label = self._active_profile.get("nickname") or Path(self._active_profile.get("path", "")).stem
            self._active_var.set(
                f"{self._active_profile.get('category', '?')} → {active_label} [{Path(self._active_profile.get('path', '')).name}]"
            )
        else:
            self._active_var.set("(none)")

        category, profile = self._selected_profile()
        if profile:
            selected_label = profile.get("nickname") or Path(profile.get("path", "")).stem
            self._selected_var.set(f"{category} → {selected_label} [{Path(profile.get('path', '')).name}]")
        else:
            self._selected_var.set("(none)")

    def _add_files(self, category):
        paths = filedialog.askopenfilenames(title=f"Select {category} profile files")
        if not paths:
            return
        existing = {item.get("path") for item in self._profile_lists[category]}
        added = 0
        for path in paths:
            if path in existing:
                continue
            self._profile_lists[category].append(
                {
                    "id": self._next_profile_id(),
                    "category": category,
                    "path": path,
                    "nickname": Path(path).stem,
                }
            )
            existing.add(path)
            added += 1
        self._save_config()
        self._refresh_profile_list(category)
        self._set_status(f"Added {added} profile(s) to {category}.")

    def _rename_selected(self, category):
        selection = self._profile_lbs[category].curselection()
        if not selection:
            self._set_status(f"Select a {category} profile first.")
            return
        idx = selection[0]
        profile = self._profile_lists[category][idx]
        current = profile.get("nickname") or Path(profile.get("path", "")).stem
        new_name = simpledialog.askstring("Rename Nickname", "Display nickname:", initialvalue=current, parent=self.frame)
        if new_name is None:
            return
        cleaned = new_name.strip()
        if not cleaned:
            self._set_status("Nickname cannot be empty.")
            return
        profile["nickname"] = cleaned
        if self._active_profile and self._active_profile.get("category") == category and self._active_profile.get("path") == profile.get("path"):
            self._active_profile["nickname"] = cleaned
        self._save_config()
        self._refresh_profile_list(category)
        self._refresh_summary()
        self._set_status(f"Updated nickname for {category}.")

    def _remove_selected(self, category):
        selection = self._profile_lbs[category].curselection()
        if not selection:
            self._set_status(f"Select a {category} profile first.")
            return
        idx = selection[0]
        profile = self._profile_lists[category].pop(idx)
        self._save_config()
        self._refresh_profile_list(category)
        self._refresh_summary()
        self._preview_show_status()
        self._set_status(f"Removed {Path(profile.get('path', '')).name} from {category}.")

    def _move_selected(self, category, direction):
        selection = self._profile_lbs[category].curselection()
        if not selection:
            self._set_status(f"Select a {category} profile first.")
            return
        idx = selection[0]
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self._profile_lists[category]):
            return
        items = self._profile_lists[category]
        items[idx], items[new_idx] = items[new_idx], items[idx]
        self._save_config()
        self._refresh_profile_list(category)
        self._profile_lbs[category].selection_set(new_idx)
        self._on_profile_select(category)

    def _command_record_path(self, relative_path):
        return os.path.join(self.linuxcommands_dir, relative_path)

    def _load_command_record(self, relative_path):
        if not self.linuxcommands_dir:
            raise RuntimeError("Pack root is not set.")
        path = self._command_record_path(relative_path)
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def _render_command(self, command_text, replacements):
        rendered = command_text
        for key, value in replacements.items():
            rendered = rendered.replace("{{" + key + "}}", shlex.quote(str(value)))
        return rendered

    def _preview_widget(self, target):
        return self._speed_preview_text if target == "speed" else self._preview_text

    def _output_widget(self, target):
        return self._speed_output_text if target == "speed" else self._output_text

    def _set_preview(self, command, label, target="wireguard"):
        self._current_action = label
        widget = self._preview_widget(target)
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", f"# {label}\n\n{command}")
        widget.configure(state="disabled")

    def _preview_show_status(self):
        try:
            record = self._load_command_record("network/WireGuard_Show_Status.json")
        except Exception as exc:
            self._set_status(f"Could not load status command: {exc}")
            return None
        command = record.get("command", "").strip()
        self._set_preview(command, record.get("title") or "Show Status", target="wireguard")
        return command

    def _preview_apply_selected(self):
        category, profile = self._selected_profile()
        if not profile:
            self._preview_show_status()
            return None, None
        try:
            record = self._load_command_record("network/WireGuard_Apply_Profile.json")
        except Exception as exc:
            self._set_status(f"Could not load apply command: {exc}")
            return None, None
        command = self._render_command(record.get("command", "").strip(), {"profile_path": profile.get("path", "")})
        self._set_preview(command, record.get("title") or "Apply Selected", target="wireguard")
        return category, profile

    def _preview_disconnect_active(self):
        if not self._active_profile:
            self._preview_show_status()
            return None
        try:
            record = self._load_command_record("network/WireGuard_Disconnect_Profile.json")
        except Exception as exc:
            self._set_status(f"Could not load disconnect command: {exc}")
            return None
        command = self._render_command(
            record.get("command", "").strip(), {"profile_path": self._active_profile.get("path", "")}
        )
        self._set_preview(command, record.get("title") or "Disconnect Active", target="wireguard")
        return self._active_profile

    def _append_output(self, text, tag=None, target="wireguard"):
        widget = self._output_widget(target)
        widget.configure(state="normal")
        if tag:
            start = widget.index("end")
            widget.insert("end", text)
            widget.tag_add(tag, start, "end")
        else:
            widget.insert("end", text)
        widget.configure(state="disabled")
        widget.see("end")

    def _set_runner_busy(self, busy):
        self._runner_busy = busy
        try:
            self._btn_stop_runner.configure(state="normal" if busy else "disabled")
            action_state = "disabled" if busy else "normal"
            self._btn_show_status.configure(state=action_state)
            self._btn_apply_selected.configure(state=action_state)
            self._btn_disconnect_active.configure(state=action_state)
            self._btn_speed_test.configure(state=action_state)
            self._btn_latency_check.configure(state=action_state)
            self._btn_public_ip.configure(state=action_state)
            self._btn_save_report.configure(state=action_state)
        except Exception:
            pass
        self._runner_status_var.set("runner: running" if busy else "runner: idle")

    def _run_show_status(self):
        command = self._preview_show_status()
        if command:
            self._run_command("show_status", command, success_payload=None, target="wireguard")

    def _run_apply_selected(self):
        category, profile = self._preview_apply_selected()
        if not profile:
            self._set_status("Select a profile first.")
            return
        command = self._preview_text.get("1.0", "end-1c").split("\n\n", 1)[1]
        payload = {
            "category": category,
            "path": profile.get("path"),
            "nickname": profile.get("nickname"),
        }
        self._run_command("apply_profile", command, success_payload=payload, target="wireguard")

    def _run_disconnect_active(self):
        active = self._preview_disconnect_active()
        if not active:
            self._set_status("No active profile is tracked yet.")
            return
        command = self._preview_text.get("1.0", "end-1c").split("\n\n", 1)[1]
        self._run_command("disconnect_profile", command, success_payload=None, target="wireguard")

    def _run_command(self, action_kind, command, success_payload, target="wireguard"):
        if self._runner_busy:
            self._set_status("Another command is already running.")
            return
        ts = _now_iso()
        self._runner_target = target
        self._runner_output_chunks = []
        self._append_output(f"\n## CMD [{ts}]\n\n", tag="cmd_header", target=target)
        self._append_output(f"```sh\n{command}\n```\n\n", tag="cmd_text", target=target)
        self._set_runner_busy(True)
        self._set_status(f"Running: {action_kind}")
        self._runner_queue = queue.Queue()
        self._runner_thread = threading.Thread(
            target=self._run_subprocess_thread,
            args=(action_kind, command, success_payload),
            daemon=True,
            name="network-control-runner",
        )
        self._runner_thread.start()
        self._schedule_runner_pump()

    def _run_subprocess_thread(self, action_kind, command, success_payload):
        try:
            proc = subprocess.Popen(
                ["bash", "-lc", command],
                cwd=_find_project_root(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as exc:
            self._runner_queue.put(("done", {"rc": -1, "error": str(exc), "action": action_kind, "payload": success_payload}))
            return

        with self._runner_lock:
            self._runner_proc = proc

        try:
            if proc.stdout is not None:
                for line in proc.stdout:
                    self._runner_queue.put(("data", _strip_ansi(line)))
            rc = proc.wait()
            self._runner_queue.put(("done", {"rc": rc, "error": "", "action": action_kind, "payload": success_payload}))
        finally:
            with self._runner_lock:
                self._runner_proc = None

    def _schedule_runner_pump(self):
        try:
            self._runner_after_id = self.frame.after(60, self._runner_pump)
        except Exception:
            self._runner_after_id = None

    def _runner_pump(self):
        done_payload = None
        try:
            while True:
                kind, payload = self._runner_queue.get_nowait()
                if kind == "data":
                    text = str(payload)
                    self._runner_output_chunks.append(text)
                    self._append_output(text, tag="terminal_output", target=self._runner_target)
                elif kind == "done":
                    done_payload = payload
        except queue.Empty:
            pass

        if done_payload is not None:
            rc = int(done_payload.get("rc", -1))
            raw_output = "".join(self._runner_output_chunks)
            if done_payload.get("error"):
                self._append_output(f"{done_payload['error']}\n", tag="terminal_output", target=self._runner_target)
            if rc == 0:
                self._append_output("\n--- exit 0 (success) ---\n\n", tag="runner_marker", target=self._runner_target)
                self._apply_success_effects(done_payload.get("action"), done_payload.get("payload"), raw_output)
                self._set_status(f"Completed: {done_payload.get('action')}")
            else:
                self._append_output(
                    f"\n--- exit {rc} (error) ---\n\n", tag="runner_marker", target=self._runner_target
                )
                self._set_status(f"Command failed with exit {rc}.")
            self._set_runner_busy(False)
            self._refresh_all_lists()
            self._refresh_summary()
            self._refresh_speed_summary()
            self._refresh_speed_report_list()
            return

        if self._runner_busy:
            self._runner_after_id = self.frame.after(60, self._runner_pump)
        else:
            self._runner_after_id = None

    def _apply_success_effects(self, action_kind, payload, raw_output):
        if action_kind == "apply_profile" and payload:
            self._active_profile = {
                "category": payload.get("category"),
                "path": payload.get("path"),
                "nickname": payload.get("nickname"),
            }
            self._save_config()
        elif action_kind == "disconnect_profile":
            self._active_profile = None
            self._save_config()
        elif action_kind == "speed_test":
            self._health_state["latest_speed_test"] = self._parse_speed_output(raw_output, payload or {})
            self._save_config()
        elif action_kind == "latency_check":
            self._health_state["latest_latency"] = self._parse_latency_output(raw_output)
            self._save_config()
        elif action_kind == "public_ip_check":
            self._health_state["latest_public_ip"] = self._parse_public_ip_output(raw_output)
            self._save_config()

    def _detect_speed_backend(self):
        candidates = [
            ("curl", "network/Speed_Test_Curl_Fallback.json", "curl"),
            ("wget", "network/Speed_Test_Wget_Fallback.json", "wget"),
            ("python3", "network/Speed_Test_Python_Fallback.json", "python3"),
        ]
        for executable, record_path, backend_id in candidates:
            if shutil.which(executable):
                return backend_id, record_path
        return None, None

    def _preview_speed_test(self):
        backend_id, record_path = self._detect_speed_backend()
        if not record_path:
            command = "printf 'No supported speed-test backend found. Install curl, wget, or ensure python3 is available.\\n'"
            self._set_preview(command, "Run Speed Test", target="speed")
            return None, None
        record = self._load_command_record(record_path)
        command = record.get("command", "").strip()
        self._set_preview(command, record.get("title") or "Run Speed Test", target="speed")
        return backend_id, command

    def _preview_latency_check(self):
        record = self._load_command_record("network/Latency_Check.json")
        command = record.get("command", "").strip()
        self._set_preview(command, record.get("title") or "Run Latency Check", target="speed")
        return command

    def _preview_public_ip(self):
        record = self._load_command_record("network/Public_IP_Provider_Check.json")
        command = record.get("command", "").strip()
        self._set_preview(command, record.get("title") or "Show Public IP / Provider", target="speed")
        return command

    def _run_speed_test(self):
        backend_id, command = self._preview_speed_test()
        if not command:
            self._set_status("No supported speed-test backend is available.")
            return
        self._run_command("speed_test", command, success_payload={"backend": backend_id}, target="speed")

    def _run_latency_check(self):
        command = self._preview_latency_check()
        self._run_command("latency_check", command, success_payload=None, target="speed")

    def _run_public_ip_check(self):
        command = self._preview_public_ip()
        self._run_command("public_ip_check", command, success_payload=None, target="speed")

    def _refresh_speed_summary(self):
        speed = self._health_state.get("latest_speed_test")
        latency = self._health_state.get("latest_latency")
        public_ip = self._health_state.get("latest_public_ip")
        last_report = self._health_state.get("last_report_path")

        if speed and speed.get("summary"):
            self._speed_latest_var.set(speed["summary"])
        else:
            self._speed_latest_var.set("(not run yet)")

        if latency and latency.get("summary"):
            self._latency_latest_var.set(latency["summary"])
        else:
            self._latency_latest_var.set("(not run yet)")

        if public_ip and public_ip.get("summary"):
            self._public_ip_latest_var.set(public_ip["summary"])
        else:
            self._public_ip_latest_var.set("(not run yet)")

        if last_report:
            self._last_report_var.set(last_report)
        else:
            self._last_report_var.set("(none saved)")

    def _report_filename(self):
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"speed_report_{stamp}.json"

    def _save_speed_report(self):
        if not self.network_reports_dir:
            self._set_status("Pack root is not set.")
            return
        report = {
            "timestamp": _now_iso(),
            "page": "network_control",
            "tab": "speed_test",
            "latest_speed_test": self._health_state.get("latest_speed_test"),
            "latest_latency": self._health_state.get("latest_latency"),
            "latest_public_ip": self._health_state.get("latest_public_ip"),
        }
        if not any(report[key] for key in ("latest_speed_test", "latest_latency", "latest_public_ip")):
            self._set_status("Run at least one speed/health action before saving a report.")
            return
        path = os.path.join(self.network_reports_dir, self._report_filename())
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(report, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
        except Exception as exc:
            self._set_status(f"Could not save report: {exc}")
            return
        self._health_state["last_report_path"] = path
        self._save_config()
        self._refresh_speed_summary()
        self._refresh_speed_report_list()
        self._set_status(f"Saved report: {os.path.basename(path)}")

    def _refresh_speed_report_list(self):
        if not hasattr(self, "_speed_report_lb"):
            return
        self._speed_report_lb.delete(0, "end")
        self._speed_report_paths = []
        if not self.network_reports_dir or not os.path.isdir(self.network_reports_dir):
            self._speed_report_path_var.set("No saved report selected.")
            return
        for name in sorted(os.listdir(self.network_reports_dir), reverse=True):
            if not name.endswith(".json"):
                continue
            full = os.path.join(self.network_reports_dir, name)
            self._speed_report_paths.append(full)
            self._speed_report_lb.insert("end", name)
        if not self._speed_report_paths:
            self._speed_report_path_var.set("No saved report selected.")

    def _on_speed_report_select(self, _event=None):
        selection = self._speed_report_lb.curselection()
        if not selection:
            self._speed_report_path_var.set("No saved report selected.")
            return
        idx = selection[0]
        if idx < len(self._speed_report_paths):
            self._speed_report_path_var.set(self._speed_report_paths[idx])

    def _parse_speed_output(self, raw_output, payload):
        backend = (payload or {}).get("backend") or "unknown"
        summary = "Speed test completed."
        match = re.search(r"DOWNLOAD_MBPS=([0-9.]+)", raw_output)
        if match:
            summary = f"download {match.group(1)} Mbps via {backend}"
        return {
            "timestamp": _now_iso(),
            "backend": backend,
            "summary": summary,
            "raw_output": raw_output.strip(),
        }

    def _parse_latency_output(self, raw_output):
        summary = "Latency check completed."
        values = re.findall(r"AVG_MS=([0-9.]+)", raw_output)
        if values:
            summary = "avg " + " / ".join(f"{value} ms" for value in values)
        return {
            "timestamp": _now_iso(),
            "summary": summary,
            "raw_output": raw_output.strip(),
        }

    def _parse_public_ip_output(self, raw_output):
        ip_match = re.search(r"PUBLIC_IP=([^\n]+)", raw_output)
        org_match = re.search(r"PUBLIC_ORG=([^\n]+)", raw_output)
        ip = ip_match.group(1).strip() if ip_match else "unknown"
        org = org_match.group(1).strip() if org_match else "provider unknown"
        return {
            "timestamp": _now_iso(),
            "summary": f"{ip} / {org}",
            "ip": ip,
            "org": org,
            "raw_output": raw_output.strip(),
        }

    def _stop_running(self):
        if not self._runner_busy:
            self._set_status("No command is running.")
            return
        proc = None
        with self._runner_lock:
            proc = self._runner_proc
        if proc is None:
            self._set_status("Runner is stopping.")
            return
        try:
            proc.terminate()
            self._set_status("Sent terminate to running command.")
        except Exception as exc:
            self._set_status(f"Could not stop command: {exc}")
