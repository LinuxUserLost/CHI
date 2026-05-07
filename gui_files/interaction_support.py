"""
Universal Guichi interaction helpers.

This module is intentionally conservative:
- wheel scrolling helpers
- shell-global Ctrl-A / Ctrl-C handling for text widgets
- dismiss-only Escape support for transient UI
- small widget setup helpers pages can opt into
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def _root_for(widget):
    try:
        return widget.winfo_toplevel()
    except Exception:
        return None


def _interaction_settings(root):
    defaults = {
        "wheel_scroll_enabled": True,
        "ctrl_a_enabled": True,
        "ctrl_c_enabled": True,
        "escape_dismiss_enabled": True,
    }
    if root is None:
        return defaults
    live = getattr(root, "_guichi_interaction_settings", None)
    if isinstance(live, dict):
        defaults.update(live)
    return defaults


def bind_wheel_scroll(widget, orient="y"):
    """Bind Linux-safe and cross-platform wheel scrolling to a widget."""
    axis_view = getattr(widget, f"{orient}view", None)
    if not callable(axis_view):
        return widget

    def _handler(event):
        root = _root_for(widget)
        if not _interaction_settings(root).get("wheel_scroll_enabled", True):
            return None
        try:
            if event.num == 4:
                axis_view_scroll(widget, -1, orient)
                return "break"
            if event.num == 5:
                axis_view_scroll(widget, 1, orient)
                return "break"
            if getattr(event, "delta", 0):
                steps = int(-1 * (event.delta / 120))
                if steps:
                    axis_view_scroll(widget, steps, orient)
                    return "break"
        except Exception:
            return None
        return None

    widget.bind("<MouseWheel>", _handler, add="+")
    widget.bind("<Button-4>", _handler, add="+")
    widget.bind("<Button-5>", _handler, add="+")
    return widget


def axis_view_scroll(widget, steps, orient="y"):
    """Scroll widget by steps units on the given axis ('x' or 'y')."""
    if orient == "x":
        widget.xview_scroll(steps, "units")
    else:
        widget.yview_scroll(steps, "units")


def setup_entry_widget(widget):
    """Hook point for Entry/ttk.Entry baseline setup; currently a pass-through for future expansion."""
    return widget


def setup_text_widget(widget, wheel=True):
    """Opt a Text widget into Guichi baseline interactions, with optional wheel scroll."""
    if wheel:
        bind_wheel_scroll(widget)
    return widget


def setup_listbox_widget(widget, wheel=True):
    """Opt a Listbox into Guichi baseline interactions, with optional wheel scroll."""
    if wheel:
        bind_wheel_scroll(widget)
    return widget


def setup_treeview_widget(widget, wheel=True):
    """Opt a Treeview into Guichi baseline interactions, with optional wheel scroll."""
    if wheel:
        bind_wheel_scroll(widget)
    return widget


def install_root_bindings(root):
    """Install shell-global conservative interaction bindings."""
    if getattr(root, "_guichi_interactions_installed", False):
        return
    root._guichi_interactions_installed = True
    root._guichi_escape_callbacks = []
    if not hasattr(root, "_guichi_interaction_settings"):
        root._guichi_interaction_settings = {
            "wheel_scroll_enabled": True,
            "ctrl_a_enabled": True,
            "ctrl_c_enabled": True,
            "escape_dismiss_enabled": True,
        }

    root.bind_all("<Control-a>", lambda e: _on_select_all(e), add="+")
    root.bind_all("<Control-A>", lambda e: _on_select_all(e), add="+")
    root.bind_all("<Control-c>", lambda e: _on_copy_selection(e), add="+")
    root.bind_all("<Control-C>", lambda e: _on_copy_selection(e), add="+")
    root.bind_all("<Escape>", lambda e: _on_escape(e), add="+")


def register_escape_dismiss(root, callback, key=None):
    """Register a dismiss callback invoked by global Escape."""
    install_root_bindings(root)
    key = key or callback
    callbacks = getattr(root, "_guichi_escape_callbacks", [])
    callbacks[:] = [item for item in callbacks if item[0] != key]
    callbacks.append((key, callback))
    root._guichi_escape_callbacks = callbacks
    return key


def unregister_escape_dismiss(root, key):
    """Remove a previously registered Escape dismiss callback by its key."""
    callbacks = getattr(root, "_guichi_escape_callbacks", [])
    callbacks[:] = [item for item in callbacks if item[0] != key]
    root._guichi_escape_callbacks = callbacks


def show_popup_menu(root, menu, x_root, y_root):
    """Show a popup menu with Escape-dismiss support."""
    settings = _interaction_settings(root)
    key = None
    if settings.get("escape_dismiss_enabled", True):
        key = register_escape_dismiss(root, lambda: _dismiss_menu(menu), key=id(menu))
    try:
        menu.tk_popup(x_root, y_root)
    finally:
        try:
            menu.grab_release()
        except Exception:
            pass
        if key is not None:
            unregister_escape_dismiss(root, key)


def _dismiss_menu(menu):
    try:
        menu.unpost()
    except Exception:
        pass
    try:
        menu.grab_release()
    except Exception:
        pass


def _on_escape(event):
    root = _root_for(event.widget)
    if not _interaction_settings(root).get("escape_dismiss_enabled", True):
        return None
    callbacks = getattr(root, "_guichi_escape_callbacks", []) if root is not None else []
    if callbacks:
        _key, callback = callbacks[-1]
        try:
            callback()
        except Exception:
            pass
        return "break"
    return None


def _on_select_all(event):
    widget = event.widget
    root = _root_for(widget)
    if not _interaction_settings(root).get("ctrl_a_enabled", True):
        return None
    if isinstance(widget, tk.Entry):
        try:
            widget.selection_range(0, "end")
            widget.icursor("end")
            return "break"
        except Exception:
            return None
    if isinstance(widget, ttk.Entry):
        try:
            widget.selection_range(0, "end")
            widget.icursor("end")
            return "break"
        except Exception:
            return None
    if isinstance(widget, tk.Text):
        try:
            widget.tag_add("sel", "1.0", "end-1c")
            widget.mark_set("insert", "1.0")
            widget.see("insert")
            return "break"
        except Exception:
            return None
    return None


def _on_copy_selection(event):
    widget = event.widget
    root = _root_for(widget)
    if not _interaction_settings(root).get("ctrl_c_enabled", True):
        return None
    text = _selected_text(widget)
    if not text:
        return None
    if root is None:
        return None
    try:
        root.clipboard_clear()
        root.clipboard_append(text)
        return "break"
    except Exception:
        return None


def _selected_text(widget):
    if isinstance(widget, (tk.Entry, ttk.Entry)):
        try:
            if widget.selection_present():
                return widget.selection_get()
        except Exception:
            return None
    if isinstance(widget, tk.Text):
        try:
            if widget.tag_ranges("sel"):
                return widget.get("sel.first", "sel.last")
        except Exception:
            return None
    return None
