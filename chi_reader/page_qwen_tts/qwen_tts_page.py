"""
page_qwen_tts / qwen_tts_page.py
────────────────────────────────────────────────────────────────────────────
Local Qwen TTS control page for Guichi shell — pagepack_chillama.

Shell contract (matches existing pack pages):
    page = QwenTTSPage(parent_widget)
    page.build(parent)   # also: create_widgets / mount / render

Layout:
    ┌─────────────────────────────────────────────┐
    │  Model:  [dropdown]   Voice: [dropdown]      │
    │  Runtime status dot                          │
    ├─────────────────────────────────────────────┤
    │  ┌──────────────────────────────────────┐   │
    │  │  Text input / paste area             │   │
    │  │  (large, scrollable)                 │   │
    │  └──────────────────────────────────────┘   │
    │  [Upload .txt]  [Upload .md]  [Clear]        │
    ├─────────────────────────────────────────────┤
    │  [▶ Generate Audio]  (big button)            │
    ├─────────────────────────────────────────────┤
    │  Status area (multi-line)                   │
    │  Output: /path/to/file.wav  [Open Folder]   │
    └─────────────────────────────────────────────┘

Backend: local qwen-tts-demo via helpers/qwen_backend.py
         Fails gracefully if runtime/paths are missing.
"""

import os
import sys
import time
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from gui_files import interaction_support

# ── Ensure pack root is importable ───────────────────────────────────────────
_THIS_FILE = os.path.abspath(__file__)
_PAGE_DIR  = os.path.dirname(_THIS_FILE)
_PACK_DIR  = os.path.dirname(_PAGE_DIR)
if _PACK_DIR not in sys.path:
    sys.path.insert(0, _PACK_DIR)

from helpers.qwen_tts_backend import QwenBackend, OUTPUT_DIR, _safe_stem


# ═════════════════════════════════════════════════════════════════════════════
# VOICES
# ─────────────────────────────────────────────────────────────────────────────
# These are placeholder voice IDs for Qwen3-TTS CustomVoice models.
# The CustomVoice variants expose a set of built-in speaker IDs.
# Exact IDs are runtime-dependent — update this list once you have confirmed
# the voice IDs your local qwen-tts-demo accepts.
#
# To discover available voices:
#   activate your venv and run:
#   python inference.py --list-voices
#   (or check the demo script's --help output)
# ═════════════════════════════════════════════════════════════════════════════

CUSTOM_VOICES = [
    "aiden",
    "dylan",
    "eric",
    "ono_anna",
    "ryan",
    "serena",
    "sohee",
    "uncle_fu",
    "vivian",
]

DEFAULT_VOICE = "ryan"

# ── Languages ─────────────────────────────────────────────────────────────────
# "auto" → model detects language automatically (passes language=None internally).
# Remaining values come from the model's codec_language_id keys (non-dialect).
LANGUAGES = [
    "auto",
    "english", "chinese", "japanese", "korean",
    "french",  "german",  "spanish", "italian",
    "portuguese", "russian",
]

DEFAULT_LANGUAGE = "auto"

# ── Models ────────────────────────────────────────────────────────────────────
MODELS = [
    "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",   # default — fast on CPU
    "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",   # larger, slower
]

DEFAULT_MODEL = MODELS[0]

_DEFAULT_PAGE_THEME = {
    "app_bg": "#f4f4f0",
    "content_bg": "#f4f4f0",
    "panel_bg": "#ffffff",
    "sidebar_bg": "#ecece6",
    "text_main": "#1b1b1b",
    "text_muted": "#6f6f6f",
    "text_active": "#000000",
    "text_on_accent": "#ffffff",
    "button_bg": "#e8e8e2",
    "button_hover": "#d9d9d0",
    "button_active": "#ffffff",
    "button_disabled": "#b8b8b0",
    "accent": "#1a5276",
    "border": "#cfcfc6",
}


def _bind_scroll(widget):
    interaction_support.bind_wheel_scroll(widget)


# ═════════════════════════════════════════════════════════════════════════════
# MAIN PAGE CLASS
# ═════════════════════════════════════════════════════════════════════════════

