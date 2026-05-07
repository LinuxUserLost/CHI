import os
import time
from pathlib import Path

try:
    import serial
    from serial import SerialException
except ImportError:  # pragma: no cover - optional dependency path
    serial = None

    class SerialException(Exception):
        pass


class FlipperUsbAdapter:
    """Small USB-side helper for early chiflippin0 work.

    This class keeps the foundation layer dependency-light while still being
    able to use community Python serial tooling when available. It normalizes
    target labels, probes device-path accessibility, performs a small open/close
    session test through pyserial when installed, and can run a read-only CLI
    help handshake.
    """

    BAUD_RATE = 230400
    OPEN_TIMEOUT = 0.2
    HANDSHAKE_WAIT = 0.35
    HANDSHAKE_READ_LIMIT = 4096

    def normalize_target(self, target: str) -> str:
        target = (target or "").strip()
        if " -> " in target:
            return target.split(" -> ", 1)[1].strip()
        return target

    def is_serial_target(self, target: str) -> bool:
        path = self.normalize_target(target)
        return path.startswith("/dev/")

    def serial_backend_status(self) -> dict:
        return {
            "available": serial is not None,
            "backend": "pyserial" if serial is not None else "unavailable",
            "reason": "" if serial is not None else "pyserial is not installed",
        }

    def probe_target(self, target: str) -> dict:
        path = self.normalize_target(target)
        info = {
            "input": target,
            "path": path,
            "exists": False,
            "readable": False,
            "writable": False,
            "is_char_device": False,
            "looks_like_flipper": False,
            "recommended_baud": self.BAUD_RATE,
            "serial_backend": self.serial_backend_status(),
            "error": "",
        }

        if not path:
            info["error"] = "empty target"
            return info

        try:
            info["exists"] = os.path.exists(path)
            if info["exists"]:
                info["readable"] = os.access(path, os.R_OK)
                info["writable"] = os.access(path, os.W_OK)
                try:
                    info["is_char_device"] = Path(path).is_char_device()
                except OSError:
                    info["is_char_device"] = False

            lower = target.lower()
            info["looks_like_flipper"] = (
                "flipper" in lower or "/dev/ttyacm" in path.lower() or "usbmodemflip" in lower
            )
        except OSError as exc:
            info["error"] = str(exc)

        return info

    def test_open_close(self, target: str) -> dict:
        path = self.normalize_target(target)
        result = {
            "path": path,
            "attempted": False,
            "success": False,
            "backend": self.serial_backend_status(),
            "baud": self.BAUD_RATE,
            "error": "",
        }

        if not path:
            result["error"] = "empty target"
            return result

        if serial is None:
            result["error"] = "pyserial is not installed"
            return result

        try:
            result["attempted"] = True
            with serial.Serial(
                path,
                self.BAUD_RATE,
                timeout=self.OPEN_TIMEOUT,
                write_timeout=self.OPEN_TIMEOUT,
            ) as handle:
                result["success"] = bool(handle.is_open)
        except (SerialException, OSError, ValueError) as exc:
            result["error"] = str(exc)

        return result

    def cli_help_handshake(self, target: str) -> dict:
        path = self.normalize_target(target)
        result = {
            "path": path,
            "attempted": False,
            "success": False,
            "backend": self.serial_backend_status(),
            "baud": self.BAUD_RATE,
            "command": "?",
            "response_preview": "",
            "error": "",
        }

        if not path:
            result["error"] = "empty target"
            return result

        if serial is None:
            result["error"] = "pyserial is not installed"
            return result

        try:
            result["attempted"] = True
            with serial.Serial(
                path,
                self.BAUD_RATE,
                timeout=self.OPEN_TIMEOUT,
                write_timeout=self.OPEN_TIMEOUT,
            ) as handle:
                handle.reset_input_buffer()
                handle.reset_output_buffer()
                handle.write(b"?\r")
                handle.flush()
                time.sleep(self.HANDSHAKE_WAIT)
                raw = handle.read(self.HANDSHAKE_READ_LIMIT)
                preview = raw.decode("utf-8", errors="replace").strip()
                result["response_preview"] = preview[:1000]
                result["success"] = bool(preview)
                if not preview:
                    result["error"] = "no response received"
        except (SerialException, OSError, ValueError) as exc:
            result["error"] = str(exc)

        return result
