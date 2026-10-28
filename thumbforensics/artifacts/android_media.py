"""Miniaturas do Android e o banco do MediaStore.

    DCIM/.thumbnails/<nome>.jpg      miniaturas soltas
    DCIM/.thumbnails/.thumbdata*     vários JPEGs concatenados (Android antigo)
    .../com.android.providers.media*/databases/external.db   MediaStore (só com root/FFS)

Com o external.db, a tabela `thumbnails` liga cada miniatura ao `image_id`
e a tabela `files` diz se a foto ainda existe — o equivalente ao cruzamento
que fazemos com o Photos.sqlite no iOS.
"""

from __future__ import annotations

import sqlite3
from pathlib import PurePosixPath

from .. import model as m
from ..carve import findings_from_blob

ARTIFACTS = {
    "android_mediastore": {
        "name": "Android — MediaStore (external.db)",
        "description": "Lê a ligação miniatura → imagem do MediaStore. Exige extração com root ou de sistema de arquivos.",
        "platform": "android",
        "paths": ("*/com.android.providers.media*/databases/external.db",
                  "*/com.google.android.providers.media*/databases/external.db"),
        "order": 10,
    },
    "android_thumbnails": {
        "name": "Android — pastas .thumbnails",
        "description": "Recupera miniaturas soltas e faz carving de JPEGs dentro de .thumbdata*.",
        "platform": "android",
        "paths": ("*/.thumbnails/*",),
        "order": 20,
    },
    "android_gallery_caches": {
        "name": "Android — caches de galerias",
        "description": "Carving de JPEGs nos caches de galerias conhecidas (Samsung, Google Fotos, Xiaomi). Exige root/FFS.",
        "platform": "android",
        "paths": ("*/com.sec.android.gallery3d/cache/*",
                  "*/com.google.android.apps.photos/cache/*",
                  "*/com.miui.gallery/cache/*"),
    },
}


def android_mediastore(ctx) -> m.Result:
    res = m.Result(headers=["Miniatura", "image_id", "Original no MediaStore"])
    store = ctx.shared.setdefault("android_mediastore", {"files": {}, "thumbs": {}})
    for rel in ctx.files:
        con = sqlite3.connect(ctx.seeker.stage(rel))
        try:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "files" in tables:
                store["files"].update(con.execute("SELECT _id, _data FROM files"))
            if "thumbnails" in tables:
                for data, image_id in con.execute("SELECT _data, image_id FROM thumbnails"):
                    if data:
                        store["thumbs"][PurePosixPath(data).name.lower()] = image_id
        finally:
            con.close()
    for name, image_id in sorted(store["thumbs"].items()):
        res.rows.append([name, image_id, store["files"].get(image_id, "— (removido)")])
    return res


def android_thumbnails(ctx) -> m.Result:
    store = ctx.shared.get("android_mediastore")
    res = m.Result()
    for rel in ctx.files:
        for f in findings_from_blob(rel, ctx.seeker.read(rel), "android"):
            if store and f.offset is None:
                image_id = store["thumbs"].get(PurePosixPath(rel).name.lower())
                if image_id is not None:
                    original = store["files"].get(image_id)
                    f.status = m.PRESENTE if original else m.ORFA
                    f.original = original or ""
                    f.note = f"image_id {image_id}"
            res.findings.append(f)
    return res


def android_gallery_caches(ctx) -> m.Result:
    res = m.Result()
    for rel in ctx.files:
        res.findings += findings_from_blob(rel, ctx.seeker.read(rel), "android")
    return res
