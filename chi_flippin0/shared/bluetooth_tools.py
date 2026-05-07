from __future__ import annotations

import shutil
import subprocess
from typing import Any, Dict, List


class BluetoothTools:
    """Linux Bluetooth environment checks for chiflippin0."""

    COMMANDS = {
        "bluetoothctl_version": ["bluetoothctl", "--version"],
        "bluetoothctl_list": ["bluetoothctl", "list"],
        "bluetoothctl_show": ["bluetoothctl", "show"],
        "rfkill_bluetooth": ["rfkill", "list", "bluetooth"],
    }

    def check_environment(self) -> Dict[str, Any]:
        checks: List[Dict[str, Any]] = []
        for label, command in self.COMMANDS.items():
            checks.append(self._run(command, label))
        return {
            "tools": self.tool_paths(),
            "checks": checks,
        }

    def tool_paths(self) -> Dict[str, str]:
        return {
            "bluetoothctl": shutil.which("bluetoothctl") or "",
            "rfkill": shutil.which("rfkill") or "",
        }

    def _run(self, command: List[str], label: str) -> Dict[str, Any]:
        executable = shutil.which(command[0])
        if not executable:
            return {
                "ok": False,
                "label": label,
                "command": command,
                "returncode": None,
                "stdout": "",
                "stderr": f"{command[0]} not found on PATH",
            }

        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            return {
                "ok": proc.returncode == 0,
                "label": label,
                "command": command,
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            }
        except Exception as exc:
            return {
                "ok": False,
                "label": label,
                "command": command,
                "returncode": None,
                "stdout": "",
                "stderr": str(exc),
            }
