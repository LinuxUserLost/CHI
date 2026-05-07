"""
Dependency tracker page for current live pychi pages.

This surface is intentionally read-only in v1.
It reads the live registry first, then inspects each page module to show:
  - dependency class
  - local/shared module relationships
  - shell/runtime touchpoints
  - OS-specific or heavy-exception flags
"""

from __future__ import annotations

import ast
import json
import os
import sysconfig
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import guichi
from gui_files import interaction_support, shell_registry


_DEFAULT_PAGE_THEME = {
    "content_bg": "#1e1e1e",
    "panel_bg": "#2b2b2b",
    "sidebar_bg": "#242424",
    "text_main": "#dddddd",
    "text_muted": "#8f8f8f",
    "text_active": "#ffffff",
    "text_on_accent": "#ffffff",
    "button_bg": "#373737",
    "button_hover": "#4a4a4a",
    "button_disabled": "#666666",
    "accent": "#4ea0ff",
    "border": "#4a4a4a",
}

_HEAVY_HINTS = {
    "ollama",
    "qwen",
    "tts",
    "speech",
    "audio",
}

_OS_SPECIFIC_IMPORTS = {
    "pty",
    "termios",
    "fcntl",
    "signal",
    "select",
    "pwd",
    "grp",
}

_OS_SPECIFIC_PAGE_HINTS = {
    "audio_router",
    "browserdock",
    "terminal_session",
    "chilaude_terminal",
    "claude_cli_wrap",
    "claude_workstation",
}


def _bind_scroll(widget):
    interaction_support.bind_wheel_scroll(widget)


def _read_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def _list_stdlib_names() -> set[str]:
    names = set(getattr(sysconfig, "get_python_version", lambda: "")() and ())
    std = getattr(__import__("sys"), "stdlib_module_names", None)
    if std:
        names.update(std)
    return names


_STDLIB_NAMES = _list_stdlib_names()


def _parse_imports(module_path: str) -> tuple[list[str], list[str]]:
    text = _read_text(module_path)
    if not text:
        return [], []
    try:
        tree = ast.parse(text, filename=module_path)
    except SyntaxError:
        return [], []
    imports: list[str] = []
    errors: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
            elif node.level:
                imports.append("." * node.level)
        elif isinstance(node, ast.Call):
            pass
    return sorted(set(imports)), errors


def _top_level_name(module_name: str) -> str:
    if not module_name:
        return ""
    return module_name.lstrip(".").split(".", 1)[0]


def _discover_dependency_details(page_entry: dict, pack_entry: dict, registry: dict) -> dict:
    source_path = pack_entry.get("source_path") or ""
    page_path = page_entry.get("page_path") or ""
    module_path = os.path.join(source_path, page_path)
    imports, parse_errors = _parse_imports(module_path)
    local_modules = []
    stdlib_modules = []
    external_modules = []
    os_specific_hits = []
    helper_hits = []

    for module_name in imports:
        top = _top_level_name(module_name)
        if not top:
            continue
        if top in _OS_SPECIFIC_IMPORTS:
            os_specific_hits.append(module_name)
        if top in {"gui_files", "guichi"} or top.startswith("chi_") or top in {"helpers", "shared"}:
            local_modules.append(module_name)
            if top in {"helpers", "shared"} or any(hint in module_name.lower() for hint in _HEAVY_HINTS):
                helper_hits.append(module_name)
            continue
        if top in _STDLIB_NAMES or module_name in _STDLIB_NAMES:
            stdlib_modules.append(module_name)
        else:
            external_modules.append(module_name)

    source_text = _read_text(module_path)
    shell_touchpoints = []
    if "guichi_shell" in source_text:
        shell_touchpoints.append("guichi_shell context")
    if "set_guichi_page_theme" in source_text:
        shell_touchpoints.append("page theme context")
    if "interaction_support" in source_text:
        shell_touchpoints.append("interaction support")

    page_name = (page_entry.get("page_name") or "").lower()
    page_id = (page_entry.get("page_id") or "").lower()
    lower_local = " ".join(local_modules + helper_hits).lower()

    dependency_class = "core_safe"
    if external_modules or any(hint in lower_local for hint in _HEAVY_HINTS) or any(hint in page_name for hint in _HEAVY_HINTS):
        dependency_class = "page_specific_heavy"
    elif os_specific_hits or any(hint in page_name or hint in page_id for hint in _OS_SPECIFIC_PAGE_HINTS):
        dependency_class = "os_specific"
    elif local_modules:
        dependency_class = "optional_local"

    relationship_notes = []
    if local_modules:
        relationship_notes.append(f"imports local modules: {', '.join(local_modules[:6])}")
    if helper_hits:
        relationship_notes.append(f"helper/external lane: {', '.join(helper_hits[:6])}")
    if page_entry.get("page_config_path"):
        relationship_notes.append(f"page config path: {page_entry['page_config_path']}")
    if shell_touchpoints:
        relationship_notes.append(f"shell touchpoints: {', '.join(shell_touchpoints)}")

    reverse_related = []
    target_roots = {mod for mod in local_modules if mod.startswith(("helpers", "shared", "gui_files"))}
    if target_roots:
        for other_pack in registry.get("packs", []):
            for other_page in other_pack.get("pages", []):
                if other_page.get("page_id") == page_entry.get("page_id"):
                    continue
                other_path = os.path.join(other_pack.get("source_path") or "", other_page.get("page_path") or "")
                other_imports, _ = _parse_imports(other_path)
                if any(mod in other_imports for mod in target_roots):
                    reverse_related.append(other_page.get("page_id") or other_page.get("page_name") or "(page)")

    return {
        "module_path": module_path,
        "imports": imports,
        "parse_errors": parse_errors,
        "dependency_class": dependency_class,
        "stdlib_modules": stdlib_modules,
        "local_modules": local_modules,
        "external_modules": external_modules,
        "os_specific_hits": os_specific_hits,
        "helper_hits": helper_hits,
        "shell_touchpoints": shell_touchpoints,
        "relationship_notes": relationship_notes,
        "reverse_related": sorted(set(reverse_related)),
    }


