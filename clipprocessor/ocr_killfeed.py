from __future__ import annotations

from dataclasses import dataclass
import inspect
import math
from typing import Any, Optional

import cv2
import numpy as np
from paddleocr import PaddleOCR
from tqdm import tqdm

from .killfeed_region import Region, region_from_config
from .timeutil import format_hhmmss


def prepare_crop_for_ocr(frame: np.ndarray, region: Region, ocr_cfg: dict[str, Any]) -> np.ndarray:
    """Crop frame to region and apply optional resize / preprocess (same as main OCR loop)."""
    crop = frame[region.as_slice()]
    crop_scale = float(ocr_cfg.get("crop_scale", 1.0))
    if not (0.1 <= crop_scale <= 2.0):
        crop_scale = 1.0
    if crop_scale != 1.0:
        crop = cv2.resize(crop, dsize=None, fx=crop_scale, fy=crop_scale, interpolation=cv2.INTER_LINEAR)
    preprocess_cfg = ocr_cfg.get("preprocess", {}) or {}
    preprocess_enabled = bool(preprocess_cfg.get("enabled", False))
    preprocess_upscale = float(preprocess_cfg.get("upscale", 1.0))
    if not (0.5 <= preprocess_upscale <= 4.0):
        preprocess_upscale = 1.0
    preprocess_use_otsu = bool(preprocess_cfg.get("use_otsu", False))
    if preprocess_enabled:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        if preprocess_upscale != 1.0:
            gray = cv2.resize(
                gray, dsize=None, fx=preprocess_upscale, fy=preprocess_upscale, interpolation=cv2.INTER_CUBIC
            )
        gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
        if preprocess_use_otsu:
            gray = cv2.GaussianBlur(gray, (3, 3), 0)
            _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            crop = cv2.cvtColor(th, cv2.COLOR_GRAY2BGR)
        else:
            crop = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    return crop


@dataclass(frozen=True)
class OcrEvent:
    timestamp_sec: float
    timestamp_hhmmss: str
    text: str
    confidence: float
    score: int
    keyword_hits: dict[str, int]


def _init_ocr(cfg: dict[str, Any]) -> PaddleOCR:
    # PaddleOCR's init args changed significantly in v3.x. We introspect the
    # constructor signature and pass only supported kwargs to stay compatible.
    sig = inspect.signature(PaddleOCR.__init__)
    supported = set(sig.parameters.keys())

    kwargs: dict[str, Any] = {}
    if "lang" in supported:
        kwargs["lang"] = str(cfg.get("lang", "en"))
    if "use_gpu" in supported:
        kwargs["use_gpu"] = bool(cfg.get("use_gpu", False))
    if "enable_mkldnn" in supported:
        # Workaround for a known PaddlePaddle CPU+oneDNN issue; keep off by default.
        kwargs["enable_mkldnn"] = bool(cfg.get("enable_mkldnn", False))
    if "text_rec_score_thresh" in supported:
        kwargs["text_rec_score_thresh"] = float(cfg.get("min_confidence", 0.0))

    return PaddleOCR(**kwargs)


def _ocr_lines(ocr: PaddleOCR, img_bgr: np.ndarray) -> list[tuple[str, float]]:
    # PaddleOCR v2.x used .ocr(..., cls=...), v3.x routes to .predict(img, **kwargs).
    # Call with minimal kwargs and parse flexibly.
    try:
        res = ocr.ocr(img_bgr)
    except TypeError:
        res = ocr.ocr(img_bgr, cls=False)
    lines: list[tuple[str, float]] = []
    if not res:
        return lines
    for page in res:
        if not page:
            continue
        # v2: [[bbox, (text, conf)], ...]
        if isinstance(page, list) and page and isinstance(page[0], (list, tuple)) and len(page[0]) == 2:
            for _bbox, tc in page:
                if isinstance(tc, (list, tuple)) and len(tc) >= 2:
                    text, conf = tc[0], tc[1]
                    t = (text or "").strip()
                    if t:
                        lines.append((t, float(conf)))
            continue
        # v3: dict-like results from PaddleX pipeline
        if isinstance(page, dict):
            items = page.get("rec_texts") or page.get("text") or []
            confs = page.get("rec_scores") or page.get("score") or []
            if isinstance(items, str):
                items = [items]
            if isinstance(confs, (int, float)):
                confs = [float(confs)]
            for i, t0 in enumerate(items):
                t = (t0 or "").strip()
                if not t:
                    continue
                conf = float(confs[i]) if i < len(confs) else 1.0
                lines.append((t, conf))
    return lines


def _fuzzy_min_haystack_len(kw: str, scoring_cfg: dict[str, Any]) -> int:
    """
    Minimum OCR text length before fuzzy matching is allowed. Shorter strings
    otherwise get max partial_ratio against long keywords (e.g. "ni" inside
    "running", "z" in "frenzy") and produce false positives.
    """
    abs_min = int(scoring_cfg.get("fuzzy_min_haystack_chars", 5))
    abs_min = max(1, abs_min)
    ratio = float(scoring_cfg.get("fuzzy_min_haystack_ratio", 0.35))
    ratio = max(0.0, min(1.0, ratio))
    compact = len(kw.replace(" ", ""))
    need = int(math.ceil(ratio * compact)) if compact else abs_min
    return max(abs_min, need)


def _partial_match_strength(kw: str, hay: str) -> int:
    """
    Return 0–100 strength of best fuzzy match of keyword inside haystack.
    Uses rapidfuzz when available; otherwise a small difflib substring scan.
    """
    if not kw or not hay:
        return 0
    try:
        from rapidfuzz import fuzz

        return int(fuzz.partial_ratio(kw, hay))
    except ImportError:
        import difflib

        lk, lh = len(kw), len(hay)
        best = 0.0
        for win in range(max(1, lk - 2), min(lh, lk + 8) + 1):
            for i in range(0, lh - win + 1):
                chunk = hay[i : i + win]
                r = difflib.SequenceMatcher(None, kw, chunk).ratio()
                if r > best:
                    best = r
        return int(100 * best)


