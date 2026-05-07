"""
page_linux_monitor_manager / linux_monitor_manager_page.py
──────────────────────────────────────────────────────────────────────────────
Linux monitor manager page for pagepack_chilos.

Shell contract:
    page = PageLinuxMonitorManager(parent_widget)
    page.build(parent)   # also: create_widgets / mount / render

Design goals:
    - always provide a working display-map editor and local profiles
    - apply live display changes only when a supported Linux backend is present
    - keep backend detection and live control explicit in the UI
    - stay dependency-free beyond native system tools already present
"""

from __future__ import annotations

import copy
import datetime
import json
import os
import re
import shutil
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

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

_ZOOM_FACTORS = {
    "25%": 0.25,
    "50%": 0.5,
    "75%": 0.75,
    "100%": 1.0,
    "125%": 1.25,
    "150%": 1.5,
    "200%": 2.0,
}
_SCALE_CHOICES = ("0.75", "1.0", "1.25", "1.5", "1.75", "2.0", "2.5")
_ROTATION_LABELS = {
    "none": "Landscape",
    "left": "Portrait Left",
    "right": "Portrait Right",
    "inverted": "Inverted",
}
_ROTATION_ORDER = ("none", "left", "right", "inverted")
_SOFT_SNAP = 18
_GRID_STEP = 24
_LAYOUT_PADDING = 24
_BOX_BORDER = 2


def _bind_scroll(widget):
    interaction_support.bind_wheel_scroll(widget)


def _run(argv, timeout=8):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
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


def _slugify_profile(name):
    cleaned = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return cleaned or "profile"


def _fmt_scale(value):
    try:
        return f"{float(value):g}"
    except Exception:
        return "1"


def _parse_scale(text, default=1.0):
    try:
        value = float(str(text).strip())
        if value <= 0:
            raise ValueError
        return value
    except Exception:
        return float(default)


def _rotation_label(rotation):
    return _ROTATION_LABELS.get(rotation, rotation.title())


def _rotation_from_numeric(value):
    mapping = {
        1: "none",
        2: "left",
        4: "inverted",
        8: "right",
    }
    try:
        return mapping.get(int(value), "none")
    except Exception:
        return "none"


def _rotation_is_portrait(rotation):
    return rotation in {"left", "right"}


def _clone_monitor(monitor):
    return copy.deepcopy(monitor)


class _DisplayBackendBase:
    backend_id = "unsupported"
    backend_label = "Local-Only"

    def is_available(self):
        return False

    def read_layout(self):
        return {
            "ok": False,
            "backend_id": self.backend_id,
            "backend_label": self.backend_label,
            "capabilities": self.capabilities(),
            "monitors": [],
            "error": "No live display backend is available.",
        }

    def apply_layout(self, _monitors):
        return {
            "ok": False,
            "stdout": "",
            "stderr": "",
            "error": "Live apply is unavailable for this backend.",
        }

    def capabilities(self):
        return {
            "can_read_layout": False,
            "can_apply_layout": False,
            "can_change_mode": False,
            "can_change_scale": False,
            "can_change_rotation": False,
            "can_change_primary": False,
            "can_enable_disable": False,
        }


class _KScreenDoctorBackend(_DisplayBackendBase):
    backend_id = "kscreen_wayland"
    backend_label = "KDE Plasma / Wayland"

    def __init__(self):
        self._exe = shutil.which("kscreen-doctor")

    def is_available(self):
        desktop = (os.environ.get("XDG_CURRENT_DESKTOP") or "").lower()
        session = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
        return bool(self._exe and "kde" in desktop and session == "wayland")

    def capabilities(self):
        return {
            "can_read_layout": True,
            "can_apply_layout": True,
            "can_change_mode": True,
            "can_change_scale": True,
            "can_change_rotation": True,
            "can_change_primary": True,
            "can_enable_disable": True,
        }

    def read_layout(self):
        result = _run([self._exe, "--json"])
        if result["error"]:
            return {
                "ok": False,
                "backend_id": self.backend_id,
                "backend_label": self.backend_label,
                "capabilities": self.capabilities(),
                "monitors": [],
                "error": result["error"],
            }
        if result["rc"] != 0:
            return {
                "ok": False,
                "backend_id": self.backend_id,
                "backend_label": self.backend_label,
                "capabilities": self.capabilities(),
                "monitors": [],
                "error": result["stderr"].strip() or "kscreen-doctor returned a non-zero status.",
            }
        try:
            payload = json.loads(result["stdout"])
        except Exception as ex:
            return {
                "ok": False,
                "backend_id": self.backend_id,
                "backend_label": self.backend_label,
                "capabilities": self.capabilities(),
                "monitors": [],
                "error": f"Failed to parse kscreen JSON: {ex}",
            }

        raw_outputs = payload.get("outputs") or []
        priorities = [
            int(item.get("priority", 0))
            for item in raw_outputs
            if item.get("enabled") and int(item.get("priority", 0)) > 0
        ]
        primary_priority = min(priorities) if priorities else 1

        monitors = []
        for raw in raw_outputs:
            name = str(raw.get("name") or f"output-{raw.get('id', '?')}").strip()
            modes = []
            for mode in raw.get("modes") or []:
                size = mode.get("size") or {}
                mode_name = str(mode.get("name") or "").strip()
                modes.append(
                    {
                        "id": str(mode.get("id") or ""),
                        "name": mode_name,
                        "width": int(size.get("width") or 0),
                        "height": int(size.get("height") or 0),
                        "refresh": float(mode.get("refreshRate") or 0),
                    }
                )
            current_mode_id = str(raw.get("currentModeId") or "")
            current_mode = next((m for m in modes if m["id"] == current_mode_id), None)
            size = raw.get("size") or {}
            pos = raw.get("pos") or {}
            enabled = bool(raw.get("enabled"))
            priority = int(raw.get("priority") or 0)
            monitor = {
                "connector": name,
                "backend_name": name,
                "backend_output_id": str(raw.get("id") or ""),
                "connected": bool(raw.get("connected")),
                "enabled": enabled,
                "primary": enabled and priority == primary_priority,
                "priority": priority,
                "x": int(pos.get("x") or 0),
                "y": int(pos.get("y") or 0),
                "rotation": _rotation_from_numeric(raw.get("rotation", 1)),
                "scale": float(raw.get("scale") or 1.0),
                "mode_id": current_mode_id,
                "mode_name": current_mode["name"] if current_mode else "",
                "width": int(size.get("width") or (current_mode or {}).get("width") or 0),
                "height": int(size.get("height") or (current_mode or {}).get("height") or 0),
                "modes": modes,
                "label_mode": "friendly",
                "friendly_name": name,
            }
            monitors.append(monitor)

        return {
            "ok": True,
            "backend_id": self.backend_id,
            "backend_label": self.backend_label,
            "capabilities": self.capabilities(),
            "monitors": monitors,
            "error": "",
        }

    def apply_layout(self, monitors):
        args = [self._exe]
        enabled_monitors = [m for m in monitors if m.get("enabled")]
        primary_connector = ""
        for monitor in enabled_monitors:
            if monitor.get("primary"):
                primary_connector = monitor["connector"]
                break
        if not primary_connector and enabled_monitors:
            primary_connector = enabled_monitors[0]["connector"]

        sorted_for_priority = []
        if enabled_monitors:
            primary_monitor = next(
                (m for m in enabled_monitors if m["connector"] == primary_connector),
                enabled_monitors[0],
            )
            sorted_for_priority.append(primary_monitor)
            for monitor in enabled_monitors:
                if monitor["connector"] == primary_monitor["connector"]:
                    continue
                sorted_for_priority.append(monitor)

        priority_map = {
            monitor["connector"]: index + 1
            for index, monitor in enumerate(sorted_for_priority)
        }

        for monitor in monitors:
            name = monitor["connector"]
            if monitor.get("enabled"):
                args.append(f"output.{name}.enable")
                mode_name = str(monitor.get("mode_name") or "").strip()
                if mode_name:
                    args.append(f"output.{name}.mode.{mode_name}")
                args.append(f"output.{name}.position.{int(monitor.get('x', 0))},{int(monitor.get('y', 0))}")
                args.append(f"output.{name}.rotation.{monitor.get('rotation', 'none')}")
                args.append(f"output.{name}.scale.{_fmt_scale(monitor.get('scale', 1.0))}")
                if name in priority_map:
                    args.append(f"output.{name}.priority.{priority_map[name]}")
            else:
                args.append(f"output.{name}.disable")

        result = _run(args, timeout=12)
        ok = result["error"] is None and result["rc"] == 0
        return {
            "ok": ok,
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "error": result["error"] or ("" if ok else result["stderr"].strip() or "kscreen-doctor apply failed."),
        }


