"""Self-test for peg pivots and for the binding that anchors a drawing to a peg.

The local matrix is T(t+p)*R*S*T(-p), so the rotation centre is parent_world @ (pivot +
translation). Two things follow, and both are checked here: a setter aiming a pivot at a point has
to take the translation back out, and a pivot placed from the artwork must not depend on which
frame the playhead was parked on (an animated Grease Pencil shows a different cell per frame).

The last check covers the other half: re-anchoring an already-bound drawing rewrites its inverse
matrix as the current peg world inverse, which cancels whatever pose the peg was holding. Only a
NEW binding may do that -- the graph sync runs on every tree update, including the one after an
undo, and re-anchoring there is what made pieces fail to land back where they were.

Run headless, from the repository root:

    ./build/bin/nuclear -b --factory-startup --python tools/nuclear_rig/selftest_pivot.py
"""
import sys
import bpy
import mathutils
from mathutils import Vector, Euler

import nuclear_peg_graph as PG
import nuclear_rig_auto as RA

FAIL = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (("   " + detail) if detail else ""))
    if not cond:
        FAIL.append(name)


def rotation_centre_world(rig, idx):
    """Ponto sobre o qual a peg gira, sob T(t+p)*R*S*T(-p)."""
    peg = rig.pegs[idx]
    parent = peg.parent_index
    pw = (PG._peg_world_matrix(rig, parent) if 0 <= parent < len(rig.pegs)
          else mathutils.Matrix.Identity(4))
    return pw @ (Vector(peg.pivot) + Vector(peg.translation))


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def make_gp(name, loc=(0.0, 0.0, 0.0)):
    bpy.ops.object.grease_pencil_add(type='STROKE', location=loc)
    ob = bpy.context.active_object
    ob.name = name
    return ob


def bind(ob, rig, peg_name):
    con = ob.constraints.new('FOLLOW_PEG')
    con.rig = rig
    con.peg_name = peg_name
    return con


# ---------------------------------------------------------------------------
print("\n=== T1: o setter ancora o centro de giro no ponto mirado ===")
fresh_scene()
ob = make_gp("piece")
rig = bpy.data.pegrigs.new("rig")
rig.pegs.new("root", parent_index=-1)
bind(ob, rig, "root")
idx = rig.pegs.find("root")
rig.pegs[idx].translation = (0.35, 0.0, -0.20)   # peca arrastada, como no caso Peg.079

target = Vector((1.5, 0.0, 2.5))
PG._set_pivot_world(rig, idx, target)
err = (rotation_centre_world(rig, idx) - target).length
check("centro de giro cai no alvo", err < 1e-5, "erro=%.9f" % err)

naive = Vector(rig.pegs[idx].pivot) + Vector(rig.pegs[idx].translation)
check("o setter descontou a translacao",
      (Vector(rig.pegs[idx].pivot) - target).length > 1e-6,
      "pivot=%s alvo=%s" % (tuple(round(v, 4) for v in rig.pegs[idx].pivot), tuple(target)))

# ---------------------------------------------------------------------------
print("\n=== T2: girar a peg nao move o proprio pivo ===")
before = rotation_centre_world(rig, idx).copy()
rig.pegs[idx].rotation = (0.0, 0.6, 0.0)
after = rotation_centre_world(rig, idx)
check("pivo imovel sob rotacao", (after - before).length < 1e-6,
      "desloc=%.9f" % (after - before).length)
rig.pegs[idx].rotation = (0.0, 0.0, 0.0)

# ---------------------------------------------------------------------------
print("\n=== T3: o pivo e solidario a peca (anda junto na translacao) ===")
p_before = rotation_centre_world(rig, idx).copy()
delta = Vector((0.4, 0.0, 0.1))
rig.pegs[idx].translation = Vector(rig.pegs[idx].translation) + delta
p_after = rotation_centre_world(rig, idx)
moved = p_after - p_before
check("pivo acompanha a peca 1:1", (moved - delta).length < 1e-6,
      "andou=%s esperado=%s" % (tuple(round(v, 4) for v in moved), tuple(delta)))

# ---------------------------------------------------------------------------
print("\n=== T4: alvo estavel — uniao das cells vs desenho do frame ===")
fresh_scene()
ob = make_gp("animated")
data = ob.data
# o objeto de teste vem com duas layers e so uma tem tracos ('Color' nasce vazia)
layer = next(l for l in data.layers
             if any(len(getattr(f.drawing, "strokes", []) or []) for f in l.frames))
# segunda cell, deslocada: o desenho do frame 10 vive longe do frame 1.
# `frames.copy` REALOCA a colecao e invalida refs Python de frame, entao o numero vem antes e o
# frame novo e re-buscado por numero. `nf.drawing = outra` faz copia INDEPENDENTE da geometria
# (instanciar compartilharia, e mover os pontos moveria as duas cells).
src_no = layer.frames[0].frame_number
src_drawing = layer.frames[0].drawing
layer.frames.new(10)
f10 = None
for fr in layer.frames:
    if fr.frame_number == 10:
        f10 = fr
