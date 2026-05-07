import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared.flipper_usb_adapter import FlipperUsbAdapter


class TransportHubPage:
    """Foundation transport page for chiflippin0.

    Current scope:
    - Linux-friendly USB serial target discovery
    - transport selector UI
    - adapter-backed target probing
    - optional pyserial-backed open/close session test
    - read-only CLI help handshake
    - session candidate selection state
    - status/logging pane

    Intentionally does not yet perform live Flipper RPC or BLE control.
    """

    def __init__(self, parent=None):
        self.parent = parent
        self.frame = None
        self.transport_var = tk.StringVar(value="usb")
        self.port_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Idle")
        self.device_label_var = tk.StringVar(value="No target selected")
        self.backend_var = tk.StringVar(value="Serial backend: checking")
        self.connected = False
        self.log_text = None
        self.port_combo = None
        self.usb_adapter = FlipperUsbAdapter()

    def build(self, parent=None):
        if parent is not None:
            self.parent = parent
        if self.parent is None:
            raise ValueError("TransportHubPage requires a parent frame")

        self.frame = ttk.Frame(self.parent)
        self.frame.pack(fill="both", expand=True)
        self._build_ui(self.frame)
        self._refresh_backend_status()
        self.refresh_ports()
        self._log("Transport Hub loaded")
        return self.frame

    def _build_ui(self, root):
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)
        root.rowconfigure(3, weight=1)

        header = ttk.Frame(root, padding=10)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text="Transport Hub", font=("TkDefaultFont", 14, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="USB-first device access with clear dependency and target checks",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(header, textvariable=self.status_var).grid(row=0, column=1, sticky="e")
        ttk.Label(header, textvariable=self.backend_var).grid(row=1, column=1, sticky="e")

        controls = ttk.LabelFrame(root, text="Connection", padding=10)
        controls.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        for col in range(6):
            controls.columnconfigure(col, weight=1 if col in (1, 3) else 0)

        ttk.Label(controls, text="Transport").grid(row=0, column=0, sticky="w")
        transport_box = ttk.Combobox(
            controls,
            textvariable=self.transport_var,
            state="readonly",
            values=["usb", "bluetooth"],
            width=14,
        )
        transport_box.grid(row=0, column=1, sticky="ew", padx=(6, 12))
        transport_box.bind("<<ComboboxSelected>>", lambda _event: self._on_transport_change())

        ttk.Label(controls, text="Port / Target").grid(row=0, column=2, sticky="w")
        self.port_combo = ttk.Combobox(controls, textvariable=self.port_var, state="readonly")
        self.port_combo.grid(row=0, column=3, sticky="ew", padx=(6, 12))

        ttk.Button(controls, text="Refresh", command=self.refresh_ports).grid(
            row=0, column=4, padx=(0, 6)
        )
        ttk.Button(controls, text="Select", command=self.connect_selected).grid(
            row=0, column=5, padx=(0, 6)
        )
        ttk.Button(controls, text="Clear", command=self.disconnect).grid(
            row=1, column=5, pady=(8, 0), sticky="e"
        )

        ttk.Label(controls, text="Current target").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(controls, textvariable=self.device_label_var).grid(
            row=1, column=1, columnspan=4, sticky="w", pady=(8, 0)
        )

        info = ttk.Panedwindow(root, orient="horizontal")
        info.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))

        left = ttk.Frame(info, padding=8)
        right = ttk.Frame(info, padding=8)
        info.add(left, weight=2)
        info.add(right, weight=3)

        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        ttk.Label(left, text="Current scope", font=("TkDefaultFont", 10, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        scope_text = tk.Text(left, wrap="word", height=12)
        scope_text.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        scope_text.insert(
            "1.0",
            "- USB-first target discovery\n"
            "- path probe and access checks\n"
            "- optional pyserial session open test\n"
            "- read-only CLI help handshake\n"
            "- target selection state\n"
            "- BLE kept visible but not implemented yet\n\n"
            "Current limits:\n"
            "1. Select does not open a full working session\n"
            "2. Session Open Test checks serial access only\n"
            "3. CLI Help Handshake asks the CLI for command help\n"
            "4. RPC and storage live in separate pages\n",
        )
        scope_text.configure(state="disabled")

        ttk.Label(right, text="Session log", font=("TkDefaultFont", 10, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.log_text = tk.Text(right, wrap="word", height=12)
        self.log_text.grid(row=1, column=0, sticky="nsew", pady=(6, 0))

        actions = ttk.LabelFrame(root, text="Actions", padding=10)
        actions.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 10))
        for col in range(5):
            actions.columnconfigure(col, weight=1)

        ttk.Button(actions, text="Refresh USB Targets", command=self.refresh_ports).grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )
        ttk.Button(actions, text="Probe Selected Target", command=self.probe_selected).grid(
            row=0, column=1, sticky="ew", padx=6
        )
        ttk.Button(actions, text="Session Open Test", command=self.test_selected_session).grid(
            row=0, column=2, sticky="ew", padx=6
        )
        ttk.Button(actions, text="CLI Help Handshake", command=self.run_cli_help_handshake).grid(
            row=0, column=3, sticky="ew", padx=6
        )
        ttk.Button(actions, text="Show Notes", command=self.open_dev_notes).grid(
            row=0, column=4, sticky="ew", padx=(6, 0)
        )

    def _refresh_backend_status(self):
        backend = self.usb_adapter.serial_backend_status()
        if backend["available"]:
            self.backend_var.set("Serial backend: pyserial available")
        else:
            self.backend_var.set("Serial backend: pyserial unavailable")
            self._log("pyserial not installed; serial test actions will report that cleanly.")

    def _on_transport_change(self):
        if self.transport_var.get() == "bluetooth":
            self.status_var.set("BLE not implemented here")
            self._log("Bluetooth transport is listed for future routing only.")
            self.port_combo.configure(values=["BLE not implemented in Transport Hub"])
            self.port_var.set("BLE not implemented in Transport Hub")
            self.device_label_var.set("No target selected")
            return
        self.refresh_ports()

    def refresh_ports(self):
        if self.transport_var.get() != "usb":
            self._on_transport_change()
            return

        ports = self._discover_usb_candidates()
        if not ports:
            ports = ["No USB serial targets found"]
        self.port_combo.configure(values=ports)
        self.port_var.set(ports[0])
        self.status_var.set("Targets refreshed")
        self._log(f"USB refresh complete. Found {len(ports)} target(s).")

    def _discover_usb_candidates(self):
        candidates = []
        for pattern in ("/dev/ttyACM*", "/dev/ttyUSB*"):
            for path in sorted(Path("/dev").glob(Path(pattern).name)):
                candidates.append(str(path))

        by_id = Path("/dev/serial/by-id")
        if by_id.exists():
            try:
                for path in sorted(by_id.iterdir()):
                    try:
                        resolved = str(path.resolve())
                    except OSError:
                        resolved = str(path)
                    label = f"{path.name} -> {resolved}"
                    if label not in candidates:
                        candidates.append(label)
            except OSError:
                self._log("Could not read /dev/serial/by-id")

        return candidates

    def connect_selected(self):
        target = self.port_var.get().strip()
        if not target or target == "No USB serial targets found":
            self.status_var.set("No target selected")
            self.device_label_var.set("No target selected")
            self._log("Select skipped: no usable target selected.")
            return

        if self.transport_var.get() == "bluetooth":
            self.status_var.set("BLE not implemented here")
            self.device_label_var.set("No target selected")
            self._log("BLE selection skipped in Transport Hub.")
            return

        probe = self.usb_adapter.probe_target(target)
        if not probe.get("exists"):
            self.status_var.set("Target missing")
            self.device_label_var.set("No target selected")
            self._log(f"Select blocked: target missing at {probe['path']}")
            return

        self.connected = True
        self.status_var.set("Target selected")
        self.device_label_var.set(probe["path"])
        self._log(
            "Selected target: "
            f"{probe['path']} | flipper_like={probe['looks_like_flipper']} | baud={probe['recommended_baud']}"
        )

    def disconnect(self):
        if not self.connected and self.device_label_var.get() == "No target selected":
            self._log("Clear skipped: nothing currently selected.")
            self.status_var.set("Idle")
            return

        self.connected = False
        self.status_var.set("Selection cleared")
        self.device_label_var.set("No target selected")
        self._log("Cleared current target selection.")

    def probe_selected(self):
        target = self.port_var.get().strip()
        if not target or target in {"No USB serial targets found", "BLE not implemented in Transport Hub"}:
            self._log("Probe skipped: no live USB target selected.")
            return

        probe = self.usb_adapter.probe_target(target)
        backend_name = probe["serial_backend"]["backend"]
        summary = (
            f"Probe: path={probe['path']} exists={probe['exists']} readable={probe['readable']} "
            f"writable={probe['writable']} char_device={probe['is_char_device']} "
            f"flipper_like={probe['looks_like_flipper']} baud={probe['recommended_baud']} backend={backend_name}"
        )
        if probe.get("error"):
            summary += f" error={probe['error']}"
        self.status_var.set("Probe complete")
        self._log(summary)

    def test_selected_session(self):
        target = self.port_var.get().strip()
        if not target or target in {"No USB serial targets found", "BLE not implemented in Transport Hub"}:
            self._log("Session open test skipped: no live USB target selected.")
            return

        result = self.usb_adapter.test_open_close(target)
        backend_name = result["backend"]["backend"]
        if result["success"]:
            self.status_var.set("Session test succeeded")
            self._log(
                f"Session open test succeeded: path={result['path']} backend={backend_name} baud={result['baud']}"
            )
            return

        self.status_var.set("Session test failed")
        self._log(
            f"Session open test failed: path={result['path']} backend={backend_name} "
            f"attempted={result['attempted']} error={result['error']}"
        )

    def run_cli_help_handshake(self):
        target = self.port_var.get().strip()
        if not target or target in {"No USB serial targets found", "BLE not implemented in Transport Hub"}:
            self._log("CLI help handshake skipped: no live USB target selected.")
            return

        result = self.usb_adapter.cli_help_handshake(target)
        backend_name = result["backend"]["backend"]
        if result["success"]:
            self.status_var.set("CLI help handshake succeeded")
            preview = result.get("response_preview", "")
            compact = preview.replace("\n", " | ")[:300]
            self._log(
                f"CLI help handshake succeeded: path={result['path']} backend={backend_name} preview={compact}"
            )
            return

        self.status_var.set("CLI help handshake failed")
        self._log(
            f"CLI help handshake failed: path={result['path']} backend={backend_name} "
            f"attempted={result['attempted']} error={result['error']}"
        )

    def open_dev_notes(self):
        notes = (
            "Transport Hub notes\n\n"
            "Select marks a target for later use.\n"
            "Session Open Test checks raw serial access.\n"
            "CLI Help Handshake sends '?' and reads back a short CLI response.\n"
            "BLE remains intentionally out of scope here.\n"
        )
        self.status_var.set("Notes shown in log")
        self._log(notes.replace("\n", " | "))

    def _log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        if self.log_text is not None:
            self.log_text.insert("end", line)
            self.log_text.see("end")
        else:
            print(line, end="")
