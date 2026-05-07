"""
Theme Organizer

First rendition of a visual Guichi theme editor.
"""

import copy
import json
import os
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, messagebox, simpledialog, ttk

from gui_files import interaction_support


TOKEN_GROUPS = [
    ("Surfaces", ["app_bg", "topbar_bg", "sidebar_bg", "content_bg", "panel_bg"]),
    ("Text", ["text_main", "text_muted", "text_active", "text_on_accent"]),
    ("Buttons", ["button_bg", "button_hover", "button_active", "button_disabled"]),
    ("Structure", ["accent", "accent_hover", "border", "divider", "focus_ring"]),
    ("Sizing", ["sidebar_width", "topbar_height", "button_height", "pad_x", "pad_y", "font_size_main", "font_size_small"]),
]

COLOR_TOKENS = {
    "app_bg", "topbar_bg", "sidebar_bg", "content_bg", "panel_bg",
    "text_main", "text_muted", "text_active", "text_on_accent",
    "button_bg", "button_hover", "button_active", "button_disabled",
    "accent", "accent_hover", "border", "divider", "focus_ring",
}

TOKEN_HELP = {
    "app_bg": "Outer app background behind the whole shell.",
    "topbar_bg": "Toolbar/menu row background.",
    "sidebar_bg": "Navigation/sidebar background surfaces.",
    "content_bg": "Main content area behind pages and cards.",
    "panel_bg": "Cards, grouped panels, and boxed sections.",
    "text_main": "Primary readable text across the UI.",
    "text_muted": "Secondary text like hints, headers, and status.",
    "text_active": "Text used in active or emphasized states.",
    "text_on_accent": "Text that sits on top of accent-colored surfaces.",
    "button_bg": "Default button fill.",
    "button_hover": "Button hover background.",
    "button_active": "Button-active emphasis color.",
    "button_disabled": "Muted button text/state color.",
    "accent": "Selected items, active highlights, strong calls to action.",
    "accent_hover": "Accent hover/stronger accent variant.",
    "border": "Frame and card outlines.",
    "divider": "Subtle separators between sections.",
    "focus_ring": "Focus or glow color for targeted elements.",
    "sidebar_width": "Navigation width target.",
    "topbar_height": "Toolbar/top-row height.",
    "button_height": "Button height target.",
    "pad_x": "Horizontal spacing rhythm.",
    "pad_y": "Vertical spacing rhythm.",
    "font_size_main": "Primary text size baseline.",
    "font_size_small": "Smaller helper text baseline.",
}

TOKEN_TARGETS = {
    "app_bg": ["preview_host"],
    "topbar_bg": ["top", "top_shell", "top_view", "top_display"],
    "sidebar_bg": ["sidebar", "nav_head"],
    "content_bg": ["body", "content"],
    "panel_bg": ["card", "button_row", "status", "sidebar_item", "title", "subtitle", "text", "status_label"],
    "text_main": ["top_shell", "top_view", "top_display", "sidebar_item", "title", "text", "sample_btn"],
    "text_muted": ["nav_head", "subtitle", "status_label"],
    "text_active": ["top_shell", "top_view", "top_display"],
    "text_on_accent": ["sidebar_selected", "accent_btn"],
    "button_bg": ["sample_btn"],
    "button_hover": ["sample_btn"],
    "button_active": ["sample_btn"],
    "button_disabled": ["sample_btn"],
    "accent": ["sidebar_selected", "accent_btn"],
    "accent_hover": ["accent_btn"],
    "border": ["preview_host", "card"],
    "divider": ["card"],
    "focus_ring": ["top", "sidebar", "card", "sample_btn", "accent_btn", "sidebar_selected"],
}

INT_TOKENS = {
    "sidebar_width", "topbar_height", "button_height", "pad_x", "pad_y",
    "font_size_main", "font_size_small",
}

FALLBACK_THEME = {
    "app_bg": "#1e1e1e",
    "topbar_bg": "#333333",
    "sidebar_bg": "#2a2a2a",
    "content_bg": "#1e1e1e",
    "panel_bg": "#2e2e2e",
    "text_main": "#c0c0c0",
    "text_muted": "#909090",
    "text_active": "#d0d0d0",
    "text_on_accent": "#ffffff",
    "button_bg": "#333333",
    "button_hover": "#444444",
    "button_active": "#ffffff",
    "button_disabled": "#555555",
    "accent": "#40c0c0",
    "accent_hover": "#55d5d5",
    "border": "#444444",
    "divider": "#3a3a3a",
    "focus_ring": "#40c0c0",
    "sidebar_width": 240,
    "topbar_height": 32,
    "button_height": 28,
    "pad_x": 6,
    "pad_y": 3,
    "font_size_main": 10,
    "font_size_small": 8,
}

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
    "divider": "#3a3a3a",
}


