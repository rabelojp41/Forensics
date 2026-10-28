"""Exportação dos achados: arquivos recuperados, HTML, CSV, JSON e cadeia de custódia."""

from __future__ import annotations

import csv
import html
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from . import model as m


def export(findings: list[m.Finding], out: Path, source_root: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    rec = out / "recuperados"
    for i, f in enumerate(findings, 1):
        if f.data is None:
            continue
        name = f"{i:05d}_{Path(f.original or f.source).name}"
        if f.offset is not None:
            name += f"_off{f.offset}"
        dest = rec / f.status / (name + ".jpg")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(f.data)
        f.exported = dest.relative_to(out).as_posix()

    rows = [_row(f) for f in findings]
    with open(out / "relatorio.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["status"])
        w.writeheader()
        w.writerows(rows)
    (out / "relatorio.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "relatorio.html").write_text(_html(findings, source_root), encoding="utf-8")
    (out / "custodia.txt").write_text(_custody(findings, source_root), encoding="utf-8")


def _row(f: m.Finding) -> dict:
    return {
        "status": f.status, "plataforma": f.platform, "origem": f.source,
        "offset": "" if f.offset is None else f.offset, "original": f.original,
        "tamanho": f.size, "sha256": f.sha256, "exportado": f.exported, "nota": f.note,
    }


def summary(findings: list[m.Finding]) -> list[tuple[str, int]]:
    c = Counter(f.status for f in findings)
    return [(s, c[s]) for s in m.STATUS_ORDEM if c[s]]


def _custody(findings: list[m.Finding], root: Path) -> str:
    lines = [
        f"thumbforensics {__version__}",
        f"Data (UTC): {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Origem: {root.resolve()}",
        f"Comando: {' '.join(sys.argv)}",
        "A origem foi aberta apenas para leitura; bancos SQLite foram copiados antes de abrir.",
        "",
        "Resumo:",
    ]
    lines += [f"  {s}: {n}" for s, n in summary(findings)]
    lines += ["", "SHA-256 de cada item (origem[@offset] -> exportado):"]
    for f in findings:
        at = "" if f.offset is None else f"@{f.offset}"
        lines.append(f"{f.sha256}  {f.source}{at} -> {f.exported or '-'}")
    return "\n".join(lines) + "\n"


CSS = """
:root{--bg:#fafaf9;--fg:#1c1917;--muted:#78716c;--card:#fff;--line:#e7e5e4;--accent:#b91c1c}
@media (prefers-color-scheme:dark){:root{--bg:#1c1917;--fg:#f5f5f4;--muted:#a8a29e;--card:#292524;--line:#44403c;--accent:#f87171}}
body{margin:0;padding:24px 16px;font:14px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg)}
h1{font-size:20px;margin:0 0 4px} h2{font-size:16px;margin:28px 0 8px} p.m{color:var(--muted);margin:0}
table.s{border-collapse:collapse;margin-top:12px} table.s td{padding:2px 12px 2px 0}
.g{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}
.c{background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden;font-size:12px}
.c img{width:100%;aspect-ratio:1;object-fit:cover;display:block;background:var(--line)}
.c div{padding:6px 8px;word-break:break-all} .c small{color:var(--muted)}
.orfa h2{color:var(--accent)}
"""


def _html(findings: list[m.Finding], root: Path) -> str:
    e = html.escape
    parts = [
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>",
        f"<title>Relatório de miniaturas</title><style>{CSS}</style>",
        "<h1>Relatório de miniaturas</h1>",
        f"<p class=m>Origem: {e(str(root.resolve()))} · {e(datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))}</p>",
        "<table class=s>",
    ]
    parts += [f"<tr><td>{e(m.STATUS_DESCRICAO[s])}</td><td><b>{n}</b></td></tr>" for s, n in summary(findings)]
    parts.append("</table>")
    for status in m.STATUS_ORDEM:
        group = [f for f in findings if f.status == status]
        if not group:
            continue
        parts.append(f"<section class={e(status)}><h2>{e(m.STATUS_DESCRICAO[status])} ({len(group)})</h2><div class=g>")
        for f in group:
            img = f"<img loading=lazy src='{e(f.exported)}' alt=''>" if f.exported else ""
            title = f.original or f.source
            off = "" if f.offset is None else f" @ {f.offset}"
            parts.append(
                f"<div class=c>{img}<div>{e(title)}<br><small>{e(f.source + off)}<br>"
                f"{e(f.note)}<br>sha256 {e(f.sha256[:16])}…</small></div></div>")
        parts.append("</div></section>")
    return "\n".join(parts)
