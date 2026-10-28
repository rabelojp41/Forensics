"""Cópia (aquisição) dos diretórios de mídia a partir do aparelho conectado por USB.

iOS: usa AFC via pymobiledevice3 (pip install pymobiledevice3). A raiz do AFC
é /private/var/mobile/Media, que contém DCIM/ e PhotoData/. O iPhone precisa
estar desbloqueado e ter "Confiar neste computador" aceito.

Android: usa adb (Depuração USB ativada). Sem root, só o armazenamento
compartilhado (/sdcard) é acessível.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable

IOS_PATHS = ["PhotoData", "DCIM"]
ANDROID_PATHS = ["/sdcard/DCIM", "/sdcard/Pictures"]


def commands(platform: str, dest: Path) -> list[list[str]]:
    if platform == "ios":
        return [["pymobiledevice3", "afc", "pull", f"/{p}", str(dest)] for p in IOS_PATHS]
    return [["adb", "pull", "-a", p, str(dest)] for p in ANDROID_PATHS]


def run(platform: str, dest: Path, dry_run: bool = False, log: Callable[[str], None] = print) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    cmds = commands(platform, dest)
    tool = cmds[0][0]
    if dry_run or shutil.which(tool) is None:
        if not dry_run:
            log(f"'{tool}' não encontrado no PATH. Instale-o e rode:")
        for c in cmds:
            log("  " + " ".join(c))
        return 0 if dry_run else 1
    failures = 0
    for c in cmds:
        log("$ " + " ".join(c))
        # Saída linha a linha, para a interface gráfica mostrar o progresso.
        proc = subprocess.Popen(c, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
        for line in proc.stdout:
            log(line.rstrip())
        if proc.wait() != 0:
            failures += 1
            log("Falhou (o caminho pode não existir neste aparelho); seguindo.")
    return 1 if failures == len(cmds) else 0
