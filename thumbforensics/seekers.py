"""Acesso somente-leitura às extrações, independente do formato de entrada.

Inspirado nos FileSeekers do iLEAPP (MIT, Alexis Brignoni): cada formato expõe
os mesmos caminhos relativos ("private/var/mobile/Media/PhotoData/...") para
que os artefatos não precisem saber de onde os bytes vêm.
"""

from __future__ import annotations

import fnmatch
import hashlib
import plistlib
import shutil
import sqlite3
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

# Domínios do backup do iTunes/Finder -> raiz no sistema de arquivos (tabela do iLEAPP).
ITUNES_DOMAINS = {
    "AppDomain-": "private/var/mobile/Containers/Data/Application",
    "AppDomainGroup-": "private/var/mobile/Containers/Shared/AppGroup",
    "AppDomainPlugin-": "private/var/mobile/Containers/Data/PluginKitPlugin",
    "CameraRollDomain": "private/var/mobile",
    "DatabaseDomain": "private/var/db",
    "HealthDomain": "private/var/mobile",
    "HomeDomain": "private/var/mobile",
    "HomeKitDomain": "private/var/mobile",
    "InstallDomain": "private/var/installd",
    "KeyboardDomain": "private/var/mobile",
    "KeychainDomain": "private/var/protected/trustd/private",
    "ManagedPreferencesDomain": "private/var/Managed Preferences",
    "MediaDomain": "private/var/mobile",
    "MobileDeviceDomain": "private/var/MobileDevice",
    "NetworkDomain": "private/var/networkd",
    "ProtectedDomain": "private/var/protected",
    "RootDomain": "private/var/root",
    "SysContainerDomain-": "private/var/containers/Data/System",
    "SysSharedContainerDomain-": "private/var/containers/Shared/SystemGroup",
    "SystemPreferencesDomain": "private/var/preferences",
    "TonesDomain": "private/var/mobile",
    "WirelessDomain": "private/var/wireless",
}


class SeekerError(Exception):
    pass


class Seeker:
    """Base: subclasses preenchem self._index {caminho relativo: chave interna} e _read_raw."""

    kind = "?"

    def __init__(self, source: Path, staging: Path):
        self.source = source
        self.staging = staging
        self._index: dict[str, object] = {}
        self._lower: dict[str, str] = {}
        self._searched: dict[str, list[str]] = {}
        self.hashes: dict[str, str] = {}  # todo arquivo lido -> SHA-256

    def _finish_index(self) -> None:
        self._lower = {rel.lower(): rel for rel in self._index}

    def __len__(self) -> int:
        return len(self._index)

    def search(self, pattern: str) -> list[str]:
        """Padrão glob sem diferenciar maiúsculas. '*' atravessa '/', como no iLEAPP."""
        if pattern not in self._searched:
            pat = pattern.lower()
            if not pat.startswith(("*", "/")):
                pat = "*/" + pat
            self._searched[pattern] = sorted(
                orig for low, orig in self._lower.items() if fnmatch.fnmatchcase("/" + low, pat))
        return self._searched[pattern]

    def exists(self, rel: str) -> bool:
        return rel.lower() in self._lower

    def read(self, rel: str) -> bytes:
        data = self._read_raw(self._index[self._lower.get(rel.lower(), rel)])
        self.hashes.setdefault(rel, hashlib.sha256(data).hexdigest())
        return data

    def stage(self, rel: str) -> Path:
        """Copia para a área de trabalho (com -wal/-shm, se houver) e devolve o caminho local."""
        dest = self.staging / PurePosixPath(rel)
        for suffix in ("", "-wal", "-shm"):
            sib = rel + suffix
            if suffix and not self.exists(sib):
                continue
            target = dest.with_name(dest.name + suffix)
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(self.read(sib))
        return dest

    def _read_raw(self, key) -> bytes:
        raise NotImplementedError

    def close(self) -> None:
        pass


class DirSeeker(Seeker):
    kind = "pasta"

    def __init__(self, source: Path, staging: Path):
        super().__init__(source, staging)
        for p in source.rglob("*"):
            if p.is_file() and not p.is_symlink():
                self._index[p.relative_to(source).as_posix()] = p
        self._finish_index()

    def _read_raw(self, key) -> bytes:
        return key.read_bytes()


class ZipSeeker(Seeker):
    kind = "zip"

    def __init__(self, source: Path, staging: Path):
        super().__init__(source, staging)
        self._zf = zipfile.ZipFile(source)
        for info in self._zf.infolist():
            if not info.is_dir():
                self._index[info.filename.lstrip("/")] = info
        self._finish_index()

    def _read_raw(self, key) -> bytes:
        return self._zf.read(key)

    def close(self) -> None:
        self._zf.close()


class TarSeeker(Seeker):
    kind = "tar"

    def __init__(self, source: Path, staging: Path):
        super().__init__(source, staging)
        self._tf = tarfile.open(source)
        for member in self._tf.getmembers():
            if member.isfile():
                self._index[member.name.removeprefix("./").lstrip("/")] = member
        self._finish_index()

    def _read_raw(self, key) -> bytes:
        return self._tf.extractfile(key).read()

    def close(self) -> None:
        self._tf.close()


class ItunesSeeker(Seeker):
    """Backup local do iTunes/Finder (Manifest.db). Backups criptografados não são suportados."""

    kind = "backup iTunes"

    def __init__(self, source: Path, staging: Path):
        super().__init__(source, staging)
        manifest_plist = source / "Manifest.plist"
        if manifest_plist.is_file():
            with open(manifest_plist, "rb") as fh:
                if plistlib.load(fh).get("IsEncrypted"):
                    raise SeekerError(
                        "Backup criptografado: este app não descriptografa. Use o iLEAPP "
                        "(que pede a senha) ou gere um backup sem senha só para a análise.")
        db = staging / "_manifest" / "Manifest.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / "Manifest.db", db)
        con = sqlite3.connect(db)
        try:
            for file_id, domain, rel_path in con.execute(
                    "SELECT fileID, domain, relativePath FROM Files WHERE flags = 1"):
                root = _domain_root(domain)
                full = f"{root}/{rel_path}" if root else f"{domain}/{rel_path}"
                self._index[full] = source / file_id[:2] / file_id
        finally:
            con.close()
        self._finish_index()

    def _read_raw(self, key) -> bytes:
        return key.read_bytes()


def _domain_root(domain: str) -> str:
    if domain in ITUNES_DOMAINS:
        return ITUNES_DOMAINS[domain]
    if "-" in domain:
        prefix, bundle = domain.split("-", 1)
        base = ITUNES_DOMAINS.get(prefix + "-")
        if base:
            return f"{base}/{bundle}"
    return ""


def detect(source: Path) -> str | None:
    """Tipo de entrada, sem indexar: 'backup', 'pasta', 'zip', 'tar' ou None."""
    if source.is_dir():
        return "backup" if (source / "Manifest.db").is_file() else "pasta"
    if source.is_file():
        if zipfile.is_zipfile(source):
            return "zip"
        if tarfile.is_tarfile(source):
            return "tar"
    return None


def open_source(source: Path, staging: Path) -> Seeker:
    """Detecta o tipo de entrada, como o '-t' do iLEAPP, mas automaticamente."""
    kind = detect(source)
    seeker = {"backup": ItunesSeeker, "pasta": DirSeeker, "zip": ZipSeeker, "tar": TarSeeker}.get(kind)
    if seeker is None:
        raise SeekerError(f"Formato de entrada não reconhecido: {source}")
    return seeker(source, staging)
