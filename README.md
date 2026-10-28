# thumbforensics

Ferramenta de linha de comando para **encontrar e recuperar miniaturas (thumbnails) de fotos** — inclusive de fotos já apagadas — em extrações de **iOS e Android**, com relatório HTML/CSV/JSON e registro de hashes SHA-256 para cadeia de custódia.

Python 3.9+, sem dependências obrigatórias (Pillow é opcional, para `--phash`).

> Use apenas em aparelhos seus ou com autorização legal. Acessar o dispositivo de outra pessoa sem consentimento é crime (no Brasil, Lei 12.737/2012).

## O que ela faz (e o que não faz)

- **Recupera miniaturas**, não as fotos originais. A resolução é baixa (no iOS, em geral algumas centenas de pixels).
- **Não acessa o celular sozinha**: o aparelho precisa estar plugado por USB no seu computador para a etapa `adquirir`.
- **Não quebra proteções**: só lê o que o iOS (via AFC) ou o Android (via adb, sem root) já expõem a um computador confiável.

## Instalação

```bash
git clone https://github.com/rabelojp41/forensics.git
cd forensics
pip install -e ".[phash]"     # ou só: pip install -e .
```

Para a aquisição:

- **iPhone:** `pip install pymobiledevice3`. Desbloqueie o aparelho e toque em "Confiar neste computador".
- **Android:** instale o `adb` (Android Platform Tools) e ative **Opções do desenvolvedor → Depuração USB**.

## Uso

### 1. Copiar os dados do aparelho (celular plugado por USB)

```bash
thumbforensics adquirir ios casos/iphone
thumbforensics adquirir android casos/android
```

Use `--simular` para ver os comandos sem executá-los. No iOS são copiados `/PhotoData` e `/DCIM` (a raiz do AFC é `/private/var/mobile/Media`). No Android, `/sdcard/DCIM` e `/sdcard/Pictures`.

Você também pode usar uma extração feita por outra ferramenta (iMazing, extração de sistema de arquivos completa, etc.): basta apontar para a pasta que contém `PhotoData/`, `DCIM/`, etc.

### 2. Analisar

A entrada pode ser uma **pasta**, um **.zip**, um **.tar/.tar.gz** ou a **pasta de um backup local do iTunes/Finder**. O tipo é detectado automaticamente.

```bash
thumbforensics analisar casos/iphone -o saida-iphone
thumbforensics analisar ~/Library/Application\ Support/MobileSync/Backup/<UDID> -o saida-backup
thumbforensics analisar extracao_ffs.zip -o saida --phash
thumbforensics analisar casos/android -o saida --artefatos android_thumbnails,android_mediastore
thumbforensics listar
```

A origem nunca é alterada. Bancos SQLite são copiados (com `-wal`/`-shm`) para uma área temporária antes de abrir, e essa área é apagada no fim.

Backups **criptografados** não são suportados: use o iLEAPP, que pede a senha, ou gere um backup sem senha só para a análise.

Saída:

| Arquivo | Conteúdo |
|---|---|
| `relatorio.html` | Uma seção por artefato: tabela e galeria por status |
| `relatorio.json` | Uma linha por mídia recuperada |
| `tabelas/<artefato>.csv` | Tabelas (ex.: itens do `Photos.sqlite` com data de exclusão) |
| `recuperados/<status>/` | JPEGs extraídos |
| `custodia.txt` | Data, comando, estado de cada artefato, SHA-256 de **todo arquivo lido** e de cada item recuperado |

## Arquitetura (inspirada no iLEAPP)

```
cli.py ──► seekers.py ──► plugins.py ──► engine.py ──► report.py
           │               │               │
           │               │               └ roda em ordem ("order"), compartilha dados
           │               │                 entre artefatos (ctx.shared) e isola erros
           │               └ descobre artifacts/*.py e --plugins DIR em tempo de execução
           └ pasta | zip | tar | backup iTunes: todos expõem os mesmos caminhos
             (ex.: private/var/mobile/Media/PhotoData/Photos.sqlite)
```

| Artefato | O que faz |
|---|---|
| `ios_photos_assets` | Itens do `Photos.sqlite` com data de criação e de envio à lixeira; publica a lista para o próximo |
| `ios_thumbnails_v2` | Miniaturas cruzadas com o disco e o banco → órfãs, lixeira, só miniatura |
| `ios_ithmb` | Caches brutos `.ithmb` (só hash) |
| `android_mediastore` | `external.db`: liga miniatura → `image_id` → original (exige root/FFS) |
| `android_thumbnails` | `.thumbnails/` e carving de `.thumbdata*`; usa o MediaStore se houver |
| `android_gallery_caches` | Carving nos caches de galerias Samsung/Google Fotos/Xiaomi (root/FFS) |

### Escrevendo um plugin

Crie um `.py` numa pasta qualquer e rode com `--plugins pasta/`. Não é preciso mexer no código do app:

