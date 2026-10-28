"""Descoberta dinâmica de artefatos (plugins), no estilo do plugin_loader do iLEAPP.

Cada módulo em thumbforensics/artifacts/ — ou numa pasta passada com
--plugins — declara um dicionário ARTIFACTS:

    ARTIFACTS = {
        "nome_da_funcao": {
            "name": "Nome legível",
            "description": "O que o artefato extrai",
            "platform": "ios" | "android" | "any",
            "paths": ("*/PhotoData/Photos.sqlite",),   # globs; '*' atravessa '/'
            "order": 10,           # opcional: menor roda antes (para encadear)
        },
    }

    def nome_da_funcao(ctx) -> Result: ...

A função recebe um Context com ctx.files (caminhos que casaram), ctx.seeker
(para ler bytes) e ctx.shared (dados publicados por artefatos anteriores).
"""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import artifacts as builtin

REQUIRED = ("name", "description", "platform", "paths")


@dataclass(frozen=True)
class Plugin:
    key: str
    name: str
    description: str
    platform: str
    paths: tuple[str, ...]
    order: int
    func: Callable
    module: str


def load(extra_dirs: list[Path] = ()) -> dict[str, Plugin]:
    modules = [importlib.import_module(f"{builtin.__name__}.{m.name}")
               for m in pkgutil.iter_modules(builtin.__path__)]
    for d in extra_dirs:
        for py in sorted(Path(d).glob("*.py")):
            spec = importlib.util.spec_from_file_location(f"plugin_externo_{py.stem}", py)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            modules.append(mod)

    plugins: dict[str, Plugin] = {}
    for mod in modules:
        for key, info in getattr(mod, "ARTIFACTS", {}).items():
            missing = [f for f in REQUIRED if f not in info]
            if missing:
                raise ValueError(f"{mod.__name__}.{key}: faltam campos {missing}")
            if key in plugins:
                raise ValueError(f"Artefato duplicado '{key}' em {mod.__name__} e {plugins[key].module}")
            func = getattr(mod, key, None)
            if not callable(func):
                raise ValueError(f"{mod.__name__}: função '{key}' não encontrada")
            plugins[key] = Plugin(key=key, name=info["name"], description=info["description"],
                                  platform=info["platform"], paths=tuple(info["paths"]),
                                  order=info.get("order", 50), func=func, module=mod.__name__)
    return plugins
