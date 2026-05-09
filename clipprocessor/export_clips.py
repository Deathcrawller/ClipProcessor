from __future__ import annotations

import os
import subprocess

from .fs import ensure_dir


def export_clips_from_txt(*, video_path: str, clips_txt_path: str, output_dir: str) -> int:
    """
    Cut clips with FFmpeg using the same row format as clips.txt:
    START|END|basename|title (title optional).
    Returns the number of clips written.
    """
    ensure_dir(output_dir)
    n = 0
    with open(clips_txt_path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) < 3:
                continue
            start, end, base = parts[0].strip(), parts[1].strip(), parts[2].strip()
            title = parts[3].strip() if len(parts) > 3 else "VOD clip"
            if not base:
                continue
            out_path = os.path.join(output_dir, f"{base}.mp4")
            cmd = [
                "ffmpeg",
                "-y",
                "-ss",
                start,
                "-to",
                end,
                "-i",
                video_path,
                "-c",
                "copy",
                "-metadata",
                f"title={title}",
                "-metadata",
                f"comment={title}",
                out_path,
            ]
            subprocess.run(cmd, check=True)
            n += 1
    return n


def ffmpeg_available() -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
