# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Nuclear — automatic rig from drawing pieces (Auto Rig).

The artist already has the character split into named Grease Pencil pieces. Rigging is
split along a non-uniform automation boundary:

* **Auto-Build Skeleton** — the predictable spine + limbs (torso·neck·head and the mirrored
  arms/legs) are matched by name against a humanoid ontology and built in one click. Pieces
  the matcher is unsure about stay as *loose members* of the rig, ready to be linked.
* **Face fan (auto)** — head-fan pieces recognised by name (eyes, brows, mouth, nose, ears,
  hair…) auto-parent under the head joint, no manual link needed.
* **Link Selected to Active** — anything still unrecognised (accessories, wardrobe, props) is
  attached in batches: select the cluster, make the parent piece active, click.

In every case the joint/pivot is **computed from geometry** (the overlap between a piece and
its parent), so the animator never places a joint by hand. Refinement happens in the existing
Peg Graph node editor (reparent by dragging links).

Pure Python over the existing PegRig API; no C side.
"""

import re
import unicodedata

import bpy
import mathutils
from bpy.props import StringProperty
from bpy.types import Operator, Panel

# --------------------------------------------------------------------------- #
# Humanoid ontology
# --------------------------------------------------------------------------- #
# role -> parent role (None = root). Sided roles inherit their side from the child.
_PARENT_ROLE = {
    "torso": None,
    "neck": "torso",
    "head": "neck",
    "clavicle": "torso",
    "upperarm": "clavicle",
    "forearm": "upperarm",
    "hand": "forearm",
    "pelvis": "torso",
    "thigh": "pelvis",
    "shin": "thigh",
    "foot": "shin",
}
_SIDED = {"clavicle", "upperarm", "forearm", "hand", "thigh", "shin", "foot"}

# Structural joints: pegs with NO drawing (pure articulation), synthesised between a limb and the spine
# even when the artist drew no piece for them — the studio standard (legs hang off a pelvis, not the
# torso; arms off a shoulder). Materialised only when a descendant limb piece routes through them; the
# pivot is the mean of their matched children's sockets. If the artist DID draw a matching piece (e.g.
# "quadril"/"ombro"), it binds to this joint like any other skeleton piece (two-peg pattern).
_STRUCT_JOINTS = {"pelvis", "clavicle"}

# Joint pegs are named after the ROLE, not after the drawing: piece names in a legacy library lie
# often enough that a graph built on them is unreadable ("1antebraco.002" is a skirt, "cabelo1.004"
# is an arm). The drawing peg keeps the piece's own name, so the artist still finds their piece.
_ROLE_LABEL = {
    "torso": "Tronco", "neck": "Pescoço", "head": "Cabeça", "clavicle": "Ombro",
    "upperarm": "Braço", "forearm": "Antebraço", "hand": "Mão", "pelvis": "Quadril",
    "thigh": "Coxa", "shin": "Canela", "foot": "Pé",
}
_FACE_LABEL = {
    "eyebrow": "Sobrancelha", "eye": "Olho", "eyelid": "Pálpebra", "pupil": "Pupila",
    "eyelash": "Cílio", "nose": "Nariz", "mouth": "Boca", "lip": "Lábio", "tooth": "Dente",
    "tongue": "Língua", "ear": "Orelha", "cheek": "Bochecha", "chin": "Queixo",
    "mustache": "Bigode", "beard": "Barba", "hair": "Cabelo", "bangs": "Franja",
    "braid": "Trança",
}


def _side_label(name, side):
    return "%s.%s" % (name, "e" if side == "L" else "d") if side else name

# Studio pattern: a skeleton piece has a structural JOINT peg (the articulation, in the chain) AND
# its own DRAWING peg (this suffix) that the drawing binds to, so the piece keeps an independent
# translation/rotation/scale separate from the joint it hangs on.
_DRAW_PEG_SUFFIX = " (ctrl)"

# Exact (normalised) base name -> role. PT first, plus a few EN/ES synonyms.
_ROLE_SYNONYMS = {
    "torso": ["tronco", "torso", "corpo", "peito", "body"],
    "neck": ["pescoco", "neck", "cuello"],
    "head": ["cabeca", "head", "cabeza"],
    "clavicle": ["clavicula", "ombro", "shoulder", "hombro"],
    "upperarm": ["braco", "brazo", "upperarm", "arm", "umero"],
    "forearm": ["antebraco", "antebrazo", "forearm"],
    "hand": ["mao", "mano", "hand"],
    "pelvis": ["quadril", "pelvis", "hip", "bacia", "cadera"],
    # "perna" is the DPE library's word for the thigh — the piece below it is always a "canela"
    "thigh": ["coxa", "perna", "thigh", "muslo", "femur"],
    "shin": ["canela", "shin", "tibia", "espinilla"],
    "foot": ["pe", "pie", "foot"],
}
_CORE_TO_ROLE = {syn: role for role, syns in _ROLE_SYNONYMS.items() for syn in syns}

_LEFT = {"e", "esq", "esquerda", "l", "left", "izq"}
_RIGHT = {"d", "dir", "direita", "r", "right", "der"}


def _norm(name):
    """Return (core, side) for a piece name. side in {'L','R','?',None}, where '?' means the
    name marks a side but not WHICH one — the studio's own convention is a leading 1/2
    ('1braco', '2braco'), and which digit is screen-left varies per character, so geometry
    decides later."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\.\d+$", "", s)                      # strip a trailing .001 dup suffix
    side = None
    m = re.search(r"[._\- ](e|esq|esquerda|izq|l|left|d|dir|direita|der|r|right)$", s)
    if m:
        tok = m.group(1)
        side = "L" if tok in _LEFT else "R"
        s = s[: m.start()]
    else:
        m = re.match(r"([12])[._\- ]?(?=[a-z])", s)   # leading side digit
        if m:
            side = "?"
            s = s[m.end():]
    s = re.sub(r"[._\- ]?\d+$", "", s)                # any other trailing digits
    s = s.strip("._- ")
    return s, side


