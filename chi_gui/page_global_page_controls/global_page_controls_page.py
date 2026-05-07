"""
Global Page Controls

Small control surface for Guichi-wide interaction defaults.
"""

import tkinter as tk
from tkinter import ttk


_DEFAULT_PAGE_THEME = {
    "content_bg": "#1e1e1e",
    "panel_bg": "#2e2e2e",
    "text_main": "#c0c0c0",
    "text_muted": "#909090",
    "button_bg": "#333333",
    "button_hover": "#444444",
    "text_active": "#d0d0d0",
    "button_disabled": "#555555",
    "border": "#444444",
}

CONTROL_ROWS = [
    (
        "wheel_scroll_enabled",
        "Wheel scrolling",
        "Enable Linux-safe and cross-platform mouse-wheel scrolling on helper-managed widgets.",
    ),
    (
        "ctrl_a_enabled",
        "Ctrl-A select all",
        "Allow global select-all in single-line entries and editable text areas.",
    ),
    (
        "ctrl_c_enabled",
        "Ctrl-C copy selection",
        "Allow global copy of selected text in supported text widgets.",
    ),
    (
        "escape_dismiss_enabled",
        "Escape dismiss",
        "Allow Escape to dismiss helper-managed popup menus and transient surfaces.",
    ),
]


class PageGlobalPageControls:
    PAGE_NAME = "global_page_controls"

    def __init__(self, parent, app=None, page_key="", page_folder="", *args, **kwargs):
        app = kwargs.pop("controller", app)
        page_key = kwargs.pop("page_context", page_key)
        page_folder = kwargs.pop("page_folder", page_folder)

        self.parent = parent
        self.app = app
        self.page_key = page_key
        self.page_folder = page_folder
        self.guichi_shell = None
        self.guichi_page_theme = None
        self._page_theme_tokens = dict(_DEFAULT_PAGE_THEME)
        self._style_prefix = f"GlobalPageControls.{id(self)}"
        self._status_var = tk.StringVar(value="Ready.")
        self._control_vars = {}

        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)

    def build(self, parent=None):
        container = parent or self.parent
        if container is not None and self.frame.master is not container:
            self.frame.destroy()
            self.parent = container
            self.frame = ttk.Frame(container)
            self.frame.columnconfigure(0, weight=1)
        for child in self.frame.winfo_children():
            child.destroy()
        self._build_ui()
        self._apply_page_theme()
        try:
            self.frame.pack(fill="both", expand=True)
        except Exception:
            self.frame.grid(row=0, column=0, sticky="nsew")
        self._load_from_shell()
        return self.frame

    create_widgets = build
    mount = build
    render = build

    def set_guichi_page_theme(self, context):
        self.guichi_page_theme = context
        tokens = dict(_DEFAULT_PAGE_THEME)
        tokens.update((context or {}).get("tokens") or {})
        self._page_theme_tokens = tokens
        self._apply_page_theme()

    def _build_ui(self):
        header = ttk.Frame(self.frame, padding=(10, 8, 10, 4))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        self._header = header

        self._title = ttk.Label(
            header,
            text="Global Page Controls",
            style=f"{self._style_prefix}.Header.TLabel",
        )
        self._title.grid(row=0, column=0, sticky="w")

        self._subtitle = ttk.Label(
            header,
            text="Global-only interaction defaults for Guichi. Changes apply live and save immediately.",
            style=f"{self._style_prefix}.Muted.TLabel",
        )
        self._subtitle.grid(row=1, column=0, sticky="w", pady=(2, 0))

        body = ttk.LabelFrame(
            self.frame,
            text="Interaction Defaults",
            padding=(10, 10),
            style=f"{self._style_prefix}.TLabelframe",
        )
        body.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        body.columnconfigure(1, weight=1)
        self._body = body

        row = 0
        for key, label, description in CONTROL_ROWS:
            var = tk.BooleanVar(value=False)
            self._control_vars[key] = var
            chk = ttk.Checkbutton(
                body,
                text=label,
                variable=var,
                command=lambda k=key: self._on_toggle(k),
                style=f"{self._style_prefix}.TCheckbutton",
            )
            chk.grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=(0, 2))
            desc = ttk.Label(
                body,
                text=description,
                style=f"{self._style_prefix}.Muted.TLabel",
                wraplength=620,
                justify="left",
            )
            desc.grid(row=row, column=1, sticky="w", pady=(0, 12))
            row += 1

        status = ttk.Frame(self.frame, padding=(10, 0, 10, 10))
        status.grid(row=2, column=0, sticky="ew")
        status.columnconfigure(0, weight=1)
        self._status_row = status
        self._status = ttk.Label(
            status,
            textvariable=self._status_var,
            style=f"{self._style_prefix}.Muted.TLabel",
        )
        self._status.grid(row=0, column=0, sticky="w")

    def _load_from_shell(self):
        shell = getattr(self, "guichi_shell", None)
        if shell is None:
            self._status_var.set("Shell context unavailable.")
            return
        settings = shell.get_interaction_settings()
        for key, var in self._control_vars.items():
            var.set(bool(settings.get(key, True)))
        self._status_var.set("Loaded current global interaction settings.")

    def _on_toggle(self, key):
        shell = getattr(self, "guichi_shell", None)
        if shell is None:
            self._status_var.set("Shell context unavailable.")
            return
        value = bool(self._control_vars[key].get())
        ok = shell.set_interaction_setting(key, value)
        label = next((row[1] for row in CONTROL_ROWS if row[0] == key), key)
        if ok:
            self._status_var.set(f"{label} {'enabled' if value else 'disabled'} globally.")
        else:
            self._status_var.set(f"Failed to update {label}.")

    def _apply_page_theme(self):
        tokens = self._page_theme_tokens
        try:
            style = ttk.Style(self.frame)
            style.configure(f"{self._style_prefix}.TFrame", background=tokens["content_bg"])
            style.configure(f"{self._style_prefix}.TLabelframe", background=tokens["panel_bg"], bordercolor=tokens["border"])
            style.configure(f"{self._style_prefix}.TLabelframe.Label", background=tokens["panel_bg"], foreground=tokens["text_main"])
            style.configure(f"{self._style_prefix}.TLabel", background=tokens["content_bg"], foreground=tokens["text_main"])
            style.configure(f"{self._style_prefix}.Muted.TLabel", background=tokens["content_bg"], foreground=tokens["text_muted"])
            style.configure(f"{self._style_prefix}.Header.TLabel", background=tokens["content_bg"], foreground=tokens["text_main"], font=("TkDefaultFont", 14, "bold"))
            style.configure(f"{self._style_prefix}.TCheckbutton", background=tokens["panel_bg"], foreground=tokens["text_main"])
            style.map(
                f"{self._style_prefix}.TCheckbutton",
                foreground=[("active", tokens["text_active"]), ("disabled", tokens["button_disabled"])],
                background=[("active", tokens["panel_bg"])],
            )
        except Exception:
            pass
        for widget in (self.frame, self._header, self._status_row):
            if widget is None:
                continue
            try:
                widget.configure(style=f"{self._style_prefix}.TFrame")
            except Exception:
                pass
        if hasattr(self, "_body"):
            try:
                self._body.configure(style=f"{self._style_prefix}.TLabelframe")
            except Exception:
                pass
