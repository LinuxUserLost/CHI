"""
sidewindow_discovery.py — Guichi Shell
Discovers chiside_* sidewindow packs from a root directory.

A valid chiside_* pack requires:
  - chiside_manifest.json   (with sidewindow_id field)
  - __init__.py             (the sidewindow entry point)

Mirrors the shell_discovery pattern but is intentionally simpler:
each chiside_* folder is exactly one sidewindow (no pages.json list needed).
"""

import os
import json
import importlib.util
import traceback
from datetime import datetime, timezone

SIDEWINDOW_PREFIX = "chiside_"
REQUIRED_MANIFEST = "chiside_manifest.json"
REQUIRED_ENTRY    = "__init__.py"
REQUIRED_FIELDS   = ("sidewindow_id",)


def discover(root):
    """
    Scan root for chiside_* folders. Returns a list of finding dicts.
    Never raises — errors are captured per-entry.
    """
    findings = []
    skipped  = []
    scan_errors = []

    try:
        if not os.path.isdir(root):
            scan_errors.append(f"root not a directory: {root}")
            return {"findings": findings, "skipped": skipped, "scan_errors": scan_errors}

        for name in sorted(os.listdir(root)):
            if not name.startswith(SIDEWINDOW_PREFIX):
                continue
            folder_path = os.path.join(root, name)
            if not os.path.isdir(folder_path):
                continue
            entry = _entry_from_folder(folder_path)
            if entry is None:
                skipped.append(folder_path)
            else:
                findings.append(entry)

    except OSError as e:
        scan_errors.append(str(e))

    return {"findings": findings, "skipped": skipped, "scan_errors": scan_errors}


def _entry_from_folder(folder_path):
    """
    Validate one chiside_* folder and return a finding dict.
    Returns None if the folder should be skipped entirely (no manifest).
    """
    folder_name = os.path.basename(folder_path)
    manifest_path = os.path.join(folder_path, REQUIRED_MANIFEST)
    init_path     = os.path.join(folder_path, REQUIRED_ENTRY)

    entry = {
        "sidewindow_id":   None,
        "sidewindow_name": folder_name,
        "short_label":     "",
        "description":     "",
        "source_path":     folder_path,
        "folder_name":     folder_name,
        "init_path":       init_path,
        "tags":            [],
        "linked_pages":    [],
        "linked_packs":    [],
        "pages":           [],
        "status":          "ok",
        "warnings":        [],
        "errors":          [],
        "last_scanned":    datetime.now(timezone.utc).isoformat(),
    }

    # Manifest required to be a sidewindow pack at all
    if not os.path.isfile(manifest_path):
        return None

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        entry["status"] = "unavailable"
        entry["errors"].append(f"manifest parse error: {e}")
        entry["sidewindow_id"] = folder_name
        return entry

    # Required field
    sid = manifest.get("sidewindow_id")
    if not sid:
        entry["status"] = "unavailable"
        entry["errors"].append("manifest missing required field: sidewindow_id")
        entry["sidewindow_id"] = folder_name
        return entry

    entry["sidewindow_id"]   = sid
    entry["sidewindow_name"] = manifest.get("sidewindow_name", folder_name)
    entry["description"]     = manifest.get("description", "")
    entry["tags"]            = manifest.get("tags", [])
    entry["linked_pages"]    = manifest.get("linked_pages", [])
    entry["linked_packs"]    = manifest.get("linked_packs", [])

    # short_label: explicit in manifest, or auto-generated from sidewindow_name
    raw_label = manifest.get("short_label", "")
    entry["short_label"] = raw_label if raw_label else entry["sidewindow_name"][:2].title()

    # chiside_pages.json: optional multi-page spec (stored, not loaded yet)
    pages_path = os.path.join(folder_path, "chiside_pages.json")
    if os.path.isfile(pages_path):
        try:
            with open(pages_path, "r", encoding="utf-8") as f:
                pages_data = json.load(f)
            entry["pages"] = pages_data.get("pages", [])
        except (json.JSONDecodeError, OSError) as e:
            entry["warnings"].append(f"chiside_pages.json parse error: {e}")

    # Entry point required
    if not os.path.isfile(init_path):
        entry["status"] = "unavailable"
        entry["errors"].append(f"missing entry point: {REQUIRED_ENTRY}")
        return entry

    # Check build callable is importable
    try:
        spec = importlib.util.spec_from_file_location(
            f"_chiside_probe_{sid}", init_path,
        )
        if spec is None:
            raise ImportError("could not build import spec")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if not callable(getattr(mod, "build", None)):
            entry["status"] = "warning"
            entry["warnings"].append("__init__.py has no build() callable")
    except Exception:
        entry["status"] = "warning"
        entry["warnings"].append(f"import probe failed: {traceback.format_exc(limit=3)}")

    return entry
