"""Análise do cache de miniaturas do app Fotos do iOS.

Estrutura (iOS 12+), relativa a /private/var/mobile/Media:

    PhotoData/Photos.sqlite                          banco da fototeca
    PhotoData/Thumbnails/V2/DCIM/100APPLE/IMG_0001.HEIC/5005.JPG
                            └── caminho do original ──┘ └ tamanho
    PhotoData/Thumbnails/*.ithmb                     caches em pixels brutos

Uma miniatura cujo original não está no disco nem no Photos.sqlite é
uma "órfã": o forte indício de que a foto foi apagada.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path

from . import model as m
from .util import find_dirs, looks_like_jpeg, sha256_bytes, sha256_file


def scan(root: Path) -> list[m.Finding]:
    findings: list[m.Finding] = []
    for photodata in find_dirs(root, "PhotoData"):
        media = photodata.parent
        assets = load_assets(photodata / "Photos.sqlite")
        findings += _scan_v2(root, media, photodata, assets)
        findings += _scan_ithmb(root, photodata)
    return findings


def load_assets(db: Path) -> dict[tuple[str, str], bool] | None:
    """Lê o Photos.sqlite: {(diretório, arquivo) em minúsculas: está_na_lixeira}.

    O banco é copiado (com -wal/-shm) para um diretório temporário antes de
    ser aberto, para nunca alterar a evidência original.
    """
    if not db.is_file():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / db.name
        for suffix in ("", "-wal", "-shm"):
            src = db.with_name(db.name + suffix)
            if src.is_file():
                shutil.copy2(src, Path(tmp) / src.name)
        con = sqlite3.connect(copy)
        try:
            return _query_assets(con)
        except sqlite3.DatabaseError:
            return None
        finally:
            con.close()


def _query_assets(con: sqlite3.Connection) -> dict[tuple[str, str], bool] | None:
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    # ZASSET no iOS 14+, ZGENERICASSET no iOS 11–13.
    table = next((t for t in ("ZASSET", "ZGENERICASSET") if t in tables), None)
    if table is None:
        return None
    cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    trashed = "ZTRASHEDSTATE" if "ZTRASHEDSTATE" in cols else "0"
    assets = {}
    for directory, filename, state in con.execute(
            f"SELECT ZDIRECTORY, ZFILENAME, {trashed} FROM {table}"):
        if filename:
            assets[((directory or "").lower(), filename.lower())] = bool(state)
    return assets


def _scan_v2(root: Path, media: Path, photodata: Path,
             assets: dict[tuple[str, str], bool] | None) -> list[m.Finding]:
    v2 = photodata / "Thumbnails" / "V2"
    if not v2.is_dir():
        return []
    findings = []
    for thumb in sorted(v2.rglob("*")):
        if not thumb.is_file():
            continue
        data = thumb.read_bytes()
        if not looks_like_jpeg(data):
            continue
        rel_original = thumb.parent.relative_to(v2)  # ex.: DCIM/100APPLE/IMG_0001.HEIC
        directory = rel_original.parent.as_posix()
        filename = rel_original.name
        findings.append(m.Finding(
            platform="ios",
            source=thumb.relative_to(root).as_posix(),
            status=_status(media / rel_original, directory, filename, assets),
            original=rel_original.as_posix(),
            size=len(data),
            sha256=sha256_bytes(data),
            note=f"miniatura {thumb.stem}",
            data=data,
        ))
    return findings


def _status(original: Path, directory: str, filename: str,
            assets: dict[tuple[str, str], bool] | None) -> str:
    on_disk = original.exists()
    if assets is None:
        return m.PRESENTE if on_disk else m.SEM_ORIGINAL
    key = (directory.lower(), filename.lower())
    if key in assets:
        if assets[key]:
            return m.LIXEIRA
        return m.PRESENTE if on_disk else m.SO_MINIATURA
    return m.PRESENTE if on_disk else m.ORFA


def _scan_ithmb(root: Path, photodata: Path) -> list[m.Finding]:
    thumbs = photodata / "Thumbnails"
    if not thumbs.is_dir():
        return []
    return [
        m.Finding(
            platform="ios",
            source=p.relative_to(root).as_posix(),
            status=m.NAO_DECODIFICADO,
            size=p.stat().st_size,
            sha256=sha256_file(p),
            note="pixels brutos sem cabeçalho; dimensões dependem da versão do iOS",
        )
        for p in sorted(thumbs.glob("*.ithmb"))
    ]
