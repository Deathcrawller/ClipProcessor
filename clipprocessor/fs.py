from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

_INVALID_STEM = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass(frozen=True)
class ProjectPaths:
    root: str
    input_dir: str
    temp_dir: str
    clips_dir: str

    def input_path(self, *parts: str) -> str:
        return os.path.join(self.input_dir, *parts)

    def temp_path(self, *parts: str) -> str:
        return os.path.join(self.temp_dir, *parts)

    def clips_path(self, *parts: str) -> str:
        return os.path.join(self.clips_dir, *parts)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def read_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str, data: Any) -> None:
    ensure_dir(os.path.dirname(path) or ".")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def safe_video_stem(filename: str) -> str:
    """Folder-safe stem from a video filename (no extension)."""
    base = os.path.splitext(os.path.basename(filename))[0]
    s = _INVALID_STEM.sub("_", base).strip(" .")
    return s or "video"


def list_input_videos(input_dir: str) -> list[str]:
    """All .mp4 files directly under input_dir, sorted by name."""
    if not os.path.isdir(input_dir):
        return []
    names = sorted(
        n for n in os.listdir(input_dir) if n.lower().endswith(".mp4")
    )
    return [os.path.join(input_dir, n) for n in names]


def find_first_video(root: str, input_dir: str) -> Optional[str]:
    """
    Find the first .mp4 in Input/ if present, otherwise in the root.
    Order is sorted by filename within each folder.
    """
    for base in (os.path.join(root, input_dir), root):
        if not os.path.isdir(base):
            continue
        names = sorted(
            n for n in os.listdir(base) if n.lower().endswith(".mp4")
        )
        if names:
            return os.path.join(base, names[0])
    return None