class _XrandrBackend(_DisplayBackendBase):
    backend_id = "xrandr_x11"
    backend_label = "X11 / xrandr"

    def __init__(self):
        self._exe = shutil.which("xrandr")

    def is_available(self):
        session = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
        return bool(self._exe and session == "x11")

    def capabilities(self):
        return {
            "can_read_layout": True,
            "can_apply_layout": True,
            "can_change_mode": True,
            "can_change_scale": False,
            "can_change_rotation": True,
            "can_change_primary": True,
            "can_enable_disable": True,
        }

    def read_layout(self):
        result = _run([self._exe, "--query"])
        if result["error"]:
            return {
                "ok": False,
                "backend_id": self.backend_id,
                "backend_label": self.backend_label,
                "capabilities": self.capabilities(),
                "monitors": [],
                "error": result["error"],
            }
        if result["rc"] != 0:
            return {
                "ok": False,
                "backend_id": self.backend_id,
                "backend_label": self.backend_label,
                "capabilities": self.capabilities(),
                "monitors": [],
                "error": result["stderr"].strip() or "xrandr returned a non-zero status.",
            }

        monitors = []
        current = None
        for raw_line in result["stdout"].splitlines():
            if not raw_line.startswith(" "):
                if current is not None:
                    monitors.append(current)
                current = None
                parts = raw_line.split()
                if len(parts) < 2:
                    continue
                connector = parts[0]
                connected = parts[1] == "connected"
                enabled = connected and not any(token == "disconnected" for token in parts[1:3])
                primary = "primary" in parts
                x = y = width = height = 0
                mode_name = ""
                rotation = "none"
                match = re.search(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", raw_line)
                if match:
                    width = int(match.group(1))
                    height = int(match.group(2))
                    x = int(match.group(3))
                    y = int(match.group(4))
                    mode_name = f"{width}x{height}"
                current = {
                    "connector": connector,
                    "backend_name": connector,
                    "backend_output_id": connector,
                    "connected": connected,
                    "enabled": enabled and connected,
                    "primary": primary,
                    "priority": 1 if primary else 50,
                    "x": x,
                    "y": y,
                    "rotation": rotation,
                    "scale": 1.0,
                    "mode_id": mode_name,
                    "mode_name": mode_name,
                    "width": width,
                    "height": height,
                    "modes": [],
                    "label_mode": "friendly",
                    "friendly_name": connector,
                }
                continue

            if current is None or not current.get("connected"):
                continue
            line = raw_line.strip()
            mode_match = re.match(r"^(\d+)x(\d+)\s+([0-9.]+)([*+]?)", line)
            if mode_match:
                mode_name = f"{mode_match.group(1)}x{mode_match.group(2)}"
                refresh = float(mode_match.group(3))
                current["modes"].append(
                    {
                        "id": f"{mode_name}@{refresh:g}",
                        "name": f"{mode_name}@{refresh:g}",
                        "width": int(mode_match.group(1)),
                        "height": int(mode_match.group(2)),
                        "refresh": refresh,
                    }
                )
                if "*" in line:
                    current["mode_name"] = f"{mode_name}@{refresh:g}"
                    current["mode_id"] = current["mode_name"]
                    current["width"] = int(mode_match.group(1))
                    current["height"] = int(mode_match.group(2))
        if current is not None:
            monitors.append(current)

        return {
            "ok": True,
            "backend_id": self.backend_id,
            "backend_label": self.backend_label,
            "capabilities": self.capabilities(),
            "monitors": monitors,
            "error": "",
        }

    def apply_layout(self, monitors):
        args = [self._exe]
        primary_connector = ""
        enabled_monitors = [m for m in monitors if m.get("enabled")]
        for monitor in enabled_monitors:
            if monitor.get("primary"):
                primary_connector = monitor["connector"]
                break
        if not primary_connector and enabled_monitors:
            primary_connector = enabled_monitors[0]["connector"]

        for monitor in monitors:
            args.extend(["--output", monitor["connector"]])
            if not monitor.get("enabled"):
                args.append("--off")
                continue
            mode_name = str(monitor.get("mode_name") or "").strip()
            args.append("--auto" if not mode_name else "--mode")
            if mode_name:
                args.append(mode_name.split("@", 1)[0])
            args.extend(["--pos", f"{int(monitor.get('x', 0))}x{int(monitor.get('y', 0))}"])
            args.extend(["--rotate", monitor.get("rotation", "none")])
            if monitor["connector"] == primary_connector:
                args.append("--primary")

        result = _run(args, timeout=12)
        ok = result["error"] is None and result["rc"] == 0
        return {
            "ok": ok,
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "error": result["error"] or ("" if ok else result["stderr"].strip() or "xrandr apply failed."),
        }


class PageLinuxMonitorManager:
    PAGE_NAME = "linux_monitor_manager"

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
        self._style_prefix = f"LinuxMonitorManager.{id(self)}"

        self._style = None
        self._backend = self._choose_backend()
        self._backend_capabilities = self._backend.capabilities()
        self._backend_label = self._backend.backend_label

        self._config_path = os.path.join(
            Path(__file__).resolve().parent, "linux_monitor_manager_config.json"
        )
        self._config = self._load_config()
        self._live_monitors = []
        self._monitors = []
        self._selected_connector = ""
        self._box_items = {}
        self._drag_connector = ""
        self._drag_offset_x = 0.0
        self._drag_offset_y = 0.0

        self._map_canvas = None
        self._map_canvas_xscroll = None
        self._map_canvas_yscroll = None
        self._profile_list = None
        self._txt_log = None

        self._var_status = tk.StringVar(value="Ready.")
        self._var_backend = tk.StringVar(value="")
        self._var_zoom = tk.StringVar(value=self._config.get("ui", {}).get("zoom_label", "100%"))
        self._var_display_name = tk.StringVar(value="")
        self._var_label_mode = tk.StringVar(value="friendly")
        self._var_enabled = tk.BooleanVar(value=True)
        self._var_primary = tk.BooleanVar(value=False)
        self._var_rotation = tk.StringVar(value="none")
        self._var_mode = tk.StringVar(value="")
        self._var_scale = tk.StringVar(value="1.0")
        self._var_position = tk.StringVar(value="")
        self._var_selection = tk.StringVar(value="No display selected.")
        self._display_zoom = _ZOOM_FACTORS.get(self._var_zoom.get(), 1.0)

        self._context_menu = None

        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)

        self._build_top_bar()
        self._build_body()
        self._build_status_bar()
        self._apply_theme()
        self._refresh_from_backend(initial=True)

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
                self._refresh_from_backend(initial=True)
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

    def build(self, parent=None): return self._embed_into_parent(parent)
    def create_widgets(self, parent=None): return self._embed_into_parent(parent)
    def mount(self, parent=None): return self._embed_into_parent(parent)
    def render(self, parent=None): return self._embed_into_parent(parent)

    def _choose_backend(self):
        for backend in (_KScreenDoctorBackend(), _XrandrBackend()):
            if backend.is_available():
                return backend
        return _DisplayBackendBase()

    def _build_top_bar(self):
        bar = ttk.Frame(self.frame, padding=(4, 4), style=f"{self._style_prefix}.TFrame")
        bar.grid(row=0, column=0, sticky="ew")
        for idx in range(8):
            bar.columnconfigure(idx, weight=0)
        bar.columnconfigure(8, weight=1)
        self._top_bar = bar

        ttk.Button(
            bar, text="Refresh Live", command=self._refresh_from_backend,
            style=f"{self._style_prefix}.TButton"
        ).grid(row=0, column=0, padx=(0, 4))
        ttk.Button(
            bar, text="Revert To Live", command=self._revert_to_live,
            style=f"{self._style_prefix}.TButton"
        ).grid(row=0, column=1, padx=4)
        ttk.Button(
            bar, text="Apply Layout", command=self._apply_live_layout,
            style=f"{self._style_prefix}.TButton"
        ).grid(row=0, column=2, padx=4)
        ttk.Button(
            bar, text="Save Profile", command=self._save_profile_prompt,
            style=f"{self._style_prefix}.TButton"
        ).grid(row=0, column=3, padx=4)
        ttk.Button(
            bar, text="Load Profile", command=self._load_selected_profile,
            style=f"{self._style_prefix}.TButton"
        ).grid(row=0, column=4, padx=4)
        ttk.Button(
            bar, text="Delete Profile", command=self._delete_selected_profile,
            style=f"{self._style_prefix}.TButton"
        ).grid(row=0, column=5, padx=4)

        ttk.Label(
            bar, text="Zoom", style=f"{self._style_prefix}.Status.TLabel"
        ).grid(row=0, column=6, padx=(12, 6))
        zoom_menu = ttk.OptionMenu(
            bar,
            self._var_zoom,
            self._var_zoom.get(),
            *list(_ZOOM_FACTORS.keys()),
            command=self._on_zoom_change,
        )
        zoom_menu.grid(row=0, column=7, sticky="w")

        ttk.Label(
            bar,
            textvariable=self._var_backend,
            anchor="e",
            style=f"{self._style_prefix}.Status.TLabel",
        ).grid(row=0, column=8, sticky="ew", padx=(12, 0))

    def _build_body(self):
        body = ttk.Frame(self.frame, padding=(4, 2), style=f"{self._style_prefix}.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)
        body.rowconfigure(1, weight=0)
        self._body_frame = body

        map_outer = ttk.LabelFrame(
            body, text="Display Map", padding=(4, 4),
            style=f"{self._style_prefix}.TLabelframe"
        )
        map_outer.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        map_outer.columnconfigure(0, weight=1)
        map_outer.columnconfigure(1, weight=0)
        map_outer.rowconfigure(0, weight=1)
        map_outer.rowconfigure(1, weight=0)

        self._map_canvas = tk.Canvas(
            map_outer, height=360, highlightthickness=1, borderwidth=0, relief="solid"
        )
        self._map_canvas.grid(row=0, column=0, sticky="nsew")
        self._map_canvas_xscroll = ttk.Scrollbar(
            map_outer, orient="horizontal", command=self._map_canvas.xview
        )
        self._map_canvas_xscroll.grid(row=1, column=0, sticky="ew")
        self._map_canvas_yscroll = ttk.Scrollbar(
            map_outer, orient="vertical", command=self._map_canvas.yview
        )
        self._map_canvas_yscroll.grid(row=0, column=1, sticky="ns")
        self._map_canvas.configure(
            xscrollcommand=self._map_canvas_xscroll.set,
            yscrollcommand=self._map_canvas_yscroll.set,
        )
        self._map_canvas.bind("<Button-1>", self._on_map_click, add="+")
        self._map_canvas.bind("<B1-Motion>", self._on_map_drag, add="+")
        self._map_canvas.bind("<ButtonRelease-1>", self._on_map_release, add="+")
        self._map_canvas.bind("<Button-3>", self._on_map_right_click, add="+")
        self._map_canvas.bind("<Control-Button-1>", self._on_map_right_click, add="+")
        self._map_canvas.bind("<MouseWheel>", self._on_map_mousewheel, add="+")
        self._map_canvas.bind("<Shift-MouseWheel>", self._on_map_mousewheel, add="+")
        self._map_canvas.bind("<Button-4>", self._on_map_mousewheel, add="+")
        self._map_canvas.bind("<Button-5>", self._on_map_mousewheel, add="+")
        self._map_canvas.bind("<Configure>", self._on_canvas_configure, add="+")

        side = ttk.Frame(body, style=f"{self._style_prefix}.TFrame")
        side.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        side.columnconfigure(0, weight=1)
        side.rowconfigure(1, weight=1)

        inspector = ttk.LabelFrame(
            side, text="Inspector", padding=(6, 6),
            style=f"{self._style_prefix}.TLabelframe"
        )
        inspector.grid(row=0, column=0, sticky="ew")
        inspector.columnconfigure(1, weight=1)
        self._inspector = inspector

        ttk.Label(
            inspector, textvariable=self._var_selection, justify="left",
            style=f"{self._style_prefix}.Status.TLabel"
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(inspector, text="Nickname", style=f"{self._style_prefix}.Status.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Entry(inspector, textvariable=self._var_display_name).grid(row=1, column=1, sticky="ew", padx=(8, 0))

        ttk.Label(inspector, text="Label Mode", style=f"{self._style_prefix}.Status.TLabel").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(
            inspector, state="readonly", textvariable=self._var_label_mode,
            values=("friendly", "technical")
        ).grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))

        ttk.Label(inspector, text="Rotation", style=f"{self._style_prefix}.Status.TLabel").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(
            inspector, state="readonly", textvariable=self._var_rotation,
            values=_ROTATION_ORDER
        ).grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))

        ttk.Label(inspector, text="Mode", style=f"{self._style_prefix}.Status.TLabel").grid(row=4, column=0, sticky="w", pady=(6, 0))
        self._mode_combo = ttk.Combobox(inspector, textvariable=self._var_mode)
        self._mode_combo.grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))

        ttk.Label(inspector, text="Scale", style=f"{self._style_prefix}.Status.TLabel").grid(row=5, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(
            inspector, textvariable=self._var_scale, values=_SCALE_CHOICES
        ).grid(row=5, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))

        ttk.Label(inspector, text="Position", style=f"{self._style_prefix}.Status.TLabel").grid(row=6, column=0, sticky="w", pady=(6, 0))
        ttk.Label(inspector, textvariable=self._var_position, style=f"{self._style_prefix}.Status.TLabel").grid(row=6, column=1, sticky="w", padx=(8, 0), pady=(6, 0))

        toggle_row = ttk.Frame(inspector, style=f"{self._style_prefix}.TFrame")
        toggle_row.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        toggle_row.columnconfigure(0, weight=1)
        toggle_row.columnconfigure(1, weight=1)
        ttk.Checkbutton(toggle_row, text="Enabled", variable=self._var_enabled).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(toggle_row, text="Primary", variable=self._var_primary).grid(row=0, column=1, sticky="w")

        action_row = ttk.Frame(inspector, style=f"{self._style_prefix}.TFrame")
        action_row.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        action_row.columnconfigure(0, weight=1)
        action_row.columnconfigure(1, weight=1)
        ttk.Button(
            action_row, text="Stage Changes", command=self._stage_inspector_changes,
            style=f"{self._style_prefix}.TButton"
        ).grid(row=0, column=0, sticky="ew", padx=(0, 3))
        ttk.Button(
            action_row, text="Rename", command=self._rename_selected_display,
            style=f"{self._style_prefix}.TButton"
        ).grid(row=0, column=1, sticky="ew", padx=(3, 0))

        profile_outer = ttk.LabelFrame(
            side, text="Profiles", padding=(4, 4),
            style=f"{self._style_prefix}.TLabelframe"
        )
        profile_outer.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        profile_outer.columnconfigure(0, weight=1)
        profile_outer.rowconfigure(0, weight=1)
        self._profile_list = tk.Listbox(
            profile_outer, height=8, selectmode="single", exportselection=False, font=("monospace", 9)
        )
        profile_scroll = ttk.Scrollbar(profile_outer, orient="vertical", command=self._profile_list.yview)
        self._profile_list.configure(yscrollcommand=profile_scroll.set)
        self._profile_list.grid(row=0, column=0, sticky="nsew")
        profile_scroll.grid(row=0, column=1, sticky="ns")
        _bind_scroll(self._profile_list)

        log_outer = ttk.LabelFrame(
            body, text="Status / Log", padding=(4, 2),
            style=f"{self._style_prefix}.TLabelframe"
        )
        log_outer.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(6, 0))
        log_outer.columnconfigure(0, weight=1)
        log_outer.rowconfigure(0, weight=1)
        self._log_outer = log_outer
        mono = ("Consolas", 9) if os.name == "nt" else ("monospace", 9)
        self._txt_log = tk.Text(
            log_outer, wrap="word", height=8, state="disabled", font=mono,
            relief="solid", borderwidth=1
        )
        scrollbar = ttk.Scrollbar(log_outer, orient="vertical", command=self._txt_log.yview)
        self._txt_log.configure(yscrollcommand=scrollbar.set)
        self._txt_log.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        _bind_scroll(self._txt_log)

        self._context_menu = tk.Menu(self.frame, tearoff=0)
        self.frame.bind_all("<Escape>", self._dismiss_context_menu, add="+")

    def _build_status_bar(self):
        bar = ttk.Frame(self.frame, padding=(4, 2), style=f"{self._style_prefix}.TFrame")
        bar.grid(row=2, column=0, sticky="ew")
        bar.columnconfigure(0, weight=1)
        self._status_bar = bar
        ttk.Label(
            bar, textvariable=self._var_status, anchor="w",
            style=f"{self._style_prefix}.Status.TLabel"
        ).grid(row=0, column=0, sticky="ew")

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
            self._style.configure(f"{self._style_prefix}.TFrame", background=tokens["content_bg"])
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
                f"{self._style_prefix}.Status.TLabel",
                background=tokens["content_bg"],
                foreground=tokens["text_muted"],
            )
        except Exception:
            pass

        try:
            self.frame.configure(style=f"{self._style_prefix}.TFrame")
        except Exception:
            pass

        for widget in (
            getattr(self, "_top_bar", None),
            getattr(self, "_body_frame", None),
            getattr(self, "_status_bar", None),
            getattr(self, "_inspector", None),
        ):
            if widget is None:
                continue
            try:
                widget.configure(style=f"{self._style_prefix}.TFrame")
            except Exception:
                pass

        if self._map_canvas is not None:
            try:
                self._map_canvas.configure(
                    background=tokens["sidebar_bg"],
                    highlightbackground=tokens["border"],
                    highlightcolor=tokens["accent"],
                )
            except Exception:
                pass
        for widget in (self._profile_list,):
            if widget is None:
                continue
            try:
                widget.configure(
                    background=tokens["panel_bg"],
                    foreground=tokens["text_main"],
                    selectbackground=tokens["accent"],
                    selectforeground=tokens["text_on_accent"],
                    highlightbackground=tokens["border"],
                )
            except Exception:
                pass
        if self._txt_log is not None:
            try:
                self._txt_log.configure(
                    background=tokens["panel_bg"],
                    foreground=tokens["text_main"],
                    insertbackground=tokens["text_main"],
                    selectbackground=tokens["accent"],
                    selectforeground=tokens["text_on_accent"],
                    highlightbackground=tokens["border"],
                )
            except Exception:
                pass
        if self._context_menu is not None:
            try:
                self._context_menu.configure(
                    background=tokens["panel_bg"],
                    foreground=tokens["text_main"],
                    activebackground=tokens["accent"],
                    activeforeground=tokens["text_on_accent"],
                    borderwidth=1,
                )
            except Exception:
                pass
        self._render_map()

    def _load_config(self):
        default = {"friendly_names": {}, "label_modes": {}, "profiles": {}, "ui": {"zoom_label": "100%"}}
        try:
            with open(self._config_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, dict):
                default.update(payload)
        except Exception:
            pass
        default["friendly_names"] = dict(default.get("friendly_names") or {})
        default["label_modes"] = dict(default.get("label_modes") or {})
        default["profiles"] = dict(default.get("profiles") or {})
        default["ui"] = dict(default.get("ui") or {})
        return default

    def _save_config(self):
        self._config.setdefault("ui", {})["zoom_label"] = self._var_zoom.get().strip() or "100%"
        try:
            with open(self._config_path, "w", encoding="utf-8") as handle:
                json.dump(self._config, handle, indent=2, sort_keys=True)
        except Exception as ex:
            self._log(f"Failed to save config: {ex}")

    def _now(self):
        return datetime.datetime.now().strftime("%H:%M:%S")

    def _set_status(self, msg):
        self._var_status.set(f"[{self._now()}] {msg}")

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

    def _refresh_from_backend(self, initial=False):
        result = self._backend.read_layout()
        self._backend_capabilities = result.get("capabilities") or self._backend.capabilities()
        self._backend_label = result.get("backend_label") or self._backend.backend_label
        capability_summary = "live apply" if self._backend_capabilities.get("can_apply_layout") else "local-only"
        self._var_backend.set(f"{self._backend_label} | {capability_summary}")

        if not result.get("ok"):
            if initial:
                self._monitors = self._seed_fallback_monitors()
                self._live_monitors = copy.deepcopy(self._monitors)
                self._apply_local_overrides(self._monitors)
                self._select_monitor(self._monitors[0]["connector"] if self._monitors else "")
                self._refresh_profile_list()
                self._render_map()
                self._set_status("Live backend unavailable. Local monitor manager is still usable.")
                self._log(result.get("error") or "Failed to read live monitor layout.")
                return
            self._set_status("Failed to refresh live layout.")
            self._log(result.get("error") or "Live read failed.")
            return

        self._live_monitors = [_clone_monitor(item) for item in result.get("monitors") or []]
        self._monitors = [_clone_monitor(item) for item in self._live_monitors]
        self._apply_local_overrides(self._monitors)
        if not self._selected_connector and self._monitors:
            self._selected_connector = self._monitors[0]["connector"]
        elif self._selected_connector and not self._monitor_by_connector(self._selected_connector):
            self._selected_connector = self._monitors[0]["connector"] if self._monitors else ""
        self._refresh_profile_list()
        self._select_monitor(self._selected_connector)
        self._render_map()
        if not initial:
            self._set_status("Refreshed live display layout.")
        self._log(f"Loaded {len(self._monitors)} displays from {self._backend_label}.")

    def _seed_fallback_monitors(self):
        names = list(self._config.get("friendly_names", {}).keys()) or ["Display-1"]
        out = []
        x = 0
        for index, name in enumerate(names, start=1):
            out.append(
                {
                    "connector": name,
                    "backend_name": name,
                    "backend_output_id": str(index),
                    "connected": True,
                    "enabled": True,
                    "primary": index == 1,
                    "priority": index,
                    "x": x,
                    "y": 0,
                    "rotation": "none",
                    "scale": 1.0,
                    "mode_id": "1920x1080@60",
                    "mode_name": "1920x1080@60",
                    "width": 1920,
                    "height": 1080,
                    "modes": [{"id": "1920x1080@60", "name": "1920x1080@60", "width": 1920, "height": 1080, "refresh": 60.0}],
                    "label_mode": "friendly",
                    "friendly_name": self._config.get("friendly_names", {}).get(name, name),
                }
            )
            x += 1920
        return out

    def _apply_local_overrides(self, monitors):
        names = self._config.get("friendly_names", {})
        label_modes = self._config.get("label_modes", {})
        for monitor in monitors:
            connector = monitor["connector"]
            monitor["friendly_name"] = names.get(connector, monitor.get("friendly_name") or connector)
            mode = str(label_modes.get(connector, monitor.get("label_mode", "friendly"))).strip().lower()
            monitor["label_mode"] = mode if mode in {"friendly", "technical"} else "friendly"

    def _monitor_by_connector(self, connector):
        for monitor in self._monitors:
            if monitor.get("connector") == connector:
                return monitor
        return None

    def _live_monitor_by_connector(self, connector):
        for monitor in self._live_monitors:
            if monitor.get("connector") == connector:
                return monitor
        return None

    def _selected_monitor(self):
        return self._monitor_by_connector(self._selected_connector)

    def _select_monitor(self, connector):
        self._selected_connector = connector if self._monitor_by_connector(connector) else ""
        self._sync_inspector()
        self._render_map()

    def _sync_inspector(self):
        monitor = self._selected_monitor()
        if monitor is None:
            self._var_selection.set("No display selected.")
            self._var_display_name.set("")
            self._var_label_mode.set("friendly")
            self._var_enabled.set(True)
            self._var_primary.set(False)
            self._var_rotation.set("none")
            self._var_mode.set("")
            self._var_scale.set("1.0")
            self._var_position.set("")
            try:
                self._mode_combo.configure(values=())
            except Exception:
                pass
            return

        display_name = monitor.get("friendly_name") or monitor["connector"]
        title = display_name if monitor.get("label_mode") == "friendly" else monitor["connector"]
        flags = []
        if monitor.get("primary"):
            flags.append("primary")
        if not monitor.get("enabled"):
            flags.append("disabled")
        if not monitor.get("connected"):
            flags.append("disconnected")
        suffix = f" [{' | '.join(flags)}]" if flags else ""
        self._var_selection.set(f"{title}{suffix}\nBackend: {monitor['connector']}")
        self._var_display_name.set(display_name)
        self._var_label_mode.set(monitor.get("label_mode", "friendly"))
        self._var_enabled.set(bool(monitor.get("enabled")))
        self._var_primary.set(bool(monitor.get("primary")))
        self._var_rotation.set(monitor.get("rotation", "none"))
        self._var_mode.set(monitor.get("mode_name", ""))
        self._var_scale.set(_fmt_scale(monitor.get("scale", 1.0)))
        self._var_position.set(f"{int(monitor.get('x', 0))}, {int(monitor.get('y', 0))}")
        modes = [m["name"] for m in monitor.get("modes", [])]
        try:
            self._mode_combo.configure(values=modes)
        except Exception:
            pass

    def _on_zoom_change(self, _value=None):
        label = self._var_zoom.get().strip()
        zoom = _ZOOM_FACTORS.get(label)
        if zoom is None:
            return
        self._display_zoom = zoom
        self._save_config()
        self._render_map()
        self._set_status(f"Map zoom set to {label}.")

    def _refresh_profile_list(self):
        if self._profile_list is None:
            return
        self._profile_list.delete(0, "end")
        for name in sorted(self._config.get("profiles", {})):
            self._profile_list.insert("end", name)

    def _selected_profile_name(self):
        if self._profile_list is None:
            return ""
        sel = self._profile_list.curselection()
        if not sel:
            return ""
        try:
            return str(self._profile_list.get(sel[0]))
        except Exception:
            return ""

    def _save_profile_prompt(self):
        initial = self._selected_profile_name() or ""
        value = simpledialog.askstring(
            "Save Profile",
            "Profile name:",
            initialvalue=initial,
            parent=self.frame,
        )
        if value is None:
            return
        name = value.strip()
        if not name:
            self._set_status("Profile name cannot be blank.")
            return
        self._save_profile(name)

    def _save_profile(self, name):
        payload = {
            "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "backend_id": self._backend.backend_id,
            "monitors": [],
        }
        for monitor in self._monitors:
            payload["monitors"].append(
                {
                    "connector": monitor["connector"],
                    "friendly_name": monitor.get("friendly_name", monitor["connector"]),
                    "label_mode": monitor.get("label_mode", "friendly"),
                    "enabled": bool(monitor.get("enabled")),
                    "primary": bool(monitor.get("primary")),
                    "x": int(monitor.get("x", 0)),
                    "y": int(monitor.get("y", 0)),
                    "rotation": monitor.get("rotation", "none"),
                    "mode_name": monitor.get("mode_name", ""),
                    "scale": float(monitor.get("scale", 1.0)),
                }
            )
        self._config.setdefault("profiles", {})[name] = payload
        self._save_config()
        self._refresh_profile_list()
        self._set_status(f"Saved profile {name}.")
        self._log(f"Saved profile {name} with {len(payload['monitors'])} displays.")

    def _load_selected_profile(self):
        name = self._selected_profile_name()
        if not name:
            self._set_status("Select a profile first.")
            return
        profile = (self._config.get("profiles") or {}).get(name)
        if not isinstance(profile, dict):
            self._set_status("Selected profile is invalid.")
            return
        staged = {_clone_monitor(m)["connector"]: _clone_monitor(m) for m in self._monitors}
        missing = []
        for saved in profile.get("monitors", []):
            connector = str(saved.get("connector") or "").strip()
            current = staged.get(connector)
            if current is None:
                missing.append(connector)
                continue
            current["friendly_name"] = str(saved.get("friendly_name") or current["connector"]).strip() or current["connector"]
            current["label_mode"] = str(saved.get("label_mode") or current.get("label_mode", "friendly")).strip().lower()
            current["enabled"] = bool(saved.get("enabled"))
            current["primary"] = bool(saved.get("primary"))
            current["x"] = int(saved.get("x", current.get("x", 0)))
            current["y"] = int(saved.get("y", current.get("y", 0)))
            current["rotation"] = str(saved.get("rotation") or current.get("rotation", "none")).strip().lower()
            current["mode_name"] = self._best_mode_name_for_monitor(current, str(saved.get("mode_name") or ""))
            current["scale"] = _parse_scale(saved.get("scale", current.get("scale", 1.0)), current.get("scale", 1.0))

        self._monitors = list(staged.values())
        self._normalize_primary_selection()
        self._persist_local_names()
        self._select_monitor(self._selected_connector or (self._monitors[0]["connector"] if self._monitors else ""))
        self._render_map()
        self._set_status(f"Loaded profile {name} into staged layout.")
        if missing:
            self._log(f"Profile {name} referenced missing connectors: {', '.join(missing)}")

    def _delete_selected_profile(self):
        name = self._selected_profile_name()
        if not name:
            self._set_status("Select a profile first.")
            return
        if not messagebox.askyesno("Delete Profile", f"Delete profile '{name}'?", parent=self.frame):
            return
        self._config.get("profiles", {}).pop(name, None)
        self._save_config()
        self._refresh_profile_list()
        self._set_status(f"Deleted profile {name}.")

    def _persist_local_names(self):
        names = self._config.setdefault("friendly_names", {})
        label_modes = self._config.setdefault("label_modes", {})
        for monitor in self._monitors:
            names[monitor["connector"]] = monitor.get("friendly_name", monitor["connector"])
            label_modes[monitor["connector"]] = monitor.get("label_mode", "friendly")
        self._save_config()

    def _revert_to_live(self):
        self._monitors = [_clone_monitor(item) for item in self._live_monitors]
        self._apply_local_overrides(self._monitors)
        self._normalize_primary_selection()
        self._select_monitor(self._selected_connector or (self._monitors[0]["connector"] if self._monitors else ""))
        self._render_map()
        self._set_status("Reverted staged layout to the last live read.")

    def _apply_live_layout(self):
        if not self._backend_capabilities.get("can_apply_layout"):
            self._set_status("Live apply is unavailable for the current backend.")
            return
        self._normalize_primary_selection()
        result = self._backend.apply_layout(self._monitors)
        if result.get("ok"):
            self._persist_local_names()
            self._set_status("Applied staged layout to the live session.")
            self._log("Applied live monitor layout.")
            self._refresh_from_backend()
            return
        self._set_status("Failed to apply live layout.")
        if result.get("stderr"):
            self._log(result["stderr"].strip())
        if result.get("error"):
            self._log(result["error"])

    def _normalize_primary_selection(self):
        enabled = [m for m in self._monitors if m.get("enabled")]
        if not enabled:
            for monitor in self._monitors:
                monitor["primary"] = False
            return
        primaries = [m for m in enabled if m.get("primary")]
        if not primaries:
            enabled[0]["primary"] = True
            primaries = [enabled[0]]
        primary_connector = primaries[0]["connector"]
        for monitor in self._monitors:
            monitor["primary"] = monitor.get("enabled") and monitor["connector"] == primary_connector

    def _stage_inspector_changes(self):
        monitor = self._selected_monitor()
        if monitor is None:
            self._set_status("Select a display first.")
            return
        name = self._var_display_name.get().strip() or monitor["connector"]
        label_mode = str(self._var_label_mode.get()).strip().lower()
        if label_mode not in {"friendly", "technical"}:
            label_mode = "friendly"
        rotation = str(self._var_rotation.get()).strip().lower()
        if rotation not in _ROTATION_ORDER:
            rotation = "none"
        enabled = bool(self._var_enabled.get())
        primary = bool(self._var_primary.get()) and enabled
        mode_name = self._best_mode_name_for_monitor(monitor, self._var_mode.get())
        scale = _parse_scale(self._var_scale.get(), monitor.get("scale", 1.0))

        monitor["friendly_name"] = name
        monitor["label_mode"] = label_mode
        monitor["rotation"] = rotation
        monitor["enabled"] = enabled
        monitor["primary"] = primary
        monitor["mode_name"] = mode_name
        monitor["scale"] = scale

        if mode_name:
            selected_mode = next((m for m in monitor.get("modes", []) if m["name"] == mode_name), None)
            if selected_mode is not None:
                monitor["mode_id"] = selected_mode["id"]
                monitor["width"] = int(selected_mode.get("width") or monitor.get("width", 0))
                monitor["height"] = int(selected_mode.get("height") or monitor.get("height", 0))

        if primary:
            for other in self._monitors:
                if other["connector"] != monitor["connector"]:
                    other["primary"] = False

        self._persist_local_names()
        self._normalize_primary_selection()
        self._sync_inspector()
        self._render_map()
        self._set_status(f"Staged changes for {monitor['connector']}.")

    def _rename_selected_display(self):
        monitor = self._selected_monitor()
        if monitor is None:
            self._set_status("Select a display first.")
            return
        value = simpledialog.askstring(
            "Rename Display",
            "Display nickname:",
            initialvalue=monitor.get("friendly_name", monitor["connector"]),
            parent=self.frame,
        )
        if value is None:
            return
        cleaned = value.strip()
        if not cleaned:
            self._set_status("Display nickname cannot be blank.")
            return
        monitor["friendly_name"] = cleaned
        self._var_display_name.set(cleaned)
        self._persist_local_names()
        self._sync_inspector()
        self._render_map()
        self._set_status(f"Renamed {monitor['connector']} to {cleaned}.")

    def _best_mode_name_for_monitor(self, monitor, requested):
        requested = str(requested or "").strip()
        modes = [m["name"] for m in monitor.get("modes", [])]
        if requested in modes:
            return requested
        if requested:
            requested_base = requested.split("@", 1)[0]
            for name in modes:
                if name.split("@", 1)[0] == requested_base:
                    return name
        return monitor.get("mode_name", "") or (modes[0] if modes else "")

    def _monitor_display_title(self, monitor):
        if monitor.get("label_mode") == "technical":
            return monitor["connector"]
        return monitor.get("friendly_name") or monitor["connector"]

    def _monitor_secondary_text(self, monitor):
        if monitor.get("label_mode") == "technical":
            return monitor.get("friendly_name") or ""
        mode = monitor.get("mode_name", "")
        scale = _fmt_scale(monitor.get("scale", 1.0))
        bits = []
        if mode:
            bits.append(mode)
        bits.append(f"{scale}x")
        return " | ".join(bits)

    def _render_map(self):
        if self._map_canvas is None:
            return
        self._map_canvas.delete("all")
        self._box_items = {}
        width = self._world_layout_width()
        height = self._world_layout_height()
        tokens = self._theme_tokens
        self._map_canvas.create_rectangle(0, 0, width, height, fill=tokens["sidebar_bg"], outline=tokens["border"])

        for monitor in self._monitors:
            self._draw_monitor_box(monitor)
        self._map_canvas.configure(scrollregion=(0, 0, width, height))

    def _draw_monitor_box(self, monitor):
        world_x1 = int(round((int(monitor.get("x", 0)) + _LAYOUT_PADDING) * self._display_zoom))
        world_y1 = int(round((int(monitor.get("y", 0)) + _LAYOUT_PADDING) * self._display_zoom))
        box_width, box_height = self._monitor_box_dimensions(monitor)
        world_x2 = world_x1 + box_width
        world_y2 = world_y1 + box_height
        selected = monitor["connector"] == self._selected_connector

        fill = self._theme_tokens["panel_bg"]
        if not monitor.get("enabled"):
            fill = "#503030"
        elif monitor.get("primary"):
            fill = "#24482d"
        outline = self._theme_tokens["accent"] if selected else self._theme_tokens["border"]
        tag = f"monitor:{monitor['connector']}"
        rect_id = self._map_canvas.create_rectangle(
            world_x1, world_y1, world_x2, world_y2,
            fill=fill, outline=outline, width=_BOX_BORDER if selected else 1,
            tags=(tag, "monitorbox"),
        )

        title = self._monitor_display_title(monitor)
        secondary = self._monitor_secondary_text(monitor)
        status_bits = []
        if monitor.get("primary"):
            status_bits.append("primary")
        if not monitor.get("enabled"):
            status_bits.append("disabled")
        if not monitor.get("connected"):
            status_bits.append("disconnected")
        status = f" [{' | '.join(status_bits)}]" if status_bits else ""
        text_lines = [title]
        if secondary:
            text_lines.append(secondary)
        if status:
            text_lines.append(status.strip())
        font_size = max(5, min(16, int(round(min(box_width, box_height) / 8))))
        text_id = self._map_canvas.create_text(
            world_x1 + box_width / 2,
            world_y1 + box_height / 2,
            text="\n".join(text_lines),
            width=max(box_width - int(round(20 * self._display_zoom)), 70),
            justify="center",
            fill=self._theme_tokens["text_main"],
            font=("TkDefaultFont", font_size, "bold" if selected else "normal"),
            tags=(tag, "monitorbox"),
        )
        self._box_items[monitor["connector"]] = (rect_id, text_id)

    def _monitor_box_dimensions(self, monitor):
        width = int(monitor.get("width") or 1920)
        height = int(monitor.get("height") or 1080)
        if not width or not height:
            width, height = 1920, 1080
        scaled_width = max(150, min(380, int(round(width / 12))))
        scaled_height = max(84, min(240, int(round(height / 12))))
        return (
            int(round(scaled_width * self._display_zoom)),
            int(round(scaled_height * self._display_zoom)),
        )

    def _world_layout_width(self):
        viewport = max(self._map_canvas.winfo_width(), 700) if self._map_canvas else 700
        content = 0
        for monitor in self._monitors:
            box_width, _ = self._monitor_box_dimensions(monitor)
            content = max(content, int(round((int(monitor.get("x", 0)) + _LAYOUT_PADDING) * self._display_zoom)) + box_width + _LAYOUT_PADDING)
        return max(viewport, content + _LAYOUT_PADDING)

    def _world_layout_height(self):
        viewport = max(self._map_canvas.winfo_height(), 420) if self._map_canvas else 420
        content = 0
        for monitor in self._monitors:
            _, box_height = self._monitor_box_dimensions(monitor)
            content = max(content, int(round((int(monitor.get("y", 0)) + _LAYOUT_PADDING) * self._display_zoom)) + box_height + _LAYOUT_PADDING)
        return max(viewport, content + _LAYOUT_PADDING)

    def _event_to_world(self, event):
        canvas_x = self._map_canvas.canvasx(event.x)
        canvas_y = self._map_canvas.canvasy(event.y)
        return canvas_x / self._display_zoom - _LAYOUT_PADDING, canvas_y / self._display_zoom - _LAYOUT_PADDING

    def _on_canvas_configure(self, _event=None):
        self._render_map()

    def _on_map_click(self, event):
        item = self._map_canvas.find_withtag("current")
        if not item:
            self._drag_connector = ""
            self._select_monitor("")
            return
        connector = self._connector_from_canvas_item(item[0])
        monitor = self._monitor_by_connector(connector)
        if monitor is None:
            return
        world_x, world_y = self._event_to_world(event)
        self._drag_connector = connector
        self._drag_offset_x = world_x - int(monitor.get("x", 0))
        self._drag_offset_y = world_y - int(monitor.get("y", 0))
        self._select_monitor(connector)

    def _on_map_drag(self, event):
        if not self._drag_connector:
            return
        monitor = self._monitor_by_connector(self._drag_connector)
        if monitor is None:
            return
        world_x, world_y = self._event_to_world(event)
        monitor["x"] = self._soft_snap_coordinate(int(round(world_x - self._drag_offset_x)))
        monitor["y"] = self._soft_snap_coordinate(int(round(world_y - self._drag_offset_y)))
        self._ensure_monitor_within_world(monitor)
        self._sync_inspector()
        self._render_map()

    def _on_map_release(self, _event=None):
        if not self._drag_connector:
            return
        monitor = self._monitor_by_connector(self._drag_connector)
        if monitor is not None:
            self._set_status(f"Moved {monitor['connector']} to {int(monitor['x'])}, {int(monitor['y'])}.")
        self._drag_connector = ""

    def _on_map_right_click(self, event):
        item = self._map_canvas.find_withtag("current")
        if not item:
            return
        connector = self._connector_from_canvas_item(item[0])
        if not connector:
            return
        self._select_monitor(connector)
        self._populate_context_menu()
        interaction_support.show_popup_menu(
            self.frame.winfo_toplevel(),
            self._context_menu,
            event.x_root,
            event.y_root,
        )

    def _dismiss_context_menu(self, _event=None):
        if self._context_menu is None:
            return
        try:
            self._context_menu.unpost()
            self._context_menu.grab_release()
        except Exception:
            pass

    def _on_map_mousewheel(self, event):
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
            self._step_zoom(delta)
            return "break"
        if shift:
            self._map_canvas.xview_scroll(-delta, "units")
            return "break"
        self._map_canvas.yview_scroll(-delta, "units")
        return "break"

    def _step_zoom(self, step):
        labels = list(_ZOOM_FACTORS.keys())
        current = self._var_zoom.get().strip()
        if current not in labels:
            current = "100%"
        idx = labels.index(current)
        idx = min(max(idx + step, 0), len(labels) - 1)
        self._var_zoom.set(labels[idx])
        self._on_zoom_change()

    def _populate_context_menu(self):
        self._context_menu.delete(0, "end")
        monitor = self._selected_monitor()
        if monitor is None:
            return
        self._context_menu.add_command(label="Rename Display...", command=self._rename_selected_display)
        self._context_menu.add_command(
            label="Label: Friendly" if monitor.get("label_mode") != "friendly" else "Label: Technical",
            command=self._toggle_selected_label_mode,
        )
        self._context_menu.add_separator()
        self._context_menu.add_command(
            label="Enable" if not monitor.get("enabled") else "Disable",
            command=self._toggle_selected_enabled,
        )
        self._context_menu.add_command(label="Set Primary", command=self._set_selected_primary)

        rotation_menu = tk.Menu(self._context_menu, tearoff=0)
        for rotation in _ROTATION_ORDER:
            rotation_menu.add_command(
                label=_rotation_label(rotation),
                command=lambda value=rotation: self._set_selected_rotation(value),
            )
        self._context_menu.add_cascade(label="Rotation", menu=rotation_menu)

        mode_menu = tk.Menu(self._context_menu, tearoff=0)
        for mode in monitor.get("modes", [])[:20]:
            mode_menu.add_command(
                label=mode["name"],
                command=lambda value=mode["name"]: self._set_selected_mode(value),
            )
        if monitor.get("modes"):
            self._context_menu.add_cascade(label="Mode", menu=mode_menu)
        self._context_menu.add_separator()
        self._context_menu.add_command(label="Stage Inspector Changes", command=self._stage_inspector_changes)

    def _toggle_selected_label_mode(self):
        monitor = self._selected_monitor()
        if monitor is None:
            return
        monitor["label_mode"] = "technical" if monitor.get("label_mode") == "friendly" else "friendly"
        self._persist_local_names()
        self._sync_inspector()
        self._render_map()

    def _toggle_selected_enabled(self):
        monitor = self._selected_monitor()
        if monitor is None:
            return
        monitor["enabled"] = not monitor.get("enabled")
        if not monitor["enabled"]:
            monitor["primary"] = False
        self._normalize_primary_selection()
        self._sync_inspector()
        self._render_map()

    def _set_selected_primary(self):
        monitor = self._selected_monitor()
        if monitor is None:
            return
        if not monitor.get("enabled"):
            monitor["enabled"] = True
        for other in self._monitors:
            other["primary"] = other["connector"] == monitor["connector"]
        self._sync_inspector()
        self._render_map()

    def _set_selected_rotation(self, rotation):
        monitor = self._selected_monitor()
        if monitor is None or rotation not in _ROTATION_ORDER:
            return
        monitor["rotation"] = rotation
        self._sync_inspector()
        self._render_map()

    def _set_selected_mode(self, mode_name):
        monitor = self._selected_monitor()
        if monitor is None:
            return
        mode_name = self._best_mode_name_for_monitor(monitor, mode_name)
        monitor["mode_name"] = mode_name
        selected_mode = next((m for m in monitor.get("modes", []) if m["name"] == mode_name), None)
        if selected_mode is not None:
            monitor["mode_id"] = selected_mode["id"]
            monitor["width"] = int(selected_mode.get("width") or monitor.get("width", 0))
            monitor["height"] = int(selected_mode.get("height") or monitor.get("height", 0))
        self._sync_inspector()
        self._render_map()

    def _connector_from_canvas_item(self, item_id):
        for tag in self._map_canvas.gettags(item_id):
            if tag.startswith("monitor:"):
                return tag.split(":", 1)[1]
        return ""

    def _soft_snap_coordinate(self, value):
        nearest = round(value / _GRID_STEP) * _GRID_STEP
        if abs(value - nearest) <= _SOFT_SNAP:
            return nearest
        return value

    def _ensure_monitor_within_world(self, monitor):
        max_x = 64000 - int(monitor.get("width", 1920))
        max_y = 64000 - int(monitor.get("height", 1080))
        monitor["x"] = min(max(int(monitor.get("x", 0)), 0), max_x)
        monitor["y"] = min(max(int(monitor.get("y", 0)), 0), max_y)

