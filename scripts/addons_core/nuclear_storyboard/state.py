"""Estado vivo do add-on: qual projeto esta aberto neste processo.

O `ProjectStore` e a fonte da verdade. As PropertyGroups do Blender sao apenas
um ESPELHO para a UI desenhar listas — quem escreve nelas e o `sync.py`, nunca
o usuario direto. Isso evita ter dois donos do mesmo dado.
"""

from __future__ import annotations

from typing import Optional

from .core import ProjectStore

_store: Optional[ProjectStore] = None


def get_store() -> Optional[ProjectStore]:
    return _store


def set_store(store: Optional[ProjectStore]) -> None:
    global _store
    _store = store


def require_store() -> ProjectStore:
    if _store is None:
        raise RuntimeError("nenhum projeto de storyboard aberto")
    return _store


def has_project() -> bool:
    return _store is not None


#: O que a PASTA revelou sobre este board na hora de abrir: trabalho escondido
#: num board aninhado, identidade que destoa das cenas vizinhas. Fica guardado
#: porque descobrir isso e VARRER O DISCO — o `draw()` de um painel roda a cada
#: redesenho, e a pasta costuma estar no Dropbox.
_notes: list = []


def set_board_notes(notes) -> None:
    global _notes
    _notes = list(notes or [])


def board_notes() -> list:
    """[(codigo, mensagem)] do que se achou na pasta ao abrir o board."""
    return list(_notes)
