"""Comparação visual opcional (dHash) entre miniaturas e originais. Requer Pillow."""

from __future__ import annotations

import io
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
    px = small.tobytes()
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return bits


def index_originals(seeker) -> list[tuple[int, str]]:
    index = []
    for rel in seeker.search("*/DCIM/*"):
        low = rel.lower()
        if any(f"/{d}/" in "/" + low for d in SKIP_DIRS) or Path(low).suffix not in PIL_EXTS:
            continue
        try:
            with Image.open(io.BytesIO(seeker.read(rel))) as img:
                index.append((dhash(img), rel))
        except Exception:
            continue
    return index


def resolve(findings: list[m.Finding], seeker, max_distance: int = 6) -> int:
    """Marca como PRESENTE as miniaturas cujo original aparece com outro nome. Retorna quantas."""
    index = index_originals(seeker)
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