def _match_role(name):
    """Exact-core match -> (role, side) or None. Exact (not substring) keeps it safe:
    'perna_do_oculos' won't be read as a shin, 'cabelo' won't be a head."""
    core, side = _norm(name)
    role = _CORE_TO_ROLE.get(core)
    if role is None:
        return None
    if role not in _SIDED:
        side = None
    return role, side


# --------------------------------------------------------------------------- #
# Face ontology (Tier 2) — the dense head fan (eyes, brows, mouth, hair…). Unlike the
# skeleton, this is not a chain: every matched piece auto-parents straight onto the head
# joint, so it's a single leaf peg (no "(ctrl)" split — a leaf peg is already independent).
# --------------------------------------------------------------------------- #
_FACE_SIDED = {"eyebrow", "eye", "eyelid", "eyelash", "ear", "cheek", "braid", "pupil"}
_FACE_SYNONYMS = {
    "eyebrow": ["sobrancelha", "sob", "eyebrow", "ceja"],
    "eye": ["olho", "eye", "ojo", "globo"],
    "eyelid": ["palpebra", "eyelid", "parpado"],
    "pupil": ["pupila", "pupil", "iris"],
    "eyelash": ["cilio", "eyelash", "cilios", "pestana"],
    "nose": ["nariz", "nose"],
    "mouth": ["boca", "mouth"],
    "lip": ["labio", "lip", "labios"],
    "tooth": ["dente", "tooth", "teeth", "dentes"],
    "tongue": ["lingua", "tongue", "lengua"],
    "ear": ["orelha", "ear", "oreja"],
    "cheek": ["bochecha", "cheek", "mejilla"],
    "chin": ["queixo", "chin", "menton"],
    "mustache": ["bigode", "mustache", "bigote"],
    "beard": ["barba", "beard"],
    "hair": ["cabelo", "hair", "pelo", "cabello"],
    "bangs": ["franja", "bangs", "fleco"],
    "braid": ["tranca", "braid", "trenza"],
}
_FACE_CORE_TO_ROLE = {syn: role for role, syns in _FACE_SYNONYMS.items() for syn in syns}


def _match_face_role(name):
    """Exact-core match against the head-fan ontology -> (role, side) or None."""
    core, side = _norm(name)
    role = _FACE_CORE_TO_ROLE.get(core)
    if role is None:
        return None
    if role not in _FACE_SIDED:
        side = None
    return role, side


def _resolve_sides(cands, mid, pos, sided):
    """Hand out the left/right slots of one role. A name that says which side wins it; the rest
    are placed by where they actually are.

    A paired limb is lateral and roughly symmetric, so the candidates FURTHEST from the body
    axis are the real ones — that is what rejects a piece whose name lies (the skirt called
    "1antebraco.002" sits dead centre between two proper forearms). Rejected candidates are
    returned as leftovers and fall through to the accessory pass instead of poisoning the rig."""
    if not sided:
        return {None: cands[0][0]}, [ob for ob, _s in cands[1:]]
    slots, undecided = {}, []
    for ob, side in cands:
        if side in ("L", "R") and side not in slots:
            slots[side] = ob
        else:
            undecided.append(ob)
    free = sorted(s for s in ("L", "R") if s not in slots)      # 'L' before 'R'
    # Furthest from the axis first: that is what survives when a liar is in the running.
    ranked = sorted(undecided, key=lambda o: -abs(pos(o) - mid))
    take, leftover = ranked[:len(free)], ranked[len(free):]
    # Among the survivors, order decides the side — a character standing off-centre or
    # mid-stride puts both feet on the same side of the axis, so absolute position can't.
    for ob, side in zip(sorted(take, key=pos), free):
        slots[side] = ob
    return slots, leftover


