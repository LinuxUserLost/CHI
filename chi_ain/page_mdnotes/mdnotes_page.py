"""
page_mdnotes / mdnotes_page.py
────────────────────────────────────────────────────────────────────────────────
Markdown Notes — notes-first workspace for pychi/chi_ain.

Layout:
  left   — saved notes list + search
  center — YAML editor + full selected note review + draft input

Save root:
  /chi_ain/mdnotes/

This page intentionally focuses on note creation and review only.
Legacy prompt/map tooling is removed from the workspace.
"""

from __future__ import annotations

import os
import re
import glob
import json
import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import guichi
from gui_files import interaction_support


DEFAULT_SUBJECT_OPTIONS = [
    "general",
    "linux",
    "python",
    "networking",
    "ai",
    "project",
]

DEFAULT_NOTE_TYPE_OPTIONS = [
    "general_note",
    "class_note",
    "agent_handoff",
    "report",
    "linux_guide",
    "research_note",
]

DEFAULT_SOURCE_OPTIONS = [
    "manual",
    "upload",
    "agent_response",
    "builder_output",
    "mixed",
]

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
    "divider": "#3a3a3a",
}


def _bind_scroll(widget):
    interaction_support.bind_wheel_scroll(widget)


def _slugify(text, max_len=24):
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_")
    return s[:max_len] if s else "note"


def _make_note_filename(notes_dir, subject_slug):
    now = datetime.datetime.now()
    year = now.strftime("%Y")
    week = now.strftime("%W").zfill(2)
    prefix = f"{year}_wk{week}_{subject_slug}_"

    existing = []
    if os.path.isdir(notes_dir):
        for fname in os.listdir(notes_dir):
            if fname.startswith(prefix) and fname.endswith(".md"):
                num_part = fname[len(prefix):-3]
                try:
                    existing.append(int(num_part))
                except ValueError:
                    pass
    next_num = max(existing, default=0) + 1
    return f"{prefix}{str(next_num).zfill(6)}.md"


def _yaml_scalar(value):
    value = "" if value is None else str(value)
    if value == "":
        return '""'
    if any(ch in value for ch in (":", "#", "\n", '"', "'", "{", "}", "[", "]", ",", "&", "*", "!", "|", ">", "%", "@", "`")):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _build_yaml_frontmatter(fields):
    lines = ["---"]
    for key, val in fields.items():
        if key == "tags":
            if isinstance(val, str):
                val = [t.strip() for t in val.split(",") if t.strip()]
            if not val:
                lines.append("tags: []")
            else:
                lines.append("tags:")
                for tag in val:
                    lines.append(f"  - {tag}")
        else:
            lines.append(f"{key}: {_yaml_scalar(val)}")
    lines.append("---")
    return "\n".join(lines)


def _parse_yaml_frontmatter(text):
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    yaml_block = text[4:end].strip()
    body = text[end + 4:].lstrip("\n")

    fields = {}
    current_key = None
    current_list = None
    for line in yaml_block.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") and current_key and current_list is not None:
            current_list.append(stripped[2:].strip())
            continue
        if current_list is not None:
            fields[current_key] = current_list
            current_list = None
        if ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if not val:
                current_key = key
                current_list = []
            else:
                fields[key] = val
                current_key = key
    if current_list is not None:
        fields[current_key] = current_list
    return fields, body


def _parse_extra_metadata(text):
    result = {}
    errors = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if ":" not in line:
            errors.append(raw)
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            errors.append(raw)
            continue
        result[key] = value
    return result, errors


def _parse_metadata_rows(rows):
    result = {}
    errors = []
    for key_var, value_var in rows:
        key = key_var.get().strip()
        value = value_var.get().strip()
        if not key and not value:
            continue
        if not key:
            errors.append("(blank key)")
            continue
        result[key] = value
    return result, errors


def _format_note_meta(frontmatter):
    created = frontmatter.get("created_at", "")
    created_short = created[:10] if created else ""
    note_type = frontmatter.get("note_type", "")
    tags = frontmatter.get("tags", "")
    if isinstance(tags, list):
        tags = ", ".join(tags[:2])
    parts = [p for p in (created_short, note_type, tags) if p]
    return " · ".join(parts)


