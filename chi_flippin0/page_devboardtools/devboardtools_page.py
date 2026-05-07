import sys
import json
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.devboard_tools import DevboardTools


class DevboardToolsPage:
    """Real Devboard tooling page for chiflippin0.

    This page wraps documented ufbt-based Devboard workflows. It does not try
    to reimplement the web debugger or invent custom flashing flows.
    """

    def __init__(self, parent=None):
        self.parent = parent
        self.frame = None
        self.tools = DevboardTools()
        self.status_var = tk.StringVar(value="Idle")
        self.backend_var = tk.StringVar(value="Devboard backend: checking")
        self.flash_confirm_var = tk.BooleanVar(value=False)
        self.output_text = None
        self.log_text = None
        self.flash_button = None

    def build(self, parent=None):
        if parent is not None:
            self.parent = parent
        if self.parent is None:
            raise ValueError("DevboardToolsPage requires a parent frame")

        self.frame = ttk.Frame(self.parent)
        self.frame.pack(fill="both", expand=True)
        self._build_ui(self.frame)
        self._refresh_backend_status()
        self._sync_flash_button_state(initial=True)
        self._log("Devboard Tools loaded")
        return self.frame

    def _build_ui(self, root):
        root.columnconfigure(0, weight=3)
        root.columnconfigure(1, weight=2)
        root.rowconfigure(2, weight=1)
        root.rowconfigure(3, weight=1)

        header = ttk.Frame(root, padding=10)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text="Devboard Tools", font=("TkDefaultFont", 14, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="Official command wrappers for Wi-Fi Developer Board checks and flashing",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(header, textvariable=self.status_var).grid(row=0, column=1, sticky="e")
        ttk.Label(header, textvariable=self.backend_var).grid(row=1, column=1, sticky="e")

        actions = ttk.LabelFrame(root, text="Actions", padding=10)
        actions.grid(row=1, column=0, sticky="ew", padx=(10, 5), pady=(0, 10))
        for col in range(2):
            actions.columnconfigure(col, weight=1)

        ttk.Button(actions, text="Check uFBT", command=self.run_check).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.flash_button = ttk.Button(actions, text="Flash Devboard", command=self.run_flash)
        self.flash_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        notes = ttk.LabelFrame(root, text="Scope", padding=10)
        notes.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=(0, 10))
        notes.columnconfigure(0, weight=1)
        notes_text = tk.Text(notes, wrap="word", height=8)
        notes_text.grid(row=0, column=0, sticky="nsew")
        notes_text.insert(
            "1.0",
            "Included now:\n"
            "- backend check with ufbt help\n"
            "- devboard flash using python -m ufbt devboard_flash\n\n"
            "Safety gate:\n"
            "- Flash stays disabled until you tick the confirmation box\n\n"
            "Not included yet:\n"
            "- custom debugger UI\n"
            "- web debug wrapper\n"
            "- Wi-Fi mode switching"
        )
        notes_text.configure(state="disabled")

        confirm = ttk.LabelFrame(root, text="Flash confirmation", padding=10)
        confirm.grid(row=2, column=1, sticky="new", padx=(5, 10), pady=(0, 10))
        confirm.columnconfigure(0, weight=1)
        ttk.Checkbutton(
            confirm,
            text="I want to allow Devboard flashing on this page",
            variable=self.flash_confirm_var,
            command=self._sync_flash_button_state,
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            confirm,
            text="Use Check uFBT first. Leave this unticked during early sync and layout testing.",
            wraplength=260,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))

        output_frame = ttk.LabelFrame(root, text="Result", padding=10)
        output_frame.grid(row=2, column=0, sticky="nsew", padx=(10, 5), pady=(0, 10))
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)
        self.output_text = tk.Text(output_frame, wrap="word")
        self.output_text.grid(row=0, column=0, sticky="nsew")

        log_frame = ttk.LabelFrame(root, text="Log", padding=10)
        log_frame.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=10, pady=(0, 10))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, wrap="word", height=8)
        self.log_text.grid(row=0, column=0, sticky="nsew")

    def _refresh_backend_status(self):
        status = self.tools.backend_status()
        ufbt_cli = status.get("ufbt_cli") or "not on PATH"
        self.backend_var.set(f"uFBT CLI: {ufbt_cli}")
        if not status.get("ufbt_cli"):
            self._log("uFBT CLI not found on PATH; command checks may still work through python -m ufbt.")

    def _sync_flash_button_state(self, initial=False):
        if self.flash_button is None:
            return
        if self.flash_confirm_var.get():
            self.flash_button.state(["!disabled"])
            if not initial:
                self._log("Flash action enabled for this page session.")
        else:
            self.flash_button.state(["disabled"])
            if not initial:
                self._log("Flash action disabled.")

    def run_check(self):
        self.status_var.set("Checking uFBT")
        result = self.tools.check_ufbt()
        self._set_output(result)
        if result.get("ok"):
            self.status_var.set("uFBT check complete")
            self._log("uFBT check succeeded")
        else:
            self.status_var.set("uFBT check failed")
            self._log("uFBT check failed")

    def run_flash(self):
        if not self.flash_confirm_var.get():
            self.status_var.set("Flash blocked")
            self._log("Flash blocked: confirmation box is not enabled.")
            return

        self.status_var.set("Flashing Devboard")
        result = self.tools.flash_devboard()
        self._set_output(result)
        if result.get("ok"):
            self.status_var.set("Devboard flash complete")
            self._log("Devboard flash succeeded")
        else:
            self.status_var.set("Devboard flash failed")
            self._log(f"Devboard flash failed: {result.get('stderr', '')}")

    def _set_output(self, payload):
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", json.dumps(payload, indent=2, default=str))
        self.output_text.configure(state="disabled")

    def _log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")
