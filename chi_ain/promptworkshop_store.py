"""
Shared prompt workshop storage helpers.

Source of truth:
  chi_ain/promptworkshop/
    prompts/
    maps/
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def normalize_workshop_root(path: str | None) -> str | None:
    if not path:
        return None
    candidate = Path(path).expanduser().resolve()
    if candidate.name == "promptworkshop":
        return str(candidate)
    nested = candidate / "promptworkshop"
    if nested.is_dir() or candidate.name == "chi_ain":
        return str(nested)
    return str(candidate)


def resolve_local_workshop_root(reference_file: str) -> str | None:
    page_file = Path(reference_file).resolve()
    chi_ain_root = page_file.parent.parent
    workshop_root = chi_ain_root / "promptworkshop"
    if workshop_root.is_dir():
        return str(workshop_root)
    return None


def ensure_workshop_dirs(workshop_root: str) -> tuple[str, str]:
    prompts_dir = os.path.join(workshop_root, "prompts")
    maps_dir = os.path.join(workshop_root, "maps")
    os.makedirs(prompts_dir, exist_ok=True)
    os.makedirs(maps_dir, exist_ok=True)
    return prompts_dir, maps_dir


def list_records(base_dir: str) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    if not base_dir or not os.path.isdir(base_dir):
        return records
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = sorted(dirs)
        for name in sorted(files):
            if not name.endswith(".json"):
                continue
            full = os.path.join(root, name)
            display = os.path.relpath(full, base_dir)
            records.append((display, full))
    return records


def load_json_record(path: str, empty_factory):
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    record = empty_factory()
    for key, value in data.items():
        if key in record:
            record[key] = value
    return record


def write_json_record(path: str, record: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)


def resolve_prompt_body(prompts_dir: str, ref: str) -> str | None:
    if not prompts_dir:
        return None
    candidates = []
    if ref.endswith(".json"):
        candidates.append(os.path.join(prompts_dir, ref))
    else:
        candidates.append(os.path.join(prompts_dir, ref + ".json"))
        candidates.append(os.path.join(prompts_dir, ref))
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data.get("body", "")
        except Exception:
            return None
    return None


def assemble_map_preview(prompts_dir: str, map_record: dict) -> str:
    parts: list[str] = []
    for block in map_record.get("blocks", []):
        btype = block.get("type", "?")
        if btype == "user_input":
            parts.append("<<user_input>>")
        elif btype == "prompt_ref":
            ref = block.get("ref", "")
            body = resolve_prompt_body(prompts_dir, ref)
            parts.append(body if body is not None else f"[unresolved: {ref}]")
        else:
            parts.append(f"[unknown block type: {btype}]")
    return "\n\n---\n\n".join(parts)
