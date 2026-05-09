from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Tuple

from .timeutil import clamp


@dataclass(frozen=True)
class Region:
    x: int
    y: int
    w: int
    h: int

    def as_slice(self) -> Tuple[slice, slice]:
        return (slice(self.y, self.y + self.h), slice(self.x, self.x + self.w))


def region_from_config(frame_w: int, frame_h: int, cfg: dict[str, Any]) -> Region:
    mode = str(cfg.get("mode", "relative")).lower()
    if mode == "auto":
        raise ValueError("killfeed_region.mode 'auto' is resolved in run_killfeed_ocr, not here.")
    x = float(cfg.get("x", 0))
    y = float(cfg.get("y", 0))
    w = float(cfg.get("w", frame_w))
    h = float(cfg.get("h", frame_h))

    if mode in ("relative", "manual"):
        rx = int(round(clamp(x, 0.0, 1.0) * frame_w))
        ry = int(round(clamp(y, 0.0, 1.0) * frame_h))
        rw = int(round(clamp(w, 0.0, 1.0) * frame_w))
        rh = int(round(clamp(h, 0.0, 1.0) * frame_h))
    else:
        rx, ry, rw, rh = int(round(x)), int(round(y)), int(round(w)), int(round(h))

    rx = max(0, min(rx, frame_w - 1))
    ry = max(0, min(ry, frame_h - 1))
    rw = max(1, min(rw, frame_w - rx))
    rh = max(1, min(rh, frame_h - ry))
    return Region(x=rx, y=ry, w=rw, h=rh)