f10.drawing = src_drawing
shifted = 0
for stroke in (f10.drawing.strokes or []):
    for pt in stroke.points:
        pt.position = (pt.position[0] + 3.0, pt.position[1], pt.position[2])
        shifted += 1
check("segunda cell criada e deslocada", shifted > 0, "%d pontos" % shifted)

bpy.context.scene.frame_set(1)
bpy.context.view_layer.update()
union_f1 = PG._drawing_union_center_world(ob).copy()
bbox_f1 = PG._drawing_center_world(ob).copy()
bpy.context.scene.frame_set(10)
bpy.context.view_layer.update()
union_f10 = PG._drawing_union_center_world(ob).copy()
bbox_f10 = PG._drawing_center_world(ob).copy()

check("uniao das cells nao depende do frame", (union_f1 - union_f10).length < 1e-6,
      "variacao=%.9f" % (union_f1 - union_f10).length)
check("bbox do frame DEPENDE do frame (o bug antigo)", (bbox_f1 - bbox_f10).length > 1e-3,
      "variacao=%.4f" % (bbox_f1 - bbox_f10).length)

# ---------------------------------------------------------------------------
print("\n=== T5: rig_auto mede a silhueta completa, nao a do playhead ===")
RA._clear_union_cache()
bpy.context.scene.frame_set(1)
mn1, mx1 = RA._aabb(ob)
RA._clear_union_cache()
bpy.context.scene.frame_set(10)
mn10, mx10 = RA._aabb(ob)
check("aabb do rig_auto nao depende do frame",
      (mn1 - mn10).length < 1e-6 and (mx1 - mx10).length < 1e-6,
      "dmin=%.9f dmax=%.9f" % ((mn1 - mn10).length, (mx1 - mx10).length))

# ---------------------------------------------------------------------------
print("\n=== T6: guard — auto-pivot nao mexe em pivo colocado a mao ===")
fresh_scene()
ob = make_gp("guarded")
rig = bpy.data.pegrigs.new("rig2")
rig.pegs.new("p", parent_index=-1)
i = rig.pegs.find("p")
bind(ob, rig, "p")
PG._mark_pivot_hand_placed(rig, "p")
rig.pegs[i].pivot = (0.0, 0.0, 0.0)          # a mao, na origem: o caso que o guard antigo perdia
PG._auto_pivot_on_bind(rig, "p", ob)
check("pivo a mao na origem sobrevive",
      all(abs(v) < 1e-9 for v in rig.pegs[i].pivot),
      "pivot=%s" % (tuple(round(v, 4) for v in rig.pegs[i].pivot),))

rig.pegs.new("q", parent_index=-1)
j = rig.pegs.find("q")
ob2 = make_gp("unguarded", loc=(2.0, 0.0, 0.0))
bind(ob2, rig, "q")
PG._auto_pivot_on_bind(rig, "q", ob2)
check("peg nova ainda recebe pivo automatico",
      any(abs(v) > 1e-9 for v in rig.pegs[j].pivot),
      "pivot=%s" % (tuple(round(v, 4) for v in rig.pegs[j].pivot),))

# ---------------------------------------------------------------------------
print("\n=== T7: squash fica ancorado numa peg arrastada ===")
fresh_scene()
ob = make_gp("squashed")
rig = bpy.data.pegrigs.new("rig3")
rig.pegs.new("s", parent_index=-1)
k = rig.pegs.find("s")
bind(ob, rig, "s")
peg = rig.pegs[k]
peg.pivot = (0.0, 0.0, 0.0)
peg.use_squash = True
peg.squash_anchor = (0.0, 0.0, 0.0)
peg.squash_tip = (0.0, 0.0, 2.0)
for label, t in (("t=0", (0.0, 0.0, 0.0)),
                 ("t em X", (0.5, 0.0, 0.0)),
                 ("t em Y", (0.0, 0.7, 0.0)),
                 ("t em Z", (0.0, 0.0, 0.4))):
    peg = rig.pegs[k]
    peg.translation = t
    peg.squash_tip = (0.0, 0.0, 2.0)
    rest = rotation_centre_world(rig, k).copy()
    peg.squash_tip = (0.0, 0.0, 3.2)          # estica
    moved = (rotation_centre_world(rig, k) - rest).length
    check("squash nao desloca o pivo (%s)" % label, moved < 1e-6, "desloc=%.9f" % moved)


# ---------------------------------------------------------------------------
print("\n=== T8: sincronizar o grafo nao desancora uma peca posada ===")
fresh_scene()
ob = make_gp("bound")
rig = bpy.data.pegrigs.new("rig4")
rig.pegs.new("p", parent_index=-1)
k = rig.pegs.find("p")
con = bind(ob, rig, "p")
con.set_inverse_pending = True


def settle():
    bpy.context.view_layer.update()
    bpy.context.evaluated_depsgraph_get().update()


