"""
page_audio_router / audio_router_page.py
────────────────────────────────────────────────────────────────────────────────
Manual Linux desktop audio router page for pagepack_chilos (Guichi v1).

Shell contract:
    page = PageAudioRouter(parent_widget)
    page.build(parent)          # also: create_widgets / mount / render

Backend:
    subprocess calls to `pactl` (primary) and optionally `wpctl` (diagnostic).
    No third-party Python dependencies. No daemons. No background polling.
    No work at import time beyond defining the class.

Layout:
    Top bar      — Refresh / Set Default / Move Stream / wpctl status
    Body         — notebook with Router and Speaker Map tabs
    Status / log — bottom: read-only Text with timestamped messages
"""

import datetime
import json
import os
import re
import shutil
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import simpledialog, ttk

from gui_files import interaction_support


_DEFAULT_PAGE_THEME = {
    "app_bg": "#1e1e1e",
    "content_bg": "#1e1e1e",
    "panel_bg": "#2e2e2e",
    "sidebar_bg": "#2a2a2a",
    "text_main": "#c0c0c0",
    "text_muted": "#909090",
    "text_active": "#d0d0d0",
    "text_on_accent": "#ffffff",
    "button_bg": "#333333",
    "button_hover": "#444444",
    "button_active": "#ffffff",
    "button_disabled": "#555555",
    "accent": "#40c0c0",
    "border": "#444444",
}

_DISPLAY_SIZE_PRESETS = {
    "small": (170, 88),
    "medium": (220, 112),
    "large": (280, 142),
}

_DISPLAY_NUDGE = 24
_DISPLAY_LAYOUT_PADDING = 18
_DISPLAY_GAP = 18
_DISPLAY_ZOOM_FACTORS = {
    "25%": 0.25,
    "50%": 0.5,
    "75%": 0.75,
    "100%": 1.0,
    "125%": 1.25,
    "150%": 1.5,
    "200%": 2.0,
}
_DISPLAY_SOFT_SNAP = 12
_ALL_OUTPUTS_SINK_NAME = "pychi_all_outputs_sink"


def _bind_scroll(widget):
    """Use the Guichi universal wheel-binding helper."""
    interaction_support.bind_wheel_scroll(widget)


def _run(argv, timeout=5):
    """
    Run a command, capture stdout/stderr, never raise into the caller.
    Returns: {"rc": int, "stdout": str, "stderr": str, "error": str|None}
    """
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout
        )
        return {
            "rc": result.returncode,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "error": None,
        }
    except FileNotFoundError:
        return {
            "rc": -1,
            "stdout": "",
            "stderr": "",
            "error": f"command not found: {argv[0]}",
        }
    except subprocess.TimeoutExpired:
        return {
            "rc": -1,
            "stdout": "",
            "stderr": "",
            "error": f"timeout after {timeout}s: {' '.join(argv)}",
        }
    except Exception as ex:
        return {
            "rc": -1,
            "stdout": "",
            "stderr": "",
            "error": f"{type(ex).__name__}: {ex}",
        }


def _parse_sinks_short(stdout):
    """
    Parse `pactl list short sinks` output. Columns are tab-separated:
        <id>\t<name>\t<driver>\t<sample_spec>\t<state>
    Returns list of {"id", "name", "state"} dicts; skips malformed lines.
    """
    out = []
    for line in stdout.splitlines():
        line = line.rstrip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        out.append(
            {
                "id": parts[0].strip(),
                "name": parts[1].strip(),
                "state": parts[4].strip() if len(parts) >= 5 else "",
            }
        )
    return out


