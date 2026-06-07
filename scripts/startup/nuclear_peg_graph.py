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
  * parent peg -> child peg   sets ``child.parent_index``
  * peg        -> drawing     binds the drawing's Follow Peg constraint to that peg
"""

import bpy
import mathutils
from bpy_extras import view3d_utils
from bpy.types import NodeTree, Node, NodeSocket, Operator, Panel
from bpy.props import PointerProperty, StringProperty

_TREE_ID = "NuclearPegTree"
_PEG_NODE_ID = "NuclearPegNode"
_DRAWING_NODE_ID = "NuclearDrawingNode"
_SOCK_ID = "NuclearPegSocket"

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


class NuclearDrawingNode(_PegGraphNode, Node):
    bl_idname = _DRAWING_NODE_ID
    bl_label = "Drawing"
    bl_icon = 'OUTLINER_OB_GREASEPENCIL'

    object_name: StringProperty(name="Object")

    def init(self, _context):
        self.inputs.new(_SOCK_ID, "Peg")
        self.use_custom_color = True
        self.color = (0.12, 0.20, 0.28)

    def draw_label(self):
        return self.object_name or "Drawing"


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


def active_peg(context):
    """Resolve the peg currently controlled by the active object, honouring the Ctrl+B climb
    (PegRig.active_peg_index) when it is the object's own peg or an ancestor of it.
    \return (rig, peg) or (None, None)."""
    ob = context.active_object
    if ob is None:
        return None, None
    con = _followpeg_constraint(ob)
    if con is None or con.rig is None:
        return None, None
    rig = con.rig
    obj_idx = rig.pegs.find(con.peg_name)
    if obj_idx < 0:
        return None, None
    idx = obj_idx
    a = rig.active_peg_index
    if 0 <= a < len(rig.pegs) and (a == obj_idx or _is_ancestor(rig, a, obj_idx)):
        idx = a
    return rig, rig.pegs[idx]


def _peg_local_matrix(peg):
    """Replicate BKE_pegrig peg local matrix: T(t+p) * R * S * T(-p)."""
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


# -------------------------------------------------------------------------------------------------
# rig -> graph (generate the node tree from the rig)
# -------------------------------------------------------------------------------------------------

def rebuild(tree):
    global _SYNCING
    rig = tree.rig
    _SYNCING = True
    try:
        tree.nodes.clear()
        if rig is None:
            return

        rows = {}

        def place(node, depth):
            row = rows.get(depth, 0)
            rows[depth] = row + 1
            node.location = (depth * 240.0, -row * 150.0)

        # Peg nodes, indexed to match rig.pegs.
        peg_nodes = []
        for i, peg in enumerate(rig.pegs):
            node = tree.nodes.new(_PEG_NODE_ID)
            node.peg_name = peg.name
            place(node, _peg_depth(rig, i))
            peg_nodes.append(node)

        # Parent links (parent.output -> child.input).
        for i, peg in enumerate(rig.pegs):
            parent = peg.parent_index
            if 0 <= parent < len(peg_nodes) and parent != i:
                tree.links.new(peg_nodes[parent].outputs[0], peg_nodes[i].inputs[0])

        # Drawing nodes linked to their controlling peg.
        peg_node_by_name = {n.peg_name: n for n in peg_nodes}
        max_depth = max(rows.keys(), default=0)
        for ob, peg_name in _bound_objects(rig):
            dn = tree.nodes.new(_DRAWING_NODE_ID)
            dn.object_name = ob.name
            place(dn, max_depth + 1)
            peg_node = peg_node_by_name.get(peg_name)
            if peg_node is not None:
                tree.links.new(peg_node.outputs[0], dn.inputs[0])
    finally:
        _SYNCING = False


def _graph_signature(tree):
    """Cheap fingerprint of the rig's structure, to detect when a rebuild is needed."""
    rig = tree.rig
    if rig is None:
        return ""
    pegs = ";".join(f"{p.name}:{p.parent_index}" for p in rig.pegs)
    bound = ";".join(sorted(f"{ob.name}->{name}" for ob, name in _bound_objects(rig)))
    return pegs + "|" + bound


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
                elif con is not None:
                    ob.constraints.remove(con)

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
        tree.rig.pegs.new(self.name)
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
            count += 1
        if count == 0:
            self.report({'WARNING'}, "No Grease Pencil objects selected")
            return {'CANCELLED'}
        rebuild(tree)
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
        world = _peg_world_matrix(rig, self._idx)
        # Project on the plane through the controlled drawing so the drag stays under the cursor.
        ob = context.active_object
        self._anchor = ob.matrix_world.translation.copy() if ob else (world @ self._init_pivot)
        rot = world.to_3x3()
        try:
            self._rot_inv = rot.inverted()
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
        row = box.row(align=True)
        row.operator("object.pegrig_pivot_grab", text="Grab Pivot (P)", icon='PIVOT_CURSOR')
        row.operator("object.pegrig_pivot_reset", text="", icon='LOOP_BACK')


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


@bpy.app.handlers.persistent
def _load_post(*_args):
    _ensure_peg_pose_keymap()


# -------------------------------------------------------------------------------------------------
# Registration
# -------------------------------------------------------------------------------------------------

classes = (
    NuclearPegSocket,
    NuclearPegTree,
    NuclearPegNode,
    NuclearDrawingNode,
    NODE_OT_nuclear_peg_sync,
    NODE_OT_nuclear_peg_add,
    NODE_OT_nuclear_peg_remove,
    NODE_OT_nuclear_peg_bind_selected,
    NODE_PT_nuclear_peg,
    OBJECT_OT_pegrig_pivot_reset,
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
    _ensure_peg_pose_keymap()


def unregister():
    if _load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_post)
    if _depsgraph_update_post in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_depsgraph_update_post)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
