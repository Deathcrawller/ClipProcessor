from __future__ import annotations

from typing import Any, Optional

import cv2
import numpy as np
from paddleocr import PaddleOCR

from .killfeed_region import Region, region_from_config
from .ocr_killfeed import _ocr_lines, _score_text, prepare_crop_for_ocr


def _candidate_relative_boxes(auto_cfg: dict[str, Any]) -> list[dict[str, float]]:
    custom = auto_cfg.get("candidates")
    if isinstance(custom, list) and custom:
        out: list[dict[str, float]] = []
        for c in custom:
            if not isinstance(c, dict):
                continue
            out.append(
                {
                    "x": float(c.get("x", 0)),
                    "y": float(c.get("y", 0)),
                    "w": float(c.get("w", 0.4)),
                    "h": float(c.get("h", 0.2)),
                }
            )
        return out
    # Default grid: multiple X anchors because Halo HUD safe-zone shifts the killfeed
    # from flush-left to center-left between players / streams.
    xs_cfg = auto_cfg.get("x_offsets")
    if isinstance(xs_cfg, list) and xs_cfg:
        xs = [float(v) for v in xs_cfg]
    else:
        xs = [0.0, 0.05, 0.10, 0.15, 0.20, 0.25]
    ys_cfg = auto_cfg.get("y_offsets")
    if isinstance(ys_cfg, list) and ys_cfg:
        ys = [float(v) for v in ys_cfg]
    else:
        # Default Y anchors cover both "classic" and slightly higher killfeed placements.
        ys = [0.32, 0.38, 0.44, 0.50, 0.56]
    hs = [0.18, 0.22]
    ws = [0.36, 0.42]
    boxes: list[dict[str, float]] = []
    for x in xs:
        for y in ys:
            for w in ws:
                for h in hs:
                    if y + h <= 1.02 and x + w <= 1.01:
                        boxes.append({"x": x, "y": y, "w": w, "h": h})
    return boxes


def _region_key(rel: dict[str, float]) -> str:
    return f"{rel['x']:.3f},{rel['y']:.3f},{rel['w']:.3f},{rel['h']:.3f}"


def detect_killfeed_region(
    *,
    cap: cv2.VideoCapture,
    frame_w: int,
    frame_h: int,
    fps: float,
    frame_count: int,
    region_cfg: dict[str, Any],
    ocr_cfg: dict[str, Any],
    keywords: dict[str, int],
    scoring_cfg: dict[str, Any],
    ocr: PaddleOCR,
) -> tuple[Region, dict[str, Any]]:
    """
    Pick a crop region by OCR-scoring candidate boxes on a few sampled frames.
    """
    auto_cfg = region_cfg.get("auto") or {}
    probe_start = max(0.0, float(auto_cfg.get("probe_start_sec", 45.0)))
    probe_dur = max(30.0, float(auto_cfg.get("probe_duration_sec", 600.0)))
    sample_n = max(3, int(auto_cfg.get("sample_count", 8)))
    min_total = float(auto_cfg.get("min_calibration_score", 4.0))
    # During calibration we can accept lower-confidence OCR, otherwise we may
    # fail to detect any text at all and every candidate scores 0.
    min_conf = float(auto_cfg.get("calibration_min_confidence", ocr_cfg.get("min_confidence", 0.0)))

    duration = frame_count / fps if frame_count > 0 and fps > 0 else 0.0
    window_end = probe_start + probe_dur
    if duration > 0:
        window_end = min(window_end, duration)
    if window_end <= probe_start + 1.0:
        window_end = probe_start + 120.0

    times: list[float] = []
    if sample_n == 1:
        times = [probe_start]
    else:
        span = max(1.0, window_end - probe_start)
        for i in range(sample_n):
            times.append(probe_start + span * (i / (sample_n - 1)))

    rel_boxes = _candidate_relative_boxes(auto_cfg)
    totals: dict[str, float] = { _region_key(b): 0.0 for b in rel_boxes }
    # Calibration can optionally use a different keyword set than main scoring.
    # This is useful when killfeed is mostly "X killed Y" (no medals), which
    # would otherwise score 0 everywhere and cause fallback.
    cal_keywords = auto_cfg.get("calibration_keywords")
    if isinstance(cal_keywords, dict) and cal_keywords:
        try:
            keywords_for_cal = {str(k): int(v) for k, v in cal_keywords.items() if str(k)}
        except Exception:
            keywords_for_cal = keywords
    else:
        keywords_for_cal = keywords

    for t in times:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        for rel in rel_boxes:
            r = region_from_config(frame_w, frame_h, {"mode": "relative", **rel})
            crop = prepare_crop_for_ocr(frame, r, ocr_cfg)
            lines = _ocr_lines(ocr, crop)
            if not lines:
                continue
            joined = " | ".join([x[0] for x in lines])
            conf = float(np.mean([x[1] for x in lines]))
            if conf < min_conf:
                continue
            score, _hits = _score_text(
                joined,
                keywords_for_cal,
                case_insensitive=bool(scoring_cfg.get("case_insensitive", True)),
                per_keyword_max_hits=int(scoring_cfg.get("per_keyword_max_hits", 3)),
                scoring_cfg=scoring_cfg,
            )
            neg = auto_cfg.get("negative_substrings") or []
            if isinstance(neg, list):
                low = joined.lower()
                for s in neg:
                    if isinstance(s, str) and s and s.lower() in low:
                        score = max(0, int(score) - 3)
            k = _region_key(rel)
            totals[k] = totals.get(k, 0.0) + float(score)

    best_key = max(totals, key=totals.get, default="")
    best_total = totals.get(best_key, 0.0)
    best_rel: Optional[dict[str, float]] = None
    for rel in rel_boxes:
        if _region_key(rel) == best_key:
            best_rel = rel
            break

    meta: dict[str, Any] = {
        "mode": "auto",
        "probe_start_sec": probe_start,
        "probe_end_sec": window_end,
        "sample_timestamps_sec": times,
        "calibration_min_confidence": min_conf,
        "calibration_keywords": list(keywords_for_cal.keys()),
        "per_candidate_score": totals,
        "best_total_score": best_total,
    }

    if best_rel is None or best_total < min_total:
        manual = region_cfg.get("manual")
        if isinstance(manual, dict) and manual:
            meta["fallback"] = "manual"
            region = region_from_config(frame_w, frame_h, manual)
            meta["killfeed_region_px"] = {"x": region.x, "y": region.y, "w": region.w, "h": region.h}
            return region, meta
        raise RuntimeError(
            f"Killfeed auto-calibration failed (best score {best_total} < {min_total}). "
            "Tweak killfeed_region.auto or set killfeed_region.mode to relative with manual x,y,w,h."
        )

    region = region_from_config(frame_w, frame_h, {"mode": "relative", **best_rel})
    meta["chosen_relative"] = best_rel
    meta["killfeed_region_px"] = {"x": region.x, "y": region.y, "w": region.w, "h": region.h}
    return region, meta
