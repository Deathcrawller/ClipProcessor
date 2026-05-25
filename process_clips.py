from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from clipprocessor.annotations import write_keyword_events_txt
from clipprocessor.clip_proposals import propose_clip_windows
from clipprocessor.export_clips import export_clips_from_txt, ffmpeg_available
from clipprocessor.fs import (
    ProjectPaths,
    ensure_dir,
    find_first_video,
    list_input_videos,
    read_json,
    safe_video_stem,
    write_json,
)
from clipprocessor.ocr_killfeed import run_killfeed_ocr


def _select_device(ocr_cfg: dict[str, Any]) -> str:
    """
    Select Paddle device before OCR initialization.

    PaddleOCR v3.x doesn't reliably accept legacy `use_gpu` kwargs. The most
    compatible approach is setting Paddle's global device.
    """
    want = str(ocr_cfg.get("device", "auto")).lower()
    try:
        import paddle  # type: ignore

        has_cuda = bool(getattr(paddle, "is_compiled_with_cuda", lambda: False)())
        if want in ("gpu", "cuda") or (want == "auto" and has_cuda):
            if has_cuda:
                paddle.device.set_device("gpu")
                return "gpu"
        paddle.device.set_device("cpu")
        return "cpu"
    except Exception:
        return "unknown"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ClipProcessor V1: killfeed OCR + keyword scoring")
    p.add_argument("--config", default="config.json", help="Path to config.json")
    p.add_argument("--video", default=None, help="Video path. Defaults to first .mp4 in Input/ then root.")
    p.add_argument("--all-videos", action="store_true", help="Process every .mp4 in Input/ (sorted by name).")
    p.add_argument("--step-sec", type=float, default=None, help="Override frame_step_sec from config.")
    p.add_argument("--start-seconds", type=float, default=None, help="Start processing at this timestamp (seconds).")
    p.add_argument("--max-seconds", type=float, default=None, help="Only process the first N seconds (debug).")
    p.add_argument("--save-crops", action="store_true", help="Save killfeed crop images to Temp/killfeed_crops.")
    p.add_argument("--save-crops-every", type=int, default=None, help="Override save_crops_every_n_frames.")
    p.add_argument("--write-clips-txt", default="clips.txt", help="Output clips.txt path (set empty to skip).")
    p.add_argument("--label-prefix", default=None, help="Prefix for clip basenames (default: stem or 'auto').")
    p.add_argument(
        "--ffmpeg-export",
        action="store_true",
        help="After scoring, run FFmpeg to cut clips (requires ffmpeg on PATH).",
    )
    return p.parse_args()


