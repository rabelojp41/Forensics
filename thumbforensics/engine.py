"""Executa os artefatos sobre uma extração."""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field

from .model import Result
from .plugins import Plugin
from .seekers import Seeker


@dataclass
class Context:
    seeker: Seeker
    files: list[str]
    shared: dict
    plugin: Plugin


@dataclass
class Run:
    plugin: Plugin
    files: list[str]
    result: Result | None = None
    error: str = ""


@dataclass
class Session:
    seeker: Seeker
    runs: list[Run] = field(default_factory=list)
    shared: dict = field(default_factory=dict)

    @property
    def findings(self):
        return [f for r in self.runs if r.result for f in r.result.findings]


def run(seeker: Seeker, plugins: list[Plugin], log=print) -> Session:
    session = Session(seeker)
    for plugin in sorted(plugins, key=lambda p: (p.order, p.key)):
        files = sorted({f for pat in plugin.paths for f in seeker.search(pat)})
        r = Run(plugin, files)
        session.runs.append(r)
        if not files:
            continue
        log(f"[{plugin.key}] {len(files)} arquivo(s)")
        try:
            r.result = plugin.func(Context(seeker, files, session.shared, plugin)) or Result()
        except Exception:
            # Como no iLEAPP: um artefato que falha não interrompe os demais.
            r.error = traceback.format_exc()
            log(f"[{plugin.key}] ERRO — veja o relatório")
    return session
