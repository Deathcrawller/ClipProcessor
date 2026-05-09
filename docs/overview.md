# ClipProcessor (V1)

## Goal
Automatically generate highlight clips from long Grifball match videos by combining multiple signals over time:

- Killfeed OCR (visual)
- Transcript (text)
- Audio peaks (sound)
- (Later) LLM ranking for final clip selection

V1 implements **Killfeed OCR + keyword scoring** and produces:

- `Temp/ocr_events.json` (debuggable timeline of OCR results and scores; per-video subfolders when batching)
- `clips.txt` (FFmpeg clip list compatible with `process_clips.bat`)

**Default:** `python process_clips.py` processes **one** video — the first `*.mp4` sorted by name in `Input/`, or in the project root if `Input/` is empty. **Multiple files:** use `python process_clips.py --all-videos` (every `Input/*.mp4`, sorted). With more than one file, outputs go under `Temp/<video-stem>/` and exported clips under `Clips/<video-stem>/`. A single file in `Input/` with `--all-videos` still uses the flat `Temp/ocr_events.json` and root `clips.txt` layout.

## Folder layout

```
ClipProcessor/
  process_clips.py
  run_process.bat
  process_clips.bat
  config.json
  requirements.txt
  Input/
    <video>.mp4
    <video>.vtt  (future)
  Temp/
    ocr_events.json
    <video-stem>/   (batch: ocr_events.json, clips.txt, …)
  Clips/
    (exported clips; batch: one subfolder per source video)
```

## Run

1. Install dependencies:

```bash
pip install -r requirements.txt
```

### GPU notes (Windows)

This project is configured for **PaddlePaddle GPU (CUDA 12.6)** by default via the `--index-url` line in `requirements.txt`.

- We also pin `nvidia-cudnn-cu12` to avoid cuDNN runtime mismatches on Windows.

- Verify your GPU is visible: `nvidia-smi`
- Verify Paddle sees CUDA:

```bash
python -c "import paddle; print(paddle.__version__); print(paddle.is_compiled_with_cuda()); print(paddle.device.get_device())"
```

2. Put an `*.mp4` in `Input/` (or in the project root).

3. Run OCR + scoring:

```bash
python process_clips.py
```

Outputs:
- `Temp/ocr_events.json` (includes `killfeed_calibration` when `mode` is `auto`)
- `Temp/killfeed_calibration.json` (only when using automatic region detection)
- `clips.txt` (overwrites by default)

4. Export clips with FFmpeg:
- Double click `process_clips.bat` (Windows) after step 3, **or**
- Double click **`run_process.bat`** to run **`python process_clips.py --all-videos --ffmpeg-export`** in one step (all `Input/*.mp4`, then FFmpeg). Requires `ffmpeg` on your PATH.

Optional **`config.json` → `pipeline`:** set **`process_all_videos`** / **`ffmpeg_export`** to `true` so a plain `python process_clips.py` run does the same without passing flags (CLI flags still override if you pass them).

`clips.txt` lines are **`START|END|basename|title`**: VOD in/out as `HH:MM:SS`, **basename** becomes `Clips\<basename>.mp4` (includes compact VOD time, e.g. `VOD003252`), **title** is written into the MP4 as FFmpeg **`title`** and **`comment`** metadata so players and Windows file properties can show when the highlight occurred.

## Killfeed crop: manual vs auto

`killfeed_region.mode` can be:

- **`relative`** — You set `x`, `y`, `w`, `h` as fractions of the frame (same on any resolution).
- **`auto`** — Samples the video over `probe_start_sec` … `probe_duration_sec`, OCR-scores candidate boxes, and picks the best match using your `keywords` list. If the score is below `min_calibration_score`, it falls back to the optional `manual` block (same shape as a normal relative region).

**HUD safe zone:** In games like Halo Infinite the killfeed can sit anywhere from **flush-left** to **near-center** depending on the streamer’s HUD settings. Auto mode tries multiple **`auto.x_offsets`** (fractions of frame width from the left) so one run can still find the feed when horizontal position changes between streams (increase this if your killfeed is closer to center).

If auto picks a bad region, add menu strings to `auto.negative_substrings`, widen **`x_offsets`**, or set **`auto.candidates`** to your own list of `{x,y,w,h}` boxes to try.

If auto gives **all-zero candidate scores**, it often means OCR saw text but the confidence was below your global `ocr.min_confidence`. In that case set `killfeed_region.auto.calibration_min_confidence` lower (for example `0.35`) so calibration can still find the right crop; the main OCR loop still uses `ocr.min_confidence`.

If auto keeps picking **radar / spectating / respawn UI** instead of the killfeed, add those strings to `auto.negative_substrings` and adjust `auto.y_offsets` upward (your killfeed is usually higher than the bottom-left HUD text).

If auto still reports **all-zero candidate scores**, it can simply mean your `keywords` rarely appear during the probe window (for example, the killfeed only shows `X killed Y` and you’re not using `killed` as a keyword). In that case, set `killfeed_region.auto.calibration_keywords` to include lightweight terms like `killed` / `kill` so the crop can lock onto the killfeed area, while keeping your main `keywords` list focused on highlight events.

## Config (manual crop)

When `mode` is `relative`, set fractions `x,y,w,h` in `[0..1]`.

## Scoring (fuzzy OCR)

Fuzzy matching uses `rapidfuzz` **partial_ratio** so typos like `OvERKILi` still match `overkill`. That score is misleading when the OCR line is very short: the same metric returns a perfect match if the line equals a tiny substring of a long keyword (for example `ni` inside `running`, or `z` in `frenzy`). To block those, fuzzy hits require the OCR text length to be at least **`fuzzy_min_haystack_chars`** and at least **`fuzzy_min_haystack_ratio`** × (keyword length without spaces), rounded up. Tune those keys under `scoring` in `config.json` if you see misses on very short but valid lines.