def _bind_scroll(widget):
    interaction_support.bind_wheel_scroll(widget)


class PageThemeOrganizer:
    PAGE_NAME = "theme_organizer"

    def __init__(self, parent, app=None, page_key="", page_folder="", *args, **kwargs):
        app = kwargs.pop("controller", app)
        page_key = kwargs.pop("page_context", page_key)
        page_folder = kwargs.pop("page_folder", page_folder)

        self.parent = parent
        self.app = app
        self.page_key = page_key
        self.page_folder = page_folder
        self.guichi_page_theme = None
        self._page_theme_tokens = dict(_DEFAULT_PAGE_THEME)
        self._style_prefix = f"ThemeOrganizer.{id(self)}"

        self._themes_path = self._resolve_themes_path()
        self._themes = {}
        self._selected_theme_name = None
        self._original_theme = None
        self._token_vars = {}
        self._token_entries = {}
        self._token_swatches = {}
        self._token_pick_buttons = {}
        self._status_var = tk.StringVar(value="Ready.")
        self._theme_name_var = tk.StringVar(value="")
        self._theme_picker_var = tk.StringVar(value="")
        self._active_token_var = tk.StringVar(value="Select a token to see what it affects.")
        self._preview_frames = {}
        self._preview_labels = {}
        self._preview_buttons = {}
        self._preview_border_defaults = {}
        self._header_frame = None
        self._header_title = None
        self._header_subtitle = None
        self._helper_title = None
        self._helper_value = None
        self._dirty = False
        self._control_layout_mode = None
        self._content_layout_mode = None

        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(2, weight=1)

        self._build_ui()
        self.frame.bind("<Configure>", self._on_resize, add="+")
        self._load_themes()

    def _resolve_themes_path(self):
        here = Path(__file__).resolve()
        for candidate in [here.parent, *here.parents]:
            path = candidate / "gui_files" / "themes" / "themes.json"
            if path.exists():
                return str(path)
        return ""

    def build(self, parent=None):
        container = parent or self.parent
        if container is not None and self.frame.master is not container:
            self.frame.destroy()
            self.parent = container
            self.frame = ttk.Frame(container)
            self.frame.columnconfigure(0, weight=1)
            self.frame.rowconfigure(2, weight=1)
            self._build_ui()
            self.frame.bind("<Configure>", self._on_resize, add="+")
            self._load_themes()
            self._apply_page_theme_to_page()
        try:
            self.frame.pack(fill="both", expand=True)
        except Exception:
            self.frame.grid(row=0, column=0, sticky="nsew")
        return self.frame

    create_widgets = build
    mount = build
    render = build

    def set_guichi_page_theme(self, context):
        self.guichi_page_theme = context
        tokens = dict(_DEFAULT_PAGE_THEME)
        tokens.update((context or {}).get("tokens") or {})
        self._page_theme_tokens = tokens
        self._apply_page_theme_to_page()

    def _build_ui(self):
        header = ttk.Frame(self.frame, padding=(10, 8, 10, 4))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        self._header_frame = header
        self._header_title = ttk.Label(
            header,
            text="Theme Organizer",
            style=f"{self._style_prefix}.HeaderTitle.TLabel",
        )
        self._header_title.grid(row=0, column=0, sticky="w")
        self._header_subtitle = ttk.Label(
            header,
            text="Edit Guichi theme tokens visually, preview them live, and save custom themes.",
            style=f"{self._style_prefix}.Muted.TLabel",
        )
        self._header_subtitle.grid(row=1, column=0, sticky="w", pady=(1, 0))

        control_bar = ttk.LabelFrame(
            self.frame,
            text="Theme Controls",
            padding=(8, 8),
            style=f"{self._style_prefix}.TLabelframe",
        )
        control_bar.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))
        control_bar.columnconfigure(0, weight=1)
        self._control_bar = control_bar

        self._theme_select_group = ttk.Frame(control_bar, style=f"{self._style_prefix}.Panel.TFrame")
        self._theme_manage_group = ttk.Frame(control_bar, style=f"{self._style_prefix}.Panel.TFrame")
        self._theme_save_group = ttk.Frame(control_bar, style=f"{self._style_prefix}.Panel.TFrame")
        self._theme_meta_group = ttk.Frame(control_bar, style=f"{self._style_prefix}.Panel.TFrame")

        self._theme_select_group.columnconfigure(1, weight=1)
        self._theme_select_group.columnconfigure(3, weight=1)

        ttk.Label(
            self._theme_select_group,
            text="Current",
            style=f"{self._style_prefix}.Panel.TLabel",
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self._theme_picker = ttk.Combobox(
            self._theme_select_group,
            textvariable=self._theme_picker_var,
            state="readonly",
            height=12,
            width=18,
            style=f"{self._style_prefix}.TCombobox",
        )
        self._theme_picker.grid(row=0, column=1, sticky="ew")
        self._theme_picker.bind("<<ComboboxSelected>>", self._on_theme_select)

        ttk.Label(
            self._theme_select_group,
            text="Theme name",
            style=f"{self._style_prefix}.Panel.TLabel",
        ).grid(row=0, column=2, sticky="w", padx=(10, 8))
        ttk.Entry(
            self._theme_select_group,
            textvariable=self._theme_name_var,
            width=18,
            style=f"{self._style_prefix}.TEntry",
        ).grid(row=0, column=3, sticky="ew")

        ttk.Button(self._theme_manage_group, text="New", command=self._new_theme, style=f"{self._style_prefix}.TButton").pack(side="left")
        ttk.Button(self._theme_manage_group, text="Duplicate", command=self._duplicate_theme, style=f"{self._style_prefix}.TButton").pack(side="left", padx=(6, 0))
        ttk.Button(self._theme_manage_group, text="Revert", command=self._revert_theme, style=f"{self._style_prefix}.TButton").pack(side="left", padx=(6, 0))
        ttk.Button(self._theme_manage_group, text="Reset Token", command=self._reset_selected_token, style=f"{self._style_prefix}.TButton").pack(side="left", padx=(6, 0))

        ttk.Button(self._theme_save_group, text="Save", command=self._save_theme, style=f"{self._style_prefix}.TButton").pack(side="left")
        ttk.Button(self._theme_save_group, text="Save As...", command=self._save_theme_as, style=f"{self._style_prefix}.TButton").pack(side="left", padx=(6, 0))

        self._meta_note = ttk.Label(
            self._theme_meta_group,
            text="Future page element workshop foundation.",
            style=f"{self._style_prefix}.Panel.Muted.TLabel",
        )
        self._meta_note.pack(side="left")
        self._status_label = ttk.Label(
            self._theme_meta_group,
            textvariable=self._status_var,
            style=f"{self._style_prefix}.Panel.Muted.TLabel",
        )
        self._status_label.pack(side="right")

        content = ttk.Frame(self.frame, style=f"{self._style_prefix}.TFrame")
        content.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)
        self._content_host = content

        editor_outer = ttk.LabelFrame(
            content,
            text="Theme Tokens",
            padding=(6, 6),
            style=f"{self._style_prefix}.TLabelframe",
        )
        editor_outer.columnconfigure(0, weight=1)
        editor_outer.rowconfigure(0, weight=1)
        self._editor_outer = editor_outer

        self._token_canvas = tk.Canvas(editor_outer, highlightthickness=0)
        token_scroll = ttk.Scrollbar(editor_outer, orient="vertical", command=self._token_canvas.yview)
        self._token_canvas.configure(yscrollcommand=token_scroll.set)
        self._token_canvas.grid(row=0, column=0, sticky="nsew")
        token_scroll.grid(row=0, column=1, sticky="ns")

        self._token_inner = ttk.Frame(self._token_canvas, padding=(0, 0, 6, 0))
        self._token_inner.columnconfigure(1, weight=1)
        self._token_window = self._token_canvas.create_window((0, 0), window=self._token_inner, anchor="nw")
        self._token_inner.bind("<Configure>", lambda e: self._token_canvas.configure(scrollregion=self._token_canvas.bbox("all")))
        self._token_canvas.bind("<Configure>", lambda e: self._token_canvas.itemconfigure(self._token_window, width=e.width))
        _bind_scroll(self._token_canvas)

        self._build_token_editor(self._token_inner)

        helper_row = ttk.Frame(editor_outer, padding=(2, 8, 2, 0), style=f"{self._style_prefix}.Panel.TFrame")
        helper_row.grid(row=1, column=0, columnspan=2, sticky="ew")
        self._helper_title = ttk.Label(
            helper_row,
            text="Active token",
            style=f"{self._style_prefix}.Panel.SectionTitle.TLabel",
        )
        self._helper_title.pack(anchor="w")
        self._helper_value = ttk.Label(
            helper_row,
            textvariable=self._active_token_var,
            style=f"{self._style_prefix}.Panel.Muted.TLabel",
            wraplength=520,
            justify="left",
        )
        self._helper_value.pack(anchor="w", pady=(2, 0))

        preview_outer = ttk.LabelFrame(
            content,
            text="Live Preview",
            padding=(10, 10),
            style=f"{self._style_prefix}.TLabelframe",
        )
        preview_outer.columnconfigure(0, weight=1)
        preview_outer.rowconfigure(0, weight=1)
        self._preview_outer = preview_outer

        self._preview_host = tk.Frame(preview_outer, bg=FALLBACK_THEME["app_bg"], bd=1, relief="solid")
        self._preview_host.grid(row=0, column=0, sticky="nsew")
        self._preview_frames["preview_host"] = self._preview_host
        self._build_preview(self._preview_host)
        self._apply_page_theme_to_page()
        self._apply_responsive_layout()

    def _on_resize(self, _event=None):
        self._apply_responsive_layout()

    def _apply_responsive_layout(self):
        width = max(self.frame.winfo_width(), 1)
        control_mode = "stacked" if width < 1180 else "inline"
        if control_mode != self._control_layout_mode:
            for group in (
                self._theme_select_group,
                self._theme_manage_group,
                self._theme_save_group,
                self._theme_meta_group,
            ):
                group.grid_forget()
            if control_mode == "inline":
                self._theme_select_group.grid(row=0, column=0, sticky="ew")
                self._theme_manage_group.grid(row=0, column=1, sticky="w", padx=(12, 0))
                self._theme_save_group.grid(row=0, column=2, sticky="w", padx=(12, 0))
                self._theme_meta_group.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(6, 0))
                self._control_bar.columnconfigure(0, weight=1)
            else:
                self._theme_select_group.grid(row=0, column=0, sticky="ew")
                self._theme_save_group.grid(row=1, column=0, sticky="w", pady=(6, 0))
                self._theme_manage_group.grid(row=2, column=0, sticky="w", pady=(6, 0))
                self._theme_meta_group.grid(row=3, column=0, sticky="ew", pady=(6, 0))
                self._control_bar.columnconfigure(0, weight=1)
            self._control_layout_mode = control_mode

        content_mode = "vertical" if width < 1320 else "horizontal"
        if content_mode != self._content_layout_mode:
            self._editor_outer.grid_forget()
            self._preview_outer.grid_forget()
            if content_mode == "horizontal":
                self._content_host.columnconfigure(0, weight=3)
                self._content_host.columnconfigure(1, weight=4)
                self._content_host.rowconfigure(0, weight=1)
                self._editor_outer.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
                self._preview_outer.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
            else:
                self._content_host.columnconfigure(0, weight=1)
                self._content_host.rowconfigure(0, weight=4)
                self._content_host.rowconfigure(1, weight=3)
                self._preview_outer.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
                self._editor_outer.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
            self._content_layout_mode = content_mode

    def _build_token_editor(self, parent):
        row = 0
        for group_name, tokens in TOKEN_GROUPS:
            ttk.Label(parent, text=group_name, style=f"{self._style_prefix}.Panel.SectionTitle.TLabel").grid(
                row=row, column=0, columnspan=4, sticky="w", pady=(8 if row else 0, 6)
            )
            row += 1
            for token in tokens:
                swatch = tk.Canvas(parent, width=18, height=18, highlightthickness=0, bd=0)
                swatch.grid(row=row, column=0, sticky="w", padx=(0, 6), pady=3)
                self._token_swatches[token] = swatch
                ttk.Label(parent, text=token, style=f"{self._style_prefix}.Panel.TLabel").grid(row=row, column=1, sticky="w", padx=(0, 8), pady=2)
                var = tk.StringVar(value="")
                var.trace_add("write", lambda *_args, t=token: self._on_token_change(t))
                self._token_vars[token] = var
                entry_width = 10 if token in COLOR_TOKENS else 6
                entry = ttk.Entry(parent, textvariable=var, width=entry_width, style=f"{self._style_prefix}.TEntry")
                entry.grid(row=row, column=2, sticky="ew", pady=2)
                entry.bind("<FocusIn>", lambda _e, t=token: self._set_active_token(t))
                entry.bind("<Button-1>", lambda _e, t=token: self._set_active_token(t))
                self._token_entries[token] = entry
                if token in COLOR_TOKENS:
                    btn = ttk.Button(parent, text="Pick", width=5, command=lambda t=token: self._pick_color(t), style=f"{self._style_prefix}.TButton")
                    btn.grid(row=row, column=3, padx=(6, 0), pady=2, sticky="e")
                    self._token_pick_buttons[token] = btn
                else:
                    ttk.Label(parent, text="number", style=f"{self._style_prefix}.Panel.Muted.TLabel").grid(
                        row=row, column=3, padx=(6, 0), pady=2, sticky="e"
                    )
                row += 1

    def _build_preview(self, parent):
        top = tk.Frame(parent, height=34, bg=FALLBACK_THEME["topbar_bg"])
        top.pack(fill="x")
        top.pack_propagate(False)
        self._preview_frames["top"] = top
        self._preview_border_defaults["top"] = {"highlightthickness": 0, "bd": 0, "relief": "flat"}

        for name in ("Shell", "View", "Display"):
            btn = tk.Label(top, text=name, padx=8, pady=6, bg=FALLBACK_THEME["topbar_bg"], fg=FALLBACK_THEME["text_main"])
            btn.pack(side="left", padx=(2, 0))
            self._preview_buttons[f"top_{name.lower()}"] = btn

        body = tk.Frame(parent, bg=FALLBACK_THEME["content_bg"])
        body.pack(fill="both", expand=True)
        self._preview_frames["body"] = body

        sidebar = tk.Frame(body, width=140, bg=FALLBACK_THEME["sidebar_bg"])
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        self._preview_frames["sidebar"] = sidebar
        self._preview_border_defaults["sidebar"] = {"highlightthickness": 0, "bd": 0, "relief": "flat"}

        nav_head = tk.Label(sidebar, text="navigation", anchor="w", padx=8, pady=6,
                            bg=FALLBACK_THEME["sidebar_bg"], fg=FALLBACK_THEME["text_muted"])
        nav_head.pack(fill="x")
        self._preview_labels["nav_head"] = nav_head

        item1 = tk.Label(sidebar, text="theme_organizer", anchor="w", padx=8, pady=4,
                         bg=FALLBACK_THEME["accent"], fg=FALLBACK_THEME["text_on_accent"])
        item1.pack(fill="x", padx=6, pady=(4, 2))
        self._preview_labels["sidebar_selected"] = item1

        item2 = tk.Label(sidebar, text="audio_router", anchor="w", padx=8, pady=4,
                         bg=FALLBACK_THEME["panel_bg"], fg=FALLBACK_THEME["text_main"])
        item2.pack(fill="x", padx=6, pady=2)
        self._preview_labels["sidebar_item"] = item2

        content = tk.Frame(body, bg=FALLBACK_THEME["content_bg"])
        content.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        self._preview_frames["content"] = content

        card = tk.Frame(content, bg=FALLBACK_THEME["panel_bg"], bd=1, relief="solid")
        card.pack(fill="both", expand=True)
        self._preview_frames["card"] = card
        self._preview_border_defaults["card"] = {"highlightthickness": 0, "bd": 1, "relief": "solid"}

        title = tk.Label(card, text="Preview Shell", font=("TkDefaultFont", 13, "bold"),
                         bg=FALLBACK_THEME["panel_bg"], fg=FALLBACK_THEME["text_main"], anchor="w")
        title.pack(fill="x", padx=10, pady=(10, 4))
        self._preview_labels["title"] = title

        subtitle = tk.Label(card, text="A visual sample of toolbar, navigation, panel, and buttons.",
                            bg=FALLBACK_THEME["panel_bg"], fg=FALLBACK_THEME["text_muted"], anchor="w")
        subtitle.pack(fill="x", padx=10, pady=(0, 8))
        self._preview_labels["subtitle"] = subtitle

        button_row = tk.Frame(card, bg=FALLBACK_THEME["panel_bg"])
        button_row.pack(fill="x", padx=10, pady=(0, 10))
        self._preview_frames["button_row"] = button_row

        sample_btn = tk.Label(button_row, text="Primary Action", padx=10, pady=5,
                              bg=FALLBACK_THEME["button_bg"], fg=FALLBACK_THEME["text_main"], bd=1, relief="ridge")
        sample_btn.pack(side="left")
        self._preview_buttons["sample_btn"] = sample_btn
        self._preview_border_defaults["sample_btn"] = {"highlightthickness": 0, "bd": 1, "relief": "ridge"}

        accent_btn = tk.Label(button_row, text="Accent State", padx=10, pady=5,
                              bg=FALLBACK_THEME["accent"], fg=FALLBACK_THEME["text_on_accent"], bd=1, relief="ridge")
        accent_btn.pack(side="left", padx=(8, 0))
        self._preview_buttons["accent_btn"] = accent_btn
        self._preview_border_defaults["accent_btn"] = {"highlightthickness": 0, "bd": 1, "relief": "ridge"}

        text = tk.Label(card, text="The goal is to make theme direction obvious before saving.",
                        wraplength=360, justify="left",
                        bg=FALLBACK_THEME["panel_bg"], fg=FALLBACK_THEME["text_main"], anchor="w")
        text.pack(fill="x", padx=10, pady=(0, 12))
        self._preview_labels["text"] = text

        status = tk.Frame(parent, height=28, bg=FALLBACK_THEME["panel_bg"])
        status.pack(fill="x")
        status.pack_propagate(False)
        self._preview_frames["status"] = status
        self._preview_border_defaults["status"] = {"highlightthickness": 0, "bd": 0, "relief": "flat"}
        status_label = tk.Label(status, text="[12:34:56] preview ready", anchor="w",
                                padx=8, bg=FALLBACK_THEME["panel_bg"], fg=FALLBACK_THEME["text_muted"])
        status_label.pack(fill="x")
        self._preview_labels["status_label"] = status_label

    def _apply_page_theme_to_page(self):
        tokens = self._page_theme_tokens
        try:
            style = ttk.Style(self.frame)
            style.configure(
                f"{self._style_prefix}.TFrame",
                background=tokens["content_bg"],
            )
            style.configure(
                f"{self._style_prefix}.TLabelframe",
                background=tokens["panel_bg"],
                bordercolor=tokens["border"],
            )
            style.configure(
                f"{self._style_prefix}.TLabelframe.Label",
                background=tokens["panel_bg"],
                foreground=tokens["text_main"],
            )
            style.configure(
                f"{self._style_prefix}.TLabel",
                background=tokens["content_bg"],
                foreground=tokens["text_main"],
            )
            style.configure(
                f"{self._style_prefix}.Muted.TLabel",
                background=tokens["content_bg"],
                foreground=tokens["text_muted"],
            )
            style.configure(
                f"{self._style_prefix}.Panel.TFrame",
                background=tokens["panel_bg"],
            )
            style.configure(
                f"{self._style_prefix}.Panel.TLabel",
                background=tokens["panel_bg"],
                foreground=tokens["text_main"],
            )
            style.configure(
                f"{self._style_prefix}.Panel.Muted.TLabel",
                background=tokens["panel_bg"],
                foreground=tokens["text_muted"],
            )
            style.configure(
                f"{self._style_prefix}.HeaderTitle.TLabel",
                background=tokens["content_bg"],
                foreground=tokens["text_main"],
                font=("TkDefaultFont", 14, "bold"),
            )
            style.configure(
                f"{self._style_prefix}.SectionTitle.TLabel",
                background=tokens["content_bg"],
                foreground=tokens["text_main"],
                font=("TkDefaultFont", 10, "bold"),
            )
            style.configure(
                f"{self._style_prefix}.Panel.SectionTitle.TLabel",
                background=tokens["panel_bg"],
                foreground=tokens["text_main"],
                font=("TkDefaultFont", 10, "bold"),
            )
            style.configure(
                f"{self._style_prefix}.TButton",
                background=tokens["button_bg"],
                foreground=tokens["text_main"],
            )
            style.map(
                f"{self._style_prefix}.TButton",
                background=[("active", tokens["button_hover"])],
                foreground=[("active", tokens["text_active"]), ("disabled", tokens["button_disabled"])],
            )
            style.configure(
                f"{self._style_prefix}.TEntry",
                fieldbackground=tokens["panel_bg"],
                foreground=tokens["text_main"],
            )
            style.configure(
                f"{self._style_prefix}.TCombobox",
                fieldbackground=tokens["panel_bg"],
                foreground=tokens["text_main"],
                background=tokens["panel_bg"],
                arrowcolor=tokens["text_main"],
            )
        except Exception:
            pass

        for widget in (
            self.frame,
            self._header_frame,
            self._control_bar,
            self._theme_select_group,
            self._theme_manage_group,
            self._theme_save_group,
            self._theme_meta_group,
        ):
            if widget is None:
                continue
            try:
                widget.configure(style=f"{self._style_prefix}.Panel.TFrame")
            except Exception:
                pass
        if self._content_host is not None:
            try:
                self._content_host.configure(style=f"{self._style_prefix}.TFrame")
            except Exception:
                pass

        for widget in (self._editor_outer, self._preview_outer):
            if widget is None:
                continue
            try:
                widget.configure(style=f"{self._style_prefix}.TLabelframe")
            except Exception:
                pass

        if self._token_canvas is not None:
            try:
                self._token_canvas.configure(
                    background=tokens["content_bg"],
                    highlightbackground=tokens["border"],
                    highlightcolor=tokens["accent"],
                )
            except Exception:
                pass
        if self._token_inner is not None:
            try:
                self._token_inner.configure(style=f"{self._style_prefix}.Panel.TFrame")
            except Exception:
                pass
        for swatch in self._token_swatches.values():
            try:
                swatch.configure(background=tokens["panel_bg"])
            except Exception:
                pass

        if self._preview_host is not None:
            try:
                self._preview_host.configure(highlightbackground=tokens["border"])
            except Exception:
                pass

    def _load_themes(self):
        if not self._themes_path or not os.path.isfile(self._themes_path):
            self._themes = {"draft_theme": dict(FALLBACK_THEME)}
            self._set_status("themes.json not found; using in-memory draft theme")
        else:
            try:
                with open(self._themes_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict) and data:
                    self._themes = data
                else:
                    self._themes = {"draft_theme": dict(FALLBACK_THEME)}
                    self._set_status("themes.json empty; using draft theme")
            except Exception as exc:
                self._themes = {"draft_theme": dict(FALLBACK_THEME)}
                self._set_status(f"theme load failed: {exc}")
        self._refresh_theme_list()

    def _refresh_theme_list(self):
        names = sorted(self._themes.keys())
        self._theme_picker.configure(values=names)
        if names:
            target = self._selected_theme_name if self._selected_theme_name in names else names[0]
            self._theme_picker_var.set(target)
            self._load_theme_into_editor(target)

    def _load_theme_into_editor(self, name):
        theme = copy.deepcopy(FALLBACK_THEME)
        theme.update(self._themes.get(name, {}))
        self._selected_theme_name = name
        self._original_theme = copy.deepcopy(theme)
        self._theme_name_var.set(name)
        self._theme_picker_var.set(name)
        for token, var in self._token_vars.items():
            var.set(str(theme.get(token, FALLBACK_THEME.get(token, ""))))
        self._dirty = False
        self._apply_preview(theme)
        self._set_active_token("app_bg")
        self._set_status(f"loaded theme: {name}")

    def _get_editor_theme(self):
        theme = {}
        for token, var in self._token_vars.items():
            raw = var.get().strip()
            if token in INT_TOKENS:
                try:
                    theme[token] = int(raw)
                except ValueError:
                    theme[token] = FALLBACK_THEME[token]
            else:
                theme[token] = raw or FALLBACK_THEME[token]
        return theme

    def _on_theme_select(self, _event=None):
        name = self._theme_picker_var.get().strip()
        if not name:
            return
        if name != self._selected_theme_name:
            self._load_theme_into_editor(name)

    def _on_token_change(self, token):
        theme = self._get_editor_theme()
        self._dirty = True
        self._apply_preview(theme)
        self._update_swatch(token, theme.get(token, ""))
        if token in COLOR_TOKENS:
            value = self._token_vars[token].get().strip()
            if value and not self._is_hex_color(value):
                self._set_status(f"invalid color for {token}: {value}")
                return
        self._set_status("preview updated")

    def _pick_color(self, token):
        current = self._token_vars[token].get().strip() or FALLBACK_THEME[token]
        chosen = colorchooser.askcolor(color=current, parent=self.frame, title=f"Pick {token}")
        if chosen and chosen[1]:
            self._token_vars[token].set(chosen[1])

    def _is_hex_color(self, value):
        if len(value) != 7 or not value.startswith("#"):
            return False
        try:
            int(value[1:], 16)
            return True
        except ValueError:
            return False

    def _apply_preview(self, theme):
        t = copy.deepcopy(FALLBACK_THEME)
        t.update(theme)
        self._clear_preview_highlights()
        self._preview_host.configure(bg=t["app_bg"], highlightbackground=t["border"])
        self._preview_frames["top"].configure(bg=t["topbar_bg"])
        self._preview_frames["body"].configure(bg=t["content_bg"])
        self._preview_frames["sidebar"].configure(bg=t["sidebar_bg"])
        self._preview_frames["content"].configure(bg=t["content_bg"])
        self._preview_frames["card"].configure(bg=t["panel_bg"], highlightbackground=t["border"], bd=1)
        self._preview_frames["button_row"].configure(bg=t["panel_bg"])
        self._preview_frames["status"].configure(bg=t["panel_bg"])

        for key in ("top_shell", "top_view", "top_display"):
            self._preview_buttons[key].configure(bg=t["topbar_bg"], fg=t["text_main"])
        self._preview_labels["nav_head"].configure(bg=t["sidebar_bg"], fg=t["text_muted"])
        self._preview_labels["sidebar_selected"].configure(bg=t["accent"], fg=t["text_on_accent"])
        self._preview_labels["sidebar_item"].configure(bg=t["panel_bg"], fg=t["text_main"])
        for key in ("title", "text"):
            self._preview_labels[key].configure(bg=t["panel_bg"], fg=t["text_main"])
        self._preview_labels["subtitle"].configure(bg=t["panel_bg"], fg=t["text_muted"])
        self._preview_labels["status_label"].configure(bg=t["panel_bg"], fg=t["text_muted"])
        self._preview_buttons["sample_btn"].configure(bg=t["button_bg"], fg=t["text_main"], activebackground=t["button_hover"])
        self._preview_buttons["accent_btn"].configure(bg=t["accent"], fg=t["text_on_accent"])
        for token in self._token_swatches:
            self._update_swatch(token, t.get(token, ""))
        active = self._active_token_var.get()
        if active and active.startswith("Token: "):
            token = active.split("Token: ", 1)[1].split(" — ", 1)[0]
            if token in self._token_vars:
                self._highlight_preview_targets(token, t)

    def _update_swatch(self, token, value):
        swatch = self._token_swatches.get(token)
        if swatch is None:
            return
        swatch.delete("all")
        if token in COLOR_TOKENS and self._is_hex_color(str(value).strip()):
            fill = str(value).strip()
        else:
            fill = "#888888"
        swatch.create_oval(2, 2, 16, 16, fill=fill, outline="#555555")

    def _set_active_token(self, token):
        helper = TOKEN_HELP.get(token, token)
        self._active_token_var.set(f"Token: {token} — {helper}")
        self._highlight_preview_targets(token, self._get_editor_theme())

    def _clear_preview_highlights(self):
        for key, widget in self._preview_frames.items():
            defaults = self._preview_border_defaults.get(key)
            if not defaults:
                continue
            try:
                widget.configure(**defaults)
            except Exception:
                pass
        for key in ("sample_btn", "accent_btn"):
            widget = self._preview_buttons.get(key)
            defaults = self._preview_border_defaults.get(key)
            if widget is None or not defaults:
                continue
            try:
                widget.configure(**defaults)
            except Exception:
                pass

    def _highlight_preview_targets(self, token, theme):
        t = copy.deepcopy(FALLBACK_THEME)
        t.update(theme)
        self._clear_preview_highlights()
        glow = t.get("focus_ring") or t.get("accent") or "#ffffff"
        for target in TOKEN_TARGETS.get(token, []):
            widget = (
                self._preview_frames.get(target)
                or self._preview_labels.get(target)
                or self._preview_buttons.get(target)
            )
            if widget is None:
                continue
            try:
                widget.configure(highlightthickness=2, highlightbackground=glow, highlightcolor=glow)
            except Exception:
                try:
                    widget.configure(bd=2, relief="solid")
                except Exception:
                    pass

    def _new_theme(self):
        name = simpledialog.askstring("New Theme", "Theme name:", parent=self.frame)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if name in self._themes:
            messagebox.showwarning("New Theme", f"Theme already exists: {name}", parent=self.frame)
            return
        self._themes[name] = copy.deepcopy(FALLBACK_THEME)
        self._selected_theme_name = name
        self._refresh_theme_list()
        self._set_status(f"created new theme draft: {name}")

    def _duplicate_theme(self):
        if not self._selected_theme_name:
            return
        name = simpledialog.askstring(
            "Duplicate Theme",
            "New theme name:",
            initialvalue=f"{self._selected_theme_name}_copy",
            parent=self.frame,
        )
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if name in self._themes:
            messagebox.showwarning("Duplicate Theme", f"Theme already exists: {name}", parent=self.frame)
            return
        self._themes[name] = self._get_editor_theme()
        self._selected_theme_name = name
        self._refresh_theme_list()
        self._set_status(f"duplicated theme: {name}")

    def _revert_theme(self):
        if not self._original_theme:
            return
        for token, var in self._token_vars.items():
            var.set(str(self._original_theme.get(token, FALLBACK_THEME.get(token, ""))))
        self._dirty = False
        self._apply_preview(self._original_theme)
        self._set_status("reverted unsaved changes")

    def _save_theme(self):
        name = self._theme_name_var.get().strip() or self._selected_theme_name
        if not name:
            self._set_status("enter a theme name first")
            return
        theme = self._validate_theme()
        if theme is None:
            return
        self._themes[name] = theme
        if self._selected_theme_name and self._selected_theme_name != name and self._selected_theme_name in self._themes:
            # keep old theme unless explicit save-as/rename path later
            pass
        self._selected_theme_name = name
        self._write_themes()
        self._refresh_theme_list()
        self._dirty = False
        self._set_status(f"saved theme: {name}")

    def _save_theme_as(self):
        name = simpledialog.askstring(
            "Save Theme As",
            "New theme name:",
            initialvalue=self._theme_name_var.get().strip() or self._selected_theme_name or "custom_theme",
            parent=self.frame,
        )
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if name in self._themes:
            confirm = messagebox.askyesno("Save Theme As", f"Overwrite existing theme '{name}'?", parent=self.frame)
            if not confirm:
                return
        self._theme_name_var.set(name)
        self._save_theme()

    def _validate_theme(self):
        theme = {}
        for token, var in self._token_vars.items():
            raw = var.get().strip()
            if token in COLOR_TOKENS:
                if not self._is_hex_color(raw):
                    messagebox.showwarning("Invalid Theme", f"{token} must be a hex color like #aabbcc", parent=self.frame)
                    self._set_status(f"invalid color: {token}")
                    return None
                theme[token] = raw
            elif token in INT_TOKENS:
                try:
                    theme[token] = int(raw)
                except ValueError:
                    messagebox.showwarning("Invalid Theme", f"{token} must be a whole number", parent=self.frame)
                    self._set_status(f"invalid number: {token}")
                    return None
        return theme

    def _write_themes(self):
        if not self._themes_path:
            self._set_status("cannot resolve themes.json path")
            return
        with open(self._themes_path, "w", encoding="utf-8") as fh:
            json.dump(dict(sorted(self._themes.items())), fh, indent=4, ensure_ascii=False)

    def _reset_selected_token(self):
        widget = self.frame.focus_get()
        for token, entry in self._token_entries.items():
            if entry is widget:
                self._token_vars[token].set(str(FALLBACK_THEME.get(token, "")))
                self._set_status(f"reset token: {token}")
                return
        self._set_status("focus a token field to reset it")

    def _set_status(self, text):
        self._status_var.set(text)
