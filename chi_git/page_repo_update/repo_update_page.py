import json
import os
import subprocess
import tkinter as tk
from datetime import datetime, timezone
from tkinter import filedialog, messagebox, simpledialog, ttk

from chi_git.theme_support import (
    apply_listbox_theme,
    apply_text_theme,
    configure_ttk_styles,
    resolve_chigit_theme,
)


_PRIVATE_PREFIXES = (
    "chi_git/chigit_data/",
    "gui_files/state/",
    "gui_files/config/",
    "chi_los/network_reports/",
    "chi_los/linuxcommands/",
)

_PRIVATE_EXACT_PATHS = {
    "chi_los/page_network_control/page_network_control_config.json",
    "chi_los/page_audio_router/audio_router_config.json",
    "chi_los/page_linux_monitor_manager/linux_monitor_manager_config.json",
}

_PUBLIC_FILE_NAMES = {
    "__init__.py",
    "module_manifest.json",
    "pages.json",
    "README.md",
    "README.MD",
}


class ChiGitRepoUpdatePage:
    def __init__(self, parent=None, app=None, page_key="", page_folder="", *args, **kwargs):
        self.app = kwargs.pop("controller", app)
        self.page_key = kwargs.pop("page_context", page_key)
        self.page_folder = kwargs.pop("page_folder", page_folder)

        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.data_dir = os.path.join(self.base_dir, "chigit_data")
        self.config_path = os.path.join(self.data_dir, "repo_update_config.json")
        self.log_path = os.path.join(self.data_dir, "repo_update_log.jsonl")
        os.makedirs(self.data_dir, exist_ok=True)

        self._ensure_json(self.config_path, {
            "last_repo_root": "",
            "last_commit_message": "",
            "last_note": "",
        })
        self._ensure_text(self.log_path)
        self.config = self._load_config()

        self.parent = parent
        self.frame = ttk.Frame(parent) if parent is not None else ttk.Frame()
        self.guichi_page_theme = None
        self._theme_tokens = resolve_chigit_theme()
        self._style_prefix = f"ChiGitRepoUpdate.{id(self)}"

        self.repo_var = tk.StringVar(value=self.config.get("last_repo_root", ""))
        self.branch_var = tk.StringVar(value="(unknown)")
        self.head_var = tk.StringVar(value="(unknown)")
        self.upstream_var = tk.StringVar(value="(none)")
        self.ahead_behind_var = tk.StringVar(value="ahead 0 / behind 0")
        self.last_commit_var = tk.StringVar(value="(none)")
        self.selection_summary_var = tk.StringVar(value="0 selected")
        self.public_selection_summary_var = tk.StringVar(value="0 selected")
        self.public_summary_var = tk.StringVar(value="public helper: review before staging")
        self.branch_help_var = tk.StringVar(
            value="Use a separate public branch. Stage only reviewed public-safe files."
        )
        self.status_var = tk.StringVar(value="ready")
        self.commit_msg_var = tk.StringVar(value=self.config.get("last_commit_message", ""))
        self.filter_var = tk.StringVar(value="")
        self.public_branch_var = tk.StringVar(value="public-upload")

        self.file_rows = []
        self.visible_rows = []
        self.public_visible_rows = []
        self._themed_frames = []
        self._themed_panel_frames = []
        self._themed_labelframes = []
        self._themed_labels = []
        self._themed_panel_labels = []
        self._themed_muted_labels = []
        self._themed_panel_muted_labels = []
        self._themed_entries = []
        self._themed_buttons = []

        self._build_ui(self.frame)
        self._apply_theme()
        self.frame.after(150, self.refresh_status)

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
        parent.rowconfigure(1, weight=1)
        parent.rowconfigure(2, weight=1)
        self._themed_frames.append(parent)

        repo_box = ttk.LabelFrame(parent, text="Repo", style=f"{self._style_prefix}.TLabelframe")
        repo_box.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        repo_box.columnconfigure(1, weight=1)
        self._themed_labelframes.append(repo_box)
        label = ttk.Label(repo_box, text="Repo root:", style=f"{self._style_prefix}.Panel.TLabel")
        label.grid(row=0, column=0, sticky="w", padx=6, pady=6)
        self._themed_panel_muted_labels.append(label)
        entry = ttk.Entry(repo_box, textvariable=self.repo_var, style=f"{self._style_prefix}.TEntry")
        entry.grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        self._themed_entries.append(entry)
        button = ttk.Button(repo_box, text="Browse", command=self.choose_repo, style=f"{self._style_prefix}.TButton")
        button.grid(row=0, column=2, padx=6, pady=6)
        self._themed_buttons.append(button)
        button = ttk.Button(repo_box, text="Refresh", command=self.refresh_status, style=f"{self._style_prefix}.TButton")
        button.grid(row=0, column=3, padx=6, pady=6)
        self._themed_buttons.append(button)

        meta = ttk.Frame(repo_box, style=f"{self._style_prefix}.Panel.TFrame")
        meta.grid(row=1, column=0, columnspan=4, sticky="ew", padx=6, pady=(0, 6))
        self._themed_panel_frames.append(meta)
        for i in range(3):
            meta.columnconfigure(i, weight=1)
        self._meta_label(meta, 0, 0, "Branch", self.branch_var)
        self._meta_label(meta, 0, 1, "HEAD", self.head_var)
        self._meta_label(meta, 0, 2, "Upstream", self.upstream_var)
        self._meta_label(meta, 1, 0, "Ahead/behind", self.ahead_behind_var)
        self._meta_label(meta, 1, 1, "Last commit", self.last_commit_var)

        notebook = ttk.Notebook(parent)
        notebook.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        self.notebook = notebook

        daily_tab = ttk.Frame(notebook, style=f"{self._style_prefix}.TFrame")
        daily_tab.columnconfigure(0, weight=1)
        daily_tab.rowconfigure(1, weight=1)
        self._themed_frames.append(daily_tab)
        notebook.add(daily_tab, text="Daily Update")

        pychi_tab = ttk.Frame(notebook, style=f"{self._style_prefix}.TFrame")
        pychi_tab.columnconfigure(0, weight=1)
        pychi_tab.rowconfigure(3, weight=1)
        self._themed_frames.append(pychi_tab)
        notebook.add(pychi_tab, text="Pychi Code")

        actions = ttk.LabelFrame(daily_tab, text="Daily update flow", style=f"{self._style_prefix}.TLabelframe")
        actions.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 4))
        self._themed_labelframes.append(actions)
        for i in range(3):
            actions.columnconfigure(i, weight=1)
        daily_buttons = (
            ("Fetch", self.fetch_remote),
            ("Pull --ff-only", self.pull_remote),
            ("Push", self.push_remote),
            ("Push + upstream", self.push_remote_with_upstream),
            ("Stage selected", self.stage_selected),
            ("Unstage selected", self.unstage_selected),
            ("Stage all", self.stage_all),
            ("Commit", self.commit_changes),
            ("Copy summary", self.copy_status_summary),
        )
        for idx, (text, cmd) in enumerate(daily_buttons):
            button = ttk.Button(actions, text=text, command=cmd, style=f"{self._style_prefix}.TButton")
            button.grid(row=idx // 3, column=idx % 3, sticky="ew", padx=4, pady=4)
            self._themed_buttons.append(button)

        files = ttk.LabelFrame(daily_tab, text="Changed files", style=f"{self._style_prefix}.TLabelframe")
        files.grid(row=1, column=0, sticky="nsew", padx=0, pady=4)
        self._themed_labelframes.append(files)
        files.columnconfigure(0, weight=1)
        files.rowconfigure(1, weight=1)

        file_toolbar = ttk.Frame(files, style=f"{self._style_prefix}.Panel.TFrame")
        file_toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(6, 2))
        self._themed_panel_frames.append(file_toolbar)
        file_toolbar.columnconfigure(8, weight=1)
        for col, (text, cmd) in enumerate((
            ("Select all", self.select_all_files),
            ("Clear selection", self.clear_file_selection),
            ("Select staged", self.select_staged_files),
            ("Select unstaged", self.select_unstaged_files),
            ("Tracked only", self.select_tracked_changes),
            ("Untracked only", self.select_untracked_files),
        )):
            button = ttk.Button(file_toolbar, text=text, command=cmd, style=f"{self._style_prefix}.TButton")
            button.grid(row=0, column=col, padx=(0, 4) if col == 0 else 4, pady=2)
            self._themed_buttons.append(button)
        label = ttk.Label(file_toolbar, text="Filter:", style=f"{self._style_prefix}.Panel.TLabel")
        label.grid(row=0, column=6, padx=(12, 4), pady=2)
        self._themed_panel_labels.append(label)
        filter_entry = ttk.Entry(file_toolbar, textvariable=self.filter_var, style=f"{self._style_prefix}.TEntry")
        filter_entry.grid(row=0, column=7, sticky="ew", padx=4, pady=2)
        self._themed_entries.append(filter_entry)
        filter_entry.bind("<KeyRelease>", lambda _event: self._apply_file_filter())
        label = ttk.Label(file_toolbar, textvariable=self.selection_summary_var, style=f"{self._style_prefix}.Panel.Muted.TLabel")
        label.grid(row=0, column=8, sticky="e", padx=(8, 0), pady=2)
        self._themed_panel_labels.append(label)

        self.files_list = tk.Listbox(files, selectmode=tk.EXTENDED)
        self.files_list.grid(row=1, column=0, sticky="nsew", padx=(6, 0), pady=(2, 6))
        self.files_list.bind("<<ListboxSelect>>", lambda _event: self._update_selection_summary())
        files_scroll = ttk.Scrollbar(files, orient="vertical", command=self.files_list.yview)
        files_scroll.grid(row=1, column=1, sticky="ns", padx=(0, 6), pady=(2, 6))
        self.files_list.configure(yscrollcommand=files_scroll.set)

        commit_box = ttk.LabelFrame(daily_tab, text="Commit", style=f"{self._style_prefix}.TLabelframe")
        commit_box.grid(row=2, column=0, sticky="ew", padx=0, pady=(4, 0))
        self._themed_labelframes.append(commit_box)
        commit_box.columnconfigure(1, weight=1)
        label = ttk.Label(commit_box, text="Commit message:", style=f"{self._style_prefix}.Panel.TLabel")
        label.grid(row=0, column=0, sticky="w", padx=6, pady=6)
        self._themed_panel_labels.append(label)
        entry = ttk.Entry(commit_box, textvariable=self.commit_msg_var, style=f"{self._style_prefix}.TEntry")
        entry.grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        self._themed_entries.append(entry)
        button = ttk.Button(commit_box, text="Save draft", command=self.save_fields_only, style=f"{self._style_prefix}.TButton")
        button.grid(row=0, column=2, padx=6, pady=6)
        self._themed_buttons.append(button)

        pychi_intro = ttk.LabelFrame(pychi_tab, text="Simple public upload", style=f"{self._style_prefix}.TLabelframe")
        pychi_intro.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 4))
        pychi_intro.columnconfigure(0, weight=1)
        self._themed_labelframes.append(pychi_intro)
        label = ttk.Label(pychi_intro, textvariable=self.branch_help_var, style=f"{self._style_prefix}.Panel.Muted.TLabel")
        label.grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))
        self._themed_panel_muted_labels.append(label)
        label = ttk.Label(pychi_intro, textvariable=self.public_summary_var, style=f"{self._style_prefix}.Panel.TLabel")
        label.grid(row=1, column=0, sticky="w", padx=8, pady=(0, 8))
        self._themed_panel_labels.append(label)

        pychi_branch = ttk.LabelFrame(pychi_tab, text="Public branch", style=f"{self._style_prefix}.TLabelframe")
        pychi_branch.grid(row=1, column=0, sticky="ew", padx=0, pady=4)
        pychi_branch.columnconfigure(1, weight=1)
        self._themed_labelframes.append(pychi_branch)
        label = ttk.Label(pychi_branch, text="Branch name:", style=f"{self._style_prefix}.Panel.TLabel")
        label.grid(row=0, column=0, sticky="w", padx=6, pady=6)
        self._themed_panel_labels.append(label)
        entry = ttk.Entry(pychi_branch, textvariable=self.public_branch_var, style=f"{self._style_prefix}.TEntry")
        entry.grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        self._themed_entries.append(entry)
        button = ttk.Button(pychi_branch, text="Create branch", command=self.create_public_branch, style=f"{self._style_prefix}.TButton")
        button.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 6))
        self._themed_buttons.append(button)

        pychi_actions = ttk.LabelFrame(pychi_tab, text="Pychi code flow", style=f"{self._style_prefix}.TLabelframe")
        pychi_actions.grid(row=2, column=0, sticky="ew", padx=0, pady=4)
        for i in range(2):
            pychi_actions.columnconfigure(i, weight=1)
        self._themed_labelframes.append(pychi_actions)
        public_buttons = (
            ("Refresh", self.refresh_status),
            ("Show non-library", self.show_pychi_code_files),
            ("Select non-library", self.select_pychi_code_files),
            ("Select private", self.select_likely_private_files_public),
            ("Stage selected", self.stage_selected_public),
            ("Commit", self.commit_changes),
            ("Push + upstream", self.push_remote_with_upstream),
            ("Copy checklist", self.copy_public_checklist),
        )
        for idx, (text, cmd) in enumerate(public_buttons):
            button = ttk.Button(pychi_actions, text=text, command=cmd, style=f"{self._style_prefix}.TButton")
            button.grid(row=idx // 2, column=idx % 2, sticky="ew", padx=4, pady=4)
            self._themed_buttons.append(button)

        pychi_files = ttk.LabelFrame(pychi_tab, text="Selected public-safe candidates", style=f"{self._style_prefix}.TLabelframe")
        pychi_files.grid(row=3, column=0, sticky="nsew", padx=0, pady=4)
        pychi_files.columnconfigure(0, weight=1)
        pychi_files.rowconfigure(2, weight=1)
        self._themed_labelframes.append(pychi_files)

        label = ttk.Label(pychi_files, text="Commit message:", style=f"{self._style_prefix}.Panel.TLabel")
        label.grid(row=0, column=0, sticky="w", padx=6, pady=(6, 2))
        self._themed_panel_labels.append(label)
        entry = ttk.Entry(pychi_files, textvariable=self.commit_msg_var, style=f"{self._style_prefix}.TEntry")
        entry.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 4))
        self._themed_entries.append(entry)
        label = ttk.Label(pychi_files, textvariable=self.public_selection_summary_var, style=f"{self._style_prefix}.Panel.Muted.TLabel")
        label.grid(row=1, column=1, sticky="e", padx=(0, 6), pady=(0, 4))
        self._themed_panel_muted_labels.append(label)
        self.public_files_list = tk.Listbox(pychi_files, selectmode=tk.EXTENDED)
        self.public_files_list.grid(row=2, column=0, sticky="nsew", padx=(6, 0), pady=(0, 6))
        self.public_files_list.bind("<<ListboxSelect>>", lambda _event: self._update_selection_summary())
        public_scroll = ttk.Scrollbar(pychi_files, orient="vertical", command=self.public_files_list.yview)
        public_scroll.grid(row=2, column=1, sticky="ns", padx=(0, 6), pady=(0, 6))
        self.public_files_list.configure(yscrollcommand=public_scroll.set)

        lower = ttk.PanedWindow(parent, orient="vertical")
        lower.grid(row=2, column=0, sticky="nsew", padx=8, pady=(4, 8))

        output = ttk.LabelFrame(lower, text="Command output", style=f"{self._style_prefix}.TLabelframe")
        output.columnconfigure(0, weight=1)
        output.rowconfigure(0, weight=1)
        self._themed_labelframes.append(output)
        self.output_text = tk.Text(output, wrap="word", height=12)
        self.output_text.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        out_scroll = ttk.Scrollbar(output, orient="vertical", command=self.output_text.yview)
        out_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 6), pady=6)
        self.output_text.configure(yscrollcommand=out_scroll.set)
        out_toolbar = ttk.Frame(output, style=f"{self._style_prefix}.Panel.TFrame")
        out_toolbar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 6))
        self._themed_panel_frames.append(out_toolbar)
        button = ttk.Button(out_toolbar, text="Clear output", command=self.clear_output, style=f"{self._style_prefix}.TButton")
        button.pack(side="left", padx=(0, 4))
        self._themed_buttons.append(button)
        button = ttk.Button(out_toolbar, text="Copy output", command=self.copy_output, style=f"{self._style_prefix}.TButton")
        button.pack(side="left", padx=4)
        self._themed_buttons.append(button)
        lower.add(output, weight=3)

        history = ttk.LabelFrame(lower, text="Recent update log", style=f"{self._style_prefix}.TLabelframe")
        history.columnconfigure(0, weight=1)
        history.rowconfigure(0, weight=1)
        self._themed_labelframes.append(history)
        self.log_text = tk.Text(history, wrap="word", height=12)
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        log_scroll = ttk.Scrollbar(history, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 6), pady=6)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_toolbar = ttk.Frame(history, style=f"{self._style_prefix}.Panel.TFrame")
        log_toolbar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 6))
        self._themed_panel_frames.append(log_toolbar)
        button = ttk.Button(log_toolbar, text="Copy log", command=self.copy_log, style=f"{self._style_prefix}.TButton")
        button.pack(side="left", padx=(0, 4))
        self._themed_buttons.append(button)
        button = ttk.Button(log_toolbar, text="Open data folder", command=self.open_data_folder, style=f"{self._style_prefix}.TButton")
        button.pack(side="left", padx=4)
        self._themed_buttons.append(button)
        lower.add(history, weight=2)

        status = ttk.Frame(parent, style=f"{self._style_prefix}.TFrame")
        status.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 8))
        status.columnconfigure(0, weight=1)
        self._themed_frames.append(status)
        label = ttk.Label(status, textvariable=self.status_var, style=f"{self._style_prefix}.Muted.TLabel")
        label.grid(row=0, column=0, sticky="w")
        self._themed_muted_labels.append(label)

    def _meta_label(self, parent, row, col, title, variable):
        box = ttk.Frame(parent, style=f"{self._style_prefix}.Panel.TFrame")
        box.grid(row=row, column=col, sticky="ew", padx=4, pady=2)
        box.columnconfigure(1, weight=1)
        self._themed_panel_frames.append(box)
        label = ttk.Label(box, text=f"{title}:", style=f"{self._style_prefix}.Panel.Muted.TLabel")
        label.grid(row=0, column=0, sticky="w")
        self._themed_panel_muted_labels.append(label)
        value = ttk.Label(box, textvariable=variable, style=f"{self._style_prefix}.Panel.TLabel")
        value.grid(row=0, column=1, sticky="w")
        self._themed_panel_labels.append(value)

    def set_guichi_page_theme(self, context):
        self.guichi_page_theme = context
        self._theme_tokens = resolve_chigit_theme(context)
        self._apply_theme()

    def _apply_theme(self):
        tokens = self._theme_tokens
        configure_ttk_styles(self.frame, self._style_prefix, tokens)

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
        for widget in self._themed_panel_muted_labels:
            try:
                widget.configure(style=f"{self._style_prefix}.Panel.Muted.TLabel")
            except Exception:
                pass
        for widget in self._themed_muted_labels:
            try:
                widget.configure(style=f"{self._style_prefix}.Muted.TLabel")
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

        apply_listbox_theme(self.files_list, tokens)
        apply_listbox_theme(self.public_files_list, tokens)
        apply_text_theme(self.output_text, tokens)
        apply_text_theme(self.log_text, tokens)

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
        return {"last_repo_root": "", "last_commit_message": "", "last_note": ""}

    def _save_config(self):
        self.config["last_repo_root"] = self.repo_var.get().strip()
        self.config["last_commit_message"] = self.commit_msg_var.get().strip()
        try:
            with open(self.config_path, "w", encoding="utf-8") as fh:
                json.dump(self.config, fh, indent=2, ensure_ascii=False)
        except Exception as exc:
            self._append_output("config write", f"failed to save config: {exc}")

    def _set_status(self, message):
        self.status_var.set(message)

    def _append_output(self, title, text):
        stamp = self._now_local()
        clean_text = (text or "").strip() or "(no output)"
        self.output_text.insert("end", f"\n[{stamp}] {title}\n{clean_text}\n")
        self.output_text.see("end")

    def _replace_log_view(self, text):
        self.log_text.delete("1.0", "end")
        self.log_text.insert("1.0", text)

    def _repo_root(self):
        return (self.repo_var.get() or "").strip()

    def _validate_repo(self, show_error=True):
        root = self._repo_root()
        if not root:
            if show_error:
                messagebox.showwarning("ChiGit Repo Update", "Choose a repo root first.")
            return None
        if not os.path.isdir(root):
            if show_error:
                messagebox.showerror("ChiGit Repo Update", f"Folder does not exist:\n{root}")
            return None
        if not os.path.isdir(os.path.join(root, ".git")):
            check = self._run_git(["rev-parse", "--git-dir"], root, quiet=True)
            if check["code"] != 0:
                if show_error:
                    messagebox.showerror("ChiGit Repo Update", f"Not a git repo:\n{root}")
                return None
        return root

    def _run_git(self, args, cwd, quiet=False):
        cmd = ["git"] + list(args)
        try:
            completed = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            merged = (stdout + ("\n" if stdout and stderr else "") + stderr).strip()
            if not quiet:
                self._append_output("git " + " ".join(args), merged)
            return {"code": completed.returncode, "stdout": stdout, "stderr": stderr, "text": merged}
        except FileNotFoundError:
            msg = "git executable was not found on this system PATH."
            if not quiet:
                self._append_output("git " + " ".join(args), msg)
            return {"code": 127, "stdout": "", "stderr": msg, "text": msg}
        except Exception as exc:
            msg = f"git command failed to launch: {exc}"
            if not quiet:
                self._append_output("git " + " ".join(args), msg)
            return {"code": 1, "stdout": "", "stderr": msg, "text": msg}

    def choose_repo(self):
        chosen = filedialog.askdirectory(initialdir=self.repo_var.get() or os.path.expanduser("~"))
        if chosen:
            self.repo_var.set(chosen)
            self._save_config()
            self.refresh_status()

    def open_data_folder(self):
        try:
            subprocess.Popen(["xdg-open", self.data_dir], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._set_status(f"Opened data folder: {self.data_dir}")
        except Exception as exc:
            self._append_output("open folder", f"Could not open data folder: {exc}")

    def clear_output(self):
        self.output_text.delete("1.0", "end")
        self._set_status("Cleared output panel.")

    def copy_output(self):
        self._copy_text(self.output_text.get("1.0", "end-1c"), "command output")

    def copy_log(self):
        self._copy_text(self.log_text.get("1.0", "end-1c"), "update log")

    def _copy_text(self, text, label):
        if not text.strip():
            messagebox.showinfo("ChiGit Repo Update", f"No {label} to copy.")
            return
        try:
            self.frame.clipboard_clear()
            self.frame.clipboard_append(text)
            self._set_status(f"Copied {label} to clipboard.")
        except Exception as exc:
            self._append_output("clipboard", f"Failed to copy {label}: {exc}")

    def copy_status_summary(self):
        root = self._repo_root()
        summary = (
            f"repo={root}\n"
            f"branch={self.branch_var.get()}\n"
            f"head={self.head_var.get()}\n"
            f"upstream={self.upstream_var.get()}\n"
            f"ahead_behind={self.ahead_behind_var.get()}\n"
            f"last_commit={self.last_commit_var.get()}\n"
            f"changed_files={len(self.file_rows)}"
        )
        self._copy_text(summary, "status summary")

    def refresh_status(self):
        root = self._validate_repo(show_error=False)
        if not root:
            self.branch_var.set("(not set)")
            self.head_var.set("(not set)")
            self.upstream_var.set("(not set)")
            self.ahead_behind_var.set("ahead 0 / behind 0")
            self.last_commit_var.set("(not set)")
            self.files_list.delete(0, "end")
            self.file_rows = []
            self.visible_rows = []
            self.public_visible_rows = []
            self.public_files_list.delete(0, "end")
            self._update_selection_summary()
            self._refresh_log_view()
            self._refresh_public_summary()
            self._set_status("Pick a valid git repo to begin.")
            return

        self.config["last_repo_root"] = root
        self._save_config()

        status_res = self._run_git(["status", "--short", "--branch"], root, quiet=True)
        branch_res = self._run_git(["branch", "--show-current"], root, quiet=True)
        head_res = self._run_git(["rev-parse", "--short", "HEAD"], root, quiet=True)
        upstream_res = self._run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"], root, quiet=True)
        ahead_behind_res = self._run_git(["rev-list", "--left-right", "--count", "HEAD...@{upstream}"], root, quiet=True)
        last_res = self._run_git(["log", "-1", "--pretty=%h %ad %s", "--date=short"], root, quiet=True)

        _, file_rows = self._parse_status(status_res["stdout"])
        self.file_rows = file_rows

        self.branch_var.set((branch_res["stdout"] or "").strip() or "(detached/unknown)")
        self.head_var.set((head_res["stdout"] or "").strip() or "(none)")
        upstream = (upstream_res["stdout"] or "").strip()
        if upstream_res["code"] == 0 and upstream:
            self.upstream_var.set(upstream)
            self.ahead_behind_var.set(self._parse_ahead_behind(ahead_behind_res["stdout"]))
        else:
            self.upstream_var.set("(no upstream)")
            self.ahead_behind_var.set("ahead ? / behind ?")
        self.last_commit_var.set((last_res["stdout"] or "").strip() or "(none)")

        self._apply_file_filter(preserve_selection=False)
        self._refresh_public_file_list(preserve_selection=False)
        self._refresh_log_view()
        self._refresh_public_summary()
        self._set_status(f"Status refreshed for {root}")

    def _parse_status(self, text):
        branch = ""
        file_rows = []
        for raw_line in (text or "").splitlines():
            line = raw_line.rstrip("\n")
            if not line:
                continue
            if line.startswith("## "):
                branch = line[3:].strip()
                continue
            status = line[:2]
            path = line[3:] if len(line) > 3 else ""
            original_path = path
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            file_rows.append({
                "status": status,
                "path": path,
                "raw_path": original_path,
                "staged": status[0] not in (" ", "?"),
                "unstaged": status[1] not in (" ",),
                "untracked": status == "??",
            })
        return branch, file_rows

    def _parse_ahead_behind(self, text):
        try:
            left, right = (text or "").strip().split()
            return f"ahead {left} / behind {right}"
        except Exception:
            return "ahead ? / behind ?"

    def _selected_visible_rows(self):
        rows = []
        for index in self.files_list.curselection():
            if 0 <= index < len(self.visible_rows):
                rows.append(self.visible_rows[index])
        return rows

    def _selected_public_rows(self):
        rows = []
        for index in self.public_files_list.curselection():
            if 0 <= index < len(self.public_visible_rows):
                rows.append(self.public_visible_rows[index])
        return rows

    def _selected_paths(self):
        return [row["path"] for row in self._selected_visible_rows()]

    def _selected_public_paths(self):
        return [row["path"] for row in self._selected_public_rows()]

    def select_all_files(self):
        self.files_list.selection_set(0, "end")
        self._update_selection_summary()

    def clear_file_selection(self):
        self.files_list.selection_clear(0, "end")
        self._update_selection_summary()

    def select_staged_files(self):
        self._select_matching_rows(lambda row: row["staged"])

    def select_unstaged_files(self):
        self._select_matching_rows(lambda row: row["unstaged"] or row["untracked"])

    def select_tracked_changes(self):
        self._select_matching_rows(lambda row: not row["untracked"])

    def select_untracked_files(self):
        self._select_matching_rows(lambda row: row["untracked"])

    def _is_likely_private_row(self, row):
        path = row["path"]
        if path in _PRIVATE_EXACT_PATHS:
            return True
        if any(path.startswith(prefix) for prefix in _PRIVATE_PREFIXES):
            return True
        if path.endswith(".jsonl") or path.endswith(".log") or path.endswith(".tmp"):
            return True
        if path.endswith(".pyc") or "/__pycache__/" in f"/{path}":
            return True
        return False

    def _is_likely_public_row(self, row):
        path = row["path"]
        name = os.path.basename(path)
        if self._is_likely_private_row(row):
            return False
        if name in _PUBLIC_FILE_NAMES:
            return True
        if path.endswith(".py"):
            return True
        if path.startswith("chi_ain/") and path.endswith((".json", ".md")):
            return True
        if path.startswith("chi_git/") and "/page_" in path and path.endswith((".json", ".md")):
            return True
        if path.startswith("chi_los/") and "/page_" in path and path.endswith((".json", ".md")):
            return True
        if path.startswith("chi_gui/") and path.endswith((".json", ".md")):
            return True
        if path.startswith("chitsheet/") and path.endswith((".json", ".md")):
            return True
        if path.startswith("gui_files/") and path.endswith(".py") and "/state/" not in path and "/config/" not in path:
            return True
        return False

    def _is_changed_or_added_row(self, row):
        return "D" not in row["status"]

    def _is_pychi_code_row(self, row):
        return self._is_changed_or_added_row(row) and self._is_likely_public_row(row)

    def _select_matching_rows(self, predicate):
        self.files_list.selection_clear(0, "end")
        for idx, row in enumerate(self.visible_rows):
            if predicate(row):
                self.files_list.selection_set(idx)
        self._update_selection_summary()

    def select_likely_public_files(self):
        self._select_matching_rows(self._is_likely_public_row)
        self._set_status("Selected files that look public-safe by default. Review before staging.")

    def select_likely_private_files(self):
        self._select_matching_rows(self._is_likely_private_row)
        self._set_status("Selected files that look private or machine-local.")

    def select_likely_private_files_public(self):
        self._select_matching_public_rows(self._is_likely_private_row)
        self._set_status("Selected private-looking files in the Pychi Code tab review list.")

    def filter_likely_public_files(self):
        self.filter_var.set("")
        self.visible_rows = [row for row in self.file_rows if self._is_likely_public_row(row)]
        self.files_list.delete(0, "end")
        for row in self.visible_rows:
            self.files_list.insert("end", f"[{row['status']}] {row['path']}   <likely public>")
        self._update_selection_summary()
        self._set_status("Showing likely public-safe files.")

    def filter_likely_private_files(self):
        self.filter_var.set("")
        self.visible_rows = [row for row in self.file_rows if self._is_likely_private_row(row)]
        self.files_list.delete(0, "end")
        for row in self.visible_rows:
            self.files_list.insert("end", f"[{row['status']}] {row['path']}   <likely private>")
        self._update_selection_summary()
        self._set_status("Showing likely private or machine-local files.")

    def copy_public_checklist(self):
        branch = self.branch_var.get()
        text = (
            "Public upload checklist\n\n"
            f"Current branch: {branch}\n"
            "- Use a separate public branch.\n"
            "- Refresh changed files.\n"
            "- Use Select likely public as a starting point.\n"
            "- Do not use Stage all for a first public push.\n"
            "- Keep out chigit_data, gui state/config, logs, jsonl, VPN/private config, and personal command files.\n"
            "- Stage selected reviewed files only.\n"
            "- Commit with a clear public-safe message.\n"
            "- Use Push + upstream the first time on a new branch.\n"
        )
        self._copy_text(text, "public upload checklist")

    def _apply_file_filter(self, preserve_selection=True):
        previous_paths = set(self._selected_paths()) if preserve_selection else set()
        needle = (self.filter_var.get() or "").strip().lower()
        if needle:
            self.visible_rows = [row for row in self.file_rows if needle in row["path"].lower() or needle in row["status"].lower()]
        else:
            self.visible_rows = list(self.file_rows)

        self.files_list.delete(0, "end")
        for row in self.visible_rows:
            tags = []
            if row["staged"]:
                tags.append("staged")
            if row["unstaged"]:
                tags.append("unstaged")
            if row["untracked"]:
                tags.append("untracked")
            tag_text = ", ".join(tags)
            self.files_list.insert("end", f"[{row['status']}] {row['path']}" + (f"   <{tag_text}>" if tag_text else ""))

        for idx, row in enumerate(self.visible_rows):
            if row["path"] in previous_paths:
                self.files_list.selection_set(idx)
        self._update_selection_summary()

    def _refresh_public_file_list(self, preserve_selection=True):
        previous_paths = set(self._selected_public_paths()) if preserve_selection else set()
        self.public_visible_rows = [row for row in self.file_rows if self._is_pychi_code_row(row)]
        self.public_files_list.delete(0, "end")
        for row in self.public_visible_rows:
            tags = []
            if row["staged"]:
                tags.append("staged")
            if row["untracked"]:
                tags.append("new")
            elif row["unstaged"]:
                tags.append("changed")
            tag_text = ", ".join(tags) or "review"
            self.public_files_list.insert("end", f"[{row['status']}] {row['path']}   <{tag_text}>")
        for idx, row in enumerate(self.public_visible_rows):
            if row["path"] in previous_paths:
                self.public_files_list.selection_set(idx)
        self._update_selection_summary()

    def _select_matching_public_rows(self, predicate):
        self.public_files_list.selection_clear(0, "end")
        for idx, row in enumerate(self.public_visible_rows):
            if predicate(row):
                self.public_files_list.selection_set(idx)
        self._update_selection_summary()

    def show_pychi_code_files(self):
        self._refresh_public_file_list(preserve_selection=False)
        self._set_status("Showing changed or added non-library files for public upload review.")

    def select_pychi_code_files(self):
        self._refresh_public_file_list(preserve_selection=False)
        self._select_matching_public_rows(self._is_pychi_code_row)
        self._set_status("Selected changed or added non-library files for the Pychi Code flow.")

    def _update_selection_summary(self):
        count = len(self.files_list.curselection())
        total = len(self.visible_rows)
        self.selection_summary_var.set(f"{count} selected / {total} shown")
        public_count = len(self.public_files_list.curselection())
        public_total = len(self.public_visible_rows)
        self.public_selection_summary_var.set(f"{public_count} selected / {public_total} shown")
        self._refresh_public_summary()

    def _refresh_public_summary(self):
        private_count = sum(1 for row in self.visible_rows if self._is_likely_private_row(row))
        public_count = sum(1 for row in self.visible_rows if self._is_likely_public_row(row))
        selected_rows = self._selected_visible_rows()
        public_selected_rows = self._selected_public_rows()
        all_selected_rows = selected_rows + [row for row in public_selected_rows if row not in selected_rows]
        selected_private = sum(1 for row in all_selected_rows if self._is_likely_private_row(row))
        selected_public = sum(1 for row in all_selected_rows if self._is_likely_public_row(row))
        self.public_summary_var.set(
            f"shown: {public_count} likely public / {private_count} likely private   "
            f"selected: {selected_public} public / {selected_private} private"
        )

    def stage_selected(self):
        root = self._validate_repo()
        if not root:
            return
        paths = self._selected_paths()
        if not paths:
            messagebox.showinfo("ChiGit Repo Update", "Select one or more changed files first.")
            return
        res = self._run_git(["add", "--"] + paths, root)
        self._log_action("stage_selected", root, paths, res)
        self.refresh_status()

    def stage_selected_public(self):
        root = self._validate_repo()
        if not root:
            return
        paths = self._selected_public_paths()
        if not paths:
            messagebox.showinfo("ChiGit Repo Update", "Select one or more Pychi Code files first.")
            return
        res = self._run_git(["add", "--"] + paths, root)
        self._log_action("stage_selected_public", root, paths, res)
        self.refresh_status()

    def unstage_selected(self):
        root = self._validate_repo()
        if not root:
            return
        paths = self._selected_paths()
        if not paths:
            messagebox.showinfo("ChiGit Repo Update", "Select one or more staged files first.")
            return
        res = self._run_git(["restore", "--staged", "--"] + paths, root)
        self._log_action("unstage_selected", root, paths, res)
        self.refresh_status()

    def stage_all(self):
        root = self._validate_repo()
        if not root:
            return
        res = self._run_git(["add", "-A"], root)
        self._log_action("stage_all", root, ["*"], res)
        self.refresh_status()

    def commit_changes(self):
        root = self._validate_repo()
        if not root:
            return
        message = (self.commit_msg_var.get() or "").strip()
        if not message:
            messagebox.showwarning("ChiGit Repo Update", "Add a commit message first.")
            return
        diff_res = self._run_git(["diff", "--cached", "--name-only"], root, quiet=True)
        staged_files = [line.strip() for line in diff_res["stdout"].splitlines() if line.strip()]
        if not staged_files:
            messagebox.showinfo("ChiGit Repo Update", "Nothing is staged. Stage files first.")
            return
        if not messagebox.askyesno("ChiGit Repo Update", f"Commit {len(staged_files)} staged file(s)?\n\nMessage:\n{message}"):
            self._set_status("Commit cancelled.")
            return
        res = self._run_git(["commit", "-m", message], root)
        self.config["last_commit_message"] = message
        self._save_config()
        self._log_action("commit", root, staged_files, res, extra={"commit_message": message})
        self.refresh_status()

    def fetch_remote(self):
        self._run_simple_remote_action("fetch", ["fetch", "--all", "--prune"])

    def pull_remote(self):
        root = self._validate_repo()
        if not root:
            return
        if not messagebox.askyesno("ChiGit Repo Update", "Run git pull --ff-only ?"):
            self._set_status("Pull cancelled.")
            return
        res = self._run_git(["pull", "--ff-only"], root)
        self._log_action("pull", root, [], res)
        self.refresh_status()

    def push_remote(self):
        root = self._validate_repo()
        if not root:
            return
        if not messagebox.askyesno("ChiGit Repo Update", "Run git push on the current branch?"):
            self._set_status("Push cancelled.")
            return
        res = self._run_git(["push"], root)
        self._log_action("push", root, [], res)
        self.refresh_status()

    def push_remote_with_upstream(self):
        root = self._validate_repo()
        if not root:
            return
        branch = (self.branch_var.get() or "").strip()
        if not branch or branch.startswith("("):
            messagebox.showwarning("ChiGit Repo Update", "Could not determine the current branch.")
            return
        prompt = (
            f"Run first-time push for branch '{branch}'?\n\n"
            "This runs:\n"
            f"git push --set-upstream origin {branch}"
        )
        if not messagebox.askyesno("ChiGit Repo Update", prompt):
            self._set_status("Push with upstream cancelled.")
            return
        res = self._run_git(["push", "--set-upstream", "origin", branch], root)
        self._log_action("push_with_upstream", root, [], res, extra={"target_branch": branch})
        self.refresh_status()

    def create_public_branch(self):
        root = self._validate_repo()
        if not root:
            return
        branch_name = (self.public_branch_var.get() or "").strip()
        if not branch_name:
            branch_name = simpledialog.askstring("ChiGit Repo Update", "New public branch name:", parent=self.frame)
            branch_name = (branch_name or "").strip()
            self.public_branch_var.set(branch_name)
        if not branch_name:
            return
        if not messagebox.askyesno(
            "ChiGit Repo Update",
            f"Create and switch to branch '{branch_name}' from the current branch?",
        ):
            self._set_status("Create branch cancelled.")
            return
        res = self._run_git(["checkout", "-b", branch_name], root)
        self._log_action("create_public_branch", root, [], res, extra={"target_branch": branch_name})
        self.refresh_status()

    def _run_simple_remote_action(self, action_name, git_args):
        root = self._validate_repo()
        if not root:
            return
        res = self._run_git(git_args, root)
        self._log_action(action_name, root, [], res)
        self.refresh_status()

    def save_fields_only(self):
        self._save_config()
        self._set_status("Saved repo root and commit draft.")

    def _log_action(self, action, repo_root, paths, result, extra=None):
        payload = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "repo_root": repo_root,
            "branch_display": self.branch_var.get(),
            "head_display": self.head_var.get(),
            "upstream_display": self.upstream_var.get(),
            "ahead_behind_display": self.ahead_behind_var.get(),
            "paths": list(paths),
            "result_code": result.get("code"),
            "result_text": result.get("text", "")[:4000],
        }
        if extra:
            payload.update(extra)
        try:
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as exc:
            self._append_output("log write", f"failed to write repo update log: {exc}")
        self._refresh_log_view()

    def _refresh_log_view(self):
        items = []
        try:
            with open(self.log_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        items.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            pass
        items = items[-20:]
        lines = []
        for item in reversed(items):
            when = item.get("timestamp_utc", "")
            action = item.get("action", "")
            code = item.get("result_code", "")
            paths = item.get("paths", [])
            msg = item.get("commit_message", "")
            branch = item.get("branch_display", "")
            lines.append(f"{when} | {action} | code={code} | {branch}")
            if paths:
                lines.append(f"paths: {', '.join(paths[:8])}")
            if msg:
                lines.append(f"commit: {msg}")
            lines.append("")
        self._replace_log_view("\n".join(lines).strip() or "(no repo update log entries yet)")

    def _now_local(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
