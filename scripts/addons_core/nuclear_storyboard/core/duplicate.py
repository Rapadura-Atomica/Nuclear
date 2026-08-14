"""Duplicar um take — e colar um take em outra cena.

Duplicar não é copiar o registro do índice: um take é um `.nuc` com a arte, os
wavs do diálogo, o timing de cada desenho e a miniatura do board. Se qualquer
uma dessas peças ficar apontando para o take de origem, os dois passam a mexer
no mesmo arquivo — desenhar num muda o outro, calado, que é o pior defeito
possível num board.

Por isso tudo que é ARQUIVO é copiado, e tudo que é IDENTIDADE é refeito: o
take, cada desenho e cada clipe nascem com id próprio. O que continua igual é o
que o artista reconhece como sendo o mesmo plano: o desenho, o tempo e a fala.

Colar em OUTRA cena traz um segundo problema: os personagens e os props são
apontados por id da biblioteca, e a biblioteca do board de destino pode ser
outra. O casamento é feito por NOME — é o que o artista lê na tela — e o que
não existe lá fica para trás, dito em voz alta em vez de virar um id órfão.

Módulo puro: recebe `ProjectStore`, mexe em disco com `shutil`, e roda no host.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Optional, Tuple

from .model import Audio, Drawing, Library, Take

#: Pasta das miniaturas do board (espelha `thumbs.THUMB_DIR`, que é do lado bpy).
THUMB_DIR = "thumbs"


class DuplicateError(Exception):
    pass


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------

def clone_take(take: Take, code: str, name: str = "") -> Take:
    """Take igual ao original, com identidade própria.

    Ids novos em cascata (take, desenhos, clipes) porque id é o que amarra a
    arte, a miniatura e o carimbo do `.nuc` ao registro: repetir um faria duas
    linhas do board disputarem o mesmo arquivo.

    O `png` de cada desenho NÃO viaja: é cache do export, regravado a cada
    entrega. Copiá-lo poria dois takes escrevendo no mesmo arquivo de saída.
    """
    novo = Take(
        code=code,
        name=name or (take.name if take.name != take.code else "") or code,
        duration_override=take.duration_override,
        character_ids=list(take.character_ids),
        prop_ids=list(take.prop_ids),
        notes=take.notes,
    )
    novo.drawings = [Drawing(name=d.name, frame=d.frame, exposure=d.exposure)
                     for d in take.drawings]
    novo.audios = [Audio(name=a.name, file=a.file, start=a.start,
                         duration=a.duration, offset=a.offset)
                   for a in take.audios]
    return novo


def remap_assets(take: Take, origem: Library, destino: Library) -> List[str]:
    """Reaponta personagens e props do take para a biblioteca de DESTINO.

    Casa por nome: é o que o artista vê, e o id é interno. Colar num board que
    divide a biblioteca do episódio — o caso normal — não muda nada, porque a
    biblioteca é literalmente a mesma. Devolve os nomes que não existem lá, para
    quem chamou poder avisar em vez de deixar um id que não resolve.
    """
    if origem is destino:
        return []
    perdidos = []
    for campo, catálogo in (("character_ids", "characters"), ("prop_ids", "props")):
        de_origem = {item.id: item.name for item in getattr(origem, catálogo)}
        por_nome = {item.name: item.id for item in getattr(destino, catálogo)}
        novos = []
        for asset_id in getattr(take, campo):
            nome = de_origem.get(asset_id)
            if nome is None:
                continue  # id que já não resolvia na origem: some junto
            equivalente = por_nome.get(nome)
            if equivalente is None:
                perdidos.append(nome)
            else:
                novos.append(equivalente)
        setattr(take, campo, novos)
    return perdidos


# ---------------------------------------------------------------------------
# Arquivos
# ---------------------------------------------------------------------------

def copy_take_files(origem_store, destino_store, take: Take, novo: Take) -> None:
    """Copia para o board de destino o que o take novo precisa ter só dele.

    O `.nuc` é a arte; os wavs são o diálogo; a miniatura é o que o board
    mostra (e é barata de copiar — regerá-la custaria abrir o arquivo).

    O `.nuc` de origem que ainda não existe no disco é um take que nunca foi
    aberto: o duplicado nasce sem arquivo e o add-on cria um em branco na
    primeira abertura, como faria com um take novo.
    """
    origem_nuc = origem_store.paths.abs(take.file) if take.file else None
    if origem_nuc is not None and origem_nuc.is_file():
        destino_nuc = destino_store.paths.abs(novo.file)
        destino_nuc.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origem_nuc, destino_nuc)

    for clipe in novo.audios:
        clipe.file = _copy_audio(origem_store, destino_store, clipe.file)

    _copy_thumb(origem_store, destino_store, take, novo)


def _copy_audio(origem_store, destino_store, relativo: str) -> str:
    """Cópia do wav dentro do board de destino; devolve o caminho relativo novo.

    Compartilhar o arquivo entre os dois takes economizaria disco e custaria
    caro no dia em que alguém abrisse o wav no editor externo: a edição de um
    plano apareceria no outro. Um wav de diálogo pesa pouco perto disso.
    """
    if not relativo:
        return relativo
    origem = origem_store.paths.abs(relativo)
    if not origem.is_file():
        return relativo  # arquivo já sumiu: o take copiado carrega o mesmo furo
    pasta = destino_store.paths.audio
    pasta.mkdir(parents=True, exist_ok=True)
    destino = _free_path(pasta / origem.name)
    shutil.copy2(origem, destino)
    return destino_store.paths.rel(destino)


def _copy_thumb(origem_store, destino_store, take: Take, novo: Take) -> None:
    origem = Path(origem_store.paths.root) / THUMB_DIR / f"{take.id}.png"
    if not origem.is_file():
        return
    destino = Path(destino_store.paths.root) / THUMB_DIR / f"{novo.id}.png"
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(origem, destino)


def _free_path(path: Path) -> Path:
    """`nome.wav` -> `nome_1.wav` enquanto estiver ocupado."""
    if not path.exists():
        return path
    i = 1
    while True:
        tentativa = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not tentativa.exists():
            return tentativa
        i += 1


# ---------------------------------------------------------------------------
# A operação inteira
# ---------------------------------------------------------------------------

def duplicate_take(origem_store, take: Take, destino_store=None,
                   destino_scene=None, after: Optional[Take] = None,
                   code: str = "") -> Tuple[Take, List[str]]:
    """Duplica o take. Devolve (take novo, nomes de asset que ficaram para trás).

    Sem `destino_store`/`destino_scene`, é a duplicação simples: mesmo board,
    mesma cena.

    O plano duplicado é **um take A MAIS**, no fim da cena, com o próximo código
    livre — numa cena de cinco planos, duplicar o segundo dá o SEXTO, e não um
    `T002B` encaixado no meio (decisão do animador em 2026-08-13). O `after` só
    é usado por quem pedir explicitamente uma posição.
    """
    destino_store = destino_store or origem_store
    if destino_scene is None:
        achado = destino_store.project.find_take(take.id)
        if achado is None:
            raise DuplicateError("o take não está neste board")
        destino_scene = achado[1]

    código = code or destino_store.free_take_code(destino_scene)
    novo = clone_take(take, código)
    novo.file = destino_store._free_take_file(código)
    if after is not None and after in destino_scene.takes:
        destino_scene.takes.insert(destino_scene.takes.index(after) + 1, novo)
    else:
        destino_scene.takes.append(novo)

    perdidos = remap_assets(novo, origem_store.library, destino_store.library)
    copy_take_files(origem_store, destino_store, take, novo)
    return novo, perdidos
