import json
import os
import shlex
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from chi_git.theme_support import (
    apply_text_theme,
    configure_ttk_styles,
    resolve_chigit_theme,
)


class ChiGitSSHDockPage:
    def __init__(self, parent=None, app=None, page_key="", page_folder="", *args, **kwargs):
        self.app = kwargs.pop("controller", app)
        self.page_key = kwargs.pop("page_context", page_key)
        self.page_folder = kwargs.pop("page_folder", page_folder)

        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.data_dir = os.path.join(self.base_dir, "chigit_data")
        self.config_path = os.path.join(self.data_dir, "sshdock_config.json")
        os.makedirs(self.data_dir, exist_ok=True)
        self._ensure_json(self.config_path, {"last_repo_root": "", "last_public_key_path": os.path.expanduser("~/.ssh/id_ed25519.pub"), "last_test_host": "git@github.com"})
        self.config = self._load_config()

        self.parent = parent
        self.frame = ttk.Frame(parent) if parent is not None else ttk.Frame()
        self.guichi_page_theme = None
        self._theme_tokens = resolve_chigit_theme()
        self._style_prefix = f"ChiGitSSHDock.{id(self)}"

        self.repo_var = tk.StringVar(value=self.config.get("last_repo_root", ""))
        self.agent_var = tk.StringVar(value="(unknown)")
        self.sock_var = tk.StringVar(value="(unknown)")
        self.keys_var = tk.StringVar(value="(unknown)")
        self.remote_var = tk.StringVar(value="(unknown)")
        self.remote_mode_var = tk.StringVar(value="(unknown)")
        self.status_var = tk.StringVar(value="ready")
        self.public_key_path_var = tk.StringVar(value=self.config.get("last_public_key_path", os.path.expanduser("~/.ssh/id_ed25519.pub")))
        self.test_host_var = tk.StringVar(value=self.config.get("last_test_host", "git@github.com"))
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
        self._write_public_preview_help()
        self._write_output_help()
        self._set_status("Ready. Refresh SSH status to begin.")
        self.frame.after(150, self.refresh_all)

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
        parent.rowconfigure(6, weight=1)
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
        button = ttk.Button(repo_box, text="Refresh all", command=self.refresh_all, style=f"{self._style_prefix}.TButton")
        button.grid(row=0, column=3, padx=6, pady=6)
        self._themed_buttons.append(button)

        status_box = ttk.LabelFrame(parent, text="SSH status", style=f"{self._style_prefix}.TLabelframe")
        status_box.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        for i in range(3):
            status_box.columnconfigure(i, weight=1)
        self._themed_labelframes.append(status_box)
        self._meta_label(status_box, 0, 0, "Agent", self.agent_var)
        self._meta_label(status_box, 0, 1, "SSH_AUTH_SOCK", self.sock_var)
        self._meta_label(status_box, 0, 2, "Loaded keys", self.keys_var)
        self._meta_label(status_box, 1, 0, "Remote", self.remote_var)
        self._meta_label(status_box, 1, 1, "Remote mode", self.remote_mode_var)
        self._meta_label(status_box, 1, 2, "Test host", self.test_host_var)

        public_box = ttk.LabelFrame(parent, text="Public key", style=f"{self._style_prefix}.TLabelframe")
        public_box.grid(row=2, column=0, sticky="ew", padx=8, pady=4)
        public_box.columnconfigure(1, weight=1)
        self._themed_labelframes.append(public_box)
        label = ttk.Label(public_box, text="Public key path:", style=f"{self._style_prefix}.Panel.Muted.TLabel")
        label.grid(row=0, column=0, sticky="w", padx=6, pady=6)
        self._themed_panel_muted_labels.append(label)
        entry = ttk.Entry(public_box, textvariable=self.public_key_path_var, style=f"{self._style_prefix}.TEntry")
        entry.grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        self._themed_entries.append(entry)
        button = ttk.Button(public_box, text="Pick", command=self.pick_public_key, style=f"{self._style_prefix}.TButton")
        button.grid(row=0, column=2, padx=6, pady=6)
        self._themed_buttons.append(button)
        button = ttk.Button(public_box, text="Show public key", command=self.show_public_key, style=f"{self._style_prefix}.TButton")
        button.grid(row=0, column=3, padx=6, pady=6)
        self._themed_buttons.append(button)

        actions_box = ttk.LabelFrame(parent, text="Actions", style=f"{self._style_prefix}.TLabelframe")
        actions_box.grid(row=3, column=0, sticky="ew", padx=8, pady=4)
        for i in range(6):
            actions_box.columnconfigure(i, weight=1)
        self._themed_labelframes.append(actions_box)
        for col, (text, cmd) in enumerate((
            ("Check agent", self.check_agent),
            ("List keys", self.list_keys),
            ("List ~/.ssh", self.list_ssh_dir),
            ("Test GitHub SSH", self.test_github_ssh),
            ("Check remote", self.check_remote_mode),
            ("Copy remote", self.copy_remote),
        )):
            button = ttk.Button(actions_box, text=text, command=cmd, style=f"{self._style_prefix}.TButton")
            button.grid(row=0, column=col, sticky="ew", padx=4, pady=6)
            self._themed_buttons.append(button)

        preview_box = ttk.LabelFrame(parent, text="Public key preview", style=f"{self._style_prefix}.TLabelframe")
        preview_box.grid(row=4, column=0, sticky="nsew", padx=8, pady=4)
        preview_box.columnconfigure(0, weight=1)
        preview_box.rowconfigure(0, weight=1)
        self._themed_labelframes.append(preview_box)
        self.public_text = tk.Text(preview_box, wrap="word", height=8)
        self.public_text.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        preview_scroll = ttk.Scrollbar(preview_box, orient="vertical", command=self.public_text.yview)
        preview_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 6), pady=6)
        self.public_text.configure(yscrollcommand=preview_scroll.set)
        preview_toolbar = ttk.Frame(preview_box, style=f"{self._style_prefix}.Panel.TFrame")
        preview_toolbar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 6))
        self._themed_panel_frames.append(preview_toolbar)
        button = ttk.Button(preview_toolbar, text="Copy public key", command=self.copy_public_key, style=f"{self._style_prefix}.TButton")
        button.pack(side="left", padx=(0, 4))
        self._themed_buttons.append(button)
        button = ttk.Button(preview_toolbar, text="Clear preview", command=lambda: self.public_text.delete("1.0", "end"), style=f"{self._style_prefix}.TButton")
        button.pack(side="left", padx=4)
        self._themed_buttons.append(button)

        output_box = ttk.LabelFrame(parent, text="SSH output", style=f"{self._style_prefix}.TLabelframe")
        output_box.grid(row=6, column=0, sticky="nsew", padx=8, pady=(4, 8))
        output_box.columnconfigure(0, weight=1)
        output_box.rowconfigure(0, weight=1)
        self._themed_labelframes.append(output_box)
        self.output_text = tk.Text(output_box, wrap="word", height=12)
        self.output_text.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        output_scroll = ttk.Scrollbar(output_box, orient="vertical", command=self.output_text.yview)
        output_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 6), pady=6)
        self.output_text.configure(yscrollcommand=output_scroll.set)
        output_toolbar = ttk.Frame(output_box, style=f"{self._style_prefix}.Panel.TFrame")
        output_toolbar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 6))
        self._themed_panel_frames.append(output_toolbar)
        button = ttk.Button(output_toolbar, text="Copy output", command=self.copy_output, style=f"{self._style_prefix}.TButton")
        button.pack(side="left", padx=(0, 4))
        self._themed_buttons.append(button)
        button = ttk.Button(output_toolbar, text="Clear output", command=lambda: self.output_text.delete("1.0", "end"), style=f"{self._style_prefix}.TButton")
        button.pack(side="left", padx=4)
        self._themed_buttons.append(button)

        status = ttk.Frame(parent, style=f"{self._style_prefix}.TFrame")
        status.grid(row=7, column=0, sticky="ew", padx=8, pady=(0, 8))
        status.columnconfigure(0, weight=1)
        self._themed_frames.append(status)
        label = ttk.Label(status, textvariable=self.status_var, style=f"{self._style_prefix}.Muted.TLabel")
        label.grid(row=0, column=0, sticky="w")
        self._themed_muted_labels.append(label)

    def _ensure_json(self, path, payload):
        if os.path.isfile(path):
            return
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)

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
            "last_public_key_path": self.public_key_path_var.get().strip(),
            "last_test_host": self.test_host_var.get().strip() or "git@github.com",
        }
        try:
            with open(self.config_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
            self.config = payload
        except Exception as exc:
            self._append_output("config write", f"Failed to save SSHDock config: {exc}")

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
        apply_text_theme(self.public_text, self._theme_tokens)
        apply_text_theme(self.output_text, self._theme_tokens)

    def _meta_label(self, parent, row, col, title, variable):
        box = ttk.Frame(parent, style=f"{self._style_prefix}.Panel.TFrame")
        box.grid(row=row, column=col, sticky="ew", padx=4, pady=2)
        box.columnconfigure(1, weight=1)
        self._themed_panel_frames.append(box)
        label = ttk.Label(box, text=f"{title}:", style=f"{self._style_prefix}.Panel.Muted.TLabel")
        label.grid(row=0, column=0, sticky="w")
        self._themed_panel_muted_labels.append(label)
        label = ttk.Label(box, textvariable=variable, style=f"{self._style_prefix}.Panel.TLabel")
        label.grid(row=0, column=1, sticky="w")
        self._themed_panel_labels.append(label)

    def _set_status(self, message):
        self.status_var.set(message)

    def _write_public_preview_help(self):
        self.public_text.delete("1.0", "end")
        self.public_text.insert(
            "1.0",
            "Public key preview is empty.\n\nChoose a public key file and use 'Show public key' to load it here."
        )

    def _write_output_help(self):
        if self.output_text.get("1.0", "end-1c").strip():
            return
        self.output_text.delete("1.0", "end")
        self.output_text.insert(
            "1.0",
            "SSH output is empty.\n\nRun an SSH action to capture agent, key, remote, or test output here."
        )

    def _append_output(self, title, text):
        from datetime import datetime
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        clean_text = (text or "").strip() or "(no output)"
        if self.output_text.get("1.0", "end-1c").startswith("SSH output is empty."):
            self.output_text.delete("1.0", "end")
        self.output_text.insert("end", f"\n[{stamp}] {title}\n{clean_text}\n")
        self.output_text.see("end")

    def _run(self, cmd, cwd=None):
        try:
            completed = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            merged = (stdout + ("\n" if stdout and stderr else "") + stderr).strip()
            return {"code": completed.returncode, "stdout": stdout, "stderr": stderr, "text": merged}
        except FileNotFoundError:
            return {"code": 127, "stdout": "", "stderr": "command not found", "text": "command not found"}
        except Exception as exc:
            return {"code": 1, "stdout": "", "stderr": str(exc), "text": str(exc)}

    def choose_repo(self):
        chosen = filedialog.askdirectory(initialdir=self.repo_var.get() or os.path.expanduser("~"))
        if chosen:
            self.repo_var.set(chosen)
            self._save_config()
            self.refresh_all()

    def pick_public_key(self):
        chosen = filedialog.askopenfilename(initialdir=os.path.expanduser("~/.ssh"))
        if chosen:
            self.public_key_path_var.set(chosen)
            self._save_config()
            self._set_status("Selected public key path.")

    def refresh_all(self):
        self._save_config()
        self.check_agent()
        self.list_keys()
        self.check_remote_mode()

    def check_agent(self):
        sock = os.environ.get("SSH_AUTH_SOCK", "")
        if sock:
            self.sock_var.set(sock)
            self.agent_var.set("running")
            self._append_output("check agent", f"SSH_AUTH_SOCK present: {sock}")
            self._set_status("SSH agent socket detected.")
        else:
            self.sock_var.set("(missing)")
            self.agent_var.set("not visible")
            self._append_output("check agent", "SSH_AUTH_SOCK is not set in this session.")
            self._set_status("No SSH agent visible in this session.")

    def list_keys(self):
        res = self._run(["ssh-add", "-l"])
        if res["code"] == 0:
            lines = [line for line in res["text"].splitlines() if line.strip()]
            self.keys_var.set(f"{len(lines)} key(s) loaded")
        elif "The agent has no identities" in res["text"]:
            self.keys_var.set("0 keys loaded")
        else:
            self.keys_var.set("(unknown)")
        self._append_output("ssh-add -l", res["text"])
        self._set_status("Listed SSH agent identities.")

    def list_ssh_dir(self):
        ssh_dir = os.path.expanduser("~/.ssh")
        res = self._run(["ls", "-la", ssh_dir])
        self._append_output("ls -la ~/.ssh", res["text"])
        self._set_status("Listed ~/.ssh contents.")

    def show_public_key(self):
        path = os.path.expanduser(self.public_key_path_var.get().strip())
        if not path:
            messagebox.showwarning("SSHDock", "Choose a public key file first.")
            return
        if not os.path.isfile(path):
            messagebox.showerror("SSHDock", f"Public key file not found:\n{path}")
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                content = fh.read().strip()
            self.public_text.delete("1.0", "end")
            self.public_text.insert("1.0", content)
            self._save_config()
            self._append_output("show public key", f"Loaded public key from {path}")
            self._set_status("Public key loaded into preview.")
        except Exception as exc:
            self._append_output("show public key", f"Failed to read public key: {exc}")

    def copy_public_key(self):
        text = self.public_text.get("1.0", "end-1c")
        if not text.strip():
            messagebox.showinfo("SSHDock", "No public key text to copy.")
            return
        try:
            self.frame.clipboard_clear()
            self.frame.clipboard_append(text)
            self._set_status("Copied public key to clipboard.")
        except Exception as exc:
            self._append_output("copy public key", f"Clipboard copy failed: {exc}")

    def test_github_ssh(self):
        host = self.test_host_var.get().strip() or "git@github.com"
        self._save_config()
        cmd = ["ssh", "-T", host]
        res = self._run(cmd)
        self._append_output(" ".join(shlex.quote(part) for part in cmd), res["text"])
        if "successfully authenticated" in res["text"].lower():
            self._set_status("SSH test succeeded.")
        else:
            self._set_status("SSH test finished. Review output.")

    def _repo_root(self):
        return (self.repo_var.get() or "").strip()

    def check_remote_mode(self):
        root = self._repo_root()
        if not root or not os.path.isdir(root):
            self.remote_var.set("(repo not set)")
            self.remote_mode_var.set("(unknown)")
            self._append_output("check remote", "Choose a valid repo to inspect remote settings.")
            return
        res = self._run(["git", "remote", "get-url", "origin"], cwd=root)
        remote = (res["stdout"] or "").strip()
        if res["code"] != 0 or not remote:
            self.remote_var.set("(unavailable)")
            self.remote_mode_var.set("(unknown)")
            self._append_output("git remote get-url origin", res["text"])
            self._set_status("Could not read repo remote.")
            return
        self.remote_var.set(remote)
        if remote.startswith("git@") or remote.startswith("ssh://"):
            mode = "ssh"
        elif remote.startswith("https://"):
            mode = "https"
        else:
            mode = "other"
        self.remote_mode_var.set(mode)
        self._append_output("git remote get-url origin", remote)
        self._set_status(f"Remote mode detected: {mode}")

    def copy_remote(self):
        remote = self.remote_var.get().strip()
        if not remote or remote.startswith("("):
            messagebox.showinfo("SSHDock", "No remote URL to copy.")
            return
        try:
            self.frame.clipboard_clear()
            self.frame.clipboard_append(remote)
            self._set_status("Copied remote URL to clipboard.")
        except Exception as exc:
            self._append_output("copy remote", f"Clipboard copy failed: {exc}")

    def copy_output(self):
        text = self.output_text.get("1.0", "end-1c")
        if not text.strip() or text.startswith("SSH output is empty."):
            messagebox.showinfo("SSHDock", "No output text to copy.")
            return
        try:
            self.frame.clipboard_clear()
            self.frame.clipboard_append(text)
            self._set_status("Copied output to clipboard.")
        except Exception as exc:
            self._append_output("copy output", f"Clipboard copy failed: {exc}")
