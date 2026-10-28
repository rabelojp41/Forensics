from __future__ import annotations

import argparse
from pathlib import Path

from . import __version__, acquire, android, ios, phash, report
from . import model as m


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="thumbforensics", description=(
        "Encontra miniaturas de fotos (inclusive de fotos apagadas) em extrações de iOS e Android."))
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("adquirir", help="copia DCIM/PhotoData do aparelho conectado por USB")
    a.add_argument("plataforma", choices=["ios", "android"])
    a.add_argument("destino", type=Path)
    a.add_argument("--simular", action="store_true", help="só mostra os comandos")

    s = sub.add_parser("analisar", help="analisa uma extração e gera o relatório")
    s.add_argument("origem", type=Path, help="pasta da extração (contendo PhotoData/, DCIM/, ...)")
    s.add_argument("-o", "--saida", type=Path, required=True)
    s.add_argument("--plataforma", choices=["ios", "android", "auto"], default="auto")
    s.add_argument("--carve", type=Path, action="append", default=[],
                   help="pasta extra para carving de JPEGs (ex.: cache de galeria); pode repetir")
    s.add_argument("--phash", action="store_true",
                   help="compara visualmente com os originais para reduzir falsos positivos (requer Pillow)")

    args = p.parse_args(argv)
    if args.cmd == "adquirir":
        return acquire.run(args.plataforma, args.destino, args.simular)
    return _analyze(args)


def _analyze(args) -> int:
    root: Path = args.origem
    if not root.is_dir():
        print(f"Pasta não encontrada: {root}")
        return 2
    if args.saida.resolve().is_relative_to(root.resolve()):
        print("A saída não pode ficar dentro da origem (não misture evidência e resultado).")
        return 2

    findings: list[m.Finding] = []
    if args.plataforma in ("ios", "auto"):
        findings += ios.scan(root)
    if args.plataforma in ("android", "auto"):
        findings += android.scan(root)
    for extra in args.carve:
        findings += android.scan_dir(extra.parent, extra, platform="carving")

    if args.phash:
        if phash.available():
            n = phash.resolve(findings, root)
            print(f"dHash: {n} miniatura(s) ligadas a um original existente.")
        else:
            print("--phash ignorado: instale Pillow (pip install Pillow).")

    report.export(findings, args.saida, root)
    print(f"{len(findings)} item(ns) encontrados.")
    for status, n in report.summary(findings):
        print(f"  {n:6d}  {m.STATUS_DESCRICAO[status]}")
    print(f"Relatório: {args.saida / 'relatorio.html'}")
    return 0
