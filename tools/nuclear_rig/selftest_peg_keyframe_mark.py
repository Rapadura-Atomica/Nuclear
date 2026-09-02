"""Self-test de "marcar keyframe" numa peça presa a peg — o gate do bug da segunda pose.

Caso real que motivou (2026-09-02): o animador marca a chave no frame 1 com `I`, vai ao frame 2
e posa; ao voltar, os dois frames mostram a mesma pose. O `I` do viewport keyava o OBJETO
(location/rotation/scale, que a Follow Peg ignora) e o `I` do Dope Sheet só re-keyava canais que
já existiam — a peg em si nunca ganhava a chave que o animador viu ser marcada.

Roda na GUI de propósito (transform e os operadores de chave precisam de janela):

    nuclear --factory-startup --python tools/nuclear_rig/selftest_peg_keyframe_mark.py

Código de saída: 0 = tudo passou, 1 = algum caso REPROVOU, 2 = o arnês QUEBROU (não é aprovação).
"""
import os
import sys
import traceback

import bpy

FAIL = []
OUT = os.environ.get("NUCLEAR_SELFTEST_OUT", "")
LINES = []


def check(name, got, want):
    ok = got == want
    line = ("  PASS  " if ok else "  FAIL  ") + "%-46s got=%r want=%r" % (name, got, want)
    print(line, flush=True)
    LINES.append(line)
    if not ok:
        FAIL.append(name)


def area_of(kind):
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == kind:
                for region in area.regions:
                    if region.type == 'WINDOW':
                        return win, area, region
    return None, None, None


def fcurves_of(id_):
    ad = id_.animation_data
    if ad is None or ad.action is None:
        return []
    out = []
    for layer in ad.action.layers:
        for strip in layer.strips:
            for cb in strip.channelbags:
                out.extend(cb.fcurves)
    return out


def key_frames(id_, path_part):
    """Frames com chave nos canais cujo data_path contém `path_part` (ordenado, sem repetir)."""
    return sorted({int(k.co.x) for fc in fcurves_of(id_) if path_part in fc.data_path
                   for k in fc.keyframe_points})


def channel_count(id_, path_part):
    return sum(1 for fc in fcurves_of(id_) if path_part in fc.data_path)


def v3(v):
    return tuple(round(c, 3) for c in v)


def reset():
    win, area, region = area_of('VIEW_3D')
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.read_factory_settings(use_empty=True)


def make_rig(with_master=False):
    """Peça GP presa à peg 'A' (filha de 'Master' se pedido). Devolve (objeto, rig)."""
    bpy.ops.object.grease_pencil_add(type='STROKE')
    ob = bpy.context.active_object
    rig = bpy.data.pegrigs.new("rig")
    parent = -1
    if with_master:
        rig.pegs.new("Master", parent_index=-1)
        parent = 0
    rig.pegs.new("A", parent_index=parent)
    con = ob.constraints.new('FOLLOW_PEG')
    con.rig = rig
    con.peg_name = "A"
    bpy.ops.object.select_all(action='DESELECT')
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.context.scene.tool_settings.use_keyframe_insert_auto = True
    return ob, rig


def dopesheet():
    win, area, region = area_of('DOPESHEET_EDITOR')
    area.spaces.active.ui_mode = 'DOPESHEET'
    return win, area, region


def peg(rig, name="A"):
    return rig.pegs[rig.pegs.find(name)]


