#!/usr/bin/env python3
"""Local word-level alignment for story MV workflows (faster-whisper).

Produces JSON in the shape `scripts/mv_workflow.py make-srt` expects:

    {"meta": {...}, "alignedWords": [{"word": "...", "startS": 0.0, "endS": 0.5, "success": true}, ...]}

This is ASR-based, not forced alignment. Supplying --lyrics biases the decoder
(initial_prompt) so homophones land closer to the real text, but the timings
still come from the acoustic model: always spot-check the result before cutting
shots on it.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys


def probe_duration(audio: str) -> float | None:
    """Real media duration via ffprobe when available."""
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", audio],
            capture_output=True, text=True, timeout=60, check=True,
        ).stdout.strip()
        return float(out)
    except Exception:
        return None


_DLL_HANDLES: list = []


def add_cuda_dll_dirs() -> None:
    """ctranslate2 needs cublas/cudnn DLLs; the pip `nvidia-*` wheels ship them
    outside PATH, so register them explicitly on Windows."""
    if sys.platform != "win32":
        return
    site = pathlib.Path(__file__).resolve().parents[1]
    try:
        import site as _site
        candidates = []
        for p in (_site.getsitepackages() if hasattr(_site, "getsitepackages") else []):
            candidates.append(pathlib.Path(p))
        candidates.append(site)
        import importlib.util
        spec = importlib.util.find_spec("nvidia")
        if spec and spec.submodule_search_locations:
            candidates.extend(pathlib.Path(p) for p in spec.submodule_search_locations)
        seen = set()
        for root in candidates:
            nv = root / "nvidia"
            if not nv.is_dir():
                continue
            for bindir in nv.glob("*/bin"):
                key = str(bindir).lower()
                if key in seen:
                    continue
                seen.add(key)
                try:
                    _DLL_HANDLES.append(os.add_dll_directory(str(bindir)))
                    os.environ["PATH"] = str(bindir) + os.pathsep + os.environ.get("PATH", "")
                except OSError:
                    pass
    except Exception:
        pass



def srt_time(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, milli = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"


def write_srt(words: list[dict], output: str, per_caption: int = 8) -> int:
    blocks: list[str] = []
    group: list[dict] = []
    for w in words:
        group.append(w)
        if len(group) >= per_caption:
            blocks.append(_block(group, len(blocks) + 1))
            group = []
    if group:
        blocks.append(_block(group, len(blocks) + 1))
    pathlib.Path(output).write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    return len(blocks)


def _join(words: list[dict]) -> str:
    parts = [w["word"] for w in words]
    if any("\u4e00" <= ch <= "\u9fff" for w in parts for ch in w):
        return "".join(parts)
    return " ".join(parts)


def _block(group: list[dict], index: int) -> str:
    start = min(w["startS"] for w in group)
    end = max(w["endS"] for w in group)
    text = _join(group)
    return f"{index}\n{srt_time(start)} --> {srt_time(end)}\n{text}"


def load_lyrics_hint(path: str | None, limit: int = 180) -> str | None:
    if not path:
        return None
    raw = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    lines = [ln.strip() for ln in raw.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith(("[", "Style", "#"))]
    hint = " ".join(lines)[:limit]
    return hint or None


def main() -> int:
    ap = argparse.ArgumentParser(description="Word-level alignment via faster-whisper")
    ap.add_argument("audio")
    ap.add_argument("-o", "--output", help="JSON output (default: <audio>.words.json)")
    ap.add_argument("--lyrics", help="lyrics text file; used as decoder hint")
    ap.add_argument("--model", default="small", help="model name or local dir (default: small)")
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--compute-type", default=None, help="float16 / int8_float16 / int8")
    ap.add_argument("--language", default="zh")
    ap.add_argument("--srt", help="also write SRT here")
    ap.add_argument("--words-per-caption", type=int, default=8)
    ap.add_argument("--min-prob", type=float, default=0.35,
                    help="words below this probability are marked success=false")
    args = ap.parse_args()

    audio = str(pathlib.Path(args.audio).resolve())
    if not pathlib.Path(audio).exists():
        print(f"ERROR: audio not found: {audio}")
        return 2

    add_cuda_dll_dirs()
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("ERROR: faster-whisper not installed in this interpreter")
        return 2

    device = args.device
    compute = args.compute_type
    if device == "auto":
        try:
            import ctranslate2
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"
    if compute is None:
        compute = "float16" if device == "cuda" else "int8"

    print(f"model={args.model} device={device} compute={compute}")
    model = WhisperModel(args.model, device=device, compute_type=compute)
    hint = load_lyrics_hint(args.lyrics)
    if hint:
        print(f"lyrics hint: {hint[:40]}…")

    segments, info = model.transcribe(
        audio,
        language=args.language,
        word_timestamps=True,
        vad_filter=True,
        initial_prompt=hint,
        beam_size=5,
        condition_on_previous_text=False,
    )

    words: list[dict] = []
    for seg in segments:
        for w in (seg.words or []):
            text = w.word.strip()
            if not text:
                continue
            words.append({
                "word": text,
                "startS": round(w.start, 3),
                "endS": round(w.end, 3),
                "success": bool(getattr(w, "probability", 1.0) >= args.min_prob),
            })

    if not words:
        print("ERROR: no words recognised (silence, wrong language flag, or music only)")
        return 1

    duration = probe_duration(audio) or float(info.duration or 0.0)
    first, last = words[0]["startS"], words[-1]["endS"]
    covered = sum(w["endS"] - w["startS"] for w in words)
    gaps = []
    for prev, cur in zip(words, words[1:]):
        if cur["startS"] - prev["endS"] > 2.0:
            gaps.append([round(prev["endS"], 2), round(cur["startS"], 2)])

    payload = {
        "meta": {
            "audio": audio,
            "duration": round(duration, 3),
            "model": args.model,
            "device": device,
            "language": info.language,
            "language_probability": round(float(info.language_probability or 0), 3),
            "word_count": len(words),
            "first_word_s": first,
            "last_word_s": last,
            "intro_s": round(first, 3),
            "outro_s": round(max(0.0, duration - last), 3),
            "speech_ratio": round(covered / duration, 3) if duration else None,
            "gaps_over_2s": gaps,
            "low_confidence_words": sum(1 for w in words if not w["success"]),
            "method": "faster-whisper word_timestamps (ASR, not forced alignment)",
        },
        "alignedWords": words,
    }

    output = args.output or (str(pathlib.Path(audio).with_suffix("")) + ".words.json")
    pathlib.Path(output).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    m = payload["meta"]
    print(f"WROTE: {output}")
    print(f"words={m['word_count']} duration={m['duration']}s "
          f"first={m['first_word_s']}s last={m['last_word_s']}s")
    print(f"intro={m['intro_s']}s outro={m['outro_s']}s "
          f"low_conf={m['low_confidence_words']} gaps>2s={len(gaps)}")

    if args.srt:
        n = write_srt(words, args.srt, args.words_per_caption)
        print(f"WROTE: {args.srt} ({n} captions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
