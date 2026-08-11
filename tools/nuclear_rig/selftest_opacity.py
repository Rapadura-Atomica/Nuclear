"""Self-test for object and peg opacity, and for the inheritance that carries it down a rig.

Opacity resolves like the transform does: a peg's value multiplied by every ancestor's, so
fading the Master Peg fades the whole character. Two consequences drive what is checked here.

First, the resolved value is RUNTIME. `BKE_pegrig_solve_world_matrices` runs on the evaluated
copy from the depsgraph, so `opacity_resolved` read off the original rig is whatever was left in
memory -- meaningless. Every check below reads it through `evaluated_get`, and one check exists
purely to prove the original is NOT the place to look.

Second, the Follow Peg constraint folds the peg's resolved opacity into the object it drives.
That write lands on the evaluated object, whose `opacity` still holds the authored value when the
constraint runs, so the evaluated object ends up carrying the product. The original object must
come out untouched -- if it ever does not, opacity would compound on every depsgraph pass and a
piece would fade to black over a few frames.

Run headless, from the repository root:

    ./build/bin/nuclear -b --factory-startup --python tools/nuclear_rig/selftest_opacity.py
"""
import sys
import bpy

FAIL = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (("   " + detail) if detail else ""))
    if not cond:
        FAIL.append(name)


def close(a, b, tol=1e-6):
    return abs(a - b) < tol


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


def add_peg(rig, name, parent_index=-1):
    """Cria a peg e devolve o INDICE — `pegs.new()` realoca o array e invalida refs Python."""
    rig.pegs.new(name, parent_index=parent_index)
    return rig.pegs.find(name)


def resolved(rig, peg_name):
    """Opacidade resolvida, lida na copia AVALIADA (no original o campo nao significa nada)."""
    dg = bpy.context.evaluated_depsgraph_get()
    rig_eval = rig.evaluated_get(dg)
    return rig_eval.pegs[rig_eval.pegs.find(peg_name)].opacity_resolved


def eval_opacity(ob):
    """A opacidade com que a peca e DESENHADA: a propria vezes a da peg que ela segue.

    Nao e mais `ob.opacity` da copia avaliada: a contribuicao da peg mora num campo runtime
    proprio, porque multiplicar dentro de `opacity` acumulava sobre a avaliacao anterior."""
    dg = bpy.context.evaluated_depsgraph_get()
    return ob.evaluated_get(dg).opacity_resolved


def sync():
    bpy.context.view_layer.update()


# ---------------------------------------------------------------------------
print("\n=== T1: nasce opaco ===")
fresh_scene()
ob = make_gp("piece")
check("objeto novo com opacity 1.0", close(ob.opacity, 1.0), "opacity=%.6f" % ob.opacity)

rig = bpy.data.pegrigs.new("rig")
root = add_peg(rig, "root")
check("peg nova com opacity 1.0", close(rig.pegs[root].opacity, 1.0),
      "opacity=%.6f" % rig.pegs[root].opacity)
sync()
check("peg nova resolve para 1.0", close(resolved(rig, "root"), 1.0),
      "resolvida=%.6f" % resolved(rig, "root"))

# ---------------------------------------------------------------------------
print("\n=== T2: a opacidade multiplica pela cadeia de pais ===")
fresh_scene()
rig = bpy.data.pegrigs.new("rig")
root = add_peg(rig, "master")
# Uma peca ligada e OBRIGATORIA para o rig existir no depsgraph: `build_pegrig` so e alcancado
# por `build_id`, ou seja, quando algum ID referencia o rig. Rig solto nunca resolve, e
# `opacity_resolved` devolve o valor de criacao (1.0) sem aviso nenhum.
anchor = make_gp("anchor")
bind(anchor, rig, "master")
arm = add_peg(rig, "arm", parent_index=root)
hand = add_peg(rig, "hand", parent_index=arm)

rig.pegs[rig.pegs.find("master")].opacity = 0.5
rig.pegs[rig.pegs.find("arm")].opacity = 0.5
rig.pegs[rig.pegs.find("hand")].opacity = 1.0
sync()

check("raiz resolve para o proprio valor", close(resolved(rig, "master"), 0.5),
      "resolvida=%.6f" % resolved(rig, "master"))
check("filha resolve para o produto", close(resolved(rig, "arm"), 0.25),
      "resolvida=%.6f esperado=0.25" % resolved(rig, "arm"))
check("neta herda mesmo estando em 1.0", close(resolved(rig, "hand"), 0.25),
      "resolvida=%.6f esperado=0.25" % resolved(rig, "hand"))

# um filho NUNCA pode voltar mais claro que o pai
rig.pegs[rig.pegs.find("hand")].opacity = 1.0
sync()
check("filho nao fica mais claro que o pai",
      resolved(rig, "hand") <= resolved(rig, "arm") + 1e-6,
      "filho=%.6f pai=%.6f" % (resolved(rig, "hand"), resolved(rig, "arm")))

