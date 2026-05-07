"""
Read-only bridge between pychi build-history logs and project-plan notes.
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

_OPTIONAL_LINK_FIELDS = (
    "project",
    "topic",
    "pack_ids",
    "page_ids",
    "related_notes",
    "related_event_ids",
    "decision_type",
    "implementation_scope",
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
        if (candidate / "01_project_workshop" / "00_pychi_build_history").is_dir():
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
            cleaned = value.strip('"').strip("'")
            if cleaned.lower() in {"true", "false"}:
                fields[key] = cleaned.lower() == "true"
            else:
                fields[key] = cleaned
    if current_key and current_list is not None:
        fields[current_key] = current_list
    return fields, body


def _stem_from_event_id(event_id: str, fallback_path: Path) -> str:
    if event_id:
        return event_id
    name = fallback_path.name
    if name.endswith("_rawuser.md"):
        return name[:-11]
    if name.endswith("_machinedata.md"):
        return name[:-15]
    return fallback_path.stem


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if "," in text:
        return [part.strip() for part in text.split(",") if part.strip()]
    return [text]


def _extract_page_ids(text: str) -> list[str]:
    if not text:
        return []
    return sorted(set(re.findall(r"\bpage_[a-z0-9_]+\b", text)))


def _slug_tokens(text: str) -> set[str]:
    parts = re.split(r"[^a-z0-9]+", text.lower())
    return {part for part in parts if len(part) >= 3}


class PageBuildHistoryViewer:
    PAGE_NAME = "build_history_viewer"

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
        self._style_prefix = f"BuildHistoryViewer.{id(self)}"

        self._root_path = None
        self._history_root = None
        self._plans_root = None
        self._events = []
        self._notes = []
        self._event_by_id = {}
        self._selected_event = None

        self._filter_var = tk.StringVar(value="")
        self._status_var = tk.StringVar(value="Ready.")

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
        self.refresh_history()
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
        header.columnconfigure(3, weight=1)
        self._header = header

        ttk.Label(
            header,
            text="Build History Bridge",
            style=f"{self._style_prefix}.Header.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Entry(header, textvariable=self._filter_var).grid(row=0, column=1, sticky="ew", padx=(10, 6))
        self._filter_var.trace_add("write", lambda *_: self._populate_event_list())
        ttk.Button(header, text="Refresh", command=self.refresh_history).grid(row=0, column=2, sticky="e")
        ttk.Label(
            header,
            text="Bridge raw user logs, machine audit logs, and related project-plan notes.",
            style=f"{self._style_prefix}.Muted.TLabel",
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))

        body = ttk.PanedWindow(self.frame, orient="horizontal")
        body.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.frame.rowconfigure(1, weight=1)

        left = ttk.Frame(body, padding=(0, 0, 8, 0))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        body.add(left, weight=1)

        ttk.Label(left, text="Events", style=f"{self._style_prefix}.PanelHeader.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self._event_list = tk.Listbox(left, exportselection=False, font=("monospace", 9))
        self._event_list.grid(row=1, column=0, sticky="nsew")
        self._event_list.bind("<<ListboxSelect>>", self._on_event_select)
        _bind_scroll(self._event_list)

        right = ttk.Notebook(body)
        body.add(right, weight=3)

        summary = ttk.Frame(right, padding=10)
        summary.columnconfigure(0, weight=1)
        summary.rowconfigure(2, weight=1)
        right.add(summary, text="Summary")
        self._summary_title = ttk.Label(summary, text="Select an event", style=f"{self._style_prefix}.Header.TLabel")
        self._summary_title.grid(row=0, column=0, sticky="w")
        self._summary_meta = ttk.Label(summary, text="", style=f"{self._style_prefix}.Muted.TLabel", wraplength=760, justify="left")
        self._summary_meta.grid(row=1, column=0, sticky="w", pady=(4, 8))
        self._summary_text = tk.Text(summary, wrap="word", state="disabled", relief="flat", borderwidth=0)
        self._summary_text.grid(row=2, column=0, sticky="nsew")
        _bind_scroll(self._summary_text)

        notes = ttk.Frame(right, padding=10)
        notes.columnconfigure(0, weight=1)
        notes.rowconfigure(0, weight=1)
        right.add(notes, text="Linked Notes")
        self._notes_text = tk.Text(notes, wrap="word", state="disabled", relief="flat", borderwidth=0)
        self._notes_text.grid(row=0, column=0, sticky="nsew")
        _bind_scroll(self._notes_text)

        raw = ttk.Frame(right, padding=10)
        raw.columnconfigure(0, weight=1)
        raw.rowconfigure(0, weight=1)
        right.add(raw, text="Raw User")
        self._raw_text = tk.Text(raw, wrap="word", state="disabled", relief="flat", borderwidth=0)
        self._raw_text.grid(row=0, column=0, sticky="nsew")
        _bind_scroll(self._raw_text)

        machine = ttk.Frame(right, padding=10)
        machine.columnconfigure(0, weight=1)
        machine.rowconfigure(0, weight=1)
        right.add(machine, text="Machine Audit")
        self._machine_text = tk.Text(machine, wrap="word", state="disabled", relief="flat", borderwidth=0)
        self._machine_text.grid(row=0, column=0, sticky="nsew")
        _bind_scroll(self._machine_text)

        ttk.Label(
            self.frame,
            textvariable=self._status_var,
            style=f"{self._style_prefix}.Muted.TLabel",
        ).grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))

    def _apply_page_theme(self):
        tokens = self._theme_tokens
        try:
            style = ttk.Style(self.frame)
            style.configure(f"{self._style_prefix}.TFrame", background=tokens["content_bg"])
            style.configure(
                f"{self._style_prefix}.Header.TLabel",
                background=tokens["content_bg"],
                foreground=tokens["text_main"],
                font=("TkDefaultFont", 14, "bold"),
            )
            style.configure(
                f"{self._style_prefix}.PanelHeader.TLabel",
                background=tokens["content_bg"],
                foreground=tokens["text_main"],
                font=("TkDefaultFont", 11, "bold"),
            )
            style.configure(
                f"{self._style_prefix}.Muted.TLabel",
                background=tokens["content_bg"],
                foreground=tokens["text_muted"],
            )
        except Exception:
            pass
        for widget in (
            getattr(self, "_summary_text", None),
            getattr(self, "_notes_text", None),
            getattr(self, "_raw_text", None),
            getattr(self, "_machine_text", None),
            getattr(self, "_event_list", None),
        ):
            if widget is None:
                continue
            try:
                widget.configure(
                    background=tokens["content_bg"] if isinstance(widget, tk.Text) else tokens["panel_bg"],
                    foreground=tokens["text_main"],
                    insertbackground=tokens["text_main"],
                    selectbackground=tokens["accent"],
                    selectforeground=tokens["text_on_accent"],
                )
            except Exception:
                pass

    def refresh_history(self):
        start = Path(__file__).resolve()
        portable_root = _find_portable_root(start)
        if portable_root is None:
            self._status_var.set("Could not locate portable root with pychi build history.")
            return
        self._root_path = portable_root
        self._history_root = portable_root / "01_project_workshop" / "00_pychi_build_history"
        self._plans_root = portable_root / "03_project_plans"
        self._notes = self._load_notes()
        self._events = self._load_events()
        self._event_by_id = {event["event_id"]: event for event in self._events if event.get("event_id")}
        self._populate_event_list()
        self._status_var.set(f"Loaded {len(self._events)} paired build-history events.")

    def _load_notes(self):
        notes = []
        if self._plans_root is None or not self._plans_root.is_dir():
            return notes
        for path in sorted(self._plans_root.rglob("*.md")):
            raw = _read_text(path)
            frontmatter, body = _parse_frontmatter(raw)
            note_id = str(frontmatter.get("id") or "").strip()
            title = str(frontmatter.get("title") or path.stem).strip()
            text = f"{title}\n{body}\n{raw}"
            notes.append(
                {
                    "path": path,
                    "id": note_id,
                    "title": title,
                    "raw": raw,
                    "frontmatter": frontmatter,
                    "body": body,
                    "tokens": _slug_tokens(text) | _slug_tokens(str(path.relative_to(self._plans_root))),
                }
            )
        return notes

    def _load_events(self):
        history_root = self._history_root
        if history_root is None or not history_root.is_dir():
            return []
        raw_dir = history_root / "raw_user_input"
        machine_dir = history_root / "machine_files"
        paired = {}

        for path in sorted(raw_dir.glob("*.md")):
            raw = _read_text(path)
            frontmatter, body = _parse_frontmatter(raw)
            stem = _stem_from_event_id(str(frontmatter.get("event_id") or ""), path)
            entry = paired.setdefault(stem, {"stem": stem})
            entry["raw_path"] = path
            entry["raw_frontmatter"] = frontmatter
            entry["raw_body"] = body
            entry["raw_text"] = raw

        for path in sorted(machine_dir.glob("*.md")):
            raw = _read_text(path)
            frontmatter, body = _parse_frontmatter(raw)
            stem = _stem_from_event_id(str(frontmatter.get("event_id") or ""), path)
            entry = paired.setdefault(stem, {"stem": stem})
            entry["machine_path"] = path
            entry["machine_frontmatter"] = frontmatter
            entry["machine_body"] = body
            entry["machine_text"] = raw

        events = []
        for stem, entry in paired.items():
            raw_front = entry.get("raw_frontmatter", {})
            machine_front = entry.get("machine_frontmatter", {})
            event_id = str(raw_front.get("event_id") or machine_front.get("event_id") or stem).strip()
            date = str(raw_front.get("date") or machine_front.get("date") or "").strip()
            session_label = str(
                raw_front.get("session_or_run_label")
                or machine_front.get("session_or_run_label")
                or ""
            ).strip()
            response_status = str(machine_front.get("response_status") or raw_front.get("status") or "").strip()
            raw_body = entry.get("raw_body", "")
            machine_body = entry.get("machine_body", "")
            raw_text = entry.get("raw_text", "")
            machine_text = entry.get("machine_text", "")

            page_ids = []
            pack_ids = []
            related_notes = []
            topics = []
            decision_type = ""
            implementation_scope = ""
            related_event_ids = []
            projects = []
            for source in (raw_front, machine_front):
                page_ids.extend(_as_list(source.get("page_ids")))
                pack_ids.extend(_as_list(source.get("pack_ids")))
                related_notes.extend(_as_list(source.get("related_notes")))
                topics.extend(_as_list(source.get("topic")))
                projects.extend(_as_list(source.get("project")))
                related_event_ids.extend(_as_list(source.get("related_event_ids")))
                if not decision_type:
                    decision_type = str(source.get("decision_type") or "").strip()
                if not implementation_scope:
                    implementation_scope = str(source.get("implementation_scope") or "").strip()

            combined_text = "\n".join([session_label, raw_text, machine_text])
            inferred_page_ids = _extract_page_ids(combined_text)
            page_ids = sorted(set([item for item in page_ids if item] + inferred_page_ids))
            pack_ids = sorted(set([item for item in pack_ids if item]))
            related_notes = sorted(set([item for item in related_notes if item]))
            related_event_ids = sorted(set([item for item in related_event_ids if item]))
            topics = sorted(set([item for item in topics if item]))
            projects = sorted(set([item for item in projects if item]))

            linked_notes = self._find_related_notes(
                related_notes=related_notes,
                page_ids=page_ids,
                session_label=session_label,
                raw_text=raw_text,
                machine_text=machine_text,
                projects=projects,
                topics=topics,
            )

            summary = self._build_event_summary(
                event_id=event_id,
                date=date,
                session_label=session_label,
                response_status=response_status,
                page_ids=page_ids,
                pack_ids=pack_ids,
                related_notes=related_notes,
                projects=projects,
                topics=topics,
                decision_type=decision_type,
                implementation_scope=implementation_scope,
                linked_notes=linked_notes,
                machine_body=machine_body,
                raw_body=raw_body,
            )

            events.append(
                {
                    "event_id": event_id,
                    "date": date,
                    "session_or_run_label": session_label,
                    "response_status": response_status,
                    "raw_path": entry.get("raw_path"),
                    "machine_path": entry.get("machine_path"),
                    "raw_text": raw_text,
                    "machine_text": machine_text,
                    "raw_body": raw_body,
                    "machine_body": machine_body,
                    "raw_frontmatter": raw_front,
                    "machine_frontmatter": machine_front,
                    "page_ids": page_ids,
                    "pack_ids": pack_ids,
                    "related_notes": related_notes,
                    "related_event_ids": related_event_ids,
                    "projects": projects,
                    "topics": topics,
                    "decision_type": decision_type,
                    "implementation_scope": implementation_scope,
                    "linked_notes": linked_notes,
                    "summary": summary,
                    "search_blob": "\n".join(
                        [
                            event_id,
                            date,
                            session_label,
                            response_status,
                            " ".join(page_ids),
                            " ".join(pack_ids),
                            " ".join(related_notes),
                            " ".join(projects),
                            " ".join(topics),
                            raw_text,
                            machine_text,
                        ]
                    ).lower(),
                }
            )

        events.sort(key=lambda item: (item.get("date") or "", item.get("event_id") or ""), reverse=True)
        return events

    def _find_related_notes(self, related_notes, page_ids, session_label, raw_text, machine_text, projects, topics):
        matches = []
        seen = set()
        explicit = set()
        for note_ref in related_notes:
            cleaned = note_ref.strip().strip("[]")
            cleaned = cleaned.replace("[[", "").replace("]]", "")
            explicit.add(cleaned.lower())
        tokens = (
            _slug_tokens(session_label)
            | _slug_tokens(raw_text)
            | _slug_tokens(machine_text)
            | _slug_tokens(" ".join(page_ids))
            | _slug_tokens(" ".join(projects))
            | _slug_tokens(" ".join(topics))
        )
        for note in self._notes:
            note_id = (note.get("id") or "").lower()
            title = (note.get("title") or "").lower()
            path_stem = note["path"].stem.lower()
            is_explicit = bool(
                explicit
                and (
                    note_id in explicit
                    or title in explicit
                    or path_stem in explicit
                )
            )
            page_hit = any(page_id.lower() in note["raw"].lower() for page_id in page_ids)
            token_overlap = len(tokens & note["tokens"])
            project_hit = any(project.lower() in str(note["path"]).lower() for project in projects if project)
            if not is_explicit and not page_hit and token_overlap < 3 and not project_hit:
                continue
            key = str(note["path"])
            if key in seen:
                continue
            seen.add(key)
            score = (
                (100 if is_explicit else 0)
                + (20 if page_hit else 0)
                + min(token_overlap, 10)
                + (5 if project_hit else 0)
            )
            matches.append((score, note))
        matches.sort(key=lambda item: (-item[0], str(item[1]["path"])))
        return [note for _score, note in matches[:8]]

    def _build_event_summary(
        self,
        event_id,
        date,
        session_label,
        response_status,
        page_ids,
        pack_ids,
        related_notes,
        projects,
        topics,
        decision_type,
        implementation_scope,
        linked_notes,
        machine_body,
        raw_body,
    ):
        lines = []
        lines.append(f"Event: {event_id}")
        if date:
            lines.append(f"Date: {date}")
        if session_label:
            lines.append(f"Session: {session_label}")
        if response_status:
            lines.append(f"Status: {response_status}")
        if page_ids:
            lines.append(f"Pages: {', '.join(page_ids)}")
        if pack_ids:
            lines.append(f"Packs: {', '.join(pack_ids)}")
        if projects:
            lines.append(f"Projects: {', '.join(projects)}")
        if topics:
            lines.append(f"Topics: {', '.join(topics)}")
        if decision_type:
            lines.append(f"Decision Type: {decision_type}")
        if implementation_scope:
            lines.append(f"Implementation Scope: {implementation_scope}")
        if related_notes:
            lines.append(f"Explicit Related Notes: {', '.join(related_notes)}")
        if linked_notes:
            lines.append("Matched Plan Notes:")
            for note in linked_notes:
                note_id = note.get("id") or note["path"].stem
                rel = note["path"].relative_to(self._root_path) if self._root_path else note["path"]
                lines.append(f"- {note_id}: {rel}")
        body_source = machine_body or raw_body or ""
        snippet = body_source.strip().splitlines()
        if snippet:
            lines.append("")
            lines.append("Snippet")
            lines.append("-------")
            lines.extend(snippet[:18])
        return "\n".join(lines)

    def _filtered_events(self):
        query = self._filter_var.get().strip().lower()
        if not query:
            return self._events
        return [event for event in self._events if query in event["search_blob"]]

    def _populate_event_list(self):
        self._event_list.delete(0, "end")
        for event in self._filtered_events():
            date = event.get("date") or "????-??-??"
            session = event.get("session_or_run_label") or "(no session label)"
            page_hint = f" [{', '.join(event['page_ids'][:2])}]" if event.get("page_ids") else ""
            label = f"{date}  {event['event_id']}  {session}{page_hint}"
            self._event_list.insert("end", label)
        if self._filtered_events():
            self._event_list.selection_set(0)
            self._event_list.activate(0)
            self._show_event(self._filtered_events()[0])
        else:
            self._selected_event = None
            self._summary_title.configure(text="No matching events")
            self._summary_meta.configure(text="")
            for widget in (self._summary_text, self._notes_text, self._raw_text, self._machine_text):
                self._set_text(widget, "")

    def _on_event_select(self, _event=None):
        sel = self._event_list.curselection()
        events = self._filtered_events()
        if not sel or not events:
            return
        idx = sel[0]
        if 0 <= idx < len(events):
            self._show_event(events[idx])

    def _show_event(self, event):
        self._selected_event = event
        self._summary_title.configure(text=event["event_id"])
        meta_parts = []
        if event.get("date"):
            meta_parts.append(f"date: {event['date']}")
        if event.get("session_or_run_label"):
            meta_parts.append(f"session: {event['session_or_run_label']}")
        if event.get("response_status"):
            meta_parts.append(f"status: {event['response_status']}")
        if event.get("raw_path"):
            meta_parts.append(f"raw: {event['raw_path'].name}")
        if event.get("machine_path"):
            meta_parts.append(f"machine: {event['machine_path'].name}")
        self._summary_meta.configure(text="   ".join(meta_parts))
        self._set_text(self._summary_text, event.get("summary", ""))

        note_lines = []
        if event.get("linked_notes"):
            for note in event["linked_notes"]:
                rel = note["path"].relative_to(self._root_path) if self._root_path else note["path"]
                note_lines.append(f"{note.get('title') or note['path'].stem}")
                note_lines.append(f"File: {rel}")
                if note.get("id"):
                    note_lines.append(f"id: {note['id']}")
                frontmatter = note.get("frontmatter", {})
                for key in ("type", "status", "project", "confidence"):
                    value = frontmatter.get(key)
                    if value:
                        note_lines.append(f"{key}: {value}")
                body = note.get("body", "").strip()
                if body:
                    note_lines.append("")
                    note_lines.extend(body.splitlines()[:16])
                note_lines.append("")
                note_lines.append("-" * 60)
                note_lines.append("")
        else:
            note_lines.append("No related notes matched yet.")
            note_lines.append("")
            note_lines.append("Best bridge fields to add in future logs:")
            for field in _OPTIONAL_LINK_FIELDS:
                note_lines.append(f"- {field}")
        self._set_text(self._notes_text, "\n".join(note_lines))

        self._set_text(self._raw_text, self._format_log_file(event.get("raw_path"), event.get("raw_frontmatter"), event.get("raw_body"), event.get("raw_text")))
        self._set_text(self._machine_text, self._format_log_file(event.get("machine_path"), event.get("machine_frontmatter"), event.get("machine_body"), event.get("machine_text")))
        self._status_var.set(f"Viewing {event['event_id']}.")

    def _format_log_file(self, path, frontmatter, body, raw_text):
        if not raw_text:
            return "(missing)"
        lines = []
        if path is not None:
            rel = path.relative_to(self._root_path) if self._root_path else path
            lines.append(f"File: {rel}")
            lines.append("")
        if frontmatter:
            lines.append("Frontmatter")
            lines.append("-----------")
            for key, value in frontmatter.items():
                lines.append(f"{key}: {value}")
            lines.append("")
        lines.append("Body")
        lines.append("----")
        lines.append(body or "(empty)")
        return "\n".join(lines)

    def _set_text(self, widget: tk.Text, content: str):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", (content or "").strip() + ("\n" if content else ""))
        widget.configure(state="disabled")
