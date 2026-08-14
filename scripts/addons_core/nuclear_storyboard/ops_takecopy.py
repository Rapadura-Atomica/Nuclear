"""Duplicar um take, e levar um take para outra cena.

Três operadores para dois gestos. **Duplicar** é o de todo dia: o artista tem um
plano pronto e quer o seguinte partindo dele — mesma cena, entrando logo depois,
com a arte, o tempo e a fala junto. **Copiar/colar** é o mesmo take indo para
OUTRA cena, que num board do estúdio é outra pasta e outro `project.json`: por
isso a área de transferência é um arquivo na config do Nuclear, e não uma
variável — entre o copiar e o colar passa uma troca de board.

O que a área de transferência guarda é uma REFERÊNCIA (board + id do take), não
uma cópia do take. Copiar não deve fotografar nada: entre o Ctrl+C e o Ctrl+V o
artista ainda pode desenhar mais um quadro naquele plano, e o que ele espera
colar é o plano como está na hora de colar.
"""

from __future__ import annotations

import json
from pathlib import Path

import bpy
from bpy.types import Operator

from . import state, sync, takefile
from .core import ProjectStore, StorageError
from .core.duplicate import DuplicateError, duplicate_take
from .translations import _, apply_context

CLIP_FILE = "take_clipboard.json"

#: Último conteúdo lido da área de transferência. O painel pergunta a cada
#: redesenho de que take ele fala, e ir ao disco nessa frequência sairia caro —
#: o board fica no Dropbox. Quem copia e quem cola atualizam o cache.
_CLIP = None


def _clip_path() -> Path:
    pasta = bpy.utils.user_resource("CONFIG", path="nuclear_storyboard", create=True)
    return Path(pasta) / CLIP_FILE


def read_clipboard(refresh: bool = False) -> dict:
    """{'board', 'take_id', 'code', 'scene'} do take copiado, ou {}."""
    global _CLIP
    if _CLIP is None or refresh:
        try:
            dados = json.loads(_clip_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            dados = {}
        _CLIP = dados if isinstance(dados, dict) else {}
    return _CLIP


def write_clipboard(dados: dict) -> None:
    global _CLIP
    _CLIP = dados
    try:
        _clip_path().write_text(json.dumps(dados, ensure_ascii=False, indent=2),
                                encoding="utf-8")
    except OSError:
        pass  # sem escrita na config: colar em outro board é que não vai dar


def clipboard_label() -> str:
    """`T003 · CENA01` para o botão de colar dizer o que ele cola."""
    dados = read_clipboard()
    partes = [dados.get("code", ""), dados.get("scene", "")]
    return " · ".join(p for p in partes if p)


def _save_if_on_screen(store, take) -> None:
    """Grava o take antes de copiá-lo, se for ele que está na tela.

    O `.nuc` no disco é a arte de quando foi salvo pela última vez. Duplicar sem
    isto daria uma cópia do plano de dez minutos atrás — com o artista olhando
    para os traços que faltam nela.
    """
    if takefile.is_on_screen(bpy.context.scene, take):
        takefile.save_take(store, take)


def _origin_store(dados: dict, aberto):
    """Board de onde o take copiado veio: o aberto, ou outro carregado do disco."""
    raiz = dados.get("board", "")
    if not raiz:
        return None
    if aberto is not None and str(aberto.paths.root) == str(raiz):
        return aberto
    try:
        return ProjectStore.load(Path(raiz))
    except StorageError:
        return None


class NSB_OT_duplicate_take(Operator):
    """Cria uma cópia deste plano no fim da cena, com desenho, tempo e falas"""

    bl_idname = "nsb.duplicate_take"
    bl_label = "Duplicate take"

    @classmethod
    def poll(cls, context):
        return sync.current_take(context) is not None

    def execute(self, context):
        store = state.require_store()
        take = sync.current_take(context)
        _save_if_on_screen(store, take)
        try:
            novo, perdidos = duplicate_take(store, take)
        except (DuplicateError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        store.save()
        sync.sync_all(context)
        self.report({"INFO"}, _("take duplicated") + f": {take.code} → {novo.code}")
        return {"FINISHED"}


class NSB_OT_copy_take(Operator):
    """Guarda este plano para colar em outra cena"""

    bl_idname = "nsb.copy_take"
    bl_label = "Copy take"
    bl_options = {"REGISTER", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        return sync.current_take(context) is not None

    def execute(self, context):
        store = state.require_store()
        take = sync.current_take(context)
        cena = sync.current_scene(context)
        # Salvar aqui e não no colar: quando o artista colar, este board pode
        # nem estar mais aberto — e aí não haveria como gravar a arte dele.
        _save_if_on_screen(store, take)
        write_clipboard({
            "board": str(store.paths.root),
            "take_id": take.id,
            "code": take.code,
            "scene": (cena.code or cena.name) if cena is not None else "",
        })
        self.report({"INFO"}, _("take copied") + f": {take.code}")
        return {"FINISHED"}


class NSB_OT_paste_take(Operator):
    """Põe o plano copiado no fim desta cena, com desenho, tempo e falas"""

    bl_idname = "nsb.paste_take"
    bl_label = "Paste take"

    @classmethod
    def poll(cls, context):
        return (sync.current_scene(context) is not None
                and bool(read_clipboard().get("take_id")))

    def execute(self, context):
        store = state.require_store()
        cena = sync.current_scene(context)
        dados = read_clipboard(refresh=True)

        origem = _origin_store(dados, store)
        if origem is None:
            self.report({"ERROR"}, _("the board the take was copied from is gone"))
            return {"CANCELLED"}
        achado = origem.project.find_take(dados.get("take_id", ""))
        if achado is None:
            self.report({"ERROR"}, _("the copied take is no longer in that board"))
            return {"CANCELLED"}
        take = achado[2]

        if origem is store:
            _save_if_on_screen(store, take)
        try:
            novo, perdidos = duplicate_take(origem, take, destino_store=store,
                                            destino_scene=cena)
        except (DuplicateError, OSError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        store.save()
        sync.sync_all(context)

        if perdidos:
            # Personagem ou prop que não existe na biblioteca deste board. O
            # take veio inteiro (a arte é o `.nuc`), o que ficou para trás é o
            # VÍNCULO — e é preciso dizer, senão some sem ninguém notar.
            self.report({"WARNING"},
                        _("take pasted, but these are not in this board's library")
                        + f": {', '.join(sorted(set(perdidos)))}")
        else:
            self.report({"INFO"}, _("take pasted") + f": {novo.code}")
        return {"FINISHED"}


CLASSES = (NSB_OT_duplicate_take, NSB_OT_copy_take, NSB_OT_paste_take)


def register():
    apply_context(CLASSES)
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
