"""Cópia (aquisição) dos diretórios de mídia a partir do aparelho conectado por USB.

iOS: usa AFC via pymobiledevice3 (pip install pymobiledevice3). A raiz do AFC
é /private/var/mobile/Media, que contém DCIM/ e PhotoData/. O iPhone precisa
estar desbloqueado e ter "Confiar neste computador" aceito.

Android: usa adb (Depuração USB ativada). Sem root, só o armazenamento
compartilhado (/sdcard) é acessível.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Callable

IOS_PATHS = ["PhotoData", "DCIM"]
ANDROID_PATHS = ["/sdcard/DCIM", "/sdcard/Pictures"]


INSTALL_HINT = {
    "ios": "Instale com: pip install pymobiledevice3 (com o ambiente .venv ativado).",
    "android": "Instale com: winget install Google.PlatformTools (depois feche e abra o terminal).",
}


def check(platform: str) -> tuple[bool, str]:
    """Verifica se há um aparelho conectado e pronto. Devolve (ok, mensagem)."""
    tool = "pymobiledevice3" if platform == "ios" else "adb"
    if shutil.which(tool) is None:
        return False, f"'{tool}' não encontrado. {INSTALL_HINT[platform]}"
    cmd = [tool, "usbmux", "list"] if platform == "ios" else [tool, "devices"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=30)
    except subprocess.TimeoutExpired:
        return False, f"'{' '.join(cmd)}' não respondeu em 30 s."
    output = (proc.stdout + proc.stderr).strip()
    if platform == "ios":
        return _check_ios(proc.returncode, proc.stdout, output)
    return _check_android(proc.returncode, output)


def _check_ios(returncode: int, stdout: str, output: str) -> tuple[bool, str]:
    if returncode != 0:
        return False, ("Não foi possível falar com o serviço de dispositivos da Apple. No Windows, "
                       "instale o app Apple Devices (Microsoft Store) ou o iTunes.\n" + output)
    try:
        devices = json.loads(stdout or "[]")
    except json.JSONDecodeError:
        return False, "Resposta inesperada do pymobiledevice3:\n" + output
    if not devices:
        return False, ("Nenhum iPhone encontrado. Confira o cabo (alguns só carregam), desbloqueie o "
                       "iPhone e toque em “Confiar” quando aparecer.")
    names = [str(d.get("DeviceName") or d.get("ProductType") or d.get("Identifier") or "iPhone")
             for d in devices if isinstance(d, dict)] or ["iPhone"]
    return True, f"Conectado: {', '.join(names)}"


def _check_android(returncode: int, output: str) -> tuple[bool, str]:
    if returncode != 0:
        return False, "O adb falhou:\n" + output
    states = [line.split()[1] for line in output.splitlines()[1:] if len(line.split()) >= 2]
    if "device" in states:
        return True, f"Conectado: {states.count('device')} aparelho(s) Android."
    if "unauthorized" in states:
        return False, "Aparelho encontrado, mas não autorizado: aceite o pedido de depuração USB na tela do celular."
    return False, ("Nenhum Android encontrado. Ative Opções do desenvolvedor → Depuração USB e "
                   "use o modo de USB “Transferência de arquivos”.")


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
