"""
Read-only viewer for 03_project_plans notes with lightweight planning hooks.

This v1 page is intentionally not an editor.
It is meant to make existing Markdown + YAML planning notes usable in pychi.
"""

from __future__ import annotations

import os
import re
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from gui_files import interaction_support


_DEFAULT_PAGE_THEME = {
    "content_bg": "#1e1e1e",
    "panel_bg": "#2b2b2b",
    "sidebar_bg": "#242424",
    "text_main": "#dddddd",
    "text_muted": "#8f8f8f",
    "text_active": "#ffffff",
    "text_on_accent": "#ffffff",
    "accent": "#4ea0ff",
    "border": "#4a4a4a",
}

_HOOK_HEADINGS = (
    "Current Direction",
    "Why It Matters Now",
    "Open Questions",
    "Next Safe Step",
    "Current Active Notes",
)


def _bind_scroll(widget):
    interaction_support.bind_wheel_scroll(widget)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _find_portable_root(start: Path) -> Path | None:
    for candidate in [start, *start.parents]:
        if (candidate / "03_project_plans").is_dir():
            return candidate
    return None


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    block = text[4:end].strip()
    body = text[end + 4 :].lstrip("\n")
    fields = {}
    current_key = None
    current_list = None
    for raw in block.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if current_key and current_list is not None and stripped.startswith("- "):
            current_list.append(stripped[2:].strip().strip('"').strip("'"))
            continue
        if current_key and current_list is not None:
            fields[current_key] = current_list
            current_key = None
            current_list = None
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        if not value:
            current_key = key
            current_list = []
        else:
            fields[key] = value.strip('"').strip("'")
    if current_key and current_list is not None:
        fields[current_key] = current_list
    return fields, body


