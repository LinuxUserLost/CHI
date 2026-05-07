"""
chiside_jsondisplayer — Guichi Shell sidepack
Loads the first .json file (alphabetically) from its library/ subdirectory
and displays it in a scrollable read-only text widget.
"""

import os
import json
import tkinter as tk
from tkinter import ttk

_PACK_DIR   = os.path.dirname(os.path.abspath(__file__))   # chiside_jsondisplayer/
_REPO_DIR   = os.path.dirname(_PACK_DIR)                   # pychi/
_LIBRARY_DIR = os.path.join(_PACK_DIR, "library")

CODENAME = "chiside_jsondisplayer"


def _find_first_json():
    if not os.path.isdir(_LIBRARY_DIR):
        return None, f"library directory not found: {_LIBRARY_DIR}"
    json_files = sorted(
        f for f in os.listdir(_LIBRARY_DIR)
        if f.lower().endswith(".json") and os.path.isfile(os.path.join(_LIBRARY_DIR, f))
    )
    if not json_files:
        return None, "no .json files found in library/"
    return os.path.join(_LIBRARY_DIR, json_files[0]), None


def _load_json(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data, os.path.basename(file_path), None
    except (json.JSONDecodeError, OSError) as e:
        return None, None, str(e)


def build(parent):
    file_path, find_error = _find_first_json()
    if find_error:
        _build_error(parent, find_error)
        return
    data, filename, load_error = _load_json(file_path)
    if load_error:
        _build_error(parent, f"failed to load {os.path.basename(file_path)}:\n{load_error}")
        return
    _build_display(parent, filename, data)


def _build_display(parent, filename, data):
    tk.Label(
        parent, text=filename,
        font=("TkDefaultFont", 9, "bold"),
        anchor=tk.W, padx=6, pady=4,
    ).pack(fill=tk.X)
    tk.Frame(parent, height=1, bg="#555555").pack(fill=tk.X, padx=4)
    text_frame = tk.Frame(parent)
    text_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
    scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL)
    text_widget = tk.Text(
        text_frame,
        wrap=tk.WORD, font=("TkFixedFont", 9),
        yscrollcommand=scrollbar.set,
        padx=4, pady=4, relief=tk.FLAT, borderwidth=0,
    )
    scrollbar.configure(command=text_widget.yview)
    text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    formatted = json.dumps(data, indent=2, ensure_ascii=False)
    text_widget.insert(tk.END, formatted)
    text_widget.configure(state=tk.DISABLED)


def _build_error(parent, message):
    tk.Label(
        parent, text="jsondisplayer",
        font=("TkDefaultFont", 9, "bold"),
        fg="#e05050", anchor=tk.W, padx=6, pady=4,
    ).pack(fill=tk.X)
    tk.Label(
        parent, text=message,
        font=("TkFixedFont", 8), fg="#c08080",
        anchor=tk.NW, wraplength=220, justify=tk.LEFT,
        padx=6, pady=4,
    ).pack(fill=tk.BOTH, expand=True)


def set_theme(tokens):
    pass
