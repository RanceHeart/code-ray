from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple


LANG_MAP: Dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".java": "java",
    ".swift": "swift",
    ".m": "objective-c",
    ".mm": "objective-c",
    ".h": "objective-c",
    ".json": "json",
    ".toml": "toml",
    ".yml": "yaml",
    ".yaml": "yaml",
}

DEFAULT_EXCLUDES: Set[str] = {
    ".git",
    "node_modules",
    "dist",
    "build",
    ".venv",
    "venv",
    "__pycache__",
    ".next",
    ".nuxt",
}

ASSET_EXTS: Set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".mp4", ".mov", ".mp3", ".wav",
    ".zip", ".gz", ".7z", ".pdf",
}


@dataclass
class FileInfo:
    path: str
    lang: str
    size: int
    lines: int


def _to_posix(p: str) -> str:
    return p.replace(os.sep, "/")


def _count_lines(abs_path: str) -> int:
    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def scan_project(
    root: str,
    exclude: Optional[List[str]] = None,
    max_files: Optional[int] = None,
    max_bytes: Optional[int] = None,
) -> List[FileInfo]:
    root = os.path.abspath(root)
    excluded = set(DEFAULT_EXCLUDES)
    if exclude:
        excluded.update(exclude)

    out: List[FileInfo] = []
    count = 0

    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        dirnames[:] = [d for d in dirnames if d not in excluded and not d.startswith(".")]

        for fn in filenames:
            if max_files is not None and count >= max_files:
                dirnames.clear()
                break

            abs_path = os.path.join(dirpath, fn)
            try:
                rel = os.path.relpath(abs_path, root)
            except ValueError:
                continue
            rel = _to_posix(rel)

            ext = Path(fn).suffix.lower()
            if ext in ASSET_EXTS:
                continue

            try:
                size = os.path.getsize(abs_path)
            except OSError:
                size = 0

            if max_bytes is not None and size > max_bytes:
                continue

            lang = LANG_MAP.get(ext, "other")
            lines = 0 if lang == "other" else _count_lines(abs_path)

            out.append(FileInfo(path=rel, lang=lang, size=size, lines=lines))
            count += 1

    # prioritize large-ish source files for summary ordering later
    return out
