# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Nuclear "Peg Graph": a node-editor view of a peg rig.

This is purely a VISUALIZATION/EDITING front-end for the native peg system (the ``PegRig``
data-block + ``Follow Peg`` constraints). The graph is *generated* from the rig (the source of
truth) by :func:`rebuild`, and edits made in the graph are written back to the rig by
``NuclearPegTree.update`` (fired by Blender when links change). A module-level ``_SYNCING`` guard
keeps those two directions from re-entering each other.

Node/socket model: every node has a single "controller" input. A link ``A.output -> B.input`` means
"B is controlled by A":
  * rig (composite) -> root peg   the peg is a root (``parent_index == -1``)
  * parent peg      -> child peg  sets ``child.parent_index``
  * peg             -> drawing    binds the drawing's Follow Peg constraint to that peg
  * rig (composite) -> drawing    the drawing is a member of the rig but follows no peg
                                  (Follow Peg constraint with the rig set and an empty peg name)

The "rig" node is a single composite hub (Toon Boom-style): every root peg and every loose member
drawing hangs from it. It owns no transform.
"""

import json
import math

import bpy
import gpu
import mathutils
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils
from bpy.types import NodeTree, Node, NodeSocket, Operator, Panel
from bpy.props import BoolProperty, PointerProperty, StringProperty

_TREE_ID = "NuclearPegTree"
_RIG_NODE_ID = "NuclearRigNode"
_PEG_NODE_ID = "NuclearPegNode"
_DRAWING_NODE_ID = "NuclearDrawingNode"
_SOCK_ID = "NuclearPegSocket"

# ID-property key under which the rig stores the Peg Graph layout (node positions + frames). Kept on
# the PegRig so the rigger's arrangement survives a graph rebuild (Sync) and -- because ID-properties
# are serialized with the datablock and copied on append/link -- travels with the rig into other
# files, where the node tree itself does not follow.
_LAYOUT_KEY = "nuclear_peg_graph_layout"

# Reentrancy guard between rebuild() (rig -> graph) and update() (graph -> rig).
_SYNCING = False


# -------------------------------------------------------------------------------------------------
# Socket / tree / nodes
# -------------------------------------------------------------------------------------------------

class NuclearPegSocket(NodeSocket):
    bl_idname = _SOCK_ID
    bl_label = "Peg"

    def draw(self, _context, layout, _node, text):
        layout.label(text=text)

    def draw_color(self, _context, _node):
        return (0.9, 0.6, 0.2, 1.0)


class NuclearPegTree(NodeTree):
    bl_idname = _TREE_ID
    bl_label = "Peg Graph"
    bl_icon = 'OUTLINER_OB_ARMATURE'

    rig: PointerProperty(
        type=bpy.types.PegRig,
        name="Peg Rig",
        description="Peg rig visualized by this graph",
    )

    def update(self):
        # Fired by Blender on topology changes (links added/removed). Write the graph back to the
        # rig, unless we are the ones rebuilding the graph from the rig.
        if _SYNCING:
            return
        _apply_graph_to_rig(self)


class _PegGraphNode:
    @classmethod
    def poll(cls, ntree):
        return ntree.bl_idname == _TREE_ID


class NuclearRigNode(_PegGraphNode, Node):
    """The rig's composite hub: root pegs and loose member drawings hang from it. No transform."""
    bl_idname = _RIG_NODE_ID
    bl_label = "Rig"
    bl_icon = 'OUTLINER_OB_ARMATURE'

    def init(self, _context):
        self.outputs.new(_SOCK_ID, "Composite")
        self.use_custom_color = True
        self.color = (0.18, 0.16, 0.10)

    def draw_label(self):
        rig = getattr(self.id_data, "rig", None)
        return rig.name if rig is not None else "Rig"


class NuclearPegNode(_PegGraphNode, Node):
    bl_idname = _PEG_NODE_ID
    bl_label = "Peg"
    bl_icon = 'EMPTY_AXIS'

    peg_name: StringProperty(name="Peg")

    def init(self, _context):
        self.inputs.new(_SOCK_ID, "Parent")
        self.outputs.new(_SOCK_ID, "Children")
        self.use_custom_color = True
        self.color = (0.28, 0.22, 0.12)

    def draw_label(self):
        return self.peg_name or "Peg"

    def draw_buttons(self, _context, layout):
        # Badge: flag pegs that drive a squash & stretch so they stand out in the graph.
        rig = getattr(self.id_data, "rig", None)
        if rig is None:
            return
        peg = rig.pegs.get(self.peg_name)
        if peg is not None and peg.use_squash:
            layout.label(text="Squash", icon='MOD_SIMPLEDEFORM')


def _cutter_invert_update(self, _context):
    """Toggling 'Invert Cutter' on a drawing node writes through to its native masks."""
    if _SYNCING:
        return
    tree = self.id_data
    if tree is not None:
        _apply_graph_to_rig(tree)


class NuclearDrawingNode(_PegGraphNode, Node):
    bl_idname = _DRAWING_NODE_ID
    bl_label = "Drawing"
    bl_icon = 'OUTLINER_OB_GREASEPENCIL'

    object_name: StringProperty(name="Object")
    # Polarity of this node's Cutter masks: off = keep inside the matte(s), on = keep outside.
    # Applies uniformly to every matte feeding the Cutter input (a union of same-polarity masks;
    # mixing polarities in one union is fragile in the GP mask pass, so it is one toggle per node).
    cutter_invert: BoolProperty(
        name="Invert Cutter",
        description="Show this drawing OUTSIDE the matte silhouette(s) instead of inside",
        default=False,
        update=_cutter_invert_update,
    )

    def init(self, _context):
        self.inputs.new(_SOCK_ID, "Peg")
        # Second input: a "Cutter" matte. Linking another drawing's Matte output here clips this
        # drawing to that drawing's silhouette (Toon Boom Cutter). Multi-input: several mattes can
        # feed one Cutter and their silhouettes union (the GP draw engine composites every native
        # cross-object mask of a layer into one mask buffer).
        self.inputs.new(_SOCK_ID, "Cutter", use_multi_input=True)
        # Output: lets this drawing act as a matte for another drawing's Cutter input.
        self.outputs.new(_SOCK_ID, "Matte")
        self.use_custom_color = True
        self.color = (0.12, 0.20, 0.28)

    def draw_label(self):
        return self.object_name or "Drawing"

    def draw_buttons(self, _context, layout):
        # Only meaningful when a matte feeds the Cutter input.
        if len(self.inputs) > 1 and self.inputs[1].links:
            layout.prop(self, "cutter_invert")


# -------------------------------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------------------------------

def _peg_depth(rig, index):
    """Number of ancestor pegs above `index` (root = 0)."""
    depth = 0
    pegs = rig.pegs
    guard = 0
    parent = pegs[index].parent_index
    while parent >= 0 and parent < len(pegs) and guard < len(pegs):
        depth += 1
        parent = pegs[parent].parent_index
        guard += 1
    return depth


def _bound_objects(rig):
    """Yield (object, peg_name) for every object whose Follow Peg constraint targets `rig`."""
    for ob in bpy.data.objects:
        for con in ob.constraints:
            if con.type == 'FOLLOW_PEG' and con.rig == rig:
                yield ob, con.peg_name
                break


def _followpeg_constraint(ob):
    for con in ob.constraints:
        if con.type == 'FOLLOW_PEG':
            return con
    return None


def _cutter_modifier(ob):
    """The object's legacy Grease Pencil Mask (Cutter) injection modifier, or None.

    Superseded by native cross-object masks; kept only to read and migrate old files.
    """
    for mod in ob.modifiers:
        if mod.type == 'GREASE_PENCIL_MASK':
            return mod
    return None


def _leaf_layers(ob):
    """The object's Grease Pencil leaf layers (where native masks live), or []."""
    data = getattr(ob, "data", None)
    layers = getattr(data, "layers", None)
    return list(layers) if layers is not None else []


