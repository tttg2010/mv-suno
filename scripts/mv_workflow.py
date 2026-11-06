#!/usr/bin/env python3
"""Offline helpers for story MV manifests and aligned-word subtitles.

No network calls and no paid API calls are made by this script.
"""
from __future__ import annotations
import argparse
import json
import pathlib
import sys
from typing import Any


def load_json(path: str) -> Any:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def parse_time(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if ":" in text:
        parts = text.split(":")
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    return float(text)


def validate_manifest(path: str, max_seconds: float = 15.0) -> int:
    data = load_json(path)
    shots = data.get("shots", data.get("images", data if isinstance(data, list) else []))
    if not isinstance(shots, list) or not shots:
        print("ERROR: manifest must be a non-empty list or contain shots[]")
        return 2
    errors: list[str] = []
    seen: set[str] = set()
    previous_end: float | None = None
    for i, shot in enumerate(shots, 1):
        sid = str(shot.get("id", f"#{i}"))
        if sid in seen:
            errors.append(f"{sid}: duplicate id")
        seen.add(sid)
        try:
            start = parse_time(shot["start"])
            end = parse_time(shot["end"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"{sid}: start/end must be numeric")
            continue
        duration = end - start
        if duration <= 0:
            errors.append(f"{sid}: non-positive duration {duration:.3f}s")
        if duration > max_seconds + 1e-6:
            errors.append(f"{sid}: duration {duration:.3f}s exceeds {max_seconds:.3f}s")
        if previous_end is not None and start < previous_end - 1e-3:
            errors.append(f"{sid}: overlaps previous shot")
        is_lipsync = bool(shot.get("lipsync") or str(shot.get("type", "")).lower() == "lipsync")
        has_audio = shot.get("reference_audio", shot.get("audio", is_lipsync))
        if is_lipsync and not has_audio:
            errors.append(f"{sid}: lipsync shot has no reference_audio/audio marker")
        previous_end = max(previous_end or end, end)
    if errors:
        print("INVALID")
        print("\n".join(f"- {e}" for e in errors))
        return 1
    print(f"VALID: {len(shots)} shots; all durations <= {max_seconds:.3f}s")
    return 0


def find_aligned_words(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        if isinstance(data.get("alignedWords"), list):
            return data["alignedWords"]
        for value in data.values():
            found = find_aligned_words(value)
            if found:
                return found
    elif isinstance(data, list):
        for value in data:
            found = find_aligned_words(value)
            if found:
                return found
    return []


def srt_time(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, milli = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"


def make_srt(path: str, output: str, words_per_caption: int = 8) -> int:
    words = find_aligned_words(load_json(path))
    if not words:
        print("ERROR: no alignedWords found")
        return 2
    blocks: list[str] = []
    group: list[dict[str, Any]] = []
    for word in words:
        text = str(word.get("word", "")).strip()
        if not text:
            continue
        group.append(word)
        if len(group) >= words_per_caption:
            blocks.append(group_to_srt(group, len(blocks) + 1))
            group = []
    if group:
        blocks.append(group_to_srt(group, len(blocks) + 1))
    pathlib.Path(output).write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    print(f"WROTE: {output} ({len(blocks)} captions)")
    return 0


def group_to_srt(group: list[dict[str, Any]], index: int) -> str:
    start = min(float(w["startS"]) for w in group)
    end = max(float(w["endS"]) for w in group)
    parts = [str(w.get("word", "")).strip() for w in group]
    is_cjk = any("\u4e00" <= ch <= "\u9fff" for w in parts for ch in w)
    text = "".join(parts) if is_cjk else " ".join(p for p in parts if p)
    return f"{index}\n{srt_time(start)} --> {srt_time(end)}\n{text}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline story MV workflow checks")
    sub = parser.add_subparsers(dest="command", required=True)
    p_validate = sub.add_parser("validate-manifest")
    p_validate.add_argument("manifest")
    p_validate.add_argument("--max-seconds", type=float, default=15.0)
    p_srt = sub.add_parser("make-srt")
    p_srt.add_argument("timestamps")
    p_srt.add_argument("output")
    p_srt.add_argument("--words-per-caption", type=int, default=8)
    args = parser.parse_args()
    if args.command == "validate-manifest":
        return validate_manifest(args.manifest, args.max_seconds)
    return make_srt(args.timestamps, args.output, args.words_per_caption)


if __name__ == "__main__":
    sys.exit(main())
