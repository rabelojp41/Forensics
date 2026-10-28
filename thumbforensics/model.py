from __future__ import annotations

from dataclasses import dataclass, field

# Status de cada miniatura em relação à foto original.
ORFA = "orfa"                # original não existe no disco nem no banco: forte indício de exclusão
LIXEIRA = "lixeira"          # original está em "Apagados" (iOS ZTRASHEDSTATE=1)
SO_MINIATURA = "so_miniatura"  # está no banco, mas o original não está no disco (ex.: iCloud "Otimizar")
SEM_ORIGINAL = "sem_original"  # original ausente no disco e não há banco para confirmar
PRESENTE = "presente"        # original ainda existe
DESCONHECIDO = "desconhecido"  # não há como ligar a miniatura a um original
NAO_DECODIFICADO = "nao_decodificado"  # cache em formato bruto (ex.: .ithmb)

STATUS_DESCRICAO = {
    ORFA: "Órfã: original ausente do disco e do banco (provavelmente apagada)",
    LIXEIRA: "Na lixeira (Apagados Recentemente)",
    SO_MINIATURA: "Só miniatura: o banco conhece a foto, mas o original não está no aparelho (ex.: iCloud otimizado)",
    SEM_ORIGINAL: "Original ausente (sem banco para confirmar)",
    PRESENTE: "Original ainda presente",
    DESCONHECIDO: "Sem vínculo com um original",
    NAO_DECODIFICADO: "Cache bruto não decodificado",
}

STATUS_ORDEM = [ORFA, LIXEIRA, SEM_ORIGINAL, SO_MINIATURA, DESCONHECIDO, PRESENTE, NAO_DECODIFICADO]


@dataclass
class Finding:
    platform: str               # "ios" | "android"
    source: str                 # caminho relativo à raiz da extração
    status: str
    original: str = ""          # caminho do original inferido (quando houver)
    offset: int | None = None   # deslocamento quando o JPEG foi extraído por carving
    size: int = 0
    sha256: str = ""
    note: str = ""
    data: bytes | None = field(default=None, repr=False)
    exported: str = ""          # caminho relativo no diretório de saída


@dataclass
class Result:
    """O que um artefato devolve: uma tabela e/ou mídias recuperadas."""
    headers: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
