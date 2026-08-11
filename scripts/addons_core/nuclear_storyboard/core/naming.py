"""Nome dos arquivos entregues: `PROJETO_EP00_C00T00`.

O padrao do estudio (decisao do usuario em 2026-08-04) e sempre esse: sigla do
projeto, episodio, cena e take, nessa ordem, com dois digitos em cada numero. E
o nome que a producao espera receber, entao ele vale tanto para o MP4 de um take
solto quanto para o animatic emendado de uma cena — nesse caso o nome para onde
o recorte termina (`DPE_EP03_C02`).

A sigla do PROJETO nao e o nome do board: o board pode se chamar
"Dragao e o Poco Encantado" e a entrega ser `DPE_...`. Ela vem de
`settings.project_code`, que o animador digita ou traz da lista de projetos do
sistema de aprovacao; vazio, cai no nome do board sanitizado, que e melhor do
que um arquivo sem identificacao.

Modulo puro (sem `bpy`): serve a UI, ao worker headless e aos testes no host.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

#: Numero + eventual sufixo de letra, em qualquer lugar do codigo:
#: "T005B" -> ("005", "B"), "SC02" -> ("02", ""), "3" -> ("3", "").
_NUMBER_RE = re.compile(r"(\d+)([A-Za-z]*)\s*$")

#: Minimo de digitos de cada numero no nome final.
DIGITS = 2


def sanitize(text: str) -> str:
    """So o que sobrevive a qualquer sistema de arquivos, sem espaco.

    Acento sai (`Dragao`, nao `Dragão`): o arquivo atravessa Dropbox, Windows e
    linha de comando de gente que nao digita acento, e `isalnum()` em Python
    aceitaria o `ã` calado.
    """
    plano = unicodedata.normalize("NFKD", text.strip())
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    out = "".join(c if c.isalnum() or c in "-_" else "_" for c in plano)
    # Underscore e o separador do padrao; deixar sobra faz `DPE__EP03`.
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


def _numbered(code: str, prefix: str) -> str:
    """`code` no formato `<prefix><numero de 2 digitos><sufixo>`.

    Take partido mantem a letra (`T005B` -> `T05B`) — e a mesma coisa que o
    codigo do board diz, so que no comprimento do padrao. Numero grande nao e
    truncado (`T123` -> `T123`): perder digito significativo trocaria um take
    por outro.

    Codigo sem numero nenhum (o artista chamou o episodio de "PILOTO") volta
    sanitizado, sem prefixo inventado.
    """
    match = _NUMBER_RE.search(code or "")
    if match is None:
        return sanitize(code).upper()
    numero, sufixo = match.group(1), match.group(2).upper()
    return f"{prefix}{int(numero):0{DIGITS}d}{sufixo}"


def project_code(project) -> str:
    """Sigla do projeto para o nome do arquivo."""
    declarado = getattr(project.settings, "project_code", "") or ""
    return sanitize(declarado).upper() or sanitize(project.name).upper() or "PROJETO"


def suggest_project_code(name: str) -> str:
    """Sigla sugerida a partir de um nome ("Dragao e o Poco Encantado" -> "DPE").

    So sugestao: quem decide e o animador, porque a sigla e combinada com a
    producao e nenhuma regra acerta sempre. Nome de uma palavra so vira as
    primeiras letras dela, que e mais util do que uma letra sozinha.
    """
    palavras = [p for p in re.split(r"[\s_\-]+", name.strip()) if p]
    # Preposicoes nao entram na sigla ("e", "o", "de", "da"...).
    grandes = [p for p in palavras if len(p) > 2 or p[0].isupper() and len(p) > 1]
    if len(grandes) >= 2:
        return "".join(p[0] for p in grandes).upper()[:8]
    if palavras:
        return sanitize(palavras[0]).upper()[:8]
    return ""


def take_basename(project, episode, scene, take) -> str:
    """`PROJETO_EP00_C00T00` — o nome de um take entregue sozinho."""
    partes = [project_code(project)]
    if episode is not None:
        partes.append(_numbered(episode.code or episode.name, "EP"))
    cena = _numbered(scene.code or scene.name, "C") if scene is not None else ""
    plano = _numbered(take.code or take.name, "T") if take is not None else ""
    # Cena e take andam colados no padrao: `C02T05`.
    if cena or plano:
        partes.append(f"{cena}{plano}")
    return "_".join(p for p in partes if p)


def scope_basename(project, episode=None, scene=None, take=None) -> str:
    """Nome do arquivo de um recorte qualquer.

    Projeto inteiro -> `DPE`; episodio -> `DPE_EP03`; cena -> `DPE_EP03_C02`;
    take -> `DPE_EP03_C02T05`. E o mesmo padrao lido de fora para dentro, o que
    faz os arquivos de uma entrega ficarem juntos na ordem certa na pasta.
    """
    if take is not None:
        return take_basename(project, episode, scene, take)
    partes = [project_code(project)]
    if episode is not None:
        partes.append(_numbered(episode.code or episode.name, "EP"))
    if scene is not None:
        partes.append(_numbered(scene.code or scene.name, "C"))
    return "_".join(p for p in partes if p)


def take_basename_by_id(project, take_id: str) -> Optional[str]:
    """Idem, achando episodio/cena pelo id do take (o worker so tem o id)."""
    achado = project.find_take(take_id)
    if achado is None:
        return None
    episode, scene, take = achado
    return take_basename(project, episode, scene, take)
