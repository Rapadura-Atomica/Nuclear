"""Drag-and-drop de `.wav` para dentro do take (RF-A01).

O artista arrasta os arquivos de diálogo do gerenciador de arquivos direto para
a janela do Nuclear e eles entram no take aberto, na ordem em que vieram: o
primeiro no início, cada um seguinte depois do anterior. Posicionar com precisão
continua sendo trabalho da timeline.

Usa `bpy.types.FileHandler`, que é como o Blender expõe o drop de arquivos para
add-ons. O operador de importação também funciona sozinho, com um `filepath`.
"""

from __future__ import annotations

from pathlib import Path

import bpy
from bpy.props import BoolProperty, CollectionProperty, StringProperty
from bpy.types import FileHandler, Operator, PropertyGroup

from . import state, sync, takefile
from .core import StorageError
from .core.timing import take_duration
from .core.wave_info import AudioError
from .translations import _


class NSB_PG_dropped_file(PropertyGroup):
    name: StringProperty()


class NSB_OT_drop_audio(Operator):
    """Importa os `.wav` soltos na janela para o take aberto."""

    bl_idname = "nsb.drop_audio"
    bl_label = "Drop audio into the take"
    bl_description = "Imports the dropped .wav files into the open take"
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(subtype="DIR_PATH", options={"HIDDEN"})
    files: CollectionProperty(type=NSB_PG_dropped_file, options={"HIDDEN"})
    filepath: StringProperty(subtype="FILE_PATH", options={"HIDDEN"})
    #: Cada clipe entra depois do anterior, em vez de todos no zero.
    sequential: BoolProperty(name="One after another", default=True)

    @classmethod
    def poll(cls, context):
        store = state.get_store()
        return store is not None and takefile.current_take_of_file(store) is not None

    def _paths(self):
        if self.files and self.directory:
            return [Path(self.directory) / f.name for f in self.files if f.name]
        return [Path(self.filepath)] if self.filepath else []

    def execute(self, context):
        store = state.require_store()
        take = takefile.current_take_of_file(store)

        wavs = [p for p in self._paths() if p.suffix.lower() == ".wav"]
        ignored = len(self._paths()) - len(wavs)
        if not wavs:
            self.report({"WARNING"}, _("only .wav files are accepted"))
            return {"CANCELLED"}

        start = max((a.end for a in take.audios), default=0.0) if self.sequential else 0.0
        imported, problems = 0, []
        for path in sorted(wavs):
            try:
                clip = store.import_audio(path, take, start=start)
            except (StorageError, AudioError) as exc:
                problems.append(str(exc))
                continue
            imported += 1
            if self.sequential:
                start = clip.end

        store.save()
        takefile.refresh_take_view(context.scene, store, take, capture=False)
        sync.sync_all(context)

        if problems:
            self.report({"ERROR"}, problems[0])
            return {"CANCELLED"} if not imported else {"FINISHED"}

        message = f"{imported} " + _("audio file(s) imported")
        if ignored:
            message += f" · {ignored} " + _("ignored (not .wav)")
        message += f" · {_('Duration')} {take_duration(take):.2f}s"
        self.report({"INFO"}, message)
        return {"FINISHED"}


class NSB_FH_wav(FileHandler):
    bl_idname = "NSB_FH_wav"
    bl_label = "Storyboard dialogue audio"
    bl_import_operator = "nsb.drop_audio"
    bl_file_extensions = ".wav"

    @classmethod
    def poll_drop(cls, context):
        # Só aceita o drop onde o artista está trabalhando no take.
        if context.area is None or context.area.type not in {"VIEW_3D", "SEQUENCE_EDITOR",
                                                             "DOPESHEET_EDITOR"}:
            return False
        return NSB_OT_drop_audio.poll(context)


CLASSES = (NSB_PG_dropped_file, NSB_OT_drop_audio, NSB_FH_wav)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
