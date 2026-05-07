"""
helpers / qwen_tts_backend.py
────────────────────────────────────────────────────────────────────────────
Local Qwen TTS backend adapter for Guichi shell — pagepack_chillama.

Lives in helpers/ so it follows the same import pattern as ollama_client.py
and avoids circular import when Guichi loads page_qwen_tts/qwen_tts_page.py
directly via spec_from_file_location.

Calls qwen_tts_infer.py (a small batch script in helpers/) via subprocess
using the qwen3tts-venv Python interpreter.
Does NOT use qwen-tts-demo (that launches a Gradio server, not batch mode).
Qwen TTS is a subprocess call — there is no persistent server to start.

ADJUSTABLE CONFIG — edit the constants below to match your environment:
    VENV_PYTHON    Python interpreter inside your qwen3tts-venv
    SCRIPT_PATH    Batch inference script (helpers/qwen_tts_infer.py)
    DEFAULT_MODEL  HuggingFace repo ID of the model to load
    RUNTIME_FLAGS  Device / dtype / flash-attn flags

Return contract for generate():
    {"ok": True,  "path": "/abs/path/to/output.wav"}
    {"ok": False, "error": "human-readable reason"}
"""

import os
import re
import subprocess
import tempfile
import shutil
from pathlib import Path

# ── Adjustable config ─────────────────────────────────────────────────────────
# Edit these to match your local install.
# You can also override them at runtime via QwenBackend.configure().

# Python interpreter inside the qwen3tts-venv
VENV_PYTHON  = "/home/min/qwen3tts-venv/bin/python"

# Batch inference script shipped alongside this file
SCRIPT_PATH  = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "qwen_tts_infer.py")

# Default model — fast 0.6B CustomVoice variant; change to 1.7B for better quality
DEFAULT_MODEL = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"

# Runtime flags — safe CPU defaults; change --device to cuda if you have a GPU
RUNTIME_FLAGS = [
    "--device",       "cpu",
    "--dtype",        "float32",
    "--no-flash-attn",
]

# Timeout in seconds for the subprocess call
GENERATION_TIMEOUT = 600   # 10 min — CPU is slow, be generous

# ── Output directory ─────────────────────────────────────────────────────────
# Page-owned output folder.  Created on first use.
OUTPUT_DIR = os.path.expanduser("~/qwen_tts_output")

# ── Safe filename helper ──────────────────────────────────────────────────────
_UNSAFE = re.compile(r"[^\w\-.]")

def _safe_stem(text: str, maxlen: int = 40) -> str:
    """Turn text into a safe filename stem."""
    stem = text.strip().replace(" ", "_")
    stem = _UNSAFE.sub("", stem)
    return stem[:maxlen] if stem else "tts"


