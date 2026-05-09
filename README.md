# ClipProcessor

Killfeed **OCR** on Halo VODs, **keyword scoring**, and **FFmpeg** clip export. Built for long Grifball / match recordings so you can turn medal lines and other HUD text into highlight candidates.

## Quick start

1. **Install** (from this folder):

   ```bash
   pip install -r requirements.txt
   ```

   GPU notes and Paddle checks are in [`docs/overview.md`](docs/overview.md).

2. Put one or more **`.mp4`** files in **`Input/`**.

3. **Run** (pick one):

   | Action | Command |
   |--------|---------|
   | One-click batch (all `Input/*.mp4` + FFmpeg) | Double-click **`run_process.bat`** |
   | Single video (first sorted `.mp4` in `Input/`) | `python process_clips.py` |
   | All videos, OCR + score only | `python process_clips.py --all-videos` |
   | All videos + cut clips via FFmpeg | `python process_clips.py --all-videos --ffmpeg-export` |

4. **Outputs**

   - **`Temp/`** — `ocr_events.json`, optional `killfeed_calibration.json`, per-video subfolders when processing multiple files.
   - **`clips.txt`** — FFmpeg-friendly rows: `START|END|basename|title` (at project root for a single video, or under `Temp/<video-stem>/` when batching).
   - **`Clips/`** — exported `.mp4` clips (flat for one video, or `Clips/<video-stem>/` when batching).

   Manual export: **`process_clips.bat`** (expects `clips.txt` + an `.mp4` in the project root — legacy single-file flow).

## Configuration

Edit **`config.json`**:

- **`killfeed_region`** — `auto` vs `manual` crop; `x_offsets` / `y_offsets`, `calibration_keywords`, `calibration_min_confidence`, `negative_substrings`.
- **`keywords`** — weights for scoring (medals, objectives, etc.).
- **`scoring`** — fuzzy OCR matching thresholds.
- **`clip_proposals`** — score threshold, pre/post roll, minimum gap between clips.
- **`pipeline`** — optional `process_all_videos` / `ffmpeg_export` defaults.

## Project layout

```
ClipProcessor/
  README.md
  config.json
  requirements.txt
  process_clips.py
  run_process.bat
  process_clips.bat
  clipprocessor/     # Python package (OCR, region, scoring, export)
  docs/overview.md   # Detailed run notes, GPU, HUD calibration
  Input/             # Drop your .mp4 files here
  Temp/              # Generated (gitignored)
  Clips/             # Exported clips (gitignored)
```

## Documentation

See **[`docs/overview.md`](docs/overview.md)** for folder layout, killfeed auto-calibration, scoring behavior, and troubleshooting.

## Requirements

- **Python 3** (see `requirements.txt` for Paddle / OCR stack).
- **FFmpeg** on your PATH for `--ffmpeg-export`, `run_process.bat`, or `process_clips.bat`.
