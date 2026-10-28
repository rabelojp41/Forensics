"""Exportação: mídias recuperadas, tabelas, HTML, JSON e cadeia de custódia."""

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
from .engine import Session


def export(session: Session, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for run in session.runs:
        if not run.result:
            continue
        for f in run.result.findings:
            n += 1
            if f.data is None:
                continue
            name = f"{n:05d}_{Path(f.original or f.source).name}"
            if f.offset is not None:
                name += f"_off{f.offset}"
            dest = out / "recuperados" / f.status / (name + ".jpg")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(f.data)
            f.exported = dest.relative_to(out).as_posix()
        if run.result.rows:
            tdir = out / "tabelas"
            tdir.mkdir(exist_ok=True)
            with open(tdir / f"{run.plugin.key}.csv", "w", newline="", encoding="utf-8-sig") as fh:  # BOM: Excel no Windows
                w = csv.writer(fh)
                w.writerow(run.result.headers)
                w.writerows(run.result.rows)

    rows = [dict(artefato=r.plugin.key, **_row(f)) for r in session.runs if r.result for f in r.result.findings]
    (out / "relatorio.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "relatorio.html").write_text(_html(session), encoding="utf-8")
    (out / "custodia.txt").write_text(_custody(session), encoding="utf-8")


def _row(f: m.Finding) -> dict:
    return {
        "status": f.status, "plataforma": f.platform, "origem": f.source,
        "offset": "" if f.offset is None else f.offset, "original": f.original,
        "tamanho": f.size, "sha256": f.sha256, "exportado": f.exported, "nota": f.note,
    }


def summary(findings: list[m.Finding]) -> list[tuple[str, int]]:
    c = Counter(f.status for f in findings)
    return [(s, c[s]) for s in m.STATUS_ORDEM if c[s]]


def _custody(session: Session) -> str:
    s = session.seeker
    lines = [
        f"thumbforensics {__version__}",
        f"Data (UTC): {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Origem: {s.source.resolve()} ({s.kind}, {len(s)} arquivos indexados)",
        f"Comando: {' '.join(sys.argv)}",
        "A origem foi lida apenas para leitura; bancos SQLite foram copiados antes de abrir.",
        "",
        "Artefatos:",
    ]
    for r in session.runs:
        state = "ERRO" if r.error else ("ok" if r.result else "sem arquivos")
        lines.append(f"  {r.plugin.key}: {state} ({len(r.files)} arquivo(s))")
    lines += ["", "SHA-256 de cada arquivo lido da origem:"]
    lines += [f"{h}  {rel}" for rel, h in sorted(s.hashes.items())]
    lines += ["", "SHA-256 de cada item recuperado (origem[@offset] -> exportado):"]
    for f in session.findings:
        at = "" if f.offset is None else f"@{f.offset}"
        lines.append(f"{f.sha256}  {f.source}{at} -> {f.exported or '-'}")
    return "\n".join(lines) + "\n"


CSS = """
:root{--bg:#fafaf9;--fg:#1c1917;--muted:#78716c;--card:#fff;--line:#e7e5e4;--accent:#b91c1c}
@media (prefers-color-scheme:dark){:root{--bg:#1c1917;--fg:#f5f5f4;--muted:#a8a29e;--card:#292524;--line:#44403c;--accent:#f87171}}
body{margin:0;padding:24px 16px;font:14px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg);max-width:1200px}
h1{font-size:20px;margin:0 0 4px} h2{font-size:17px;margin:32px 0 4px} h3{font-size:14px;margin:16px 0 8px}
p.m{color:var(--muted);margin:0} .err{color:var(--accent);white-space:pre-wrap;font-size:12px}
table{border-collapse:collapse;font-size:12px} td,th{padding:3px 10px 3px 0;text-align:left;border-bottom:1px solid var(--line)}
.scroll{overflow-x:auto;max-height:420px;overflow-y:auto}
.g{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}
.c{background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden;font-size:12px}
.c img{width:100%;aspect-ratio:1;object-fit:cover;display:block;background:var(--line)}
.c div{padding:6px 8px;word-break:break-all} .c small{color:var(--muted)}
h3.orfa{color:var(--accent)}
"""


def _html(session: Session) -> str:
    e = html.escape
    s = session.seeker
    parts = [
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>",
        f"<title>Relatório forense</title><style>{CSS}</style>",
        "<h1>Relatório forense</h1>",
        f"<p class=m>Origem: {e(str(s.source.resolve()))} ({e(s.kind)}) · "
        f"{e(datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))}</p>",
        "<table style='margin-top:12px'>",
    ]
    parts += [f"<tr><td>{e(m.STATUS_DESCRICAO[st])}</td><td><b>{n}</b></td></tr>"
              for st, n in summary(session.findings)]
    parts.append("</table>")
    for r in session.runs:
        if not r.files:
            continue
        parts.append(f"<h2>{e(r.plugin.name)}</h2><p class=m>{e(r.plugin.description)} · {len(r.files)} arquivo(s)</p>")
        if r.error:
            parts.append(f"<p class=err>{e(r.error)}</p>")
            continue
        res = r.result
        if res.rows:
            parts.append("<div class=scroll><table><tr>" + "".join(f"<th>{e(h)}</th>" for h in res.headers) + "</tr>")
            parts += ["<tr>" + "".join(f"<td>{e(str(v))}</td>" for v in row) + "</tr>" for row in res.rows]
            parts.append("</table></div>")
        for status in m.STATUS_ORDEM:
            group = [f for f in res.findings if f.status == status]
            if not group:
                continue
            parts.append(f"<h3 class={e(status)}>{e(m.STATUS_DESCRICAO[status])} ({len(group)})</h3><div class=g>")
            for f in group:
                img = f"<img loading=lazy src='{e(f.exported)}' alt=''>" if f.exported else ""
                off = "" if f.offset is None else f" @ {f.offset}"
                parts.append(f"<div class=c>{img}<div>{e(f.original or f.source)}<br><small>"
                             f"{e(f.source + off)}<br>{e(f.note)}<br>sha256 {e(f.sha256[:16])}…</small></div></div>")
            parts.append("</div>")
    return "\n".join(parts)
