# ClipProcessor

Killfeed **OCR** on Halo VODs, **keyword scoring**, and **FFmpeg** clip export. Built for long Grifball / match recordings so you can turn medal lines and other HUD text into highlight candidates.

## Quick start

1. **Install** — Windows 11, double-click **`setup.bat`** in this folder.

   It checks for Python and FFmpeg (offers to install them via `winget` if missing), detects whether you have an NVIDIA GPU, creates a `.venv\`, and installs the right PaddlePaddle build.

   Force a specific build by running from a terminal:

   ```powershell
   .\setup.bat gpu   # force CUDA 12.6 GPU wheel
   .\setup.bat cpu   # force CPU wheel
   ```

   Prefer a manual install? See [`docs/overview.md`](docs/overview.md) — short version:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements-gpu.txt   # or requirements-cpu.txt
   ```

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
   - **`Clips/<video-stem>/`** — one subfolder per source video, always. Contains the exported `.mp4` clips (when `--ffmpeg-export`) and **`<video-stem>_events.txt`**, a human-readable keyword timeline (every OCR sample with a keyword hit, deduplicated). Lines marked with `*` met the clip score threshold.

   Manual export: **`process_clips.bat`** (expects `clips.txt` + an `.mp4` in the project root — legacy single-file flow).

## Configuration

Edit **`config.json`**:

- **`killfeed_region`** — `auto` vs `manual` crop; `x_offsets` / `y_offsets`, `calibration_keywords`, `calibration_min_confidence`, `negative_substrings`.
- **`keywords`** — weights for scoring (medals, objectives, etc.).
- **`scoring`** — fuzzy OCR matching thresholds.
- **`clip_proposals`** — score threshold, pre/post roll, minimum gap between clips, and an **`annotations`** sub-block:
  - `enabled` (default `true`) — write `Clips/<video-stem>/<video-stem>_events.txt` after OCR.
  - `dedupe_window_sec` (default `5`) — collapse repeats of the same keyword that occur within this many seconds (the killfeed lingers across consecutive OCR samples).
  - `include_score` (default `true`) — append `(score N)` to each line. Lines whose event reached `score_threshold` are also tagged with a trailing `*`.
- **`pipeline`** — optional `process_all_videos` / `ffmpeg_export` defaults.

## Project layout

```
ClipProcessor/
  README.md
  config.json
  setup.bat              # First-time install (creates .venv\, picks GPU/CPU)
  requirements.txt       # Base PyPI deps
  requirements-gpu.txt   # Base + PaddlePaddle GPU (CUDA 12.6)
  requirements-cpu.txt   # Base + PaddlePaddle CPU
  process_clips.py
  run_process.bat        # One-click: process all Input/*.mp4 + FFmpeg export
  process_clips.bat      # Legacy: FFmpeg-only export from root clips.txt
  clipprocessor/         # Python package (OCR, region, scoring, export, annotations)
  docs/overview.md       # Detailed run notes, GPU, HUD calibration
  Input/                 # Drop your .mp4 files here
  Temp/                  # Generated (gitignored)
  Clips/                 # Exported clips + per-video annotation .txt (gitignored)
```

## Documentation

See **[`docs/overview.md`](docs/overview.md)** for folder layout, killfeed auto-calibration, scoring behavior, and troubleshooting.

## Requirements

- **Windows 11** (the install scripts assume `winget` is available).
- **Python 3.10+** — `setup.bat` can install Python 3.12 via `winget` if missing.
- **FFmpeg** on your PATH — `setup.bat` can install it via `winget`.
- **NVIDIA GPU (optional)** with a recent driver for the GPU PaddlePaddle wheel (CUDA 12.6). No GPU? `setup.bat` falls back to the CPU build automatically.
