"""
sidewindow_registry.py — Guichi Shell
Load, save, and merge the sidewindow registry.

Registry shape:
{
  "version": 1,
  "sidewindows": [ { sidewindow_id, sidewindow_name, source_path, ... } ]
}
"""

import os
import json
from datetime import datetime, timezone


def _empty_registry():
    return {"version": 1, "sidewindows": []}


def load_registry(path):
    """
    Load sidewindow registry from JSON.
    Returns an empty registry on missing or corrupt file.
    """
    if not os.path.isfile(path):
        return _empty_registry()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("sidewindows"), list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return _empty_registry()


def save_registry(registry, path):
    """Write registry to JSON. Creates parent directory if needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)


def merge_findings(registry, findings):
    """
    Merge new scan findings into the existing registry.

    - New entries are added.
    - Existing entries matched by (sidewindow_id + source_path) are updated.
    - Entries from prior scans that were not found this scan are kept as-is
      (same preserve-unknown behaviour as shell_registry).

    Returns list of action dicts: [{"action": str, "sidewindow_id": str, "source_path": str}]
    """
    existing = {
        (e.get("sidewindow_id"), e.get("source_path")): e
        for e in registry.get("sidewindows", [])
    }

    actions = []

    for finding in findings:
        key = (finding.get("sidewindow_id"), finding.get("source_path"))
        if key in existing:
            existing[key].update(finding)
            actions.append({
                "action": "updated",
                "sidewindow_id": finding.get("sidewindow_id"),
                "source_path": finding.get("source_path"),
            })
        else:
            existing[key] = finding
            actions.append({
                "action": "added",
                "sidewindow_id": finding.get("sidewindow_id"),
                "source_path": finding.get("source_path"),
            })

    registry["sidewindows"] = list(existing.values())
    return actions