def _managed_cutter_mattes(ob, graph_obnames):
    """Names of matte objects feeding `ob` via native cross-object cutter masks that the Peg Graph
    owns: the matte is a drawing node in this graph and the mask is not an Auto-Patch mask (those
    belong to the Auto-Patch / Contour systems and must be left untouched)."""
    mattes = set()
    for layer in _leaf_layers(ob):
        for m in layer.mask_layers:
            mo = getattr(m, "object", None)
            if (mo is not None and not getattr(m, "use_auto_patch", False)
                    and mo.name in graph_obnames and mo.name != ob.name):
                mattes.add(mo.name)
    return mattes


def _effective_cutter_mattes(ob, graph_obnames):
    """Cutter mattes that should show in the graph: native masks plus any not-yet-migrated legacy
    injection-modifier target. Keeps the rebuild signature stable across the migration."""
    mattes = _managed_cutter_mattes(ob, graph_obnames)
    leg = _cutter_modifier(ob)
    if leg is not None and leg.object is not None and leg.object.name in graph_obnames:
        mattes.add(leg.object.name)
    mattes.discard(ob.name)
    return mattes


def _object_cutter_invert(ob, graph_obnames):
    """Polarity of `ob`'s graph-owned cutter masks (uniform by construction); False if none."""
    for layer in _leaf_layers(ob):
        for m in layer.mask_layers:
            mo = getattr(m, "object", None)
            if (mo is not None and not getattr(m, "use_auto_patch", False)
                    and mo.name in graph_obnames and mo.name != ob.name):
                return bool(m.invert)
    return False


def _set_object_cutters(ob, desired_names, graph_obnames, invert=False):
    """Reconcile `ob`'s native cross-object cutter masks to exactly `desired_names` (matte object
    names), on every leaf layer, all with polarity `invert`. Only masks the graph owns are
    added/removed/retuned; foreign cross-object masks (Auto-Patch, manual) are preserved. Multiple
    mattes union at draw time."""
    desired = {n for n in desired_names if n != ob.name and n in graph_obnames}
    for layer in _leaf_layers(ob):
        seen = set()
        stale = []
        for m in layer.mask_layers:
            mo = getattr(m, "object", None)
            if (mo is None or getattr(m, "use_auto_patch", False)
                    or mo.name not in graph_obnames):
                continue  # not ours
            if mo.name in desired and mo.name not in seen:
                seen.add(mo.name)
                m.invert = invert
            else:
                stale.append(m)
        for m in stale:
            layer.mask_layers.remove(m)
        missing = desired - seen
        if missing:
            layer.use_masks = True
            for name in sorted(missing):
                mo = bpy.data.objects.get(name)
                if mo is not None:
                    # Empty layer name = the whole matte object is the silhouette.
                    layer.mask_layers.new(name="", object=mo, invert=invert)


def _migrate_legacy_cutter(ob, graph_obnames):
    """Lazy upgrade: fold a legacy GREASE_PENCIL_MASK injection modifier into native cross-object
    masks so the graph speaks a single language, then drop the modifier."""
    leg = _cutter_modifier(ob)
    if leg is None:
        return
    matte = leg.object
    invert = bool(getattr(leg, "invert", False))
    ob.modifiers.remove(leg)
    if matte is not None and matte.name != ob.name and matte.name in graph_obnames:
        mattes = _managed_cutter_mattes(ob, graph_obnames)
        mattes.add(matte.name)
        _set_object_cutters(ob, mattes, graph_obnames, invert)


def _would_cycle(rig, child_index, new_parent_index):
    """True if making `new_parent_index` the parent of `child_index` would create a cycle."""
    pegs = rig.pegs
    p = new_parent_index
    guard = 0
    while p >= 0 and p < len(pegs) and guard <= len(pegs):
        if p == child_index:
            return True
        p = pegs[p].parent_index
        guard += 1
    return False


def _is_ancestor(rig, ancestor, peg):
    """True if `ancestor` is a strict ancestor of `peg` in the parent chain."""
    pegs = rig.pegs
    p = pegs[peg].parent_index if 0 <= peg < len(pegs) else -1
    guard = 0
    while p >= 0 and p < len(pegs) and guard <= len(pegs):
        if p == ancestor:
            return True
        p = pegs[p].parent_index
        guard += 1
    return False


def _ancestor_chain(rig, idx):
    """Indices from peg `idx` up to its root: [idx, parent, ..., root]. Guarded against cycles."""
    chain = []
    i = idx
    guard = 0
    while 0 <= i < len(rig.pegs) and guard <= len(rig.pegs):
        chain.append(i)
        i = rig.pegs[i].parent_index
        guard += 1
    return chain


def _object_peg_index(context):
    """Index of the peg the active object's Follow Peg constraint targets, or -1."""
    ob = context.active_object
    if ob is None:
        return None, -1
    con = _followpeg_constraint(ob)
    if con is None or con.rig is None:
        return None, -1
    return con.rig, con.rig.pegs.find(con.peg_name)


def _active_peg_index(context):
    """Index of the peg currently controlled (climb-aware): the active peg if it is the object's own
    peg or an ancestor of it, otherwise the object's own peg. Returns (rig, index) or (None, -1)."""
    rig, obj_idx = _object_peg_index(context)
    if rig is None or obj_idx < 0:
        return None, -1
    idx = obj_idx
    a = rig.active_peg_index
    if 0 <= a < len(rig.pegs) and (a == obj_idx or _is_ancestor(rig, a, obj_idx)):
        idx = a
    return rig, idx


def active_peg(context):
    """Resolve the peg currently controlled by the active object, honouring the Ctrl+B climb
    (PegRig.active_peg_index) when it is the object's own peg or an ancestor of it.
    \return (rig, peg) or (None, None)."""
    rig, idx = _active_peg_index(context)
    if rig is None or idx < 0:
        return None, None
    return rig, rig.pegs[idx]


def _peg_local_matrix(peg):
    """Replicate BKE_pegrig peg local matrix: T(t+p) * R * S * T(-p). The rotation centre is
    pivot+translation, so a dragged drawing keeps spinning about itself."""
    from mathutils import Matrix, Vector, Euler
    p = Vector(peg.pivot)
    t = Vector(peg.translation)
    rot = Euler(peg.rotation, 'XYZ').to_matrix().to_4x4()
    scale = Matrix.Diagonal(Vector((peg.scale[0], peg.scale[1], peg.scale[2], 1.0)))
    return Matrix.Translation(t + p) @ rot @ scale @ Matrix.Translation(-p)


def _peg_world_matrix(rig, idx):
    """World matrix of peg `idx` = product of local matrices from the root down."""
    chain = []
    i = idx
    guard = 0
    while 0 <= i < len(rig.pegs) and guard <= len(rig.pegs):
        chain.append(i)
        i = rig.pegs[i].parent_index
        guard += 1
    m = mathutils.Matrix()
    for j in reversed(chain):
        m = m @ _peg_local_matrix(rig.pegs[j])
    return m


def _drawing_center_world(ob):
    """World-space centre of a Grease Pencil object's bounding box."""
    corners = [ob.matrix_world @ mathutils.Vector(c) for c in ob.bound_box]
    return sum(corners, mathutils.Vector()) / 8.0


def _set_peg_pivot_to_drawing(rig, peg_name, ob):
    """Place the peg's pivot at the bound drawing's centre (in the peg's parent frame) so it
    rotates in place instead of orbiting the parent origin."""
    idx = rig.pegs.find(peg_name)
    if idx < 0:
        return
    peg = rig.pegs[idx]
    parent = peg.parent_index
    pw = _peg_world_matrix(rig, parent) if 0 <= parent < len(rig.pegs) else mathutils.Matrix.Identity(4)
    peg.pivot = pw.inverted() @ _drawing_center_world(ob)


def _auto_pivot_on_bind(rig, peg_name, ob):
    """On first binding a drawing to a peg, snap the peg's pivot to that drawing — unless the user
    has already placed a pivot (non-zero)."""
    idx = rig.pegs.find(peg_name)
    if idx < 0:
        return
    piv = rig.pegs[idx].pivot
    if piv[0] or piv[1] or piv[2]:
        return
    _set_peg_pivot_to_drawing(rig, peg_name, ob)


