"""Operações de alto nível, compartilhadas pela linha de comando e pela interface gráfica."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Iterable

from . import engine, phash, plugins, report
from . import model as m
from .seekers import SeekerError, open_source

Log = Callable[[str], None]


class AnalysisError(Exception):
    pass


def select(available: dict, keys: Iterable[str] | None = None, platform: str = "auto") -> list:
    chosen = list(available.values())
    if keys:
        keys = list(keys)
        unknown = [k for k in keys if k not in available]
        if unknown:
            raise AnalysisError(f"Artefato(s) desconhecido(s): {', '.join(unknown)}")
        chosen = [available[k] for k in keys]
    if platform != "auto":
        chosen = [pl for pl in chosen if pl.platform in (platform, "any")]
    return chosen


def analyze(src: Path, out: Path, chosen: list, use_phash: bool = False, log: Log = print) -> engine.Session:
    if not src.exists():
        raise AnalysisError(f"Origem não encontrada: {src}")
    if src.is_dir() and out.resolve().is_relative_to(src.resolve()):
        raise AnalysisError("A saída não pode ficar dentro da origem (não misture evidência e resultado).")
    if not chosen:
        raise AnalysisError("Nenhum artefato selecionado.")

    work = out / "_trabalho"
    try:
        seeker = open_source(src, work)
    except SeekerError as ex:
        raise AnalysisError(str(ex)) from ex
    log(f"Origem: {seeker.kind}, {len(seeker)} arquivos indexados; {len(chosen)} artefato(s).")
    try:
        session = engine.run(seeker, chosen, log=log)
        if use_phash:
            if phash.available():
                log(f"dHash: {phash.resolve(session.findings, seeker)} miniatura(s) ligadas a um original existente.")
            else:
                log("Comparação visual ignorada: instale Pillow (pip install Pillow).")
        report.export(session, out)
    finally:
        seeker.close()
        shutil.rmtree(work, ignore_errors=True)

    log(f"{len(session.findings)} item(ns) recuperados.")
    for status, n in report.summary(session.findings):
        log(f"  {n:6d}  {m.STATUS_DESCRICAO[status]}")
    log(f"Relatório: {out / 'relatorio.html'}")
    return session