def _assign_roles(objs, planar):
    """piece -> (role, side) for the skeleton, and the reverse map. Roles are filled per role
    so both sides of a pair are decided together."""
    axis = planar[0]
    xs = [_center_world(o)[axis] for o in objs]
    mid = (min(xs) + max(xs)) * 0.5

    by_role = {}
    for ob in objs:
        m = _match_role(ob.name)
        if m is not None:
            by_role.setdefault(m[0], []).append((ob, m[1]))

    matched, keymap, rejected = {}, {}, []
    for role, cands in by_role.items():
        slots, leftover = _resolve_sides(cands, mid, lambda o: _center_world(o)[axis],
                                         role in _SIDED)
        rejected += leftover
        for side, ob in slots.items():
            keymap[(role, side)] = ob
            matched[ob] = (role, side)
    return matched, keymap, rejected


# --------------------------------------------------------------------------- #
# Geometry — joint pivots from piece overlap
# --------------------------------------------------------------------------- #
def _aabb(ob):
    cs = [ob.matrix_world @ mathutils.Vector(c) for c in ob.bound_box]
    mn = mathutils.Vector((min(c[i] for c in cs) for i in range(3)))
    mx = mathutils.Vector((max(c[i] for c in cs) for i in range(3)))
    return mn, mx


def _center_world(ob):
    mn, mx = _aabb(ob)
    return (mn + mx) * 0.5


def _planar_axes(objs):
    """The two axes the character lives in (drop the thin/depth axis)."""
    ext = [0.0, 0.0, 0.0]
    for ob in objs:
        mn, mx = _aabb(ob)
        for i in range(3):
            ext[i] += mx[i] - mn[i]
    thin = ext.index(min(ext))
    return [i for i in range(3) if i != thin]


def _joint_world(child, parent, planar):
    """World point of the joint between child and parent = centroid of their bbox overlap in
    the character plane. Falls back to the child's centre when they don't overlap."""
    amn, amx = _aabb(child)
    bmn, bmx = _aabb(parent)
    cen = _center_world(child)
    for i in planar:
        lo = max(amn[i], bmn[i])
        hi = min(amx[i], bmx[i])
        if hi <= lo:
            return _center_world(child)        # no overlap -> own centre
        cen[i] = (lo + hi) * 0.5
    return cen


# --------------------------------------------------------------------------- #
# Peg world matrix (clone of nuclear_peg_graph helpers) + pivot placement
# --------------------------------------------------------------------------- #
def _peg_local_matrix(peg):
    from mathutils import Matrix, Vector, Euler
    p = Vector(peg.pivot)
    t = Vector(peg.translation)
    rot = Euler(peg.rotation, "XYZ").to_matrix().to_4x4()
    scale = Matrix.Diagonal(Vector((peg.scale[0], peg.scale[1], peg.scale[2], 1.0)))
    return Matrix.Translation(t + p) @ rot @ scale @ Matrix.Translation(-p)


def _peg_world_matrix(rig, idx):
    chain, i, guard = [], idx, 0
    while 0 <= i < len(rig.pegs) and guard <= len(rig.pegs):
        chain.append(i)
        i = rig.pegs[i].parent_index
        guard += 1
    m = mathutils.Matrix()
    for j in reversed(chain):
        m = m @ _peg_local_matrix(rig.pegs[j])
    return m


def _set_pivot_world(rig, peg_index, world_pt):
    """Place a peg's pivot at a world point, expressed in its parent's frame (so the peg
    rotates in place, not orbiting the parent)."""
    peg = rig.pegs[peg_index]
    parent = peg.parent_index
    pw = _peg_world_matrix(rig, parent) if 0 <= parent < len(rig.pegs) else mathutils.Matrix.Identity(4)
    peg.pivot = pw.inverted() @ world_pt


# --------------------------------------------------------------------------- #
# Builder core (validated headless vs Carolina)
# --------------------------------------------------------------------------- #
def _topo_order(pegs):
    by_name = {p["name"]: p for p in pegs}
    ordered, placed = [], set()

    def emit(p, stack):
        nm = p["name"]
        if nm in placed or nm in stack:
            return
        parent = p.get("parent")
        if parent and parent in by_name and parent not in placed:
            emit(by_name[parent], stack | {nm})
        placed.add(nm)
        ordered.append(p)

    for p in pegs:
        emit(p, set())
    return ordered


def _bind(ob, rig, peg_name):
    """One Follow Peg constraint binding ob -> peg (fresh, so set-inverse keeps its pose)."""
    for c in list(ob.constraints):
        if c.type == "FOLLOW_PEG":
            ob.constraints.remove(c)
    con = ob.constraints.new("FOLLOW_PEG")
    con.rig = rig
    if peg_name:
        con.peg_name = peg_name
    return con


def build_rig_from_spec(spec):
    rig = bpy.data.pegrigs.new(spec.get("rig_name") or "PegRig")
    name_to_index = {}
    for p in _topo_order(spec["pegs"]):
        parent = p.get("parent")
        parent_index = name_to_index.get(parent, -1) if parent else -1
        peg = rig.pegs.new(p["name"], parent_index=parent_index)
        name_to_index[p["name"]] = len(rig.pegs) - 1
        if peg.name != p["name"]:
            name_to_index[peg.name] = len(rig.pegs) - 1
    for p in spec["pegs"]:
        idx = name_to_index[p["name"]]
        peg = rig.pegs[idx]
        peg.pivot = p.get("pivot", (0, 0, 0))
    return rig, name_to_index