# -------------------------------------------------------------------------------------------------
# Layout persistence (positions + frames)
#
# The rigger's node arrangement is the whole point of the Peg Graph, so it must survive a Sync (which
# rebuilds the tree from scratch) AND travel with the rig into other files. The live node tree is the
# working copy; the durable copy is a JSON snapshot stored on the PegRig (`_LAYOUT_KEY`). Everything
# here reads/writes ``location_absolute`` -- a node inside a frame has a parent-RELATIVE ``location``,
# so using the absolute field is what keeps framed nodes from jumping on rebuild.
# -------------------------------------------------------------------------------------------------

def _node_layout_key(node):
    """Stable key identifying a peg/drawing/rig node across rebuilds, or None for other nodes."""
    if node.bl_idname == _PEG_NODE_ID:
        return ["peg", node.peg_name]
    if node.bl_idname == _DRAWING_NODE_ID:
        return ["draw", node.object_name]
    if node.bl_idname == _RIG_NODE_ID:
        return ["rig", ""]
    return None


def _capture_layout(tree):
    """Snapshot the live node arrangement (positions + frames + parenting) into the rig's layout
    ID-property, overwriting the previous snapshot. Callers must skip this for an EMPTY tree so a
    layout just appended with the rig is not clobbered before it has been applied."""
    rig = tree.rig
    if rig is None:
        return
    pegs, draws = {}, {}
    rig_loc = None
    frame_nodes = [n for n in tree.nodes if n.bl_idname == 'NodeFrame']
    frame_pos = {f.name: i for i, f in enumerate(frame_nodes)}
    members = [[] for _ in frame_nodes]

    for n in tree.nodes:
        loc = list(n.location_absolute)
        if n.bl_idname == _PEG_NODE_ID:
            pegs[n.peg_name] = loc
        elif n.bl_idname == _DRAWING_NODE_ID:
            draws[n.object_name] = loc
        elif n.bl_idname == _RIG_NODE_ID:
            rig_loc = loc
        parent = n.parent
        if parent is not None and parent.bl_idname == 'NodeFrame':
            fi = frame_pos.get(parent.name)
            if fi is not None:
                key = ["frame", frame_pos[n.name]] if n.bl_idname == 'NodeFrame' \
                    else _node_layout_key(n)
                if key is not None:
                    members[fi].append(key)

    frames = []
    for i, f in enumerate(frame_nodes):
        frames.append({
            "label": f.label,
            "use_custom_color": f.use_custom_color,
            "color": list(f.color),
            "label_size": f.label_size,
            "shrink": f.shrink,
            "loc": list(f.location_absolute),
            "width": f.width,
            "height": f.height,
            "members": members[i],
        })

    rig[_LAYOUT_KEY] = json.dumps({"pegs": pegs, "draws": draws, "rig": rig_loc, "frames": frames})


def _read_layout(rig):
    """Parsed layout snapshot stored on `rig`, or {} when absent/corrupt."""
    raw = rig.get(_LAYOUT_KEY) if rig is not None else None
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _apply_frames(tree, frames, node_by_key):
    """Recreate the saved NodeFrames and re-attach their members. nodes.clear() in rebuild() destroys
    frames and parenting; this restores them. Positions are set via location_absolute AFTER parenting
    (parenting never moves a node on the canvas), so members stay exactly where `place` put them."""
    if not frames:
        return
    created = []
    for fdata in frames:
        fr = tree.nodes.new('NodeFrame')
        fr.label = fdata.get("label", "")
        if fdata.get("use_custom_color"):
            fr.use_custom_color = True
            col = fdata.get("color")
            if col:
                fr.color = col[:3]
        fr.label_size = int(fdata.get("label_size", 20))
        fr.shrink = bool(fdata.get("shrink", True))
        created.append(fr)

    # Re-attach members (including nested frames, referenced by index) once every frame exists.
    for i, fdata in enumerate(frames):
        fr = created[i]
        for mk in fdata.get("members", []):
            if not mk:
                continue
            if mk[0] == "frame":
                idx = mk[1] if len(mk) > 1 else -1
                target = created[idx] if isinstance(idx, int) and 0 <= idx < len(created) else None
            else:
                target = node_by_key.get((mk[0], mk[1] if len(mk) > 1 else ""))
            if target is not None:
                target.parent = fr

    # A shrink frame auto-sizes/positions around its members, so loc/size are best-effort and only
    # forced for non-shrink frames.
    for i, fdata in enumerate(frames):
        fr = created[i]
        loc = fdata.get("loc")
        if loc:
            fr.location_absolute = loc
        if not fdata.get("shrink", True):
            if fdata.get("width"):
                fr.width = fdata["width"]
            if fdata.get("height"):
                fr.height = fdata["height"]


# -------------------------------------------------------------------------------------------------
# rig -> graph (generate the node tree from the rig)
# -------------------------------------------------------------------------------------------------

def rebuild(tree):
    global _SYNCING
    rig = tree.rig
    _SYNCING = True
    try:
        # Fold the current on-screen arrangement into the rig's durable layout before clearing, so
        # node moves and frames made since the last capture are preserved. Skip when the tree is
        # empty (e.g. a fresh graph in a file the rig was just appended into) so we apply the
        # appended layout instead of overwriting it with nothing.
        if rig is not None and len(tree.nodes):
            _capture_layout(tree)

        tree.nodes.clear()
        if rig is None:
            return

        # Positions come from the (just-refreshed) durable layout, keyed like the live nodes. This is
        # also what carries the layout across files: an appended rig brings its layout, no live nodes.
        layout = _read_layout(rig)
        positions = {}
        for _name, _xy in layout.get("pegs", {}).items():
            positions[('peg', _name)] = _xy
        for _on, _xy in layout.get("draws", {}).items():
            positions[('draw', _on)] = _xy
        _rloc = layout.get("rig")
        if _rloc:
            positions[('rig', '')] = _rloc

        rows = {}

        def place(node, depth, key):
            loc = positions.get(key)
            if loc is not None:
                node.location_absolute = loc
                return
            row = rows.get(depth, 0)
            rows[depth] = row + 1
            node.location_absolute = (depth * 240.0, -row * 150.0)

        # The composite hub (one per rig); root pegs and loose members connect to it.
        rig_node = tree.nodes.new(_RIG_NODE_ID)
        place(rig_node, -1, ('rig', ''))

        # Peg nodes, indexed to match rig.pegs.
        peg_nodes = []
        for i, peg in enumerate(rig.pegs):
            node = tree.nodes.new(_PEG_NODE_ID)
            node.peg_name = peg.name
            place(node, _peg_depth(rig, i), ('peg', peg.name))
            peg_nodes.append(node)

        # Parent links: child peg <- parent peg, or root peg <- composite hub.
        for i, peg in enumerate(rig.pegs):
            parent = peg.parent_index
            if 0 <= parent < len(peg_nodes) and parent != i:
                tree.links.new(peg_nodes[parent].outputs[0], peg_nodes[i].inputs[0])
            else:
                tree.links.new(rig_node.outputs[0], peg_nodes[i].inputs[0])

        # Drawing nodes linked to their controlling peg, or to the composite hub when loose.
        peg_node_by_name = {n.peg_name: n for n in peg_nodes}
        max_depth = max(rows.keys(), default=0)
        draw_node_by_obname = {}
        for ob, peg_name in _bound_objects(rig):
            dn = tree.nodes.new(_DRAWING_NODE_ID)
            dn.object_name = ob.name
            draw_node_by_obname[ob.name] = dn
            place(dn, max_depth + 1, ('draw', ob.name))
            peg_node = peg_node_by_name.get(peg_name) if peg_name else None
            if peg_node is not None:
                tree.links.new(peg_node.outputs[0], dn.inputs[0])
            else:
                tree.links.new(rig_node.outputs[0], dn.inputs[0])

        # Cutter links: matte drawing's "Matte" output -> masked drawing's "Cutter" input,
        # reconstructed from each object's native cross-object cutter masks (one link per matte; the
        # Cutter input is multi-input so several mattes feed it). Legacy injection-modifier cutters
        # are migrated to native masks on the fly so old files keep working.
        graph_obnames = set(draw_node_by_obname)
        for ob_name, dn in draw_node_by_obname.items():
            ob = bpy.data.objects.get(ob_name)
            if ob is None:
                continue
            _migrate_legacy_cutter(ob, graph_obnames)
            mattes = sorted(_managed_cutter_mattes(ob, graph_obnames))
            for matte_name in mattes:
                src = draw_node_by_obname.get(matte_name)
                if src is not None:
                    tree.links.new(src.outputs[-1], dn.inputs[1])
            if mattes:
                dn.cutter_invert = _object_cutter_invert(ob, graph_obnames)

        # Re-attach the rigger's frames (F / Join in New Frame) and node parenting that nodes.clear()
        # destroyed. Members are matched back to the freshly created nodes by their stable keys.
        node_by_key = {('rig', ''): rig_node}
        for _pn in peg_nodes:
            node_by_key[('peg', _pn.peg_name)] = _pn
        for _on, _dn in draw_node_by_obname.items():
            node_by_key[('draw', _on)] = _dn
        _apply_frames(tree, layout.get("frames", []), node_by_key)
    finally:
        _SYNCING = False