class QwenTTSPage:
    """
    Qwen TTS control page — Guichi shell page.

    Instantiation:  QwenTTSPage(parent_frame)
    GUI mount:      .build(parent) / .create_widgets(parent) / .mount(parent)
    """

    PAGE_NAME = "Qwen TTS"

    def __init__(self, parent, app=None, page_key="", page_folder="",
                 *args, **kwargs):
        app         = kwargs.pop("controller",    app)
        page_key    = kwargs.pop("page_context",  page_key)
        page_folder = kwargs.pop("page_folder",   page_folder)

        self.parent      = parent
        self.app         = app
        self.page_key    = page_key
        self.page_folder = page_folder
        self.guichi_page_theme = None
        self._theme_tokens = dict(_DEFAULT_PAGE_THEME)
        self._style_prefix = f"QwenTTS.{id(self)}"

        # Backend
        self._backend    = QwenBackend()
        self._generating = False
        self._last_output_path = ""

        # Generation stats / timer state
        self._gen_start_time    = None
        self._gen_timer_after_id = None
        self._gen_words         = 0
        self._gen_chars         = 0
        self._gen_current_var   = tk.StringVar(value="Current: —")
        self._gen_last_var      = tk.StringVar(value="Last: —")
        self._status_placeholder_active = True
        self._status_help_text = (
            "Qwen TTS is ready for input.\n"
            "1. Paste or upload text.\n"
            "2. Pick a voice and optional title.\n"
            "3. Generate audio and save/open the result path."
        )

        self._style = None
        self._settings_strip = None
        self._instruct_bar = None
        self._upload_row = None
        self._text_frame = None
        self._generate_row = None
        self._status_frame = None
        self._output_row = None
        self._path_entry = None

        # Build root frame
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(2, weight=1)   # text area grows

        self._build_settings_strip()   # row 0
        self._build_text_area()        # rows 1-2
        self._build_generate_row()     # row 3
        self._build_status_area()      # row 4-5
        self._apply_theme()

        # Deferred runtime check
        self.frame.after(400, self._check_runtime_status)

    # ── Shell mount methods (same contract as existing pages) ─────────────────

    def _embed_into_parent(self, parent=None):
        container = parent or self.parent
        try:
            if container is not None and self.frame.master is not container:
                self.frame.destroy()
                self.parent = container
                self.frame  = ttk.Frame(container)
                self.frame.columnconfigure(0, weight=1)
                self.frame.rowconfigure(2, weight=1)
                self._build_settings_strip()
                self._build_text_area()
                self._build_generate_row()
                self._build_status_area()
                self._apply_theme()
                self.frame.after(400, self._check_runtime_status)
        except Exception:
            pass
        try:
            self.frame.pack(fill="both", expand=True)
        except Exception:
            try:
                self.frame.grid(row=0, column=0, sticky="nsew")
            except Exception:
                pass
        return self.frame

    def build(self, parent=None):
        return self._embed_into_parent(parent)
    def create_widgets(self, parent=None):
        return self._embed_into_parent(parent)
    def mount(self, parent=None):
        return self._embed_into_parent(parent)
    def render(self, parent=None):
        return self._embed_into_parent(parent)

    # ═════════════════════════════════════════════════════════════════════════
    # ROW 0 — Settings strip: model, voice, runtime indicator
    # ═════════════════════════════════════════════════════════════════════════

    def set_guichi_page_theme(self, context):
        self.guichi_page_theme = context
        tokens = dict(_DEFAULT_PAGE_THEME)
        if isinstance(context, dict):
            tokens.update(context)
        self._theme_tokens = tokens
        self._apply_theme()

    def _build_settings_strip(self):
        strip = tk.Frame(self.frame, padx=8, pady=6)
        strip.grid(row=0, column=0, sticky="ew")
        strip.columnconfigure(99, weight=1)   # right spacer
        self._settings_strip = strip

        col = 0

        # Runtime dot
        self._rt_dot = tk.Label(strip, text="\u25cf", font=("", 13),
                                fg="#888")
        self._rt_dot.grid(row=0, column=col, padx=(0, 4))
        col += 1

        self._rt_label = tk.Label(strip, text="Checking runtime\u2026",
                                  font=("", 9), anchor="w")
        self._rt_label.grid(row=0, column=col, padx=(0, 16))
        col += 1

        # Model
        tk.Label(strip, text="Model:", font=("", 9)).grid(row=0, column=col, padx=(0, 3))
        col += 1

        self._model_var = tk.StringVar(value=DEFAULT_MODEL)
        self._model_combo = ttk.Combobox(
            strip, textvariable=self._model_var,
            values=MODELS, width=28, state="readonly", font=("", 9),
            style=f"{self._style_prefix}.TCombobox")
        self._model_combo.grid(row=0, column=col, padx=(0, 14))
        col += 1

        # Voice
        tk.Label(strip, text="Voice:", font=("", 9)).grid(row=0, column=col, padx=(0, 3))
        col += 1

        self._voice_var = tk.StringVar(value=DEFAULT_VOICE)
        self._voice_combo = ttk.Combobox(
            strip, textvariable=self._voice_var,
            values=CUSTOM_VOICES, width=16, font=("", 9),
            style=f"{self._style_prefix}.TCombobox")
        self._voice_combo.grid(row=0, column=col, padx=(0, 4))
        col += 1

        # Editable voice entry tooltip
        tk.Label(strip, text="(editable)", font=("", 8)).grid(
            row=0, column=col, padx=(0, 4))
        col += 1

        # Language
        tk.Label(strip, text="Lang:", font=("", 9)).grid(row=0, column=col, padx=(0, 3))
        col += 1

        self._lang_var = tk.StringVar(value=DEFAULT_LANGUAGE)
        self._lang_combo = ttk.Combobox(
            strip, textvariable=self._lang_var,
            values=LANGUAGES, width=12, state="readonly", font=("", 9),
            style=f"{self._style_prefix}.TCombobox")
        self._lang_combo.grid(row=0, column=col, padx=(0, 14))
        col += 1

        # Spacer
        tk.Frame(strip).grid(row=0, column=99, sticky="ew")

        # Re-check button (far right)
        ttk.Button(strip, text="\u21bb Re-check",
                   command=self._check_runtime_status,
                   width=10, style=f"{self._style_prefix}.TButton").grid(row=0, column=100, padx=(4, 0))

        # ── Row 1 inside strip: Instruct (optional) ───────────────────────────
        instruct_bar = tk.Frame(strip)
        instruct_bar.grid(row=1, column=0, columnspan=101, sticky="ew",
                          padx=4, pady=(0, 4))
        instruct_bar.columnconfigure(1, weight=1)
        self._instruct_bar = instruct_bar

        tk.Label(instruct_bar, text="Instruct:", font=("", 9)).grid(row=0, column=0,
                                                   padx=(0, 4), sticky="w")
        self._instruct_var = tk.StringVar(value="")
        ttk.Entry(instruct_bar, textvariable=self._instruct_var,
                  font=("", 9), style=f"{self._style_prefix}.TEntry").grid(row=0, column=1, sticky="ew", padx=(0, 6))
        tk.Label(instruct_bar,
                 text="optional · style/tone hint · silently ignored on 0.6B",
                 font=("", 8)).grid(row=0, column=2, sticky="w")

    # ═════════════════════════════════════════════════════════════════════════
    # ROW 1-2 — Text input area + upload buttons
    # ═════════════════════════════════════════════════════════════════════════

    def _build_text_area(self):
        # Upload button row (row 1)
        btn_row = ttk.Frame(self.frame, padding=(8, 4, 8, 2), style=f"{self._style_prefix}.TFrame")
        btn_row.grid(row=1, column=0, sticky="ew")
        self._upload_row = btn_row

        ttk.Button(btn_row, text="\U0001f4c4 Upload .txt",
                   command=self._upload_txt, width=14, style=f"{self._style_prefix}.TButton").pack(side="left", padx=(0, 4))
        ttk.Button(btn_row, text="\U0001f4dd Upload .md",
                   command=self._upload_md,  width=14, style=f"{self._style_prefix}.TButton").pack(side="left", padx=(0, 4))

        ttk.Separator(btn_row, orient="vertical").pack(
            side="left", fill="y", padx=8, pady=2)

        ttk.Button(btn_row, text="Clear Text",
                   command=self._clear_text, width=10, style=f"{self._style_prefix}.TButton").pack(side="left", padx=(0, 4))

        ttk.Separator(btn_row, orient="vertical").pack(
            side="left", fill="y", padx=8, pady=2)

        tk.Label(btn_row, text="Title:", font=("", 9)).pack(side="left", padx=(0, 3))
        self._title_var = tk.StringVar(value="")
        ttk.Entry(btn_row, textvariable=self._title_var,
                  font=("", 9), width=22, style=f"{self._style_prefix}.TEntry").pack(side="left", padx=(0, 4))
        ttk.Button(btn_row, text="\U0001f4be Save Input",
                   command=self._save_input, width=12, style=f"{self._style_prefix}.TButton").pack(side="left", padx=(0, 4))

        self._char_count_var = tk.StringVar(value="0 chars")
        ttk.Label(btn_row, textvariable=self._char_count_var,
                  font=("", 8), style=f"{self._style_prefix}.Muted.TLabel").pack(side="right", padx=8)

        # Text area (row 2)
        txt_frame = ttk.Frame(self.frame, padding=(8, 0, 8, 4), style=f"{self._style_prefix}.TFrame")
        txt_frame.grid(row=2, column=0, sticky="nsew")
        txt_frame.columnconfigure(0, weight=1)
        txt_frame.rowconfigure(0, weight=1)
        self._text_frame = txt_frame

        self._text_input = tk.Text(
            txt_frame, wrap="word", undo=True,
            font=("", 11), relief="solid", borderwidth=1,
            padx=10, pady=8, insertwidth=2,
            selectbackground="#c8d8f0", spacing3=2)
        tsb = ttk.Scrollbar(txt_frame, orient="vertical",
                             command=self._text_input.yview)
        self._text_input.configure(yscrollcommand=tsb.set)
        self._text_input.grid(row=0, column=0, sticky="nsew")
        tsb.grid(row=0, column=1, sticky="ns")
        _bind_scroll(self._text_input)
        interaction_support.setup_text_widget(self._text_input, wheel=False)

        # Placeholder hint
        self._placeholder_active = True
        self._placeholder_text   = "Paste or type text here, or upload a .txt / .md file\u2026"
        self._text_input.insert("1.0", self._placeholder_text)
        self._text_input.configure(fg=self._theme_tokens["text_muted"])

        self._text_input.bind("<FocusIn>",  self._on_text_focus_in)
        self._text_input.bind("<FocusOut>", self._on_text_focus_out)
        self._text_input.bind("<<Modified>>", self._on_text_modified)

    # ── Text area helpers ─────────────────────────────────────────────────────

    def _on_text_focus_in(self, event=None):
        if self._placeholder_active:
            self._text_input.delete("1.0", "end")
            self._text_input.configure(fg=self._theme_tokens["text_main"])
            self._placeholder_active = False

    def _on_text_focus_out(self, event=None):
        content = self._text_input.get("1.0", "end-1c").strip()
        if not content:
            self._text_input.delete("1.0", "end")
            self._text_input.insert("1.0", self._placeholder_text)
            self._text_input.configure(fg=self._theme_tokens["text_muted"])
            self._placeholder_active = True

    def _on_text_modified(self, event=None):
        self._text_input.edit_modified(False)
        if not self._placeholder_active:
            n = len(self._text_input.get("1.0", "end-1c"))
            self._char_count_var.set(f"{n:,} chars")

    def _get_text(self) -> str:
        """Return current text content (empty string if placeholder active)."""
        if self._placeholder_active:
            return ""
        return self._text_input.get("1.0", "end-1c").strip()

    def _set_text(self, content: str):
        """Replace text area contents."""
        self._text_input.configure(fg=self._theme_tokens["text_main"])
        self._text_input.delete("1.0", "end")
        self._text_input.insert("1.0", content)
        self._placeholder_active = False
        n = len(content)
        self._char_count_var.set(f"{n:,} chars")

    def _clear_text(self):
        self._text_input.delete("1.0", "end")
        self._on_text_focus_out()
        self._char_count_var.set("0 chars")
        self._set_status("Text cleared.", kind="info")

    def _upload_txt(self):
        self._upload_text_file([("Text files", "*.txt"), ("All files", "*.*")])

    def _upload_md(self):
        self._upload_text_file([("Markdown files", "*.md"), ("All files", "*.*")])

    def _save_input(self):
        """Save current text area contents to a .txt file chosen by the user."""
        text = self._get_text()
        if not text:
            self._set_status("Nothing to save — text area is empty.", kind="warn")
            return
        from datetime import datetime
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        title = self._title_var.get().strip()
        slug  = _safe_stem(title) if title else _safe_stem(text)
        default_name = f"{stamp}_{slug}.txt"
        path = filedialog.asksaveasfilename(
            title="Save input text",
            initialfile=default_name,
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            self._set_status(f"Saved input to: {path}", kind="ok")
        except OSError as exc:
            self._set_status(f"Save error: {exc}", kind="error")

    def _upload_text_file(self, filetypes):
        path = filedialog.askopenfilename(
            title="Choose a text file", filetypes=filetypes)
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
            self._set_text(content)
            fname = os.path.basename(path)
            self._set_status(
                f"Loaded: {fname}  ({len(content):,} chars)", kind="ok")
        except Exception as exc:
            self._set_status(f"Read error: {exc}", kind="error")

    # ═════════════════════════════════════════════════════════════════════════
    # ROW 3 — Generate button
    # ═════════════════════════════════════════════════════════════════════════

    def _build_generate_row(self):
        gen_row = ttk.Frame(self.frame, padding=(8, 4), style=f"{self._style_prefix}.TFrame")
        gen_row.grid(row=3, column=0, sticky="ew")
        gen_row.columnconfigure(1, weight=1)
        self._generate_row = gen_row

        self._gen_btn = tk.Button(
            gen_row,
            text="\u25b6  Generate Audio",
            font=("", 12, "bold"),
            relief="flat", padx=24, pady=10,
            cursor="hand2",
            command=self._on_generate)
        self._gen_btn.grid(row=0, column=0, sticky="w")

        # Word / char summary label
        self._summary_var = tk.StringVar(value="")
        ttk.Label(gen_row, textvariable=self._summary_var,
                  font=("", 9), style=f"{self._style_prefix}.Muted.TLabel").grid(
            row=0, column=1, sticky="w", padx=16)

        # Generation stats row
        stats_row = ttk.Frame(gen_row)
        stats_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        self._stats_row = stats_row
        ttk.Label(stats_row, textvariable=self._gen_current_var,
                  font=("Monospace", 9), style=f"{self._style_prefix}.Accent.TLabel").pack(
            side="left", padx=(0, 20))
        ttk.Label(stats_row, textvariable=self._gen_last_var,
                  font=("Monospace", 9), style=f"{self._style_prefix}.Muted.TLabel").pack(
            side="left")

    # ═════════════════════════════════════════════════════════════════════════
    # ROW 4-5 — Status area + output path
    # ═════════════════════════════════════════════════════════════════════════

    def _build_status_area(self):
        # Status text box (row 4)
        status_frame = ttk.Frame(self.frame, padding=(8, 2, 8, 2), style=f"{self._style_prefix}.TFrame")
        status_frame.grid(row=4, column=0, sticky="ew")
        status_frame.columnconfigure(0, weight=1)
        self._status_frame = status_frame

        self._status_text = tk.Text(
            status_frame, height=6, wrap="word",
            font=("Monospace", 9), relief="flat",
            state="disabled", padx=8, pady=6,
            borderwidth=1)
        self._status_text.grid(row=0, column=0, sticky="ew")
        _bind_scroll(self._status_text)
        interaction_support.setup_text_widget(self._status_text, wheel=False)

        # Output path row (row 5)
        out_row = ttk.Frame(self.frame, padding=(8, 2, 8, 6), style=f"{self._style_prefix}.TFrame")
        out_row.grid(row=5, column=0, sticky="ew")
        out_row.columnconfigure(1, weight=1)
        self._output_row = out_row

        ttk.Label(out_row, text="Output:", font=("", 9),
                  style=f"{self._style_prefix}.TLabel").grid(row=0, column=0, padx=(0, 6))

        self._output_path_var = tk.StringVar(value="No audio generated yet.")
        self._path_entry = ttk.Entry(out_row, textvariable=self._output_path_var,
                                     state="readonly", font=("Monospace", 9), style=f"{self._style_prefix}.TEntry")
        self._path_entry.grid(row=0, column=1, sticky="ew", padx=(0, 6))

        self._open_folder_btn = ttk.Button(
            out_row, text="\U0001f4c2 Open Folder",
            command=self._open_output_folder, width=14, style=f"{self._style_prefix}.TButton")
        self._open_folder_btn.grid(row=0, column=2)
        self._write_status_help()

    def _write_status_help(self):
        self._status_placeholder_active = True
        self._status_text.configure(state="normal")
        self._status_text.delete("1.0", "end")
        self._status_text.insert("1.0", self._status_help_text + "\n", "help")
        self._status_text.configure(state="disabled")

    def _clear_status_placeholder(self):
        if not self._status_placeholder_active:
            return
        self._status_text.configure(state="normal")
        self._status_text.delete("1.0", "end")
        self._status_text.configure(state="disabled")
        self._status_placeholder_active = False

    # ── Status helpers ────────────────────────────────────────────────────────

    def _set_status(self, msg: str, kind: str = "info"):
        """
        Append a line to the status area.
        kind: "info" | "ok" | "warn" | "error"
        """
        self._clear_status_placeholder()
        self._status_text.configure(state="normal")
        # Trim to last ~30 lines to keep it readable
        lines = int(self._status_text.index("end-1c").split(".")[0])
        if lines > 30:
            self._status_text.delete("1.0", f"{lines - 28}.0")
        tag = kind if kind in ("ok", "warn", "error") else "info"
        self._status_text.insert("end", msg + "\n", tag)
        self._status_text.configure(state="disabled")
        self._status_text.see("end")

    def _apply_theme(self):
        tokens = self._theme_tokens
        try:
            self._style = ttk.Style(self.frame)
            self._style.configure(f"{self._style_prefix}.TFrame", background=tokens["content_bg"])
            self._style.configure(f"{self._style_prefix}.TLabel", background=tokens["content_bg"], foreground=tokens["text_main"])
            self._style.configure(f"{self._style_prefix}.Muted.TLabel", background=tokens["content_bg"], foreground=tokens["text_muted"])
            self._style.configure(f"{self._style_prefix}.Accent.TLabel", background=tokens["content_bg"], foreground=tokens["accent"])
            self._style.configure(
                f"{self._style_prefix}.TButton",
                background=tokens["button_bg"],
                foreground=tokens["text_main"],
                bordercolor=tokens["border"],
                focuscolor=tokens["accent"],
            )
            self._style.map(
                f"{self._style_prefix}.TButton",
                background=[("active", tokens["button_hover"]), ("pressed", tokens["accent"])],
                foreground=[("pressed", tokens["text_on_accent"])],
            )
            self._style.configure(
                f"{self._style_prefix}.TEntry",
                fieldbackground=tokens["panel_bg"],
                foreground=tokens["text_main"],
                insertcolor=tokens["text_main"],
                bordercolor=tokens["border"],
            )
            self._style.configure(
                f"{self._style_prefix}.TCombobox",
                fieldbackground=tokens["panel_bg"],
                foreground=tokens["text_main"],
                selectbackground=tokens["accent"],
                selectforeground=tokens["text_on_accent"],
                bordercolor=tokens["border"],
                arrowcolor=tokens["text_main"],
            )
            self._style.map(
                f"{self._style_prefix}.TCombobox",
                fieldbackground=[("readonly", tokens["panel_bg"])],
                foreground=[("readonly", tokens["text_main"])],
                selectbackground=[("readonly", tokens["accent"])],
                selectforeground=[("readonly", tokens["text_on_accent"])],
            )
        except Exception:
            pass

        try:
            self.frame.configure(style=f"{self._style_prefix}.TFrame")
        except Exception:
            pass
        try:
            self.frame.configure(background=tokens["app_bg"])
        except Exception:
            pass

        for pane in (
            getattr(self, "_settings_strip", None),
            getattr(self, "_instruct_bar", None),
            getattr(self, "_upload_row", None),
            getattr(self, "_generate_row", None),
            getattr(self, "_status_frame", None),
            getattr(self, "_output_row", None),
            getattr(self, "_stats_row", None),
        ):
            try:
                pane.configure(bg=tokens["content_bg"])
            except Exception:
                pass

        for widget in getattr(self, "_settings_strip", None).winfo_children() if getattr(self, "_settings_strip", None) else []:
            if isinstance(widget, tk.Label):
                try:
                    widget.configure(bg=tokens["sidebar_bg"], fg=tokens["text_main"])
                except Exception:
                    pass
            elif isinstance(widget, tk.Frame):
                try:
                    widget.configure(bg=tokens["sidebar_bg"])
                except Exception:
                    pass
        try:
            self._settings_strip.configure(bg=tokens["sidebar_bg"])
            self._instruct_bar.configure(bg=tokens["sidebar_bg"])
        except Exception:
            pass
        for widget in getattr(self, "_instruct_bar", None).winfo_children() if getattr(self, "_instruct_bar", None) else []:
            if isinstance(widget, tk.Label):
                try:
                    fg = tokens["text_muted"] if "optional" in widget.cget("text") else tokens["text_main"]
                    widget.configure(bg=tokens["sidebar_bg"], fg=fg)
                except Exception:
                    pass

        for widget in getattr(self, "_upload_row", None).winfo_children() if getattr(self, "_upload_row", None) else []:
            if isinstance(widget, tk.Label):
                try:
                    widget.configure(bg=tokens["content_bg"], fg=tokens["text_main"])
                except Exception:
                    pass

        try:
            self._text_input.configure(
                bg=tokens["panel_bg"],
                fg=tokens["text_main"] if not self._placeholder_active else tokens["text_muted"],
                insertbackground=tokens["text_main"],
                highlightbackground=tokens["border"],
                highlightcolor=tokens["accent"],
                selectbackground=tokens["accent"],
                selectforeground=tokens["text_on_accent"],
            )
        except Exception:
            pass
        try:
            self._status_text.configure(
                bg=tokens["panel_bg"],
                fg=tokens["text_main"],
                insertbackground=tokens["text_main"],
                selectbackground=tokens["accent"],
                selectforeground=tokens["text_on_accent"],
            )
            self._status_text.tag_configure("ok", foreground="#2e7d32")
            self._status_text.tag_configure("warn", foreground="#e65100")
            self._status_text.tag_configure("error", foreground="#c62828")
            self._status_text.tag_configure("info", foreground=tokens["text_main"])
            self._status_text.tag_configure("help", foreground=tokens["text_muted"])
        except Exception:
            pass
        try:
            self._gen_btn.configure(
                bg=tokens["accent"],
                fg=tokens["text_on_accent"],
                activebackground=tokens["button_hover"],
                activeforeground=tokens["text_on_accent"],
                disabledforeground=tokens["button_disabled"],
                highlightbackground=tokens["content_bg"],
            )
        except Exception:
            pass

    # ── Runtime check ─────────────────────────────────────────────────────────

    def _check_runtime_status(self):
        """
        Run on startup and on demand.  Shows exact path state and tells the
        user what to do next — no guessing required.
        """
        b = self._backend

        # Always show current configured paths so the user can see what
        # the backend is actually looking at.
        self._set_status("─── Qwen TTS runtime check ───────────────────", kind="info")
        self._set_status(
            "ℹ  Qwen TTS runs as a local subprocess — no server to start.",
            kind="info")
        self._set_status(
            f"   python  : {b.venv_python}", kind="info")
        self._set_status(
            f"   script  : {b.script_path}", kind="info")
        self._set_status(
            f"   output  : {b.output_dir}",  kind="info")

        rt = b.check_runtime()
        if rt["ok"]:
            self._rt_dot.configure(fg="#2e7d32")
            self._rt_label.configure(text="Runtime OK", fg="#2e7d32")
            self._set_status("✓  Both paths found — ready to generate.", kind="ok")
        else:
            self._rt_dot.configure(fg="#e65100")
            self._rt_label.configure(text="Runtime not found", fg="#e65100")
            self._set_status("", kind="info")
            self._set_status("✘  Missing paths:", kind="error")
            for m in rt.get("missing", []):
                self._set_status(f"     {m}", kind="error")
            self._set_status("", kind="info")
            self._set_status(
                "▶  To fix: edit VENV_PYTHON and SCRIPT_PATH at the top of",
                kind="warn")
            self._set_status(
                "     chi_reader/helpers/qwen_tts_backend.py",
                kind="warn")
            self._set_status(
                "   Then restart Guichi (or use Re-check below).", kind="warn")


    # ═════════════════════════════════════════════════════════════════════════
    # GENERATE
    # ═════════════════════════════════════════════════════════════════════════

    # ── Generation timer helpers ──────────────────────────────────────────────

    @staticmethod
    def _format_elapsed(seconds):
        seconds = int(seconds)
        h, rem = divmod(seconds, 3600)
        m, s   = divmod(rem, 60)
        if h:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _start_generation_timer(self, words, chars):
        self._gen_start_time = time.monotonic()
        self._gen_words = words
        self._gen_chars = chars
        # Cancel any stale timer from a previous run.
        if self._gen_timer_after_id is not None:
            try:
                self.frame.after_cancel(self._gen_timer_after_id)
            except Exception:
                pass
            self._gen_timer_after_id = None
        self._gen_current_var.set(
            f"Current: 00:00 running  ·  {words:,} words · {chars:,} chars")
        self._tick_generation_timer()

    def _tick_generation_timer(self):
        if not self._generating or self._gen_start_time is None:
            self._gen_timer_after_id = None
            return
        elapsed = time.monotonic() - self._gen_start_time
        self._gen_current_var.set(
            f"Current: {self._format_elapsed(elapsed)} running"
            f"  ·  {self._gen_words:,} words · {self._gen_chars:,} chars")
        try:
            self._gen_timer_after_id = self.frame.after(1000, self._tick_generation_timer)
        except Exception:
            self._gen_timer_after_id = None

    def _finish_generation_timer(self, ok: bool):
        if self._gen_timer_after_id is not None:
            try:
                self.frame.after_cancel(self._gen_timer_after_id)
            except Exception:
                pass
            self._gen_timer_after_id = None
        if self._gen_start_time is not None:
            elapsed = time.monotonic() - self._gen_start_time
            elapsed_str = self._format_elapsed(elapsed)
            result_str  = "✓ ok" if ok else "✗ failed"
            self._gen_current_var.set(
                f"Current: {elapsed_str} done  ·  {self._gen_words:,} words · {self._gen_chars:,} chars")
            self._gen_last_var.set(
                f"Last: {elapsed_str}  ·  {self._gen_words:,} words · {self._gen_chars:,} chars  ·  {result_str}")
            self._gen_start_time = None

    def _on_generate(self):
        if self._generating:
            self._set_status("Generation already in progress\u2026", kind="warn")
            return

        text = self._get_text()
        if not text:
            self._set_status("No text to synthesise — paste text or upload a file.",
                             kind="warn")
            return

        model    = self._model_var.get().strip()
        voice    = self._voice_var.get().strip() or DEFAULT_VOICE
        lang     = self._lang_var.get().strip() or DEFAULT_LANGUAGE
        title    = self._title_var.get().strip()
        instruct = self._instruct_var.get().strip()

        # Show word/char summary
        words = len(text.split())
        chars = len(text)
        self._summary_var.set(f"{words:,} words · {chars:,} chars")

        self._set_status(
            f"Generating\u2026  model={model.split('/')[-1]}  "
            f"voice={voice}  lang={lang}",
            kind="info")
        self._set_status(
            "CPU mode — this may take a while. The UI will remain responsive.",
            kind="info")

        self._generating = True
        self._gen_btn.configure(state="disabled", text="\u23f3  Generating\u2026")
        self._output_path_var.set("(generating\u2026)")
        self._start_generation_timer(words, chars)

        def _bg():
            try:
                result = self._backend.generate(
                    text, model, voice,
                    language=lang, title=title, instruct=instruct)
            except Exception as exc:
                result = {
                    "ok": False,
                    "error": f"Worker exception during Qwen TTS generation: {exc}",
                }
            try:
                self.frame.after(0, lambda: self._on_generate_done(result))
            except Exception:
                # Frame was destroyed while generating — avoid crashing the thread.
                pass

        threading.Thread(target=_bg, daemon=True).start()

    def _on_generate_done(self, result: dict):
        self._generating = False
        self._finish_generation_timer(result.get("ok", False))
        self._gen_btn.configure(state="normal", text="\u25b6  Generate Audio")

        if result["ok"]:
            path = result["path"]
            self._last_output_path = path
            self._output_path_var.set(path)
            fname = os.path.basename(path)
            self._set_status(f"\u2713 Done: {fname}", kind="ok")
            self._set_status(f"  Saved to: {path}", kind="ok")
        else:
            self._output_path_var.set("(failed)")
            self._set_status("\u2718 Generation failed:", kind="error")
            for line in result.get("error", "unknown error").splitlines():
                self._set_status(f"  {line}", kind="error")

    # ═════════════════════════════════════════════════════════════════════════
    # OUTPUT FOLDER
    # ═════════════════════════════════════════════════════════════════════════

    def _open_output_folder(self):
        folder = self._backend.output_dir
        if not os.path.isdir(folder):
            try:
                os.makedirs(folder, exist_ok=True)
                self._set_status(f"Created output folder: {folder}", kind="ok")
            except OSError as exc:
                self._set_status(f"Cannot create output folder: {exc}", kind="error")
                return

        # Try xdg-open (Linux), then fallback to reporting the path
        try:
            subprocess.Popen(["xdg-open", folder],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            self._set_status(f"Opened folder: {folder}", kind="ok")
        except FileNotFoundError:
            # xdg-open not available — just display the path
            self._set_status(
                f"Output folder: {folder}  (xdg-open not found — open manually)",
                kind="info")
        except Exception as exc:
            self._set_status(f"Could not open folder: {exc}", kind="warn")
