from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, List

from .timeutil import format_hhmmss


def _peak_vod_compact(peak_sec: float) -> str:
    """HHMMSS (no separators) for filenames, from VOD time at peak."""
    whole = int(math.floor(float(peak_sec) + 1e-9))
    h = whole // 3600
    m = (whole % 3600) // 60
    s = whole % 60
    return f"{h:02d}{m:02d}{s:02d}"


@dataclass(frozen=True)
class ClipWindow:
    start_sec: float
    end_sec: float
    peak_sec: float
    label: str
    score: int
    meta_title: str

    def as_txt_row(self) -> str:
        # Fourth field is FFmpeg metadata title (no | characters).
        return f"{format_hhmmss(self.start_sec)}|{format_hhmmss(self.end_sec)}|{self.label}|{self.meta_title}"


def propose_clip_windows(
    *,
    timestamps_sec: Iterable[float],
    scores: Iterable[int],
    score_threshold: int,
    pre_seconds: float,
    post_seconds: float,
    min_gap_seconds: float,
    label_prefix: str = "auto",
) -> List[ClipWindow]:
    pts = sorted(zip(timestamps_sec, scores), key=lambda x: x[0])
    out: List[ClipWindow] = []

    last_end = -1e9
    n = 0
    for t, s in pts:
        if int(s) < int(score_threshold):
            continue
        start = max(0.0, float(t) - float(pre_seconds))
        end = max(start + 0.1, float(t) + float(post_seconds))
        if start < last_end + float(min_gap_seconds):
            continue
        n += 1
        peak = float(t)
        vod = format_hhmmss(peak)
        vod_compact = _peak_vod_compact(peak)
        label = f"{label_prefix}-{n:03d}-VOD{vod_compact}-peak{int(peak)}s-score{int(s)}"
        meta_title = f"VOD {vod} ({int(peak)}s) score {int(s)}"
        out.append(
            ClipWindow(
                start_sec=start,
                end_sec=end,
                peak_sec=peak,
                label=label,
                score=int(s),
                meta_title=meta_title,
            )
        )
        last_end = end

    return out

