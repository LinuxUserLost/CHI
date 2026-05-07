"""
Theme-friendly Qwen TTS page for Guichi.

This page keeps the original Qwen TTS behavior and backend contract, but
rebuilds the GUI structure around the newer themed-page standard.
"""

from __future__ import annotations

import os
import sys
import time
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog

from gui_files import interaction_support

_THIS_FILE = os.path.abspath(__file__)
_PAGE_DIR = os.path.dirname(_THIS_FILE)
_PACK_DIR = os.path.dirname(_PAGE_DIR)
if _PACK_DIR not in sys.path:
    sys.path.insert(0, _PACK_DIR)

from helpers.qwen_tts_backend import QwenBackend, _safe_stem


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

LANGUAGES = [
    "auto",
    "english", "chinese", "japanese", "korean",
    "french", "german", "spanish", "italian",
    "portuguese", "russian",
]

DEFAULT_LANGUAGE = "auto"

MODELS = [
    "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
    "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
]

DEFAULT_MODEL = MODELS[0]

_DEFAULT_PAGE_THEME = {
    "app_bg": "#1e1e1e",
    "content_bg": "#1e1e1e",
    "panel_bg": "#2e2e2e",
    "sidebar_bg": "#252525",
    "text_main": "#d0d0d0",
    "text_muted": "#909090",
    "text_active": "#f0f0f0",
    "text_on_accent": "#ffffff",
    "button_bg": "#333333",
    "button_hover": "#444444",
    "button_active": "#ffffff",
    "button_disabled": "#666666",
    "accent": "#4ea0ff",
    "border": "#4a4a4a",
    "divider": "#3a3a3a",
}

_STATUS_COLORS = {
    "ok": "#5cc37a",
    "warn": "#f0b35b",
    "error": "#e06b6b",
}


