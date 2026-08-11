"""Operadores do timing dos desenhos.

Sobrou UM. Os outros quatro saíram porque o que eles faziam já acontece
sozinho: abrir o take monta os clipes de áudio na timeline (`takefile.open_take`)
e salvar lê de volta a posição dos clipes e o timing dos keyframes
(`takefile.save_take`). Botão que repete o que o programa já fez é só mais uma
coisa para o artista aprender — e para ele esquecer de clicar.
"""

from __future__ import annotations

import bpy
from bpy.types import Operator

from . import audiotl, state, sync, takefile, timingtools
from .translations import _, apply_context


class NSB_OT_apply_exposures(Operator):
    """Devolve os desenhos à divisão automática da duração.

    Junta o que eram dois botões ("distribuir na duração" e "voltar ao tempo
    automático"): para o artista é uma coisa só — desmanchar o timing manual e
    espalhar tudo de novo por igual.
    """

    bl_idname = "nsb.apply_exposures"
    bl_label = "Space the drawings evenly"
    bl_description = ("Clears the timing set by hand and spreads the drawings over "
                      "the take duration — the drawings themselves are untouched")

    @classmethod
    def poll(cls, context):
        store = state.get_store()
        return store is not None and takefile.current_take_of_file(store) is not None

    def execute(self, context):
        from . import gp
        store = state.require_store()
        take = takefile.current_take_of_file(store)
        ob = gp.find_take_object(take)
        if ob is None:
            self.report({"ERROR"}, _("the take has no canvas"))
            return {"CANCELLED"}

        fps = store.project.settings.fps
        timingtools.clear_exposures(take)
        moved = timingtools.apply_exposures(take, ob, fps)
        audiotl.apply_take_range(context.scene, take, fps)
        store.save()
        sync.sync_all(context)
        self.report({"INFO"}, f"{moved} " + _("drawing(s) repositioned"))
        return {"FINISHED"}


CLASSES = (NSB_OT_apply_exposures,)


def register():
    apply_context(CLASSES)
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