def _extract_section(body: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(body)
    if not match:
        return ""
    start = match.end()
    rest = body[start:]
    next_heading = re.search(r"^##\s+", rest, re.MULTILINE)
    section = rest[: next_heading.start()] if next_heading else rest
    return section.strip()


def _extract_wikilinks(text: str) -> list[str]:
    return sorted(set(re.findall(r"\[\[([^\]]+)\]\]", text)))


class PageProjectPlansViewer:
    PAGE_NAME = "project_plans_viewer"

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
        self._style_prefix = f"ProjectPlansViewer.{id(self)}"
        self._status_var = tk.StringVar(value="Ready.")
        self._note_cache = {}
        self._plans_root = None
        self._selected_note = None

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
        self.refresh_notes()
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

        ttk.Label(header, text="03 Project Plans Viewer", style=f"{self._style_prefix}.Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Browse cleaned project-plan notes, frontmatter, and phase/build-cycle hooks without leaving pychi.",
            style=f"{self._style_prefix}.Muted.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
        ttk.Button(header, text="Refresh", command=self.refresh_notes).grid(row=0, column=1, rowspan=2, sticky="e")

        body = ttk.PanedWindow(self.frame, orient="horizontal")
        body.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.frame.rowconfigure(1, weight=1)

        left = ttk.Frame(body, padding=(0, 0, 8, 0))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        body.add(left, weight=1)

        ttk.Label(left, text="Projects / Notes", style=f"{self._style_prefix}.PanelHeader.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self._tree = ttk.Treeview(left, show="tree", selectmode="browse")
        self._tree.grid(row=1, column=0, sticky="nsew")
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        _bind_scroll(self._tree)

        right = ttk.Notebook(body)
        body.add(right, weight=3)

        overview = ttk.Frame(right, padding=10)
        overview.columnconfigure(0, weight=1)
        overview.rowconfigure(2, weight=1)
        right.add(overview, text="Note")
        self._detail_title = ttk.Label(overview, text="Select a note", style=f"{self._style_prefix}.Header.TLabel")
        self._detail_title.grid(row=0, column=0, sticky="w")
        self._detail_meta = ttk.Label(overview, text="", style=f"{self._style_prefix}.Muted.TLabel", wraplength=760, justify="left")
        self._detail_meta.grid(row=1, column=0, sticky="w", pady=(4, 8))
        self._detail_body = tk.Text(overview, wrap="word", state="disabled", relief="flat", borderwidth=0)
        self._detail_body.grid(row=2, column=0, sticky="nsew")
        _bind_scroll(self._detail_body)

        hooks = ttk.Frame(right, padding=10)
        hooks.columnconfigure(0, weight=1)
        hooks.rowconfigure(0, weight=1)
        right.add(hooks, text="Planning Hooks")
        self._hooks_text = tk.Text(hooks, wrap="word", state="disabled", relief="flat", borderwidth=0)
        self._hooks_text.grid(row=0, column=0, sticky="nsew")
        _bind_scroll(self._hooks_text)

        raw_tab = ttk.Frame(right, padding=10)
        raw_tab.columnconfigure(0, weight=1)
        raw_tab.rowconfigure(0, weight=1)
        right.add(raw_tab, text="Raw")
        self._raw_text = tk.Text(raw_tab, wrap="none", state="disabled", relief="flat", borderwidth=0)
        self._raw_text.grid(row=0, column=0, sticky="nsew")
        _bind_scroll(self._raw_text)

        ttk.Label(self.frame, textvariable=self._status_var, style=f"{self._style_prefix}.Muted.TLabel").grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))

    def _apply_page_theme(self):
        tokens = self._theme_tokens
        try:
            style = ttk.Style(self.frame)
            style.configure(f"{self._style_prefix}.TFrame", background=tokens["content_bg"])
            style.configure(f"{self._style_prefix}.Header.TLabel", background=tokens["content_bg"], foreground=tokens["text_main"], font=("TkDefaultFont", 14, "bold"))
            style.configure(f"{self._style_prefix}.PanelHeader.TLabel", background=tokens["content_bg"], foreground=tokens["text_main"], font=("TkDefaultFont", 11, "bold"))
            style.configure(f"{self._style_prefix}.Muted.TLabel", background=tokens["content_bg"], foreground=tokens["text_muted"])
        except Exception:
            pass
        for text_widget in (getattr(self, "_detail_body", None), getattr(self, "_hooks_text", None), getattr(self, "_raw_text", None)):
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

    def refresh_notes(self):
        start = Path(__file__).resolve()
        portable_root = _find_portable_root(start)
        if portable_root is None:
            self._status_var.set("Could not locate portable root with 03_project_plans.")
            return
        self._plans_root = portable_root / "03_project_plans"
        self._note_cache.clear()
        self._populate_tree()
        self._status_var.set(f"Loaded notes from {self._plans_root}.")

    def _populate_tree(self):
        tree = self._tree
        tree.delete(*tree.get_children())
        if self._plans_root is None:
            return
        for project_dir in sorted(p for p in self._plans_root.iterdir() if p.is_dir()):
            project_node = tree.insert("", "end", iid=str(project_dir), text=project_dir.name)
            note_paths = sorted(project_dir.rglob("*.md"))
            for note_path in note_paths:
                rel = note_path.relative_to(project_dir)
                tree.insert(project_node, "end", iid=str(note_path), text=str(rel))
            if note_paths:
                tree.item(project_node, open=True)

    def _on_tree_select(self, _event=None):
        selection = self._tree.selection()
        if not selection:
            return
        selected = Path(selection[0])
        if not selected.is_file():
            return
        self._selected_note = selected
        self._render_note(selected)

    def _set_text(self, widget: tk.Text, content: str):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content.strip() + "\n")
        widget.configure(state="disabled")

    def _render_note(self, note_path: Path):
        raw = _read_text(note_path)
        frontmatter, body = _parse_frontmatter(raw)
        title = frontmatter.get("title") or note_path.stem
        self._detail_title.configure(text=title)
        tags = frontmatter.get("tags", [])
        if isinstance(tags, list):
            tags_text = ", ".join(tags)
        else:
            tags_text = str(tags)
        meta = [
            f"type: {frontmatter.get('type', '(none)')}",
            f"status: {frontmatter.get('status', '(none)')}",
            f"project: {frontmatter.get('project', '(none)')}",
            f"confidence: {frontmatter.get('confidence', '(none)')}",
            f"discussion_count: {frontmatter.get('discussion_count', '(none)')}",
        ]
        if tags_text:
            meta.append(f"tags: {tags_text}")
        self._detail_meta.configure(text="   ".join(meta))
        self._set_text(self._detail_body, body or "(empty note body)")

        hooks = []
        for heading in _HOOK_HEADINGS:
            section = _extract_section(body, heading)
            if section:
                hooks.append(f"{heading}\n{'-' * len(heading)}\n{section}")
        links = _extract_wikilinks(raw)
        if links:
            hooks.append("Related Notes\n-------------\n" + "\n".join(f"- [[{name}]]" for name in links))
        if not hooks:
            hooks = ["No explicit planning hooks detected yet."]
        self._set_text(self._hooks_text, "\n\n".join(hooks))

        raw_lines = []
        if frontmatter:
            raw_lines.append("Frontmatter")
            raw_lines.append("-----------")
            for key, value in frontmatter.items():
                raw_lines.append(f"{key}: {value}")
            raw_lines.append("")
        raw_lines.append(f"File: {note_path}")
        raw_lines.append("")
        raw_lines.append("Raw markdown")
        raw_lines.append("------------")
        raw_lines.append(raw or "(empty file)")
        self._set_text(self._raw_text, "\n".join(raw_lines))
        self._status_var.set(f"Viewing {note_path.name}.")
