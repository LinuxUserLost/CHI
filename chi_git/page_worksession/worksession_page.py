import json
import os
import subprocess
import tkinter as tk
from datetime import datetime, timezone
from tkinter import filedialog, messagebox, ttk

from chi_git.theme_support import (
    apply_listbox_theme,
    apply_text_theme,
    configure_ttk_styles,
    resolve_chigit_theme,
)


class ChiGitWorkSessionPage:
    def __init__(self, parent=None, app=None, page_key="", page_folder="", *args, **kwargs):
        self.app = kwargs.pop("controller", app)
        self.page_key = kwargs.pop("page_context", page_key)
        self.page_folder = kwargs.pop("page_folder", page_folder)

        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.data_dir = os.path.join(self.base_dir, "chigit_data")
        self.config_path = os.path.join(self.data_dir, "worksession_config.json")
        self.log_path = os.path.join(self.data_dir, "worksession_log.jsonl")
        os.makedirs(self.data_dir, exist_ok=True)

        self._ensure_json(self.config_path, {
            "last_repo_root": "",
            "last_lane": "",
            "last_agent": "",
            "last_task_id": "",
            "last_pagepack": "",
            "last_note": ""
        })
        self._ensure_text(self.log_path)
        self.config = self._load_config()

        self.parent = parent
        self.frame = ttk.Frame(parent) if parent is not None else ttk.Frame()
        self.guichi_page_theme = None
        self._theme_tokens = resolve_chigit_theme()
        self._style_prefix = f"ChiGitWorkSession.{id(self)}"

        self.repo_var = tk.StringVar(value=self.config.get("last_repo_root", ""))
        self.lane_var = tk.StringVar(value=self.config.get("last_lane", ""))
        self.agent_var = tk.StringVar(value=self.config.get("last_agent", ""))
        self.task_id_var = tk.StringVar(value=self.config.get("last_task_id", ""))
        self.pagepack_var = tk.StringVar(value=self.config.get("last_pagepack", ""))
        self.branch_var = tk.StringVar(value="(unknown)")
        self.head_var = tk.StringVar(value="(unknown)")
        self.status_var = tk.StringVar(value="ready")
        self.snapshot_summary_var = tk.StringVar(value="No snapshot yet")
        self.entry_filter_var = tk.StringVar(value="")

        self.entry_rows = []
        self.visible_rows = []
        self._themed_frames = []
        self._themed_panel_frames = []
        self._themed_labelframes = []
        self._themed_labels = []
        self._themed_panel_labels = []
        self._themed_muted_labels = []
        self._themed_panel_muted_labels = []
        self._themed_entries = []
        self._themed_buttons = []
        self._themed_comboboxes = []

        self._build_ui(self.frame)
        self._apply_theme()
        self.frame.after(150, self.refresh_repo_state)
        self.frame.after(250, self.refresh_log_list)

    def build(self, parent=None):
        return self._embed_into_parent(parent)

    def create_widgets(self, parent=None):
        return self._embed_into_parent(parent)

    def mount(self, parent=None):
        return self._embed_into_parent(parent)

    def render(self, parent=None):
        return self._embed_into_parent(parent)

    def _embed_into_parent(self, parent=None):
        container = parent or self.parent
        self.parent = container
        try:
            self.frame.pack_forget()
        except Exception:
            pass
        try:
            self.frame.pack(in_=container, fill="both", expand=True)
        except Exception:
            try:
                self.frame.grid(row=0, column=0, sticky="nsew")
            except Exception:
                pass
        return self.frame

    def _build_ui(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(4, weight=1)
        parent.rowconfigure(5, weight=1)
        self._themed_frames.append(parent)

        repo_box = ttk.LabelFrame(parent, text="Repo", style=f"{self._style_prefix}.TLabelframe")
        repo_box.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        repo_box.columnconfigure(1, weight=1)
        self._themed_labelframes.append(repo_box)
        label = ttk.Label(repo_box, text="Repo root:", style=f"{self._style_prefix}.Panel.Muted.TLabel")
        label.grid(row=0, column=0, sticky="w", padx=6, pady=6)
        self._themed_panel_muted_labels.append(label)
        entry = ttk.Entry(repo_box, textvariable=self.repo_var, style=f"{self._style_prefix}.TEntry")
        entry.grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        self._themed_entries.append(entry)
        button = ttk.Button(repo_box, text="Browse", command=self.choose_repo, style=f"{self._style_prefix}.TButton")
        button.grid(row=0, column=2, padx=6, pady=6)
        self._themed_buttons.append(button)
        button = ttk.Button(repo_box, text="Refresh state", command=self.refresh_repo_state, style=f"{self._style_prefix}.TButton")
        button.grid(row=0, column=3, padx=6, pady=6)
        self._themed_buttons.append(button)
        label = ttk.Label(repo_box, text="Branch:", style=f"{self._style_prefix}.Panel.Muted.TLabel")
        label.grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self._themed_panel_muted_labels.append(label)
        label = ttk.Label(repo_box, textvariable=self.branch_var, style=f"{self._style_prefix}.Panel.TLabel")
        label.grid(row=1, column=1, sticky="w", padx=6, pady=4)
        self._themed_panel_labels.append(label)
        label = ttk.Label(repo_box, text="HEAD:", style=f"{self._style_prefix}.Panel.Muted.TLabel")
        label.grid(row=1, column=2, sticky="e", padx=6, pady=4)
        self._themed_panel_muted_labels.append(label)
        label = ttk.Label(repo_box, textvariable=self.head_var, style=f"{self._style_prefix}.Panel.TLabel")
        label.grid(row=1, column=3, sticky="w", padx=6, pady=4)
        self._themed_panel_labels.append(label)

        session_box = ttk.LabelFrame(parent, text="Work session fields", style=f"{self._style_prefix}.TLabelframe")
        session_box.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        session_box.columnconfigure(1, weight=1)
        session_box.columnconfigure(3, weight=1)
        self._themed_labelframes.append(session_box)

        label = ttk.Label(session_box, text="Lane:", style=f"{self._style_prefix}.Panel.Muted.TLabel")
        label.grid(row=0, column=0, sticky="w", padx=6, pady=6)
        self._themed_panel_muted_labels.append(label)
        lane_combo = ttk.Combobox(
            session_box,
            textvariable=self.lane_var,
            values=["browser", "claude_cli", "local_qwen", "manual_terminal", "guichi_manual", "other"],
            style=f"{self._style_prefix}.TCombobox",
        )
        lane_combo.grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        self._themed_comboboxes.append(lane_combo)
        label = ttk.Label(session_box, text="Agent:", style=f"{self._style_prefix}.Panel.Muted.TLabel")
        label.grid(row=0, column=2, sticky="w", padx=6, pady=6)
        self._themed_panel_muted_labels.append(label)
        entry = ttk.Entry(session_box, textvariable=self.agent_var, style=f"{self._style_prefix}.TEntry")
        entry.grid(row=0, column=3, sticky="ew", padx=6, pady=6)
        self._themed_entries.append(entry)

        label = ttk.Label(session_box, text="Task id:", style=f"{self._style_prefix}.Panel.Muted.TLabel")
        label.grid(row=1, column=0, sticky="w", padx=6, pady=6)
        self._themed_panel_muted_labels.append(label)
        entry = ttk.Entry(session_box, textvariable=self.task_id_var, style=f"{self._style_prefix}.TEntry")
        entry.grid(row=1, column=1, sticky="ew", padx=6, pady=6)
        self._themed_entries.append(entry)
        label = ttk.Label(session_box, text="Pagepack:", style=f"{self._style_prefix}.Panel.Muted.TLabel")
        label.grid(row=1, column=2, sticky="w", padx=6, pady=6)
        self._themed_panel_muted_labels.append(label)
        entry = ttk.Entry(session_box, textvariable=self.pagepack_var, style=f"{self._style_prefix}.TEntry")
        entry.grid(row=1, column=3, sticky="ew", padx=6, pady=6)
        self._themed_entries.append(entry)

        note_box = ttk.LabelFrame(parent, text="Work note", style=f"{self._style_prefix}.TLabelframe")
        note_box.grid(row=2, column=0, sticky="nsew", padx=8, pady=4)
        note_box.columnconfigure(0, weight=1)
        note_box.rowconfigure(0, weight=1)
        self._themed_labelframes.append(note_box)
        self.note_text = tk.Text(note_box, wrap="word", height=7)
        self.note_text.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        note_scroll = ttk.Scrollbar(note_box, orient="vertical", command=self.note_text.yview)
        note_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 6), pady=6)
        self.note_text.configure(yscrollcommand=note_scroll.set)
        if self.config.get("last_note"):
            self.note_text.insert("1.0", self.config.get("last_note", ""))

        action_box = ttk.LabelFrame(parent, text="Actions", style=f"{self._style_prefix}.TLabelframe")
        action_box.grid(row=3, column=0, sticky="ew", padx=8, pady=4)
        for i in range(6):
            action_box.columnconfigure(i, weight=1)
        self._themed_labelframes.append(action_box)
        for col, (text, cmd) in enumerate((
            ("Save draft fields", self.save_fields_only),
            ("Save work entry", self.save_work_entry),
            ("Save snapshot entry", self.save_snapshot_entry),
            ("Refresh entries", self.refresh_log_list),
            ("Copy summary", self.copy_current_summary),
            ("Open data folder", self.open_data_folder),
        )):
            button = ttk.Button(action_box, text=text, command=cmd, style=f"{self._style_prefix}.TButton")
            button.grid(row=0, column=col, sticky="ew", padx=4, pady=6)
            self._themed_buttons.append(button)

        list_box = ttk.LabelFrame(parent, text="Recent work entries", style=f"{self._style_prefix}.TLabelframe")
        list_box.grid(row=4, column=0, sticky="nsew", padx=8, pady=4)
        list_box.columnconfigure(0, weight=1)
        list_box.rowconfigure(1, weight=1)
        self._themed_labelframes.append(list_box)
        filter_row = ttk.Frame(list_box, style=f"{self._style_prefix}.Panel.TFrame")
        filter_row.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(6, 2))
        filter_row.columnconfigure(1, weight=1)
        self._themed_panel_frames.append(filter_row)
        label = ttk.Label(filter_row, text="Filter:", style=f"{self._style_prefix}.Panel.Muted.TLabel")
        label.grid(row=0, column=0, sticky="w", padx=(0, 4), pady=2)
        self._themed_panel_muted_labels.append(label)
        entry = ttk.Entry(filter_row, textvariable=self.entry_filter_var, style=f"{self._style_prefix}.TEntry")
        entry.grid(row=0, column=1, sticky="ew", padx=4, pady=2)
        entry.bind("<KeyRelease>", lambda _event: self._apply_entry_filter())
        self._themed_entries.append(entry)
        self.entry_list = tk.Listbox(list_box, exportselection=False)
        self.entry_list.grid(row=1, column=0, sticky="nsew", padx=(6, 0), pady=(2, 6))
        self.entry_list.bind("<<ListboxSelect>>", lambda _event: self.show_selected_entry())
        list_scroll = ttk.Scrollbar(list_box, orient="vertical", command=self.entry_list.yview)
        list_scroll.grid(row=1, column=1, sticky="ns", padx=(0, 6), pady=(2, 6))
        self.entry_list.configure(yscrollcommand=list_scroll.set)

        detail_box = ttk.LabelFrame(parent, text="Entry details", style=f"{self._style_prefix}.TLabelframe")
        detail_box.grid(row=5, column=0, sticky="nsew", padx=8, pady=(4, 8))
        detail_box.columnconfigure(0, weight=1)
        detail_box.rowconfigure(0, weight=1)
        self._themed_labelframes.append(detail_box)
        self.detail_text = tk.Text(detail_box, wrap="word", height=12)
        self.detail_text.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        detail_scroll = ttk.Scrollbar(detail_box, orient="vertical", command=self.detail_text.yview)
        detail_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 6), pady=6)
        self.detail_text.configure(yscrollcommand=detail_scroll.set)

        status = ttk.Frame(parent, style=f"{self._style_prefix}.TFrame")
        status.grid(row=6, column=0, sticky="ew", padx=8, pady=(0, 8))
        status.columnconfigure(0, weight=1)
        self._themed_frames.append(status)
        label = ttk.Label(status, textvariable=self.status_var, style=f"{self._style_prefix}.Muted.TLabel")
        label.grid(row=0, column=0, sticky="w")
        self._themed_muted_labels.append(label)
        label = ttk.Label(status, textvariable=self.snapshot_summary_var, style=f"{self._style_prefix}.Muted.TLabel")
        label.grid(row=0, column=1, sticky="e")
        self._themed_muted_labels.append(label)

    def _ensure_json(self, path, payload):
        if os.path.isfile(path):
            return
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)

    def _ensure_text(self, path):
        if os.path.isfile(path):
            return
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("")

    def _load_config(self):
        try:
            with open(self.config_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def _save_config(self):
        payload = {
            "last_repo_root": self.repo_var.get().strip(),
            "last_lane": self.lane_var.get().strip(),
            "last_agent": self.agent_var.get().strip(),
            "last_task_id": self.task_id_var.get().strip(),
            "last_pagepack": self.pagepack_var.get().strip(),
            "last_note": self.note_text.get("1.0", "end-1c").strip(),
        }
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        self.config = payload

    def set_guichi_page_theme(self, context):
        self.guichi_page_theme = context
        self._theme_tokens = resolve_chigit_theme(context)
        self._apply_theme()

    def _apply_theme(self):
        configure_ttk_styles(self.frame, self._style_prefix, self._theme_tokens)
        for widget in self._themed_frames:
            try:
                widget.configure(style=f"{self._style_prefix}.TFrame")
            except Exception:
                pass
        for widget in self._themed_panel_frames:
            try:
                widget.configure(style=f"{self._style_prefix}.Panel.TFrame")
            except Exception:
                pass
        for widget in self._themed_labelframes:
            try:
                widget.configure(style=f"{self._style_prefix}.TLabelframe")
            except Exception:
                pass
        for widget in self._themed_labels:
            try:
                widget.configure(style=f"{self._style_prefix}.TLabel")
            except Exception:
                pass
        for widget in self._themed_panel_labels:
            try:
                widget.configure(style=f"{self._style_prefix}.Panel.TLabel")
            except Exception:
                pass
        for widget in self._themed_muted_labels:
            try:
                widget.configure(style=f"{self._style_prefix}.Muted.TLabel")
            except Exception:
                pass
        for widget in self._themed_panel_muted_labels:
            try:
                widget.configure(style=f"{self._style_prefix}.Panel.Muted.TLabel")
            except Exception:
                pass
        for widget in self._themed_entries:
            try:
                widget.configure(style=f"{self._style_prefix}.TEntry")
            except Exception:
                pass
        for widget in self._themed_buttons:
            try:
                widget.configure(style=f"{self._style_prefix}.TButton")
            except Exception:
                pass
        for widget in self._themed_comboboxes:
            try:
                widget.configure(style=f"{self._style_prefix}.TCombobox")
            except Exception:
                pass
        apply_text_theme(self.note_text, self._theme_tokens)
        apply_listbox_theme(self.entry_list, self._theme_tokens)
        apply_text_theme(self.detail_text, self._theme_tokens)

    def _set_status(self, message):
        self.status_var.set(message)

    def _run_git(self, args, cwd=None):
        cmd = ["git"] + list(args)
        try:
            completed = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            merged = (stdout + ("\n" if stdout and stderr else "") + stderr).strip()
            return {"code": completed.returncode, "stdout": stdout, "stderr": stderr, "text": merged}
        except FileNotFoundError:
            return {"code": 127, "stdout": "", "stderr": "git not found", "text": "git not found"}
        except Exception as exc:
            return {"code": 1, "stdout": "", "stderr": str(exc), "text": str(exc)}

    def _validate_repo(self, show_error=True):
        root = self.repo_var.get().strip()
        if not root:
            if show_error:
                messagebox.showwarning("WorkSession", "Choose a repo root first.")
            return None
        if not os.path.isdir(root):
            if show_error:
                messagebox.showerror("WorkSession", f"Folder does not exist:\n{root}")
            return None
        probe = self._run_git(["rev-parse", "--git-dir"], cwd=root)
        if probe["code"] != 0:
            if show_error:
                messagebox.showerror("WorkSession", f"Not a git repo:\n{root}")
            return None
        return root

    def choose_repo(self):
        chosen = filedialog.askdirectory(initialdir=self.repo_var.get() or os.path.expanduser("~"))
        if chosen:
            self.repo_var.set(chosen)
            self._save_config()
            self.refresh_repo_state()

    def refresh_repo_state(self):
        root = self._validate_repo(show_error=False)
        if not root:
            self.branch_var.set("(not set)")
            self.head_var.set("(not set)")
            self.snapshot_summary_var.set("No snapshot yet")
            self._set_status("Choose a valid repo to begin.")
            return
        self._save_config()
        branch_res = self._run_git(["branch", "--show-current"], cwd=root)
        head_res = self._run_git(["rev-parse", "--short", "HEAD"], cwd=root)
        status_res = self._run_git(["status", "--short"], cwd=root)
        changed_count = len([line for line in status_res["stdout"].splitlines() if line.strip()])
        self.branch_var.set((branch_res["stdout"] or "").strip() or "(detached/unknown)")
        self.head_var.set((head_res["stdout"] or "").strip() or "(none)")
        self.snapshot_summary_var.set(f"{changed_count} changed file(s)")
        self._set_status("Repo state refreshed.")

    def _make_entry(self, entry_type):
        root = self._validate_repo()
        if not root:
            return None
        self.refresh_repo_state()
        self._save_config()
        note = self.note_text.get("1.0", "end-1c").strip()
        status_res = self._run_git(["status", "--short"], cwd=root)
        last_commit_res = self._run_git(["log", "-1", "--pretty=%H%x1f%h%x1f%ad%x1f%s", "--date=short"], cwd=root)
        last_commit_parts = (last_commit_res["stdout"] or "").split("\x1f")
        while len(last_commit_parts) < 4:
            last_commit_parts.append("")
        changed_files = [line.strip() for line in status_res["stdout"].splitlines() if line.strip()]
        return {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "entry_type": entry_type,
            "repo_root": root,
            "lane": self.lane_var.get().strip(),
            "agent": self.agent_var.get().strip(),
            "task_id": self.task_id_var.get().strip(),
            "pagepack": self.pagepack_var.get().strip(),
            "branch": self.branch_var.get().strip(),
            "head": self.head_var.get().strip(),
            "note": note,
            "changed_files": changed_files,
            "changed_file_count": len(changed_files),
            "last_commit_full": last_commit_parts[0],
            "last_commit_short": last_commit_parts[1],
            "last_commit_date": last_commit_parts[2],
            "last_commit_subject": last_commit_parts[3],
        }

    def save_fields_only(self):
        self._save_config()
        self._set_status("Saved draft fields locally.")

    def save_work_entry(self):
        entry = self._make_entry("work_entry")
        if not entry:
            return
        self._append_entry(entry)
        self.refresh_log_list()
        self._set_status("Saved work entry.")

    def save_snapshot_entry(self):
        entry = self._make_entry("snapshot_entry")
        if not entry:
            return
        self._append_entry(entry)
        self.refresh_log_list()
        self._set_status("Saved snapshot entry.")

    def _append_entry(self, entry):
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def refresh_log_list(self):
        rows = []
        try:
            with open(self.log_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            pass
        self.entry_rows = list(reversed(rows[-100:]))
        self._apply_entry_filter()

    def _entry_row_text(self, row):
        stamp = row.get("timestamp_utc", "")
        entry_type = row.get("entry_type", "")
        lane = row.get("lane", "") or "(no lane)"
        branch = row.get("branch", "") or "(no branch)"
        task = row.get("task_id", "") or "(no task)"
        note = (row.get("note", "") or "").splitlines()[0][:50]
        return f"{stamp} | {entry_type} | {lane} | {branch} | {task} | {note}"

    def _apply_entry_filter(self):
        needle = (self.entry_filter_var.get() or "").strip().lower()
        if needle:
            self.visible_rows = [
                row for row in self.entry_rows
                if needle in self._entry_row_text(row).lower()
                or needle in json.dumps(row, ensure_ascii=False).lower()
            ]
        else:
            self.visible_rows = list(self.entry_rows)
        self.entry_list.delete(0, "end")
        for row in self.visible_rows:
            self.entry_list.insert("end", self._entry_row_text(row))
        if not self.entry_rows:
            self.detail_text.delete("1.0", "end")
            self.detail_text.insert("1.0", "No work entries yet.\n\nSave a work entry or snapshot entry to start building the session log.")
            self._set_status("No work entries yet.")
        elif needle and not self.visible_rows:
            self.detail_text.delete("1.0", "end")
            self.detail_text.insert("1.0", f"No work entries match filter: {self.entry_filter_var.get().strip()}")
            self._set_status("No entries match the current filter.")

    def show_selected_entry(self):
        sel = self.entry_list.curselection()
        if not sel:
            return
        idx = sel[0]
        if not (0 <= idx < len(self.visible_rows)):
            return
        row = self.visible_rows[idx]
        pretty = json.dumps(row, indent=2, ensure_ascii=False)
        summary_lines = [
            "Entry Summary",
            "",
            f"Timestamp: {row.get('timestamp_utc', '') or '(unknown)'}",
            f"Entry type: {row.get('entry_type', '') or '(unknown)'}",
            f"Repo root: {row.get('repo_root', '') or '(unknown)'}",
            f"Lane: {row.get('lane', '') or '(none)'}",
            f"Agent: {row.get('agent', '') or '(none)'}",
            f"Task id: {row.get('task_id', '') or '(none)'}",
            f"Pagepack: {row.get('pagepack', '') or '(none)'}",
            f"Branch: {row.get('branch', '') or '(unknown)'}",
            f"HEAD: {row.get('head', '') or '(unknown)'}",
            f"Changed files: {row.get('changed_file_count', 0)}",
            f"Last commit: {row.get('last_commit_short', '') or '(none)'}  {row.get('last_commit_date', '') or ''}  {row.get('last_commit_subject', '') or ''}".rstrip(),
            "",
            "Note",
            row.get("note", "") or "(no note)",
            "",
            "Raw JSON",
            pretty,
        ]
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", "\n".join(summary_lines))
        self._set_status("Showing selected work entry.")

    def copy_current_summary(self):
        summary = {
            "repo_root": self.repo_var.get().strip(),
            "lane": self.lane_var.get().strip(),
            "agent": self.agent_var.get().strip(),
            "task_id": self.task_id_var.get().strip(),
            "pagepack": self.pagepack_var.get().strip(),
            "branch": self.branch_var.get().strip(),
            "head": self.head_var.get().strip(),
            "note": self.note_text.get("1.0", "end-1c").strip(),
        }
        text = json.dumps(summary, indent=2, ensure_ascii=False)
        try:
            self.frame.clipboard_clear()
            self.frame.clipboard_append(text)
            self._set_status("Copied current session summary.")
        except Exception as exc:
            self.detail_text.delete("1.0", "end")
            self.detail_text.insert("1.0", f"Clipboard copy failed: {exc}")

    def open_data_folder(self):
        try:
            subprocess.Popen(["xdg-open", self.data_dir], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._set_status("Opened ChiGit data folder.")
        except Exception as exc:
            self.detail_text.delete("1.0", "end")
            self.detail_text.insert("1.0", f"Could not open data folder: {exc}")
