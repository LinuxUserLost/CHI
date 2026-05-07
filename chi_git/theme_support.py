"""
Shared page-theme support for chi_git pages.

This stays intentionally thin:
- default git-page theme tokens
- style prefix configuration for ttk widgets
- direct application helpers for tk.Text and tk.Listbox

Pages should still own their layout and interaction logic.
"""

from tkinter import ttk

from gui_files import interaction_support


CHIGIT_DEFAULT_PAGE_THEME = {
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


def resolve_chigit_theme(context=None):
    tokens = dict(CHIGIT_DEFAULT_PAGE_THEME)
    tokens.update((context or {}).get("tokens") or {})
    return tokens


def configure_ttk_styles(widget, style_prefix, tokens):
    style = ttk.Style(widget)
    style.configure(
        f"{style_prefix}.TFrame",
        background=tokens["content_bg"],
    )
    style.configure(
        f"{style_prefix}.Panel.TFrame",
        background=tokens["panel_bg"],
    )
    style.configure(
        f"{style_prefix}.TLabelframe",
        background=tokens["panel_bg"],
        bordercolor=tokens["border"],
    )
    style.configure(
        f"{style_prefix}.TLabelframe.Label",
        background=tokens["panel_bg"],
        foreground=tokens["text_main"],
    )
    style.configure(
        f"{style_prefix}.TLabel",
        background=tokens["content_bg"],
        foreground=tokens["text_main"],
    )
    style.configure(
        f"{style_prefix}.Panel.TLabel",
        background=tokens["panel_bg"],
        foreground=tokens["text_main"],
    )
    style.configure(
        f"{style_prefix}.Muted.TLabel",
        background=tokens["content_bg"],
        foreground=tokens["text_muted"],
    )
    style.configure(
        f"{style_prefix}.Panel.Muted.TLabel",
        background=tokens["panel_bg"],
        foreground=tokens["text_muted"],
    )
    style.configure(
        f"{style_prefix}.TButton",
        background=tokens["button_bg"],
        foreground=tokens["text_main"],
    )
    style.map(
        f"{style_prefix}.TButton",
        background=[("active", tokens["button_hover"])],
        foreground=[("active", tokens["text_active"]), ("disabled", tokens["button_disabled"])],
    )
    style.configure(
        f"{style_prefix}.TEntry",
        fieldbackground=tokens["panel_bg"],
        foreground=tokens["text_main"],
    )
    style.configure(
        f"{style_prefix}.TCombobox",
        fieldbackground=tokens["panel_bg"],
        foreground=tokens["text_main"],
        background=tokens["panel_bg"],
        arrowcolor=tokens["text_main"],
    )
    return style


def apply_text_theme(widget, tokens):
    interaction_support.setup_text_widget(widget)
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


def apply_listbox_theme(widget, tokens):
    interaction_support.setup_listbox_widget(widget)
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