def evaluated_location(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    return obj.evaluated_get(depsgraph).matrix_world.translation.copy()


settle()
tree = bpy.data.node_groups.new("graph", PG._TREE_ID)
tree.rig = rig
PG.rebuild(tree)
settle()

rig.pegs[k].rotation = (0.0, 0.5, 0.0)
rig.pegs[k].translation = (0.4, 0.0, 0.3)
rig.id_data.update_tag()
settle()
posed = evaluated_location(ob)

PG._apply_graph_to_rig(tree)          # o que o node tree dispara a cada update, undo incluso
settle()
drift = (evaluated_location(ob) - posed).length
check("sync mantem a peca na pose", drift < 1e-6, "desloc=%.9f" % drift)

# o mecanismo continua existindo — o guard e que decide quando usa-lo
con.set_inverse_pending = True
ob.update_tag()
settle()
moved = (evaluated_location(ob) - posed).length
check("re-ancorar explicitamente ainda re-ancora", moved > 1e-5, "desloc=%.6f" % moved)


# ---------------------------------------------------------------------------
print("\n=== T9: reparentear nao move a peg nem o pivo ===")


def reparent_case(label, parent_setup, peg_pose, new_parent_key, keep=True):
    """Devolve (desloc do pivo, desloc da peca) ao reparentear, com ou sem keep-transform."""
    fresh_scene()
    piece = make_gp("piece_" + label.replace(" ", "_"))
    r = bpy.data.pegrigs.new("rig_" + label.replace(" ", "_"))
    r.pegs.new("A", parent_index=-1)
    r.pegs.new("B", parent_index=-1)
    ia, ib = r.pegs.find("A"), r.pegs.find("B")
    parent_setup(r, ia, ib)
    r.pegs.new("C", parent_index=ia)
    ic = r.pegs.find("C")
    c = bind(piece, r, "C")
    c.set_inverse_pending = True
    bpy.context.view_layer.update()
    bpy.context.evaluated_depsgraph_get().update()

    PG._set_pivot_world(r, ic, Vector((2.0, 0.0, 1.0)))
    peg_pose(r, ic)
    r.id_data.update_tag()
    bpy.context.view_layer.update()
    bpy.context.evaluated_depsgraph_get().update()

    pivot_before = PG._peg_pivot_world(r, ic).copy()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    piece_before = piece.evaluated_get(depsgraph).matrix_world.translation.copy()

    target = ib if new_parent_key == "B" else -1
    if keep:
        PG._reparent_keep_transform(r, ic, target)
    else:
        r.pegs[ic].parent_index = target      # baseline: o que o codigo fazia antes
    r.id_data.update_tag()
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()

    pivot_drift = (PG._peg_pivot_world(r, ic) - pivot_before).length
    piece_drift = (piece.evaluated_get(depsgraph).matrix_world.translation - piece_before).length
    return pivot_drift, piece_drift


def reparent_check(label, parent_setup, peg_pose, new_parent_key, exact=True):
    pivot_drift, piece_drift = reparent_case(label, parent_setup, peg_pose, new_parent_key)
    _base_pivot, base_piece = reparent_case(label, parent_setup, peg_pose, new_parent_key,
                                            keep=False)
    check("reparent %s: pivo parado" % label, pivot_drift < 1e-5, "desloc=%.9f" % pivot_drift)
    if exact:
        check("reparent %s: peca parada" % label, piece_drift < 1e-5, "desloc=%.9f" % piece_drift)
    else:
        # Escala nao-uniforme composta com rotacao gera SHEAR, e a peg guarda euler + escala por
        # eixo: essa orientacao nao e representavel, entao a PECA ainda escorrega. O pivo continua
        # exato, que e o que o keep-transform promete. Informativo, nao falha.
        print("  nota   reparent %s: peca escorrega %.4f (sem keep-transform: %.4f) — shear"
              % (label, piece_drift, base_piece))


def translated(r, ia, ib):
    r.pegs[ia].translation = (1.0, 0.0, 0.0)
    r.pegs[ib].translation = (0.0, 0.0, 1.5)


def rotated(r, ia, ib):
    translated(r, ia, ib)
    r.pegs[ia].rotation = (0.0, 0.4, 0.0)
    r.pegs[ib].rotation = (0.0, -0.9, 0.0)


def scaled(r, ia, ib):
    rotated(r, ia, ib)
    r.pegs[ia].scale = (1.4, 1.0, 0.7)
    r.pegs[ib].scale = (0.6, 1.0, 1.3)


def at_rest(_r, _i):
    pass


def posed(r, i):
    r.pegs[i].rotation = (0.0, 0.35, 0.0)
    r.pegs[i].translation = (0.25, 0.0, -0.15)
    r.pegs[i].scale = (1.2, 1.0, 0.9)


reparent_check("pai transladado", translated, at_rest, "B")
reparent_check("pai rotacionado", rotated, at_rest, "B")
reparent_check("pai escalado", scaled, at_rest, "B", exact=False)
reparent_check("peg posada", scaled, posed, "B", exact=False)
reparent_check("de volta a raiz", scaled, posed, "root", exact=False)

# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
if FAIL:
    print("FALHARAM %d: %s" % (len(FAIL), "; ".join(FAIL)))
else:
    print("TODOS OS TESTES PASSARAM")
print("=" * 60)
sys.stdout.flush()