```python
from thumbforensics.model import Result

ARTIFACTS = {
    "whatsapp_midia": {                       # = nome da função
        "name": "WhatsApp — mídia",
        "description": "Lista arquivos de mídia do WhatsApp",
        "platform": "ios",                    # ios | android | any
        "paths": ("*/Message/Media/*",),      # globs; '*' atravessa '/'
        "order": 50,                          # opcional
    },
}

def whatsapp_midia(ctx):
    rows = [[rel, len(ctx.seeker.read(rel))] for rel in ctx.files]
    return Result(headers=["arquivo", "bytes"], rows=rows)
```

O `ctx` traz `files` (caminhos que casaram), `seeker` (`read`, `stage`, `exists`, `search`) e `shared` (dados de artefatos anteriores). Chaves duplicadas são rejeitadas. Uma exceção num plugin aparece no relatório sem interromper os demais.

## Como cada miniatura é classificada

| Status | Significado |
|---|---|
| `orfa` | O original não está no disco nem no banco (`Photos.sqlite` no iOS, `external.db` no Android). É o indício mais forte de foto apagada. |
| `lixeira` | Está em "Apagados Recentemente" (`ZTRASHEDSTATE = 1`). |
| `so_miniatura` | O banco conhece a foto, mas o original não está no aparelho. Geralmente é o **iCloud com "Otimizar armazenamento"**, e não uma exclusão. |
| `sem_original` | Original ausente e não há banco para confirmar. |
| `desconhecido` | Não há como ligar a miniatura a um original. É o caso normal no Android sem root, já que o `external.db` do MediaStore fica fora do alcance do adb. |
| `presente` | O original ainda existe (pelo caminho ou, com `--phash`, por semelhança visual). |
| `nao_decodificado` | Arquivos `.ithmb` do iOS: pixels brutos, listados e com hash, mas não convertidos em imagem. |

## Onde ficam os caches

**iOS** (`/private/var/mobile/Media`)

- `PhotoData/Thumbnails/V2/<caminho do original>/<tamanho>.JPG`: o nome da pasta é o caminho do original, o que permite cruzar com o `Photos.sqlite`.
- `PhotoData/Photos.sqlite`: tabela `ZASSET` (iOS 14+) ou `ZGENERICASSET` (iOS 11–13).
- `PhotoData/Thumbnails/*.ithmb`.

**Android** (`/sdcard`)

- `DCIM/.thumbnails/*.jpg` e `.thumbdata*`: vários JPEGs concatenados, extraídos por *carving*.
- `external.db` do MediaStore e caches de galerias em `Android/data/<pacote>/cache`: só em extrações com root ou de sistema de arquivos completo.
- Em Android 10+ (armazenamento com escopo), boa parte dos caches deixou de ficar no `/sdcard`, então espere menos resultados.

## O post viral: o que é verdade e o que não é

- ✅ **Miniaturas de fotos apagadas podem persistir** em `PhotoData/Thumbnails`. Esse é um artefato conhecido na perícia de iOS.
- ❌ **"É um cache do Spotlight":** não é. É o cache de miniaturas do app Fotos, indexado pelo `Photos.sqlite`.
- ❌ **"Apps com acesso a Arquivos e Pastas no iPhone podem ler esse cache":** no iOS não existe essa permissão. Cada app roda em sandbox, e o acesso à fototeca (PhotoKit) entrega só as fotos da biblioteca, não esse cache. "Arquivos e Pastas" é uma permissão do **macOS**.
- ⚠️ **O risco real fica no computador.** Backups não criptografados do iPhone (`~/Library/Application Support/MobileSync/Backup` no Mac) podem ser lidos por qualquer programa com acesso ao disco. Ative **"Criptografar backup local"** no Finder/iTunes.
- ⚠️ **"Tudo que aparece sem original foi apagado":** falso positivo comum. Com o iCloud otimizando o armazenamento, o original fica na nuvem e só a miniatura fica no aparelho. Por isso existe o status `so_miniatura`.

## Ferramentas maduras para comparar

- [iLEAPP](https://github.com/abrignoni/iLEAPP) e [ALEAPP](https://github.com/abrignoni/ALEAPP): parsers forenses open source de iOS e Android, muito mais abrangentes.
- Ferramentas comerciais (Cellebrite, Magnet AXIOM) fazem extrações completas que o AFC/adb não alcançam.

Este projeto é focado e didático. Para casos reais, valide os resultados com ferramentas estabelecidas.

## Créditos

A arquitetura (seekers, plugins declarativos, encadeamento e isolamento de erros) e a tabela de domínios do backup do iTunes foram adaptadas do [iLEAPP](https://github.com/abrignoni/iLEAPP), de Alexis Brignoni e colaboradores, sob licença MIT. As consultas ao `Photos.sqlite` seguem as ideias dos módulos de Scott Koenig no mesmo projeto.

## Testes

```bash
python -m unittest discover -s tests -v
```