def _parse_sink_inputs(stdout):
    """
    Parse `pactl list sink-inputs` (verbose). Best-effort extraction of
    id, current sink index, and stream-identifying metadata for each entry.
    Returns list of {"id", "sink_id", "app_name", "media_name", "process_binary"} dicts.
    """
    streams = []
    cur = None
    for raw in stdout.splitlines():
        line = raw.rstrip()
        match = re.match(r"^Sink Input #(\d+)", line)
        if match:
            if cur is not None:
                streams.append(cur)
            cur = {
                "id": match.group(1),
                "sink_id": "",
                "app_name": "",
                "media_name": "",
                "process_binary": "",
            }
            continue
        if cur is None:
            continue
        stripped = line.strip()
        if stripped.startswith("Sink:"):
            cur["sink_id"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("application.name") and "=" in stripped:
            cur["app_name"] = stripped.split("=", 1)[1].strip().strip('"')
        elif stripped.startswith("media.name") and "=" in stripped:
            cur["media_name"] = stripped.split("=", 1)[1].strip().strip('"')
        elif stripped.startswith("application.process.binary") and "=" in stripped:
            cur["process_binary"] = stripped.split("=", 1)[1].strip().strip('"')
    if cur is not None:
        streams.append(cur)
    return streams


def _derive_display_label(sink_name, alias=""):
    """Turn a sink name into a usable seeded display label."""
    if alias.strip():
        return alias.strip()
    base = sink_name.rsplit(".", 1)[-1]
    base = base.replace("__", " ").replace("_", " ")
    parts = [part for part in re.split(r"\s+", base) if part]
    if not parts:
        return sink_name
    words = []
    for part in parts:
        lower = part.lower()
        if lower in {"sink", "output", "alsa"}:
            continue
        words.append(part.upper() if part.isupper() else part.capitalize())
    return " ".join(words) or sink_name


class PageAudioRouter:
    """
    Linux audio router page.

    Shell contract (Guichi loader):
        page = PageAudioRouter(parent_frame)
        page.build(parent)   # also: create_widgets / mount / render
    """

    PAGE_NAME = "audio_router"

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
        self._style_prefix = f"AudioRouter.{id(self)}"

        self._have_pactl = bool(shutil.which("pactl"))
        self._have_wpctl = bool(shutil.which("wpctl"))

        self._sinks = []
        self._streams = []
        self._default_sink = ""
        self._sink_aliases = {}

        self._display_boxes = []
        self._next_display_id = 1
        self._selected_display_id = None
        self._layout_presets = {}
        self._routing_rules = []
        self._next_rule_id = 1
        self._auto_apply_rules = False
        self._stream_manual_overrides = {}

        self._var_default = None
        self._var_status = None
        self._var_auto_apply_rules = None
        self._var_rule_keyword = None
        self._var_rule_target = None
        self._lb_sinks = None
        self._lb_streams = None
        self._txt_log = None
        self._btn_refresh = None
        self._btn_default = None
        self._btn_move = None
        self._btn_wpctl = None
        self._btn_apply_rules = None
        self._btn_all_outputs = None
        self._sink_menu = None
        self._stream_menu = None
        self._map_stream_menu = None
        self._routing_rule_menu = None
        self._display_menu = None
        self._style = None
        self._top_bar = None
        self._body_frame = None
        self._log_outer = None
        self._status_bar = None
        self._default_label = None
        self._status_label = None
        self._notebook = None
        self._router_tab = None
        self._map_tab = None
        self._map_canvas = None
        self._map_stream_tabs = None
        self._map_streams_tab = None
        self._keyword_assigner_tab = None
        self._speaker_support_tabs = None
        self._inactive_speakers_tab = None
        self._layout_presets_tab = None
        self._log_tab = None
        self._map_streams = None
        self._staging_list = None
        self._preset_list = None
        self._routing_rule_list = None
        self._rule_target_menu = None
        self._display_detail_var = None
        self._display_zoom_var = None
        self._display_zoom = 1.0
        self._map_canvas_xscroll = None
        self._map_canvas_yscroll = None
        self._box_items = {}
        self._drag_display_id = None
        self._drag_offset_x = 0.0
        self._drag_offset_y = 0.0
        self._all_outputs_module_id = ""
        self._all_outputs_previous_default = ""

        self._config_path = os.path.join(
            Path(__file__).resolve().parent, "audio_router_config.json"
        )

        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)

        self._build_top_bar()
        self._build_body()
        self._build_status_bar()
        self._apply_theme()

        self.frame.after(100, self._initial_refresh)

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
                self._build_body()
                self._build_status_bar()
                self._apply_theme()
                self.frame.after(50, self._initial_refresh)
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
        bar = ttk.Frame(
            self.frame, padding=(4, 4), style=f"{self._style_prefix}.TFrame"
        )
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(99, weight=1)
        self._top_bar = bar

        self._btn_refresh = ttk.Button(
            bar,
            text="Refresh",
            width=10,
            command=self._on_refresh,
            style=f"{self._style_prefix}.TButton",
        )
        self._btn_refresh.grid(row=0, column=0, padx=2)

        self._btn_default = ttk.Button(
            bar,
            text="Set Selected Sink as Default",
            command=self._on_set_default,
            style=f"{self._style_prefix}.TButton",
        )
        self._btn_default.grid(row=0, column=1, padx=2)

        self._btn_move = ttk.Button(
            bar,
            text="Move Stream → Selected Sink",
            command=self._on_move_stream,
            style=f"{self._style_prefix}.TButton",
        )
        self._btn_move.grid(row=0, column=2, padx=2)

        self._btn_wpctl = ttk.Button(
            bar,
            text="wpctl status",
            command=self._on_wpctl_status,
            style=f"{self._style_prefix}.TButton",
        )
        self._btn_wpctl.grid(row=0, column=3, padx=2)

        self._btn_apply_rules = ttk.Button(
            bar,
            text="Apply Rules",
            command=self._on_apply_rules,
            style=f"{self._style_prefix}.TButton",
        )
        self._btn_apply_rules.grid(row=0, column=4, padx=2)

        self._var_default = tk.StringVar(value="Default sink: (unknown)")
        self._default_label = ttk.Label(
            bar,
            textvariable=self._var_default,
            anchor="e",
            style=f"{self._style_prefix}.Muted.TLabel",
        )
        self._default_label.grid(row=0, column=99, sticky="ew", padx=8)

    def _build_body(self):
        body = ttk.Frame(
            self.frame, padding=(4, 2), style=f"{self._style_prefix}.TFrame"
        )
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self._body_frame = body

        notebook = ttk.Notebook(body)
        notebook.grid(row=0, column=0, sticky="nsew")
        self._notebook = notebook

        map_tab = ttk.Frame(notebook, style=f"{self._style_prefix}.TFrame")
        map_tab.columnconfigure(0, weight=5, minsize=320)
        map_tab.columnconfigure(1, weight=6, minsize=360)
        map_tab.rowconfigure(0, weight=1)
        map_tab.rowconfigure(1, weight=0)
        map_tab.rowconfigure(2, weight=0)
        self._map_tab = map_tab
        notebook.add(map_tab, text="Speaker Map")

        self._build_map_tab()

        router_tab = ttk.Frame(notebook, style=f"{self._style_prefix}.TFrame")
        router_tab.columnconfigure(0, weight=1, minsize=260)
        router_tab.columnconfigure(1, weight=1, minsize=260)
        router_tab.rowconfigure(0, weight=1)
        self._router_tab = router_tab
        notebook.add(router_tab, text="Router")

        self._lb_sinks = self._build_list_pane(router_tab, 0, 0, "Outputs (sinks)")
        self._lb_streams = self._build_list_pane(
            router_tab, 0, 1, "Active Streams (sink-inputs)"
        )
        self._bind_router_context_menus()

    def _build_map_tab(self):
        canvas_outer = ttk.LabelFrame(
            self._map_tab,
            text="",
            padding=(4, 4),
            style=f"{self._style_prefix}.TLabelframe",
        )
        canvas_outer.grid(row=0, column=0, columnspan=2, sticky="nsew")
        canvas_outer.columnconfigure(0, weight=1)
        canvas_outer.columnconfigure(1, weight=0)
        canvas_outer.rowconfigure(1, weight=1)
        canvas_outer.rowconfigure(2, weight=0)

        header_row = ttk.Frame(canvas_outer, style=f"{self._style_prefix}.TFrame")
        header_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        header_row.columnconfigure(0, weight=1)
        ttk.Label(
            header_row,
            text="Speaker Layout",
            style=f"{self._style_prefix}.Status.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self._btn_all_outputs = ttk.Button(
            header_row,
            text="All Outputs: Off",
            command=self._toggle_all_outputs,
            style=f"{self._style_prefix}.TButton",
        )
        self._btn_all_outputs.grid(row=0, column=1, sticky="e")

        self._map_canvas = tk.Canvas(
            canvas_outer,
            height=420,
            highlightthickness=1,
            borderwidth=0,
            relief="solid",
        )
        self._map_canvas.grid(row=1, column=0, sticky="nsew")
        self._map_canvas_xscroll = ttk.Scrollbar(
            canvas_outer, orient="horizontal", command=self._map_canvas.xview
        )
        self._map_canvas_xscroll.grid(row=2, column=0, sticky="ew")
        self._map_canvas_yscroll = ttk.Scrollbar(
            canvas_outer, orient="vertical", command=self._map_canvas.yview
        )
        self._map_canvas_yscroll.grid(row=1, column=1, sticky="ns")
        self._map_canvas.configure(
            xscrollcommand=self._map_canvas_xscroll.set,
            yscrollcommand=self._map_canvas_yscroll.set,
        )
        self._map_canvas.bind("<Button-1>", self._on_map_canvas_click, add="+")
        self._map_canvas.bind("<Button-3>", self._on_map_canvas_right_click, add="+")
        self._map_canvas.bind("<Control-Button-1>", self._on_map_canvas_right_click, add="+")
        self._map_canvas.bind("<Configure>", self._on_map_canvas_configure, add="+")
        self._map_canvas.bind("<B1-Motion>", self._on_map_canvas_drag, add="+")
        self._map_canvas.bind("<ButtonRelease-1>", self._on_map_canvas_release, add="+")
        self._map_canvas.bind("<MouseWheel>", self._on_map_canvas_mousewheel, add="+")
        self._map_canvas.bind("<Shift-MouseWheel>", self._on_map_canvas_mousewheel, add="+")
        self._map_canvas.bind("<Button-4>", self._on_map_canvas_mousewheel, add="+")
        self._map_canvas.bind("<Button-5>", self._on_map_canvas_mousewheel, add="+")

        details = ttk.LabelFrame(
            self._map_tab,
            text="Selected Speaker",
            padding=(6, 6),
            style=f"{self._style_prefix}.TLabelframe",
        )
        details.grid(row=1, column=0, sticky="nsew", padx=(0, 4), pady=(6, 0))
        details.columnconfigure(0, weight=1)
        details.rowconfigure(0, weight=1)
        self._display_detail_var = tk.StringVar(value="No speaker selected.")
        detail_label = ttk.Label(
            details,
            textvariable=self._display_detail_var,
            justify="left",
            wraplength=320,
            style=f"{self._style_prefix}.Status.TLabel",
        )
        detail_label.grid(row=0, column=0, sticky="ew")

        action_row = ttk.Frame(details, style=f"{self._style_prefix}.TFrame")
        action_row.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        action_row.columnconfigure(0, weight=1)
        action_row.columnconfigure(1, weight=1)
        ttk.Button(
            action_row,
            text="Rename Speaker",
            command=self._rename_selected_display,
            style=f"{self._style_prefix}.TButton",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ttk.Button(
            action_row,
            text="Place / Return",
            command=self._toggle_selected_display_placement,
            style=f"{self._style_prefix}.TButton",
        ).grid(row=0, column=1, sticky="ew", padx=(2, 0))
        ttk.Button(
            action_row,
            text="Label Mode",
            command=self._toggle_selected_display_label_mode,
            style=f"{self._style_prefix}.TButton",
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        zoom_row = ttk.Frame(details, style=f"{self._style_prefix}.TFrame")
        zoom_row.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(
            zoom_row,
            text="Zoom",
            style=f"{self._style_prefix}.Status.TLabel",
        ).grid(row=0, column=0, sticky="w", padx=(0, 6))
        self._display_zoom_var = tk.StringVar(value="100%")
        zoom_menu = ttk.OptionMenu(
            zoom_row,
            self._display_zoom_var,
            "100%",
            *list(_DISPLAY_ZOOM_FACTORS.keys()),
            command=self._on_display_zoom_change,
        )
        zoom_menu.grid(row=0, column=1, sticky="ew")
        zoom_row.columnconfigure(1, weight=1)

        streams_outer = ttk.LabelFrame(
            self._map_tab,
            text="Streams For Speaker Actions",
            padding=(4, 4),
            style=f"{self._style_prefix}.TLabelframe",
        )
        streams_outer.grid(row=1, column=1, sticky="nsew", padx=(4, 0), pady=(6, 0))
        streams_outer.columnconfigure(0, weight=1)
        streams_outer.rowconfigure(0, weight=1)
        self._map_stream_tabs = ttk.Notebook(streams_outer)
        self._map_stream_tabs.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self._map_streams_tab = ttk.Frame(self._map_stream_tabs, style=f"{self._style_prefix}.TFrame")
        self._map_streams_tab.columnconfigure(0, weight=1)
        self._map_streams_tab.rowconfigure(0, weight=1)
        self._keyword_assigner_tab = ttk.Frame(self._map_stream_tabs, style=f"{self._style_prefix}.TFrame")
        self._keyword_assigner_tab.columnconfigure(0, weight=1)
        self._keyword_assigner_tab.rowconfigure(2, weight=1)
        self._map_stream_tabs.add(self._map_streams_tab, text="Streams")
        self._map_stream_tabs.add(self._keyword_assigner_tab, text="Keyword Assigner")
        self._map_streams = tk.Listbox(
            self._map_streams_tab,
            height=10,
            selectmode="single",
            exportselection=False,
            font=("monospace", 9),
        )
        stream_scroll = ttk.Scrollbar(
            self._map_streams_tab, orient="vertical", command=self._map_streams.yview
        )
        self._map_streams.configure(yscrollcommand=stream_scroll.set)
        self._map_streams.grid(row=0, column=0, sticky="nsew")
        stream_scroll.grid(row=0, column=1, sticky="ns")
        _bind_scroll(self._map_streams)

        stream_actions = ttk.Frame(self._map_streams_tab, style=f"{self._style_prefix}.TFrame")
        stream_actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        stream_actions.columnconfigure(0, weight=1)
        stream_actions.columnconfigure(1, weight=1)
        ttk.Button(
            stream_actions,
            text="Set Default Speaker",
            command=self._set_default_from_selected_display,
            style=f"{self._style_prefix}.TButton",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ttk.Button(
            stream_actions,
            text="Move Stream To Speaker",
            command=self._move_map_stream_to_selected_display,
            style=f"{self._style_prefix}.TButton",
        ).grid(row=0, column=1, sticky="ew", padx=(2, 0))
        self._var_auto_apply_rules = tk.BooleanVar(value=False)
        auto_apply = ttk.Checkbutton(
            self._keyword_assigner_tab,
            text="Auto-apply on refresh",
            variable=self._var_auto_apply_rules,
            command=self._on_toggle_auto_apply_rules,
        )
        auto_apply.grid(row=0, column=0, sticky="w", columnspan=2, pady=(0, 4))

        add_rule_row = ttk.Frame(self._keyword_assigner_tab, style=f"{self._style_prefix}.TFrame")
        add_rule_row.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        add_rule_row.columnconfigure(0, weight=1)
        add_rule_row.columnconfigure(1, weight=0)
        add_rule_row.columnconfigure(2, weight=0)
        self._var_rule_keyword = tk.StringVar(value="")
        keyword_entry = ttk.Entry(
            add_rule_row,
            textvariable=self._var_rule_keyword,
        )
        keyword_entry.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 4))
        ttk.Label(
            add_rule_row,
            text="Route Matches To",
            style=f"{self._style_prefix}.Status.TLabel",
        ).grid(row=1, column=0, sticky="w", padx=(0, 6))
        self._var_rule_target = tk.StringVar(value="")
        self._rule_target_menu = ttk.OptionMenu(
            add_rule_row,
            self._var_rule_target,
            "",
        )
        self._rule_target_menu.grid(row=1, column=1, sticky="ew", padx=(0, 4))
        ttk.Button(
            add_rule_row,
            text="Add Keyword Rule",
            command=self._add_manual_keyword_rule,
            style=f"{self._style_prefix}.TButton",
        ).grid(row=1, column=2, sticky="ew")

        self._routing_rule_list = tk.Listbox(
            self._keyword_assigner_tab,
            height=7,
            selectmode="single",
            exportselection=False,
            font=("monospace", 9),
        )
        rule_scroll = ttk.Scrollbar(
            self._keyword_assigner_tab, orient="vertical", command=self._routing_rule_list.yview
        )
        self._routing_rule_list.configure(yscrollcommand=rule_scroll.set)
        self._routing_rule_list.grid(row=2, column=0, sticky="nsew")
        rule_scroll.grid(row=2, column=1, sticky="ns")
        _bind_scroll(self._routing_rule_list)

        rule_actions = ttk.Frame(self._keyword_assigner_tab, style=f"{self._style_prefix}.TFrame")
        rule_actions.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        rule_actions.columnconfigure(0, weight=1)
        rule_actions.columnconfigure(1, weight=1)
        rule_actions.columnconfigure(2, weight=1)
        ttk.Button(
            rule_actions,
            text="Add From Stream",
            command=self._add_rule_from_selected_stream,
            style=f"{self._style_prefix}.TButton",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ttk.Button(
            rule_actions,
            text="Apply Now",
            command=self._on_apply_rules,
            style=f"{self._style_prefix}.TButton",
        ).grid(row=0, column=1, sticky="ew", padx=2)
        ttk.Button(
            rule_actions,
            text="Delete Rule",
            command=self._delete_selected_routing_rule,
            style=f"{self._style_prefix}.TButton",
        ).grid(row=0, column=2, sticky="ew", padx=(2, 0))

        self._speaker_support_tabs = ttk.Notebook(self._map_tab)
        self._speaker_support_tabs.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(6, 0))
        self._inactive_speakers_tab = ttk.Frame(self._speaker_support_tabs, style=f"{self._style_prefix}.TFrame")
        self._inactive_speakers_tab.columnconfigure(0, weight=1)
        self._layout_presets_tab = ttk.Frame(self._speaker_support_tabs, style=f"{self._style_prefix}.TFrame")
        self._layout_presets_tab.columnconfigure(0, weight=1)
        self._layout_presets_tab.rowconfigure(0, weight=1)
        self._log_tab = ttk.Frame(self._speaker_support_tabs, style=f"{self._style_prefix}.TFrame")
        self._log_tab.columnconfigure(0, weight=1)
        self._log_tab.rowconfigure(0, weight=1)
        self._speaker_support_tabs.add(self._layout_presets_tab, text="Layout Presets")
        self._speaker_support_tabs.add(self._inactive_speakers_tab, text="Inactive Speakers")
        self._speaker_support_tabs.add(self._log_tab, text="Status / Log")
        self._speaker_support_tabs.select(self._layout_presets_tab)

        staging_outer = ttk.Frame(self._inactive_speakers_tab, style=f"{self._style_prefix}.TFrame")
        staging_outer.grid(row=0, column=0, sticky="nsew")
        staging_outer.columnconfigure(0, weight=1)
        self._staging_list = tk.Listbox(
            staging_outer,
            height=5,
            selectmode="single",
            exportselection=False,
            font=("monospace", 9),
        )
        self._staging_list.grid(row=0, column=0, sticky="ew")
        self._staging_list.bind("<<ListboxSelect>>", self._on_staging_select, add="+")
        self._staging_list.bind("<Double-Button-1>", self._on_staging_double_click, add="+")
        _bind_scroll(self._staging_list)

        presets_outer = ttk.Frame(self._layout_presets_tab, style=f"{self._style_prefix}.TFrame")
        presets_outer.grid(row=0, column=0, sticky="nsew")
        presets_outer.columnconfigure(0, weight=1)
        presets_outer.rowconfigure(0, weight=1)
        self._preset_list = tk.Listbox(
            presets_outer,
            height=6,
            selectmode="single",
            exportselection=False,
            font=("monospace", 9),
        )
        preset_scroll = ttk.Scrollbar(
            presets_outer, orient="vertical", command=self._preset_list.yview
        )
        self._preset_list.configure(yscrollcommand=preset_scroll.set)
        self._preset_list.grid(row=0, column=0, sticky="nsew")
        preset_scroll.grid(row=0, column=1, sticky="ns")
        _bind_scroll(self._preset_list)

        preset_actions = ttk.Frame(presets_outer, style=f"{self._style_prefix}.TFrame")
        preset_actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        preset_actions.columnconfigure(0, weight=1)
        preset_actions.columnconfigure(1, weight=1)
        preset_actions.columnconfigure(2, weight=1)
        preset_actions.columnconfigure(3, weight=1)
        ttk.Button(
            preset_actions,
            text="Save Current",
            command=self._save_layout_preset_prompt,
            style=f"{self._style_prefix}.TButton",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ttk.Button(
            preset_actions,
            text="Load",
            command=self._load_selected_layout_preset,
            style=f"{self._style_prefix}.TButton",
        ).grid(row=0, column=1, sticky="ew", padx=2)
        ttk.Button(
            preset_actions,
            text="Delete",
            command=self._delete_selected_layout_preset,
            style=f"{self._style_prefix}.TButton",
        ).grid(row=0, column=2, sticky="ew", padx=2)
        ttk.Button(
            preset_actions,
            text="Refresh",
            command=self._refresh_layout_presets_view,
            style=f"{self._style_prefix}.TButton",
        ).grid(row=0, column=3, sticky="ew", padx=(2, 0))

        log_outer = ttk.Frame(self._log_tab, style=f"{self._style_prefix}.TFrame")
        log_outer.grid(row=0, column=0, sticky="nsew")
        log_outer.columnconfigure(0, weight=1)
        log_outer.rowconfigure(0, weight=1)
        self._log_outer = log_outer

        mono = ("Consolas", 9) if os.name == "nt" else ("monospace", 9)
        self._txt_log = tk.Text(
            log_outer,
            wrap="word",
            height=8,
            state="disabled",
            font=mono,
            relief="solid",
            borderwidth=1,
        )
        scrollbar = ttk.Scrollbar(
            log_outer, orient="vertical", command=self._txt_log.yview
        )
        self._txt_log.configure(yscrollcommand=scrollbar.set)
        self._txt_log.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        _bind_scroll(self._txt_log)

    def _build_list_pane(self, parent, row, col, title):
        outer = ttk.LabelFrame(
            parent,
            text=title,
            padding=(4, 2),
            style=f"{self._style_prefix}.TLabelframe",
        )
        outer.grid(
            row=row,
            column=col,
            sticky="nsew",
            padx=(0, 4) if col == 0 else (4, 0),
        )
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        listbox = tk.Listbox(
            outer,
            height=10,
            selectmode="single",
            activestyle="dotbox",
            exportselection=False,
            font=("monospace", 9),
        )
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=listbox.yview)
        listbox.configure(yscrollcommand=scrollbar.set)
        listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        _bind_scroll(listbox)
        return listbox

    def _bind_router_context_menus(self):
        self._sink_menu = tk.Menu(self.frame, tearoff=0)
        self._sink_menu.add_command(
            label="Rename Output...",
            command=self._rename_selected_sink,
        )
        self._sink_menu.add_command(
            label="Reset Output Name",
            command=self._reset_selected_sink_name,
        )

        self._stream_menu = tk.Menu(self.frame, tearoff=0)
        self._map_stream_menu = tk.Menu(self.frame, tearoff=0)
        self._routing_rule_menu = tk.Menu(self.frame, tearoff=0)
        self._display_menu = tk.Menu(self.frame, tearoff=0)

        for widget in (self._lb_sinks, self._lb_streams):
            widget.bind("<Button-3>", self._on_right_click, add="+")
            widget.bind("<Control-Button-1>", self._on_right_click, add="+")
        self._lb_sinks.bind("<Double-Button-1>", self._on_sink_double_click, add="+")
        self._lb_streams.bind(
            "<Double-Button-1>", self._on_stream_double_click, add="+"
        )
        self._map_streams.bind("<Button-3>", self._on_map_stream_right_click, add="+")
        self._map_streams.bind("<Control-Button-1>", self._on_map_stream_right_click, add="+")
        self._routing_rule_list.bind("<Button-3>", self._on_routing_rule_right_click, add="+")
        self._routing_rule_list.bind("<Control-Button-1>", self._on_routing_rule_right_click, add="+")
        self.frame.bind_all("<Button-1>", self._dismiss_context_menus, add="+")
        self.frame.bind_all("<Escape>", self._dismiss_context_menus, add="+")

    def _build_status_bar(self):
        self._var_status = tk.StringVar(value="Ready.")
        bar = ttk.Frame(
            self.frame, padding=(4, 2), style=f"{self._style_prefix}.TFrame"
        )
        bar.grid(row=2, column=0, sticky="ew")
        bar.columnconfigure(0, weight=1)
        self._status_bar = bar
        self._status_label = ttk.Label(
            bar,
            textvariable=self._var_status,
            anchor="w",
            style=f"{self._style_prefix}.Status.TLabel",
        )
        self._status_label.grid(row=0, column=0, sticky="ew")

    def set_guichi_page_theme(self, context):
        self.guichi_page_theme = context
        tokens = dict(_DEFAULT_PAGE_THEME)
        tokens.update((context or {}).get("tokens") or {})
        self._theme_tokens = tokens
        self._apply_theme()

    def _apply_theme(self):
        tokens = self._theme_tokens
        try:
            self._style = ttk.Style(self.frame)
            self._style.configure(
                f"{self._style_prefix}.TFrame",
                background=tokens["content_bg"],
            )
            self._style.configure(
                f"{self._style_prefix}.TLabelframe",
                background=tokens["panel_bg"],
                bordercolor=tokens["border"],
            )
            self._style.configure(
                f"{self._style_prefix}.TLabelframe.Label",
                background=tokens["panel_bg"],
                foreground=tokens["text_main"],
            )
            self._style.configure(
                f"{self._style_prefix}.TButton",
                background=tokens["button_bg"],
                foreground=tokens["text_main"],
            )
            self._style.map(
                f"{self._style_prefix}.TButton",
                background=[("active", tokens["button_hover"])],
                foreground=[
                    ("active", tokens["text_active"]),
                    ("disabled", tokens["button_disabled"]),
                ],
            )
            self._style.configure(
                f"{self._style_prefix}.Muted.TLabel",
                background=tokens["content_bg"],
                foreground=tokens["text_muted"],
            )
            self._style.configure(
                f"{self._style_prefix}.Status.TLabel",
                background=tokens["content_bg"],
                foreground=tokens["text_muted"],
            )
            self._style.configure(
                f"{self._style_prefix}.TNotebook",
                background=tokens["content_bg"],
                borderwidth=0,
            )
            self._style.configure(
                f"{self._style_prefix}.TNotebook.Tab",
                background=tokens["panel_bg"],
                foreground=tokens["text_main"],
            )
            self._style.map(
                f"{self._style_prefix}.TNotebook.Tab",
                background=[("selected", tokens["accent"])],
                foreground=[("selected", tokens["text_on_accent"])],
            )
            if self._notebook is not None:
                self._notebook.configure(style=f"{self._style_prefix}.TNotebook")
            if self._map_stream_tabs is not None:
                self._map_stream_tabs.configure(style=f"{self._style_prefix}.TNotebook")
            if self._speaker_support_tabs is not None:
                self._speaker_support_tabs.configure(style=f"{self._style_prefix}.TNotebook")
        except Exception:
            pass

        try:
            self.frame.configure(style=f"{self._style_prefix}.TFrame")
        except Exception:
            pass

        for widget in (
            self._top_bar,
            self._body_frame,
            self._router_tab,
            self._map_tab,
            self._map_streams_tab,
            self._keyword_assigner_tab,
            self._inactive_speakers_tab,
            self._layout_presets_tab,
            self._log_tab,
            self._log_outer,
            self._status_bar,
        ):
            if widget is None:
                continue
            try:
                widget.configure(style=f"{self._style_prefix}.TFrame")
            except Exception:
                pass

        for widget in (self._default_label, self._status_label):
            if widget is None:
                continue
            try:
                widget.configure(
                    style=(
                        f"{self._style_prefix}.Muted.TLabel"
                        if widget is self._default_label
                        else f"{self._style_prefix}.Status.TLabel"
                    )
                )
            except Exception:
                pass

        list_bg = tokens["panel_bg"]
        list_fg = tokens["text_main"]
        select_bg = tokens["accent"]
        select_fg = tokens["text_on_accent"]
        border = tokens["border"]
        for widget in (
            self._lb_sinks,
            self._lb_streams,
            self._map_streams,
            self._staging_list,
            self._preset_list,
            self._routing_rule_list,
        ):
            if widget is None:
                continue
            try:
                widget.configure(
                    background=list_bg,
                    foreground=list_fg,
                    selectbackground=select_bg,
                    selectforeground=select_fg,
                    highlightbackground=border,
                    highlightcolor=select_bg,
                )
            except Exception:
                pass
        if self._txt_log is not None:
            try:
                self._txt_log.configure(
                    background=list_bg,
                    foreground=list_fg,
                    insertbackground=list_fg,
                    selectbackground=select_bg,
                    selectforeground=select_fg,
                    highlightbackground=border,
                    highlightcolor=select_bg,
                )
            except Exception:
                pass
        if self._map_canvas is not None:
            try:
                self._map_canvas.configure(
                    background=tokens["sidebar_bg"],
                    highlightbackground=border,
                    highlightcolor=select_bg,
                )
            except Exception:
                pass
        for menu in (self._sink_menu, self._stream_menu, self._map_stream_menu, self._display_menu):
            if menu is None:
                continue
            try:
                menu.configure(
                    background=tokens["panel_bg"],
                    foreground=tokens["text_main"],
                    activebackground=tokens["accent"],
                    activeforeground=tokens["text_on_accent"],
                    borderwidth=1,
                )
            except Exception:
                pass
        self._render_display_map()

    def _now(self):
        return datetime.datetime.now().strftime("%H:%M:%S")

    def _set_status(self, msg):
        try:
            self._var_status.set(f"[{self._now()}] {msg}")
        except Exception:
            pass

    def _log(self, msg):
        if self._txt_log is None:
            return
        try:
            self._txt_log.configure(state="normal")
            self._txt_log.insert("end", f"[{self._now()}] {msg}\n")
            self._txt_log.see("end")
            self._txt_log.configure(state="disabled")
        except Exception:
            pass

    def _log_block(self, title, text):
        if not text:
            return
        self._log(f"{title}:")
        try:
            self._txt_log.configure(state="normal")
            for line in text.splitlines():
                self._txt_log.insert("end", f"  {line}\n")
            self._txt_log.see("end")
            self._txt_log.configure(state="disabled")
        except Exception:
            pass

    def _update_button_state(self):
        state_actions = "normal" if self._have_pactl else "disabled"
        state_wpctl = "normal" if self._have_wpctl else "disabled"
        for button in (self._btn_refresh, self._btn_default, self._btn_move, self._btn_apply_rules, self._btn_all_outputs):
            if button is not None:
                button.configure(state=state_actions)
        if self._btn_wpctl is not None:
            self._btn_wpctl.configure(state=state_wpctl)

    def _initial_refresh(self):
        self._load_config()
        self._have_pactl = bool(shutil.which("pactl"))
        self._have_wpctl = bool(shutil.which("wpctl"))
        self._update_button_state()

        if not self._have_pactl and not self._have_wpctl:
            msg = (
                "Neither 'pactl' nor 'wpctl' was found on PATH. "
                "Install pulseaudio-utils (pactl) or wireplumber (wpctl) "
                "to use this page."
            )
            self._set_status("Audio tools not available.")
            self._log(msg)
            self._render_lists()
            self._render_display_map()
            self._select_layout_presets_tab()
            self.frame.after_idle(self._refresh_layout_presets_view)
            return

        if not self._have_pactl:
            self._set_status("pactl not found — read-only mode (wpctl diagnostic only).")
            self._log(
                "pactl not found on PATH. Set-default and move-stream are "
                "disabled. Use 'wpctl status' for a diagnostic snapshot."
            )
            self._render_lists()
            self._render_display_map()
            self._select_layout_presets_tab()
            self.frame.after_idle(self._refresh_layout_presets_view)
            return

        self._do_refresh()
        self._select_layout_presets_tab()
        self.frame.after_idle(self._refresh_layout_presets_view)

    def _on_refresh(self):
        if not self._have_pactl:
            self._set_status("pactl not available.")
            return
        self._do_refresh()

    def _do_refresh(self, allow_rule_apply=True):
        r_sinks = _run(["pactl", "list", "short", "sinks"])
        if r_sinks["error"] is not None or r_sinks["rc"] != 0:
            self._sinks = []
            err = r_sinks["error"] or r_sinks["stderr"].strip() or f"rc={r_sinks['rc']}"
            self._log(f"pactl list short sinks failed: {err}")
            self._log_block("raw stdout", r_sinks["stdout"])
        else:
            try:
                self._sinks = _parse_sinks_short(r_sinks["stdout"])
            except Exception as ex:
                self._sinks = []
                self._log(f"sink parser failed: {ex}")
                self._log_block("raw stdout", r_sinks["stdout"])

        r_streams = _run(["pactl", "list", "sink-inputs"])
        if r_streams["error"] is not None or r_streams["rc"] != 0:
            self._streams = []
            err = r_streams["error"] or r_streams["stderr"].strip() or "non-zero exit"
            self._log(f"pactl list sink-inputs failed: {err}")
            self._log_block("raw stdout", r_streams["stdout"])
        else:
            try:
                self._streams = _parse_sink_inputs(r_streams["stdout"])
            except Exception as ex:
                self._streams = []
                self._log(f"sink-input parser failed: {ex}")
                self._log_block("raw stdout", r_streams["stdout"])

        r_def = _run(["pactl", "get-default-sink"])
        self._default_sink = r_def["stdout"].strip() if r_def["error"] is None and r_def["rc"] == 0 else ""

        self._sync_display_boxes()
        if allow_rule_apply and self._auto_apply_rules and self._streams:
            moved = self._apply_routing_rules(refresh_after=False)
            if moved:
                self._do_refresh(allow_rule_apply=False)
                return
        self._render_lists()
        self._render_display_map()
        self._render_layout_presets()
        self._render_routing_rules()
        self._set_status(
            f"Refreshed: {len(self._sinks)} sink(s), {len(self._streams)} active stream(s)."
        )

    def _render_lists(self):
        self._prune_stream_manual_overrides()
        if self._var_default is not None:
            if self._default_sink:
                self._var_default.set(
                    f"Default sink: {self._display_sink_name(self._default_sink)}"
                )
            else:
                self._var_default.set("Default sink: (unknown)")

        if self._lb_sinks is not None:
            self._lb_sinks.delete(0, "end")
            if not self._sinks:
                self._lb_sinks.insert("end", "(no sinks)")
            else:
                for sink in self._sinks:
                    marker = "*" if sink["name"] == self._default_sink else " "
                    label = f"{marker} {sink['id']:>3}  {self._display_sink_name(sink['name'])}"
                    if sink.get("state"):
                        label += f"  [{sink['state']}]"
                    self._lb_sinks.insert("end", label)

        router_stream_rows = []
        map_stream_rows = []
        if not self._streams:
            router_stream_rows = ["(no active streams)"]
            map_stream_rows = ["(no active streams)"]
        else:
            for stream in self._streams:
                app = self._stream_label(stream)
                sink_ref = stream.get("sink_id") or "?"
                sink_name = self._sink_name_from_id(sink_ref)
                sink_label = self._display_sink_name(sink_name) if sink_name else f"sink {sink_ref}"
                zone = self._display_label_for_sink(sink_name)
                stream_id = str(stream.get("id", "")).strip()
                override_marker = "  [manual]" if stream_id in self._stream_manual_overrides else ""
                router_stream_rows.append(f"{stream['id']:>3}  {app}  → {sink_label}")
                map_suffix = f" [{zone}]" if zone else ""
                map_stream_rows.append(f"{stream['id']:>3}  {app}  → {sink_label}{map_suffix}{override_marker}")

        if self._lb_streams is not None:
            self._lb_streams.delete(0, "end")
            for row in router_stream_rows:
                self._lb_streams.insert("end", row)

        if self._map_streams is not None:
            current = self._selected_map_stream_id()
            self._map_streams.delete(0, "end")
            for row in map_stream_rows:
                self._map_streams.insert("end", row)
            self._restore_map_stream_selection(current)

    def _selected_sink(self):
        if not self._sinks or self._lb_sinks is None:
            return None
        sel = self._lb_sinks.curselection()
        if not sel:
            return None
        idx = sel[0]
        return self._sinks[idx] if 0 <= idx < len(self._sinks) else None

    def _selected_stream(self):
        if not self._streams or self._lb_streams is None:
            return None
        sel = self._lb_streams.curselection()
        if not sel:
            return None
        idx = sel[0]
        return self._streams[idx] if 0 <= idx < len(self._streams) else None

    def _selected_map_stream(self):
        if not self._streams or self._map_streams is None:
            return None
        sel = self._map_streams.curselection()
        if not sel:
            return None
        idx = sel[0]
        return self._streams[idx] if 0 <= idx < len(self._streams) else None

    def _selected_map_stream_id(self):
        stream = self._selected_map_stream()
        return stream.get("id") if stream else None

    def _restore_map_stream_selection(self, stream_id):
        if self._map_streams is None or stream_id is None:
            return
        for idx, stream in enumerate(self._streams):
            if stream.get("id") == stream_id:
                self._map_streams.selection_clear(0, "end")
                self._map_streams.selection_set(idx)
                self._map_streams.activate(idx)
                return

    def _select_layout_presets_tab(self):
        if self._speaker_support_tabs is None or self._layout_presets_tab is None:
            return
        try:
            self._speaker_support_tabs.select(self._layout_presets_tab)
        except Exception:
            pass

    def _refresh_layout_presets_view(self):
        self._render_layout_presets()
        self._select_layout_presets_tab()

    def _sink_name_from_id(self, sink_id):
        for sink in self._sinks:
            if sink.get("id") == str(sink_id):
                return sink.get("name", "")
        return ""

    def _display_sink_name(self, sink_name):
        alias = self._sink_aliases.get(sink_name, "").strip()
        return f"{alias} ({sink_name})" if alias else sink_name

    def _stream_label(self, stream):
        app_name = str(stream.get("app_name", "")).strip()
        media_name = str(stream.get("media_name", "")).strip()
        process_binary = str(stream.get("process_binary", "")).strip()
        for candidate in (app_name, media_name, process_binary):
            if candidate:
                return candidate
        return "(unknown app)"

    def _stream_rule_keyword(self, stream):
        app_name = str(stream.get("app_name", "")).strip()
        process_binary = str(stream.get("process_binary", "")).strip()
        media_name = str(stream.get("media_name", "")).strip()
        for candidate in (app_name, process_binary, media_name):
            if candidate:
                return candidate
        return ""

    def _load_config(self):
        self._sink_aliases = {}
        self._display_boxes = []
        self._next_display_id = 1
        self._selected_display_id = None
        self._layout_presets = {}
        self._routing_rules = []
        self._next_rule_id = 1
        self._auto_apply_rules = False
        self._stream_manual_overrides = {}
        if not self._config_path or not os.path.exists(self._config_path):
            if self._var_auto_apply_rules is not None:
                self._var_auto_apply_rules.set(False)
            return
        try:
            with open(self._config_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            aliases = data.get("sink_aliases", {})
            if isinstance(aliases, dict):
                self._sink_aliases = {
                    str(key): str(val).strip()
                    for key, val in aliases.items()
                    if str(val).strip()
                }
            layout = data.get("display_layout", {})
            if isinstance(layout, dict):
                boxes = layout.get("boxes", [])
                if isinstance(boxes, list):
                    for raw in boxes:
                        box = self._normalize_display_box(raw)
                        if box is not None:
                            self._display_boxes.append(box)
                next_id = layout.get("next_id", 1)
                if isinstance(next_id, int) and next_id > 0:
                    self._next_display_id = next_id
                else:
                    self._next_display_id = self._compute_next_display_id()
            presets = data.get("layout_presets", {})
            if isinstance(presets, dict):
                for name, raw in presets.items():
                    preset = self._normalize_layout_preset(name, raw)
                    if preset is not None:
                        self._layout_presets[preset["name"]] = preset
            rules = data.get("routing_rules", [])
            if isinstance(rules, list):
                for raw in rules:
                    rule = self._normalize_routing_rule(raw)
                    if rule is not None:
                        self._routing_rules.append(rule)
            next_rule_id = data.get("routing_next_id", 1)
            if isinstance(next_rule_id, int) and next_rule_id > 0:
                self._next_rule_id = next_rule_id
            else:
                self._next_rule_id = self._compute_next_rule_id()
            self._auto_apply_rules = bool(data.get("routing_auto_apply", False))
        except Exception as ex:
            self._log(f"failed to load audio router config: {ex}")
        if self._var_auto_apply_rules is not None:
            self._var_auto_apply_rules.set(self._auto_apply_rules)

    def _save_config(self):
        payload = {
            "sink_aliases": dict(sorted(self._sink_aliases.items())),
            "display_layout": {
                "next_id": self._compute_next_display_id(),
                "boxes": [self._serialize_display_box(box) for box in self._display_boxes],
            },
            "layout_presets": {
                name: self._serialize_layout_preset(preset)
                for name, preset in sorted(self._layout_presets.items())
            },
            "routing_rules": [self._serialize_routing_rule(rule) for rule in self._routing_rules],
            "routing_next_id": self._compute_next_rule_id(),
            "routing_auto_apply": bool(self._auto_apply_rules),
        }
        try:
            with open(self._config_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
        except Exception as ex:
            self._log(f"failed to save audio router config: {ex}")

    def _normalize_display_box(self, raw):
        if not isinstance(raw, dict):
            return None
        display_id = str(raw.get("id", "")).strip()
        if not display_id:
            return None
        label = str(raw.get("label", "")).strip() or display_id
        size = str(raw.get("size", "medium")).strip().lower()
        if size not in _DISPLAY_SIZE_PRESETS:
            size = "medium"
        orientation = str(raw.get("orientation", "landscape")).strip().lower()
        if orientation not in {"landscape", "portrait"}:
            orientation = "landscape"
        label_mode = str(raw.get("label_mode", "friendly")).strip().lower()
        if label_mode not in {"friendly", "technical"}:
            label_mode = "friendly"
        box = {
            "id": display_id,
            "label": label,
            "size": size,
            "orientation": orientation,
            "label_mode": label_mode,
            "x": int(raw.get("x", _DISPLAY_LAYOUT_PADDING)),
            "y": int(raw.get("y", _DISPLAY_LAYOUT_PADDING)),
            "assigned_sink": str(raw.get("assigned_sink", "")).strip(),
            "seed_sink": str(raw.get("seed_sink", "")).strip(),
            "placed": bool(raw.get("placed", False)),
        }
        return box

    def _serialize_display_box(self, box):
        return {
            "id": box["id"],
            "label": box["label"],
            "size": box["size"],
            "orientation": box.get("orientation", "landscape"),
            "label_mode": box.get("label_mode", "friendly"),
            "x": int(box["x"]),
            "y": int(box["y"]),
            "assigned_sink": box.get("assigned_sink", ""),
            "seed_sink": box.get("seed_sink", ""),
            "placed": bool(box.get("placed", False)),
        }

    def _compute_next_display_id(self):
        highest = 0
        for box in self._display_boxes:
            match = re.match(r"^display_(\d+)$", str(box.get("id", "")))
            if match:
                highest = max(highest, int(match.group(1)))
        return highest + 1

    def _normalize_layout_preset(self, name, raw):
        preset_name = str(name).strip()
        if not preset_name or not isinstance(raw, dict):
            return None
        boxes = []
        for item in raw.get("boxes", []):
            box = self._normalize_display_box(item)
            if box is not None:
                boxes.append(box)
        next_id = raw.get("next_id", 1)
        if not isinstance(next_id, int) or next_id <= 0:
            next_id = 1
        return {"name": preset_name, "boxes": boxes, "next_id": next_id}

    def _serialize_layout_preset(self, preset):
        return {
            "next_id": int(preset.get("next_id", 1)),
            "boxes": [self._serialize_display_box(box) for box in preset.get("boxes", [])],
        }

    def _normalize_routing_rule(self, raw):
        if not isinstance(raw, dict):
            return None
        rule_id = str(raw.get("id", "")).strip()
        match_text = str(raw.get("match_text", "")).strip()
        if not rule_id or not match_text:
            return None
        return {
            "id": rule_id,
            "match_text": match_text,
            "target_display_id": str(raw.get("target_display_id", "")).strip(),
            "enabled": bool(raw.get("enabled", True)),
            "case_sensitive": bool(raw.get("case_sensitive", False)),
        }

    def _serialize_routing_rule(self, rule):
        return {
            "id": rule["id"],
            "match_text": rule["match_text"],
            "target_display_id": rule.get("target_display_id", ""),
            "enabled": bool(rule.get("enabled", True)),
            "case_sensitive": bool(rule.get("case_sensitive", False)),
        }

    def _compute_next_rule_id(self):
        highest = 0
        for rule in self._routing_rules:
            match = re.match(r"^rule_(\d+)$", str(rule.get("id", "")))
            if match:
                highest = max(highest, int(match.group(1)))
        return highest + 1

    def _new_rule_id(self):
        rule_id = f"rule_{self._next_rule_id}"
        self._next_rule_id += 1
        return rule_id

    def _new_display_id(self):
        display_id = f"display_{self._next_display_id}"
        self._next_display_id += 1
        return display_id

    def _display_label_for_sink(self, sink_name):
        if not sink_name:
            return ""
        for box in self._display_boxes:
            if box.get("assigned_sink") == sink_name:
                return box.get("label", "")
        return ""

    def _is_all_outputs_active(self):
        return self._sink_by_name(_ALL_OUTPUTS_SINK_NAME) is not None

    def _update_all_outputs_button(self):
        if self._btn_all_outputs is None:
            return
        active = self._is_all_outputs_active()
        self._btn_all_outputs.configure(
            text="All Outputs: On" if active else "All Outputs: Off"
        )

    def _active_speaker_sink_names(self):
        names = []
        seen = set()
        for box in self._placed_display_boxes():
            sink_name = str(box.get("assigned_sink", "")).strip()
            if (
                not sink_name
                or sink_name == _ALL_OUTPUTS_SINK_NAME
                or sink_name in seen
                or not self._sink_exists(sink_name)
            ):
                continue
            seen.add(sink_name)
            names.append(sink_name)
        return names

    def _active_speaker_count_for_sink(self, sink_name):
        if not sink_name:
            return 0
        return sum(
            1
            for box in self._display_boxes
            if box.get("placed") and box.get("assigned_sink") == sink_name
        )

    def _sync_display_boxes(self):
        if not self._sinks:
            self._save_config()
            return

        changed = False
        represented = set()
        for box in self._display_boxes:
            seed_sink = box.get("seed_sink", "")
            assigned_sink = box.get("assigned_sink", "")
            if seed_sink:
                represented.add(seed_sink)
            if assigned_sink:
                represented.add(assigned_sink)

        if not self._display_boxes:
            x = _DISPLAY_LAYOUT_PADDING
            y = _DISPLAY_LAYOUT_PADDING
            canvas_width = self._canvas_layout_width()
            for sink in self._sinks:
                if sink["name"] == _ALL_OUTPUTS_SINK_NAME:
                    continue
                width, _height = self._display_dimensions_for_values("medium", "landscape")
                if x > _DISPLAY_LAYOUT_PADDING and x + width > canvas_width - _DISPLAY_LAYOUT_PADDING:
                    x = _DISPLAY_LAYOUT_PADDING
                    y += _DISPLAY_SIZE_PRESETS["medium"][1] + _DISPLAY_GAP
                box = {
                    "id": self._new_display_id(),
                    "label": _derive_display_label(
                        sink["name"], self._sink_aliases.get(sink["name"], "")
                    ),
                    "size": "medium",
                    "orientation": "landscape",
                    "label_mode": "friendly",
                    "x": x,
                    "y": y,
                    "assigned_sink": sink["name"],
                    "seed_sink": sink["name"],
                    "placed": True,
                }
                self._display_boxes.append(box)
                x += width + _DISPLAY_GAP
            changed = True
        else:
            for sink in self._sinks:
                if sink["name"] == _ALL_OUTPUTS_SINK_NAME:
                    continue
                if sink["name"] in represented:
                    continue
                box = {
                    "id": self._new_display_id(),
                    "label": _derive_display_label(
                        sink["name"], self._sink_aliases.get(sink["name"], "")
                    ),
                    "size": "medium",
                    "orientation": "landscape",
                    "label_mode": "friendly",
                    "x": _DISPLAY_LAYOUT_PADDING,
                    "y": _DISPLAY_LAYOUT_PADDING,
                    "assigned_sink": sink["name"],
                    "seed_sink": sink["name"],
                    "placed": False,
                }
                self._display_boxes.append(box)
                represented.add(sink["name"])
                changed = True

        self._next_display_id = self._compute_next_display_id()
        if changed:
            self._save_config()

    def _render_display_map(self):
        if self._map_canvas is None:
            return
        self._map_canvas.delete("all")
        self._box_items = {}
        tokens = self._theme_tokens

        width = self._world_layout_width()
        height = self._world_layout_height()
        self._map_canvas.create_rectangle(
            0,
            0,
            width,
            height,
            fill=tokens["sidebar_bg"],
            outline=tokens["border"],
        )

        placed_boxes = self._placed_display_boxes()
        for box in placed_boxes:
            self._draw_display_box(box)
        self._map_canvas.configure(scrollregion=(0, 0, width, height))

        if self._staging_list is not None:
            self._staging_list.delete(0, "end")
            for box in self._display_boxes:
                if box.get("placed"):
                    continue
                sink_name = box.get("assigned_sink", "")
                sink_text = self._display_sink_name(sink_name) if sink_name else "(unassigned)"
                self._staging_list.insert("end", f"{box['label']}  →  {sink_text}")
            self._sync_staging_selection()

        self._update_all_outputs_button()
        self._update_display_details()
        self._refresh_rule_target_menu()
        self._render_layout_presets()
        self._render_routing_rules()

    def _draw_display_box(self, box):
        box_width, box_height = self._display_dimensions(box)
        width = int(round(box_width * self._display_zoom))
        height = int(round(box_height * self._display_zoom))
        x1 = int(round(int(box.get("x", _DISPLAY_LAYOUT_PADDING)) * self._display_zoom))
        y1 = int(round(int(box.get("y", _DISPLAY_LAYOUT_PADDING)) * self._display_zoom))
        x2 = x1 + width
        y2 = y1 + height
        selected = box.get("id") == self._selected_display_id
        sink_name = box.get("assigned_sink", "")
        sink_present = bool(self._sink_exists(sink_name)) if sink_name else False
        is_default_display = self._display_is_default(box)

        fill = self._theme_tokens["panel_bg"]
        outline = self._theme_tokens["accent"] if selected else self._theme_tokens["border"]
        if sink_name and not sink_present:
            fill = "#503030"
        elif is_default_display and sink_present:
            fill = "#214b4b"

        tag = f"displaybox:{box['id']}"
        rect_id = self._map_canvas.create_rectangle(
            x1,
            y1,
            x2,
            y2,
            fill=fill,
            outline=outline,
            width=2 if selected else 1,
            tags=(tag, "displaybox"),
        )
        font_size = max(5, min(14, int(round(min(width, height) / 10))))
        title = self._display_title_for_box(box)
        output_name = self._display_secondary_text_for_box(box)
        status = ""
        if sink_name and not sink_present:
            status = " [missing]"
        elif is_default_display and sink_present:
            status = " [default]"
        if output_name:
            text = f"{title}\n{output_name}{status}"
        elif status:
            text = f"{title}{status}"
        else:
            text = title
        text_id = self._map_canvas.create_text(
            x1 + width / 2,
            y1 + height / 2,
            text=text,
            width=max(width - int(round(18 * self._display_zoom)), 80),
            justify="center",
            fill=self._theme_tokens["text_main"],
            font=("TkDefaultFont", font_size, "bold" if selected else "normal"),
            tags=(tag, "displaybox"),
        )
        self._box_items[box["id"]] = (rect_id, text_id)

    def _display_box_by_id(self, display_id):
        for box in self._display_boxes:
            if box.get("id") == display_id:
                return box
        return None

    def _placed_display_boxes(self):
        return [box for box in self._display_boxes if box.get("placed")]

    def _rule_target_choices(self):
        choices = []
        for display in self._placed_display_boxes():
            sink_name = display.get("assigned_sink", "")
            if not sink_name:
                continue
            label = f"{display.get('label', '(speaker)')} ({self._display_sink_name(sink_name)})"
            choices.append((label, display["id"]))
        return choices

    def _refresh_rule_target_menu(self):
        if self._rule_target_menu is None or self._var_rule_target is None:
            return
        choices = self._rule_target_choices()
        labels = [label for label, _display_id in choices]
        current = self._var_rule_target.get().strip()
        menu = self._rule_target_menu["menu"]
        menu.delete(0, "end")
        for label in labels:
            menu.add_command(
                label=label,
                command=lambda value=label: self._var_rule_target.set(value),
            )
        if not labels:
            self._var_rule_target.set("(no active speaker targets)")
            return
        if current and current in labels:
            self._var_rule_target.set(current)
            return
        selected_display = self._selected_display()
        if selected_display is not None:
            for label, display_id in choices:
                if display_id == selected_display.get("id"):
                    self._var_rule_target.set(label)
                    return
        self._var_rule_target.set(labels[0])

    def _selected_rule_target_display_id(self):
        if self._var_rule_target is None:
            return ""
        current = self._var_rule_target.get().strip()
        for label, display_id in self._rule_target_choices():
            if label == current:
                return display_id
        return ""

    def _render_layout_presets(self):
        if self._preset_list is None:
            return
        current = self._selected_preset_name()
        self._preset_list.delete(0, "end")
        names = sorted(self._layout_presets)
        for name in names:
            self._preset_list.insert("end", name)
        if current and current in names:
            idx = names.index(current)
            self._preset_list.selection_set(idx)
            self._preset_list.activate(idx)

    def _render_routing_rules(self):
        if self._routing_rule_list is None:
            return
        current = self._selected_routing_rule_id()
        self._routing_rule_list.delete(0, "end")
        for rule in self._routing_rules:
            prefix = "on " if rule.get("enabled", True) else "off"
            caps = "[Aa]" if rule.get("case_sensitive", False) else "[aa]"
            self._routing_rule_list.insert(
                "end",
                f"{prefix:<3}  {caps}  {rule['match_text']}  →  {self._routing_rule_display_label(rule)}",
            )
        if current is not None:
            for idx, rule in enumerate(self._routing_rules):
                if rule.get("id") == current:
                    self._routing_rule_list.selection_set(idx)
                    self._routing_rule_list.activate(idx)
                    break

    def _selected_preset_name(self):
        if self._preset_list is None:
            return None
        sel = self._preset_list.curselection()
        if not sel:
            return None
        try:
            return str(self._preset_list.get(sel[0]))
        except Exception:
            return None

    def _selected_routing_rule(self):
        if self._routing_rule_list is None:
            return None
        sel = self._routing_rule_list.curselection()
        if not sel:
            return None
        idx = sel[0]
        return self._routing_rules[idx] if 0 <= idx < len(self._routing_rules) else None

    def _selected_routing_rule_id(self):
        rule = self._selected_routing_rule()
        return rule.get("id") if rule else None

    def _routing_rule_by_id(self, rule_id):
        for rule in self._routing_rules:
            if rule.get("id") == rule_id:
                return rule
        return None

    def _stream_by_id(self, stream_id):
        stream_id = str(stream_id or "").strip()
        if not stream_id:
            return None
        for stream in self._streams:
            if str(stream.get("id", "")).strip() == stream_id:
                return stream
        return None

    def _friendly_sink_label(self, sink_name):
        if not sink_name:
            return ""
        alias = self._sink_aliases.get(sink_name, "").strip()
        if alias:
            return alias
        return _derive_display_label(sink_name, "")

    def _prune_stream_manual_overrides(self):
        if not self._stream_manual_overrides:
            return
        active_ids = {
            str(stream.get("id", "")).strip()
            for stream in self._streams
            if str(stream.get("id", "")).strip()
        }
        stale_ids = [stream_id for stream_id in self._stream_manual_overrides if stream_id not in active_ids]
        for stream_id in stale_ids:
            self._stream_manual_overrides.pop(stream_id, None)

    def _mark_stream_manual_override(self, stream, sink_name, display_id=""):
        stream_id = str(stream.get("id", "")).strip()
        if not stream_id:
            return
        self._stream_manual_overrides[stream_id] = {
            "sink_name": str(sink_name or "").strip(),
            "display_id": str(display_id or "").strip(),
        }

    def _routing_rule_display_label(self, rule):
        display = self._display_box_by_id(rule.get("target_display_id", ""))
        if display is None:
            return "(missing speaker)"
        sink_name = display.get("assigned_sink", "")
        if not sink_name:
            return f"{display.get('label', '(speaker)')} [no output]"
        return f"{display.get('label', '(speaker)')} → {self._display_sink_name(sink_name)}"

    def _display_title_for_box(self, box):
        if box.get("label_mode", "friendly") == "technical":
            return box.get("assigned_sink") or box.get("seed_sink") or box.get("label", "")
        return box.get("label", "")

    def _display_secondary_text_for_box(self, box):
        if box.get("label_mode", "friendly") == "technical":
            return ""
        sink_name = box.get("assigned_sink", "")
        if not sink_name:
            return "(unassigned)"
        friendly = self._friendly_sink_label(sink_name)
        if friendly.strip().lower() == str(box.get("label", "")).strip().lower():
            return ""
        return friendly

    def _sink_exists(self, sink_name):
        return any(sink.get("name") == sink_name for sink in self._sinks)

    def _default_display_id(self):
        sink_name = self._default_sink.strip()
        if not sink_name:
            return ""
        for box in self._display_boxes:
            if box.get("placed") and box.get("assigned_sink") == sink_name:
                return str(box.get("id", ""))
        for box in self._display_boxes:
            if box.get("assigned_sink") == sink_name:
                return str(box.get("id", ""))
        return ""

    def _display_is_default(self, box):
        if not box:
            return False
        sink_name = str(box.get("assigned_sink", "")).strip()
        if not sink_name or sink_name != self._default_sink:
            return False
        return str(box.get("id", "")) == self._default_display_id()

    def _selected_display(self):
        return self._display_box_by_id(self._selected_display_id)

    def _select_display(self, display_id):
        self._selected_display_id = display_id if self._display_box_by_id(display_id) else None
        self._sync_staging_selection()
        self._render_display_map()

    def _sync_staging_selection(self):
        if self._staging_list is None:
            return
        self._staging_list.selection_clear(0, "end")
        display = self._selected_display()
        if display is None or display.get("placed"):
            return
        idx = 0
        for box in self._display_boxes:
            if box.get("placed"):
                continue
            if box.get("id") == display.get("id"):
                self._staging_list.selection_set(idx)
                self._staging_list.activate(idx)
                return
            idx += 1

    def _update_display_details(self):
        if self._display_detail_var is None:
            return
        display = self._selected_display()
        if display is None:
            self._display_detail_var.set("No speaker selected.")
            return
        sink_name = display.get("assigned_sink", "")
        sink_text = self._display_sink_name(sink_name) if sink_name else "(unassigned)"
        state = "active" if display.get("placed") else "inactive"
        shared_count = self._active_speaker_count_for_sink(sink_name)
        if sink_name and not self._sink_exists(sink_name):
            sink_text += " [missing]"
        elif self._display_is_default(display):
            sink_text += " [default]"
        self._display_detail_var.set(
            f"{display['label']}\n"
            f"Output: {sink_text}\n"
            f"Shared Output: {shared_count} active speaker(s)\n"
            f"Size: {display.get('size', 'medium')}\n"
            f"Orientation: {display.get('orientation', 'landscape')}\n"
            f"Label Mode: {display.get('label_mode', 'friendly')}\n"
            f"Speaker State: {state}\n"
            f"Position: ({int(display.get('x', 0))}, {int(display.get('y', 0))})"
        )

    def _on_map_canvas_configure(self, _event=None):
        self._render_display_map()

    def _on_map_canvas_click(self, event):
        item = self._map_canvas.find_withtag("current")
        if not item:
            self._drag_display_id = None
            self._select_display(None)
            return
        display_id = self._display_id_from_canvas_item(item[0])
        display = self._display_box_by_id(display_id)
        if display is not None:
            world_x, world_y = self._event_to_world(event)
            self._drag_display_id = display_id
            self._drag_offset_x = world_x - int(display.get("x", 0))
            self._drag_offset_y = world_y - int(display.get("y", 0))
        self._select_display(display_id)

    def _on_map_canvas_right_click(self, event):
        item = self._map_canvas.find_withtag("current")
        if not item:
            return
        display_id = self._display_id_from_canvas_item(item[0])
        if not display_id:
            return
        self._selected_display_id = display_id
        self._populate_display_menu()
        self._render_display_map()
        interaction_support.show_popup_menu(
            self.frame.winfo_toplevel(),
            self._display_menu,
            event.x_root,
            event.y_root,
        )

    def _on_map_canvas_drag(self, event):
        if not self._drag_display_id:
            return
        display = self._display_box_by_id(self._drag_display_id)
        if display is None or not display.get("placed"):
            return
        world_x, world_y = self._event_to_world(event)
        display["x"] = self._soft_snap_coordinate(int(round(world_x - self._drag_offset_x)))
        display["y"] = self._soft_snap_coordinate(int(round(world_y - self._drag_offset_y)))
        self._ensure_display_within_canvas(display)
        self._render_display_map()

    def _on_map_canvas_release(self, _event=None):
        if not self._drag_display_id:
            return
        display = self._display_box_by_id(self._drag_display_id)
        if display is not None:
            self._save_config()
            self._set_status(
                f"Moved {display['label']} to ({display['x']}, {display['y']})."
            )
        self._drag_display_id = None

    def _on_map_canvas_mousewheel(self, event):
        if self._map_canvas is None:
            return "break"
        ctrl = bool(event.state & 0x4)
        shift = bool(event.state & 0x1)
        delta = 0
        if getattr(event, "num", None) == 4:
            delta = 1
        elif getattr(event, "num", None) == 5:
            delta = -1
        elif getattr(event, "delta", 0):
            delta = 1 if event.delta > 0 else -1
        if delta == 0:
            return "break"
        if ctrl:
            self._step_display_zoom(delta)
            return "break"
        if shift:
            self._map_canvas.xview_scroll(-delta, "units")
            return "break"
        self._map_canvas.yview_scroll(-delta, "units")
        return "break"

    def _display_id_from_canvas_item(self, item_id):
        for tag in self._map_canvas.gettags(item_id):
            if tag.startswith("displaybox:"):
                return tag.split(":", 1)[1]
        return None

    def _populate_display_menu(self):
        self._display_menu.delete(0, "end")
        display = self._selected_display()
        if display is None:
            return
        if self._sinks:
            for sink in self._sinks:
                label = self._display_sink_name(sink["name"])
                if sink["name"] == display.get("assigned_sink"):
                    label += "  [current]"
                self._display_menu.add_command(
                    label=f"Assign Output → {label}",
                    command=lambda sink_name=sink["name"]: self._assign_display_sink(sink_name),
                )
        else:
            self._display_menu.add_command(label="No outputs available", state="disabled")
        self._display_menu.add_separator()
        self._display_menu.add_command(
            label="Clear Output Assignment",
            command=lambda: self._assign_display_sink(""),
        )
        self._display_menu.add_command(
            label="Rename Speaker...",
            command=self._rename_selected_display,
        )
        label_mode_menu = tk.Menu(self._display_menu, tearoff=0)
        label_mode_menu.add_command(
            label="Friendly",
            command=lambda: self._set_selected_display_label_mode("friendly"),
        )
        label_mode_menu.add_command(
            label="Technical",
            command=lambda: self._set_selected_display_label_mode("technical"),
        )
        self._display_menu.add_cascade(label="Label Mode", menu=label_mode_menu)
        size_menu = tk.Menu(self._display_menu, tearoff=0)
        for size in ("small", "medium", "large"):
            size_menu.add_command(
                label=size.capitalize(),
                command=lambda value=size: self._set_selected_display_size(value),
            )
        self._display_menu.add_cascade(label="Set Size", menu=size_menu)
        orientation_menu = tk.Menu(self._display_menu, tearoff=0)
        orientation_menu.add_command(
            label="Landscape",
            command=lambda: self._set_selected_display_orientation("landscape"),
        )
        orientation_menu.add_command(
            label="Portrait",
            command=lambda: self._set_selected_display_orientation("portrait"),
        )
        self._display_menu.add_cascade(label="Set Orientation", menu=orientation_menu)
        self._display_menu.add_command(
            label="Toggle Orientation",
            command=self._toggle_selected_display_orientation,
        )
        self._display_menu.add_separator()
        self._display_menu.add_command(
            label="Set Default To This Speaker",
            command=self._set_default_from_selected_display,
        )
        self._display_menu.add_command(
            label="Move Selected Stream To Speaker",
            command=self._move_map_stream_to_selected_display,
        )

    def _on_staging_select(self, _event=None):
        if self._staging_list is None:
            return
        sel = self._staging_list.curselection()
        if not sel:
            return
        idx = sel[0]
        staged = [box for box in self._display_boxes if not box.get("placed")]
        if 0 <= idx < len(staged):
            self._selected_display_id = staged[idx]["id"]
            self._render_display_map()

    def _on_staging_double_click(self, _event=None):
        self._place_selected_display()

    def _on_map_stream_right_click(self, event):
        widget = event.widget
        self._dismiss_context_menus()
        try:
            idx = widget.nearest(event.y)
        except Exception:
            return
        if idx is None or idx < 0 or idx >= len(self._streams):
            return
        try:
            widget.selection_clear(0, "end")
            widget.selection_set(idx)
            widget.activate(idx)
        except Exception:
            return
        stream = self._selected_map_stream()
        if stream is None:
            return
        self._populate_map_stream_menu(stream)
        interaction_support.show_popup_menu(
            self.frame.winfo_toplevel(),
            self._map_stream_menu,
            event.x_root,
            event.y_root,
        )

    def _on_routing_rule_right_click(self, event):
        widget = event.widget
        self._dismiss_context_menus()
        try:
            idx = widget.nearest(event.y)
        except Exception:
            return
        if idx is None or idx < 0 or idx >= len(self._routing_rules):
            return
        try:
            widget.selection_clear(0, "end")
            widget.selection_set(idx)
            widget.activate(idx)
        except Exception:
            return
        rule = self._selected_routing_rule()
        if rule is None:
            return
        self._populate_routing_rule_menu(rule)
        interaction_support.show_popup_menu(
            self.frame.winfo_toplevel(),
            self._routing_rule_menu,
            event.x_root,
            event.y_root,
        )

    def _toggle_selected_display_placement(self):
        display = self._selected_display()
        if display is None:
            self._set_status("Select a speaker first.")
            return
        if display.get("placed"):
            display["placed"] = False
            self._save_config()
            self._render_display_map()
            self._set_status(f"Moved {display['label']} to inactive speakers.")
            return
        self._place_selected_display()

    def _place_selected_display(self):
        display = self._selected_display()
        if display is None:
            self._set_status("Select a speaker first.")
            return
        display["placed"] = True
        display["x"], display["y"] = self._next_open_display_position(display)
        self._ensure_display_within_canvas(display)
        self._save_config()
        self._render_display_map()
        self._set_status(f"Placed {display['label']} into the speaker layout.")

    def _rename_selected_display(self):
        display = self._selected_display()
        if display is None:
            self._set_status("Select a speaker first.")
            return
        value = simpledialog.askstring(
            "Rename Speaker",
            "Speaker name:",
            initialvalue=display.get("label", ""),
            parent=self.frame,
        )
        if value is None:
            return
        cleaned = value.strip()
        if not cleaned:
            self._set_status("Speaker name cannot be blank.")
            return
        display["label"] = cleaned
        self._save_config()
        self._render_display_map()
        self._set_status(f"Renamed speaker to {cleaned}.")

    def _save_layout_preset_prompt(self):
        value = simpledialog.askstring(
            "Save Layout Preset",
            "Preset name:",
            parent=self.frame,
        )
        if value is None:
            return
        name = value.strip()
        if not name:
            self._set_status("Preset name cannot be blank.")
            return
        self._layout_presets[name] = {
            "name": name,
            "next_id": self._compute_next_display_id(),
            "boxes": [self._normalize_display_box(self._serialize_display_box(box)) for box in self._display_boxes],
        }
        self._save_config()
        self._render_layout_presets()
        self._set_status(f"Saved layout preset {name}.")

    def _load_selected_layout_preset(self):
        name = self._selected_preset_name()
        if not name:
            self._set_status("Select a preset first.")
            return
        preset = self._layout_presets.get(name)
        if preset is None:
            self._set_status("Preset not found.")
            return
        self._display_boxes = [
            self._normalize_display_box(self._serialize_display_box(box))
            for box in preset.get("boxes", [])
            if self._normalize_display_box(self._serialize_display_box(box)) is not None
        ]
        self._next_display_id = int(preset.get("next_id", self._compute_next_display_id()))
        self._selected_display_id = None
        self._sync_display_boxes()
        self._save_config()
        self._render_lists()
        self._render_display_map()
        self._set_status(f"Loaded layout preset {name}.")

    def _delete_selected_layout_preset(self):
        name = self._selected_preset_name()
        if not name:
            self._set_status("Select a preset first.")
            return
        self._layout_presets.pop(name, None)
        self._save_config()
        self._render_layout_presets()
        self._set_status(f"Deleted layout preset {name}.")

    def _on_toggle_auto_apply_rules(self):
        self._auto_apply_rules = bool(self._var_auto_apply_rules.get()) if self._var_auto_apply_rules is not None else False
        self._save_config()
        self._set_status(
            "Auto-apply routing rules enabled." if self._auto_apply_rules else "Auto-apply routing rules disabled."
        )

    def _add_manual_keyword_rule(self):
        keyword = self._var_rule_keyword.get().strip() if self._var_rule_keyword is not None else ""
        if not keyword:
            self._set_status("Enter a keyword first.")
            return
        display_id = self._selected_rule_target_display_id()
        if not display_id:
            self._set_status("Choose a target speaker first.")
            return
        self._create_routing_rule(keyword, display_id)
        if self._var_rule_keyword is not None:
            self._var_rule_keyword.set("")

    def _add_rule_from_selected_stream(self):
        display = self._selected_display()
        if display is None:
            self._set_status("Select a target speaker first.")
            return
        if not display.get("placed"):
            self._set_status("Select an active target speaker first.")
            return
        if not display.get("assigned_sink", ""):
            self._set_status("Assign an output to the selected speaker first.")
            return
        stream = self._selected_map_stream() or self._selected_stream()
        if stream is None:
            self._set_status("Select a stream first.")
            return
        initial = self._stream_rule_keyword(stream)
        value = simpledialog.askstring(
            "Add App Routing Rule",
            "Match stream keyword containing:",
            initialvalue=initial,
            parent=self.frame,
        )
        if value is None:
            return
        match_text = value.strip()
        if not match_text:
            self._set_status("Rule text cannot be blank.")
            return
        self._create_routing_rule(match_text, display["id"])

    def _create_routing_rule(self, match_text, display_id, case_sensitive=False):
        display = self._display_box_by_id(display_id)
        if display is None:
            self._set_status("Selected speaker no longer exists.")
            return None
        if not display.get("placed"):
            self._set_status("Rule targets must be speakers on the active speaker map.")
            return None
        if not display.get("assigned_sink", ""):
            self._set_status("Assign an output to that speaker before creating a rule.")
            return None
        rule = {
            "id": self._new_rule_id(),
            "match_text": str(match_text).strip(),
            "target_display_id": display_id,
            "enabled": True,
            "case_sensitive": bool(case_sensitive),
        }
        if not rule["match_text"]:
            self._set_status("Rule text cannot be blank.")
            return None
        self._routing_rules.append(rule)
        self._save_config()
        self._render_routing_rules()
        self._refresh_rule_target_menu()
        self._set_status(f"Added routing rule: {rule['match_text']} → {display['label']}.")
        return rule

    def _create_keyword_rule_from_stream_id(self, display_id, stream_id):
        stream = self._stream_by_id(stream_id)
        if stream is None:
            self._set_status("That stream is no longer active.")
            return
        keyword = self._stream_rule_keyword(stream)
        if not keyword:
            self._set_status("Selected stream does not expose a usable keyword.")
            return
        self._create_routing_rule(keyword, display_id)

    def _delete_selected_routing_rule(self):
        rule = self._selected_routing_rule()
        if rule is None:
            self._set_status("Select a routing rule first.")
            return
        self._routing_rules = [item for item in self._routing_rules if item.get("id") != rule.get("id")]
        self._save_config()
        self._render_routing_rules()
        self._set_status(f"Deleted routing rule for {rule['match_text']}.")

    def _toggle_routing_rule_case_sensitive(self, rule_id):
        rule = self._routing_rule_by_id(rule_id)
        if rule is None:
            self._set_status("Routing rule no longer exists.")
            return
        rule["case_sensitive"] = not bool(rule.get("case_sensitive", False))
        self._save_config()
        self._render_routing_rules()
        state = "on" if rule["case_sensitive"] else "off"
        self._set_status(f"Cap sensitive {state} for {rule['match_text']}.")

    def _toggle_routing_rule_enabled(self, rule_id):
        rule = self._routing_rule_by_id(rule_id)
        if rule is None:
            self._set_status("Routing rule no longer exists.")
            return
        rule["enabled"] = not bool(rule.get("enabled", True))
        self._save_config()
        self._render_routing_rules()
        state = "enabled" if rule["enabled"] else "disabled"
        self._set_status(f"Rule {state}: {rule['match_text']}.")

    def _set_routing_rule_target(self, rule_id, display_id):
        rule = self._routing_rule_by_id(rule_id)
        display = self._display_box_by_id(display_id)
        if rule is None or display is None:
            self._set_status("Rule target is no longer available.")
            return
        if not display.get("placed") or not display.get("assigned_sink", ""):
            self._set_status("Rule targets must be active speakers with assigned outputs.")
            return
        rule["target_display_id"] = display_id
        self._save_config()
        self._render_routing_rules()
        self._set_status(f"Retargeted {rule['match_text']} to {display['label']}.")

    def _rename_routing_rule_keyword(self, rule_id):
        rule = self._routing_rule_by_id(rule_id)
        if rule is None:
            self._set_status("Routing rule no longer exists.")
            return
        value = simpledialog.askstring(
            "Rename Keyword Rule",
            "Keyword:",
            initialvalue=rule.get("match_text", ""),
            parent=self.frame,
        )
        if value is None:
            return
        keyword = value.strip()
        if not keyword:
            self._set_status("Rule text cannot be blank.")
            return
        rule["match_text"] = keyword
        self._save_config()
        self._render_routing_rules()
        self._set_status(f"Updated keyword rule to {keyword}.")

    def _on_apply_rules(self):
        if not self._have_pactl:
            self._set_status("pactl not available.")
            return
        moved = self._apply_routing_rules(refresh_after=True)
        if not moved:
            self._set_status("No routing rules needed to move any streams.")

    def _apply_routing_rules(self, refresh_after=True):
        if not self._routing_rules or not self._streams:
            return 0
        self._prune_stream_manual_overrides()
        moved = 0
        for stream in self._streams:
            stream_id = str(stream.get("id", "")).strip()
            if stream_id in self._stream_manual_overrides:
                continue
            source_text = self._stream_rule_keyword(stream)
            if not source_text:
                continue
            source_text_folded = source_text.lower()
            for rule in self._routing_rules:
                if not rule.get("enabled", True):
                    continue
                match_text_raw = str(rule.get("match_text", "")).strip()
                if not match_text_raw:
                    continue
                if rule.get("case_sensitive", False):
                    if match_text_raw not in source_text:
                        continue
                else:
                    if match_text_raw.lower() not in source_text_folded:
                        continue
                display = self._display_box_by_id(rule.get("target_display_id", ""))
                if display is None or not display.get("placed"):
                    continue
                sink_name = display.get("assigned_sink", "")
                if not sink_name:
                    continue
                sink = self._sink_by_name(sink_name)
                if sink is None:
                    continue
                current_sink_name = self._sink_name_from_id(stream.get("sink_id", ""))
                if current_sink_name == sink_name:
                    break
                if self._move_stream_to_sink(stream, sink, refresh=False, manual_override=False):
                    moved += 1
                break
        if moved:
            self._log(f"Applied routing rules: moved {moved} stream(s).")
            if refresh_after:
                self._do_refresh(allow_rule_apply=False)
        return moved

    def _on_display_zoom_change(self, _value=None):
        label = self._display_zoom_var.get().strip()
        zoom = _DISPLAY_ZOOM_FACTORS.get(label)
        if zoom is None:
            return
        self._display_zoom = zoom
        self._render_display_map()
        self._set_status(f"Speaker map zoom set to {label}.")

    def _step_display_zoom(self, step):
        labels = list(_DISPLAY_ZOOM_FACTORS.keys())
        current = self._display_zoom_var.get().strip()
        if current not in _DISPLAY_ZOOM_FACTORS:
            current = "100%"
        idx = labels.index(current)
        idx = min(max(idx + step, 0), len(labels) - 1)
        self._display_zoom_var.set(labels[idx])
        self._on_display_zoom_change()

    def _set_selected_display_size(self, size):
        display = self._selected_display()
        if display is None:
            self._set_status("Select a speaker first.")
            return
        if size not in _DISPLAY_SIZE_PRESETS:
            return
        display["size"] = size
        self._ensure_display_within_canvas(display)
        self._save_config()
        self._render_display_map()
        self._set_status(f"Changed {display['label']} size to {size}.")

    def _set_selected_display_label_mode(self, label_mode):
        display = self._selected_display()
        if display is None:
            self._set_status("Select a speaker first.")
            return
        if label_mode not in {"friendly", "technical"}:
            return
        display["label_mode"] = label_mode
        self._save_config()
        self._render_display_map()
        self._set_status(
            f"Changed {display['label']} label mode to {label_mode}."
        )

    def _toggle_selected_display_label_mode(self):
        display = self._selected_display()
        if display is None:
            self._set_status("Select a speaker first.")
            return
        next_mode = (
            "technical"
            if display.get("label_mode", "friendly") == "friendly"
            else "friendly"
        )
        self._set_selected_display_label_mode(next_mode)

    def _set_selected_display_orientation(self, orientation):
        display = self._selected_display()
        if display is None:
            self._set_status("Select a speaker first.")
            return
        if orientation not in {"landscape", "portrait"}:
            return
        display["orientation"] = orientation
        self._ensure_display_within_canvas(display)
        self._save_config()
        self._render_display_map()
        self._set_status(
            f"Changed {display['label']} orientation to {orientation}."
        )

    def _toggle_selected_display_orientation(self):
        display = self._selected_display()
        if display is None:
            self._set_status("Select a speaker first.")
            return
        display["orientation"] = (
            "portrait"
            if display.get("orientation", "landscape") == "landscape"
            else "landscape"
        )
        self._ensure_display_within_canvas(display)
        self._save_config()
        self._render_display_map()
        self._set_status(
            f"Changed {display['label']} orientation to {display['orientation']}."
        )

    def _ensure_display_within_canvas(self, display):
        width, height = self._display_dimensions(display)
        canvas_width = self._canvas_layout_width()
        canvas_height = self._canvas_layout_height()
        max_x = max(_DISPLAY_LAYOUT_PADDING, canvas_width - width - _DISPLAY_LAYOUT_PADDING)
        max_y = max(_DISPLAY_LAYOUT_PADDING, canvas_height - height - _DISPLAY_LAYOUT_PADDING)
        display["x"] = min(max(int(display.get("x", 0)), _DISPLAY_LAYOUT_PADDING), max_x)
        display["y"] = min(max(int(display.get("y", 0)), _DISPLAY_LAYOUT_PADDING), max_y)

    def _soft_snap_coordinate(self, value):
        nearest = round(value / _DISPLAY_NUDGE) * _DISPLAY_NUDGE
        if abs(value - nearest) <= _DISPLAY_SOFT_SNAP:
            return nearest
        return value

    def _canvas_layout_width(self):
        return max(self._map_canvas.winfo_width(), 640) if self._map_canvas else 640

    def _canvas_layout_height(self):
        return max(self._map_canvas.winfo_height(), 320) if self._map_canvas else 320

    def _world_layout_width(self):
        viewport = self._canvas_layout_width()
        content = viewport
        for box in self._display_boxes:
            if not box.get("placed"):
                continue
            box_width, _ = self._display_dimensions(box)
            content = max(
                content,
                int(box.get("x", 0)) + box_width + _DISPLAY_LAYOUT_PADDING,
            )
        return int(round(content * self._display_zoom))

    def _world_layout_height(self):
        viewport = self._canvas_layout_height()
        content = viewport
        for box in self._display_boxes:
            if not box.get("placed"):
                continue
            _, box_height = self._display_dimensions(box)
            content = max(
                content,
                int(box.get("y", 0)) + box_height + _DISPLAY_LAYOUT_PADDING,
            )
        return int(round(content * self._display_zoom))

    def _event_to_world(self, event):
        canvas_x = self._map_canvas.canvasx(event.x)
        canvas_y = self._map_canvas.canvasy(event.y)
        return canvas_x / self._display_zoom, canvas_y / self._display_zoom

    def _display_dimensions_for_values(self, size, orientation):
        width, height = _DISPLAY_SIZE_PRESETS.get(size, _DISPLAY_SIZE_PRESETS["medium"])
        if orientation == "portrait":
            width, height = height, width
        return width, height

    def _display_dimensions(self, box):
        return self._display_dimensions_for_values(
            box.get("size", "medium"),
            box.get("orientation", "landscape"),
        )

    def _next_open_display_position(self, display):
        width, height = self._display_dimensions(display)
        canvas_width = self._canvas_layout_width()
        placed = [box for box in self._display_boxes if box.get("placed") and box.get("id") != display.get("id")]

        if not placed:
            return _DISPLAY_LAYOUT_PADDING, _DISPLAY_LAYOUT_PADDING

        row_height = max(
            (self._display_dimensions(box)[1] for box in placed),
            default=_DISPLAY_SIZE_PRESETS["medium"][1],
        )
        x = _DISPLAY_LAYOUT_PADDING
        y = _DISPLAY_LAYOUT_PADDING
        attempts = 0
        while attempts < 200:
            candidate = {
                "x1": x,
                "y1": y,
                "x2": x + width,
                "y2": y + height,
            }
            overlap = False
            for box in placed:
                bx, by = int(box.get("x", 0)), int(box.get("y", 0))
                bw, bh = self._display_dimensions(box)
                if not (
                    candidate["x2"] <= bx
                    or candidate["x1"] >= bx + bw
                    or candidate["y2"] <= by
                    or candidate["y1"] >= by + bh
                ):
                    overlap = True
                    break
            if not overlap:
                return x, y
            x += width + _DISPLAY_GAP
            if x + width > canvas_width - _DISPLAY_LAYOUT_PADDING:
                x = _DISPLAY_LAYOUT_PADDING
                y += row_height + _DISPLAY_GAP
            attempts += 1
        return _DISPLAY_LAYOUT_PADDING, _DISPLAY_LAYOUT_PADDING

    def _assign_display_sink(self, sink_name):
        display = self._selected_display()
        if display is None:
            self._set_status("Select a speaker first.")
            return
        display["assigned_sink"] = sink_name
        self._save_config()
        self._render_lists()
        self._render_display_map()
        if sink_name:
            self._set_status(
                f"Assigned {display['label']} to {self._display_sink_name(sink_name)}."
            )
        else:
            self._set_status(f"Cleared output assignment for {display['label']}.")

    def _on_right_click(self, event):
        widget = event.widget
        self._dismiss_context_menus()
        try:
            idx = widget.nearest(event.y)
        except Exception:
            return
        if idx is None or idx < 0:
            return
        try:
            widget.selection_clear(0, "end")
            widget.selection_set(idx)
            widget.activate(idx)
        except Exception:
            return

        if widget is self._lb_sinks:
            if self._selected_sink() is None:
                return
            interaction_support.show_popup_menu(
                self.frame.winfo_toplevel(), self._sink_menu, event.x_root, event.y_root
            )
            return

        if widget is self._lb_streams:
            stream = self._selected_stream()
            if stream is None:
                return
            self._populate_stream_menu(stream)
            interaction_support.show_popup_menu(
                self.frame.winfo_toplevel(),
                self._stream_menu,
                event.x_root,
                event.y_root,
            )

    def _dismiss_context_menus(self, _event=None):
        if _event is not None and isinstance(getattr(_event, "widget", None), tk.Menu):
            return
        for menu in (self._sink_menu, self._stream_menu, self._map_stream_menu, self._routing_rule_menu, self._display_menu):
            if menu is None:
                continue
            try:
                menu.unpost()
                menu.grab_release()
            except Exception:
                pass

    def _on_sink_double_click(self, _event=None):
        if self._selected_sink() is not None:
            self._on_set_default()

    def _on_stream_double_click(self, _event=None):
        stream = self._selected_stream()
        sink = self._selected_sink()
        if stream is None:
            self._set_status("Select a stream first.")
            return
        if sink is None:
            self._set_status("Select a target output first.")
            return
        self._move_stream_to_sink(stream, sink, manual_override=True)

    def _populate_stream_menu(self, stream):
        self._stream_menu.delete(0, "end")
        if not self._sinks:
            self._stream_menu.add_command(label="No outputs available", state="disabled")
            return
        current_sink_name = self._sink_name_from_id(stream.get("sink_id", ""))
        for sink in self._sinks:
            label = self._display_sink_name(sink["name"])
            if sink["name"] == current_sink_name:
                label += "  [current]"
            self._stream_menu.add_command(
                label=label,
                command=lambda sink_name=sink["name"]: self._move_selected_stream_to_sink_name(sink_name),
            )

    def _populate_map_stream_menu(self, stream):
        self._map_stream_menu.delete(0, "end")
        placed_displays = self._placed_display_boxes()
        if not placed_displays:
            self._map_stream_menu.add_command(
                label="No speakers on active speaker map",
                state="disabled",
            )
            return
        current_sink_name = self._sink_name_from_id(stream.get("sink_id", ""))
        added = False
        current_marked = False
        for display in placed_displays:
            sink_name = display.get("assigned_sink", "")
            if not sink_name:
                continue
            label = display.get("label", "(speaker)")
            sink_label = self._display_sink_name(sink_name)
            shared_count = self._active_speaker_count_for_sink(sink_name)
            if sink_name == current_sink_name:
                if not current_marked:
                    label += "  [current]"
                    current_marked = True
                else:
                    label += "  [same output]"
            elif shared_count > 1:
                label += f"  [shared x{shared_count}]"
            self._map_stream_menu.add_command(
                label=f"{label}  →  {sink_label}",
                command=lambda display_id=display["id"]: self._move_selected_map_stream_to_display_id(display_id),
            )
            added = True
        if not added:
            self._map_stream_menu.add_command(
                label="No active speakers have assigned outputs",
                state="disabled",
            )
            return
        self._map_stream_menu.add_separator()
        keyword = self._stream_rule_keyword(stream)
        for display in placed_displays:
            sink_name = display.get("assigned_sink", "")
            if not sink_name:
                continue
            self._map_stream_menu.add_command(
                label=(
                    f'Create Keyword Rule "{keyword}" → {display.get("label", "(speaker)")}'
                    if keyword
                    else f"Create Keyword Rule → {display.get('label', '(speaker)')}"
                ),
                command=lambda display_id=display["id"], stream_id=str(stream.get("id", "")).strip(): self._create_keyword_rule_from_stream_id(display_id, stream_id),
            )

    def _populate_routing_rule_menu(self, rule):
        self._routing_rule_menu.delete(0, "end")
        cap_label = "Cap Sensitive: On" if rule.get("case_sensitive", False) else "Cap Sensitive: Off"
        self._routing_rule_menu.add_command(
            label=cap_label,
            command=lambda rule_id=rule["id"]: self._toggle_routing_rule_case_sensitive(rule_id),
        )
        state_label = "Disable Rule" if rule.get("enabled", True) else "Enable Rule"
        self._routing_rule_menu.add_command(
            label=state_label,
            command=lambda rule_id=rule["id"]: self._toggle_routing_rule_enabled(rule_id),
        )
        placed_displays = [display for display in self._placed_display_boxes() if display.get("assigned_sink", "")]
        if placed_displays:
            self._routing_rule_menu.add_separator()
            for display in placed_displays:
                self._routing_rule_menu.add_command(
                    label=f"Retarget → {display.get('label', '(speaker)')}",
                    command=lambda rule_id=rule["id"], display_id=display["id"]: self._set_routing_rule_target(rule_id, display_id),
                )
        self._routing_rule_menu.add_separator()
        self._routing_rule_menu.add_command(
            label="Rename Keyword...",
            command=lambda rule_id=rule["id"]: self._rename_routing_rule_keyword(rule_id),
        )
        self._routing_rule_menu.add_command(
            label="Delete Rule",
            command=self._delete_selected_routing_rule,
        )

    def _move_selected_map_stream_to_display_id(self, display_id):
        display = self._display_box_by_id(display_id)
        if display is None:
            self._set_status("Selected speaker no longer exists.")
            return
        sink_name = display.get("assigned_sink", "")
        if not sink_name:
            self._set_status("Selected speaker has no assigned output.")
            return
        if not self._have_pactl:
            self._set_status("pactl not available.")
            return
        stream = self._selected_map_stream()
        if stream is None:
            self._set_status("Select a stream in the speaker map tab first.")
            return
        sink = self._sink_by_name(sink_name)
        if sink is None:
            self._set_status("Assigned output is currently unavailable.")
            return
        self._move_stream_to_sink(stream, sink, manual_override=True, override_display_id=display_id)

    def _rename_selected_sink(self):
        sink = self._selected_sink()
        if sink is None:
            self._set_status("Select an output first.")
            return
        current_alias = self._sink_aliases.get(sink["name"], "")
        value = simpledialog.askstring(
            "Rename Output",
            f"Custom name for:\n{sink['name']}",
            initialvalue=current_alias,
            parent=self.frame,
        )
        if value is None:
            return
        cleaned = value.strip()
        if not cleaned:
            self._sink_aliases.pop(sink["name"], None)
            self._save_config()
            self._render_lists()
            self._render_display_map()
            self._set_status(f"Reset output name for {sink['name']}.")
            self._log(f"reset output alias: {sink['name']}")
            return
        self._sink_aliases[sink["name"]] = cleaned
        self._save_config()
        self._render_lists()
        self._render_display_map()
        self._set_status(f"Renamed output to {cleaned}.")
        self._log(f"set output alias: {sink['name']} -> {cleaned}")

    def _reset_selected_sink_name(self):
        sink = self._selected_sink()
        if sink is None:
            self._set_status("Select an output first.")
            return
        if sink["name"] not in self._sink_aliases:
            self._set_status("Output already uses default name.")
            return
        self._sink_aliases.pop(sink["name"], None)
        self._save_config()
        self._render_lists()
        self._render_display_map()
        self._set_status(f"Reset output name for {sink['name']}.")
        self._log(f"reset output alias: {sink['name']}")

    def _move_selected_stream_to_sink_name(self, sink_name):
        stream = self._selected_stream()
        if stream is None:
            self._set_status("Select a stream first.")
            return
        sink = self._sink_by_name(sink_name)
        if sink is None:
            self._set_status("Target output no longer exists. Refresh and try again.")
            return
        self._move_stream_to_sink(stream, sink, manual_override=True)

    def _sink_by_name(self, sink_name):
        for sink in self._sinks:
            if sink.get("name") == sink_name:
                return sink
        return None

    def _find_all_outputs_module_id(self):
        result = _run(["pactl", "list", "short", "modules"])
        if result["error"] is not None or result["rc"] != 0:
            return ""
        for line in result["stdout"].splitlines():
            parts = line.split("\t", 2)
            if len(parts) < 3:
                continue
            module_id, module_name, module_args = parts[0].strip(), parts[1].strip(), parts[2]
            if module_name != "module-combine-sink":
                continue
            if f"sink_name={_ALL_OUTPUTS_SINK_NAME}" in module_args:
                return module_id
        return ""

    def _toggle_all_outputs(self):
        if not self._have_pactl:
            self._set_status("pactl not available.")
            return
        if self._is_all_outputs_active():
            self._disable_all_outputs()
            return
        self._enable_all_outputs()

    def _enable_all_outputs(self):
        sink_names = self._active_speaker_sink_names()
        if len(sink_names) < 2:
            self._set_status("Need at least two active speaker outputs for All Outputs.")
            return
        self._all_outputs_previous_default = self._default_sink if self._default_sink != _ALL_OUTPUTS_SINK_NAME else ""
        args = [
            "pactl",
            "load-module",
            "module-combine-sink",
            f"sink_name={_ALL_OUTPUTS_SINK_NAME}",
            f"sinks={','.join(sink_names)}",
            "sink_properties=device.description=All Outputs",
        ]
        result = _run(args, timeout=8)
        if result["error"] is not None or result["rc"] != 0:
            err = result["error"] or result["stderr"].strip() or f"rc={result['rc']}"
            self._log(f"load-module module-combine-sink failed: {err}")
            self._log_block("raw stdout", result["stdout"])
            self._set_status("All Outputs enable failed.")
            return
        self._all_outputs_module_id = result["stdout"].strip()
        self._do_refresh(allow_rule_apply=False)
        combined_sink = self._sink_by_name(_ALL_OUTPUTS_SINK_NAME)
        if combined_sink is None:
            self._set_status("All Outputs sink did not appear after enable.")
            return
        set_default = _run(["pactl", "set-default-sink", _ALL_OUTPUTS_SINK_NAME])
        if set_default["error"] is not None or set_default["rc"] != 0:
            err = set_default["error"] or set_default["stderr"].strip() or f"rc={set_default['rc']}"
            self._log(f"set-default-sink {_ALL_OUTPUTS_SINK_NAME!r} failed: {err}")
            self._log_block("raw stdout", set_default["stdout"])
            self._set_status("All Outputs enabled, but setting default failed.")
            self._do_refresh(allow_rule_apply=False)
            return
        moved = 0
        for stream in self._streams:
            current_sink_name = self._sink_name_from_id(stream.get("sink_id", ""))
            if current_sink_name == _ALL_OUTPUTS_SINK_NAME:
                continue
            if self._move_stream_to_sink(stream, combined_sink, refresh=False, manual_override=False):
                moved += 1
        self._log(f"all outputs enabled using {len(sink_names)} sink(s)")
        self._do_refresh(allow_rule_apply=False)
        self._set_status(f"All Outputs enabled. Moved {moved} stream(s) to the combined output.")

    def _disable_all_outputs(self):
        module_id = self._all_outputs_module_id or self._find_all_outputs_module_id()
        if not module_id:
            self._set_status("All Outputs module not found.")
            self._do_refresh(allow_rule_apply=False)
            return
        result = _run(["pactl", "unload-module", module_id])
        if result["error"] is not None or result["rc"] != 0:
            err = result["error"] or result["stderr"].strip() or f"rc={result['rc']}"
            self._log(f"unload-module {module_id!r} failed: {err}")
            self._log_block("raw stdout", result["stdout"])
            self._set_status("All Outputs disable failed.")
            return
        self._all_outputs_module_id = ""
        self._do_refresh(allow_rule_apply=False)
        restored = False
        if self._all_outputs_previous_default:
            previous_sink = self._sink_by_name(self._all_outputs_previous_default)
            if previous_sink is not None:
                restore = _run(["pactl", "set-default-sink", self._all_outputs_previous_default])
                if restore["error"] is None and restore["rc"] == 0:
                    restored = True
        self._do_refresh(allow_rule_apply=False)
        self._set_status(
            "All Outputs disabled and default restored."
            if restored
            else "All Outputs disabled."
        )

    def _on_set_default(self):
        if not self._have_pactl:
            self._set_status("pactl not available.")
            return
        sink = self._selected_sink()
        if sink is None:
            self._set_status("Select a sink first.")
            return
        self._set_default_to_sink_name(sink["name"])

    def _set_default_to_sink_name(self, sink_name):
        sink = self._sink_by_name(sink_name)
        if sink is None:
            self._set_status("Target output no longer exists. Refresh and try again.")
            return
        result = _run(["pactl", "set-default-sink", sink_name])
        if result["error"] is not None or result["rc"] != 0:
            err = result["error"] or result["stderr"].strip() or f"rc={result['rc']}"
            self._log(f"set-default-sink {sink_name!r} failed: {err}")
            self._log_block("raw stdout", result["stdout"])
            self._set_status("Set default failed.")
            return
        self._log(f"set-default-sink: {sink_name}")
        self._set_status(f"Default sink set to {self._display_sink_name(sink_name)}.")
        self._do_refresh()

    def _on_move_stream(self):
        if not self._have_pactl:
            self._set_status("pactl not available.")
            return
        stream = self._selected_stream()
        sink = self._selected_sink()
        if stream is None:
            self._set_status("Select a stream first.")
            return
        if sink is None:
            self._set_status("Select a target sink first.")
            return
        self._move_stream_to_sink(stream, sink, manual_override=True)

    def _move_stream_to_sink(self, stream, sink, refresh=True, manual_override=False, override_display_id=""):
        result = _run(["pactl", "move-sink-input", stream["id"], sink["name"]])
        if result["error"] is not None or result["rc"] != 0:
            err = result["error"] or result["stderr"].strip() or f"rc={result['rc']}"
            self._log(
                f"move-sink-input {stream['id']} -> {sink['name']} failed: {err}"
            )
            self._log_block("raw stdout", result["stdout"])
            self._set_status("Move stream failed.")
            return False
        self._log(
            f"move-sink-input: stream {stream['id']} "
            f"({stream.get('app_name') or 'unknown app'}) "
            f"→ {self._display_sink_name(sink['name'])}"
        )
        self._set_status(
            f"Moved stream {stream['id']} to {self._display_sink_name(sink['name'])}."
        )
        if manual_override:
            self._mark_stream_manual_override(stream, sink["name"], display_id=override_display_id)
        else:
            self._stream_manual_overrides.pop(str(stream.get("id", "")).strip(), None)
        if refresh:
            self._do_refresh()
        return True

    def _set_default_from_selected_display(self):
        display = self._selected_display()
        if display is None:
            self._set_status("Select a speaker first.")
            return
        sink_name = display.get("assigned_sink", "")
        if not sink_name:
            self._set_status("Assign an output to this speaker first.")
            return
        if not self._have_pactl:
            self._set_status("pactl not available.")
            return
        self._set_default_to_sink_name(sink_name)

    def _move_map_stream_to_selected_display(self):
        display = self._selected_display()
        if display is None:
            self._set_status("Select a speaker first.")
            return
        sink_name = display.get("assigned_sink", "")
        if not sink_name:
            self._set_status("Assign an output to this speaker first.")
            return
        if not self._have_pactl:
            self._set_status("pactl not available.")
            return
        stream = self._selected_map_stream()
        if stream is None:
            self._set_status("Select a stream in the speaker map tab first.")
            return
        sink = self._sink_by_name(sink_name)
        if sink is None:
            self._set_status("Assigned output is currently unavailable.")
            return
        self._move_stream_to_sink(stream, sink, manual_override=True, override_display_id=display.get("id", ""))

    def _on_wpctl_status(self):
        if not self._have_wpctl:
            self._set_status("wpctl not available.")
            return
        result = _run(["wpctl", "status"], timeout=5)
        if result["error"] is not None:
            self._log(f"wpctl status failed: {result['error']}")
            self._set_status("wpctl status failed.")
            return
        self._log_block("wpctl status", result["stdout"] or result["stderr"])
        self._set_status("wpctl status captured.")
