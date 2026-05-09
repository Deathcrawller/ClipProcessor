from __future__ import annotations

import math


def format_hhmmss(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    whole = int(math.floor(seconds + 1e-9))
    h = whole // 3600
    m = (whole % 3600) // 60
    s = whole % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

