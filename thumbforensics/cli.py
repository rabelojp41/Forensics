from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from . import __version__, acquire, engine, phash, plugins, report
from . import model as m
from .seekers import SeekerError, open_source


def main(argv: list[str] | None = None) -> int:
    # Terminais sem UTF-8 (ex.: saída redirecionada no Windows) não devem derrubar o programa.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    p = argparse.ArgumentParser(prog="thumbforensics", description=(
        "Recupera miniaturas de fotos (inclusive apagadas) e artefatos de fototeca em extrações de iOS e Android."))
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("adquirir", help="copia DCIM/PhotoData do aparelho conectado por USB")
    a.add_argument("plataforma", choices=["ios", "android"])
    a.add_argument("destino", type=Path)
    a.add_argument("--simular", action="store_true", help="só mostra os comandos")

    ls = sub.add_parser("listar", help="lista os artefatos disponíveis (inclusive plugins externos)")
    ls.add_argument("--plugins", type=Path, action="append", default=[])

    s = sub.add_parser("analisar", help="analisa uma extração e gera o relatório")
    s.add_argument("origem", type=Path, help="pasta, .zip, .tar(.gz) ou pasta de backup do iTunes/Finder")
    s.add_argument("-o", "--saida", type=Path, required=True)
    s.add_argument("--plataforma", choices=["ios", "android", "auto"], default="auto")
    s.add_argument("--artefatos", help="lista separada por vírgula (veja 'listar'); padrão: todos")
    s.add_argument("--plugins", type=Path, action="append", default=[],
                   help="pasta com plugins .py extras; pode repetir")
    s.add_argument("--phash", action="store_true",
                   help="compara visualmente com os originais para reduzir falsos positivos (requer Pillow)")

    args = p.parse_args(argv)
    if args.cmd == "adquirir":
        return acquire.run(args.plataforma, args.destino, args.simular)
    if args.cmd == "listar":
        for pl in sorted(plugins.load(args.plugins).values(), key=lambda x: (x.platform, x.order, x.key)):
            print(f"{pl.key:28} {pl.platform:8} {pl.name}\n{'':38}{pl.description}")
        return 0
    return _analyze(args)


def _select(available: dict, args) -> list:
    chosen = list(available.values())
    if args.artefatos:
        keys = [k.strip() for k in args.artefatos.split(",") if k.strip()]
        unknown = [k for k in keys if k not in available]
        if unknown:
            raise SystemExit(f"Artefato(s) desconhecido(s): {', '.join(unknown)}")
        chosen = [available[k] for k in keys]
    if args.plataforma != "auto":
        chosen = [pl for pl in chosen if pl.platform in (args.plataforma, "any")]
    return chosen


def _analyze(args) -> int:
    src: Path = args.origem
    if not src.exists():
        print(f"Origem não encontrada: {src}")
        return 2
    if src.is_dir() and args.saida.resolve().is_relative_to(src.resolve()):
        print("A saída não pode ficar dentro da origem (não misture evidência e resultado).")
        return 2

    chosen = _select(plugins.load(args.plugins), args)
    work = args.saida / "_trabalho"
    try:
        seeker = open_source(src, work)
    except SeekerError as ex:
        print(ex)
        return 2
    print(f"Origem: {seeker.kind}, {len(seeker)} arquivos indexados; {len(chosen)} artefato(s).")
    try:
        session = engine.run(seeker, chosen)
        if args.phash:
            if phash.available():
                print(f"dHash: {phash.resolve(session.findings, seeker)} miniatura(s) ligadas a um original existente.")
            else:
                print("--phash ignorado: instale Pillow (pip install Pillow).")
        report.export(session, args.saida)
    finally:
        seeker.close()
        shutil.rmtree(work, ignore_errors=True)

    print(f"{len(session.findings)} item(ns) recuperados.")
    for status, n in report.summary(session.findings):
        print(f"  {n:6d}  {m.STATUS_DESCRICAO[status]}")
    print(f"Relatório: {args.saida / 'relatorio.html'}")
    return 0
