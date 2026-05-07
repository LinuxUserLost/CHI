"""
Claude Workstation

Small Claude-specific embedded terminal page for chi_ain.

Features:
- choose project root
- start an interactive shell in that root
- launch Claude into the live shell
- long transcript view
- easy transcript save
"""

import datetime
import os
import queue
import re
import shlex
import shutil
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from gui_files import interaction_support

try:
    import fcntl
    import pty
    import select
    import struct
    import termios
    PTY_AVAILABLE = True
except Exception:
    PTY_AVAILABLE = False


ANSI_CSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
ANSI_OSC_RE = re.compile(r"\x1B\][^\x07\x1B]*(?:\x07|\x1B\\)")
ANSI_OTHER_RE = re.compile(r"\x1B[@-Z\\-_]")


def _strip_ansi(text: str) -> str:
    text = ANSI_OSC_RE.sub("", text)
    text = ANSI_CSI_RE.sub("", text)
    text = ANSI_OTHER_RE.sub("", text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def _find_project_root() -> str:
    here = Path(__file__).resolve()
    for candidate in [here.parent, *here.parents]:
        if (candidate / "guichi.py").exists():
            return str(candidate)
    try:
        return os.getcwd()
    except Exception:
        return os.path.expanduser("~")


def _bind_scroll(widget):
    interaction_support.bind_wheel_scroll(widget)


class PageClaudeWorkstation:
    PAGE_NAME = "Claude_Workstation"

    def __init__(self, parent, app=None, page_key="", page_folder="", *args, **kwargs):
        app = kwargs.pop("controller", app)
        page_key = kwargs.pop("page_context", page_key)
        page_folder = kwargs.pop("page_folder", page_folder)

        self.parent = parent
        self.app = app
        self.page_key = page_key
        self.page_folder = page_folder

        self._root_var = tk.StringVar(value=_find_project_root())
        self._claude_var = tk.StringVar(value="claude")
        self._status_var = tk.StringVar(value="Ready")

        self._history_dir = os.path.join(Path(__file__).resolve().parent, "claude_workstation_history")

        self._pty_master_fd = None
        self._pty_proc = None
        self._pty_alive = False
        self._pty_started_at = None
        self._pty_shell_path = os.environ.get("SHELL", "/bin/bash") or "/bin/bash"
        self._pty_out_queue = queue.Queue()
        self._pty_reader_thr = None
        self._pty_pump_after = None
        self._pty_stop_logged = False

        self._last_response = ""
        self._command_history = []
        self._history_idx = -1

    def build(self, parent):
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(2, weight=1)
        self.frame.pack(fill="both", expand=True)
        self._build_ui()
        return self.frame

    create_widgets = build
    mount = build
    render = build

    def _build_ui(self):
        cfg = ttk.LabelFrame(self.frame, text="Claude Workstation", padding=(10, 6))
        cfg.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        cfg.columnconfigure(1, weight=1)

        ttk.Label(cfg, text="Project root:", font=("", 10, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(cfg, textvariable=self._root_var, font=("monospace", 10)).grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Button(cfg, text="Browse...", width=10, command=self._choose_root).grid(row=0, column=2, padx=(6, 0), pady=3)

        ttk.Label(cfg, text="Claude executable:", font=("", 10, "bold")).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(cfg, textvariable=self._claude_var, font=("monospace", 10)).grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Label(cfg, text="Embedded Claude session page", foreground="#666").grid(row=1, column=2, sticky="w", padx=(6, 0), pady=3)

        actions = ttk.LabelFrame(self.frame, text="Session", padding=(10, 6))
        actions.grid(row=1, column=0, sticky="ew", padx=8, pady=4)

        self._start_btn = ttk.Button(actions, text="Start Shell", width=12, command=self._start_shell)
        self._start_btn.pack(side="left", padx=2)
        self._launch_btn = ttk.Button(actions, text="Launch Claude", width=14, command=self._launch_claude)
        self._launch_btn.pack(side="left", padx=2)
        self._stop_btn = ttk.Button(actions, text="Stop", width=8, command=self._stop_shell)
        self._stop_btn.pack(side="left", padx=2)
        self._ctrl_c_btn = ttk.Button(actions, text="Send Ctrl-C", width=12, command=lambda: self._send_signal_byte(b"\x03"))
        self._ctrl_c_btn.pack(side="left", padx=2)
        ttk.Button(actions, text="Save Transcript", width=14, command=self._save_transcript).pack(side="left", padx=8)
        ttk.Button(actions, text="Copy Last Response", width=17, command=self._copy_last_response).pack(side="left", padx=2)
        ttk.Button(actions, text="Clear View", width=10, command=self._clear_view).pack(side="left", padx=2)

        ttk.Label(actions, textvariable=self._status_var, foreground="#555").pack(side="left", padx=(12, 0), fill="x", expand=True)

        body = ttk.PanedWindow(self.frame, orient="vertical")
        body.grid(row=2, column=0, sticky="nsew", padx=8, pady=(4, 8))

        view_outer = ttk.LabelFrame(body, text="Transcript", padding=4)
        view_outer.columnconfigure(0, weight=1)
        view_outer.rowconfigure(0, weight=1)
        self._session_view = tk.Text(
            view_outer,
            wrap="word",
            state="disabled",
            font=("monospace", 10),
            background="#fafaf8",
            relief="flat",
            borderwidth=1,
            padx=8,
            pady=6,
        )
        view_scroll = ttk.Scrollbar(view_outer, orient="vertical", command=self._session_view.yview)
        self._session_view.configure(yscrollcommand=view_scroll.set)
        self._session_view.grid(row=0, column=0, sticky="nsew")
        view_scroll.grid(row=0, column=1, sticky="ns")
        _bind_scroll(self._session_view)
        self._session_view.tag_configure("cmd_header", foreground="#2563eb", font=("monospace", 10, "bold"))
        self._session_view.tag_configure("cmd_text", foreground="#15803d")
        self._session_view.tag_configure("terminal_output", foreground="#111827")
        self._session_view.tag_configure("marker", foreground="#9ca3af")
        body.add(view_outer, weight=4)

        input_outer = ttk.LabelFrame(self.frame, text="Input  (Enter = Send)", padding=(6, 4))
        input_outer.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 8))
        input_outer.columnconfigure(0, weight=1)
        self._cmd_input = tk.Text(input_outer, height=4, wrap="word", font=("monospace", 10), padx=6, pady=4)
        input_scroll = ttk.Scrollbar(input_outer, orient="vertical", command=self._cmd_input.yview)
        self._cmd_input.configure(yscrollcommand=input_scroll.set)
        self._cmd_input.grid(row=0, column=0, sticky="ew")
        input_scroll.grid(row=0, column=1, sticky="ns")
        self._send_btn = ttk.Button(input_outer, text="Send", width=8, command=self._send_input_to_shell)
        self._send_btn.grid(row=0, column=2, padx=(4, 0), sticky="ns")
        _bind_scroll(self._cmd_input)
        self._cmd_input.bind("<Return>", lambda e: (self._send_input_to_shell(), "break"))
        self._cmd_input.bind("<Shift-Return>", self._insert_newline)
        self.frame.bind("<Destroy>", self._on_destroy, add="+")
        self._set_session_buttons()

    def _choose_root(self):
        chosen = filedialog.askdirectory(title="Choose Claude project root", initialdir=self._root_var.get() or _find_project_root())
        if chosen:
            self._root_var.set(chosen)
            self._set_status(f"Root set: {chosen}")

    def _set_status(self, text: str):
        self._status_var.set(text)

    def _set_session_buttons(self):
        running = self._pty_alive
        self._start_btn.configure(state="disabled" if running else "normal")
        self._launch_btn.configure(state="normal")
        self._stop_btn.configure(state="normal" if running else "disabled")
        self._ctrl_c_btn.configure(state="normal" if running else "disabled")
        self._send_btn.configure(state="normal")

    def _insert_newline(self, _event=None):
        self._cmd_input.insert("insert", "\n")
        return "break"

    def _on_destroy(self, event):
        if event.widget is self.frame:
            self._stop_shell(log_message=False)

    def _sv_append(self, text: str, tag=None):
        self._session_view.configure(state="normal")
        if tag:
            start = self._session_view.index("end")
            self._session_view.insert("end", text)
            self._session_view.tag_add(tag, start, "end")
        else:
            self._session_view.insert("end", text)
        self._session_view.configure(state="disabled")
        self._session_view.see("end")

    def _start_shell(self):
        if self._pty_alive:
            self._set_status("Shell already running.")
            return
        if not PTY_AVAILABLE:
            messagebox.showerror("Claude Workstation", "PTY support is unavailable on this platform.")
            self._set_status("PTY unavailable.")
            return

        root_dir = self._root_var.get().strip()
        if not root_dir or not os.path.isdir(root_dir):
            messagebox.showwarning("Claude Workstation", "Choose a valid project root first.")
            return

        try:
            os.makedirs(self._history_dir, exist_ok=True)
            master_fd, slave_fd = pty.openpty()
            flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
            fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            try:
                ws = struct.pack("HHHH", 40, 120, 0, 0)
                fcntl.ioctl(master_fd, termios.TIOCSWINSZ, ws)
            except Exception:
                pass

            env = dict(os.environ)
            env["TERM"] = "dumb"
            env["PS1"] = "$ "
            env.pop("PROMPT_COMMAND", None)

            shell_argv = [self._pty_shell_path, "--noediting", "-i"] \
                if "bash" in os.path.basename(self._pty_shell_path) \
                else [self._pty_shell_path, "-i"]
            proc = subprocess.Popen(
                shell_argv,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                start_new_session=True,
                env=env,
                cwd=root_dir,
            )
            os.close(slave_fd)

            self._pty_master_fd = master_fd
            self._pty_proc = proc
            self._pty_alive = True
            self._pty_stop_logged = False
            self._pty_started_at = _now_iso()
            self._pty_reader_thr = threading.Thread(target=self._shell_reader_loop, daemon=True, name="claude-workstation-pty-reader")
            self._pty_reader_thr.start()
            self._pty_schedule_pump()
            self._set_session_buttons()

            self._sv_append(f"\n--- shell started [{self._pty_started_at}] ({self._pty_shell_path} pid={proc.pid}) ---\n\n", tag="marker")
            self._set_status(f"Shell started in {root_dir}")
        except Exception as exc:
            self._pty_alive = False
            self._set_session_buttons()
            self._set_status(f"Failed to start shell: {exc}")

    def _launch_claude(self):
        claude_exe = self._claude_var.get().strip() or "claude"
        resolved = claude_exe if os.path.sep in claude_exe else shutil.which(claude_exe)
        if not resolved:
            self._sv_append(
                f"\n--- Claude executable not found: {claude_exe} ---\n"
                "Set the full executable path in the field above.\n\n",
                tag="marker",
            )
            self._set_status(f"Claude executable not found: {claude_exe}")
            return
        if not self._pty_alive:
            self._start_shell()
        if not self._pty_alive:
            return
        ts = _now_iso()
        launch_cmd = f"TERM=dumb NO_COLOR=1 {shlex.quote(resolved)}"
        self._command_history.append(launch_cmd)
        self._history_idx = len(self._command_history) - 1
        self._sv_append(f"\n## CMD [{ts}]\n\n", tag="cmd_header")
        self._sv_append(f"```sh\n{launch_cmd}\n```\n\n", tag="cmd_text")
        if self._send_to_shell(launch_cmd + "\n"):
            self._set_status("Claude launched in live shell.")
        else:
            self._set_status("Failed to launch Claude.")

    def _stop_shell(self, log_message=True):
        if not self._pty_alive:
            if log_message:
                self._set_status("Shell is not running.")
            return
        proc = self._pty_proc
        try:
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        finally:
            self._pty_finalize(log_message=log_message)

    def _pty_cancel_pump(self):
        if self._pty_pump_after is None:
            return
        try:
            self.frame.after_cancel(self._pty_pump_after)
        except Exception:
            pass
        self._pty_pump_after = None

    def _pty_finalize(self, log_message=True):
        was_alive = self._pty_alive or self._pty_master_fd is not None or self._pty_proc is not None
        self._pty_cancel_pump()
        try:
            if self._pty_master_fd is not None:
                os.close(self._pty_master_fd)
        except Exception:
            pass
        self._pty_master_fd = None
        self._pty_proc = None
        self._pty_alive = False
        self._pty_reader_thr = None
        self._set_session_buttons()
        if was_alive and log_message and not self._pty_stop_logged:
            self._sv_append(f"\n--- shell stopped [{_now_iso()}] ---\n\n", tag="marker")
            self._pty_stop_logged = True
        if log_message:
            self._set_status("Shell stopped.")

    def _shell_reader_loop(self):
        fd = self._pty_master_fd
        while self._pty_alive and fd is not None:
            try:
                ready, _, _ = select.select([fd], [], [], 0.2)
            except (OSError, ValueError):
                break
            if not ready:
                if self._pty_proc is None or self._pty_proc.poll() is not None:
                    self._pty_out_queue.put(("__EOF__", None))
                    return
                continue
            try:
                chunk = os.read(fd, 4096)
            except BlockingIOError:
                continue
            except OSError:
                self._pty_out_queue.put(("__EOF__", None))
                return
            if not chunk:
                self._pty_out_queue.put(("__EOF__", None))
                return
            try:
                text = chunk.decode("utf-8", errors="replace")
            except Exception:
                text = repr(chunk)
            self._pty_out_queue.put(("data", _strip_ansi(text)))

    def _pty_schedule_pump(self):
        self._pty_cancel_pump()
        try:
            self._pty_pump_after = self.frame.after(60, self._pty_pump)
        except Exception:
            self._pty_pump_after = None

    def _pty_pump(self):
        try:
            drained = []
            eof = False
            while True:
                try:
                    kind, payload = self._pty_out_queue.get_nowait()
                except queue.Empty:
                    break
                if kind == "__EOF__":
                    eof = True
                    break
                drained.append(payload)
            if drained:
                joined = "".join(drained)
                self._last_response = (self._last_response + joined)[-20000:]
                self._sv_append(joined, tag="terminal_output")
            if eof:
                self._pty_finalize()
                return
        except Exception as exc:
            self._sv_append(f"\n--- output pump error: {exc} ---\n\n", tag="marker")
            self._pty_finalize(log_message=False)
            self._set_status(f"Output handling failed: {exc}")
            return
        if self._pty_alive:
            self._pty_pump_after = self.frame.after(60, self._pty_pump)
        else:
            self._pty_pump_after = None

    def _send_to_shell(self, data: str) -> bool:
        if not self._pty_alive or self._pty_master_fd is None:
            return False
        try:
            os.write(self._pty_master_fd, data.encode("utf-8", errors="replace"))
            return True
        except OSError:
            self._pty_out_queue.put(("__EOF__", None))
            return False

    def _send_signal_byte(self, data: bytes):
        if not self._pty_alive or self._pty_master_fd is None:
            self._set_status("Shell not running.")
            return
        try:
            os.write(self._pty_master_fd, data)
            self._set_status(f"Sent control byte {data!r}.")
        except OSError as exc:
            self._set_status(f"Send failed: {exc}")

    def _send_input_to_shell(self):
        if not self._pty_alive:
            self._start_shell()
        if not self._pty_alive:
            return
        text = self._cmd_input.get("1.0", "end-1c")
        if not text.strip():
            self._cmd_input.delete("1.0", "end")
            self._send_to_shell("\n")
            self._set_status("Sent newline.")
            return
        self._cmd_input.delete("1.0", "end")
        cleaned = text.strip().replace("\r\n", "\n").replace("\r", "\n")
        if cleaned:
            self._command_history.append(cleaned)
            self._history_idx = len(self._command_history) - 1
            ts = _now_iso()
            self._sv_append(f"\n## CMD [{ts}]\n\n", tag="cmd_header")
            self._sv_append(f"```sh\n{cleaned}\n```\n\n", tag="cmd_text")
        if not text.endswith("\n"):
            text += "\n"
        if self._send_to_shell(text):
            self._set_status("Command sent.")
        else:
            self._set_status("Send failed.")

    def _save_transcript(self):
        os.makedirs(self._history_dir, exist_ok=True)
        transcript = self._session_view.get("1.0", "end-1c").strip()
        if not transcript:
            messagebox.showinfo("Save Transcript", "Nothing to save yet.")
            return
        filename = f"claude_workstation_{_now_stamp()}.md"
        path = os.path.join(self._history_dir, filename)
        root_dir = self._root_var.get().strip()
        lines = [
            "---",
            "schema_version: 1",
            "chipack: chi_ain",
            "page: Claude_Workstation",
            f"saved_at: {_now_iso()}",
            f"project_root: {root_dir}",
            f"shell_started_at: {self._pty_started_at or ''}",
            f"shell_path: {self._pty_shell_path}",
            "---",
            "",
            transcript,
            "",
        ]
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines))
            self._set_status(f"Transcript saved: {filename}")
            messagebox.showinfo("Save Transcript", f"Saved:\n{path}")
        except OSError as exc:
            messagebox.showerror("Save Transcript", str(exc))

    def _copy_last_response(self):
        captured = self._last_response.strip()
        if not captured:
            self._set_status("No terminal output captured yet.")
            return
        self.frame.clipboard_clear()
        self.frame.clipboard_append(captured)
        self._set_status("Recent terminal output copied.")

    def _clear_view(self):
        self._session_view.configure(state="normal")
        self._session_view.delete("1.0", "end")
        self._session_view.configure(state="disabled")
        self._set_status("Transcript view cleared.")
