"""RN02 em tempo real: enquanto a camada ativa é BG, o pincel fica cinza.

Feito com timer, não com msgbus: `Brush.color` não emite notificação confiável
(mesma pegadinha do toolkit de pintura). O timer é barato — só lê duas cores e
sai quando a camada ativa não é BG.
"""

from __future__ import annotations

import bpy

from . import gp

INTERVAL = 0.25


def _active_gp_object(context):
    # Logo depois de abrir um arquivo o contexto do timer é restrito e nem
    # `object` existe nele: ler o atributo direto levantava AttributeError, e
    # uma exceção no timer o DESREGISTRA — a trava sumia ao trocar de take.
    ob = getattr(context, "object", None)
    if ob is None or ob.type not in {"GREASEPENCIL", "GPENCIL"}:
        return None
    return ob if ob.get(gp.TAKE_KEY) else None


def _paint_brush(context):
    tool_settings = getattr(context, "tool_settings", None)
    settings = getattr(tool_settings, "gpencil_paint", None)
    return getattr(settings, "brush", None) if settings else None


def _tick():
    context = bpy.context
    ob = _active_gp_object(context)
    if ob is None:
        return INTERVAL

    layer = ob.data.layers.active
    if layer is None or gp.layer_role(layer) != gp.ROLE_BG:
        return INTERVAL

    brush = _paint_brush(context)
    if brush is not None:
        color = brush.color
        if max(color[:3]) - min(color[:3]) > 1e-4:
            brush.color = gp.desaturate(color)

    index = ob.active_material_index
    if 0 <= index < len(ob.data.materials):
        mat = ob.data.materials[index]
        if mat is not None and mat.grease_pencil is not None:
            gpm = mat.grease_pencil
            for attr in ("color", "fill_color"):
                value = getattr(gpm, attr)
                if max(value[:3]) - min(value[:3]) > 1e-4:
                    setattr(gpm, attr, (*gp.desaturate(value), value[3]))
    return INTERVAL


def is_running() -> bool:
    return bpy.app.timers.is_registered(_tick)


def start() -> None:
    if not is_running():
        bpy.app.timers.register(_tick, persistent=True)


def stop() -> None:
    if is_running():
        bpy.app.timers.unregister(_tick)


def register() -> None:
    start()


def unregister() -> None:
    stop()