class PageDependencyTracker:
    PAGE_NAME = "dependency_tracker"

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
        self._theme_tokens = dict(_DEFAULT_PAGE_THEME)
        self._style_prefix = f"DependencyTracker.{id(self)}"
        self._registry = {"packs": []}
        self._details_cache = {}
        self._filter_var = tk.StringVar(value="all")
        self._status_var = tk.StringVar(value="Ready.")
        self._selected_page_key = None

        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)

    def build(self, parent=None):
        container = parent or self.parent
        if container is not None and self.frame.master is not container:
            self.frame.destroy()
            self.parent = container
            self.frame = ttk.Frame(container)
            self.frame.columnconfigure(0, weight=1)
            self.frame.rowconfigure(1, weight=1)
        for child in self.frame.winfo_children():
            child.destroy()
        self._build_ui()
        self._apply_page_theme()
        self.refresh_data()
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
        self._theme_tokens = tokens
        self._apply_page_theme()

    def _build_ui(self):
        header = ttk.Frame(self.frame, padding=(10, 8, 10, 6))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        self._header = header

        ttk.Label(
            header,
            text="Page Dependency Tracker",
            style=f"{self._style_prefix}.Header.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Live page map for current implemented packs, helpers, and runtime exceptions.",
            style=f"{self._style_prefix}.Muted.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))

        controls = ttk.Frame(header)
        controls.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Button(controls, text="Refresh", command=self.refresh_data).pack(side="right")
        ttk.Label(controls, text="Class:", style=f"{self._style_prefix}.Muted.TLabel").pack(side="left", padx=(0, 6))
        filter_box = ttk.Combobox(
            controls,
            textvariable=self._filter_var,
            values=["all", "core_safe", "optional_local", "os_specific", "page_specific_heavy"],
            state="readonly",
            width=20,
        )
        filter_box.pack(side="left")
        filter_box.bind("<<ComboboxSelected>>", lambda *_: self._populate_tree())

        summary = ttk.LabelFrame(self.frame, text="Summary", padding=(10, 8))
        summary.grid(row=1, column=0, sticky="ew", padx=10)
        for idx in range(5):
            summary.columnconfigure(idx, weight=1)
        self._summary = summary
        self._summary_labels = {}
        for idx, key in enumerate(("packs", "pages", "core_safe", "optional_local", "exception_lanes")):
            lbl = ttk.Label(summary, text="", style=f"{self._style_prefix}.Summary.TLabel", justify="left")
            lbl.grid(row=0, column=idx, sticky="w", padx=(0, 10))
            self._summary_labels[key] = lbl

        body = ttk.PanedWindow(self.frame, orient="horizontal")
        body.grid(row=2, column=0, sticky="nsew", padx=10, pady=10)
        self.frame.rowconfigure(2, weight=1)

        left = ttk.Frame(body, padding=(0, 0, 8, 0))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        body.add(left, weight=1)

        ttk.Label(left, text="Current Pages", style=f"{self._style_prefix}.PanelHeader.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 4))
        tree = ttk.Treeview(left, show="tree", selectmode="browse")
        tree.grid(row=1, column=0, sticky="nsew")
        tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        _bind_scroll(tree)
        self._tree = tree

        right = ttk.Notebook(body)
        body.add(right, weight=3)
        self._notebook = right

        overview = ttk.Frame(right, padding=10)
        overview.columnconfigure(0, weight=1)
        self._overview = overview
        right.add(overview, text="Overview")

        self._detail_title = ttk.Label(overview, text="Select a page", style=f"{self._style_prefix}.Header.TLabel")
        self._detail_title.grid(row=0, column=0, sticky="w")
        self._detail_meta = ttk.Label(overview, text="", style=f"{self._style_prefix}.Muted.TLabel", wraplength=760, justify="left")
        self._detail_meta.grid(row=1, column=0, sticky="w", pady=(4, 8))
        self._detail_body = tk.Text(
            overview,
            wrap="word",
            state="disabled",
            relief="flat",
            borderwidth=0,
            padx=2,
            pady=2,
            height=26,
        )
        self._detail_body.grid(row=2, column=0, sticky="nsew")
        overview.rowconfigure(2, weight=1)
        _bind_scroll(self._detail_body)

        imports_tab = ttk.Frame(right, padding=10)
        imports_tab.columnconfigure(0, weight=1)
        imports_tab.rowconfigure(0, weight=1)
        right.add(imports_tab, text="Imports")
        self._imports_text = tk.Text(imports_tab, wrap="word", state="disabled", relief="flat", borderwidth=0)
        self._imports_text.grid(row=0, column=0, sticky="nsew")
        _bind_scroll(self._imports_text)

        status = ttk.Label(self.frame, textvariable=self._status_var, style=f"{self._style_prefix}.Muted.TLabel")
        status.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))
        self._status = status

    def _apply_page_theme(self):
        tokens = self._theme_tokens
        try:
            style = ttk.Style(self.frame)
            style.configure(f"{self._style_prefix}.TFrame", background=tokens["content_bg"])
            style.configure(f"{self._style_prefix}.Header.TLabel", background=tokens["content_bg"], foreground=tokens["text_main"], font=("TkDefaultFont", 14, "bold"))
            style.configure(f"{self._style_prefix}.PanelHeader.TLabel", background=tokens["content_bg"], foreground=tokens["text_main"], font=("TkDefaultFont", 11, "bold"))
            style.configure(f"{self._style_prefix}.Muted.TLabel", background=tokens["content_bg"], foreground=tokens["text_muted"])
            style.configure(f"{self._style_prefix}.Summary.TLabel", background=tokens["panel_bg"], foreground=tokens["text_main"])
        except Exception:
            pass
        for widget in (self.frame, getattr(self, "_header", None), getattr(self, "_overview", None)):
            if widget is None:
                continue
            try:
                widget.configure(style=f"{self._style_prefix}.TFrame")
            except Exception:
                pass
        for text_widget in (getattr(self, "_detail_body", None), getattr(self, "_imports_text", None)):
            if text_widget is None:
                continue
            try:
                text_widget.configure(
                    background=tokens["content_bg"],
                    foreground=tokens["text_main"],
                    insertbackground=tokens["text_main"],
                    selectbackground=tokens["accent"],
                    selectforeground=tokens["text_on_accent"],
                )
            except Exception:
                pass

    def refresh_data(self):
        shell = getattr(self, "guichi_shell", None)
        self._registry = shell.registry if shell is not None else shell_registry.load_registry(guichi.REGISTRY_PATH)
        self._details_cache.clear()
        self._populate_summary()
        self._populate_tree()
        self._status_var.set("Loaded live registry and refreshed dependency view.")

    def _iter_pages(self):
        for pack_entry in self._registry.get("packs", []):
            if pack_entry.get("hidden"):
                continue
            for page_entry in pack_entry.get("pages", []):
                yield pack_entry, page_entry

    def _get_page_key(self, pack_entry: dict, page_entry: dict) -> str:
        return f"{pack_entry.get('pack_id')}::{pack_entry.get('source_path')}::{page_entry.get('page_id')}"

    def _get_details(self, pack_entry: dict, page_entry: dict) -> dict:
        key = self._get_page_key(pack_entry, page_entry)
        if key not in self._details_cache:
            self._details_cache[key] = _discover_dependency_details(page_entry, pack_entry, self._registry)
        return self._details_cache[key]

    def _populate_summary(self):
        packs = [p for p in self._registry.get("packs", []) if not p.get("hidden")]
        page_rows = list(self._iter_pages())
        counts = {
            "packs": len(packs),
            "pages": len(page_rows),
            "core_safe": 0,
            "optional_local": 0,
            "exception_lanes": 0,
        }
        for pack_entry, page_entry in page_rows:
            dep_class = self._get_details(pack_entry, page_entry)["dependency_class"]
            if dep_class == "core_safe":
                counts["core_safe"] += 1
            elif dep_class == "optional_local":
                counts["optional_local"] += 1
            else:
                counts["exception_lanes"] += 1
        self._summary_labels["packs"].configure(text=f"Packs\n{counts['packs']}")
        self._summary_labels["pages"].configure(text=f"Pages\n{counts['pages']}")
        self._summary_labels["core_safe"].configure(text=f"Core-safe\n{counts['core_safe']}")
        self._summary_labels["optional_local"].configure(text=f"Optional-local\n{counts['optional_local']}")
        self._summary_labels["exception_lanes"].configure(text=f"Exception lanes\n{counts['exception_lanes']}")

    def _populate_tree(self):
        selected_filter = self._filter_var.get()
        tree = self._tree
        tree.delete(*tree.get_children())
        for pack_entry in self._registry.get("packs", []):
            if pack_entry.get("hidden"):
                continue
            pack_id = pack_entry.get("pack_id") or "(pack)"
            pack_node = tree.insert("", "end", iid=f"pack::{pack_id}::{pack_entry.get('source_path')}", text=f"{pack_id}")
            any_added = False
            for page_entry in pack_entry.get("pages", []):
                details = self._get_details(pack_entry, page_entry)
                dep_class = details["dependency_class"]
                if selected_filter != "all" and dep_class != selected_filter:
                    continue
                page_name = page_entry.get("page_name") or page_entry.get("page_id") or "(page)"
                label = f"{page_name}  [{dep_class}]"
                item_id = self._get_page_key(pack_entry, page_entry)
                tree.insert(pack_node, "end", iid=item_id, text=label)
                any_added = True
            if any_added:
                tree.item(pack_node, open=True)
            else:
                tree.delete(pack_node)

    def _on_tree_select(self, _event=None):
        selection = self._tree.selection()
        if not selection:
            return
        key = selection[0]
        if not key or not key.count("::") >= 2:
            return
        self._selected_page_key = key
        for pack_entry, page_entry in self._iter_pages():
            if self._get_page_key(pack_entry, page_entry) == key:
                self._render_page_details(pack_entry, page_entry)
                return

    def _set_text(self, widget: tk.Text, content: str):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content.strip() + "\n")
        widget.configure(state="disabled")

    def _render_page_details(self, pack_entry: dict, page_entry: dict):
        details = self._get_details(pack_entry, page_entry)
        page_name = page_entry.get("page_name") or page_entry.get("page_id") or "(page)"
        self._detail_title.configure(text=page_name)
        self._detail_meta.configure(
            text=(
                f"class: {details['dependency_class']}   "
                f"pack: {pack_entry.get('pack_id')}   "
                f"path: {page_entry.get('page_path') or '(none)'}"
            )
        )
        overview_lines = [
            f"Module path: {details['module_path']}",
            f"Page class: {page_entry.get('page_class') or '(missing)'}",
            f"Status: {page_entry.get('status', 'unknown')}",
            "",
            "Key relationships:",
        ]
        if details["relationship_notes"]:
            overview_lines.extend(f"- {line}" for line in details["relationship_notes"])
        else:
            overview_lines.append("- no special relationships detected beyond core page loading")
        if details["reverse_related"]:
            overview_lines.append("")
            overview_lines.append("Other pages sharing helper/runtime lanes:")
            overview_lines.extend(f"- {name}" for name in details["reverse_related"][:12])
        if details["parse_errors"]:
            overview_lines.append("")
            overview_lines.append("Parse warnings:")
            overview_lines.extend(f"- {err}" for err in details["parse_errors"])
        self._set_text(self._detail_body, "\n".join(overview_lines))

        import_lines = [
            f"Dependency class: {details['dependency_class']}",
            "",
            "Stdlib imports:",
        ]
        import_lines.extend(f"- {name}" for name in details["stdlib_modules"] or ["(none detected)"])
        import_lines.append("")
        import_lines.append("Local/shared imports:")
        import_lines.extend(f"- {name}" for name in details["local_modules"] or ["(none detected)"])
        import_lines.append("")
        import_lines.append("External imports:")
        import_lines.extend(f"- {name}" for name in details["external_modules"] or ["(none detected)"])
        import_lines.append("")
        import_lines.append("OS-specific flags:")
        flags = details["os_specific_hits"] or ["(none detected)"]
        import_lines.extend(f"- {name}" for name in flags)
        self._set_text(self._imports_text, "\n".join(import_lines))
        self._status_var.set(f"Selected {page_name} [{details['dependency_class']}].")
