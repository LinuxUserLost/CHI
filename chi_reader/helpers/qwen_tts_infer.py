#!/usr/bin/env python3
"""
helpers/qwen_tts_infer.py — standalone batch inference script for Qwen TTS.

Called by qwen_tts_backend.py as a subprocess.  Must run inside the
qwen3tts-venv where qwen_tts is installed.

Usage:
    /home/min/qwen3tts-venv/bin/python qwen_tts_infer.py \
        --model  Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice \
        --text-file  /tmp/qwen_tts_xxxxx.txt \
        --speaker    default \
        --output     /home/user/qwen_tts_output/file.wav \
        --device     cpu \
        --dtype      float32 \
        --no-flash-attn

Exit 0 on success, 1 on any failure (error details on stderr).
"""

import argparse
import os
import sys


def _build_parser():
    p = argparse.ArgumentParser(description="Qwen3 TTS batch inference")
    p.add_argument("--model",       required=True,
                   help="HuggingFace repo ID or local path to a Qwen3-TTS model")
    p.add_argument("--text-file",   required=True,
                   help="Path to a UTF-8 text file containing text to synthesise")
    p.add_argument("--speaker",     default="default",
                   help="Speaker ID for CustomVoice models (default: 'default')")
    p.add_argument("--language",    default=None,
                   help="Language hint (optional, e.g. 'english', 'chinese'). "
                        "Leave unset for Auto-detect.")
    p.add_argument("--instruct",    default="",
                   help="Style/tone instruction (optional). "
                        "Silently ignored for 0.6B models.")
    p.add_argument("--output",      required=True,
                   help="Output .wav file path")
    p.add_argument("--device",      default="cpu",
                   help="Torch device: cpu | cuda | cuda:0 (default: cpu)")
    p.add_argument("--dtype",       default="float32",
                   choices=["float32", "fp32", "float16", "fp16",
                            "bfloat16", "bf16"],
                   help="Torch dtype (default: float32)")
    p.add_argument("--no-flash-attn", action="store_true", dest="no_flash_attn",
                   help="Disable FlashAttention-2 (safe for CPU / unpatched envs)")
    p.add_argument("--seed", type=int, default=None,
                   help="Random seed for reproducible generation (omit for random output)")
    return p


def _dtype(name: str):
    import torch
    return {
        "float32": torch.float32, "fp32":    torch.float32,
        "float16": torch.float16, "fp16":    torch.float16,
        "bfloat16": torch.bfloat16, "bf16": torch.bfloat16,
    }[name]


def main():
    args = _build_parser().parse_args()

    # ── 1. Read text ───────────────────────────────────────────────────────────
    try:
        with open(args.text_file, "r", encoding="utf-8") as fh:
            text = fh.read().strip()
    except OSError as exc:
        print(f"ERROR reading text file: {exc}", file=sys.stderr)
        sys.exit(1)

    if not text:
        print("ERROR: text file is empty.", file=sys.stderr)
        sys.exit(1)

    # ── 2. Load model ──────────────────────────────────────────────────────────
    try:
        from qwen_tts import Qwen3TTSModel
    except ImportError as exc:
        print(f"ERROR: cannot import qwen_tts — is the venv correct?\n  {exc}",
              file=sys.stderr)
        sys.exit(1)

    torch_dtype = _dtype(args.dtype)
    print(f"[qwen_tts_infer] Loading model: {args.model}", flush=True)
    print(f"[qwen_tts_infer] device={args.device}  dtype={args.dtype}", flush=True)

    try:
        tts = Qwen3TTSModel.from_pretrained(
            args.model,
            device_map=args.device,
            torch_dtype=torch_dtype,
        )
    except Exception as exc:
        print(f"ERROR: model load failed:\n  {exc}", file=sys.stderr)
        sys.exit(1)

    # Print supported speakers so the user can see valid IDs in the log
    try:
        spks = tts.model.get_supported_speakers()
        print(f"[qwen_tts_infer] Supported speakers: {spks}", flush=True)
    except Exception:
        pass

    # ── 3. Generate ────────────────────────────────────────────────────────────
    if args.seed is not None:
        import random
        import numpy
        import torch
        random.seed(args.seed)
        numpy.random.seed(args.seed)
        torch.manual_seed(args.seed)
        print(f"[qwen_tts_infer] seed={args.seed}", flush=True)

    instruct_val = args.instruct.strip() if args.instruct else None
    print(f"[qwen_tts_infer] Generating — speaker={args.speaker!r}  "
          f"language={args.language!r}  instruct={instruct_val!r}", flush=True)
    try:
        wavs, sr = tts.generate_custom_voice(
            text=text,
            speaker=args.speaker,
            language=args.language,
            instruct=instruct_val,
        )
    except ValueError as exc:
        # ValueError is raised for bad speaker/language — give a clear message
        print(f"ERROR: generation parameter rejected:\n  {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"ERROR: generation failed:\n  {exc}", file=sys.stderr)
        sys.exit(1)

    # ── 4. Save ────────────────────────────────────────────────────────────────
    out_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(out_dir, exist_ok=True)

    try:
        import soundfile as sf
        sf.write(args.output, wavs[0], sr)
    except Exception as exc:
        print(f"ERROR: could not save wav:\n  {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"[qwen_tts_infer] Saved: {args.output}", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
