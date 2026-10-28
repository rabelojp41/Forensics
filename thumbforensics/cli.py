from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, acquire, api, plugins


def main(argv: list[str] | None = None) -> int:
    # Terminais sem UTF-8 (ex.: saída redirecionada no Windows) não devem derrubar o programa.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    p = argparse.ArgumentParser(prog="thumbforensics", description=(
        "Recupera miniaturas de fotos (inclusive apagadas) e artefatos de fototeca em extrações de iOS e Android."))
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("gui", help="abre a interface gráfica")

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
    if args.cmd == "gui":
        from . import gui
        return gui.main()
    if args.cmd == "adquirir":
        return acquire.run(args.plataforma, args.destino, args.simular)
    if args.cmd == "listar":
        for pl in sorted(plugins.load(args.plugins).values(), key=lambda x: (x.platform, x.order, x.key)):
            print(f"{pl.key:28} {pl.platform:8} {pl.name}\n{'':38}{pl.description}")
        return 0
    return _analyze(args)


def _analyze(args) -> int:
    try:
        chosen = api.select(plugins.load(args.plugins),
                            args.artefatos.split(",") if args.artefatos else None, args.plataforma)
        api.analyze(args.origem, args.saida, chosen, args.phash)
    except api.AnalysisError as ex:
        print(ex)
        return 2
    return 0