class QwenBackend:
    """
    Thin adapter between the UI and the local qwen-tts-demo CLI.

    Usage:
        backend = QwenBackend()
        result  = backend.generate(text, model_id, voice_id)
        # result == {"ok": True,  "path": "/home/.../qwen_tts_output/...wav"}
        # result == {"ok": False, "error": "reason"}
    """

    def __init__(self):
        self.venv_python   = VENV_PYTHON
        self.script_path   = SCRIPT_PATH
        self.runtime_flags = list(RUNTIME_FLAGS)
        self.output_dir    = OUTPUT_DIR

    # ── Public API ────────────────────────────────────────────────────────────

    def configure(self, venv_python=None, script_path=None, output_dir=None):
        """Override paths at runtime (e.g. from a Settings tab)."""
        if venv_python:
            self.venv_python = os.path.expanduser(venv_python)
        if script_path:
            self.script_path = os.path.expanduser(script_path)
        if output_dir:
            self.output_dir = os.path.expanduser(output_dir)

    def check_runtime(self) -> dict:
        """
        Quick sanity check before attempting generation.
        Returns {"ok": True} or {"ok": False, "missing": [...], "hint": str}.
        """
        missing = []
        if not os.path.isfile(self.venv_python):
            missing.append(f"Python not found: {self.venv_python}")
        if not os.path.isfile(self.script_path):
            missing.append(f"Inference script not found: {self.script_path}")
        if missing:
            hint = (
                "Edit VENV_PYTHON and SCRIPT_PATH in\n"
                "  pagepack_chillama/helpers/qwen_tts_backend.py\n"
                "Note: Qwen TTS is a subprocess — no server needs to be started."
            )
            return {"ok": False, "missing": missing, "hint": hint}
        return {"ok": True}

    def generate(self, text: str, model_id: str, voice_id: str,
                 language: str = None, title: str = "",
                 instruct: str = "") -> dict:
        """
        Run Qwen TTS and save output into the page-owned output folder.

        Parameters
        ----------
        text     : text to synthesise
        model_id : e.g. "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
        voice_id : speaker ID (see CUSTOM_VOICES in qwen_tts_page.py)
        language : language hint ("auto" or a language name, e.g. "english").
                   None / "auto" → model auto-detects.
        title    : short label used as the filename slug; if empty, first 40
                   chars of text are used instead.
        instruct : optional style/tone instruction; silently ignored on 0.6B.

        Returns
        -------
        {"ok": True,  "path": "/abs/path/output.wav"}
        {"ok": False, "error": "reason"}
        """
        # 1. Guard: runtime present?
        rt = self.check_runtime()
        if not rt["ok"]:
            lines = rt["missing"] + [rt["hint"]]
            return {"ok": False, "error": "\n".join(lines)}

        # 2. Guard: non-empty text
        text = text.strip()
        if not text:
            return {"ok": False, "error": "Text is empty."}

        # 3. Ensure output directory exists
        try:
            os.makedirs(self.output_dir, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "error": f"Cannot create output dir: {exc}"}

        # 4. Build output filename — use title slug if provided, else text stem
        from datetime import datetime
        stamp     = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem      = _safe_stem(title) if title.strip() else _safe_stem(text)
        model_tag = model_id.split("/")[-1].replace("-", "_")[:20]
        fname     = f"{stamp}_{model_tag}_{stem}.wav"
        out_path  = os.path.join(self.output_dir, fname)

        # 5. Write text to a temp file to avoid shell-quoting issues
        try:
            tmp_fd, tmp_txt = tempfile.mkstemp(suffix=".txt", prefix="qwen_tts_")
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as exc:
            return {"ok": False, "error": f"Cannot write temp file: {exc}"}

        # 6. Build command
        cmd = self._build_cmd(model_id, voice_id, tmp_txt, out_path,
                              language=language, instruct=instruct)

        # 7. Run
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=GENERATION_TIMEOUT,
            )
        except FileNotFoundError:
            return {"ok": False,
                    "error": f"Executable not found: {self.venv_python}"}
        except subprocess.TimeoutExpired:
            return {"ok": False,
                    "error": f"Generation timed out after {GENERATION_TIMEOUT}s."}
        except Exception as exc:
            return {"ok": False, "error": f"Subprocess error: {exc}"}
        finally:
            try:
                os.unlink(tmp_txt)
            except OSError:
                pass

        # 8. Check result
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            stdout = (proc.stdout or "").strip()
            detail = stderr or stdout or "(no output)"
            return {"ok": False,
                    "error": f"Exit {proc.returncode}:\n{detail[:800]}"}

        if not os.path.isfile(out_path):
            # Some scripts write to a different path — try to find a .wav nearby
            found = self._scan_for_output(out_path)
            if found:
                return {"ok": True, "path": found}
            return {"ok": False,
                    "error": (
                        f"Script exited OK but output file not found:\n"
                        f"  expected: {out_path}\n"
                        f"  stdout: {(proc.stdout or '').strip()[:400]}"
                    )}

        return {"ok": True, "path": out_path}

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_cmd(self, model_id, voice_id, text_file, out_path,
                   language=None, instruct=""):
        """
        Build the subprocess command list for qwen_tts_infer.py.

        Flag reference (must match qwen_tts_infer.py argparse):
            --model      HF repo ID or local path
            --text-file  path to temp UTF-8 text file
            --speaker    speaker ID for CustomVoice models
            --output     destination .wav path
            --language   language hint (omitted for "auto"/None)
            --instruct   optional style instruction (omitted if empty)
            + RUNTIME_FLAGS (--device, --dtype, --no-flash-attn)
        """
        cmd = [
            self.venv_python,
            self.script_path,
            "--model",     model_id,
            "--text-file", text_file,
            "--speaker",   voice_id,
            "--output",    out_path,
        ] + self.runtime_flags
        if language and language.strip().lower() not in ("auto", ""):
            cmd += ["--language", language.strip().lower()]
        if instruct and instruct.strip():
            cmd += ["--instruct", instruct.strip()]
        return cmd

    @staticmethod
    def _scan_for_output(expected_path):
        """
        If the script wrote to a slightly different path, try to find it.
        Looks in the same directory for the most recently created .wav file.
        """
        out_dir = os.path.dirname(expected_path)
        try:
            candidates = [
                os.path.join(out_dir, f)
                for f in os.listdir(out_dir)
                if f.endswith(".wav")
            ]
            if candidates:
                return max(candidates, key=os.path.getmtime)
        except OSError:
            pass
        return None