def _graph_signature(tree):
    """Cheap fingerprint of the rig's structure, to detect when a rebuild is needed."""
    rig = tree.rig
    if rig is None:
        return ""
    pegs = ";".join(f"{p.name}:{p.parent_index}" for p in rig.pegs)
    bound = ";".join(sorted(f"{ob.name}->{name}" for ob, name in _bound_objects(rig)))
    graph_obnames = {ob.name for ob, _ in _bound_objects(rig)}
    cutters = ";".join(sorted(
        f"{ob.name}=>{mn}@{int(_object_cutter_invert(ob, graph_obnames))}"
        for ob, _ in _bound_objects(rig)
        for mn in _effective_cutter_mattes(ob, graph_obnames)))
    return pegs + "|" + bound + "|" + cutters


# -------------------------------------------------------------------------------------------------
# graph -> rig (write graph edits back to the rig)
# -------------------------------------------------------------------------------------------------

def _input_source_node(node):
    if not node.inputs:
        return None
    links = node.inputs[0].links
    return links[0].from_node if links else None


def _apply_graph_to_rig(tree):
    global _SYNCING
    rig = tree.rig
    if rig is None:
        return
    _SYNCING = True
    try:
        peg_index_by_name = {p.name: i for i, p in enumerate(rig.pegs)}
        graph_obnames = {n.object_name for n in tree.nodes if n.bl_idname == _DRAWING_NODE_ID}

        for node in tree.nodes:
            if node.bl_idname == _PEG_NODE_ID:
                index = peg_index_by_name.get(node.peg_name)
                if index is None:
                    continue
                src = _input_source_node(node)
                new_parent = -1
                if src is not None and src.bl_idname == _PEG_NODE_ID:
                    new_parent = peg_index_by_name.get(src.peg_name, -1)
                if new_parent != index and not _would_cycle(rig, index, new_parent):
                    rig.pegs[index].parent_index = new_parent

            elif node.bl_idname == _DRAWING_NODE_ID:
                ob = bpy.data.objects.get(node.object_name)
                if ob is None:
                    continue
                src = _input_source_node(node)
                con = _followpeg_constraint(ob)
                if src is not None and src.bl_idname == _PEG_NODE_ID:
                    if con is None:
                        con = ob.constraints.new('FOLLOW_PEG')
                    con.rig = rig
                    con.peg_name = src.peg_name
                    con.set_inverse_pending = True
                    _auto_pivot_on_bind(rig, src.peg_name, ob)
                elif src is not None and src.bl_idname == _RIG_NODE_ID:
                    # Member of the rig, but following no peg.
                    if con is None:
                        con = ob.constraints.new('FOLLOW_PEG')
                    con.rig = rig
                    con.peg_name = ""
                elif con is not None:
                    ob.constraints.remove(con)

                # Cutter / mask: every link into the multi-input "Cutter" socket adds a native
                # cross-object GP mask clipping this object to that matte's silhouette; multiple
                # mattes union. Reconciled against the links, so removing a link removes the mask.
                desired = set()
                if len(node.inputs) > 1:
                    for link in node.inputs[1].links:
                        s = link.from_node
                        if s is not None and s.bl_idname == _DRAWING_NODE_ID:
                            desired.add(s.object_name)
                _set_object_cutters(ob, desired, graph_obnames, node.cutter_invert)

        if rig.id_data:
            rig.id_data.update_tag()
    finally:
        _SYNCING = False


# -------------------------------------------------------------------------------------------------
# Operators
# -------------------------------------------------------------------------------------------------

def _active_peg_tree(context):
    space = context.space_data
    if space and space.type == 'NODE_EDITOR' and space.tree_type == _TREE_ID:
        return space.edit_tree or space.node_tree
    return None


def _rig_from_active_object(context):
    ob = context.active_object
    if ob is not None:
        con = _followpeg_constraint(ob)
        if con is not None and con.rig is not None:
            return con.rig
    return None


class NODE_OT_nuclear_peg_sync(Operator):
    bl_idname = "node.nuclear_peg_sync"
    bl_label = "Sync Peg Graph"
    bl_description = "Rebuild the graph from the peg rig (creating the graph if needed)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space and space.type == 'NODE_EDITOR' and space.tree_type == _TREE_ID

    def execute(self, context):
        space = context.space_data
        tree = space.edit_tree or space.node_tree
        if tree is None:
            tree = bpy.data.node_groups.new("Peg Graph", _TREE_ID)
            space.node_tree = tree
        if tree.rig is None:
            tree.rig = _rig_from_active_object(context)
        if tree.rig is None:
            self.report({'WARNING'}, "No peg rig: select a drawing bound to a peg, or set the rig")
            return {'CANCELLED'}
        rebuild(tree)
        return {'FINISHED'}


class NODE_OT_nuclear_peg_add(Operator):
    bl_idname = "node.nuclear_peg_add"
    bl_label = "Add Peg"
    bl_description = "Add a new peg to the rig shown in this graph"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(name="Name", default="Peg")

    @classmethod
    def poll(cls, context):
        tree = _active_peg_tree(context)
        return tree is not None and tree.rig is not None

    def execute(self, context):
        tree = _active_peg_tree(context)
        rig = tree.rig

        # The new peg becomes the PARENT of the active node (clicking a node then "Add Peg" inserts a
        # peg above it):
        #  * peg node active   -> the new peg is inserted ABOVE the clicked peg: the new peg takes the
        #                          clicked peg's old parent, and the clicked peg becomes its child.
        #  * drawing node active-> the new peg becomes the drawing's parent/controller, but only if
        #                          that object has no controlling peg yet (don't steal an existing one).
        active = tree.nodes.active
        new_parent = -1          # the new peg's own parent
        reparent_child = -1      # a peg that should become a child of the new peg
        bind_drawing = None
        if active is not None:
            if active.bl_idname == _PEG_NODE_ID:
                ci = rig.pegs.find(active.peg_name)
                if ci >= 0:
                    reparent_child = ci
                    new_parent = rig.pegs[ci].parent_index  # insert in place: inherit its parent
            elif active.bl_idname == _DRAWING_NODE_ID:
                ob = bpy.data.objects.get(active.object_name)
                con = _followpeg_constraint(ob) if ob else None
                if ob is not None and (con is None or not con.peg_name):
                    bind_drawing = ob

        peg = rig.pegs.new(self.name, parent_index=new_parent)
        new_idx = rig.pegs.find(peg.name)

        if reparent_child >= 0:
            rig.pegs[reparent_child].parent_index = new_idx  # clicked peg now hangs under the new one
        if bind_drawing is not None:
            con = _followpeg_constraint(bind_drawing) or bind_drawing.constraints.new('FOLLOW_PEG')
            con.rig = rig
            con.peg_name = peg.name
            con.set_inverse_pending = True
            _auto_pivot_on_bind(rig, peg.name, bind_drawing)

        rig.active_peg_index = new_idx  # select & highlight the freshly-added peg
        rebuild(tree)
        return {'FINISHED'}


