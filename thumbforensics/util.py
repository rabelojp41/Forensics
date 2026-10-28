from __future__ import annotations

import hashlib
import os
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".gif", ".webp",
              ".mov", ".mp4", ".dng", ".tif", ".tiff", ".bmp", ".3gp"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_dirs(root: Path, name: str) -> list[Path]:
    """Todos os diretórios chamados `name` (sem diferenciar maiúsculas) sob root."""
    lname = name.lower()
    hits = []
    for dirpath, dirnames, _ in os.walk(root):
        for d in dirnames:
            if d.lower() == lname:
                hits.append(Path(dirpath) / d)
    return hits


def looks_like_jpeg(data: bytes) -> bool:
    return data[:3] == b"\xff\xd8\xff"