# --------------------------------------------------------------------------- #
# Helpers shared by the operators
# --------------------------------------------------------------------------- #
def _gp_targets(context):
    sel = [o for o in context.selected_objects if o.type == "GREASEPENCIL"]
    if len(sel) >= 2:
        return sel
    return [o for o in context.view_layer.objects if o.type == "GREASEPENCIL" and o.visible_get()]


def _followpeg(ob):
    for c in ob.constraints:
        if c.type == "FOLLOW_PEG":
            return c
    return None


def _peg_index_of(ob):
    """(rig, peg_index) the object follows, or (rig, -1) loose, or (None, -1)."""
    con = _followpeg(ob)
    if con is None or con.rig is None:
        return None, -1
    return con.rig, con.rig.pegs.find(con.peg_name) if con.peg_name else -1


def _grouped_layout(rig):
    """Ask the Peg Graph to (re)compute a body-region grouped layout for this rig, so opening the
    graph shows tidy horizontal frames instead of a vertical pile. Best-effort: silently skips if the
    Peg Graph module is unavailable."""
    try:
        import nuclear_peg_graph as npg
        npg.compute_grouped_layout(rig)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Armature -> PegRig conversion
# --------------------------------------------------------------------------- #
# Legacy characters were rigged with a Grease Pencil Armature modifier: the chain and the
# pivots were already approved by the animator, and every piece declares which bone drives it
# through its VERTEX GROUPS. That is the whole mapping — no per-character name table needed:
#
#   * one JOINT peg per bone kept (pivot = the bone head in world space, exactly where the
#     animator put it), the parenting copied from the bone hierarchy;
#   * one DRAWING peg per piece under the joint its vertex group names;
#   * bones nothing routes through are pruned; disconnected bone islands (a head chain drawn
#     apart from the body chain) are re-anchored onto the nearest bone of the main island.
#
# Two vertex groups on one piece mean one of two things, told apart by name:
#   * mirrored bones (1pe/2pe, perna.e/perna.d) -> the piece was duplicated for both sides and
#     kept both groups. The competing pieces are matched to the candidate joints by their
#     left-to-right order in the character plane;
#   * anything else (a piece spanning eye + pupil) -> it binds to the candidates' lowest
#     common ancestor, the deepest bone that rigidly carries all of them.