class NODE_OT_nuclear_peg_remove(Operator):
    bl_idname = "node.nuclear_peg_remove"
    bl_label = "Remove Peg"
    bl_description = "Remove the peg of the active node from the rig"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        tree = _active_peg_tree(context)
        return (tree is not None and tree.rig is not None and
                tree.nodes.active is not None and
                tree.nodes.active.bl_idname == _PEG_NODE_ID)

    def execute(self, context):
        tree = _active_peg_tree(context)
        rig = tree.rig
        peg = rig.pegs.get(tree.nodes.active.peg_name)
        if peg is None:
            return {'CANCELLED'}
        rig.pegs.remove(peg)
        rebuild(tree)
        return {'FINISHED'}


class NODE_OT_nuclear_peg_bind_selected(Operator):
    bl_idname = "node.nuclear_peg_bind_selected"
    bl_label = "Bind Selected Drawings"
    bl_description = "Bind the selected Grease Pencil objects to the peg of the active node"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        tree = _active_peg_tree(context)
        return (tree is not None and tree.rig is not None and
                tree.nodes.active is not None and
                tree.nodes.active.bl_idname == _PEG_NODE_ID)

    def execute(self, context):
        tree = _active_peg_tree(context)
        rig = tree.rig
        peg_name = tree.nodes.active.peg_name
        count = 0
        for ob in context.selected_objects:
            if ob.type != 'GREASEPENCIL':
                continue
            con = _followpeg_constraint(ob)
            if con is None:
                con = ob.constraints.new('FOLLOW_PEG')
            con.rig = rig
            con.peg_name = peg_name
            con.set_inverse_pending = True
            _auto_pivot_on_bind(rig, peg_name, ob)
            count += 1
        if count == 0:
            self.report({'WARNING'}, "No Grease Pencil objects selected")
            return {'CANCELLED'}
        rebuild(tree)
        return {'FINISHED'}


class NODE_OT_nuclear_peg_locate(Operator):
    """Frame the node of the selected stroke or peg (the 'O' shortcut). Resolution priority:
      1. the active object, if it is a Grease Pencil drawing bound to this rig -> its drawing node;
      2. otherwise the active peg (PegRig.active_peg_index) -> its peg node;
      3. otherwise whatever node is currently active.
    The matched node is selected/made-active and then framed via View Selected."""
    bl_idname = "node.nuclear_peg_locate"
    bl_label = "Locate Selected in Graph"
    bl_description = "Frame the node of the selected stroke or peg in the Peg Graph"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        tree = _active_peg_tree(context)
        return tree is not None and tree.rig is not None

    def execute(self, context):
        tree = _active_peg_tree(context)
        rig = tree.rig
        target = None

        # 1. selected stroke: the active object, if it is a drawing bound to this rig.
        ob = context.active_object
        if ob is not None and ob.type == 'GREASEPENCIL':
            con = _followpeg_constraint(ob)
            if con is not None and con.rig == rig:
                target = next((n for n in tree.nodes
                               if n.bl_idname == _DRAWING_NODE_ID and n.object_name == ob.name), None)

        # 2. selected peg: the rig's active peg.
        if target is None:
            i = rig.active_peg_index
            if 0 <= i < len(rig.pegs):
                want = rig.pegs[i].name
                target = next((n for n in tree.nodes
                               if n.bl_idname == _PEG_NODE_ID and n.peg_name == want), None)

        # 3. fall back to the currently active node.
        if target is None:
            target = tree.nodes.active
        if target is None:
            self.report({'WARNING'}, "Nothing selected to locate")
            return {'CANCELLED'}

        for n in tree.nodes:
            n.select = False
        target.select = True
        tree.nodes.active = target
        bpy.ops.node.view_selected('INVOKE_DEFAULT')
        return {'FINISHED'}


# -------------------------------------------------------------------------------------------------
# UI panel (node editor sidebar)
# -------------------------------------------------------------------------------------------------

class NODE_PT_nuclear_peg(Panel):
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Peg"
    bl_label = "Peg Graph"

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space and space.type == 'NODE_EDITOR' and space.tree_type == _TREE_ID

    def draw(self, context):
        layout = self.layout
        space = context.space_data
        tree = space.edit_tree or space.node_tree

        if tree is None:
            layout.operator("node.nuclear_peg_sync", icon='FILE_REFRESH')
            return

        layout.prop_search(tree, "rig", bpy.data, "pegrigs", text="Rig")
        col = layout.column(align=True)
        col.operator("node.nuclear_peg_sync", icon='FILE_REFRESH')
        col.operator("node.nuclear_peg_add", icon='ADD')
        col.operator("node.nuclear_peg_remove", icon='REMOVE')
        col.operator("node.nuclear_peg_bind_selected", icon='LINKED')


class OBJECT_OT_pegrig_select_child(Operator):
    """Descend the hierarchy: the counterpart to Select Parent (Ctrl+B). Moves the controlled peg
    one level DOWN, toward the drawing -- i.e. to the child of the current peg that lies on the path
    to the object's own peg. Bound to Ctrl+Shift+B in the Peg Pose tool."""
    bl_idname = "object.pegrig_select_child"
    bl_label = "Select Child Peg"
    bl_description = "Make the child of the active peg the controlled peg (descend toward the drawing)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _object_peg_index(context)[1] >= 0

    def execute(self, context):
        rig, obj_idx = _object_peg_index(context)
        if rig is None or obj_idx < 0:
            return {'CANCELLED'}
        _r, active = _active_peg_index(context)
        if active < 0 or active == obj_idx:
            return {'CANCELLED'}  # already at the drawing's own peg; nothing below
        # Walk up from the object's peg; the node whose parent is `active` is the step down.
        child = obj_idx
        guard = 0
        while 0 <= child < len(rig.pegs) and guard <= len(rig.pegs):
            parent = rig.pegs[child].parent_index
            if parent == active:
                rig.active_peg_index = child  # fires msgbus -> both views redraw
                return {'FINISHED'}
            child = parent
            guard += 1
        return {'CANCELLED'}


class OBJECT_OT_pegrig_pivot_reset(Operator):
    bl_idname = "object.pegrig_pivot_reset"
    bl_label = "Reset Pivot"
    bl_description = "Reset the active peg's pivot to its origin"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return active_peg(context)[1] is not None

    def execute(self, context):
        _rig, peg = active_peg(context)
        if peg is None:
            return {'CANCELLED'}
        peg.pivot = (0.0, 0.0, 0.0)
        return {'FINISHED'}


