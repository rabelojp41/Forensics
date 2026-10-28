"""Comparação visual opcional (dHash) entre miniaturas e originais. Requer Pillow."""

from __future__ import annotations

import io
import os
from pathlib import Path

from . import model as m

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

UNRESOLVED = {m.DESCONHECIDO, m.ORFA, m.SEM_ORIGINAL}
SKIP_DIRS = {"photodata", ".thumbnails", ".thumbs"}
PIL_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff"}


def available() -> bool:
    return Image is not None


def dhash(img: "Image.Image") -> int:
    small = img.convert("L").resize((9, 8))
    px = list(small.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return bits


def index_originals(root: Path) -> list[tuple[int, str]]:
    index = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS]
        for name in filenames:
            p = Path(dirpath) / name
            if p.suffix.lower() not in PIL_EXTS:
                continue
            try:
                with Image.open(p) as img:
                    index.append((dhash(img), p.relative_to(root).as_posix()))
            except Exception:
                continue
    return index


def resolve(findings: list[m.Finding], root: Path, max_distance: int = 6) -> int:
    """Marca como PRESENTE as miniaturas cujo original aparece com outro nome. Retorna quantas."""
    index = index_originals(root)
    matched = 0
    for f in findings:
        if f.status not in UNRESOLVED or not f.data or not index:
            continue
        try:
            with Image.open(io.BytesIO(f.data)) as img:
                h = dhash(img)
        except Exception:
            continue
        dist, path = min((bin(h ^ oh).count("1"), op) for oh, op in index)
        if dist <= max_distance:
            f.note = (f.note + "; " if f.note else "") + f"parecida com {path} (dHash {dist})"
            f.status = m.PRESENTE
            matched += 1
    return matched
