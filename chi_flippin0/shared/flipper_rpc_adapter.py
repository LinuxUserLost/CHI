from __future__ import annotations

from typing import Any, Dict, List

try:
    from flipperzero_protobuf.cli_helpers import dict2datetime
    from flipperzero_protobuf.flipper_proto import FlipperProto
except ImportError:  # pragma: no cover - optional dependency path
    FlipperProto = None
    dict2datetime = None


class FlipperRpcAdapter:
    """Optional adapter around flipperzero_protobuf_py.

    This adapter only exposes actions that are explicitly shown in the public
    project examples: ping, device info, datetime retrieval, and read-only
    storage listing.
    """

    def backend_status(self) -> Dict[str, Any]:
        return {
            "available": FlipperProto is not None,
            "backend": "flipperzero_protobuf_py" if FlipperProto is not None else "unavailable",
            "reason": "" if FlipperProto is not None else "flipperzero_protobuf_py is not installed",
        }

    def ping(self) -> Dict[str, Any]:
        if FlipperProto is None:
            return {"ok": False, "error": "flipperzero_protobuf_py is not installed", "data": None}
        try:
            proto = FlipperProto()
            resp = proto.rpc_system_ping()
            return {"ok": True, "error": "", "data": resp}
        except Exception as exc:  # pragma: no cover - device dependent path
            return {"ok": False, "error": str(exc), "data": None}

    def device_info(self) -> Dict[str, Any]:
        if FlipperProto is None:
            return {"ok": False, "error": "flipperzero_protobuf_py is not installed", "data": None}
        try:
            proto = FlipperProto()
            resp = proto.rpc_device_info()
            return {"ok": True, "error": "", "data": resp}
        except Exception as exc:  # pragma: no cover - device dependent path
            return {"ok": False, "error": str(exc), "data": None}

    def datetime_info(self) -> Dict[str, Any]:
        if FlipperProto is None:
            return {"ok": False, "error": "flipperzero_protobuf_py is not installed", "data": None}
        try:
            proto = FlipperProto()
            resp = proto.rpc_get_datetime()
            converted = dict2datetime(resp).isoformat() if dict2datetime is not None else resp
            return {"ok": True, "error": "", "data": {"raw": resp, "iso": converted}}
        except Exception as exc:  # pragma: no cover - device dependent path
            return {"ok": False, "error": str(exc), "data": None}

    def list_path(self, path: str) -> Dict[str, Any]:
        if FlipperProto is None:
            return {"ok": False, "error": "flipperzero_protobuf_py is not installed", "data": None}

        clean_path = self._clean_path(path)
        try:
            proto = FlipperProto()
            resp = proto.rpc_storage_list(clean_path)
            cleaned: List[Dict[str, Any]] = []
            for item in resp:
                cleaned.append(dict(item))
            return {"ok": True, "error": "", "data": {"path": clean_path, "entries": cleaned}}
        except Exception as exc:  # pragma: no cover - device dependent path
            return {"ok": False, "error": str(exc), "data": {"path": clean_path}}

    def list_ext(self) -> Dict[str, Any]:
        return self.list_path('/ext')

    def _clean_path(self, path: str) -> str:
        path = (path or '').strip()
        if not path:
            return '/'
        if not path.startswith('/'):
            return '/' + path
        return path
