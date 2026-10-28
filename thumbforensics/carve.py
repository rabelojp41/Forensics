"""Carving de JPEGs embutidos em blobs (ex.: .thumbdata do Android)."""

from __future__ import annotations

from typing import Iterator

SOI = b"\xff\xd8\xff"
EOI = b"\xff\xd9"
MAX_JPEG = 20 * 1024 * 1024


def carve_jpegs(data: bytes, min_size: int = 512) -> Iterator[tuple[int, bytes]]:
    """Gera (offset, bytes) de cada JPEG encontrado em `data`.

    Percorre os segmentos do cabeçalho até o SOS e depois procura o EOI,
    o que evita cortar o arquivo no FFD9 de uma miniatura EXIF embutida.
    """
    pos = 0
    while True:
        start = data.find(SOI, pos)
        if start < 0:
            return
        end = _find_end(data, start)
        if end is None:
            pos = start + 3
            continue
        blob = data[start:end]
        if len(blob) >= min_size:
            yield start, blob
        pos = end


def _find_end(data: bytes, start: int) -> int | None:
    i = start + 2
    n = len(data)
    # Segmentos do cabeçalho: FFxx + tamanho de 2 bytes, até o SOS (FFDA).
    while i + 4 <= n:
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:  # bytes de preenchimento
            i += 1
            continue
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            i += 2
            continue
        seg_len = int.from_bytes(data[i + 2:i + 4], "big")
        if seg_len < 2:
            return None
        if marker == 0xDA:
            i += 2 + seg_len
            break
        i += 2 + seg_len
    else:
        return None
    # Dados entrópicos: o EOI é o primeiro FFD9 (FF00 e RSTn não são marcadores).
    end = data.find(EOI, i, start + MAX_JPEG)
    return None if end < 0 else end + 2


def findings_from_blob(rel: str, data: bytes, platform: str) -> list:
    """Um arquivo vira uma miniatura (JPEG inteiro) ou várias (carving)."""
    from . import model as m
    from .util import sha256_bytes

    carved = list(carve_jpegs(data))
    if len(carved) == 1 and carved[0][0] == 0 and not data[len(carved[0][1]):].strip(b"\x00"):
        blob = carved[0][1]
        return [m.Finding(platform=platform, source=rel, status=m.DESCONHECIDO,
                          size=len(blob), sha256=sha256_bytes(blob), data=blob)]
    return [m.Finding(platform=platform, source=rel, status=m.DESCONHECIDO, offset=off,
                      size=len(blob), sha256=sha256_bytes(blob), note="extraído por carving", data=blob)
            for off, blob in carved]
