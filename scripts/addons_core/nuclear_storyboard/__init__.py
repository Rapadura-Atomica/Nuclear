"""Storyboard & Animatic — add-on do Nuclear.

Fase 1: modelo de dados, projeto em disco (JSON), estrutura episódio/cena/take,
áudio com duração derivada, biblioteca de assets e validação das regras do PRD.
Fase 2: canvas do take em Grease Pencil — camadas por papel, desenhos como
keyframes, cor hex do lineart no material e trava do BG em escala de cinza.
Fase 3: timeline do take — áudios como clipes do VSE (waveform, arrasto, corte)
e exposição por desenho lida ou aplicada nos keyframes.
Fase 4: export — render dos desenhos, MP4 com burning e projeto `.kdenlive`,
tudo num worker headless que não mexe na sessão do artista.
A interface é bilíngue: as strings do código estão em inglês e o português vem
de `translations.py`, seguindo o idioma configurado no próprio Nuclear.
"""

bl_info = {
    "name": "Storyboard & Animatic",
    "author": "Rapadura Atômica",
    "version": (0, 15, 0),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar (N) > Storyboard",
    "description": "Storyboard por take, áudio de diálogo e animatic — sem geração automática",
    "category": "Animation",
}

if "bpy" in locals():  # recarga do add-on: reimporta os submódulos
    import importlib
    from . import (audioedit, audiotl, autoswitch, bgguard, core, dragdrop, gp,
                   ops, ops_approval, ops_canvas, ops_export, ops_timeline,
                   overlay, props, state, sync, takefile, thumbs, timelineui,
                   timingtools, translations, ui, workspace)
    for _mod in (core, state, gp, audiotl, audioedit, timingtools, translations,
                 props, sync, thumbs, workspace, takefile, autoswitch, ops,
                 ops_canvas, ops_timeline, ops_export, ops_approval, dragdrop,
                 bgguard, overlay, timelineui, ui):
        importlib.reload(_mod)

try:
    import bpy
except ModuleNotFoundError:
    # Fora do Blender: `nuclear_storyboard.core` continua importável, que é o
    # ponto de manter o núcleo sem bpy. Sem Blender não há o que registrar.
    bpy = None
    MODULES = ()
else:
    from . import (audioedit, bgguard, boardpanel, dragdrop, ops, ops_approval,
                   ops_canvas, ops_export, ops_timeline, overlay, props,
                   takefile, thumbs, timelineui, translations, ui)

    # translations primeiro: os rótulos das classes já registram traduzidos.
    MODULES = (translations, props, ops, ops_canvas, ops_timeline, ops_export,
               ops_approval, dragdrop, takefile, bgguard, audioedit, thumbs,
               overlay, timelineui, ui, boardpanel)


def register():
    if bpy is None:
        raise RuntimeError("este add-on precisa rodar dentro do Nuclear")
    for module in MODULES:
        module.register()


def unregister():
    from . import state
    state.set_store(None)
    for module in reversed(MODULES):
        module.unregister()
