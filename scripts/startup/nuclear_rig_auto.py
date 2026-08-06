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
_STRUCT_JOINTS = {
    "pelvis":   {"label": "Quadril", "sided": False},
    "clavicle": {"label": "Ombro",   "sided": True},
}

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
    "thigh": ["coxa", "thigh", "muslo", "femur"],
    "shin": ["canela", "shin", "tibia", "espinilla"],
    "foot": ["pe", "pie", "foot"],
}
_CORE_TO_ROLE = {syn: role for role, syns in _ROLE_SYNONYMS.items() for syn in syns}

_LEFT = {"e", "esq", "esquerda", "l", "left", "izq"}
_RIGHT = {"d", "dir", "direita", "r", "right", "der"}


def _norm(name):
    """Return (core, side) for a piece name. side in {'L','R',None}."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\.\d+$", "", s)                      # strip a trailing .001 dup suffix
    side = None
    m = re.search(r"[._\- ](e|esq|esquerda|izq|l|left|d|dir|direita|der|r|right)$", s)
    if m:
        tok = m.group(1)
        side = "L" if tok in _LEFT else "R"
        s = s[: m.start()]
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


# --------------------------------------------------------------------------- #
# Geometry — joint pivots from piece overlap
# --------------------------------------------------------------------------- #
# Union bounding boxes, cached for one operator run (see _clear_union_cache).
_UNION_BOX_CACHE = {}


def _clear_union_cache():
    _UNION_BOX_CACHE.clear()


def _union_box_local(ob):
    """Local-space bounding box corners covering EVERY drawing the object holds.

    `ob.bound_box` is the evaluated box, i.e. whichever cell the playhead is showing -- so a rig
    built on frame 40 places its joints and pivots differently from the same rig built on frame 1.
    Walking all keyframes of all layers makes the result depend on the artwork instead of the
    playhead. Returns None when there is no stroke data to measure."""
    data = getattr(ob, "data", None)
    if ob.type != 'GREASEPENCIL' or data is None:
        return None

    lo = [float('inf')] * 3
    hi = [float('-inf')] * 3
    for layer in data.layers:
        for frame in layer.frames:
            drawing = getattr(frame, "drawing", None)
            if drawing is None:
                continue
            try:
                strokes = drawing.strokes
            except Exception:
                continue
            for stroke in (strokes or []):
                points = stroke.points
                n = len(points)
                if n == 0:
                    continue
                step = max(1, n // 256)  # this only feeds a bounding box
                for i in range(0, n, step):
                    pos = points[i].position
                    for axis in range(3):
                        v = pos[axis]
                        if v < lo[axis]:
                            lo[axis] = v
                        if v > hi[axis]:
                            hi[axis] = v

    if lo[0] > hi[0]:
        return None
    return [(lo[0] if x else hi[0], lo[1] if y else hi[1], lo[2] if z else hi[2])
            for x in (1, 0) for y in (1, 0) for z in (1, 0)]


def _aabb(ob):
    key = ob.as_pointer()
    corners = _UNION_BOX_CACHE.get(key)
    if corners is None:
        corners = _union_box_local(ob) or list(ob.bound_box)
        _UNION_BOX_CACHE[key] = corners
    cs = [ob.matrix_world @ mathutils.Vector(c) for c in corners]
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


def _reparent_keep_transform(rig, peg_index, new_parent_index):
    """Hang a peg under a different parent without moving it or its pivot (local copy of the
    Peg Graph helper, so this module also works as a stand-alone add-on).

    `translation` and `pivot` live in the PARENT's frame, so swapping the parent reinterprets them
    against a different matrix and the peg jumps. With M = parent_world_new^-1 * parent_world_old
    and the local matrix T(t+p)*R*S*T(-p): p stays put, t' = M @ (t + p) - p, R'*S' = M3 * R * S.

    Limitation: a frame change that composes non-uniform scale with rotation carries shear, which
    euler + per-axis scale cannot express -- the pivot lands exactly, the piece still shifts."""
    if not (0 <= peg_index < len(rig.pegs)):
        return False
    peg = rig.pegs[peg_index]
    if peg.parent_index == new_parent_index:
        return False

    def parent_world(index):
        return (_peg_world_matrix(rig, index) if 0 <= index < len(rig.pegs)
                else mathutils.Matrix.Identity(4))

    world_old = parent_world(peg.parent_index)
    world_new = parent_world(new_parent_index)
    try:
        change = world_new.inverted() @ world_old
    except ValueError:
        peg.parent_index = new_parent_index
        return True

    from mathutils import Euler, Matrix, Vector
    pivot = Vector(peg.pivot)
    translation = Vector(peg.translation)
    basis = (change.to_3x3()
             @ Euler(peg.rotation, "XYZ").to_matrix()
             @ Matrix.Diagonal(Vector(peg.scale)))

    # `decompose` separates rotation from scale properly; `to_euler` alone assumes an orthogonal
    # matrix and returns nonsense once a non-uniform scale is in the product.
    _loc, rotation, scale = basis.to_4x4().decompose()

    peg.parent_index = new_parent_index
    peg.translation = (change @ (translation + pivot)) - pivot
    peg.rotation = rotation.to_euler("XYZ", Euler(peg.rotation, "XYZ"))
    peg.scale = scale
    return True


def _has_placed_pivot(peg):
    """True when this peg carries a pivot someone put there (a fresh peg starts at the origin)."""
    return any(abs(v) > 1e-9 for v in peg.pivot)


def _set_pivot_world(rig, peg_index, world_pt):
    """Place a peg's pivot at a world point, expressed in its parent's frame (so the peg
    rotates in place, not orbiting the parent).

    The local matrix is T(t+p)*R*S*T(-p), so the rotation centre is parent_world @ (pivot +
    translation): the translation has to come back out, or a peg that has been dragged ends up
    turning about a point offset from the joint by exactly that drag."""
    peg = rig.pegs[peg_index]
    parent = peg.parent_index
    pw = _peg_world_matrix(rig, parent) if 0 <= parent < len(rig.pegs) else mathutils.Matrix.Identity(4)
    peg.pivot = (pw.inverted() @ world_pt) - mathutils.Vector(peg.translation)


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
        _clear_union_cache()  # measure the artwork as it stands now, not as a past run saw it
        objs = _gp_targets(context)
        if not objs:
            self.report({"ERROR"}, "No Grease Pencil pieces found")
            return {"CANCELLED"}
        planar = _planar_axes(objs)

        matched = {}                      # ob -> (role, side)
        keymap = {}                       # (role, side) -> ob
        for ob in objs:
            r = _match_role(ob.name)
            if r is not None and r not in keymap:   # first piece wins a role slot
                matched[ob] = r
                keymap[r] = ob
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
            if n["ob"] is not None:
                return n["ob"].name
            lbl = _STRUCT_JOINTS[n["role"]]["label"]
            return f"{lbl}.{'e' if n['side'] == 'L' else 'd'}" if n["side"] else lbl

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
            dname = ob.name + _DRAW_PEG_SUFFIX
            rig.pegs.new(dname, parent_index=j_idx[node_name(key)])
            dpeg_idx = len(rig.pegs) - 1
            _bind(ob, rig, dname)
            _set_pivot_world(rig, dpeg_idx, _center_world(ob))

        # 3) Face fan: pieces recognised by the head-fan ontology (eyes, brows, mouth, hair…)
        #    auto-parent onto the head joint (or its nearest drawn ancestor) instead of falling
        #    loose. Geometric pivot against that anchor, same as everywhere else.
        anchor_ob = nodes[face_anchor_key]["ob"] if face_anchor_key is not None else None
        anchor_peg_idx = j_idx[node_name(face_anchor_key)] if face_anchor_key is not None else -1
        face_matched = set()
        if anchor_ob is not None:
            for ob in objs:
                if ob in matched or _match_face_role(ob.name) is None:
                    continue
                rig.pegs.new(ob.name, parent_index=anchor_peg_idx)
                peg_idx = len(rig.pegs) - 1
                _bind(ob, rig, ob.name)
                _set_pivot_world(rig, peg_idx, _joint_world(ob, anchor_ob, planar))
                face_matched.add(ob)

        # 4) Anything still unmatched: its own peg on the composite (root). A leaf, so a single
        #    peg is already its independent controller; linkable later.
        extra = 0
        for ob in objs:
            if ob in matched or ob in face_matched:
                continue
            rig.pegs.new(ob.name, parent_index=-1)
            peg_idx = len(rig.pegs) - 1
            _bind(ob, rig, ob.name)
            _set_pivot_world(rig, peg_idx, _center_world(ob))
            extra += 1

        rig.active_peg_index = rig.pegs.find(keymap[("torso", None)].name) if ("torso", None) in keymap else 0
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
        _clear_union_cache()  # measure the artwork as it stands now, not as a past run saw it
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
            existing = ch_rig is rig and ch_idx >= 0
            if existing:
                if not _cycle(rig, ch_idx, attach_idx):
                    _reparent_keep_transform(rig, ch_idx, attach_idx)
            else:
                rig.pegs.new(ch.name, parent_index=attach_idx)
                ch_idx = len(rig.pegs) - 1
                _bind(ch, rig, ch.name)
            # Re-parenting an existing peg must not move its pivot: the rigger may have placed it
            # on the joint by hand, and the guessed one is only a starting point for a NEW peg.
            if not (existing and _has_placed_pivot(rig.pegs[ch_idx])):
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
        layout.separator()
        layout.label(text="Select fan + active parent:", icon="INFO")
        layout.operator("object.nuclear_rig_link_to_parent", icon="LINKED")
        layout.separator()
        layout.label(text="Refine in the Peg Graph editor", icon="NODETREE")


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #
_classes = (
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
