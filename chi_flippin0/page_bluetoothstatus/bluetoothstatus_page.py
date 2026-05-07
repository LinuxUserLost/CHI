import sys
import json
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.bluetooth_tools import BluetoothTools


class BluetoothStatusPage:
    """Verified-capabilities Bluetooth page for chiflippin0.

    This page performs real local Linux Bluetooth checks and displays a
    carefully limited capability map for Flipper BLE. It does not attempt to
    pair, control, or emulate unsupported desktop-host BLE flows.
    """

    VERIFIED_FACTS = [
        "Flipper Zero hardware includes Bluetooth LE 5.4.",
        "Flipper settings support Bluetooth LE pairing with the phone app and mention connecting to a smartphone or computer as a controller.",
        "The mobile app can remotely control, update, synchronize, and install community-developed apps over Bluetooth LE.",
        "This page does not claim Flipper can replace your Linux Bluetooth adapter. That remains unverified here.",
    ]

    def __init__(self, parent=None):
        self.parent = parent
        self.frame = None
        self.tools = BluetoothTools()
        self.status_var = tk.StringVar(value="Idle")
        self.output_text = None
        self.log_text = None

    def build(self, parent=None):
        if parent is not None:
            self.parent = parent
        if self.parent is None:
            raise ValueError("BluetoothStatusPage requires a parent frame")

        self.frame = ttk.Frame(self.parent)
        self.frame.pack(fill="both", expand=True)
        self._build_ui(self.frame)
        self._log("Bluetooth Status loaded")
        self.render_verified_facts()
        return self.frame

    def _build_ui(self, root):
        root.columnconfigure(0, weight=3)
        root.columnconfigure(1, weight=2)
        root.rowconfigure(2, weight=1)

        header = ttk.Frame(root, padding=10)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text="Bluetooth Status", font=("TkDefaultFont", 14, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="Verified BLE boundaries plus real Linux Bluetooth environment checks",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(header, textvariable=self.status_var).grid(row=0, column=1, sticky="e")

        actions = ttk.LabelFrame(root, text="Actions", padding=10)
        actions.grid(row=1, column=0, sticky="ew", padx=(10, 5), pady=(0, 10))
        for col in range(3):
            actions.columnconfigure(col, weight=1)

        ttk.Button(actions, text="Verified Facts", command=self.render_verified_facts).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(actions, text="Check Linux Bluetooth", command=self.run_linux_checks).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(actions, text="Tool Paths", command=self.show_tool_paths).grid(row=0, column=2, sticky="ew", padx=(6, 0))

        notes = ttk.LabelFrame(root, text="Scope", padding=10)
        notes.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=(0, 10))
        notes.columnconfigure(0, weight=1)
        notes_text = tk.Text(notes, wrap="word", height=8)
        notes_text.grid(row=0, column=0, sticky="nsew")
        notes_text.insert(
            "1.0",
            "Included now:\n"
            "- verified BLE capability summary\n"
            "- Linux Bluetooth tool/path checks\n"
            "- adapter visibility checks\n\n"
            "Not included:\n"
            "- pairing flow\n"
            "- generic BLE control\n"
            "- host-adapter replacement claims\n"
            "- unsupported feature buttons"
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

    def render_verified_facts(self):
        self.status_var.set("Showing verified facts")
        payload = {
            "verified_facts": self.VERIFIED_FACTS,
            "current_page_boundary": "status and verification only",
        }
        self._set_output(payload)
        self._log("Rendered verified BLE facts")

    def run_linux_checks(self):
        self.status_var.set("Checking Linux Bluetooth")
        payload = self.tools.check_environment()
        self._set_output(payload)
        self._log("Ran Linux Bluetooth checks")
        self.status_var.set("Linux Bluetooth check complete")

    def show_tool_paths(self):
        self.status_var.set("Showing tool paths")
        payload = {
            "tools": self.tools.tool_paths(),
        }
        self._set_output(payload)
        self._log("Rendered Bluetooth tool paths")
        self.status_var.set("Tool paths shown")

    def _set_output(self, payload):
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", json.dumps(payload, indent=2, default=str))
        self.output_text.configure(state="disabled")

    def _log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")