class OBJECT_OT_pegrig_pivot_to_drawing(Operator):
    bl_idname = "object.pegrig_pivot_to_drawing"
    bl_label = "Pivot to Drawing"
    bl_description = "Place the active peg's pivot at the centre of its controlled drawing"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return active_peg(context)[1] is not None and context.active_object is not None

    def execute(self, context):
        rig, peg = active_peg(context)
        ob = context.active_object
        if peg is None or ob is None:
            return {'CANCELLED'}
        _set_peg_pivot_to_drawing(rig, peg.name, ob)
        rig.id_data.update_tag()
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class OBJECT_OT_pegrig_pivot_grab(Operator):
    bl_idname = "object.pegrig_pivot_grab"
    bl_label = "Grab Peg Pivot"
    bl_description = "Move the active peg's pivot point in the viewport"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return (space and space.type == 'VIEW_3D' and context.region_data is not None and
                active_peg(context)[1] is not None)

    def invoke(self, context, event):
        rig, peg = active_peg(context)
        if peg is None:
            return {'CANCELLED'}
        self._rig = rig
        self._idx = rig.pegs.find(peg.name)
        self._init_pivot = mathutils.Vector(peg.pivot)
        # The pivot lives in the peg's PARENT frame: in the local matrix T(t+p)*R*S*T(-p) the
        # T(-p) is applied before the peg's own rotation/scale. So the cursor delta must be mapped
        # through the parent's world rotation, NOT the peg's own (which is skewed by R*S once the
        # peg has been posed). Using the parent's frame keeps the pivot under the cursor.
        parent_idx = rig.pegs[self._idx].parent_index
        if 0 <= parent_idx < len(rig.pegs):
            parent_world = _peg_world_matrix(rig, parent_idx)
        else:
            parent_world = mathutils.Matrix.Identity(4)
        # Project on the plane through the controlled drawing so the drag stays under the cursor.
        ob = context.active_object
        self._anchor = ob.matrix_world.translation.copy() if ob else (parent_world @ self._init_pivot)
        try:
            self._rot_inv = parent_world.to_3x3().inverted()
        except ValueError:
            self._rot_inv = mathutils.Matrix.Identity(3)
        self._init_mouse = (event.mouse_region_x, event.mouse_region_y)
        context.window_manager.modal_handler_add(self)
        context.area.header_text_set("Grab Pivot: move to place, LMB/Enter confirm, RMB/Esc cancel")
        return {'RUNNING_MODAL'}

    def _project(self, context, mx, my):
        return view3d_utils.region_2d_to_location_3d(
            context.region, context.region_data, (mx, my), self._anchor)

    def _finish(self, context):
        context.area.header_text_set(None)
        context.area.tag_redraw()

    def modal(self, context, event):
        peg = self._rig.pegs[self._idx]
        if event.type == 'MOUSEMOVE':
            cur = self._project(context, event.mouse_region_x, event.mouse_region_y)
            init = self._project(context, *self._init_mouse)
            delta_local = self._rot_inv @ (cur - init)
            peg.pivot = self._init_pivot + delta_local
            self._rig.id_data.update_tag()
            context.area.tag_redraw()
        elif event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            self._finish(context)
            return {'FINISHED'}
        elif event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            peg.pivot = self._init_pivot
            self._rig.id_data.update_tag()
            self._finish(context)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


class VIEW3D_PT_nuclear_peg(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Peg"
    bl_label = "Active Peg"

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and active_peg(context)[1] is not None

    def draw(self, context):
        layout = self.layout
        rig, peg = active_peg(context)
        if peg is None:
            layout.label(text="No active peg")
            return

        row = layout.row(align=True)
        row.label(text=peg.name, icon='EMPTY_AXIS')
        row.label(text=rig.name, icon='OUTLINER_OB_ARMATURE')

        col = layout.column()
        col.use_property_split = True
        col.prop(peg, "translation")
        col.prop(peg, "rotation")
        col.prop(peg, "scale")

        box = layout.box()
        box.label(text="Pivot", icon='PIVOT_BOUNDBOX')
        col = box.column()
        col.use_property_split = True
        col.prop(peg, "pivot", text="")
        box.operator("object.pegrig_pivot_to_drawing", text="Pivot to Drawing", icon='OBJECT_ORIGIN')
        row = box.row(align=True)
        row.operator("object.pegrig_pivot_grab", text="Grab Pivot (P)", icon='PIVOT_CURSOR')
        row.operator("object.pegrig_pivot_reset", text="", icon='LOOP_BACK')

        box = layout.box()
        box.label(text="Squash & Stretch", icon='MOD_SIMPLEDEFORM')
        if not peg.use_squash:
            box.operator("object.pegrig_squash_enable", text="Enable Squash", icon='CON_SIZELIMIT')
        else:
            box.prop(peg, "use_squash", text="Enabled")
            col = box.column()
            col.use_property_split = True
            col.prop(peg, "squash_volume", slider=True)
            col.prop(peg, "squash_anchor", text="Anchor")
            col.prop(peg, "squash_tip", text="Tip")
            row = box.row(align=True)
            row.prop(peg, "squash_rest_len")
            row.operator("object.pegrig_squash_reset_rest", text="", icon='LOOP_BACK')


# -------------------------------------------------------------------------------------------------
# Auto-refresh handler: rebuild visible peg graphs when the rig structure changes
# -------------------------------------------------------------------------------------------------

_LAST_SIGNATURES = {}


def _depsgraph_update_post(_scene, _depsgraph):
    if _SYNCING:
        return
    wm = bpy.data.window_managers
    for win in (w for wm_ in wm for w in wm_.windows):
        for area in win.screen.areas:
            if area.type != 'NODE_EDITOR':
                continue
            space = area.spaces.active
            if space.tree_type != _TREE_ID:
                continue
            tree = space.edit_tree or space.node_tree
            if tree is None or tree.rig is None:
                continue
            sig = _graph_signature(tree)
            if _LAST_SIGNATURES.get(tree.name) != sig:
                _LAST_SIGNATURES[tree.name] = sig
                rebuild(tree)


# -------------------------------------------------------------------------------------------------
# Keep the "Peg Pose" tool keymap populated (the inline-keymap tool can be cleared on file load)
# -------------------------------------------------------------------------------------------------

_PEG_POSE_KM = "3D View Tool: Object, Peg Pose"
_PEG_POSE_BINDINGS = (
    ("object.pegrig_pick", {"type": 'LEFTMOUSE', "value": 'CLICK'}, None),
    ("transform.translate",
     {"type": 'LEFTMOUSE', "value": 'CLICK_DRAG'},
     {"properties": [("release_confirm", True)]}),
    ("object.pegrig_select_parent", {"type": 'B', "value": 'PRESS', "ctrl": True}, None),
    ("object.pegrig_select_child", {"type": 'B', "value": 'PRESS', "ctrl": True, "shift": True}, None),
    ("object.pegrig_pivot_grab", {"type": 'P', "value": 'PRESS'}, None),
)


def _ensure_peg_pose_keymap():
    """Populate the Peg Pose tool keymap if it is missing/empty (e.g. after File > New)."""
    from bl_keymap_utils.io import keymap_init_from_data
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.default if wm else None
    if kc is None:
        return
    km = kc.keymaps.get(_PEG_POSE_KM)
    if km is None:
        km = kc.keymaps.new(_PEG_POSE_KM, space_type='VIEW_3D', region_type='WINDOW', tool=True)
    if not km.keymap_items:
        keymap_init_from_data(km, _PEG_POSE_BINDINGS)


def _set_render_border_ctrl_b(active):
    """Toggle the global 3D View Ctrl+B 'Set Render Region' (view3d.render_border). It otherwise
    shadows the Peg Pose tool's Ctrl+B (Select Parent) whenever the tool's poll falls through, so we
    disable it while the peg system is registered and restore it on unregister."""
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.user if wm else None
    km = kc.keymaps.get("3D View") if kc else None
    if km is None:
        return
    for kmi in km.keymap_items:
        if (kmi.idname == "view3d.render_border" and kmi.type == 'B'
                and kmi.ctrl and not kmi.alt and not kmi.shift):
            kmi.active = active


@bpy.app.handlers.persistent
def _load_post(*_args):
    _ensure_peg_pose_keymap()
    _set_render_border_ctrl_b(False)  # keep Ctrl+B free for peg navigation
    _subscribe_active_peg()  # msgbus subscriptions are cleared on file load; re-arm.


@bpy.app.handlers.persistent
def _save_pre(*_args):
    """Bake every Peg Graph's on-screen layout into its rig before the file is written, so a rig
    appended/linked from this file into another carries the rigger's arrangement with it (the node
    tree itself does not travel with the rig)."""
    try:
        for ng in bpy.data.node_groups:
            if ng.bl_idname == _TREE_ID and ng.rig is not None and len(ng.nodes):
                _capture_layout(ng)
    except Exception:
        # Layout persistence must never block a file save.
        pass


# -------------------------------------------------------------------------------------------------
# Viewport overlay (GPU): draw peg pivots so the rotation centre is visible
# -------------------------------------------------------------------------------------------------

_PIVOT_DRAW_HANDLE = None


def _peg_pivot_world(rig, idx):
    """World position of the point peg `idx` actually rotates/scales about. With the local matrix
    T(t+p)*R*S*T(-p) that centre is pivot+translation, mapped through the parent's world frame."""
    peg = rig.pegs[idx]
    parent = peg.parent_index
    pw = _peg_world_matrix(rig, parent) if 0 <= parent < len(rig.pegs) else mathutils.Matrix.Identity(4)
    return pw @ (mathutils.Vector(peg.pivot) + mathutils.Vector(peg.translation))


# Harmony-style colours: the posing/animation chain reads GREEN (rigging mode would be red).
_CHAIN_GREEN = (0.25, 0.90, 0.35, 0.95)     # the live root->active hierarchy chain
_CLIMB_GREEN = (0.55, 1.00, 0.55, 1.00)     # the segment the Ctrl+B climb has walked (brighter)
_PEG_AMBER = (1.00, 0.75, 0.10, 1.00)       # the active peg's articulation (the "you are here")
_PEG_FAINT = (1.00, 0.70, 0.10, 0.35)       # other pegs, for context


def _view_ring(center, right, up, radius, segments=32):
    """A LINE_STRIP ring of `segments` points facing the viewer, centred at `center`."""
    return [center + (right * math.cos(a) + up * math.sin(a)) * radius
            for a in (i / segments * 2.0 * math.pi for i in range(segments + 1))]


def _selected_peg_index(context):
    """Index of the peg to HIGHLIGHT for the active object: the rig's `active_peg_index` (the peg
    last clicked/picked), falling back to the object's own peg. Returns (rig, index) or (None, -1).
    Unlike `_active_peg_index`, this is NOT climb-constrained -- any clicked peg highlights itself."""
    rig, obj_idx = _object_peg_index(context)
    if rig is None:
        return None, -1
    i = rig.active_peg_index
    if 0 <= i < len(rig.pegs):
        return rig, i
    return (rig, obj_idx) if obj_idx >= 0 else (None, -1)


_BBOX_EDGES = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
               (0, 4), (1, 5), (2, 6), (3, 7))


