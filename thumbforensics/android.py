"""Análise de caches de miniaturas do Android.

Locais comuns no armazenamento compartilhado (/sdcard):

    DCIM/.thumbnails/<id>.jpg           miniaturas do MediaStore (id do banco)
    DCIM/.thumbnails/.thumbdata*        vários JPEGs concatenados (Android antigo)
    Pictures/.thumbnails/...

Caches de galerias de fabricantes (ex.: Samsung) ficam em
Android/data/<pacote>/cache e só aparecem em extrações com root ou
de sistema de arquivos completo; passe-os com --carve.

Sem o banco do MediaStore (external.db, exige root) não há como ligar
<id>.jpg ao original, então o status fica "desconhecido" — a menos que
--phash encontre o original por semelhança visual.
"""

from __future__ import annotations

from pathlib import Path

from . import model as m
from .carve import carve_jpegs
from .util import find_dirs, sha256_bytes

THUMB_DIRS = (".thumbnails", ".thumbs", ".Thumbs")


def scan(root: Path) -> list[m.Finding]:
    findings: list[m.Finding] = []
    seen: set[Path] = set()
    for name in THUMB_DIRS:
        for d in find_dirs(root, name):
            if d.resolve() in seen:
                continue
            seen.add(d.resolve())
            findings += scan_dir(root, d)
    return findings


def scan_dir(root: Path, directory: Path, platform: str = "android") -> list[m.Finding]:
    """Varre um diretório: JPEGs soltos são lidos inteiros; o resto passa por carving."""
    findings = []
    for f in sorted(directory.rglob("*")):
        if not f.is_file():
            continue
        data = f.read_bytes()
        rel = f.relative_to(root).as_posix()
        carved = list(carve_jpegs(data))
        if len(carved) == 1 and carved[0][0] == 0 and not data[len(carved[0][1]):].strip(b"\x00"):
            blob = carved[0][1]
            findings.append(m.Finding(platform=platform, source=rel, status=m.DESCONHECIDO,
                                      size=len(blob), sha256=sha256_bytes(blob), data=blob))
            continue
        for offset, blob in carved:
            findings.append(m.Finding(platform=platform, source=rel, status=m.DESCONHECIDO,
                                      offset=offset, size=len(blob), sha256=sha256_bytes(blob),
                                      note="extraído por carving", data=blob))
    return findings
