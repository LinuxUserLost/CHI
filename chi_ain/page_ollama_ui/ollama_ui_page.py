"""
page_ollama_ui / ollama_ui_page.py
──────────────────────────────────────────────────────────────────────────────
Ollama workstation page for Guichi.

This rebuild keeps the original behavior foundation:
- persistent session singleton
- Ollama client usage
- chat/send/export flows
- attachment scanning + context assembly

UI direction:
- left  : prompt / save / session / debug
- center: chat workspace
- right : attachments / context controls
"""

from __future__ import annotations

import os
import sys
import json
import datetime
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from gui_files import interaction_support
from chi_ain import promptworkshop_store

_THIS_FILE = os.path.abspath(__file__)
_PAGE_DIR = os.path.dirname(_THIS_FILE)
_PACK_DIR = os.path.dirname(_PAGE_DIR)
_REPO_DIR = os.path.dirname(_PACK_DIR)
_HELPERS_ROOT = os.path.join(_REPO_DIR, "chi_reader")
if _HELPERS_ROOT not in sys.path:
    sys.path.insert(0, _HELPERS_ROOT)

from helpers.ollama_client import OllamaClient, DEFAULT_BASE_URL


READABLE_EXTENSIONS = {
    ".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".csv", ".html", ".css", ".js", ".ts", ".xml", ".sql", ".sh",
}

MAX_SCAN_FILES = 50
MAX_SCAN_BYTES = 1_048_576

_CLR_OK = "#2e7d32"
_CLR_WARN = "#e65100"
_CLR_ERR = "#c62828"

_DEFAULT_PAGE_THEME = {
    "app_bg": "#1e1e1e",
    "content_bg": "#1e1e1e",
    "panel_bg": "#2b2b2b",
    "sidebar_bg": "#242424",
    "text_main": "#dddddd",
    "text_muted": "#8f8f8f",
    "text_active": "#ffffff",
    "text_on_accent": "#ffffff",
    "button_bg": "#373737",
    "button_hover": "#4a4a4a",
    "button_active": "#ffffff",
    "button_disabled": "#666666",
    "accent": "#4ea0ff",
    "border": "#4a4a4a",
    "divider": "#343434",
}


def _blend_hex(color_a: str, color_b: str, factor: float) -> str:
    factor = max(0.0, min(1.0, factor))
    try:
        a = color_a.lstrip("#")
        b = color_b.lstrip("#")
        ar, ag, ab = int(a[0:2], 16), int(a[2:4], 16), int(a[4:6], 16)
        br, bg, bb = int(b[0:2], 16), int(b[2:4], 16), int(b[4:6], 16)
        rr = int(ar + (br - ar) * factor)
        rg = int(ag + (bg - ag) * factor)
        rb = int(ab + (bb - ab) * factor)
        return f"#{rr:02x}{rg:02x}{rb:02x}"
    except Exception:
        return color_a


class ChillamaSession:
    """Persistent session state that survives page unmount/remount."""

    def __init__(self):
        self.history = []
        self.attachments = []
        self.last_response = ""
        self.last_exchange = {}
        self.system_prompt = ""
        self.temperature = "0.7"
        self.context_mode = "include_contents"
        self.base_url = DEFAULT_BASE_URL
        self.selected_model = ""
        self.keep_alive = True
        self.connected = False
        self.models = []
        self.created_at = datetime.datetime.now().strftime("%H:%M:%S")
        self.client = OllamaClient(DEFAULT_BASE_URL)

    def is_live(self):
        return bool(self.history) or self.connected


_LIVE_SESSION = None


