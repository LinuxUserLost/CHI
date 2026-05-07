import sys
import json
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.flipper_rpc_adapter import FlipperRpcAdapter


class RpcInfoPage:
    """Real protobuf-backed device info page for chiflippin0.

    Actions in this page are limited to calls explicitly shown in the public
    flipperzero_protobuf_py examples: ping, device info, datetime retrieval,
    and listing /ext.
    """

    def __init__(self, parent=None):
        self.parent = parent
        self.frame = None
        self.adapter = FlipperRpcAdapter()
        self.status_var = tk.StringVar(value="Idle")
        self.backend_var = tk.StringVar(value="RPC backend: checking")
        self.output_text = None
        self.log_text = None

    def build(self, parent=None):
        if parent is not None:
            self.parent = parent
        if self.parent is None:
            raise ValueError("RpcInfoPage requires a parent frame")

        self.frame = ttk.Frame(self.parent)
        self.frame.pack(fill="both", expand=True)
        self._build_ui(self.frame)
        self._refresh_backend_status()
        self._log("RPC Info loaded")
        return self.frame

    def _build_ui(self, root):
        root.columnconfigure(0, weight=3)
        root.columnconfigure(1, weight=2)
        root.rowconfigure(2, weight=1)

        header = ttk.Frame(root, padding=10)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text="RPC Info", font=("TkDefaultFont", 14, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="Read-only device info actions through the optional protobuf backend",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(header, textvariable=self.status_var).grid(row=0, column=1, sticky="e")
        ttk.Label(header, textvariable=self.backend_var).grid(row=1, column=1, sticky="e")

        actions = ttk.LabelFrame(root, text="Actions", padding=10)
        actions.grid(row=1, column=0, sticky="ew", padx=(10, 5), pady=(0, 10))
        for col in range(4):
            actions.columnconfigure(col, weight=1)

        ttk.Button(actions, text="Ping", command=self.run_ping).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(actions, text="Device Info", command=self.run_device_info).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(actions, text="Date/Time", command=self.run_datetime).grid(row=0, column=2, sticky="ew", padx=6)
        ttk.Button(actions, text="List /ext", command=self.run_list_ext).grid(row=0, column=3, sticky="ew", padx=(6, 0))

        notes = ttk.LabelFrame(root, text="Scope", padding=10)
        notes.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=(0, 10))
        notes.columnconfigure(0, weight=1)
        notes_text = tk.Text(notes, wrap="word", height=6)
        notes_text.grid(row=0, column=0, sticky="nsew")
        notes_text.insert(
            "1.0",
            "Included now:\n"
            "- ping\n"
            "- read device info\n"
            "- read date/time\n"
            "- list /ext\n\n"
            "Not included yet:\n"
            "- reboot\n"
            "- app launch\n"
            "- write actions"
        )
        notes_text.configure(state="disabled")

        output_frame = ttk.LabelFrame(root, text="Result", padding=10)
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
            self.backend_var.set("RPC backend: flipperzero_protobuf_py available")
        else:
            self.backend_var.set("RPC backend: unavailable")
            self._log(status["reason"])

    def run_ping(self):
        self._run_action("Ping", self.adapter.ping)

    def run_device_info(self):
        self._run_action("Device Info", self.adapter.device_info)

    def run_datetime(self):
        self._run_action("Date/Time", self.adapter.datetime_info)

    def run_list_ext(self):
        self._run_action("List /ext", self.adapter.list_ext)

    def _run_action(self, label, func):
        self.status_var.set(f"Running {label}")
        result = func()
        self._set_output(result)
        if result.get("ok"):
            self.status_var.set(f"{label} complete")
            self._log(f"{label} succeeded")
        else:
            self.status_var.set(f"{label} failed")
            self._log(f"{label} failed: {result.get('error', '')}")

    def _set_output(self, payload):
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", json.dumps(payload, indent=2, default=str))
        self.output_text.configure(state="disabled")

    def _log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")