class PageMdNotes:
    PAGE_NAME = "markdown_notes"

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
        self._style_prefix = f"MdNotes.{id(self)}"
        self._style = None

        self.pack_root = ""
        self.notes_dir = ""
        self._note_history = []
        self._visible_notes = []
        self._selected_note = None
        self._left_panel_open = True
        self._custom_meta_rows = []

        self._subject_options = list(DEFAULT_SUBJECT_OPTIONS)
        self._note_type_options = list(DEFAULT_NOTE_TYPE_OPTIONS)
        self._source_options = list(DEFAULT_SOURCE_OPTIONS)

        self._status_var = tk.StringVar(value="Ready.")
        self._notes_dir_var = tk.StringVar(value="(not set)")
        self._search_var = tk.StringVar(value="")
        self._search_var.trace_add("write", lambda *_: self._apply_note_filter())
        self._recent_root_var = tk.StringVar(value="")

        self._yaml_title = tk.StringVar(value="")
        self._yaml_subject = tk.StringVar(value="general")
        self._yaml_note_type = tk.StringVar(value="general_note")
        self._yaml_source = tk.StringVar(value="manual")
        self._yaml_tags = tk.StringVar(value="")
        self._subject_new_var = tk.StringVar(value="")
        self._type_new_var = tk.StringVar(value="")
        self._source_new_var = tk.StringVar(value="")
        self._history_count_var = tk.StringVar(value="")

        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=0)
        self.frame.columnconfigure(1, weight=1)
        self.frame.rowconfigure(1, weight=1)

        self._build_top_bar()
        self._build_left_column()
        self._build_main_content()
        self._build_bottom_bar()
        self._apply_theme()

        self.frame.after(250, self._auto_find_root)

    def _embed_into_parent(self, parent=None):
        container = parent or self.parent
        try:
            if container is not None and self.frame.master is not container:
                self.frame.destroy()
                self.parent = container
                self.frame = ttk.Frame(container)
                self.frame.columnconfigure(0, weight=0)
                self.frame.columnconfigure(1, weight=1)
                self.frame.rowconfigure(1, weight=1)
                self._build_top_bar()
                self._build_left_column()
                self._build_main_content()
                self._build_bottom_bar()
                self._apply_theme()
                self.frame.after(50, self._auto_find_root)
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

    def _build_top_bar(self):
        self._top_bar = ttk.Frame(self.frame, padding=(6, 4))
        self._top_bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        self._top_bar.columnconfigure(3, weight=1)
        self._top_bar.columnconfigure(6, weight=1)

        ttk.Button(self._top_bar, text="Auto-Find", width=10, command=self._auto_find_root).grid(row=0, column=0, padx=(0, 4))
        self._top_toggle_btn = ttk.Button(self._top_bar, text="Hide Notes", width=11, command=self._toggle_saved_notes_panel)
        self._top_toggle_btn.grid(row=0, column=1, padx=(0, 8))
        ttk.Label(self._top_bar, text="Notes Root:").grid(row=0, column=2, padx=(0, 4), sticky="e")
        self._notes_path_entry = ttk.Entry(self._top_bar, textvariable=self._notes_dir_var, state="readonly")
        self._notes_path_entry.grid(row=0, column=3, sticky="ew", padx=(0, 4))
        ttk.Button(self._top_bar, text="…", width=2, command=self._choose_notes_root).grid(row=0, column=4, padx=(0, 6))
        ttk.Label(self._top_bar, text="Recent:").grid(row=0, column=5, padx=(0, 4), sticky="e")
        self._recent_root_cb = ttk.Combobox(self._top_bar, textvariable=self._recent_root_var, state="readonly", width=26)
        self._recent_root_cb.grid(row=0, column=6, padx=(0, 4), sticky="ew")
        self._recent_root_cb.bind("<<ComboboxSelected>>", self._on_recent_root_selected)
        ttk.Button(self._top_bar, text="Reload", width=8, command=self._reload_all).grid(row=0, column=7)
        self._refresh_recent_root_choices()

    def _build_left_column(self):
        self._left_rail = ttk.Frame(self.frame, padding=(2, 4))
        self._left_rail.grid(row=1, column=0, sticky="nsw", padx=(6, 0), pady=4)
        self._left_rail.columnconfigure(0, weight=1)

        self._left_toggle_btn = ttk.Button(
            self._left_rail,
            text="◀",
            width=3,
            command=self._toggle_saved_notes_panel,
        )
        self._left_toggle_btn.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self._left_count_rail_label = ttk.Label(self._left_rail, textvariable=self._history_count_var, anchor="n", justify="center", wraplength=44)
        self._left_count_rail_label.grid(row=1, column=0, sticky="new")

        self._left_outer = ttk.LabelFrame(self.frame, text="Saved Notes", padding=(6, 4))
        self._left_outer.grid(row=1, column=0, sticky="nsew", padx=(6, 3), pady=4)
        self._left_outer.columnconfigure(0, weight=1)
        self._left_outer.rowconfigure(1, weight=1)

        self._left_search = ttk.Entry(self._left_outer, textvariable=self._search_var)
        self._left_search.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        list_frame = ttk.Frame(self._left_outer)
        list_frame.grid(row=1, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self._notes_list = tk.Listbox(list_frame, width=34, activestyle="none", exportselection=False)
        self._notes_list.grid(row=0, column=0, sticky="nsew")
        list_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self._notes_list.yview)
        list_scroll.grid(row=0, column=1, sticky="ns")
        self._notes_list.configure(yscrollcommand=list_scroll.set)
        interaction_support.setup_listbox_widget(self._notes_list)
        self._notes_list.bind("<<ListboxSelect>>", self._on_note_select)

        self._left_count_label = ttk.Label(self._left_outer, textvariable=self._history_count_var)
        self._left_count_label.grid(row=2, column=0, sticky="e", pady=(4, 0))
        self._apply_left_panel_visibility()

    def _build_main_content(self):
        self._main = ttk.Frame(self.frame, padding=(3, 0, 6, 0))
        self._main.grid(row=1, column=1, sticky="nsew", pady=4)
        self._main.columnconfigure(0, weight=1)
        self._main.rowconfigure(1, weight=1)
        self._main.rowconfigure(2, weight=1)
        self._main.rowconfigure(3, weight=0)

        self._build_yaml_header(self._main)
        self._build_review_panel(self._main)
        self._build_input_panel(self._main)
        self._build_action_row(self._main)

    def _build_yaml_header(self, parent):
        self._yaml_outer = ttk.LabelFrame(parent, text="Note Header (YAML)", padding=(6, 4))
        self._yaml_outer.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self._yaml_outer.columnconfigure(1, weight=1)
        self._yaml_outer.columnconfigure(3, weight=1)

        ttk.Label(self._yaml_outer, text="Title:").grid(row=0, column=0, sticky="e", padx=(0, 4), pady=1)
        ttk.Entry(self._yaml_outer, textvariable=self._yaml_title).grid(row=0, column=1, columnspan=3, sticky="ew", pady=1)

        self._subject_row = ttk.Frame(self._yaml_outer)
        self._subject_row.grid(row=1, column=0, columnspan=4, sticky="ew", pady=1)
        ttk.Label(self._subject_row, text="Subject:", width=8, anchor="e").pack(side="left", padx=(0, 4))
        self._subject_cb = ttk.Combobox(self._subject_row, textvariable=self._yaml_subject, values=self._subject_options, state="readonly", width=14)
        self._subject_cb.pack(side="left", padx=(0, 6))
        ttk.Entry(self._subject_row, textvariable=self._subject_new_var, width=12).pack(side="left", padx=(0, 2))
        ttk.Button(self._subject_row, text="+", width=2, command=self._add_subject).pack(side="left", padx=(0, 12))
        ttk.Label(self._subject_row, text="Type:").pack(side="left", padx=(0, 4))
        self._note_type_cb = ttk.Combobox(self._subject_row, textvariable=self._yaml_note_type, values=self._note_type_options, state="readonly", width=14)
        self._note_type_cb.pack(side="left", padx=(0, 6))
        ttk.Entry(self._subject_row, textvariable=self._type_new_var, width=12).pack(side="left", padx=(0, 2))
        ttk.Button(self._subject_row, text="+", width=2, command=self._add_note_type).pack(side="left")

        self._source_row = ttk.Frame(self._yaml_outer)
        self._source_row.grid(row=2, column=0, columnspan=4, sticky="ew", pady=1)
        ttk.Label(self._source_row, text="Source:", width=8, anchor="e").pack(side="left", padx=(0, 4))
        self._source_cb = ttk.Combobox(self._source_row, textvariable=self._yaml_source, values=self._source_options, state="readonly", width=14)
        self._source_cb.pack(side="left", padx=(0, 6))
        ttk.Entry(self._source_row, textvariable=self._source_new_var, width=12).pack(side="left", padx=(0, 2))
        ttk.Button(self._source_row, text="+", width=2, command=self._add_source).pack(side="left", padx=(0, 12))
        ttk.Label(self._source_row, text="Tags:").pack(side="left", padx=(0, 4))
        ttk.Entry(self._source_row, textvariable=self._yaml_tags, width=24).pack(side="left", fill="x", expand=True)

        extra_frame = ttk.Frame(self._yaml_outer)
        extra_frame.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        extra_frame.columnconfigure(1, weight=1)
        ttk.Label(extra_frame, text="Custom Fields:", width=10, anchor="e").grid(row=0, column=0, padx=(0, 4), sticky="ne")
        self._custom_meta_outer = ttk.Frame(extra_frame)
        self._custom_meta_outer.grid(row=0, column=1, sticky="ew")
        self._custom_meta_outer.columnconfigure(0, weight=1)
        self._custom_meta_hint = ttk.Label(extra_frame, text="Add key/value metadata rows. Raw YAML remains review-only.")
        self._custom_meta_hint.grid(row=1, column=1, sticky="w", pady=(2, 0))
        self._add_meta_btn = ttk.Button(extra_frame, text="+ Add field", width=10, command=self._add_custom_meta_row)
        self._add_meta_btn.grid(row=0, column=2, padx=(6, 0), sticky="ne")
        self._rebuild_custom_meta_rows()

    def _build_review_panel(self, parent):
        self._review_outer = ttk.LabelFrame(parent, text="Selected Note Review", padding=(6, 4))
        self._review_outer.grid(row=1, column=0, sticky="nsew", pady=(0, 4))
        self._review_outer.columnconfigure(0, weight=1)
        self._review_outer.rowconfigure(0, weight=1)

        self._review_txt = tk.Text(
            self._review_outer,
            wrap="word",
            state="disabled",
            font=("Monospace", 10),
            relief="flat",
            borderwidth=1,
            padx=8,
            pady=6,
        )
        self._review_txt.grid(row=0, column=0, sticky="nsew")
        review_scroll = ttk.Scrollbar(self._review_outer, orient="vertical", command=self._review_txt.yview)
        review_scroll.grid(row=0, column=1, sticky="ns")
        self._review_txt.configure(yscrollcommand=review_scroll.set)
        interaction_support.setup_text_widget(self._review_txt)

    def _build_input_panel(self, parent):
        self._input_outer = ttk.LabelFrame(parent, text="New Note Draft", padding=(6, 4))
        self._input_outer.grid(row=2, column=0, sticky="nsew", pady=(0, 4))
        self._input_outer.columnconfigure(0, weight=1)
        self._input_outer.rowconfigure(0, weight=1)

        self._input_txt = tk.Text(
            self._input_outer,
            wrap="word",
            height=8,
            undo=True,
            font=("", 11),
            relief="flat",
            borderwidth=1,
            padx=8,
            pady=6,
            insertwidth=2,
        )
        self._input_txt.grid(row=0, column=0, sticky="nsew")
        input_scroll = ttk.Scrollbar(self._input_outer, orient="vertical", command=self._input_txt.yview)
        input_scroll.grid(row=0, column=1, sticky="ns")
        self._input_txt.configure(yscrollcommand=input_scroll.set)
        interaction_support.setup_text_widget(self._input_txt)

    def _build_action_row(self, parent):
        self._action_row = ttk.Frame(parent, padding=(0, 2))
        self._action_row.grid(row=3, column=0, sticky="ew")
        self._action_row.columnconfigure(10, weight=1)

        ttk.Button(self._action_row, text="Submit Note", width=12, command=self._submit_note).grid(row=0, column=0, padx=(0, 4))
        ttk.Button(self._action_row, text="Copy Input", width=10, command=self._copy_input).grid(row=0, column=1, padx=(0, 4))
        ttk.Button(self._action_row, text="Clear Input", width=10, command=self._clear_input).grid(row=0, column=2, padx=(0, 4))
        ttk.Button(self._action_row, text="Upload File…", width=12, command=self._upload_file).grid(row=0, column=3, padx=(0, 4))

    def _build_bottom_bar(self):
        self._bottom_bar = ttk.Frame(self.frame, padding=(6, 2))
        self._bottom_bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        self._bottom_bar.columnconfigure(0, weight=1)
        self._status_label = ttk.Label(self._bottom_bar, textvariable=self._status_var, anchor="w")
        self._status_label.grid(row=0, column=0, sticky="ew")

    def _add_subject(self):
        new = self._subject_new_var.get().strip()
        if not new:
            return
        slug = _slugify(new)
        if slug and slug not in self._subject_options:
            self._subject_options.append(slug)
            self._subject_cb.configure(values=self._subject_options)
        self._yaml_subject.set(slug)
        self._subject_new_var.set("")
        self._set_status(f"Subject added: {slug}")

    def _add_note_type(self):
        new = self._type_new_var.get().strip()
        if not new:
            return
        slug = _slugify(new)
        if slug and slug not in self._note_type_options:
            self._note_type_options.append(slug)
            self._note_type_cb.configure(values=self._note_type_options)
        self._yaml_note_type.set(slug)
        self._type_new_var.set("")
        self._set_status(f"Note type added: {slug}")

    def _add_source(self):
        new = self._source_new_var.get().strip()
        if not new:
            return
        slug = _slugify(new)
        if slug and slug not in self._source_options:
            self._source_options.append(slug)
            self._source_cb.configure(values=self._source_options)
        self._yaml_source.set(slug)
        self._source_new_var.set("")
        self._set_status(f"Source added: {slug}")

    def _add_custom_meta_row(self, key="", value=""):
        key_var = tk.StringVar(value=key)
        value_var = tk.StringVar(value=value)
        self._custom_meta_rows.append((key_var, value_var))
        self._rebuild_custom_meta_rows()

    def _remove_custom_meta_row(self, row_index):
        if 0 <= row_index < len(self._custom_meta_rows):
            self._custom_meta_rows.pop(row_index)
            self._rebuild_custom_meta_rows()

    def _rebuild_custom_meta_rows(self):
        for child in self._custom_meta_outer.winfo_children():
            child.destroy()
        if not self._custom_meta_rows:
            empty = ttk.Label(self._custom_meta_outer, text="(no custom fields)")
            empty.grid(row=0, column=0, sticky="w")
            self._apply_ttk_theme_tree(self._custom_meta_outer)
            return

        for row_index, (key_var, value_var) in enumerate(self._custom_meta_rows):
            row = ttk.Frame(self._custom_meta_outer)
            row.grid(row=row_index, column=0, sticky="ew", pady=1)
            row.columnconfigure(1, weight=1)
            ttk.Entry(row, textvariable=key_var, width=18).grid(row=0, column=0, padx=(0, 4), sticky="ew")
            ttk.Entry(row, textvariable=value_var).grid(row=0, column=1, padx=(0, 4), sticky="ew")
            ttk.Button(row, text="✕", width=2, command=lambda i=row_index: self._remove_custom_meta_row(i)).grid(row=0, column=2)
        self._apply_ttk_theme_tree(self._custom_meta_outer)

    def _submit_note(self):
        body = self._input_txt.get("1.0", "end-1c").strip()
        if not body:
            self._set_status("Nothing to submit — type in the draft box first.")
            return
        if not self.notes_dir:
            messagebox.showwarning("Submit Note", "No notes root is set.")
            return

        os.makedirs(self.notes_dir, exist_ok=True)
        now = datetime.datetime.now()
        subject = self._yaml_subject.get().strip() or "note"
        slug = _slugify(subject)

        existing_nums = []
        for fname in os.listdir(self.notes_dir):
            if fname.endswith(".md"):
                parts = fname[:-3].rsplit("_", 1)
                if len(parts) == 2:
                    try:
                        existing_nums.append(int(parts[1]))
                    except ValueError:
                        pass
        log_number = max(existing_nums, default=0) + 1

        frontmatter = {
            "title": self._yaml_title.get().strip() or "Untitled Note",
            "subject": subject,
            "log_number": log_number,
            "created_at": now.isoformat(timespec="seconds"),
            "updated_at": now.isoformat(timespec="seconds"),
            "note_type": self._yaml_note_type.get(),
            "tags": self._yaml_tags.get(),
            "source": self._yaml_source.get(),
        }

        extra_meta, extra_errors = _parse_metadata_rows(self._custom_meta_rows)
        if extra_errors:
            self._set_status("Custom metadata ignored for invalid row(s) with blank keys.")
        ignored_keys = []
        for key, value in extra_meta.items():
            if key not in frontmatter:
                frontmatter[key] = value
            else:
                ignored_keys.append(key)

        fname = _make_note_filename(self.notes_dir, slug)
        fpath = os.path.join(self.notes_dir, fname)
        full_content = _build_yaml_frontmatter(frontmatter) + "\n\n" + body + "\n"

        try:
            with open(fpath, "w", encoding="utf-8") as fh:
                fh.write(full_content)
            if ignored_keys:
                self._set_status(f"Submitted: {fname}  |  ignored custom keys: {', '.join(ignored_keys)}")
            else:
                self._set_status(f"Submitted: {fname}")
            self._refresh_note_history(select_path=fpath)
        except Exception as exc:
            messagebox.showerror("Save Error", f"Failed to save note:\n{exc}")

    def _upload_file(self):
        fpath = filedialog.askopenfilename(
            title="Upload File",
            filetypes=[("Text/Markdown", "*.txt *.md *.log"), ("All files", "*.*")],
        )
        if not fpath:
            return
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except Exception as exc:
            messagebox.showerror("Read Error", str(exc))
            return

        self._input_txt.delete("1.0", "end")
        self._input_txt.insert("1.0", content)
        self._yaml_source.set("upload")
        if not self._yaml_title.get().strip():
            self._yaml_title.set(os.path.basename(fpath))
        self._set_status(f"Loaded file: {os.path.basename(fpath)} — draft updated.")

    def _copy_input(self):
        text = self._input_txt.get("1.0", "end-1c").strip()
        if not text:
            self._set_status("Nothing to copy.")
            return
        try:
            self.frame.clipboard_clear()
            self.frame.clipboard_append(text)
            self._set_status(f"Copied {len(text)} chars to clipboard.")
        except Exception as exc:
            self._set_status(f"Clipboard error: {exc}")

    def _clear_input(self):
        self._input_txt.delete("1.0", "end")
        self._set_status("Draft input cleared.")

    def _refresh_note_history(self, select_path=None):
        self._note_history = []
        if not self.notes_dir or not os.path.isdir(self.notes_dir):
            self._apply_note_filter()
            return

        md_files = sorted(
            glob.glob(os.path.join(self.notes_dir, "*.md")),
            key=os.path.getmtime,
            reverse=True,
        )

        for fpath in md_files:
            try:
                with open(fpath, "r", encoding="utf-8") as fh:
                    raw_text = fh.read()
                frontmatter, body = _parse_yaml_frontmatter(raw_text)
                self._note_history.append({
                    "path": fpath,
                    "filename": os.path.basename(fpath),
                    "frontmatter": frontmatter,
                    "body": body,
                    "raw": raw_text,
                    "title": frontmatter.get("title", os.path.basename(fpath)),
                    "meta": _format_note_meta(frontmatter),
                })
            except Exception:
                self._note_history.append({
                    "path": fpath,
                    "filename": os.path.basename(fpath),
                    "frontmatter": {},
                    "body": "",
                    "raw": "(read error)",
                    "title": os.path.basename(fpath),
                    "meta": "(read error)",
                })

        self._apply_note_filter(select_path=select_path)

    def _apply_note_filter(self, *_, select_path=None):
        query = self._search_var.get().strip().lower()
        self._visible_notes = []
        for note in self._note_history:
            haystack = " ".join([
                note.get("title", ""),
                note.get("filename", ""),
                note.get("meta", ""),
                note.get("frontmatter", {}).get("subject", ""),
            ]).lower()
            if query and query not in haystack:
                continue
            self._visible_notes.append(note)
        self._render_note_list(select_path=select_path)

    def _render_note_list(self, select_path=None):
        self._notes_list.delete(0, "end")
        for note in self._visible_notes:
            row = note["title"]
            if note["meta"]:
                row += f" — {note['meta']}"
            self._notes_list.insert("end", row)

        if not self._visible_notes:
            self._history_count_var.set("0 note(s)")
            self._render_review_text("(no notes match the current filter)")
            self._selected_note = None
            return

        visible = len(self._visible_notes)
        total = len(self._note_history)
        if visible == total:
            self._history_count_var.set(f"{visible} note(s)")
        else:
            self._history_count_var.set(f"{visible}/{total} note(s)")
        select_index = 0
        if select_path:
            for idx, note in enumerate(self._visible_notes):
                if note["path"] == select_path:
                    select_index = idx
                    break
        elif self._selected_note is not None:
            for idx, note in enumerate(self._visible_notes):
                if note["path"] == self._selected_note["path"]:
                    select_index = idx
                    break
        self._notes_list.selection_clear(0, "end")
        self._notes_list.selection_set(select_index)
        self._notes_list.see(select_index)
        self._show_selected_index(select_index)

    def _on_note_select(self, event=None):
        sel = self._notes_list.curselection()
        if not sel:
            return
        self._show_selected_index(sel[0])

    def _show_selected_index(self, index):
        if index < 0 or index >= len(self._visible_notes):
            return
        note = self._visible_notes[index]
        self._selected_note = note
        self._render_review_text(note["raw"])
        self._set_status(f"Reviewing: {note['filename']}")

    def _render_review_text(self, text):
        self._review_txt.configure(state="normal")
        self._review_txt.delete("1.0", "end")
        self._review_txt.insert("1.0", text)
        self._review_txt.configure(state="disabled")

    def _build_empty_review(self):
        self._render_review_text("(select a note to review it here)")

    def _build_empty_draft(self):
        self._input_txt.delete("1.0", "end")

    def _toggle_saved_notes_panel(self):
        self._left_panel_open = not self._left_panel_open
        self._apply_left_panel_visibility()

    def _apply_left_panel_visibility(self):
        if self._left_panel_open:
            self._left_rail.grid_remove()
            self._left_outer.grid()
            self._left_toggle_btn.configure(text="◀")
            self._top_toggle_btn.configure(text="Hide Notes")
        else:
            self._left_outer.grid_remove()
            self._left_rail.grid()
            self._left_toggle_btn.configure(text="▶")
            self._top_toggle_btn.configure(text="Show Notes")

    def _set_status(self, msg):
        self._status_var.set(msg)

    def _auto_find_root(self):
        local_pack_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        local_notes_dir = os.path.join(local_pack_root, "mdnotes")
        if os.path.isdir(local_notes_dir):
            self._apply_notes_dir(local_notes_dir, remember=True)
            self._set_status(f"Auto-found local notes root: {local_notes_dir}")
            return
        self._set_status("Local chi_ain/mdnotes root not found — choose a notes root manually.")

    def _choose_notes_root(self):
        initial_dir = self.notes_dir or self._get_shell_config().get("last_selected_root") or os.path.dirname(os.path.abspath(__file__))
        d = filedialog.askdirectory(title="Select Notes Save Directory", initialdir=initial_dir)
        if d:
            self._apply_notes_dir(d, remember=True)
            self._set_status(f"Manual notes root set: {self.notes_dir}")

    def _set_root(self, pack_path):
        self.pack_root = pack_path
        self._apply_notes_dir(os.path.join(pack_path, "mdnotes"), remember=True)

    def _get_shell_config(self):
        if self.app is not None and hasattr(self.app, "config") and isinstance(self.app.config, dict):
            return self.app.config
        return guichi.load_config()

    def _save_shell_config(self, config):
        if self.app is not None and hasattr(self.app, "config") and isinstance(self.app.config, dict):
            self.app.config.update(config)
        guichi.save_config(config)

    def _resolve_recent_notes_dir(self, candidate):
        if not candidate:
            return None
        candidate = os.path.abspath(candidate)
        if os.path.basename(candidate) == "mdnotes":
            return candidate
        nested = os.path.join(candidate, "mdnotes")
        if os.path.isdir(nested):
            return nested
        if os.path.isdir(candidate):
            return candidate
        return None

    def _collect_recent_note_roots(self):
        config = self._get_shell_config()
        seen = set()
        options = []
        for raw in [self.notes_dir, config.get("last_selected_root"), *(config.get("known_roots") or [])]:
            notes_dir = self._resolve_recent_notes_dir(raw)
            if not notes_dir or notes_dir in seen:
                continue
            seen.add(notes_dir)
            options.append(notes_dir)
        return options

    def _refresh_recent_root_choices(self):
        options = self._collect_recent_note_roots()
        if hasattr(self, "_recent_root_cb"):
            self._recent_root_cb.configure(values=options)
        if self.notes_dir and self.notes_dir in options:
            self._recent_root_var.set(self.notes_dir)
        elif options:
            self._recent_root_var.set(options[0])
        else:
            self._recent_root_var.set("")

    def _remember_notes_root(self, notes_dir):
        config = self._get_shell_config()
        known = list(config.get("known_roots") or [])
        if notes_dir not in known:
            known.append(notes_dir)
        config["known_roots"] = known
        self._save_shell_config(config)
        self._refresh_recent_root_choices()

    def _apply_notes_dir(self, notes_dir, remember=False):
        normalized = self._resolve_recent_notes_dir(notes_dir)
        if normalized is None:
            self._set_status(f"Invalid notes root: {notes_dir}")
            return False
        self.notes_dir = normalized
        if os.path.basename(normalized) == "mdnotes":
            self.pack_root = os.path.dirname(normalized)
        else:
            self.pack_root = ""
        os.makedirs(self.notes_dir, exist_ok=True)
        self._notes_dir_var.set(self.notes_dir)
        if remember:
            self._remember_notes_root(self.notes_dir)
        self._reload_all()
        return True

    def _on_recent_root_selected(self, event=None):
        candidate = self._recent_root_var.get().strip()
        if not candidate:
            return
        resolved = self._resolve_recent_notes_dir(candidate)
        if not resolved or not os.path.isdir(resolved):
            self._set_status("Selected recent notes root is unavailable — choose one manually.")
            return
        if self._apply_notes_dir(resolved, remember=False):
            self._set_status(f"Recent notes root applied: {self.notes_dir}")

    def _reload_all(self):
        self._refresh_note_history()
        self._build_empty_draft()
        if not self._note_history:
            self._build_empty_review()

    def _apply_theme(self):
        tokens = self._theme_tokens
        try:
            self._style = ttk.Style(self.frame)
            self._style.configure(f"{self._style_prefix}.TFrame", background=tokens["content_bg"])
            self._style.configure(f"{self._style_prefix}.Panel.TFrame", background=tokens["panel_bg"])
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
            self._style.configure(f"{self._style_prefix}.TLabel", background=tokens["content_bg"], foreground=tokens["text_main"])
            self._style.configure(f"{self._style_prefix}.Muted.TLabel", background=tokens["content_bg"], foreground=tokens["text_muted"])
            self._style.configure(
                f"{self._style_prefix}.TButton",
                background=tokens["button_bg"],
                foreground=tokens["text_main"],
            )
            self._style.map(
                f"{self._style_prefix}.TButton",
                background=[("active", tokens["button_hover"])],
                foreground=[("active", tokens["text_active"]), ("disabled", tokens["button_disabled"])],
            )
            self._style.configure(
                f"{self._style_prefix}.TEntry",
                fieldbackground=tokens["panel_bg"],
                foreground=tokens["text_main"],
            )
            self._style.configure(
                f"{self._style_prefix}.TCombobox",
                fieldbackground=tokens["panel_bg"],
                foreground=tokens["text_main"],
                background=tokens["button_bg"],
                arrowcolor=tokens["text_main"],
            )
            self._style.map(
                f"{self._style_prefix}.TCombobox",
                fieldbackground=[("readonly", tokens["panel_bg"])],
                selectbackground=[("readonly", tokens["accent"])],
                selectforeground=[("readonly", tokens["text_on_accent"])],
            )
        except Exception:
            pass

        try:
            self.frame.configure(style=f"{self._style_prefix}.TFrame")
        except Exception:
            pass
        self._apply_ttk_theme_tree(self.frame)

        for widget in (self._notes_list,):
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

        for widget in (self._review_txt, self._input_txt):
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

        try:
            self._status_label.configure(style=f"{self._style_prefix}.Muted.TLabel")
            self._left_count_label.configure(style=f"{self._style_prefix}.Muted.TLabel")
            self._left_count_rail_label.configure(style=f"{self._style_prefix}.Muted.TLabel")
            self._custom_meta_hint.configure(style=f"{self._style_prefix}.Muted.TLabel")
        except Exception:
            pass

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
                    child.configure(style=f"{self._style_prefix}.TLabel")
                elif isinstance(child, ttk.Frame):
                    child.configure(style=f"{self._style_prefix}.TFrame")
            except Exception:
                pass
            self._apply_ttk_theme_tree(child)