def _load_cfg(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing config file: {path}")
    return read_json(path)


def _process_one_video(
    *,
    video_path: str,
    cfg: dict[str, Any],
    paths: ProjectPaths,
    root: str,
    args: argparse.Namespace,
    events_json_path: str,
    clips_txt_path: str | None,
    clips_subdir: str,
    video_stem: str,
    label_prefix: str,
) -> tuple[int, int, int]:
    """Run OCR + scoring for one file. Returns (event_count, clip_window_count, annotation_line_count)."""
    ocr_cfg = cfg.get("ocr", {}) or {}
    debug_cfg = cfg.get("debug", {}) or {}
    crops_dir = os.path.join(paths.temp_dir, "killfeed_crops")
    save_crops = bool(args.save_crops or debug_cfg.get("save_crops", False))
    if save_crops:
        ensure_dir(crops_dir)
    else:
        crops_dir = None

    events, region, calibration_meta = run_killfeed_ocr(
        video_path=video_path,
        frame_step_sec=float(args.step_sec if args.step_sec is not None else cfg.get("frame_step_sec", 2.0)),
        region_cfg=cfg.get("killfeed_region", {}) or {},
        ocr_cfg=ocr_cfg,
        keywords=cfg.get("keywords", {}) or {},
        scoring_cfg=cfg.get("scoring", {}) or {},
        debug_save_crops=save_crops,
        debug_save_every_n_frames=int(
            args.save_crops_every
            if args.save_crops_every is not None
            else debug_cfg.get("save_crops_every_n_frames", 5)
        ),
        debug_crop_dir=crops_dir,
        start_seconds=float(args.start_seconds if args.start_seconds is not None else 0.0),
        max_seconds=args.max_seconds,
    )

    out_events = {
        "video_path": video_path,
        "killfeed_region_px": {"x": region.x, "y": region.y, "w": region.w, "h": region.h},
        "killfeed_calibration": calibration_meta,
        "event_count": len(events),
        "events": [
            {
                "timestamp_sec": e.timestamp_sec,
                "timestamp_hhmmss": e.timestamp_hhmmss,
                "text": e.text,
                "confidence": e.confidence,
                "score": e.score,
                "keyword_hits": e.keyword_hits,
            }
            for e in events
        ],
    }
    ensure_dir(os.path.dirname(events_json_path) or ".")
    write_json(events_json_path, out_events)
    if calibration_meta:
        cal_dir = os.path.dirname(events_json_path) or "."
        write_json(os.path.join(cal_dir, "killfeed_calibration.json"), calibration_meta)

    clip_cfg = cfg.get("clip_proposals", {}) or {}
    windows = propose_clip_windows(
        timestamps_sec=[e.timestamp_sec for e in events],
        scores=[e.score for e in events],
        score_threshold=int(clip_cfg.get("score_threshold", 8)),
        pre_seconds=float(clip_cfg.get("pre_seconds", 8)),
        post_seconds=float(clip_cfg.get("post_seconds", 20)),
        min_gap_seconds=float(clip_cfg.get("min_gap_seconds", 12)),
        label_prefix=label_prefix,
    )

    if clips_txt_path:
        ensure_dir(os.path.dirname(clips_txt_path) or ".")
        with open(clips_txt_path, "w", encoding="utf-8") as f:
            for w in windows:
                f.write(w.as_txt_row() + "\n")

    ann_cfg = clip_cfg.get("annotations", {}) or {}
    ann_enabled = bool(ann_cfg.get("enabled", True))
    n_ann = 0
    if ann_enabled:
        ensure_dir(clips_subdir)
        ann_path = os.path.join(clips_subdir, f"{video_stem}_events.txt")
        n_ann = write_keyword_events_txt(
            out_path=ann_path,
            events=events,
            video_path=video_path,
            score_threshold=int(clip_cfg.get("score_threshold", 8)),
            dedupe_window_sec=float(ann_cfg.get("dedupe_window_sec", 5.0)),
            include_score=bool(ann_cfg.get("include_score", True)),
        )

    return len(events), len(windows), n_ann


def main() -> int:
    args = _parse_args()
    cfg = _load_cfg(args.config)

    root = os.path.abspath(os.path.dirname(__file__))
    paths = ProjectPaths(
        root=root,
        input_dir=os.path.join(root, str(cfg.get("input_dir", "Input"))),
        temp_dir=os.path.join(root, str(cfg.get("temp_dir", "Temp"))),
        clips_dir=os.path.join(root, str(cfg.get("clips_dir", "Clips"))),
    )
    ensure_dir(paths.input_dir)
    ensure_dir(paths.temp_dir)
    ensure_dir(paths.clips_dir)

    pipe = cfg.get("pipeline", {}) or {}
    all_videos = bool(args.all_videos or pipe.get("process_all_videos", False))
    if args.video:
        all_videos = False
    do_ffmpeg = bool(args.ffmpeg_export or pipe.get("ffmpeg_export", False))

    if all_videos:
        videos = list_input_videos(paths.input_dir)
        if not videos:
            print(f"No .mp4 files in {paths.input_dir}", file=sys.stderr)
            return 1
    else:
        video_path = args.video or find_first_video(paths.root, os.path.basename(paths.input_dir))
        if not video_path:
            print(f"No .mp4 found in {paths.input_dir} or project root.", file=sys.stderr)
            return 1
        videos = [video_path]

    use_subdirs = bool(all_videos and len(videos) > 1)

    device = _select_device(cfg.get("ocr", {}) or {})
    if device != "unknown":
        print(f"Device: {device}")

    write_clips_root = str(args.write_clips_txt or "").strip()
    any_fail = False

    for video_path in videos:
        stem = safe_video_stem(video_path)
        default_prefix = stem if use_subdirs else "auto"
        prefix = (args.label_prefix or "").strip() or default_prefix

        # Per-video subfolder under Clips/ is always used so each video's
        # exports + annotation stay bundled together for hand-off.
        clips_subdir = os.path.join(paths.clips_dir, stem)

        if use_subdirs:
            sub = os.path.join(paths.temp_dir, stem)
            ensure_dir(sub)
            events_json_path = os.path.join(sub, "ocr_events.json")
            clips_txt_path = os.path.join(sub, "clips.txt") if write_clips_root else None
        else:
            events_json_path = os.path.join(paths.temp_dir, "ocr_events.json")
            clips_txt_path = (
                os.path.join(root, write_clips_root) if write_clips_root else None
            )

        print(f"\n=== {os.path.basename(video_path)} ===")
        try:
            n_ev, n_clips, n_ann = _process_one_video(
                video_path=video_path,
                cfg=cfg,
                paths=paths,
                root=root,
                args=args,
                events_json_path=events_json_path,
                clips_txt_path=clips_txt_path,
                clips_subdir=clips_subdir,
                video_stem=stem,
                label_prefix=prefix,
            )
        except Exception as ex:
            print(f"Error: {ex}", file=sys.stderr)
            any_fail = True
            continue

        print(f"OCR events: {n_ev} -> {events_json_path}")
        print(f"Proposed clips: {n_clips} -> {clips_txt_path or '(skipped)'}")
        if n_ann:
            print(
                f"Keyword annotations: {n_ann} -> "
                f"{os.path.join(clips_subdir, f'{stem}_events.txt')}"
            )

        if do_ffmpeg and clips_txt_path and os.path.isfile(clips_txt_path):
            if not ffmpeg_available():
                print("ffmpeg not found on PATH; skip export.", file=sys.stderr)
                any_fail = True
                continue
            ensure_dir(clips_subdir)
            try:
                n_cut = export_clips_from_txt(
                    video_path=video_path,
                    clips_txt_path=clips_txt_path,
                    output_dir=clips_subdir,
                )
                print(f"Exported {n_cut} clip(s) -> {clips_subdir}")
            except Exception as ex:
                print(f"FFmpeg export failed: {ex}", file=sys.stderr)
                any_fail = True

    if write_clips_root and not do_ffmpeg:
        if use_subdirs:
            print("\nPer-video clips.txt under Temp/<video>/ — use --ffmpeg-export or process_clips.bat per file.")
        else:
            print("\nNext: run process_clips.bat to export, or use --ffmpeg-export.")

    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