class TTSQwenPage:
    PAGE_NAME = "TTS Qwen"

    def __init__(self, parent, app=None, page_key="", page_folder="", *args, **kwargs):
        app = kwargs.pop("controller", app)
        page_key = kwargs.pop("page_context", page_key)
        page_folder = kwargs.pop("page_folder", page_folder)

        self.parent = parent
        self.app = app
        self.page_key = page_key
        self.page_folder = page_folder
        self.guichi_page_theme = None
        self._theme_tokens = dict(_DEFAULT_PAGE_THEME)
        self._style_prefix = f"TTSQwen.{id(self)}"
        self._style = None

        self._backend = QwenBackend()
        self._generating = False
        self._last_output_path = ""
        self._gen_start_time = None
        self._gen_timer_after_id = None
        self._gen_words = 0
        self._gen_chars = 0

        self._model_var = tk.StringVar(value=DEFAULT_MODEL)
        self._voice_var = tk.StringVar(value=DEFAULT_VOICE)
        self._lang_var = tk.StringVar(value=DEFAULT_LANGUAGE)
        self._instruct_var = tk.StringVar(value="")
        self._title_var = tk.StringVar(value="")
        self._char_count_var = tk.StringVar(value="0 chars")
        self._summary_var = tk.StringVar(value="Paste or upload text to begin.")
        self._gen_current_var = tk.StringVar(value="Current: —")
        self._gen_last_var = tk.StringVar(value="Last: —")
        self._output_path_var = tk.StringVar(value="No audio generated yet.")

        self._placeholder_active = True
        self._placeholder_text = "Paste or type text here, or upload a .txt / .md file…"
        self._status_placeholder_active = True
        self._status_help_text = (
            "Qwen TTS is ready for input.\n"
            "1. Paste or upload text.\n"
            "2. Adjust voice, language, and optional title.\n"
            "3. Generate audio and open the output folder if needed."
        )

        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)

        self._build_header()
        self._build_workspace()
        self._build_footer()
        self._apply_theme()
        self.frame.after(400, self._check_runtime_status)

    def _embed_into_parent(self, parent=None):
        container = parent or self.parent
        try:
            if container is not None and self.frame.master is not container:
                self.frame.destroy()
                self.parent = container
                self.frame = ttk.Frame(container)
                self.frame.columnconfigure(0, weight=1)
                self.frame.rowconfigure(1, weight=1)
                self._build_header()
                self._build_workspace()
                self._build_footer()
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

    def set_guichi_page_theme(self, context):
        self.guichi_page_theme = context
        tokens = dict(_DEFAULT_PAGE_THEME)
        tokens.update((context or {}).get("tokens") or {})
        self._theme_tokens = tokens
        self._apply_theme()

    def _build_header(self):
        self._header = ttk.LabelFrame(self.frame, text="Session Setup", padding=(8, 6))
        self._header.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        for col in (1, 3, 5, 7):
            self._header.columnconfigure(col, weight=1)

        self._rt_dot = tk.Label(self._header, text="●", font=("", 13))
        self._rt_dot.grid(row=0, column=0, padx=(0, 4), sticky="w")
        self._rt_label = ttk.Label(self._header, text="Checking runtime…")
        self._rt_label.grid(row=0, column=1, padx=(0, 16), sticky="w")

        ttk.Label(self._header, text="Model:").grid(row=0, column=2, padx=(0, 4), sticky="e")
        self._model_combo = ttk.Combobox(
            self._header,
            textvariable=self._model_var,
            values=MODELS,
            state="readonly",
            width=30,
        )
        self._model_combo.grid(row=0, column=3, padx=(0, 12), sticky="ew")

        ttk.Label(self._header, text="Voice:").grid(row=0, column=4, padx=(0, 4), sticky="e")
        self._voice_combo = ttk.Combobox(
            self._header,
            textvariable=self._voice_var,
            values=CUSTOM_VOICES,
            width=18,
        )
        self._voice_combo.grid(row=0, column=5, padx=(0, 12), sticky="ew")

        ttk.Label(self._header, text="Lang:").grid(row=0, column=6, padx=(0, 4), sticky="e")
        self._lang_combo = ttk.Combobox(
            self._header,
            textvariable=self._lang_var,
            values=LANGUAGES,
            state="readonly",
            width=12,
        )
        self._lang_combo.grid(row=0, column=7, padx=(0, 12), sticky="ew")

        self._recheck_btn = ttk.Button(self._header, text="↻ Re-check", width=10, command=self._check_runtime_status)
        self._recheck_btn.grid(row=0, column=8, sticky="e")

        ttk.Label(self._header, text="Instruct:").grid(row=1, column=0, columnspan=1, padx=(0, 4), pady=(8, 0), sticky="w")
        self._instruct_entry = ttk.Entry(self._header, textvariable=self._instruct_var)
        self._instruct_entry.grid(row=1, column=1, columnspan=7, pady=(8, 0), sticky="ew")
        self._instruct_hint = ttk.Label(
            self._header,
            text="optional · style/tone hint · silently ignored on 0.6B",
        )
        self._instruct_hint.grid(row=1, column=8, padx=(8, 0), pady=(8, 0), sticky="e")

    def _build_workspace(self):
        self._workspace = ttk.Frame(self.frame)
        self._workspace.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        self._workspace.columnconfigure(0, weight=5)
        self._workspace.columnconfigure(1, weight=3)
        self._workspace.rowconfigure(0, weight=1)

        self._editor_panel = ttk.LabelFrame(self._workspace, text="Text Input", padding=(8, 6))
        self._editor_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self._editor_panel.columnconfigure(0, weight=1)
        self._editor_panel.rowconfigure(1, weight=1)

        self._toolbar = ttk.Frame(self._editor_panel)
        self._toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self._toolbar.columnconfigure(99, weight=1)

        ttk.Button(self._toolbar, text="📄 Upload .txt", width=14, command=self._upload_txt).grid(row=0, column=0, padx=(0, 4))
        ttk.Button(self._toolbar, text="📝 Upload .md", width=14, command=self._upload_md).grid(row=0, column=1, padx=(0, 4))
        ttk.Button(self._toolbar, text="Clear Text", width=10, command=self._clear_text).grid(row=0, column=2, padx=(0, 8))

        ttk.Label(self._toolbar, text="Title:").grid(row=0, column=3, padx=(0, 4))
        self._title_entry = ttk.Entry(self._toolbar, textvariable=self._title_var, width=22)
        self._title_entry.grid(row=0, column=4, padx=(0, 4))
        ttk.Button(self._toolbar, text="💾 Save Input", width=12, command=self._save_input).grid(row=0, column=5, padx=(0, 8))

        self._char_label = ttk.Label(self._toolbar, textvariable=self._char_count_var)
        self._char_label.grid(row=0, column=100, sticky="e")

        self._text_outer = ttk.Frame(self._editor_panel)
        self._text_outer.grid(row=1, column=0, sticky="nsew")
        self._text_outer.columnconfigure(0, weight=1)
        self._text_outer.rowconfigure(0, weight=1)

        self._text_input = tk.Text(
            self._text_outer,
            wrap="word",
            undo=True,
            font=("", 11),
            relief="flat",
            borderwidth=1,
            padx=10,
            pady=8,
            insertwidth=2,
            spacing3=2,
        )
        self._text_scroll = ttk.Scrollbar(self._text_outer, orient="vertical", command=self._text_input.yview)
        self._text_input.configure(yscrollcommand=self._text_scroll.set)
        self._text_input.grid(row=0, column=0, sticky="nsew")
        self._text_scroll.grid(row=0, column=1, sticky="ns")
        interaction_support.setup_text_widget(self._text_input)
        self._text_input.insert("1.0", self._placeholder_text)
        self._text_input.bind("<FocusIn>", self._on_text_focus_in)
        self._text_input.bind("<FocusOut>", self._on_text_focus_out)
        self._text_input.bind("<<Modified>>", self._on_text_modified)

        self._side_panel = ttk.Frame(self._workspace)
        self._side_panel.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        self._side_panel.columnconfigure(0, weight=1)
        self._side_panel.rowconfigure(1, weight=1)
        self._side_panel.rowconfigure(2, weight=1)

        self._action_panel = ttk.LabelFrame(self._side_panel, text="Generate", padding=(8, 8))
        self._action_panel.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self._action_panel.columnconfigure(0, weight=1)

        self._gen_btn = ttk.Button(self._action_panel, text="▶ Generate Audio", command=self._on_generate)
        self._gen_btn.grid(row=0, column=0, sticky="ew")
        self._summary_label = ttk.Label(self._action_panel, textvariable=self._summary_var, wraplength=280, justify="left")
        self._summary_label.grid(row=1, column=0, sticky="ew", pady=(8, 2))
        self._gen_current_label = ttk.Label(self._action_panel, textvariable=self._gen_current_var)
        self._gen_current_label.grid(row=2, column=0, sticky="w", pady=(4, 0))
        self._gen_last_label = ttk.Label(self._action_panel, textvariable=self._gen_last_var)
        self._gen_last_label.grid(row=3, column=0, sticky="w", pady=(2, 0))

        self._status_panel = ttk.LabelFrame(self._side_panel, text="Status", padding=(8, 6))
        self._status_panel.grid(row=1, column=0, sticky="nsew", pady=4)
        self._status_panel.columnconfigure(0, weight=1)
        self._status_panel.rowconfigure(0, weight=1)

        self._status_text = tk.Text(
            self._status_panel,
            height=8,
            wrap="word",
            state="disabled",
            font=("Monospace", 9),
            relief="flat",
            borderwidth=1,
            padx=8,
            pady=6,
        )
        self._status_text.grid(row=0, column=0, sticky="nsew")
        interaction_support.setup_text_widget(self._status_text)

        self._output_panel = ttk.LabelFrame(self._side_panel, text="Output", padding=(8, 6))
        self._output_panel.grid(row=2, column=0, sticky="nsew", pady=(4, 0))
        self._output_panel.columnconfigure(0, weight=1)

        self._output_entry = ttk.Entry(
            self._output_panel,
            textvariable=self._output_path_var,
            state="readonly",
            font=("Monospace", 9),
        )
        self._output_entry.grid(row=0, column=0, sticky="ew")
        self._open_folder_btn = ttk.Button(self._output_panel, text="📂 Open Folder", command=self._open_output_folder)
        self._open_folder_btn.grid(row=1, column=0, sticky="w", pady=(8, 0))

        self._write_status_help()

    def _build_footer(self):
        self._footer = ttk.Frame(self.frame, padding=(8, 4))
        self._footer.grid(row=2, column=0, sticky="ew")
        self._footer.columnconfigure(0, weight=1)
        self._footer_note = ttk.Label(
            self._footer,
            text="Local subprocess workflow using the configured Qwen TTS backend. No persistent server required.",
        )
        self._footer_note.grid(row=0, column=0, sticky="w")

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
        if self._placeholder_active:
            return ""
        return self._text_input.get("1.0", "end-1c").strip()

    def _set_text(self, content: str):
        self._text_input.configure(fg=self._theme_tokens["text_main"])
        self._text_input.delete("1.0", "end")
        self._text_input.insert("1.0", content)
        self._placeholder_active = False
        self._char_count_var.set(f"{len(content):,} chars")

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
        text = self._get_text()
        if not text:
            self._set_status("Nothing to save — text area is empty.", kind="warn")
            return
        from datetime import datetime
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        title = self._title_var.get().strip()
        slug = _safe_stem(title) if title else _safe_stem(text)
        path = filedialog.asksaveasfilename(
            title="Save input text",
            initialfile=f"{stamp}_{slug}.txt",
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
        path = filedialog.askopenfilename(title="Choose a text file", filetypes=filetypes)
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
            self._set_text(content)
            self._set_status(f"Loaded: {os.path.basename(path)}  ({len(content):,} chars)", kind="ok")
        except Exception as exc:
            self._set_status(f"Read error: {exc}", kind="error")

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

    def _set_status(self, msg: str, kind: str = "info"):
        self._clear_status_placeholder()
        self._status_text.configure(state="normal")
        lines = int(self._status_text.index("end-1c").split(".")[0])
        if lines > 30:
            self._status_text.delete("1.0", f"{lines - 28}.0")
        tag = kind if kind in ("ok", "warn", "error") else "info"
        self._status_text.insert("end", msg + "\n", tag)
        self._status_text.configure(state="disabled")
        self._status_text.see("end")

    @staticmethod
    def _format_elapsed(seconds):
        seconds = int(seconds)
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _start_generation_timer(self, words, chars):
        self._gen_start_time = time.monotonic()
        self._gen_words = words
        self._gen_chars = chars
        if self._gen_timer_after_id is not None:
            try:
                self.frame.after_cancel(self._gen_timer_after_id)
            except Exception:
                pass
            self._gen_timer_after_id = None
        self._gen_current_var.set(f"Current: 00:00 running  ·  {words:,} words · {chars:,} chars")
        self._tick_generation_timer()

    def _tick_generation_timer(self):
        if not self._generating or self._gen_start_time is None:
            self._gen_timer_after_id = None
            return
        elapsed = time.monotonic() - self._gen_start_time
        self._gen_current_var.set(
            f"Current: {self._format_elapsed(elapsed)} running  ·  {self._gen_words:,} words · {self._gen_chars:,} chars"
        )
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
            result_str = "✓ ok" if ok else "✗ failed"
            self._gen_current_var.set(
                f"Current: {elapsed_str} done  ·  {self._gen_words:,} words · {self._gen_chars:,} chars"
            )
            self._gen_last_var.set(
                f"Last: {elapsed_str}  ·  {self._gen_words:,} words · {self._gen_chars:,} chars  ·  {result_str}"
            )
            self._gen_start_time = None

    def _check_runtime_status(self):
        b = self._backend
        self._write_status_help()
        self._set_status("─── Qwen TTS runtime check ───────────────────", kind="info")
        self._set_status("ℹ  Qwen TTS runs as a local subprocess — no server to start.", kind="info")
        self._set_status(f"   python  : {b.venv_python}", kind="info")
        self._set_status(f"   script  : {b.script_path}", kind="info")
        self._set_status(f"   output  : {b.output_dir}", kind="info")

        rt = b.check_runtime()
        if rt["ok"]:
            self._rt_dot.configure(fg=_STATUS_COLORS["ok"])
            self._rt_label.configure(text="Runtime OK")
            self._set_status("✓  Both paths found — ready to generate.", kind="ok")
        else:
            self._rt_dot.configure(fg=_STATUS_COLORS["warn"])
            self._rt_label.configure(text="Runtime not found")
            self._set_status("", kind="info")
            self._set_status("✘  Missing paths:", kind="error")
            for item in rt.get("missing", []):
                self._set_status(f"     {item}", kind="error")
            self._set_status("", kind="info")
            self._set_status("▶  To fix: edit VENV_PYTHON and SCRIPT_PATH at the top of", kind="warn")
            self._set_status("     chi_reader/helpers/qwen_tts_backend.py", kind="warn")
            self._set_status("   Then restart Guichi (or use Re-check below).", kind="warn")

    def _on_generate(self):
        if self._generating:
            self._set_status("Generation already in progress…", kind="warn")
            return

        text = self._get_text()
        if not text:
            self._set_status("No text to synthesise — paste text or upload a file.", kind="warn")
            return

        model = self._model_var.get().strip()
        voice = self._voice_var.get().strip() or DEFAULT_VOICE
        lang = self._lang_var.get().strip() or DEFAULT_LANGUAGE
        title = self._title_var.get().strip()
        instruct = self._instruct_var.get().strip()

        words = len(text.split())
        chars = len(text)
        self._summary_var.set(f"{words:,} words · {chars:,} chars")
        self._set_status(
            f"Generating…  model={model.split('/')[-1]}  voice={voice}  lang={lang}",
            kind="info",
        )
        self._set_status("CPU mode — this may take a while. The UI will remain responsive.", kind="info")

        self._generating = True
        self._gen_btn.configure(state="disabled", text="⏳ Generating…")
        self._output_path_var.set("(generating…)")
        self._start_generation_timer(words, chars)

        def _bg():
            try:
                result = self._backend.generate(
                    text,
                    model,
                    voice,
                    language=lang,
                    title=title,
                    instruct=instruct,
                )
            except Exception as exc:
                result = {"ok": False, "error": f"Worker exception during Qwen TTS generation: {exc}"}
            try:
                self.frame.after(0, lambda: self._on_generate_done(result))
            except Exception:
                pass

        threading.Thread(target=_bg, daemon=True).start()

    def _on_generate_done(self, result: dict):
        self._generating = False
        self._finish_generation_timer(result.get("ok", False))
        self._gen_btn.configure(state="normal", text="▶ Generate Audio")
        if result["ok"]:
            path = result["path"]
            self._last_output_path = path
            self._output_path_var.set(path)
            self._set_status(f"✓ Done: {os.path.basename(path)}", kind="ok")
            self._set_status(f"  Saved to: {path}", kind="ok")
        else:
            self._output_path_var.set("(failed)")
            self._set_status("✘ Generation failed:", kind="error")
            for line in result.get("error", "unknown error").splitlines():
                self._set_status(f"  {line}", kind="error")

    def _open_output_folder(self):
        folder = self._backend.output_dir
        if not os.path.isdir(folder):
            try:
                os.makedirs(folder, exist_ok=True)
                self._set_status(f"Created output folder: {folder}", kind="ok")
            except OSError as exc:
                self._set_status(f"Cannot create output folder: {exc}", kind="error")
                return
        try:
            subprocess.Popen(["xdg-open", folder], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._set_status(f"Opened folder: {folder}", kind="ok")
        except FileNotFoundError:
            self._set_status(f"Output folder: {folder}  (xdg-open not found — open manually)", kind="info")
        except Exception as exc:
            self._set_status(f"Could not open folder: {exc}", kind="warn")

    def _apply_theme(self):
        tokens = self._theme_tokens
        try:
            self._style = ttk.Style(self.frame)
            self._style.configure(f"{self._style_prefix}.TFrame", background=tokens["content_bg"])
            self._style.configure(f"{self._style_prefix}.Panel.TFrame", background=tokens["panel_bg"])
            self._style.configure(
                f"{self._style_prefix}.TLabelframe",
                background=tokens["panel_bg"],
                bordercolor=tokens["border"],
            )
            self._style.configure(
                f"{self._style_prefix}.TLabelframe.Label",
                background=tokens["panel_bg"],
                foreground=tokens["text_main"],
            )
            self._style.configure(f"{self._style_prefix}.TLabel", background=tokens["content_bg"], foreground=tokens["text_main"])
            self._style.configure(f"{self._style_prefix}.Panel.TLabel", background=tokens["panel_bg"], foreground=tokens["text_main"])
            self._style.configure(f"{self._style_prefix}.Muted.TLabel", background=tokens["content_bg"], foreground=tokens["text_muted"])
            self._style.configure(f"{self._style_prefix}.PanelMuted.TLabel", background=tokens["panel_bg"], foreground=tokens["text_muted"])
            self._style.configure(f"{self._style_prefix}.Accent.TLabel", background=tokens["content_bg"], foreground=tokens["accent"])
            self._style.configure(
                f"{self._style_prefix}.TButton",
                background=tokens["button_bg"],
                foreground=tokens["text_main"],
            )
            self._style.map(
                f"{self._style_prefix}.TButton",
                background=[("active", tokens["button_hover"]), ("pressed", tokens["accent"])],
                foreground=[("pressed", tokens["text_on_accent"]), ("disabled", tokens["button_disabled"])],
            )
            self._style.configure(
                f"{self._style_prefix}.Primary.TButton",
                background=tokens["accent"],
                foreground=tokens["text_on_accent"],
            )
            self._style.map(
                f"{self._style_prefix}.Primary.TButton",
                background=[("active", tokens["button_hover"]), ("pressed", tokens["accent"])],
                foreground=[("active", tokens["text_on_accent"]), ("pressed", tokens["text_on_accent"])],
            )
            self._style.configure(
                f"{self._style_prefix}.TEntry",
                fieldbackground=tokens["panel_bg"],
                foreground=tokens["text_main"],
            )
            self._style.configure(
                f"{self._style_prefix}.TCombobox",
                fieldbackground=tokens["panel_bg"],
                foreground=tokens["text_main"],
                background=tokens["button_bg"],
                arrowcolor=tokens["text_main"],
            )
            self._style.map(
                f"{self._style_prefix}.TCombobox",
                fieldbackground=[("readonly", tokens["panel_bg"])],
                selectbackground=[("readonly", tokens["accent"])],
                selectforeground=[("readonly", tokens["text_on_accent"])],
            )
        except Exception:
            pass

        try:
            self.frame.configure(style=f"{self._style_prefix}.TFrame")
        except Exception:
            pass
        self._apply_ttk_theme_tree(self.frame)

        border = tokens["border"]
        panel_bg = tokens["panel_bg"]
        text_main = tokens["text_main"]
        text_muted = tokens["text_muted"]
        accent = tokens["accent"]
        text_on_accent = tokens["text_on_accent"]

        try:
            self.frame.configure(background=tokens["app_bg"])
        except Exception:
            pass

        for widget in (self._header,):
            try:
                widget.configure(style=f"{self._style_prefix}.TLabelframe")
            except Exception:
                pass

        for frame in (self._header, self._workspace, self._toolbar, self._side_panel, self._footer):
            try:
                frame.configure(style=f"{self._style_prefix}.TFrame")
            except Exception:
                pass

        for widget in (
            self._settings_strip_labels() +
            [self._summary_label, self._gen_current_label, self._gen_last_label, self._footer_note]
        ):
            try:
                widget.configure(style=f"{self._style_prefix}.Muted.TLabel" if widget in (self._instruct_hint, self._char_label, self._gen_last_label, self._footer_note) else f"{self._style_prefix}.TLabel")
            except Exception:
                pass

        for text_widget in (self._text_input, self._status_text):
            try:
                text_widget.configure(
                    background=panel_bg,
                    foreground=text_main,
                    insertbackground=text_main,
                    selectbackground=accent,
                    selectforeground=text_on_accent,
                    highlightbackground=border,
                    highlightcolor=accent,
                )
            except Exception:
                pass

        try:
            self._text_input.configure(
                foreground=text_main if not self._placeholder_active else text_muted,
            )
        except Exception:
            pass

        try:
            self._status_text.tag_configure("ok", foreground=_STATUS_COLORS["ok"])
            self._status_text.tag_configure("warn", foreground=_STATUS_COLORS["warn"])
            self._status_text.tag_configure("error", foreground=_STATUS_COLORS["error"])
            self._status_text.tag_configure("info", foreground=text_main)
            self._status_text.tag_configure("help", foreground=text_muted)
        except Exception:
            pass

        try:
            self._rt_label.configure(style=f"{self._style_prefix}.Muted.TLabel")
        except Exception:
            pass
        try:
            self._rt_dot.configure(bg=panel_bg)
        except Exception:
            pass

        try:
            self._gen_btn.configure(style=f"{self._style_prefix}.Primary.TButton")
        except Exception:
            pass

    def _settings_strip_labels(self):
        return [
            self._rt_label,
            self._instruct_hint,
            self._char_label,
            self._summary_label,
            self._gen_current_label,
            self._gen_last_label,
            self._footer_note,
        ]

    def _apply_ttk_theme_tree(self, widget):
        for child in widget.winfo_children():
            try:
                if isinstance(child, ttk.LabelFrame):
                    child.configure(style=f"{self._style_prefix}.TLabelframe")
                elif isinstance(child, ttk.Combobox):
                    child.configure(style=f"{self._style_prefix}.TCombobox")
                elif isinstance(child, ttk.Entry):
                    child.configure(style=f"{self._style_prefix}.TEntry")
                elif isinstance(child, ttk.Button):
                    child.configure(style=f"{self._style_prefix}.TButton")
                elif isinstance(child, ttk.Label):
                    current = str(child.cget("text"))
                    if child in (self._instruct_hint, self._char_label, self._gen_last_label, self._footer_note):
                        child.configure(style=f"{self._style_prefix}.Muted.TLabel")
                    else:
                        child.configure(style=f"{self._style_prefix}.TLabel")
                elif isinstance(child, ttk.Frame):
                    child.configure(style=f"{self._style_prefix}.TFrame")
            except Exception:
                pass
            self._apply_ttk_theme_tree(child)