def cases():
    reset()
    yield 0.3

    # ---- A: I no viewport marca a PEG, e o caso relatado fecha ------------------------------
    win, area, region = area_of('VIEW_3D')
    with bpy.context.temp_override(window=win, area=area, region=region):
        ob, rig = make_rig()
        sc = bpy.context.scene
        sc.frame_set(1)
        bpy.ops.anim.keyframe_insert()
        check("A: I viewport keya os 9 canais da peg", channel_count(rig, 'pegs["A"]'), 9)
        check("A: I viewport nao keya o objeto", ob.animation_data is None, True)
        sc.frame_set(2)
        bpy.ops.transform.translate(value=(0, 0, 1))
        sc.frame_set(1)
        check("A: frame 1 mantem a pose 1", v3(peg(rig).translation), (0.0, 0.0, 0.0))
        sc.frame_set(2)
        check("A: frame 2 mantem a pose 2", v3(peg(rig).translation), (0.0, 0.0, 1.0))
        # Alt+I no frame 2 apaga so a chave da peg naquele frame.
        bpy.ops.anim.keyframe_delete_v3d()
        check("A: Alt+I apaga a chave da peg no frame", key_frames(rig, 'pegs["A"].translation'), [1])
    reset()
    yield 0.3

    # ---- B: I no Dope Sheet keya um rig SEM canal nenhum -------------------------------------
    win, area, region = area_of('VIEW_3D')
    with bpy.context.temp_override(window=win, area=area, region=region):
        ob, rig = make_rig(with_master=True)
        sc = bpy.context.scene
        sc.frame_set(1)
        check("B: rig comeca sem canais", len(fcurves_of(rig)), 0)
    win, area, region = dopesheet()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.action.keyframe_insert(type='ALL')
    yield 0.3
    win, area, region = area_of('VIEW_3D')
    with bpy.context.temp_override(window=win, area=area, region=region):
        sc = bpy.context.scene
        check("B: I dopesheet keya a peg da peca", channel_count(rig, 'pegs["A"]'), 9)
        check("B: I dopesheet keya a Master tambem", channel_count(rig, 'pegs["Master"]'), 9)
        sc.frame_set(2)
        bpy.ops.transform.translate(value=(1, 0, 0))
        sc.frame_set(1)
        check("B: frame 1 mantem a pose 1", v3(peg(rig).translation), (0.0, 0.0, 0.0))
        sc.frame_set(2)
        check("B: frame 2 mantem a pose 2", v3(peg(rig).translation), (1.0, 0.0, 0.0))
    reset()
    yield 0.3

    # ---- C: Ctrl+B (peg ativa = ancestral) — o I segue a mesma peg que o transform ---------
    win, area, region = area_of('VIEW_3D')
    with bpy.context.temp_override(window=win, area=area, region=region):
        ob, rig = make_rig(with_master=True)
        rig.active_peg_index = rig.pegs.find("Master")
        bpy.context.scene.frame_set(1)
        bpy.ops.anim.keyframe_insert()
        check("C: I keya a Master ativa", channel_count(rig, 'pegs["Master"]'), 9)
        check("C: I nao keya a peg folha", channel_count(rig, 'pegs["A"]'), 0)
    reset()
    yield 0.3

    # ---- D: objeto SEM peg continua keyando o proprio objeto (nao-regressao) ---------------
    win, area, region = area_of('VIEW_3D')
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.mesh.primitive_cube_add()
        ob = bpy.context.active_object
        bpy.context.scene.frame_set(1)
        bpy.ops.anim.keyframe_insert()
        check("D: I keya location do objeto sem peg", key_frames(ob, "location"), [1])
    yield 0.2


GEN = None


def run():
    global GEN
    try:
        if GEN is None:
            print("\n=== selftest de marcar keyframe na peg — %s ===" % bpy.app.version_string, flush=True)
            GEN = cases()
        return next(GEN)
    except StopIteration:
        code = 1 if FAIL else 0
        verdict = "ALL PASS" if not FAIL else "FALHARAM %d: %s" % (len(FAIL), ", ".join(FAIL))
    except Exception:
        code = 2
        verdict = "ARNES QUEBROU:\n" + traceback.format_exc()
    print("\n=== %s ===" % verdict, flush=True)
    LINES.append(verdict)
    if OUT:
        with open(OUT, "w", encoding="utf-8") as fh:
            fh.write("\n".join(LINES) + "\n")
    bpy.ops.wm.quit_blender()
    sys.exit(code)


# persistent: read_factory_settings descarta timers comuns e a GUI ficaria aberta para sempre.
bpy.app.timers.register(run, first_interval=2.0, persistent=True)