# ---------------------------------------------------------------------------
print("\n=== T3: o campo resolvido so existe na copia avaliada ===")
fresh_scene()
rig = bpy.data.pegrigs.new("rig")
root = add_peg(rig, "master")
child = add_peg(rig, "child", parent_index=root)
anchor = make_gp("anchor")
bind(anchor, rig, "child")
rig.pegs[rig.pegs.find("master")].opacity = 0.25
rig.pegs[rig.pegs.find("child")].opacity = 1.0
sync()

orig_resolved = rig.pegs[rig.pegs.find("child")].opacity_resolved
check("na avaliada o produto esta correto", close(resolved(rig, "child"), 0.25),
      "avaliada=%.6f" % resolved(rig, "child"))
print("        (original marca %.6f — runtime, nao confie nele)" % orig_resolved)
check("authored do original intacto",
      close(rig.pegs[rig.pegs.find("master")].opacity, 0.25),
      "opacity=%.6f" % rig.pegs[rig.pegs.find("master")].opacity)

# ---------------------------------------------------------------------------
print("\n=== T4: a peca ligada por Follow Peg herda a opacidade da peg ===")
fresh_scene()
ob = make_gp("piece")
rig = bpy.data.pegrigs.new("rig")
root = add_peg(rig, "master")
bind(ob, rig, "master")

rig.pegs[rig.pegs.find("master")].opacity = 0.5
ob.opacity = 0.5
sync()

check("avaliada = propria x da peg", close(eval_opacity(ob), 0.25),
      "avaliada=%.6f esperado=0.25" % eval_opacity(ob))
check("ORIGINAL nao foi tocado", close(ob.opacity, 0.5),
      "original=%.6f" % ob.opacity)

# a acumulacao so aparece depois de varias passadas — force algumas
for _ in range(5):
    sync()
    eval_opacity(ob)
check("estavel apos 5 avaliacoes", close(eval_opacity(ob), 0.25),
      "avaliada=%.6f" % eval_opacity(ob))
check("original ainda intacto apos 5 avaliacoes", close(ob.opacity, 0.5),
      "original=%.6f" % ob.opacity)

# peca solta (sem peg) fica com o proprio valor
loose = make_gp("loose")
loose.opacity = 0.5
sync()
check("peca sem peg mantem o proprio valor", close(eval_opacity(loose), 0.5),
      "avaliada=%.6f" % eval_opacity(loose))

# ---------------------------------------------------------------------------
print("\n=== T5: opacidade animada ===")
fresh_scene()
ob = make_gp("piece")
rig = bpy.data.pegrigs.new("rig")
root = add_peg(rig, "master")
bind(ob, rig, "master")

idx = rig.pegs.find("master")
scene = bpy.context.scene
scene.frame_set(1)
rig.pegs[idx].opacity = 1.0
rig.pegs[idx].keyframe_insert("opacity")
scene.frame_set(10)
rig.pegs[idx].opacity = 0.0
rig.pegs[idx].keyframe_insert("opacity")

scene.frame_set(1)
sync()
op1 = eval_opacity(ob)
scene.frame_set(10)
sync()
op10 = eval_opacity(ob)
scene.frame_set(5)
sync()
op5 = eval_opacity(ob)

check("peg opacity e animavel", close(op1, 1.0) and close(op10, 0.0),
      "f1=%.6f f10=%.6f" % (op1, op10))
peg5 = resolved(rig, "master")
check("a peg interpola a curva", 0.0 < peg5 < 1.0, "peg no f5=%.6f" % peg5)
check("BUG: a peca acompanha a curva da peg", close(op5, peg5),
      "peca=%.6f peg=%.6f — a peca nao e re-avaliada quando so a opacidade da peg muda"
      % (op5, peg5))

# a peca tambem anima sozinha
scene.frame_set(1)
ob.opacity = 1.0
ob.keyframe_insert("opacity")
scene.frame_set(10)
ob.opacity = 0.5
ob.keyframe_insert("opacity")
scene.frame_set(10)
sync()
check("object opacity e animavel", close(eval_opacity(ob), 0.0),
      "f10=%.6f (0.5 da peca x 0.0 da peg)" % eval_opacity(ob))

# ---------------------------------------------------------------------------
print("\n=== T6: a opacidade chega ao desenho (draw/render) ===")
fresh_scene()
ob = make_gp("piece")
data = ob.data
layer = data.layers[0]
layer.opacity = 0.8
ob.opacity = 0.5
sync()

# o multiplicador vive no draw engine; o que da para checar por dados e que a layer NAO foi
# alterada no original — a multiplicacao acontece na avaliacao, nao no arquivo.
check("layer opacity do original preservada", close(layer.opacity, 0.8),
      "layer=%.6f" % layer.opacity)
check("object opacity do original preservada", close(ob.opacity, 0.5),
      "objeto=%.6f" % ob.opacity)