def _drawing_outline(ob, right, up, s):
    """LINES points outlining a drawing object: its world bounding box, or -- for a boundless
    object like an Empty -- a small view-facing square at its origin."""
    corners = [ob.matrix_world @ mathutils.Vector(c) for c in ob.bound_box]
    xs = [c.x for c in corners]
    ys = [c.y for c in corners]
    zs = [c.z for c in corners]
    if max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)) < 1e-4:
        c = ob.matrix_world.translation
        r = s * 1.3
        a, b = c - right * r - up * r, c + right * r - up * r
        d, e = c + right * r + up * r, c - right * r + up * r
        return [a, b, b, d, d, e, e, a]
    pts = []
    for i, j in _BBOX_EDGES:
        pts += [corners[i], corners[j]]
    return pts


def _controlled_drawings(rig, sel_idx):
    """(object, direct) for every drawing the selected peg moves: bound straight to it (direct=True)
    or to one of its descendant pegs (direct=False, i.e. it moves along through the chain)."""
    out = []
    for ob, peg_name in _bound_objects(rig):
        if not peg_name:
            continue
        bidx = rig.pegs.find(peg_name)
        if bidx == sel_idx:
            out.append((ob, True))
        elif bidx >= 0 and _is_ancestor(rig, sel_idx, bidx):
            out.append((ob, False))
    return out


def _active_drawing_object():
    """The Grease Pencil object whose drawing node is the active node in an open Peg Graph, or None.
    Lets a click on a drawing node light up that drawing in the viewport."""
    for wm in bpy.data.window_managers:
        for win in wm.windows:
            for area in win.screen.areas:
                if area.type != 'NODE_EDITOR':
                    continue
                sp = area.spaces.active
                if getattr(sp, 'tree_type', '') != _TREE_ID:
                    continue
                tree = sp.edit_tree or sp.node_tree
                if tree is None:
                    continue
                node = tree.nodes.active
                if node is not None and node.bl_idname == _DRAWING_NODE_ID:
                    return bpy.data.objects.get(node.object_name)
    return None


def _draw_pivot_overlay():
    context = bpy.context
    if context.mode != 'OBJECT':
        return
    rv3d = context.region_data
    if rv3d is None:
        return

    # View-facing axes so the markers keep their shape from any angle, sized stable on screen.
    vm = rv3d.view_matrix
    right = mathutils.Vector((vm[0][0], vm[0][1], vm[0][2]))
    up = mathutils.Vector((vm[1][0], vm[1][1], vm[1][2]))
    s = max(rv3d.view_distance, 0.001) * 0.0125

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')  # always visible, like a pivot gizmo
    shader.bind()

    rig, sel = _selected_peg_index(context)
    if rig is not None and sel >= 0:
        # Other pegs of the rig: small faint dots, just so you can see where they are to click them.
        others = []
        for i in range(len(rig.pegs)):
            if i == sel:
                continue
            c = _peg_pivot_world(rig, i)
            others += [c - right * s * 0.4, c + right * s * 0.4, c - up * s * 0.4, c + up * s * 0.4]
        if others:
            gpu.state.line_width_set(1.0)
            shader.uniform_float("color", _PEG_FAINT)
            batch_for_shader(shader, 'LINES', {"pos": others}).draw(shader)

        # The drawings this peg moves: bright box for the ones bound straight to it, faint box for
        # the ones it carries along through the chain (bound to a descendant peg).
        gpu.state.line_width_set(1.5)
        for ob, direct in _controlled_drawings(rig, sel):
            if ob is None:
                continue
            shader.uniform_float("color", _PEG_AMBER if direct else _PEG_FAINT)
            batch_for_shader(shader, 'LINES', {"pos": _drawing_outline(ob, right, up, s)}).draw(shader)

        # The selected peg itself: a bright ring at its pivot (its rotation centre).
        c = _peg_pivot_world(rig, sel)
        gpu.state.line_width_set(2.5)
        shader.uniform_float("color", _PEG_AMBER)
        batch_for_shader(shader, 'LINE_STRIP', {"pos": _view_ring(c, right, up, s)}).draw(shader)

    # A drawing whose node is actively selected in a Peg Graph: a bright box around it.
    adraw = _active_drawing_object()
    if adraw is not None:
        gpu.state.line_width_set(2.5)
        shader.uniform_float("color", _PEG_AMBER)
        batch_for_shader(shader, 'LINES', {"pos": _drawing_outline(adraw, right, up, s)}).draw(shader)

    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


def _add_pivot_overlay():
    global _PIVOT_DRAW_HANDLE
    if _PIVOT_DRAW_HANDLE is None:
        _PIVOT_DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(
            _draw_pivot_overlay, (), 'WINDOW', 'POST_VIEW')


def _remove_pivot_overlay():
    global _PIVOT_DRAW_HANDLE
    if _PIVOT_DRAW_HANDLE is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_PIVOT_DRAW_HANDLE, 'WINDOW')
        _PIVOT_DRAW_HANDLE = None


# -------------------------------------------------------------------------------------------------
# Node-editor highlight (GPU): light up the active peg node and its ancestor chain in the Peg Graph
# -------------------------------------------------------------------------------------------------

_NODE_HL_HANDLE = None


def _node_rect_region(node, region, ui_scale):
    """Bounding box of `node` in region pixel coords: (xmin, ymin, xmax, ymax).

    node.location_absolute is the node's top-left on the canvas (location is parent-frame-relative,
    so a framed node would be mis-placed); node.width is in tree units; node.dimensions is in pixels
    at ui_scale (not view zoom), so its height in tree units is dimensions.y/ui_scale.
    """
    v2d = region.view2d
    x0, y0 = node.location_absolute
    w = node.width
    h = node.dimensions.y / ui_scale if ui_scale else node.dimensions.y
    rx0, ry0 = v2d.view_to_region(x0, y0, clip=False)
    rx1, ry1 = v2d.view_to_region(x0 + w, y0 - h, clip=False)
    return min(rx0, rx1), min(ry0, ry1), max(rx0, rx1), max(ry0, ry1)