class AIInterface:
    PAGE_NAME = "Ollama UI"

    def __init__(self, parent, app=None, page_key="", page_folder="", *args, **kwargs):
        global _LIVE_SESSION
        app = kwargs.pop("controller", app)
        page_key = kwargs.pop("page_context", page_key)
        page_folder = kwargs.pop("page_folder", page_folder)

        self.parent = parent
        self.app = app
        self.page_key = page_key
        self.page_folder = page_folder
        self.guichi_page_theme = None
        self._theme_tokens = dict(_DEFAULT_PAGE_THEME)
        self._style_prefix = f"OllamaUI.{id(self)}"
        self._style = None

        if _LIVE_SESSION is not None and _LIVE_SESSION.keep_alive:
            self._session = _LIVE_SESSION
            self._is_resuming = True
        else:
            self._session = ChillamaSession()
            _LIVE_SESSION = self._session
            self._is_resuming = False

        self._scan_cancel = False
        self._scanning = False
        self._workshop_root = ""
        self._workshop_prompts_dir = ""
        self._workshop_maps_dir = ""
        self._workshop_prompt_files = []
        self._workshop_map_files = []

        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)

        self._build_header()
        self._build_workspace()
        self._build_status_bar()
        self._apply_theme()

        self.frame.bind("<Destroy>", self._on_frame_destroy)

        if self._is_resuming:
            self._restore_session_to_widgets()
        else:
            self.frame.after(300, self._check_connection)

        self._update_session_status()

    @property
    def _client(self):
        return self._session.client

    @property
    def _connected(self):
        return self._session.connected

    @_connected.setter
    def _connected(self, value):
        self._session.connected = value

    @property
    def _models(self):
        return self._session.models

    @_models.setter
    def _models(self, value):
        self._session.models = value

    @property
    def _selected_model(self):
        return self._session.selected_model

    @_selected_model.setter
    def _selected_model(self, value):
        self._session.selected_model = value

    @property
    def _history(self):
        return self._session.history

    @_history.setter
    def _history(self, value):
        self._session.history = value

    @property
    def _attachments(self):
        return self._session.attachments

    @_attachments.setter
    def _attachments(self, value):
        self._session.attachments = value

    @property
    def _last_response(self):
        return self._session.last_response

    @_last_response.setter
    def _last_response(self, value):
        self._session.last_response = value

    @property
    def _last_exchange(self):
        return self._session.last_exchange

    @_last_exchange.setter
    def _last_exchange(self, value):
        self._session.last_exchange = value

    def _embed_into_parent(self, parent=None):
        container = parent or self.parent
        try:
            if container is not None and self.frame.master is not container:
                self.frame.destroy()
                self.parent = container
                self.frame = ttk.Frame(container)
                self.frame.columnconfigure(0, weight=1)
                self.frame.rowconfigure(1, weight=1)
                self._build_header()
                self._build_workspace()
                self._build_status_bar()
                self._apply_theme()
                self.frame.bind("<Destroy>", self._on_frame_destroy)
                if self._is_resuming:
                    self._restore_session_to_widgets()
                else:
                    self.frame.after(300, self._check_connection)
                self._update_session_status()
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

    def set_guichi_page_theme(self, context):
        self.guichi_page_theme = context
        tokens = dict(_DEFAULT_PAGE_THEME)
        tokens.update((context or {}).get("tokens") or {})
        self._theme_tokens = tokens
        self._apply_theme()

    def _on_frame_destroy(self, event=None):
        global _LIVE_SESSION
        if event and event.widget is not self.frame:
            return
        try:
            self._session.system_prompt = self._system_txt.get("1.0", "end-1c").strip()
            self._session.temperature = self._temp_var.get()
            self._session.context_mode = self._context_mode_var.get()
            self._session.base_url = self._url_var.get().strip()
        except Exception:
            pass
        if not self._session.keep_alive:
            _LIVE_SESSION = None

    def _kill_session(self):
        global _LIVE_SESSION
        new = ChillamaSession()
        new.keep_alive = self._session.keep_alive
        new.base_url = self._session.base_url
        new.client = self._session.client
        new.connected = self._session.connected
        new.models = self._session.models
        new.selected_model = self._session.selected_model
        _LIVE_SESSION = new
        self._session = new

        self._chat_display.configure(state="normal")
        self._chat_display.delete("1.0", "end")
        self._chat_display.configure(state="disabled")
        self._append_chat_meta("Session reset — history and attachments cleared.")

        self._refresh_attach_display()
        self._update_attach_badge()
        self._update_session_status()
        self._set_status("Session reset.")

    def _on_keep_alive_toggle(self):
        self._session.keep_alive = self._keep_alive_var.get()
        self._update_session_status()

    def _restore_session_to_widgets(self):
        self._url_var.set(self._session.base_url)
        self._temp_var.set(self._session.temperature)

        if self._session.models:
            names = [m["name"] for m in self._session.models]
            self._model_combo.configure(values=names)

        if self._session.selected_model:
            self._model_var.set(self._session.selected_model)

        if self._session.connected:
            self._conn_label.configure(text="Connected (restored)", fg=_CLR_OK)
            self._status_dot.configure(fg=_CLR_OK)
        else:
            self.frame.after(300, self._check_connection)

        self._system_txt.delete("1.0", "end")
        if self._session.system_prompt:
            self._system_txt.insert("1.0", self._session.system_prompt)

        self._context_mode_var.set(self._session.context_mode)
        self._keep_alive_var.set(self._session.keep_alive)

        self._rebuild_chat_from_history()
        self._refresh_attach_display()
        self._update_attach_badge()
        self._refresh_debug_info()

        exchanges = len([h for h in self._session.history if h.get("role") == "assistant"])
        self._append_chat_meta(
            f"Session restored — {exchanges} exchange(s) — started {self._session.created_at}"
        )

    def _build_header(self):
        self._header = ttk.Frame(self.frame, padding=(8, 6))
        self._header.grid(row=0, column=0, sticky="ew")
        for idx in (3, 6, 11):
            self._header.columnconfigure(idx, weight=1)

        self._status_dot = tk.Label(self._header, text="●", font=("", 13), anchor="w")
        self._status_dot.grid(row=0, column=0, padx=(0, 4))

        self._conn_label = tk.Label(self._header, text="Not checked", font=("", 9), anchor="w")
        self._conn_label.grid(row=0, column=1, padx=(0, 8), sticky="w")

        tk.Label(self._header, text="URL:", font=("", 9), anchor="e").grid(row=0, column=2, padx=(0, 4), sticky="e")
        self._url_var = tk.StringVar(value=self._session.base_url)
        self._url_entry = ttk.Entry(self._header, textvariable=self._url_var, width=28)
        self._url_entry.grid(row=0, column=3, sticky="ew", padx=(0, 6))
        self._url_entry.bind("<Return>", lambda e: self._check_connection())

        ttk.Button(self._header, text="Refresh", width=9, command=self._check_connection).grid(row=0, column=4, padx=(0, 10))

        tk.Label(self._header, text="Model:", font=("", 9), anchor="e").grid(row=0, column=5, padx=(0, 4), sticky="e")
        self._model_var = tk.StringVar(value=self._session.selected_model or "(none)")
        self._model_combo = ttk.Combobox(self._header, textvariable=self._model_var, values=[], width=24, state="readonly")
        self._model_combo.grid(row=0, column=6, sticky="ew", padx=(0, 8))
        self._model_combo.bind("<<ComboboxSelected>>", self._on_model_select)

        tk.Label(self._header, text="Temp:", font=("", 9), anchor="e").grid(row=0, column=7, padx=(0, 4), sticky="e")
        self._temp_var = tk.StringVar(value=self._session.temperature)
        ttk.Entry(self._header, textvariable=self._temp_var, width=6).grid(row=0, column=8, padx=(0, 10))

        self._keep_alive_var = tk.BooleanVar(value=self._session.keep_alive)
        self._keep_alive_chk = ttk.Checkbutton(
            self._header,
            text="Keep Session",
            variable=self._keep_alive_var,
            command=self._on_keep_alive_toggle,
        )
        self._keep_alive_chk.grid(row=0, column=9, padx=(0, 10), sticky="w")

        self._session_status_var = tk.StringVar(value="No session")
        self._session_status_lbl = tk.Label(self._header, textvariable=self._session_status_var, font=("", 8), anchor="e")
        self._session_status_lbl.grid(row=0, column=11, sticky="e")

    def _build_workspace(self):
        self._workspace = ttk.Frame(self.frame, padding=(6, 0, 6, 4))
        self._workspace.grid(row=1, column=0, sticky="nsew")
        self._workspace.columnconfigure(0, weight=1)
        self._workspace.rowconfigure(0, weight=1)
        self._workspace.rowconfigure(1, weight=0)
        self._workspace.rowconfigure(2, weight=0)
        self._workspace.rowconfigure(3, weight=0)

        self._build_center_pane()
        self._build_utility_stack()

    def _build_utility_stack(self):
        self._utility_outer = ttk.Frame(self._workspace)
        self._utility_outer.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self._utility_outer.columnconfigure(0, weight=1)

        self._utility_states = {
            "workshop": True,
            "attachments": True,
            "system": False,
            "save": False,
            "session": False,
        }
        self._utility_buttons = {}
        self._utility_content_frames = {}

        definitions = [
            ("workshop", "Prompt Workshop", self._build_workshop_section),
            ("attachments", "Attachments / Context", self._build_attachments_section),
            ("system", "System Prompt", self._build_system_prompt_section),
            ("save", "Save / Export", self._build_save_export_section),
            ("session", "Session / Debug", self._build_session_debug_section),
        ]

        row = 0
        for key, title, builder in definitions:
            button = ttk.Button(
                self._utility_outer,
                text="",
                command=lambda k=key: self._toggle_utility_section(k),
            )
            button.grid(row=row, column=0, sticky="ew", pady=(0, 4))
            self._utility_buttons[key] = button
            row += 1

            frame = ttk.LabelFrame(self._utility_outer, text=title, padding=(8, 6))
            frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
            frame.columnconfigure(0, weight=1)
            self._utility_content_frames[key] = frame
            builder(frame)
            row += 1

        self._refresh_utility_sections()

    def _build_system_prompt_section(self, pane):
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(0, weight=1)

        self._system_txt = tk.Text(pane, wrap="word", height=8, undo=True, relief="flat", borderwidth=1, padx=8, pady=6)
        self._system_txt.grid(row=0, column=0, sticky="nsew")
        sys_scroll = ttk.Scrollbar(pane, orient="vertical", command=self._system_txt.yview)
        sys_scroll.grid(row=0, column=1, sticky="ns")
        self._system_txt.configure(yscrollcommand=sys_scroll.set)
        interaction_support.setup_text_widget(self._system_txt)

        self._system_hint = ttk.Label(
            pane,
            text="Applied to every send. Leave blank for normal model behavior.",
            justify="left",
        )
        self._system_hint.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

    def _build_workshop_section(self, pane):
        pane.columnconfigure(0, weight=1)
        pane.columnconfigure(1, weight=1)
        pane.rowconfigure(2, weight=1)

        self._workshop_status_var = tk.StringVar(value="Prompt workshop not loaded yet.")
        self._workshop_status_lbl = ttk.Label(pane, textvariable=self._workshop_status_var, justify="left")
        self._workshop_status_lbl.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))

        top_btns = ttk.Frame(pane)
        top_btns.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Button(top_btns, text="Refresh Lists", command=self._refresh_workshop_lists).pack(side="left", padx=(0, 4))
        ttk.Button(top_btns, text="Preview Selected", command=self._preview_workshop_selection).pack(side="left", padx=(0, 4))
        ttk.Button(top_btns, text="Clear Preview", command=self._clear_workshop_preview).pack(side="left")

        prompt_lf = ttk.LabelFrame(pane, text="Prompts", padding=(6, 4))
        prompt_lf.grid(row=2, column=0, sticky="nsew", padx=(0, 4))
        prompt_lf.columnconfigure(0, weight=1)
        prompt_lf.rowconfigure(0, weight=1)
        self._workshop_prompt_lb = tk.Listbox(prompt_lf, height=6, selectmode="extended", activestyle="none", exportselection=False)
        self._workshop_prompt_lb.grid(row=0, column=0, sticky="nsew")
        interaction_support.setup_listbox_widget(self._workshop_prompt_lb)
        prompt_scroll = ttk.Scrollbar(prompt_lf, orient="vertical", command=self._workshop_prompt_lb.yview)
        prompt_scroll.grid(row=0, column=1, sticky="ns")
        self._workshop_prompt_lb.configure(yscrollcommand=prompt_scroll.set)
        self._workshop_prompt_lb.bind("<<ListboxSelect>>", lambda e: self._preview_workshop_selection())

        map_lf = ttk.LabelFrame(pane, text="Maps", padding=(6, 4))
        map_lf.grid(row=2, column=1, sticky="nsew", padx=(4, 0))
        map_lf.columnconfigure(0, weight=1)
        map_lf.rowconfigure(0, weight=1)
        self._workshop_map_lb = tk.Listbox(map_lf, height=6, selectmode="extended", activestyle="none", exportselection=False)
        self._workshop_map_lb.grid(row=0, column=0, sticky="nsew")
        interaction_support.setup_listbox_widget(self._workshop_map_lb)
        map_scroll = ttk.Scrollbar(map_lf, orient="vertical", command=self._workshop_map_lb.yview)
        map_scroll.grid(row=0, column=1, sticky="ns")
        self._workshop_map_lb.configure(yscrollcommand=map_scroll.set)
        self._workshop_map_lb.bind("<<ListboxSelect>>", lambda e: self._preview_workshop_selection())

        preview_lf = ttk.LabelFrame(pane, text="Workshop Preview", padding=(6, 4))
        preview_lf.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(6, 6))
        preview_lf.columnconfigure(0, weight=1)
        preview_lf.rowconfigure(0, weight=1)
        self._workshop_preview = tk.Text(preview_lf, height=8, wrap="word", state="disabled", relief="flat", borderwidth=1, padx=8, pady=6)
        self._workshop_preview.grid(row=0, column=0, sticky="nsew")
        interaction_support.setup_text_widget(self._workshop_preview)
        preview_scroll = ttk.Scrollbar(preview_lf, orient="vertical", command=self._workshop_preview.yview)
        preview_scroll.grid(row=0, column=1, sticky="ns")
        self._workshop_preview.configure(yscrollcommand=preview_scroll.set)

        action_row = ttk.Frame(pane)
        action_row.grid(row=4, column=0, columnspan=2, sticky="ew")
        ttk.Button(action_row, text="Replace System Prompt", command=self._replace_system_prompt_from_workshop).pack(side="left", padx=(0, 4))
        ttk.Button(action_row, text="Append To System Prompt", command=self._append_system_prompt_from_workshop).pack(side="left")

        self._refresh_workshop_lists()

    def _build_save_export_section(self, pane):
        pane.columnconfigure(0, weight=1)
        ttk.Button(pane, text="Save Last Response", command=self._save_response).grid(row=0, column=0, sticky="ew", pady=(0, 4))
        ttk.Button(pane, text="Copy Last Response", command=self._copy_response).grid(row=1, column=0, sticky="ew", pady=(0, 4))
        ttk.Button(pane, text="Save Chat Log", command=self._save_chat).grid(row=2, column=0, sticky="ew", pady=(0, 4))
        ttk.Button(pane, text="Save Exchange Bundle", command=self._save_exchange_bundle).grid(row=3, column=0, sticky="ew")

    def _build_center_pane(self):
        pane = self._workspace
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(0, weight=1)
        pane.rowconfigure(1, weight=0)
        pane.rowconfigure(2, weight=0)

        conv_lf = ttk.LabelFrame(pane, text="Conversation", padding=(8, 6))
        conv_lf.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
        conv_lf.columnconfigure(0, weight=1)
        conv_lf.rowconfigure(0, weight=1)

        self._chat_display = tk.Text(
            conv_lf,
            wrap="word",
            state="disabled",
            relief="flat",
            borderwidth=0,
            padx=12,
            pady=10,
            spacing3=2,
            cursor="xterm",
        )
        self._chat_display.grid(row=0, column=0, sticky="nsew")
        chat_scroll = ttk.Scrollbar(conv_lf, orient="vertical", command=self._chat_display.yview)
        chat_scroll.grid(row=0, column=1, sticky="ns")
        self._chat_display.configure(yscrollcommand=chat_scroll.set)
        interaction_support.setup_text_widget(self._chat_display)
        self._chat_display.bind("<Control-c>", self._copy_chat_selection)
        self._chat_display.bind("<Control-C>", self._copy_chat_selection)
        self._configure_chat_tags()
        self._append_chat_meta("Ollama Workstation — connect, choose a model, and start a session.")

        util_row = ttk.Frame(pane, padding=(0, 0, 0, 4))
        util_row.grid(row=1, column=0, sticky="ew")
        util_row.columnconfigure(10, weight=1)
        ttk.Button(util_row, text="Upload File", width=12, command=self._choose_file).grid(row=0, column=0, padx=(0, 4))
        ttk.Button(util_row, text="Upload Dir", width=12, command=self._choose_directory).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(util_row, text="Copy Last", width=10, command=self._copy_response).grid(row=0, column=2, padx=(0, 4))
        ttk.Button(util_row, text="Clear Chat", width=10, command=self._clear_chat).grid(row=0, column=3, padx=(0, 4))
        self._attach_badge_var = tk.StringVar(value="")
        self._attach_badge = ttk.Label(util_row, textvariable=self._attach_badge_var)
        self._attach_badge.grid(row=0, column=10, sticky="e")

        comp_lf = ttk.LabelFrame(pane, text="Composer", padding=(8, 6))
        comp_lf.grid(row=2, column=0, sticky="ew")
        comp_lf.columnconfigure(0, weight=1)
        self._composer = tk.Text(self._workspace, wrap="word", height=5, undo=True, relief="flat", borderwidth=1, padx=8, pady=6, insertwidth=2)
        self._composer.grid(in_=comp_lf, row=0, column=0, sticky="ew", padx=(0, 6))
        interaction_support.setup_text_widget(self._composer)
        self._composer.bind("<Return>", self._on_composer_return)
        self._composer.bind("<Shift-Return>", self._on_composer_shift_return)
        self._composer.bind("<Control-Return>", lambda e: (self._on_send(), "break"))
        self._send_btn = ttk.Button(comp_lf, text="Send ▶", command=self._on_send, width=10)
        self._send_btn.grid(row=0, column=1, sticky="ns")

    def _build_attachments_section(self, pane):
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(1, weight=1)
        pane.rowconfigure(2, weight=0)

        ctrl_lf = ttk.Frame(pane)
        ctrl_lf.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctrl_lf.columnconfigure(1, weight=1)
        ttk.Button(ctrl_lf, text="Choose File…", command=self._choose_file).grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=(0, 4))
        ttk.Button(ctrl_lf, text="Choose Dir…", command=self._choose_directory).grid(row=0, column=1, sticky="ew", pady=(0, 4))
        ttk.Button(ctrl_lf, text="Clear All", command=self._clear_attachments).grid(row=1, column=0, sticky="ew", padx=(0, 4))
        self._cancel_btn = ttk.Button(ctrl_lf, text="Cancel Scan", command=self._cancel_scan)
        self._cancel_btn.grid(row=1, column=1, sticky="ew")
        self._cancel_btn.grid_remove()

        self._scan_status_var = tk.StringVar(value="")
        self._scan_status_lbl = ttk.Label(ctrl_lf, textvariable=self._scan_status_var, justify="left")
        self._scan_status_lbl.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        mode_row = ttk.Frame(ctrl_lf)
        mode_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self._context_mode_var = tk.StringVar(value=self._session.context_mode)
        self._context_mode_var.trace_add("write", lambda *_: self._on_context_mode_change())
        ttk.Radiobutton(mode_row, text="Paths only", variable=self._context_mode_var, value="paths_only").pack(side="left", padx=(0, 8))
        ttk.Radiobutton(mode_row, text="Include contents", variable=self._context_mode_var, value="include_contents").pack(side="left")

        attach_lf = ttk.Frame(pane)
        attach_lf.grid(row=1, column=0, sticky="nsew", pady=(0, 6))
        attach_lf.columnconfigure(0, weight=1)
        attach_lf.rowconfigure(0, weight=1)

        cols = ("name", "type", "size", "status")
        self._attach_tree = ttk.Treeview(attach_lf, columns=cols, show="headings", selectmode="extended")
        self._attach_tree.heading("name", text="Name")
        self._attach_tree.heading("type", text="Type")
        self._attach_tree.heading("size", text="Size")
        self._attach_tree.heading("status", text="Status")
        self._attach_tree.column("name", width=220, minwidth=120)
        self._attach_tree.column("type", width=60, minwidth=40, anchor="center")
        self._attach_tree.column("size", width=72, minwidth=50, anchor="e")
        self._attach_tree.column("status", width=90, minwidth=60, anchor="center")
        self._attach_tree.grid(row=0, column=0, sticky="nsew")
        interaction_support.setup_treeview_widget(self._attach_tree)
        tree_scroll = ttk.Scrollbar(attach_lf, orient="vertical", command=self._attach_tree.yview)
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self._attach_tree.configure(yscrollcommand=tree_scroll.set)

        self._drop_label = tk.Label(
            attach_lf,
            text="No attachments yet.\nChoose a file or scan a directory.",
            justify="center",
        )
        self._drop_label.place(relx=0.5, rely=0.5, anchor="center")

        foot = ttk.Frame(pane)
        foot.grid(row=2, column=0, sticky="ew")
        foot.columnconfigure(1, weight=1)
        ttk.Button(foot, text="Remove Selected", command=self._remove_selected_attachments).grid(row=0, column=0, sticky="w")
        self._attach_count_var = tk.StringVar(value="0 files")
        ttk.Label(foot, textvariable=self._attach_count_var).grid(row=0, column=1, sticky="e")

    def _build_session_debug_section(self, pane):
        pane.columnconfigure(0, weight=1)
        self._session_hint = ttk.Label(
            pane,
            text="Use keep-alive to preserve conversation across page switches.",
            justify="left",
        )
        self._session_hint.grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Button(pane, text="Reset / Kill Session", command=self._kill_session).grid(row=1, column=0, sticky="ew", pady=(0, 6))

        self._debug_info_var = tk.StringVar(value="No connection info yet.")
        self._debug_label = ttk.Label(pane, textvariable=self._debug_info_var, justify="left", anchor="w", wraplength=760)
        self._debug_label.grid(row=2, column=0, sticky="ew")
        ttk.Button(pane, text="Refresh Connection Info", command=self._refresh_debug_info).grid(row=3, column=0, sticky="w", pady=(6, 0))

    def _resolve_workshop_root(self):
        root = promptworkshop_store.resolve_local_workshop_root(__file__)
        if not root:
            self._workshop_root = ""
            self._workshop_prompts_dir = ""
            self._workshop_maps_dir = ""
            return False
        self._workshop_root = root
        self._workshop_prompts_dir, self._workshop_maps_dir = promptworkshop_store.ensure_workshop_dirs(root)
        return True

    def _refresh_workshop_lists(self):
        self._workshop_prompt_files = []
        self._workshop_map_files = []
        self._workshop_prompt_lb.delete(0, "end")
        self._workshop_map_lb.delete(0, "end")
        if not self._resolve_workshop_root():
            self._workshop_status_var.set("Prompt workshop root not found.")
            self._clear_workshop_preview()
            return

        self._workshop_prompt_files = promptworkshop_store.list_records(self._workshop_prompts_dir)
        self._workshop_map_files = promptworkshop_store.list_records(self._workshop_maps_dir)
        for display, _full in self._workshop_prompt_files:
            self._workshop_prompt_lb.insert("end", display)
        for display, _full in self._workshop_map_files:
            self._workshop_map_lb.insert("end", display)
        if not self._workshop_prompt_files:
            self._workshop_prompt_lb.insert("end", "(no prompts)")
        if not self._workshop_map_files:
            self._workshop_map_lb.insert("end", "(no maps)")
        self._workshop_status_var.set(
            f"{len(self._workshop_prompt_files)} prompt(s) • {len(self._workshop_map_files)} map(s)"
        )
        self._clear_workshop_preview()

    def _selected_prompt_records(self):
        records = []
        for idx in self._workshop_prompt_lb.curselection():
            if idx >= len(self._workshop_prompt_files):
                continue
            display, full = self._workshop_prompt_files[idx]
            try:
                record = promptworkshop_store.load_json_record(full, lambda: {"title": "", "body": ""})
            except Exception:
                continue
            records.append((display, record))
        return records

    def _selected_map_records(self):
        records = []
        for idx in self._workshop_map_lb.curselection():
            if idx >= len(self._workshop_map_files):
                continue
            display, full = self._workshop_map_files[idx]
            try:
                record = promptworkshop_store.load_json_record(full, lambda: {"title": "", "blocks": []})
            except Exception:
                continue
            records.append((display, record))
        return records

    def _build_workshop_bundle(self):
        parts = []
        prompt_count = 0
        map_count = 0
        for display, record in self._selected_prompt_records():
            body = (record.get("body") or "").strip()
            if not body:
                continue
            parts.append(body)
            prompt_count += 1
        for display, record in self._selected_map_records():
            assembled = promptworkshop_store.assemble_map_preview(self._workshop_prompts_dir, record).strip()
            if not assembled:
                continue
            parts.append(assembled)
            map_count += 1
        bundle = "\n\n---\n\n".join(parts).strip()
        return bundle, prompt_count, map_count

    def _preview_workshop_selection(self):
        bundle, prompt_count, map_count = self._build_workshop_bundle()
        self._workshop_preview.configure(state="normal")
        self._workshop_preview.delete("1.0", "end")
        self._workshop_preview.insert("1.0", bundle or "(select prompts and/or maps to preview)")
        self._workshop_preview.configure(state="disabled")
        if bundle:
            self._workshop_status_var.set(f"Previewing {prompt_count} prompt(s) + {map_count} map(s)")
        else:
            self._workshop_status_var.set(
                f"{len(self._workshop_prompt_files)} prompt(s) • {len(self._workshop_map_files)} map(s)"
            )
        return bundle

    def _clear_workshop_preview(self):
        self._workshop_preview.configure(state="normal")
        self._workshop_preview.delete("1.0", "end")
        self._workshop_preview.insert("1.0", "(select prompts and/or maps to preview)")
        self._workshop_preview.configure(state="disabled")

    def _replace_system_prompt_from_workshop(self):
        bundle = self._preview_workshop_selection().strip()
        if not bundle:
            self._set_status("Select workshop prompt(s) or map(s) first.")
            return
        self._system_txt.delete("1.0", "end")
        self._system_txt.insert("1.0", bundle)
        self._session.system_prompt = bundle
        self._set_status("System prompt replaced from workshop selection.")

    def _append_system_prompt_from_workshop(self):
        bundle = self._preview_workshop_selection().strip()
        if not bundle:
            self._set_status("Select workshop prompt(s) or map(s) first.")
            return
        current = self._system_txt.get("1.0", "end-1c").strip()
        final = f"{current}\n\n---\n\n{bundle}" if current else bundle
        self._system_txt.delete("1.0", "end")
        self._system_txt.insert("1.0", final)
        self._session.system_prompt = final
        self._set_status("Workshop selection appended to system prompt.")

    def _toggle_utility_section(self, key):
        self._utility_states[key] = not self._utility_states.get(key, False)
        self._refresh_utility_sections()

    def _refresh_utility_sections(self):
        labels = {
            "workshop": "Prompt Workshop",
            "attachments": "Attachments / Context",
            "system": "System Prompt",
            "save": "Save / Export",
            "session": "Session / Debug",
        }
        counts = {
            "workshop": f"{len(self._workshop_prompt_files)}p • {len(self._workshop_map_files)}m",
            "attachments": f"{len(self._attachments)} attached",
            "system": "prompt + instructions",
            "save": "response, chat, bundle",
            "session": "keep-alive + debug",
        }
        for key, button in self._utility_buttons.items():
            open_state = self._utility_states.get(key, False)
            prefix = "Hide" if open_state else "Show"
            button.configure(text=f"{prefix} {labels[key]}  •  {counts[key]}")
            frame = self._utility_content_frames[key]
            if open_state:
                frame.grid()
            else:
                frame.grid_remove()

    def _build_status_bar(self):
        self._status_bar = ttk.Frame(self.frame, padding=(8, 2))
        self._status_bar.grid(row=2, column=0, sticky="ew")
        self._status_bar.columnconfigure(0, weight=1)
        self._status_var = tk.StringVar(value="Ready.")
        self._status_label = ttk.Label(self._status_bar, textvariable=self._status_var, anchor="w")
        self._status_label.grid(row=0, column=0, sticky="ew")

    def _set_status(self, msg):
        self._status_var.set(msg)

    def _configure_chat_tags(self):
        t = self._theme_tokens
        user_name = t["accent"]
        ai_name = t["text_main"]
        meta_fg = t["text_muted"]
        thinking_fg = _blend_hex(t["text_muted"], t["accent"], 0.35)
        user_bg = _blend_hex(t["accent"], t["panel_bg"], 0.72)
        ai_bg = _blend_hex(t["sidebar_bg"], t["panel_bg"], 0.45)
        chat_bg = t["content_bg"]
        user_fg = t["text_on_accent"] if user_bg == t["accent"] else t["text_main"]
        ai_fg = t["text_main"]
        self._chat_display.tag_configure("user_name", font=("", 9, "bold"), foreground=user_name, justify="right", spacing1=12)
        self._chat_display.tag_configure("user_msg", font=("", 10), foreground=user_fg, background=user_bg, justify="right", lmargin1=120, lmargin2=120, rmargin=8, spacing1=2, spacing3=4)
        self._chat_display.tag_configure("ai_name", font=("", 9, "bold"), foreground=ai_name, justify="left", spacing1=12)
        self._chat_display.tag_configure("ai_msg", font=("", 10), foreground=ai_fg, background=ai_bg, justify="left", lmargin1=8, lmargin2=8, rmargin=120, spacing1=2, spacing3=4)
        self._chat_display.tag_configure("meta", font=("", 8), foreground=meta_fg, justify="center", spacing1=2, spacing3=6)
        self._chat_display.tag_configure("thinking", font=("", 9, "italic"), foreground=thinking_fg, justify="left", lmargin1=8, spacing1=2, spacing3=4)
        self._chat_display.tag_configure("separator", font=("", 4), foreground=chat_bg, justify="center", spacing1=0, spacing3=0)

    def _apply_theme(self):
        t = self._theme_tokens
        try:
            self._style = ttk.Style(self.frame)
            self._style.configure(f"{self._style_prefix}.TFrame", background=t["content_bg"])
            self._style.configure(f"{self._style_prefix}.Panel.TFrame", background=t["panel_bg"])
            self._style.configure(
                f"{self._style_prefix}.TLabelframe",
                background=t["panel_bg"],
                bordercolor=t["border"],
            )
            self._style.configure(
                f"{self._style_prefix}.TLabelframe.Label",
                background=t["panel_bg"],
                foreground=t["text_main"],
            )
            self._style.configure(f"{self._style_prefix}.TLabel", background=t["content_bg"], foreground=t["text_main"])
            self._style.configure(f"{self._style_prefix}.Panel.TLabel", background=t["panel_bg"], foreground=t["text_main"])
            self._style.configure(f"{self._style_prefix}.Muted.TLabel", background=t["content_bg"], foreground=t["text_muted"])
            self._style.configure(
                f"{self._style_prefix}.TButton",
                background=t["button_bg"],
                foreground=t["text_main"],
            )
            self._style.map(
                f"{self._style_prefix}.TButton",
                background=[("active", t["button_hover"])],
                foreground=[("active", t["text_active"]), ("disabled", t["button_disabled"])],
            )
            self._style.configure(
                f"{self._style_prefix}.TEntry",
                fieldbackground=t["panel_bg"],
                foreground=t["text_main"],
            )
            self._style.configure(
                f"{self._style_prefix}.TCombobox",
                fieldbackground=t["panel_bg"],
                foreground=t["text_main"],
                background=t["button_bg"],
                arrowcolor=t["text_main"],
            )
            self._style.map(
                f"{self._style_prefix}.TCombobox",
                fieldbackground=[("readonly", t["panel_bg"])],
                selectbackground=[("readonly", t["accent"])],
                selectforeground=[("readonly", t["text_on_accent"])],
            )
            self._style.configure(
                f"{self._style_prefix}.Treeview",
                background=t["panel_bg"],
                foreground=t["text_main"],
                fieldbackground=t["panel_bg"],
                bordercolor=t["border"],
            )
            self._style.map(
                f"{self._style_prefix}.Treeview",
                background=[("selected", t["accent"])],
                foreground=[("selected", t["text_on_accent"])],
            )
            self._style.configure(
                f"{self._style_prefix}.Treeview.Heading",
                background=t["button_bg"],
                foreground=t["text_main"],
            )
            self._style.configure(
                f"{self._style_prefix}.TRadiobutton",
                background=t["panel_bg"],
                foreground=t["text_main"],
            )
            self._style.map(
                f"{self._style_prefix}.TRadiobutton",
                background=[("active", t["panel_bg"])],
                foreground=[("active", t["text_active"])],
            )
            self._style.configure(
                f"{self._style_prefix}.TCheckbutton",
                background=t["content_bg"],
                foreground=t["text_main"],
            )
        except Exception:
            pass

        try:
            self.frame.configure(style=f"{self._style_prefix}.TFrame")
        except Exception:
            pass
        self._apply_ttk_theme_tree(self.frame)

        for tk_frame in (self._header,):
            try:
                tk_frame.configure(bg=t["sidebar_bg"])
            except Exception:
                pass

        for label in (self._status_dot, self._conn_label, self._session_status_lbl):
            try:
                label.configure(bg=t["sidebar_bg"])
            except Exception:
                pass
        for label, fg in (
            (self._status_dot, _CLR_WARN if not self._connected else _CLR_OK),
            (self._conn_label, _CLR_OK if self._connected else t["text_muted"]),
            (self._session_status_lbl, _CLR_OK if (_LIVE_SESSION and _LIVE_SESSION.is_live()) else t["text_muted"]),
        ):
            try:
                label.configure(fg=fg)
            except Exception:
                pass

        for plain_label in self._header.winfo_children():
            if isinstance(plain_label, tk.Label) and plain_label not in (self._status_dot, self._conn_label, self._session_status_lbl):
                try:
                    plain_label.configure(bg=t["sidebar_bg"], fg=t["text_muted"])
                except Exception:
                    pass

        for widget in (
            self._chat_display,
            self._composer,
            self._system_txt,
            getattr(self, "_workshop_preview", None),
        ):
            if widget is None:
                continue
            try:
                bg = t["content_bg"] if widget is self._chat_display else t["panel_bg"]
                widget.configure(
                    background=bg,
                    foreground=t["text_main"],
                    insertbackground=t["text_main"],
                    selectbackground=t["accent"],
                    selectforeground=t["text_on_accent"],
                    highlightbackground=t["border"],
                    highlightcolor=t["accent"],
                )
            except Exception:
                pass

        try:
            self._drop_label.configure(bg=t["panel_bg"], fg=t["text_muted"])
        except Exception:
            pass

        for widget in (
            getattr(self, "_workshop_prompt_lb", None),
            getattr(self, "_workshop_map_lb", None),
        ):
            if widget is None:
                continue
            try:
                widget.configure(
                    background=t["panel_bg"],
                    foreground=t["text_main"],
                    selectbackground=t["accent"],
                    selectforeground=t["text_on_accent"],
                    highlightbackground=t["border"],
                    highlightcolor=t["accent"],
                )
            except Exception:
                pass

        for label in (
            self._system_hint,
            self._session_hint,
            self._scan_status_lbl,
            self._attach_badge,
            self._status_label,
            getattr(self, "_workshop_status_lbl", None),
        ):
            if label is None:
                continue
            try:
                label.configure(style=f"{self._style_prefix}.Muted.TLabel")
            except Exception:
                pass

        self._configure_chat_tags()

    def _apply_ttk_theme_tree(self, widget):
        for child in widget.winfo_children():
            try:
                if isinstance(child, ttk.LabelFrame):
                    child.configure(style=f"{self._style_prefix}.TLabelframe")
                elif isinstance(child, ttk.Combobox):
                    child.configure(style=f"{self._style_prefix}.TCombobox")
                elif isinstance(child, ttk.Entry):
                    child.configure(style=f"{self._style_prefix}.TEntry")
                elif isinstance(child, ttk.Button):
                    child.configure(style=f"{self._style_prefix}.TButton")
                elif isinstance(child, ttk.Label):
                    style = f"{self._style_prefix}.Panel.TLabel" if child.master in (
                        getattr(self, "_left_pane", None),
                        getattr(self, "_right_pane", None),
                    ) else f"{self._style_prefix}.TLabel"
                    child.configure(style=style)
                elif isinstance(child, ttk.Frame):
                    child.configure(style=f"{self._style_prefix}.TFrame")
                elif isinstance(child, ttk.Treeview):
                    child.configure(style=f"{self._style_prefix}.Treeview")
                elif isinstance(child, ttk.Radiobutton):
                    child.configure(style=f"{self._style_prefix}.TRadiobutton")
                elif isinstance(child, ttk.Checkbutton):
                    child.configure(style=f"{self._style_prefix}.TCheckbutton")
            except Exception:
                pass
            self._apply_ttk_theme_tree(child)

    def _update_session_status(self):
        s = _LIVE_SESSION
        if s is None or not s.is_live():
            self._session_status_var.set("No session")
            self._session_status_lbl.configure(fg=self._theme_tokens["text_muted"])
        else:
            msg_count = len(s.history)
            keep_alive = "keep-alive on" if s.keep_alive else "keep-alive off"
            self._session_status_var.set(f"● session • {msg_count} msg(s) • {s.created_at} • {keep_alive}")
            self._session_status_lbl.configure(fg=_CLR_OK)

    def _rebuild_chat_from_history(self):
        d = self._chat_display
        d.configure(state="normal")
        d.delete("1.0", "end")
        d.configure(state="disabled")
        self._append_chat_meta("Ollama Workstation — connect, choose a model, and start a session.")
        for turn in self._session.history:
            role = turn.get("role", "")
            text = turn.get("display") or turn.get("content", "")
            if role == "user":
                self._append_chat_user(text)
            elif role == "assistant":
                self._append_chat_ai(text)

    def _append_chat_user(self, text):
        d = self._chat_display
        d.configure(state="normal")
        d.insert("end", "\n", "separator")
        d.insert("end", "You\n", "user_name")
        d.insert("end", text + "\n", "user_msg")
        d.configure(state="disabled")
        d.see("end")

    def _append_chat_ai(self, text, meta=""):
        d = self._chat_display
        d.configure(state="normal")
        d.insert("end", "\n", "separator")
        short = (self._selected_model.split(":")[0] if ":" in self._selected_model else self._selected_model) or "AI"
        d.insert("end", f"{short}\n", "ai_name")
        d.insert("end", text + "\n", "ai_msg")
        if meta:
            d.insert("end", meta + "\n", "meta")
        d.configure(state="disabled")
        d.see("end")

    def _append_chat_meta(self, text):
        d = self._chat_display
        d.configure(state="normal")
        d.insert("end", "\n" + text + "\n", "meta")
        d.configure(state="disabled")
        d.see("end")

    def _show_thinking(self):
        d = self._chat_display
        d.configure(state="normal")
        d.insert("end", "\n", "separator")
        short = (self._selected_model.split(":")[0] if ":" in self._selected_model else self._selected_model) or "AI"
        d.insert("end", f"{short}\n", "ai_name")
        mark_line = int(d.index("end-1c").split(".")[0])
        d.insert("end", "Thinking…\n", "thinking")
        d.configure(state="disabled")
        d.see("end")
        return mark_line

    def _remove_thinking(self, mark_line):
        d = self._chat_display
        d.configure(state="normal")
        try:
            delete_from = max(1, mark_line - 2)
            d.delete(f"{delete_from}.0", "end")
        except Exception:
            pass
        d.configure(state="disabled")

    def _copy_chat_selection(self, event=None):
        try:
            text = self._chat_display.get("sel.first", "sel.last")
            if text:
                self.frame.clipboard_clear()
                self.frame.clipboard_append(text)
                self._set_status(f"Copied {len(text)} chars.")
        except tk.TclError:
            pass
        return "break"

    def _on_composer_return(self, event=None):
        self._on_send()
        return "break"

    def _on_composer_shift_return(self, event=None):
        self._composer.insert("insert", "\n")
        return "break"

    def _check_connection(self):
        url = self._url_var.get().strip()
        if url:
            self._client.base_url = url.rstrip("/")
            self._session.base_url = url.rstrip("/")

        self._set_status("Checking connection…")
        self._conn_label.configure(text="Checking…", fg=_CLR_WARN)
        self._status_dot.configure(fg=_CLR_WARN)

        def _bg():
            ping = self._client.ping()
            models_result = self._client.list_models() if ping["ok"] else None
            self.frame.after(0, lambda: self._apply_connection(ping, models_result))

        threading.Thread(target=_bg, daemon=True).start()

    def _apply_connection(self, ping, models_result):
        if ping["ok"]:
            self._connected = True
            version = ping.get("version") or ""
            label = "Connected" + (f" (v{version})" if version else "")
            self._conn_label.configure(text=label, fg=_CLR_OK)
            self._status_dot.configure(fg=_CLR_OK)

            if models_result and models_result["ok"]:
                self._models = models_result["models"]
                names = [m["name"] for m in self._models]
                self._model_combo.configure(values=names)
                if names:
                    if self._selected_model not in names:
                        self._model_var.set(names[0])
                        self._selected_model = names[0]
                    else:
                        self._model_var.set(self._selected_model)
                self._set_status(f"Connected. {len(names)} model(s) available.")
            else:
                err = (models_result or {}).get("error", "unknown")
                self._set_status(f"Connected but model list failed: {err}")
        else:
            self._connected = False
            self._conn_label.configure(text="Disconnected", fg=_CLR_ERR)
            self._status_dot.configure(fg=_CLR_ERR)
            self._set_status(f"Connection failed: {ping.get('error', 'unknown')}")

        self._refresh_debug_info()
        self._update_session_status()

    def _on_model_select(self, event=None):
        self._selected_model = self._model_var.get()
        self._set_status(f"Model: {self._selected_model}")
        self._refresh_debug_info()

    def _refresh_debug_info(self):
        parts = [
            f"Base URL: {self._client.base_url}",
            f"Connected: {self._connected}",
            f"Models loaded: {len(self._models)}",
            f"Selected: {self._selected_model or '(none)'}",
            f"Attachments: {len(self._attachments)}",
            f"History turns: {len(self._history)}",
            f"Context mode: {self._context_mode_var.get() if hasattr(self, '_context_mode_var') else self._session.context_mode}",
            f"Keep-alive: {self._session.keep_alive}",
            f"Session since: {self._session.created_at}",
        ]
        self._debug_info_var.set("\n".join(parts))

    def _choose_file(self):
        paths = filedialog.askopenfilenames(title="Choose file(s) to attach", filetypes=[("All files", "*.*")])
        for path in paths:
            self._add_attachment(path, is_dir=False)
        self._refresh_attach_display()
        self._update_attach_badge()

    def _choose_directory(self):
        directory = filedialog.askdirectory(title="Choose directory to scan")
        if directory:
            self._scan_directory(directory)

    def _scan_directory(self, root_path):
        if self._scanning:
            self._set_status("Scan already in progress.")
            return
        self._scanning = True
        self._scan_cancel = False
        self._cancel_btn.grid()
        self._scan_status_var.set("Scanning…")

        def _bg():
            count = 0
            total_bytes = 0
            try:
                for dirpath, dirnames, filenames in os.walk(root_path):
                    if self._scan_cancel:
                        break
                    dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__"]
                    for fname in sorted(filenames):
                        if self._scan_cancel or count >= MAX_SCAN_FILES:
                            break
                        if fname.startswith("."):
                            continue
                        fpath = os.path.join(dirpath, fname)
                        try:
                            fsize = os.path.getsize(fpath)
                        except OSError:
                            fsize = 0
                        ext = os.path.splitext(fname)[1].lower()
                        readable = ext in READABLE_EXTENSIONS
                        if readable and (total_bytes + fsize) > MAX_SCAN_BYTES:
                            readable = False
                        entry = {
                            "path": fpath,
                            "name": fname,
                            "is_dir": False,
                            "readable": readable,
                            "ext": ext,
                            "size": fsize,
                            "status": "readable" if readable else "skipped",
                        }
                        self._attachments.append(entry)
                        if readable:
                            total_bytes += fsize
                        count += 1
                        if count % 10 == 0:
                            self.frame.after(0, lambda c=count: self._scan_status_var.set(f"Scanning… {c} files"))
                    if count >= MAX_SCAN_FILES:
                        break
            except Exception as exc:
                self.frame.after(0, lambda: self._set_status(f"Scan error: {exc}"))
            finally:
                cancelled = self._scan_cancel
                self._scanning = False
                self._scan_cancel = False

                def _finish():
                    self._cancel_btn.grid_remove()
                    suffix = " (cancelled)" if cancelled else ""
                    self._scan_status_var.set(f"Done: {count} files{suffix}")
                    self._refresh_attach_display()
                    self._update_attach_badge()
                    self._set_status(f"Directory scan complete: {count} file(s){suffix}.")

                self.frame.after(0, _finish)

        threading.Thread(target=_bg, daemon=True).start()

    def _cancel_scan(self):
        self._scan_cancel = True
        self._scan_status_var.set("Cancelling…")

    def _add_attachment(self, path, is_dir=False):
        for attachment in self._attachments:
            if attachment["path"] == path:
                return
        ext = os.path.splitext(path)[1].lower()
        readable = ext in READABLE_EXTENSIONS
        try:
            size = os.path.getsize(path) if not is_dir else 0
        except OSError:
            size = 0
        self._attachments.append({
            "path": path,
            "name": os.path.basename(path),
            "is_dir": is_dir,
            "readable": readable,
            "ext": ext,
            "size": size,
            "status": "readable" if readable else "skipped",
        })

    def _refresh_attach_display(self):
        self._attach_tree.delete(*self._attach_tree.get_children())
        for idx, attachment in enumerate(self._attachments):
            self._attach_tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(attachment["name"], attachment.get("ext", ""), self._fmt_size(attachment["size"]), attachment["status"]),
            )
        count = len(self._attachments)
        self._attach_count_var.set(f"{count} file{'s' if count != 1 else ''}")
        if count == 0:
            self._drop_label.place(relx=0.5, rely=0.5, anchor="center")
        else:
            self._drop_label.place_forget()
        self._refresh_debug_info()

    def _remove_selected_attachments(self):
        selection = self._attach_tree.selection()
        if not selection:
            return
        for idx in sorted([int(s) for s in selection], reverse=True):
            if 0 <= idx < len(self._attachments):
                del self._attachments[idx]
        self._refresh_attach_display()
        self._update_attach_badge()

    def _clear_attachments(self):
        self._attachments.clear()
        self._refresh_attach_display()
        self._update_attach_badge()
        self._scan_status_var.set("")
        self._set_status("Attachments cleared.")

    def _update_attach_badge(self):
        count = len(self._attachments)
        mode = self._context_mode_var.get().replace("_", " ")
        if count:
            self._attach_badge_var.set(f"📎 {count} file{'s' if count != 1 else ''} attached • {mode}")
        else:
            self._attach_badge_var.set("")
        if hasattr(self, "_utility_buttons"):
            self._refresh_utility_sections()

    @staticmethod
    def _fmt_size(size):
        if size < 1024:
            return f"{size} B"
        if size < 1048576:
            return f"{size / 1024:.1f} KB"
        return f"{size / 1048576:.1f} MB"

    def _on_context_mode_change(self):
        self._session.context_mode = self._context_mode_var.get()
        self._update_attach_badge()
        self._refresh_debug_info()

    def _assemble_context(self) -> str:
        if not self._attachments:
            return ""
        mode = self._context_mode_var.get()
        parts = []
        total_read = 0
        for attachment in self._attachments:
            path = attachment["path"]
            if mode == "paths_only":
                parts.append(f"[attached] {path}")
                continue
            if attachment["readable"] and attachment["status"] == "readable":
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as fh:
                        budget = MAX_SCAN_BYTES - total_read
                        if budget <= 0:
                            parts.append(f"[attached: budget exceeded] {path}")
                            continue
                        content = fh.read(budget)
                        total_read += len(content.encode("utf-8", errors="replace"))
                        parts.append(f"--- {path} ---\n{content}\n--- end {os.path.basename(path)} ---")
                except Exception as exc:
                    parts.append(f"[attached: read error: {exc}] {path}")
            else:
                parts.append(f"[attached: binary/skipped] {path}")
        return "\n\n".join(parts)

    def _on_send(self):
        model = self._model_var.get().strip()
        if not model or model == "(none)":
            self._set_status("Select a model first.")
            return
        if not self._connected:
            self._set_status("Not connected to Ollama — check URL and refresh.")
            return
        user_text = self._composer.get("1.0", "end-1c").strip()
        if not user_text:
            self._set_status("Type a message first.")
            return

        visible_system_text = self._system_txt.get("1.0", "end-1c").strip()
        system_text = visible_system_text.replace("<<user_input>>", user_text) if "<<user_input>>" in visible_system_text else visible_system_text
        self._session.system_prompt = visible_system_text
        self._session.context_mode = self._context_mode_var.get()
        self._session.base_url = self._url_var.get().strip()
        try:
            self._session.temperature = self._temp_var.get()
        except Exception:
            pass

        context = self._assemble_context()
        full_user = f"{user_text}\n\n--- Attached Context ---\n{context}" if context else user_text

        try:
            temperature = float(self._temp_var.get())
            temperature = max(0.0, min(2.0, temperature))
        except ValueError:
            temperature = 0.7

        self._append_chat_user(user_text)
        if self._attachments:
            count = len(self._attachments)
            mode = self._context_mode_var.get().replace("_", " ")
            self._append_chat_meta(f"📎 {count} file{'s' if count != 1 else ''} attached ({mode})")

        self._composer.delete("1.0", "end")
        self._history.append({"role": "user", "content": full_user, "display": user_text})

        messages = []
        if system_text:
            messages.append({"role": "system", "content": system_text})
        for turn in self._history:
            messages.append({"role": turn["role"], "content": turn["content"]})

        thinking_mark = self._show_thinking()
        self._send_btn.configure(state="disabled")
        self._set_status(f"Sending to {model}…")

        def _bg():
            result = self._client.chat(model=model, messages=messages, temperature=temperature)
            self.frame.after(
                0,
                lambda: self._handle_response(
                    result,
                    model,
                    system_text,
                    user_text,
                    full_user,
                    temperature,
                    thinking_mark,
                ),
            )

        threading.Thread(target=_bg, daemon=True).start()

    def _handle_response(self, result, model, system_text, user_text, full_user, temperature, thinking_mark):
        self._send_btn.configure(state="normal")
        self._remove_thinking(thinking_mark)

        if result["ok"]:
            content = result["content"]
            self._last_response = content

            duration_ns = result.get("total_duration", 0)
            eval_count = result.get("eval_count", 0)
            duration_s = duration_ns / 1e9 if duration_ns else 0
            meta_parts = []
            if duration_s:
                meta_parts.append(f"{duration_s:.1f}s")
            if eval_count:
                meta_parts.append(f"{eval_count} tokens")
            meta = " • ".join(meta_parts)

            self._append_chat_ai(content, meta=meta)
            self._history.append({"role": "assistant", "content": content})
            self._last_exchange = {
                "timestamp": datetime.datetime.now().isoformat(),
                "model": model,
                "temperature": temperature,
                "system_prompt": system_text,
                "user_prompt": user_text,
                "context_mode": self._context_mode_var.get(),
                "attachments": [
                    {"path": a["path"], "status": a["status"], "readable": a["readable"]}
                    for a in self._attachments
                ],
                "full_user_content": full_user,
                "response": content,
                "total_duration_ns": result.get("total_duration", 0),
                "eval_count": result.get("eval_count", 0),
            }
            self._set_status(f"Response received ({len(content)} chars).")
        else:
            err = result.get("error", "unknown error")
            self._last_response = ""
            self._append_chat_ai(f"[Error] {err}")
            self._set_status(f"Request failed: {err}")

        self._update_session_status()
        self._refresh_debug_info()
        self._composer.focus_set()

    def _copy_response(self):
        text = self._last_response
        if not text:
            self._set_status("No response to copy.")
            return
        try:
            self.frame.clipboard_clear()
            self.frame.clipboard_append(text)
            self._set_status(f"Copied {len(text)} chars to clipboard.")
        except Exception as exc:
            self._set_status(f"Clipboard error: {exc}")

    def _save_response(self):
        text = self._last_response
        if not text:
            self._set_status("No response to save.")
            return
        path = filedialog.asksaveasfilename(
            title="Save Response",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Text", "*.txt"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            self._set_status(f"Response saved: {path}")
        except Exception as exc:
            messagebox.showerror("Save Error", f"Failed to save:\n{exc}")

    def _save_chat(self):
        if not self._history:
            self._set_status("No conversation to save.")
            return
        path = filedialog.asksaveasfilename(
            title="Save Chat",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Text", "*.txt"), ("JSON", "*.json"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext == ".json":
                export = {
                    "timestamp": datetime.datetime.now().isoformat(),
                    "model": self._selected_model,
                    "system_prompt": self._system_txt.get("1.0", "end-1c").strip(),
                    "turns": self._history,
                }
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(export, fh, indent=2, ensure_ascii=False)
            else:
                lines = [
                    "# Chat Log",
                    f"**Date:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    f"**Model:** {self._selected_model}",
                    "",
                    "---",
                    "",
                ]
                for turn in self._history:
                    role = turn["role"].capitalize()
                    text = turn.get("display") or turn["content"]
                    lines += [f"### {role}", "", text, "", "---", ""]
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(lines) + "\n")
            self._set_status(f"Chat saved: {path}")
        except Exception as exc:
            messagebox.showerror("Save Error", f"Failed to save chat:\n{exc}")

    def _clear_chat(self):
        self._history.clear()
        self._last_response = ""
        self._last_exchange = {}
        self._chat_display.configure(state="normal")
        self._chat_display.delete("1.0", "end")
        self._chat_display.configure(state="disabled")
        self._append_chat_meta("Chat cleared. Type a message below to start a new conversation.")
        self._set_status("Chat cleared.")
        self._update_session_status()
        self._refresh_debug_info()

    def _save_exchange_bundle(self):
        if not self._last_exchange:
            self._set_status("No exchange to save — send a prompt first.")
            return
        folder = filedialog.askdirectory(title="Choose folder for exchange bundle")
        if not folder:
            return

        now = datetime.datetime.now()
        stamp = now.strftime("%Y%m%d_%H%M%S")
        bundle_dir = os.path.join(folder, f"exchange_{stamp}")
        os.makedirs(bundle_dir, exist_ok=True)

        ex = self._last_exchange
        with open(os.path.join(bundle_dir, "exchange.json"), "w", encoding="utf-8") as fh:
            json.dump(ex, fh, indent=2, ensure_ascii=False)

        summary_lines = [
            "# Exchange Summary",
            f"**Date:** {ex.get('timestamp', '')}",
            f"**Model:** {ex.get('model', '')}",
            f"**Temperature:** {ex.get('temperature', '')}",
            "",
            "## System Prompt",
            ex.get("system_prompt", "(none)") or "(none)",
            "",
            "## User Prompt",
            ex.get("user_prompt", ""),
            "",
            "## Attachments",
            f"Mode: {ex.get('context_mode', 'paths_only')}",
        ]
        for att in ex.get("attachments", []):
            summary_lines.append(f"- {att['path']}  [{att['status']}]")
        summary_lines += [
            "",
            "## Response",
            ex.get("response", ""),
            "",
            "---",
            f"*Duration: {ex.get('total_duration_ns', 0) / 1e9:.1f}s | Tokens: {ex.get('eval_count', 0)}*",
        ]
        with open(os.path.join(bundle_dir, "exchange_summary.md"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(summary_lines) + "\n")

        with open(os.path.join(bundle_dir, "attachment_manifest.json"), "w", encoding="utf-8") as fh:
            json.dump({"context_mode": ex.get("context_mode", "paths_only"), "files": ex.get("attachments", [])}, fh, indent=2, ensure_ascii=False)

        with open(os.path.join(bundle_dir, "settings_metadata.json"), "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "model": ex.get("model", ""),
                    "temperature": ex.get("temperature", 0.7),
                    "base_url": self._client.base_url,
                    "timestamp": ex.get("timestamp", ""),
                    "total_duration_ns": ex.get("total_duration_ns", 0),
                    "eval_count": ex.get("eval_count", 0),
                },
                fh,
                indent=2,
                ensure_ascii=False,
            )

        with open(os.path.join(bundle_dir, "conversation_history.json"), "w", encoding="utf-8") as fh:
            json.dump({"turns": self._history}, fh, indent=2, ensure_ascii=False)

        self._set_status(f"Bundle saved: {bundle_dir}")