def _score_text(
    text: str,
    keywords: dict[str, int],
    *,
    case_insensitive: bool,
    per_keyword_max_hits: int,
    scoring_cfg: Optional[dict[str, Any]] = None,
) -> tuple[int, dict[str, int]]:
    """
    Keyword hits: exact substring counts first. If fuzzy_match is enabled and
    there are zero exact hits, fall back to fuzzy partial match so OCR
    variants like "OvERKILi" still match "overkill".
    """
    sc = scoring_cfg or {}
    fuzzy_on = bool(sc.get("fuzzy_match", True))
    fuzzy_thresh = int(sc.get("fuzzy_partial_threshold", 82))
    fuzzy_thresh = max(50, min(100, fuzzy_thresh))
    fuzzy_min_len = int(sc.get("fuzzy_min_keyword_len", 4))
    hay = text.lower() if case_insensitive else text
    total = 0
    hits: dict[str, int] = {}
    for raw_kw, weight in keywords.items():
        if not raw_kw:
            continue
        kw = raw_kw.lower() if case_insensitive else raw_kw
        exact = hay.count(kw)
        count = 0
        if exact > 0:
            count = min(exact, int(per_keyword_max_hits))
        elif fuzzy_on and len(kw) >= fuzzy_min_len:
            hay_len = len(hay.strip())
            if hay_len >= _fuzzy_min_haystack_len(kw, sc):
                pr = _partial_match_strength(kw, hay)
                if pr >= fuzzy_thresh:
                    count = 1
        if count <= 0:
            continue
        count = min(count, int(per_keyword_max_hits))
        hits[raw_kw] = count
        total += int(weight) * count
    return total, hits


def run_killfeed_ocr(
    *,
    video_path: str,
    frame_step_sec: float,
    region_cfg: dict[str, Any],
    ocr_cfg: dict[str, Any],
    keywords: dict[str, int],
    scoring_cfg: dict[str, Any],
    debug_save_crops: bool,
    debug_save_every_n_frames: int,
    debug_crop_dir: Optional[str],
    start_seconds: float = 0.0,
    max_seconds: Optional[float] = None,
) -> tuple[list[OcrEvent], Region, Optional[dict[str, Any]]]:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open video: {video_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 0:
        fps = 30.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(0.25, float(frame_step_sec))
    step_frames = max(1, int(round(step * fps)))

    ok, first = cap.read()
    if not ok or first is None:
        raise RuntimeError("Failed to read first frame.")
    frame_h, frame_w = first.shape[:2]
    mode = str(region_cfg.get("mode", "relative")).lower()
    ocr = _init_ocr(ocr_cfg)
    calibration_meta: Optional[dict[str, Any]] = None
    if mode == "auto":
        from .killfeed_auto import detect_killfeed_region

        region, calibration_meta = detect_killfeed_region(
            cap=cap,
            frame_w=frame_w,
            frame_h=frame_h,
            fps=fps,
            frame_count=frame_count,
            region_cfg=region_cfg,
            ocr_cfg=ocr_cfg,
            keywords=keywords,
            scoring_cfg=scoring_cfg,
            ocr=ocr,
        )
    else:
        region = region_from_config(frame_w, frame_h, region_cfg)

    min_conf = float(ocr_cfg.get("min_confidence", 0.0))
    case_insensitive = bool(scoring_cfg.get("case_insensitive", True))
    per_keyword_max_hits = int(scoring_cfg.get("per_keyword_max_hits", 3))

    events: list[OcrEvent] = []
    start_seconds = max(0.0, float(start_seconds))
    frame_idx = int(round(start_seconds * fps))
    sample_idx = 0
    # Re-process the first frame as part of the sequential loop.
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    pbar_total = (frame_count // step_frames + 1) if frame_count > 0 else None

    for _ in tqdm(iter(int, 1), total=pbar_total, desc="OCR killfeed", unit="sample"):
        # Advance to the next sampled frame efficiently.
        if frame_idx == 0:
            ok, frame = cap.read()
        else:
            for _skip in range(step_frames - 1):
                ok = cap.grab()
                if not ok:
                    break
            if not ok:
                break
            ok, frame = cap.read()
        if not ok or frame is None:
            break

        t = frame_idx / fps
        if max_seconds is not None and t > float(max_seconds):
            break
        crop = prepare_crop_for_ocr(frame, region, ocr_cfg)
        lines = _ocr_lines(ocr, crop)
        if lines:
            joined = " | ".join([l[0] for l in lines])
            conf = float(np.mean([l[1] for l in lines]))
            if conf >= min_conf:
                score, hits = _score_text(
                    joined,
                    keywords,
                    case_insensitive=case_insensitive,
                    per_keyword_max_hits=per_keyword_max_hits,
                    scoring_cfg=scoring_cfg,
                )
                events.append(
                    OcrEvent(
                        timestamp_sec=float(t),
                        timestamp_hhmmss=format_hhmmss(t),
                        text=joined,
                        confidence=conf,
                        score=int(score),
                        keyword_hits=hits,
                    )
                )

        if debug_save_crops and debug_crop_dir and (
            sample_idx % max(1, int(debug_save_every_n_frames)) == 0
        ):
            out = f"{debug_crop_dir}/killfeed_{sample_idx:06d}_{format_hhmmss(t).replace(':', '-')}.png"
            cv2.imwrite(out, crop)

        sample_idx += 1
        frame_idx += step_frames

    cap.release()
    return events, region, calibration_meta

