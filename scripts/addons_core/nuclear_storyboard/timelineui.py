"""A duração do take se muda na timeline, onde ela é vista.

Antes ela morava num diálogo do painel "Mais opções" — três cliques longe do
lugar em que o artista percebe que o plano está curto, que é olhando a timeline
tocar. Agora são duas coisas, as duas no canto direito da timeline (embaixo, na
tela do storyboard):

- um campo com os segundos do take, ao lado do "End" do Nuclear;
- o próprio "End": arrastar o fim da cena PASSA A SER a duração do take.

O "End" funciona porque a cena de um take existe para caber nele — quem escreve
`frame_end` é `audiotl.apply_take_range`, a partir da duração. Fechar o círculo
custa uma comparação: só vira ajuste manual quando o fim pedido difere, EM
FRAMES, do que a duração calculada daria. Sem isso, o arredondamento de um
diálogo de 2,53s (61 frames) voltaria como 2,5417s e congelaria o take, que
nunca mais acompanharia o áudio.
"""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent

from . import state

#: Dono das assinaturas de msgbus — o Blender as descarta por este objeto.
_OWNER = object()


def take_on_screen():
    """(store, take) do take aberto no arquivo, ou (store, None)."""
    from . import takefile

    store = state.get_store()
    if store is None:
        return None, None
    return store, takefile.current_take_of_file(store)


# ---------------------------------------------------------------------------
# O fim da cena vira a duração do take
# ---------------------------------------------------------------------------

def _on_frame_end(*_args):
    """`frame_end` mudou na timeline: se não foi a gente, é ordem do artista."""
    from . import sync, takefile
    from .core import take_duration
    from .core.timing import seconds_to_frames

    try:
        context = bpy.context
        scene = getattr(context, "scene", None)
        store, take = take_on_screen()
        if scene is None or take is None or not takefile.is_on_screen(scene, take):
            return
        fps = store.project.settings.fps
        if seconds_to_frames(take_duration(take), fps) == scene.frame_end:
            return  # o fim já corresponde ao take: quem escreveu foi o add-on

        takefile.capture_from_scene(scene, store, take)
        take.duration_override = max(1, scene.frame_end) / float(fps)
        takefile.refresh_take_view(scene, store, take, capture=False)
        _save_soon(store)
        sync.sync_takes(context)
    except Exception as exc:  # msgbus engole exceção e some com a notificação
        print(f"[storyboard] duração pela timeline: {exc}")


def _save_soon(store):
    from . import props
    props._save_soon(store)


def subscribe(context=None) -> bool:
    """Passa a ouvir o fim da cena. Recomeça a cada arquivo aberto."""
    if bpy.app.background:
        return False
    bpy.msgbus.clear_by_owner(_OWNER)
    bpy.msgbus.subscribe_rna(
        key=(bpy.types.Scene, "frame_end"),
        owner=_OWNER, args=(), notify=_on_frame_end, options={"PERSISTENT"})
    return True


@persistent
def _on_load_post(_dummy):
    # Carregar arquivo limpa as assinaturas de msgbus; sem reatar, o "End" volta
    # a ser só o fim da cena no segundo take da sessão — calado.
    subscribe()


# ---------------------------------------------------------------------------
# O campo de segundos, no canto direito da timeline
# ---------------------------------------------------------------------------

def draw_take_duration(self, context):
    """Desenhado no fim do cabeçalho, que é o canto direito da timeline."""
    _store, take = take_on_screen()
    if take is None:
        return

    layout = self.layout
    row = layout.row(align=True)
    # O código do take vem junto: quem olha a timeline precisa saber de qual
    # plano é aquele tempo, e a sidebar pode estar fechada.
    row.label(text=take.code or take.name, icon="GREASEPENCIL")
    row.prop(context.window_manager.nsb, "take_seconds", text="")
    if take.duration_override is not None:
        # Tempo travado à mão é ESTADO: enquanto ele existe o take ignora o
        # áudio, e antes a única pista disso era estranhar. O botão desfaz.
        sub = row.row(align=True)
        sub.operator_context = "EXEC_DEFAULT"
        sub.operator("nsb.set_take_duration", text="", icon="LOOP_BACK").clear = True


HEADERS = ("DOPESHEET_HT_header",)


def register():
    for nome in HEADERS:
        getattr(bpy.types, nome).append(draw_take_duration)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    subscribe()


def unregister():
    bpy.msgbus.clear_by_owner(_OWNER)
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    for nome in HEADERS:
        getattr(bpy.types, nome).remove(draw_take_duration)
