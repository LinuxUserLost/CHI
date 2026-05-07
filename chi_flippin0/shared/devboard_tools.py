from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Any, Dict, List


class DevboardTools:
    """Small wrapper for official Devboard command paths.

    Uses the documented ufbt module invocation route for flashing the Wi-Fi
    Developer Board. It keeps subprocess usage narrow and explicit.
    """

    def backend_status(self) -> Dict[str, Any]:
        python_path = sys.executable or "python3"
        ufbt_exe = shutil.which("ufbt")
        return {
            "python": python_path,
            "ufbt_cli": ufbt_exe or "",
            "python_module_command": [python_path, "-m", "ufbt"],
        }

    def check_ufbt(self) -> Dict[str, Any]:
        python_path = sys.executable or "python3"
        checks: List[Dict[str, Any]] = []

        checks.append(self._run([python_path, "-m", "ufbt", "--help"], label="python -m ufbt --help"))

        ufbt_exe = shutil.which("ufbt")
        if ufbt_exe:
            checks.append(self._run([ufbt_exe, "--help"], label="ufbt --help"))

        ok = any(item.get("ok") for item in checks)
        return {"ok": ok, "checks": checks, "backend": self.backend_status()}

    def flash_devboard(self) -> Dict[str, Any]:
        python_path = sys.executable or "python3"
        return self._run(
            [python_path, "-m", "ufbt", "devboard_flash"],
            label="python -m ufbt devboard_flash",
        )

    def _run(self, command: List[str], label: str) -> Dict[str, Any]:
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=180,
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
        except Exception as exc:  # pragma: no cover - environment dependent path
            return {
                "ok": False,
                "label": label,
                "command": command,
                "returncode": None,
                "stdout": "",
                "stderr": str(exc),
            }