def _draw_node_highlight():
    context = bpy.context
    space = context.space_data
    if space is None or space.type != 'NODE_EDITOR' or space.tree_type != _TREE_ID:
        return
    tree = space.edit_tree or space.node_tree
    if tree is None:
        return
    region = context.region
    if region is None:
        return

    # Highlight the ACTIVE node directly (not via active_peg_index): clicking a node already
    # redraws the editor, so reading nodes.active here makes the halo appear on the very first
    # click -- no waiting on the sync timer, no double-click. Works for peg AND drawing nodes.
    node = tree.nodes.active
    if node is None or node.bl_idname not in (_PEG_NODE_ID, _DRAWING_NODE_ID):
        return

    ui_scale = context.preferences.system.ui_scale
    xmin, ymin, xmax, ymax = _node_rect_region(node, region, ui_scale)
    pad = 3.0
    loop = [(xmin - pad, ymin - pad), (xmax + pad, ymin - pad),
            (xmax + pad, ymax + pad), (xmin - pad, ymax + pad), (xmin - pad, ymin - pad)]

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(3.0)
    shader.bind()
    shader.uniform_float("color", _PEG_AMBER)
    batch_for_shader(shader, 'LINE_STRIP', {"pos": loop}).draw(shader)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


def _add_node_overlay():
    global _NODE_HL_HANDLE
    if _NODE_HL_HANDLE is None:
        _NODE_HL_HANDLE = bpy.types.SpaceNodeEditor.draw_handler_add(
            _draw_node_highlight, (), 'WINDOW', 'POST_PIXEL')


def _remove_node_overlay():
    global _NODE_HL_HANDLE
    if _NODE_HL_HANDLE is not None:
        bpy.types.SpaceNodeEditor.draw_handler_remove(_NODE_HL_HANDLE, 'WINDOW')
        _NODE_HL_HANDLE = None


# -------------------------------------------------------------------------------------------------
# Redraw on climb: PegRig.active_peg_index changes carry no depsgraph update, so subscribe to it via
# msgbus and tag the viewports / peg graphs for redraw when the Ctrl+B climb moves the active peg.
# -------------------------------------------------------------------------------------------------

_MSGBUS_OWNER = object()


def _tag_redraw_peg_areas(*_args):
    for wm in bpy.data.window_managers:
        for win in wm.windows:
            for area in win.screen.areas:
                if area.type in {'VIEW_3D', 'NODE_EDITOR'}:
                    area.tag_redraw()


def _subscribe_active_peg():
    try:
        rna = (bpy.types.PegRig, "active_peg_index")
    except AttributeError:
        return  # native peg type not available (e.g. stock Blender)
    bpy.msgbus.clear_by_owner(_MSGBUS_OWNER)
    bpy.msgbus.subscribe_rna(
        key=rna, owner=_MSGBUS_OWNER, args=(), notify=_tag_redraw_peg_areas)


# -------------------------------------------------------------------------------------------------
# Node-click -> selection: clicking a peg node in the Peg Graph should also select that peg in the
# viewport. Node selection fires no callback, so poll the active node and mirror it into the rig's
# active_peg_index. We only act when the active node *changes* (tracked per tree) so this never
# fights the Ctrl+B climb, which moves active_peg_index without changing the active node.
# -------------------------------------------------------------------------------------------------

_LAST_ACTIVE_NODE = {}


def _sync_node_selection():
    for wm in bpy.data.window_managers:
        for win in wm.windows:
            for area in win.screen.areas:
                if area.type != 'NODE_EDITOR':
                    continue
                space = area.spaces.active
                if getattr(space, 'tree_type', '') != _TREE_ID:
                    continue
                tree = space.edit_tree or space.node_tree
                if tree is None or tree.rig is None:
                    continue
                rig = tree.rig
                node = tree.nodes.active
                is_drawing = node is not None and node.bl_idname == _DRAWING_NODE_ID
                if node is None:
                    key = None
                elif node.bl_idname == _PEG_NODE_ID:
                    key = ('peg', node.peg_name)
                elif is_drawing:
                    key = ('draw', node.object_name)
                else:
                    key = ('other', node.name)

                if key != _LAST_ACTIVE_NODE.get(tree.name):
                    # The user clicked a different node. For a peg, drive the rig's selection; for a
                    # drawing, just force a redraw so the viewport lights that drawing up.
                    _LAST_ACTIVE_NODE[tree.name] = key
                    if key is not None and key[0] == 'peg':
                        idx = rig.pegs.find(key[1])
                        if idx >= 0 and rig.active_peg_index != idx:
                            rig.active_peg_index = idx
                    _tag_redraw_peg_areas()
                elif not is_drawing:
                    # Selection stable and not a drawing: mirror a viewport pick / Ctrl+B back onto
                    # the active node so the graph highlights the same peg the viewport does. (Skip
                    # when a drawing node is active, so we never steal focus from a clicked drawing.)
                    i = rig.active_peg_index
                    if 0 <= i < len(rig.pegs):
                        want = rig.pegs[i].name
                        cur_peg = node.peg_name if (node and node.bl_idname == _PEG_NODE_ID) else None
                        if cur_peg != want:
                            target = next((n for n in tree.nodes if n.bl_idname == _PEG_NODE_ID
                                           and n.peg_name == want), None)
                            if target is not None:
                                tree.nodes.active = target
                                _LAST_ACTIVE_NODE[tree.name] = ('peg', want)
                                _tag_redraw_peg_areas()
    return 0.05  # seconds


# -------------------------------------------------------------------------------------------------
# Keymap: "O" in the Peg Graph frames the selected stroke/peg. Bound in the Node Editor keymap; the
# operator's poll restricts it to our tree, so on other node trees the 'O' event falls through.
# -------------------------------------------------------------------------------------------------

_locate_keymaps = []


def _add_locate_keymap():
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:  # missing in --background; the sidebar button still works
        return
    km = kc.keymaps.new(name="Node Editor", space_type='NODE_EDITOR')
    kmi = km.keymap_items.new("node.nuclear_peg_locate", 'O', 'PRESS')
    _locate_keymaps.append((km, kmi))


def _remove_locate_keymap():
    for km, kmi in _locate_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (RuntimeError, ReferenceError):
            pass
    _locate_keymaps.clear()


# -------------------------------------------------------------------------------------------------
# Registration
# -------------------------------------------------------------------------------------------------

classes = (
    NuclearPegSocket,
    NuclearPegTree,
    NuclearRigNode,
    NuclearPegNode,
    NuclearDrawingNode,
    NODE_OT_nuclear_peg_sync,
    NODE_OT_nuclear_peg_add,
    NODE_OT_nuclear_peg_remove,
    NODE_OT_nuclear_peg_bind_selected,
    NODE_OT_nuclear_peg_locate,
    NODE_PT_nuclear_peg,
    OBJECT_OT_pegrig_select_child,
    OBJECT_OT_pegrig_pivot_reset,
    OBJECT_OT_pegrig_pivot_to_drawing,
    OBJECT_OT_pegrig_pivot_grab,
    VIEW3D_PT_nuclear_peg,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    if _depsgraph_update_post not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_depsgraph_update_post)
    if _load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_post)
    if _save_pre not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(_save_pre)
    _add_pivot_overlay()
    _add_node_overlay()
    _ensure_peg_pose_keymap()
    _add_locate_keymap()
    _set_render_border_ctrl_b(False)  # free Ctrl+B for the Peg Pose tool (avoid render-border clash)
    # Nuclear default: zoom towards the mouse pointer (the wheel zoom in view2d already honours this
    # global preference; it is off in stock Blender). Applies to all 2D editors + the 3D viewport.
    try:
        bpy.context.preferences.inputs.use_zoom_to_mouse = True
    except (AttributeError, RuntimeError):
        pass
    _subscribe_active_peg()
    if not bpy.app.timers.is_registered(_sync_node_selection):
        bpy.app.timers.register(_sync_node_selection, persistent=True)


def unregister():
    _remove_locate_keymap()
    _set_render_border_ctrl_b(True)  # restore the stock Ctrl+B 'Set Render Region'
    if bpy.app.timers.is_registered(_sync_node_selection):
        bpy.app.timers.unregister(_sync_node_selection)
    bpy.msgbus.clear_by_owner(_MSGBUS_OWNER)
    _remove_node_overlay()
    _remove_pivot_overlay()
    if _save_pre in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(_save_pre)
    if _load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post)
    if _depsgraph_update_post in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_depsgraph_update_post)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
