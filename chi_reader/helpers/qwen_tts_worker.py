#!/usr/bin/env python3
"""
helpers/qwen_tts_worker.py — persistent Qwen TTS worker process.

Loads the model once at startup, then accepts JSON-line commands on stdin
and writes JSON-line responses to stdout.  Designed to be launched by
qwen_tts_backend.py (Stage 2+) but can also be tested manually.

Usage:
    /home/min/qwen3tts-venv/bin/python qwen_tts_worker.py \
        --model  Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice \
        --device cpu \
        --dtype  float32 \
        --no-flash-attn

Protocol (all messages are single UTF-8 JSON lines, newline-terminated):

  Startup (worker → caller, after model loaded):
    {"status": "ready", "model": "<model_id>"}

  Startup failure (worker → caller):
    {"status": "error", "error": "<message>"}
    (then exits nonzero)

  ping:
    in:  {"cmd": "ping"}
    out: {"status": "ready"}

  generate:
    in:  {"cmd": "generate", "text_file": "/tmp/...", "speaker": "ryan",
          "language": null, "instruct": "", "output": "/path/out.wav"}
    out: {"ok": true,  "path": "/path/out.wav"}
         {"ok": false, "error": "<message>"}

  shutdown:
    in:  {"cmd": "shutdown"}
    out: {"status": "shutting_down"}
    (then exits 0)

Normal progress/debug output goes to stderr only — stdout is reserved for
JSON protocol lines.

Exit 0 on clean shutdown, 1 on model-load failure.
"""

import argparse
import json
import os
import sys


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _emit(obj: dict) -> None:
    """Write a JSON line to stdout and flush immediately."""
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def _log(msg: str) -> None:
    """Write a debug/progress line to stderr."""
    print(msg, file=sys.stderr, flush=True)


def _dtype_for(name: str):
    import torch
    return {
        "float32": torch.float32, "fp32":    torch.float32,
        "float16": torch.float16, "fp16":    torch.float16,
        "bfloat16": torch.bfloat16, "bf16": torch.bfloat16,
    }[name]


# ─────────────────────────────────────────────────────────────────────────────
# Argparse
# ─────────────────────────────────────────────────────────────────────────────

def _build_parser():
    p = argparse.ArgumentParser(
        description="Persistent Qwen3 TTS worker — JSON-line protocol on stdin/stdout")
    p.add_argument("--model", required=True,
                   help="HuggingFace repo ID or local path to a Qwen3-TTS model")
    p.add_argument("--device", default="cpu",
                   help="Torch device: cpu | cuda | cuda:0 (default: cpu)")
    p.add_argument("--dtype", default="float32",
                   choices=["float32", "fp32", "float16", "fp16", "bfloat16", "bf16"],
                   help="Torch dtype (default: float32)")
    p.add_argument("--no-flash-attn", action="store_true", dest="no_flash_attn",
                   help="Disable FlashAttention-2 (safe for CPU / unpatched envs)")
    return p


# ─────────────────────────────────────────────────────────────────────────────
# Model loading
# ─────────────────────────────────────────────────────────────────────────────

def _load_model(model_id: str, device: str, dtype_name: str):
    """Load and return (tts, sample_rate_placeholder) or raise on failure."""
    try:
        from qwen_tts import Qwen3TTSModel
    except ImportError as exc:
        raise RuntimeError(
            f"Cannot import qwen_tts — is the correct venv active?\n  {exc}"
        ) from exc

    torch_dtype = _dtype_for(dtype_name)
    _log(f"[worker] Loading model: {model_id}  device={device}  dtype={dtype_name}")

    tts = Qwen3TTSModel.from_pretrained(
        model_id,
        device_map=device,
        torch_dtype=torch_dtype,
    )

    # Log supported speakers to stderr for manual testing convenience.
    try:
        spks = tts.model.get_supported_speakers()
        _log(f"[worker] Supported speakers: {spks}")
    except Exception:
        pass

    _log("[worker] Model loaded — entering command loop.")
    return tts


# ─────────────────────────────────────────────────────────────────────────────
# Request handlers
# ─────────────────────────────────────────────────────────────────────────────

def _handle_generate(tts, req: dict) -> dict:
    text_file = req.get("text_file", "")
    speaker   = req.get("speaker",   "default")
    language  = req.get("language")   or None
    instruct  = req.get("instruct",   "") or None
    out_path  = req.get("output",     "")

    # Validate inputs
    if not text_file:
        return {"ok": False, "error": "generate: 'text_file' is required."}
    if not out_path:
        return {"ok": False, "error": "generate: 'output' is required."}

    # Read text
    try:
        with open(text_file, "r", encoding="utf-8") as fh:
            text = fh.read().strip()
    except OSError as exc:
        return {"ok": False, "error": f"Cannot read text_file: {exc}"}

    if not text:
        return {"ok": False, "error": "Text file is empty after stripping."}

    # Normalise instruct
    instruct_val = instruct.strip() if instruct else None

    _log(f"[worker] Generating — speaker={speaker!r}  language={language!r}"
         f"  instruct={instruct_val!r}  chars={len(text)}")

    # Generate
    try:
        wavs, sr = tts.generate_custom_voice(
            text=text,
            speaker=speaker,
            language=language,
            instruct=instruct_val,
        )
    except ValueError as exc:
        return {"ok": False,
                "error": f"Generation parameter rejected: {exc}"}
    except Exception as exc:
        return {"ok": False,
                "error": f"Generation failed: {exc}"}

    # Guard empty output
    if not wavs:
        return {"ok": False, "error": "Model returned empty audio output."}

    # Ensure output directory exists
    out_dir = os.path.dirname(os.path.abspath(out_path))
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "error": f"Cannot create output directory: {exc}"}

    # Save wav
    try:
        import soundfile as sf
        sf.write(out_path, wavs[0], sr)
    except Exception as exc:
        return {"ok": False, "error": f"Cannot save wav: {exc}"}

    _log(f"[worker] Saved: {out_path}")
    return {"ok": True, "path": out_path}


# ─────────────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────────────

def _command_loop(tts) -> None:
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        # Parse request
        try:
            req = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            _emit({"ok": False, "error": f"JSON parse error: {exc}"})
            continue

        cmd = req.get("cmd", "")

        if cmd == "ping":
            _emit({"status": "ready"})

        elif cmd == "generate":
            result = _handle_generate(tts, req)
            _emit(result)

        elif cmd == "shutdown":
            _emit({"status": "shutting_down"})
            break

        else:
            _emit({"ok": False, "error": f"Unknown command: {cmd!r}"})


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    args = _build_parser().parse_args()

    # Model load — emit error and exit nonzero on failure.
    try:
        tts = _load_model(args.model, args.device, args.dtype)
    except Exception as exc:
        _emit({"status": "error", "error": str(exc)})
        sys.exit(1)

    # Signal readiness to caller.
    _emit({"status": "ready", "model": args.model})

    # Enter command loop — exits on shutdown command or stdin EOF.
    try:
        _command_loop(tts)
    except KeyboardInterrupt:
        pass

    _log("[worker] Exiting cleanly.")
    sys.exit(0)


if __name__ == "__main__":
    main()
