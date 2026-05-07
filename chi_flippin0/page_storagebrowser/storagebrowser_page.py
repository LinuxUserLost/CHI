import sys
import json
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.flipper_rpc_adapter import FlipperRpcAdapter


class StorageBrowserPage:
    """Read-only storage browser for chiflippin0.

    This page stays intentionally narrow: it only lists storage paths through
    the optional flipperzero_protobuf_py backend. No upload, delete, rename, or
    write actions are exposed here yet.
    """

    def __init__(self, parent=None):
        self.parent = parent
        self.frame = None
        self.adapter = FlipperRpcAdapter()
        self.status_var = tk.StringVar(value="Idle")
        self.backend_var = tk.StringVar(value="Storage backend: checking")
        self.path_var = tk.StringVar(value="/ext")
        self.output_text = None
        self.log_text = None

    def build(self, parent=None):
        if parent is not None:
            self.parent = parent
        if self.parent is None:
            raise ValueError("StorageBrowserPage requires a parent frame")

        self.frame = ttk.Frame(self.parent)
        self.frame.pack(fill="both", expand=True)
        self._build_ui(self.frame)
        self._refresh_backend_status()
        self._log("Storage Browser loaded")
        return self.frame

    def _build_ui(self, root):
        root.columnconfigure(0, weight=3)
        root.columnconfigure(1, weight=2)
        root.rowconfigure(2, weight=1)

        header = ttk.Frame(root, padding=10)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text="Storage Browser", font=("TkDefaultFont", 14, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="Read-only path browsing through the optional protobuf backend",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(header, textvariable=self.status_var).grid(row=0, column=1, sticky="e")
        ttk.Label(header, textvariable=self.backend_var).grid(row=1, column=1, sticky="e")

        controls = ttk.LabelFrame(root, text="Browse", padding=10)
        controls.grid(row=1, column=0, sticky="ew", padx=(10, 5), pady=(0, 10))
        controls.columnconfigure(1, weight=1)
        controls.columnconfigure(2, weight=1)
        controls.columnconfigure(3, weight=1)
        controls.columnconfigure(4, weight=1)

        ttk.Label(controls, text="Path").grid(row=0, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.path_var).grid(row=0, column=1, sticky="ew", padx=(6, 10))
        ttk.Button(controls, text="List /", command=self.list_root).grid(row=0, column=2, sticky="ew", padx=(0, 6))
        ttk.Button(controls, text="List /ext", command=self.list_ext).grid(row=0, column=3, sticky="ew", padx=6)
        ttk.Button(controls, text="Browse Path", command=self.browse_current_path).grid(row=0, column=4, sticky="ew", padx=(6, 0))

        notes = ttk.LabelFrame(root, text="Scope", padding=10)
        notes.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=(0, 10))
        notes.columnconfigure(0, weight=1)
        notes_text = tk.Text(notes, wrap="word", height=7)
        notes_text.grid(row=0, column=0, sticky="nsew")
        notes_text.insert(
            "1.0",
            "Included now:\n"
            "- list /\n"
            "- list /ext\n"
            "- browse a typed path\n"
            "- read-only result display\n\n"
            "Not included yet:\n"
            "- file read/download\n"
            "- upload\n"
            "- delete/rename\n"
            "- write actions"
        )
        notes_text.configure(state="disabled")

        output_frame = ttk.LabelFrame(root, text="Entries", padding=10)
        output_frame.grid(row=2, column=0, sticky="nsew", padx=(10, 5), pady=(0, 10))
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)
        self.output_text = tk.Text(output_frame, wrap="word")
        self.output_text.grid(row=0, column=0, sticky="nsew")

        log_frame = ttk.LabelFrame(root, text="Log", padding=10)
        log_frame.grid(row=2, column=1, sticky="nsew", padx=(5, 10), pady=(0, 10))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, wrap="word")
        self.log_text.grid(row=0, column=0, sticky="nsew")

    def _refresh_backend_status(self):
        status = self.adapter.backend_status()
        if status["available"]:
            self.backend_var.set("Storage backend: flipperzero_protobuf_py available")
        else:
            self.backend_var.set("Storage backend: unavailable")
            self._log(status["reason"])

    def list_root(self):
        self.path_var.set("/")
        self._run_list("/")

    def list_ext(self):
        self.path_var.set("/ext")
        self._run_list("/ext")

    def browse_current_path(self):
        self._run_list(self.path_var.get())

    def _run_list(self, path):
        self.status_var.set(f"Listing {path}")
        result = self.adapter.list_path(path)
        self._set_output(result)
        if result.get("ok"):
            listed_path = result.get("data", {}).get("path", path)
            entries = result.get("data", {}).get("entries", [])
            self.status_var.set(f"Listed {listed_path}")
            self._log(f"Listed {listed_path} with {len(entries)} entrie(s)")
        else:
            self.status_var.set("List failed")
            self._log(f"List failed for {path}: {result.get('error', '')}")

    def _set_output(self, payload):
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", json.dumps(payload, indent=2, default=str))
        self.output_text.configure(state="disabled")

    def _log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")