def _mirror_core(name):
    """Name stripped of side markers, so mirrored bones collapse onto one key.
    '1pe' / '2pe' -> 'pe'; 'perna.e' / 'perna.d' -> 'perna'."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\.\d+$", "", s)                      # a trailing .001 duplicate suffix
    s = re.sub(r"^\d+[._\- ]?", "", s)                # a leading side digit ('1pe')
    core, _side = _norm(s)                            # trailing side token / digits
    return core


def _bone_ancestry(parent_of, name):
    """[name, parent, …, root]."""
    chain, seen = [], set()
    while name is not None and name not in seen:
        seen.add(name)
        chain.append(name)
        name = parent_of.get(name)
    return chain


def _lowest_common_ancestor(parent_of, names):
    chains = [_bone_ancestry(parent_of, n) for n in names]
    common = set(chains[0])
    for c in chains[1:]:
        common &= set(c)
    if not common:
        return None
    # deepest = the one furthest from the root along the first chain
    return min((b for b in chains[0] if b in common), key=lambda b: chains[0].index(b))


def _armature_of(objs):
    """The armature driving these pieces: the one most of them are modified by, else the
    single armature in the file."""
    votes = {}
    for ob in objs:
        for m in ob.modifiers:
            if m.type == "GREASE_PENCIL_ARMATURE" and m.object is not None:
                votes[m.object] = votes.get(m.object, 0) + 1
    if votes:
        return max(votes, key=votes.get)
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    return arms[0] if len(arms) == 1 else None


def _resolve_bindings(arm, objs, planar):
    """piece -> bone name, plus the pieces we could not place. Pure name/geometry reasoning;
    nothing is modified."""
    bones = {b.name: b for b in arm.data.bones}
    parent_of = {b.name: (b.parent.name if b.parent else None) for b in arm.data.bones}
    head = {n: arm.matrix_world @ bones[n].head_local for n in bones}

    cands = {ob: [g.name for g in ob.vertex_groups if g.name in bones] for ob in objs}
    bind, loose, mirrored = {}, [], {}
    for ob, cs in cands.items():
        if not cs:
            loose.append(ob)
        elif len(cs) == 1:
            bind[ob] = cs[0]
        elif len({_mirror_core(c) for c in cs}) == 1:
            mirrored.setdefault(frozenset(cs), []).append(ob)   # duplicated for both sides
        else:
            # the piece's own name may point at one of them ('1olho' among eye + pupil)
            own = _mirror_core(ob.name)
            named = [c for c in cs if _mirror_core(c) == own]
            bind[ob] = named[0] if len(named) == 1 else (_lowest_common_ancestor(parent_of, cs) or cs[0])

    # Mirrored sets: absolute distance to the bone head lies (the drawings sit offset as a
    # block), so match by left-to-right order instead — leftmost piece to leftmost joint.
    axis = planar[0]
    for cs, obs in mirrored.items():
        obs_sorted = sorted(obs, key=lambda o: _center_world(o)[axis])
        cs_sorted = sorted(cs, key=lambda c: head[c][axis])
        for i, ob in enumerate(obs_sorted):
            bind[ob] = cs_sorted[i] if i < len(cs_sorted) else _lowest_common_ancestor(parent_of, cs)
    return bind, loose, head, parent_of


def _kept_bone_tree(parent_of, head, used):
    """Bones to materialise: every bone on the path from a used bone up to its root. Returns
    (ordered bone names, parent map) with disconnected islands re-anchored onto the nearest
    bone of the largest island, so a head chain drawn apart still follows the body."""
    keep = set()
    for u in used:
        keep.update(_bone_ancestry(parent_of, u))

    roots = [b for b in keep if parent_of.get(b) is None]
    island = {}                                   # root -> its bones
    for b in keep:
        island.setdefault(_bone_ancestry(parent_of, b)[-1], []).append(b)
    order = sorted(roots, key=lambda r: -len(island[r]))

    parent = {b: parent_of.get(b) for b in keep}
    anchored = set(island[order[0]]) if order else set()
    for r in order[1:]:
        near = min(anchored, key=lambda b: (head[b] - head[r]).length, default=None)
        parent[r] = near
        anchored.update(island[r])

    ordered, placed = [], set()
    for b in keep:                                # parents before children
        stack = []
        cur = b
        while cur is not None and cur not in placed:
            stack.append(cur)
            cur = parent.get(cur)
        for n in reversed(stack):
            placed.add(n)
            ordered.append(n)
    return ordered, parent, order[0] if order else None


def _bone_labels(bones, head, axis, parent):
    """bone -> friendly joint name, for the bones whose OWN name is recognisable AND resolve to
    exactly the expected count for their role (one per side).

    A legacy armature carries a deform bone next to its joint bone ('1braco' hanging off
    '1braco.001') and both read as an upper arm. The pair is told apart by structure: the one
    with children IS the joint, the leaf is the deform. When that reading doesn't produce the
    exact expected count the role is left alone — an animator's bone name is at least unique and
    honest, while a wrong 'Braço.e' is worse than no label."""
    has_kids = set(parent.values())
    by_role = {}
    for b in bones:
        m = _match_role(b)
        if m is not None:
            by_role.setdefault(m[0], []).append((b, m[1]))
    xs = [head[b][axis] for b in bones]
    mid = (min(xs) + max(xs)) * 0.5 if xs else 0.0
    span = (max(xs) - min(xs)) if xs else 0.0

    out = {}
    for role, cands in by_role.items():
        sided = role in _SIDED
        want = 2 if sided else 1
        joints = [c for c in cands if c[0] in has_kids]
        pool = next((p for p in (joints, cands) if len(p) == want), None)
        if pool is None:
            continue
        if sided and abs(head[pool[0][0]][axis] - head[pool[1][0]][axis]) < span * 0.05:
            continue                      # both on the same limb: a joint/deform pair, not a pair of sides
        slots, _left = _resolve_sides(pool, mid, lambda b: head[b][axis], sided)
        for side, b in slots.items():
            out[b] = _side_label(_ROLE_LABEL.get(role, role), side)
    return out


def build_pegrig_from_armature(arm=None, objs=None, rig_name=None, drop_armature=True):
    """Convert an armature-rigged cut-out character into a PegRig, in place. Returns a report
    dict. Idempotent: re-running replaces any previous rig and its Follow Peg constraints."""
    if objs is None:
        objs = [o for o in bpy.data.objects if o.type == "GREASEPENCIL"]
    if arm is None:
        arm = _armature_of(objs)
    if arm is None or not objs:
        raise ValueError("need one armature and at least one Grease Pencil piece")
    planar = _planar_axes(objs)

    bind, loose, head, parent_of = _resolve_bindings(arm, objs, planar)

    # Wipe any previous conversion, then drop the armature deform BEFORE binding pegs, so the
    # pegs capture the drawing's own rest position (the armature is rarely exactly at rest).
    for ob in bpy.data.objects:
        for c in list(ob.constraints):
            if c.type == "FOLLOW_PEG":
                ob.constraints.remove(c)
    for r in list(bpy.data.pegrigs):
        bpy.data.pegrigs.remove(r)
    if drop_armature:
        for ob in objs:
            for m in list(ob.modifiers):
                if m.type == "GREASE_PENCIL_ARMATURE" and m.object is arm:
                    ob.modifiers.remove(m)
        arm.hide_viewport = True
        arm.hide_render = True
    bpy.context.view_layer.update()

    if rig_name is None:
        rig_name = re.sub(r"^(armature|arm|rig)[_.\- ]*", "", arm.name, flags=re.I) or "PegRig"
    rig = bpy.data.pegrigs.new(rig_name)

    ordered, bone_parent, main_root = _kept_bone_tree(parent_of, head, set(bind.values()))
    label = _bone_labels(ordered, head, planar[0], bone_parent)
    idx = {}
    for b in ordered:                                     # 1) joint pegs, one per bone kept
        p = bone_parent.get(b)
        rig.pegs.new(label.get(b, b), parent_index=idx.get(p, -1))
        idx[b] = len(rig.pegs) - 1
    for b in ordered:
        _set_pivot_world(rig, idx[b], head[b])

    for ob in sorted(bind, key=lambda o: o.name):         # 2) one drawing peg per piece
        b = bind[ob]
        peg = rig.pegs.new(ob.name + _DRAW_PEG_SUFFIX, parent_index=idx[b])
        _set_pivot_world(rig, len(rig.pegs) - 1, head[b])
        _bind(ob, rig, peg.name)

    for ob in sorted(loose, key=lambda o: o.name):        # 3) unrecognised: loose on the root
        peg = rig.pegs.new(ob.name, parent_index=idx.get(main_root, -1))
        _set_pivot_world(rig, len(rig.pegs) - 1, _center_world(ob))
        _bind(ob, rig, peg.name)

    rig.use_fake_user = True
    rig.active_peg_index = idx.get(main_root, 0)
    _grouped_layout(rig)
    bpy.context.view_layer.update()
    return {"rig": rig.name, "pegs": len(rig.pegs), "bound": len(bind),
            "joints": len(ordered), "loose": [o.name for o in loose],
            "pruned": sorted(set(parent_of) - set(ordered)),
            "bind": {o.name: label.get(b, b)
                     for o, b in sorted(bind.items(), key=lambda t: t[0].name)}}


class OBJECT_OT_nuclear_rig_from_armature(Operator):
    bl_idname = "object.nuclear_rig_from_armature"
    bl_label = "Convert Armature to Pegs"
    bl_description = ("Rebuild a legacy armature-rigged character as a PegRig: bones become "
                      "joint pegs at their own pivots, each drawing follows the joint its "
                      "vertex group names, and the armature is switched off")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and any(o.type == "ARMATURE" for o in bpy.data.objects)

    def execute(self, context):
        objs = _gp_targets(context)
        name = context.scene.nuclear_rig_name
        try:
            # the untouched default means "name it after the armature"
            rep = build_pegrig_from_armature(objs=objs,
                                             rig_name=None if name in ("", "PegRig") else name)
        except ValueError as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}
        self.report({"INFO"},
                    f"Rig '{rep['rig']}': {rep['joints']} joints + {rep['bound']} drawings "
                    f"+ {len(rep['loose'])} loose ({rep['pegs']} pegs)")
        return {"FINISHED"}


# --------------------------------------------------------------------------- #
# Operator: Auto-Build Skeleton
# --------------------------------------------------------------------------- #
class OBJECT_OT_nuclear_rig_auto_skeleton(Operator):
    bl_idname = "object.nuclear_rig_auto_skeleton"
    bl_label = "Auto-Build Skeleton"
    bl_description = ("Match the drawing pieces to a humanoid skeleton by name and build the "
                      "spine + limbs in one click; head-fan pieces (eyes/brows/mouth/hair) "
                      "auto-parent under the head; anything else stays loose to be linked")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def execute(self, context):
        objs = _gp_targets(context)
        if not objs:
            self.report({"ERROR"}, "No Grease Pencil pieces found")
            return {"CANCELLED"}
        planar = _planar_axes(objs)

        matched, keymap, _rejected = _assign_roles(objs, planar)
        if not matched:
            self.report({"ERROR"}, "No skeleton pieces recognised by name (torso/arm/leg/…)")
            return {"CANCELLED"}

        # --- Resolve the joint nodes: one per matched piece, PLUS structural joints (pelvis/shoulder)
        #     synthesised on demand when a limb routes through them. A non-structural role with no
        #     drawn piece collapses (head parents straight to the torso if the neck wasn't drawn); a
        #     structural role does NOT collapse — it materialises as a drawing-less articulation peg. ---
        nodes = {}                        # (role, side) -> {"ob", "role", "side", "parent"}

        def ensure_node(role, side):
            side = side if role in _SIDED else None
            ob = keymap.get((role, side))
            if ob is None and role not in _STRUCT_JOINTS:
                pr = _PARENT_ROLE[role]           # collapse past an undrawn, non-structural role
                return ensure_node(pr, side) if pr is not None else None
            key = (role, side)
            if key not in nodes:
                pr = _PARENT_ROLE[role]
                nodes[key] = {"ob": ob, "role": role, "side": side,
                              "parent": ensure_node(pr, side) if pr is not None else None}
            return key

        for role_side in list(keymap):
            ensure_node(*role_side)

        # Anchor for the face fan (Tier 2): the head joint, or its nearest DRAWN ancestor
        # (neck, then torso) if no "cabeca" piece exists — same collapse rule as the chain.
        face_anchor_key = ensure_node("head", None)

        def node_name(key):
            n = nodes[key]
            return _side_label(_ROLE_LABEL.get(n["role"], n["role"]), n["side"])

        # 1) Joint chain: one structural peg per node, parented via the resolved ontology. Drawn nodes
        #    carry the articulation pivots (hip/knee/…); no drawing binds to a structural joint.
        pegs = [{"name": node_name(k),
                 "parent": node_name(nodes[k]["parent"]) if nodes[k]["parent"] is not None else None,
                 "pivot": (0, 0, 0)} for k in nodes]
        spec = {"rig_name": context.scene.nuclear_rig_name or "PegRig", "pegs": pegs}
        rig, j_idx = build_rig_from_spec(spec)

        # Joint pivots. A drawn piece pivots on its articulation with the nearest DRAWN ancestor (skip
        # structural joints — they have no geometry). A structural joint sits at the mean of its direct
        # children's sockets (the hip = midpoint of the two thigh sockets).
        def drawn_ancestor_ob(key):
            p = nodes[key]["parent"]
            while p is not None:
                if nodes[p]["ob"] is not None:
                    return nodes[p]["ob"]
                p = nodes[p]["parent"]
            return None

        pivot_world, children_of = {}, {}
        for key, n in nodes.items():
            if n["parent"] is not None:
                children_of.setdefault(n["parent"], []).append(key)
            if n["ob"] is not None:
                ref = drawn_ancestor_ob(key)
                pivot_world[key] = _joint_world(n["ob"], ref, planar) if ref else _center_world(n["ob"])

        def _depth(key):
            d, p = 0, nodes[key]["parent"]
            while p is not None:
                d, p = d + 1, nodes[p]["parent"]
            return d

        for key in sorted((k for k, nn in nodes.items() if nn["ob"] is None), key=_depth, reverse=True):
            pts = [pivot_world[c] for c in children_of.get(key, []) if c in pivot_world]
            acc = mathutils.Vector((0, 0, 0))
            for pt in pts:
                acc = acc + pt
            pivot_world[key] = acc / len(pts) if pts else acc
        for key in nodes:
            _set_pivot_world(rig, j_idx[node_name(key)], pivot_world[key])

        # 2) Each DRAWN piece also gets its OWN drawing peg (independent T/R/S), a child of its joint;
        #    the drawing binds to THIS peg. Structural joints stay drawing-less.
        n_struct = 0
        for key, n in nodes.items():
            if n["ob"] is None:
                n_struct += 1
                continue
            ob = n["ob"]
            peg = rig.pegs.new(ob.name + _DRAW_PEG_SUFFIX, parent_index=j_idx[node_name(key)])
            _bind(ob, rig, peg.name)
            _set_pivot_world(rig, len(rig.pegs) - 1, _center_world(ob))

        # 3) Face fan: pieces recognised by the head-fan ontology (eyes, brows, mouth, hair…)
        #    auto-parent onto the head joint (or its nearest drawn ancestor) instead of falling
        #    loose. Geometric pivot against that anchor, same as everywhere else. Sides are
        #    resolved by position, like the limbs, so '1olho'/'2olho' become Olho.e/Olho.d.
        anchor_ob = nodes[face_anchor_key]["ob"] if face_anchor_key is not None else None
        anchor_peg_idx = j_idx[node_name(face_anchor_key)] if face_anchor_key is not None else -1
        face_matched = set()
        if anchor_ob is not None:
            axis = planar[0]
            xs = [_center_world(o)[axis] for o in objs]
            mid = (min(xs) + max(xs)) * 0.5
            by_face = {}
            for ob in objs:
                m = _match_face_role(ob.name)
                if ob not in matched and m is not None:
                    by_face.setdefault(m[0], []).append((ob, m[1]))
            for role, cands in by_face.items():
                slots, _leftover = _resolve_sides(cands, mid, lambda o: _center_world(o)[axis],
                                                  role in _FACE_SIDED)
                for side, ob in slots.items():
                    peg = rig.pegs.new(_side_label(_FACE_LABEL.get(role, role), side),
                                       parent_index=anchor_peg_idx)
                    _bind(ob, rig, peg.name)
                    _set_pivot_world(rig, len(rig.pegs) - 1, _joint_world(ob, anchor_ob, planar))
                    face_matched.add(ob)

        # 4) Anything still unmatched: its own peg on the composite (root). A leaf, so a single
        #    peg is already its independent controller; linkable later.
        extra = 0
        for ob in objs:
            if ob in matched or ob in face_matched:
                continue
            peg = rig.pegs.new(ob.name, parent_index=-1)
            _bind(ob, rig, peg.name)
            _set_pivot_world(rig, len(rig.pegs) - 1, _center_world(ob))
            extra += 1

        torso = rig.pegs.find(_ROLE_LABEL["torso"]) if ("torso", None) in keymap else -1
        rig.active_peg_index = max(torso, 0)
        _grouped_layout(rig)
        context.view_layer.update()
        n_drawn = len(matched)
        n_face = len(face_matched)
        self.report({"INFO"},
                    f"Rig '{rig.name}': {n_drawn} drawn joints + {n_struct} structural joints "
                    f"(pelvis/shoulder) + {n_drawn} drawing pegs + {n_face} face pieces + "
                    f"{extra} loose — select a cluster + a parent and Link")
        return {"FINISHED"}


# --------------------------------------------------------------------------- #
# Operator: Link Selected to Active
# --------------------------------------------------------------------------- #
def _cycle(rig, child_idx, new_parent_idx):
    i, guard = new_parent_idx, 0
    while 0 <= i < len(rig.pegs) and guard <= len(rig.pegs):
        if i == child_idx:
            return True
        i = rig.pegs[i].parent_index
        guard += 1
    return False


class OBJECT_OT_nuclear_rig_link_to_parent(Operator):
    bl_idname = "object.nuclear_rig_link_to_parent"
    bl_label = "Link Selected to Active"
    bl_description = ("Make every selected drawing follow the active drawing's peg "
                      "(joint pivots auto-placed). Batch-attach a fan to one parent")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        act = context.active_object
        return (context.mode == "OBJECT" and act is not None and act.type == "GREASEPENCIL"
                and any(o.type == "GREASEPENCIL" and o is not act for o in context.selected_objects))

    def execute(self, context):
        active = context.active_object
        children = [o for o in context.selected_objects
                    if o.type == "GREASEPENCIL" and o is not active]
        if not children:
            self.report({"ERROR"}, "Select children + an active parent drawing")
            return {"CANCELLED"}
        planar = _planar_axes([active] + children)

        # Resolve (or bootstrap) the rig and the ATTACH peg under the active object. Children should
        # follow the active piece's structural joint, so if the active drawing follows a drawing peg
        # (a leaf under a joint), attach under that joint; otherwise attach under the active's own peg.
        rig, act_dpeg = _peg_index_of(active)
        if rig is None:
            rig = bpy.data.pegrigs.new(context.scene.nuclear_rig_name or "PegRig")
        if act_dpeg < 0:
            rig.pegs.new(active.name, parent_index=-1)
            act_dpeg = rig.pegs.find(active.name)
            _bind(active, rig, active.name)
            _set_pivot_world(rig, act_dpeg, _center_world(active))
            attach_idx = act_dpeg
        else:
            jp = rig.pegs[act_dpeg].parent_index
            attach_idx = jp if jp >= 0 else act_dpeg
        attach_peg_name = rig.pegs[attach_idx].name

        linked = 0
        for ch in children:
            ch_rig, ch_idx = _peg_index_of(ch)
            attach_idx = rig.pegs.find(attach_peg_name)      # re-fetch (array may realloc)
            if ch_rig is rig and ch_idx >= 0:
                if not _cycle(rig, ch_idx, attach_idx):
                    rig.pegs[ch_idx].parent_index = attach_idx
            else:
                rig.pegs.new(ch.name, parent_index=attach_idx)
                ch_idx = len(rig.pegs) - 1
                _bind(ch, rig, ch.name)
            _set_pivot_world(rig, ch_idx, _joint_world(ch, active, planar))
            linked += 1

        rig.active_peg_index = rig.pegs.find(attach_peg_name)
        _grouped_layout(rig)
        context.view_layer.update()
        self.report({"INFO"}, f"Linked {linked} piece(s) under '{active.name}'")
        return {"FINISHED"}


# --------------------------------------------------------------------------- #
# Panel
# --------------------------------------------------------------------------- #
class VIEW3D_PT_nuclear_rig_auto(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Rig"
    bl_label = "Auto Rig"

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "nuclear_rig_name", text="Name")
        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("object.nuclear_rig_auto_skeleton", icon="OUTLINER_OB_ARMATURE")
        if any(o.type == "ARMATURE" for o in bpy.data.objects):
            col.operator("object.nuclear_rig_from_armature", icon="BONE_DATA")
        layout.separator()
        layout.label(text="Select fan + active parent:", icon="INFO")
        layout.operator("object.nuclear_rig_link_to_parent", icon="LINKED")
        layout.separator()
        layout.label(text="Refine in the Peg Graph editor", icon="NODETREE")


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #
_classes = (
    OBJECT_OT_nuclear_rig_from_armature,
    OBJECT_OT_nuclear_rig_auto_skeleton,
    OBJECT_OT_nuclear_rig_link_to_parent,
    VIEW3D_PT_nuclear_rig_auto,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.nuclear_rig_name = StringProperty(name="Rig Name", default="PegRig")


def unregister():
    del bpy.types.Scene.nuclear_rig_name
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
