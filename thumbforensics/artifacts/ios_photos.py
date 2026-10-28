"""Fototeca do iOS: Photos.sqlite e cache de miniaturas.

    PhotoData/Photos.sqlite                                    banco da fototeca
    PhotoData/Thumbnails/V2/DCIM/100APPLE/IMG_0001.HEIC/5005.JPG
                            └── caminho do original ──┘
    PhotoData/Thumbnails/*.ithmb                               pixels brutos

Consultas adaptadas das ideias do módulo Ph003 do iLEAPP (Scott Koenig).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from .. import model as m
from ..util import sha256_bytes

ARTIFACTS = {
    "ios_photos_assets": {
        "name": "Fotos — itens do Photos.sqlite",
        "description": "Lista os itens da fototeca, com data de criação e estado de lixeira "
                       "(ZASSET no iOS 14+, ZGENERICASSET no iOS 11–13).",
        "platform": "ios",
        "paths": ("*/PhotoData/Photos.sqlite",),
        "order": 10,
    },
    "ios_thumbnails_v2": {
        "name": "Fotos — miniaturas (Thumbnails/V2)",
        "description": "Recupera as miniaturas e as cruza com o disco e o Photos.sqlite para "
                       "identificar fotos apagadas (órfãs).",
        "platform": "ios",
        "paths": ("*/PhotoData/Thumbnails/V2/*",),
        "order": 20,
    },
    "ios_ithmb": {
        "name": "Fotos — caches .ithmb",
        "description": "Lista os caches em pixels brutos (não decodificados) com hash.",
        "platform": "ios",
        "paths": ("*/PhotoData/Thumbnails/*.ithmb",),
    },
}

COCOA_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
V2 = "photodata/thumbnails/v2/"


def cocoa(ts) -> str:
    if ts in (None, ""):
        return ""
    try:
        return (COCOA_EPOCH + timedelta(seconds=float(ts))).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, OverflowError):
        return str(ts)


def ios_photos_assets(ctx) -> m.Result:
    res = m.Result(headers=["Banco", "Diretório", "Arquivo", "Criado em", "Na lixeira", "Para a lixeira em"])
    libraries = ctx.shared.setdefault("ios_assets", {})
    for rel in ctx.files:
        prefix = rel[:rel.lower().rfind("photodata/photos.sqlite")]
        con = sqlite3.connect(ctx.seeker.stage(rel))
        try:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            table = next((t for t in ("ZASSET", "ZGENERICASSET") if t in tables), None)
            if table is None:
                continue
            cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
            pick = [c if c in cols else "NULL" for c in
                    ("ZDIRECTORY", "ZFILENAME", "ZDATECREATED", "ZTRASHEDSTATE", "ZTRASHEDDATE")]
            assets = {}
            for directory, filename, created, trashed, trashed_at in con.execute(
                    f"SELECT {', '.join(pick)} FROM {table} ORDER BY ZDATECREATED" if "ZDATECREATED" in cols
                    else f"SELECT {', '.join(pick)} FROM {table}"):
                if not filename:
                    continue
                assets[((directory or "").lower(), filename.lower())] = bool(trashed)
                res.rows.append([rel, directory or "", filename, cocoa(created),
                                 "sim" if trashed else "", cocoa(trashed_at) if trashed else ""])
            libraries[prefix] = assets
        finally:
            con.close()
    return res


def ios_thumbnails_v2(ctx) -> m.Result:
    res = m.Result()
    libraries = ctx.shared.get("ios_assets", {})
    for rel in ctx.files:
        cut = rel.lower().find(V2)
        prefix, inner = rel[:cut], rel[cut + len(V2):]
        if inner.count("/") < 1:
            continue
        data = ctx.seeker.read(rel)
        if data[:3] != b"\xff\xd8\xff":
            continue
        original = inner.rsplit("/", 1)[0]          # ex.: DCIM/100APPLE/IMG_0001.HEIC
        directory, _, filename = original.rpartition("/")
        res.findings.append(m.Finding(
            platform="ios", source=rel, original=original, size=len(data), sha256=sha256_bytes(data),
            status=_status(ctx.seeker.exists(prefix + original), directory, filename, libraries.get(prefix)),
            note=f"miniatura {inner.rsplit('/', 1)[1]}", data=data))
    return res


def _status(on_disk: bool, directory: str, filename: str, assets: dict | None) -> str:
    if assets is None:
        return m.PRESENTE if on_disk else m.SEM_ORIGINAL
    key = (directory.lower(), filename.lower())
    if key in assets:
        if assets[key]:
            return m.LIXEIRA
        return m.PRESENTE if on_disk else m.SO_MINIATURA
    return m.PRESENTE if on_disk else m.ORFA


def ios_ithmb(ctx) -> m.Result:
    res = m.Result()
    for rel in ctx.files:
        data = ctx.seeker.read(rel)
        res.findings.append(m.Finding(
            platform="ios", source=rel, status=m.NAO_DECODIFICADO, size=len(data),
            sha256=sha256_bytes(data), note="pixels brutos sem cabeçalho; dimensões dependem da versão do iOS"))
    return res
