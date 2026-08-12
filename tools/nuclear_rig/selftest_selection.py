"""Self-test do clique de seleção na viewport — o gate que a 1.8.0 não tinha.

Roda na GUI de propósito: clique e box select passam pelo buffer de seleção da GPU, que não
existe em `--background`. Um release que quebre qualquer um dos três caminhos abaixo é um
release que o artista não consegue usar, por mais que os testes headless passem.

    nuclear --factory-startup --python tools/nuclear_rig/selftest_selection.py

Sai com código 1 se algum caso falhar (a GUI fecha sozinha ao terminar).
"""
import os
import sys

import bpy

FAIL = []
OUT = os.environ.get("NUCLEAR_SELFTEST_OUT", "")
LINES = []


def check(name, got, want):
    ok = got == want
    line = ("  PASS  " if ok else "  FAIL  ") + "%-34s got=%s want=%s" % (name, got or "NADA", want)
    print(line, flush=True)
    LINES.append(line)
    if not ok:
        FAIL.append(name)


def view3d():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        return win, area, region
    return None, None, None


def selected():
    return sorted(o.name for o in bpy.data.objects if o.select_get())


def case(label, make, expect):
    """Monta a cena, enquadra o objeto e exercita os três caminhos de seleção."""
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.wm.read_factory_settings(use_empty=True)
    win, area, region = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        make()
        ob = bpy.context.view_layer.objects.active
        ob.select_set(True)
        bpy.ops.view3d.view_selected()
        w, h = region.width, region.height

        bpy.ops.object.select_all(action='DESELECT')
        bpy.ops.view3d.select('EXEC_DEFAULT', deselect_all=True, location=(w // 2, h // 2))
        check("%s: clique" % label, selected(), expect)

        bpy.ops.object.select_all(action='DESELECT')
        bpy.ops.view3d.select_box('EXEC_DEFAULT', xmin=0, xmax=w, ymin=0, ymax=h, mode='SET')
        check("%s: box select" % label, selected(), expect)

        bpy.ops.object.select_all(action='DESELECT')
        bpy.ops.object.select_all(action='SELECT')
        check("%s: select all" % label, selected(), expect)


def run():
    print("\n=== selftest de seleção — %s ===" % bpy.app.version_string, flush=True)
    case("MESH", lambda: bpy.ops.mesh.primitive_cube_add(), ["Cube"])
    case("GP desenho", lambda: bpy.ops.object.grease_pencil_add(type='MONKEY'), ["Suzanne"])
    case("GP stroke", lambda: bpy.ops.object.grease_pencil_add(type='STROKE'), ["Stroke"])
    case("EMPTY", lambda: bpy.ops.object.empty_add(), ["Empty"])

    verdict = "ALL PASS" if not FAIL else "FALHARAM %d: %s" % (len(FAIL), ", ".join(FAIL))
    print("\n=== %s ===" % verdict, flush=True)
    LINES.append(verdict)
    if OUT:
        with open(OUT, "w", encoding="utf-8") as fh:
            fh.write("\n".join(LINES) + "\n")
    bpy.ops.wm.quit_blender()
    sys.exit(1 if FAIL else 0)
    return None


bpy.app.timers.register(run, first_interval=2.0)
