from __future__ import annotations

import os
from typing import Iterable, Optional, Sequence

from .fs import ensure_dir
from .ocr_killfeed import OcrEvent
from .timeutil import format_hhmmss


def _format_keyword_label(raw: str) -> str:
    """Render a config keyword for the report (e.g. "killing spree" -> "Killing Spree")."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    return " ".join(part.capitalize() for part in raw.split())


def _collect_keyword_lines(
    events: Sequence[OcrEvent],
    dedupe_window_sec: float,
) -> list[tuple[float, int, list[str]]]:
    """
    Walk OCR events in chronological order and yield one entry per "fresh"
    keyword observation. The killfeed lingers across consecutive OCR samples,
    so we suppress repeats of the same keyword that occur within
    `dedupe_window_sec` seconds of the previously accepted occurrence.

    Returns a list of ``(timestamp_sec, score, [keywords])`` tuples. Multiple
    keywords are grouped when they all become fresh on the same event.
    """
    window = max(0.0, float(dedupe_window_sec))
    last_seen: dict[str, float] = {}
    out: list[tuple[float, int, list[str]]] = []
    for ev in sorted(events, key=lambda e: e.timestamp_sec):
        if not ev.keyword_hits:
            continue
        fresh: list[str] = []
        for kw in ev.keyword_hits.keys():
            prev = last_seen.get(kw)
            if prev is None or (ev.timestamp_sec - prev) > window:
                fresh.append(kw)
                last_seen[kw] = ev.timestamp_sec
        if fresh:
            out.append((float(ev.timestamp_sec), int(ev.score), fresh))
    return out


def write_keyword_events_txt(
    *,
    out_path: str,
    events: Iterable[OcrEvent],
    video_path: str,
    score_threshold: Optional[int] = None,
    dedupe_window_sec: float = 5.0,
    include_score: bool = True,
) -> int:
    """
    Write a human-readable text doc of every OCR event with at least one
    keyword hit. The format is intentionally simple so a reviewer can scan it:

        00:05:54 - Overkill                  (score 12)
        00:06:23 - Scored                    (score 20)  *
        00:08:11 - Killing Spree, Overkill   (score 22)  *

    A trailing ``*`` (when ``score_threshold`` is provided) marks lines whose
    event crossed the clipping threshold, i.e. produced a clip window.

    Returns the number of data lines written (header excluded).
    """
    ensure_dir(os.path.dirname(out_path) or ".")
    entries = _collect_keyword_lines(list(events), dedupe_window_sec=dedupe_window_sec)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# Keyword events for {os.path.basename(video_path)}\n")
        f.write(f"# Source: {video_path}\n")
        if score_threshold is not None:
            f.write(
                f"# Clip score threshold: {int(score_threshold)} "
                "(lines marked with * triggered a clip window)\n"
            )
        f.write(f"# Duplicate-keyword suppression window: {dedupe_window_sec:g}s\n")
        f.write(
            "# Format: HH:MM:SS - Keyword[, Keyword...] "
            + ("(score N)" if include_score else "")
            + "\n"
        )
        f.write("\n")

        count = 0
        for ts, score, kws in entries:
            label = ", ".join(_format_keyword_label(k) for k in kws)
            line = f"{format_hhmmss(ts)} - {label}"
            if include_score:
                line += f"  (score {int(score)})"
            if score_threshold is not None and int(score) >= int(score_threshold):
                line += "  *"
            f.write(line + "\n")
            count += 1
    return count