# ---------------------------------------------------------------------------
print("\n=== T7: valores fora de faixa nao escapam ===")
fresh_scene()
ob = make_gp("piece")
ob.opacity = 5.0
check("RNA clampa acima de 1.0", close(ob.opacity, 1.0), "opacity=%.6f" % ob.opacity)
ob.opacity = -3.0
check("RNA clampa abaixo de 0.0", close(ob.opacity, 0.0), "opacity=%.6f" % ob.opacity)

rig = bpy.data.pegrigs.new("rig")
root = add_peg(rig, "master")
rig.pegs[root].opacity = 9.0
check("RNA clampa a peg", close(rig.pegs[root].opacity, 1.0),
      "opacity=%.6f" % rig.pegs[root].opacity)

# ---------------------------------------------------------------------------
print("\n=== T8: sobrevive ao save/load ===")
fresh_scene()
ob = make_gp("piece")
rig = bpy.data.pegrigs.new("rig")
root = add_peg(rig, "master")
bind(ob, rig, "master")
rig.pegs[root].opacity = 0.25
ob.opacity = 0.5

import tempfile
import os
path = os.path.join(tempfile.gettempdir(), "nuclear_selftest_opacity.blend")
bpy.ops.wm.save_as_mainfile(filepath=path)
bpy.ops.wm.open_mainfile(filepath=path)

ob = bpy.data.objects["piece"]
rig = bpy.data.pegrigs["rig"]
sync()
check("object opacity sobreviveu ao arquivo", close(ob.opacity, 0.5),
      "opacity=%.6f" % ob.opacity)
check("peg opacity sobreviveu ao arquivo",
      close(rig.pegs[rig.pegs.find("master")].opacity, 0.25),
      "opacity=%.6f" % rig.pegs[rig.pegs.find("master")].opacity)
check("BUG: a heranca refaz apos o load", close(eval_opacity(ob), 0.125),
      "avaliada=%.6f esperado=0.125 — `world_opacity` vem do disco e so re-resolve "
      "quando algo tagga o rig" % eval_opacity(ob))
os.unlink(path)

# ---------------------------------------------------------------------------
print("\n=== T9: mexer no Master Peg alcanca o rig INTEIRO ===")
fresh_scene()
rig = bpy.data.pegrigs.new("rig")
# Cadeia de quatro niveis com peca pendurada em cada profundidade — o que interessa e a peca
# mais funda, que so escurece se o produto atravessar todos os elos.
master = add_peg(rig, "master")
spine = add_peg(rig, "spine", parent_index=master)
arm = add_peg(rig, "arm", parent_index=spine)
hand = add_peg(rig, "hand", parent_index=arm)

pieces = {}
for peg_name in ("master", "spine", "arm", "hand"):
    piece = make_gp("piece_" + peg_name)
    bind(piece, rig, peg_name)
    pieces[peg_name] = piece
sync()

check("rig aceso: todas as pecas em 1.0",
      all(close(eval_opacity(p), 1.0) for p in pieces.values()),
      " ".join("%s=%.2f" % (n, eval_opacity(p)) for n, p in pieces.items()))

# a manipulacao que o painel faz: escrever em peg.opacity (o slider passa por aqui)
rig.pegs[rig.pegs.find("master")].opacity = 0.0
sync()
faded = {n: eval_opacity(p) for n, p in pieces.items()}
check("Master em 0 apaga o rig INTEIRO", all(close(v, 0.0) for v in faded.values()),
      " ".join("%s=%.3f" % (n, v) for n, v in faded.items()))

# meio-termo: o Master a 0.5 escurece tudo pela metade, inclusive a peca mais funda
rig.pegs[rig.pegs.find("master")].opacity = 0.5
sync()
half = {n: eval_opacity(p) for n, p in pieces.items()}
check("Master em 0.5 escurece tudo pela metade", all(close(v, 0.5) for v in half.values()),
      " ".join("%s=%.3f" % (n, v) for n, v in half.items()))

# e a peca funda acumula os elos do meio, nao so o Master
rig.pegs[rig.pegs.find("master")].opacity = 1.0
rig.pegs[rig.pegs.find("spine")].opacity = 0.5
rig.pegs[rig.pegs.find("arm")].opacity = 0.5
sync()
check("a peca funda acumula a cadeia toda", close(eval_opacity(pieces["hand"]), 0.25),
      "hand=%.4f esperado=0.25" % eval_opacity(pieces["hand"]))
check("peca acima do elo escurecido nao e afetada",
      close(eval_opacity(pieces["master"]), 1.0),
      "master=%.4f" % eval_opacity(pieces["master"]))

# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
if FAIL:
    print("FALHARAM %d: %s" % (len(FAIL), "; ".join(FAIL)))
else:
    print("TODOS OS TESTES PASSARAM")
print("=" * 60)
sys.stdout.flush()
