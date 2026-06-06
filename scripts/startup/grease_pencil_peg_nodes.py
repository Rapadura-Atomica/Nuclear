# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Grease Pencil peg node graph (object level).

A Toon Boom-style node view for rigging a character made of several Grease Pencil objects
(the "strokes" / body parts). Pegs are styled Empty objects that control the strokes through
native object parenting. The graph is scoped to a collection (the character):

    Collection (character)
      Peg "Master" (empty)
        Peg "Arm" (empty) -> Stroke "Arm" (GP object) -> [enter] its layers
        Peg "Hand"(empty) -> Stroke "Hand"(GP object)

Nodes are pegs/strokes, links are object parenting. Entering a stroke shows its drawing layers.
"""

import bpy
from bpy.types import NodeTree, Node, NodeSocket, Operator, Panel

# Guard so rebuilding the graph (which edits links) does not recursively re-apply it.
_syncing = False

_TREE_ID = 'GreasePencilPegTree'
_PEG_ID = 'GreasePencilPegNode'
_STROKE_ID = 'GreasePencilStrokeNode'
_LAYER_ID = 'GreasePencilLayerNode'
_SOCK_ID = 'GreasePencilPegSocket'
_PEG_PROP = "gp_peg"  # custom property marking an Empty as a peg
_TREE_PREFIX = ".PegGraph::"


def _is_peg(ob):
    return ob is not None and ob.type == 'EMPTY' and bool(ob.get(_PEG_PROP, False))


def _is_stroke(ob):
    return ob is not None and ob.type == 'GREASEPENCIL'


def _make_peg(name, collection):
    """Create a styled peg Empty and link it to a collection."""
    peg = bpy.data.objects.new(name, None)
    peg.empty_display_type = 'CIRCLE'
    peg.empty_display_size = 0.5
    peg.show_in_front = True
    peg.show_name = True
    peg[_PEG_PROP] = True
    collection.objects.link(peg)
    return peg


def _set_parent(child, parent):
    """Parent child to parent (or unparent if None), keeping its world transform."""
    if child.parent is parent:
        return
    if parent is not None and parent is child:
        return
    matrix = child.matrix_world.copy()
    child.parent = parent
    child.matrix_parent_inverse.identity()
    child.matrix_world = matrix


def _parent_depth(ob, members):
    depth = 0
    parent = ob.parent
    while parent is not None and parent in members:
        depth += 1
        parent = parent.parent
    return depth


def rebuild_from_collection(tree):
    """Rebuild the rig graph from the target collection's pegs and strokes."""
    global _syncing
    coll = tree.target_collection
    if coll is None:
        return
    _syncing = True
    try:
        tree.nodes.clear()
        members = set(coll.all_objects)
        node_by_object = {}
        rows = {}

        def place(node, ob):
            depth = _parent_depth(ob, members)
            row = rows.get(depth, 0)
            rows[depth] = row + 1
            node.location = (depth * 280.0, -row * 170.0)

        for ob in coll.all_objects:
            if _is_peg(ob):
                node = tree.nodes.new(_PEG_ID)
            elif _is_stroke(ob):
                node = tree.nodes.new(_STROKE_ID)
            else:
                continue
            node.object_name = ob.name
            place(node, ob)
            node_by_object[ob.name] = node

        for ob in coll.all_objects:
            node = node_by_object.get(ob.name)
            if node is None:
                continue
            parent = ob.parent
            if parent is not None and _is_peg(parent) and parent.name in node_by_object:
                tree.links.new(node_by_object[parent.name].outputs[0], node.inputs[0])
    finally:
        _syncing = False


def _apply_links(tree):
    """Reparent each object to match its node's Parent link."""
    global _syncing
    coll = tree.target_collection
    if coll is None:
        return
    try:
        objects = bpy.data.objects
    except AttributeError:
        # `bpy.data` is restricted (e.g. during file load or teardown); skip safely.
        return
    _syncing = True
    try:
        for node in tree.nodes:
            if node.bl_idname not in {_PEG_ID, _STROKE_ID}:
                continue
            child = objects.get(node.object_name)
            if child is None:
                continue
            parent = None
            socket = node.inputs[0]
            if socket.is_linked:
                from_node = socket.links[0].from_node
                if from_node.bl_idname == _PEG_ID:
                    parent = objects.get(from_node.object_name)
            _set_parent(child, parent)
    finally:
        _syncing = False


def build_layers(tree):
    """Project the drawing layers of a stroke (GP object) as nodes (the piece level)."""
    global _syncing
    ob = bpy.data.objects.get(tree.target_object)
    if ob is None or ob.type != 'GREASEPENCIL':
        return
    _syncing = True
    try:
        tree.nodes.clear()
        for i, layer in enumerate(ob.data.layers):
            node = tree.nodes.new(_LAYER_ID)
            node.layer_name = layer.name
            node.location = (0.0, -i * 140.0)
    finally:
        _syncing = False


def _get_or_make_tree(key, level):
    name = _TREE_PREFIX + key
    tree = bpy.data.node_groups.get(name)
    if tree is None or tree.bl_idname != _TREE_ID:
        tree = bpy.data.node_groups.new(name, _TREE_ID)
    tree.level = level
    return tree


class GreasePencilPegTree(NodeTree):
    """Node graph for rigging a Grease Pencil character (pegs + strokes of a collection)"""
    bl_idname = _TREE_ID
    bl_label = "Grease Pencil Pegs"
    bl_icon = 'OUTLINER_OB_EMPTY'

    level: bpy.props.EnumProperty(
        name="Level",
        items=(
            ('RIG', "Rig", "The pegs and strokes of a character collection"),
            ('PIECE', "Piece", "The drawing layers of a stroke"),
        ),
        default='RIG',
    )

    target_collection: bpy.props.PointerProperty(
        type=bpy.types.Collection,
        name="Character",
        description="Collection whose pegs and strokes this graph rigs",
    )

    target_object: bpy.props.StringProperty(
        name="Stroke",
        description="Name of the stroke (GP object) whose layers this graph shows",
    )

    def update(self):
        if _syncing or self.level != 'RIG':
            return
        _apply_links(self)


class GreasePencilPegSocket(NodeSocket):
    """Peg parent/child connection"""
    bl_idname = _SOCK_ID
    bl_label = "Peg"

    def draw(self, context, layout, node, text):
        layout.label(text=text)

    @classmethod
    def draw_color_simple(cls):
        return (0.91, 0.62, 0.24, 1.0)


class _PegTreeNode:
    @classmethod
    def poll(cls, ntree):
        return ntree.bl_idname == _TREE_ID


class GreasePencilPegNode(_PegTreeNode, Node):
    """A peg: a styled Empty that controls strokes through object parenting"""
    bl_idname = _PEG_ID
    bl_label = "Peg"
    bl_icon = 'EMPTY_AXIS'

    object_name: bpy.props.StringProperty(name="Peg")

    def init(self, context):
        self.inputs.new(_SOCK_ID, "Parent")
        self.outputs.new(_SOCK_ID, "Children")
        self.use_custom_color = True
        self.color = (0.27, 0.20, 0.12)

    def _object(self):
        return bpy.data.objects.get(self.object_name)

    def draw_buttons(self, context, layout):
        ob = self._object()
        if ob is None:
            layout.label(text="Missing peg", icon='ERROR')
            return
        layout.prop(ob, "location", text="")
        layout.prop(ob, "rotation_euler", text="Rotation")
        layout.prop(ob, "scale", text="Scale")

    def draw_label(self):
        return self.object_name or "Peg"


class GreasePencilStrokeNode(_PegTreeNode, Node):
    """A stroke: a Grease Pencil object (a body part); enter it to edit its layers"""
    bl_idname = _STROKE_ID
    bl_label = "Stroke"
    bl_icon = 'OUTLINER_OB_GREASEPENCIL'

    object_name: bpy.props.StringProperty(name="Stroke")

    def init(self, context):
        self.inputs.new(_SOCK_ID, "Parent")
        self.use_custom_color = True
        self.color = (0.12, 0.20, 0.27)

    def _object(self):
        return bpy.data.objects.get(self.object_name)

    def draw_buttons(self, context, layout):
        ob = self._object()
        if ob is None:
            layout.label(text="Missing stroke", icon='ERROR')
            return
        layout.label(text="{} layer(s)".format(len(ob.data.layers)))
        layout.operator("node.grease_pencil_peg_enter", text="Enter", icon='ZOOM_IN')

    def draw_label(self):
        return self.object_name or "Stroke"


class GreasePencilLayerNode(_PegTreeNode, Node):
    """A drawing layer inside a stroke"""
    bl_idname = _LAYER_ID
    bl_label = "Layer"
    bl_icon = 'OUTLINER_DATA_GP_LAYER'

    layer_name: bpy.props.StringProperty(name="Layer")

    def init(self, context):
        self.use_custom_color = True
        self.color = (0.10, 0.16, 0.22)

    def draw_buttons(self, context, layout):
        tree = self.id_data
        ob = bpy.data.objects.get(tree.target_object)
        layer = ob.data.layers.get(self.layer_name) if ob else None
        if layer is None:
            layout.label(text="Missing layer", icon='ERROR')
            return
        layout.prop(layer, "opacity", text="Opacity", slider=True)

    def draw_label(self):
        return self.layer_name or "Layer"


def _peg_editor_poll(context):
    space = context.space_data
    return (
        space is not None
        and space.type == 'NODE_EDITOR'
        and space.tree_type == _TREE_ID
        and space.edit_tree is not None
    )


class NODE_OT_grease_pencil_peg_sync(Operator):
    """Show the rig of the active collection"""
    bl_idname = "node.grease_pencil_peg_sync"
    bl_label = "Sync from Active Collection"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space is not None and space.type == 'NODE_EDITOR' and space.tree_type == _TREE_ID

    def execute(self, context):
        snode = context.space_data
        coll = context.collection
        if coll is None:
            self.report({'WARNING'}, "No active collection")
            return {'CANCELLED'}
        tree = _get_or_make_tree("rig:" + coll.name, 'RIG')
        tree.target_collection = coll
        rebuild_from_collection(tree)
        snode.node_tree = tree
        return {'FINISHED'}


class NODE_OT_grease_pencil_peg_add(Operator):
    """Add a peg, as a child of the active peg node if one is selected"""
    bl_idname = "node.grease_pencil_peg_add"
    bl_label = "Add Peg"
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty(name="Name", default="Peg")

    @classmethod
    def poll(cls, context):
        return _peg_editor_poll(context) and context.space_data.edit_tree.level == 'RIG'

    def execute(self, context):
        tree = context.space_data.edit_tree
        coll = tree.target_collection
        if coll is None:
            self.report({'WARNING'}, "Sync a collection first")
            return {'CANCELLED'}
        peg = _make_peg(self.name, coll)
        active = tree.nodes.active
        if active is not None and active.bl_idname == _PEG_ID:
            parent = bpy.data.objects.get(active.object_name)
            if _is_peg(parent):
                _set_parent(peg, parent)
        rebuild_from_collection(tree)
        return {'FINISHED'}


class NODE_OT_grease_pencil_peg_delete_nodes(Operator):
    """Delete the selected pegs/strokes (their objects) from the character"""
    bl_idname = "node.grease_pencil_peg_delete_nodes"
    bl_label = "Delete"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not _peg_editor_poll(context):
            return False
        tree = context.space_data.edit_tree
        if tree.level != 'RIG':
            return False
        return any(n.select and n.bl_idname in {_PEG_ID, _STROKE_ID} for n in tree.nodes)

    def execute(self, context):
        tree = context.space_data.edit_tree
        names = [n.object_name for n in tree.nodes
                 if n.select and n.bl_idname in {_PEG_ID, _STROKE_ID}]
        for name in names:
            ob = bpy.data.objects.get(name)
            if ob is None:
                continue
            # Re-parent the object's children to its own parent so the rest of the rig survives.
            for child in list(ob.children):
                _set_parent(child, ob.parent)
            bpy.data.objects.remove(ob, do_unlink=True)
        rebuild_from_collection(tree)
        return {'FINISHED'}


class NODE_OT_grease_pencil_peg_enter(Operator):
    """Enter the active stroke to edit its drawing layers"""
    bl_idname = "node.grease_pencil_peg_enter"
    bl_label = "Enter"

    @classmethod
    def poll(cls, context):
        if not _peg_editor_poll(context):
            return False
        active = context.space_data.edit_tree.nodes.active
        return active is not None and active.bl_idname == _STROKE_ID

    def execute(self, context):
        snode = context.space_data
        active = snode.edit_tree.nodes.active
        ob = bpy.data.objects.get(active.object_name)
        if ob is None or ob.type != 'GREASEPENCIL':
            return {'CANCELLED'}
        child = _get_or_make_tree("layers:" + ob.name, 'PIECE')
        child.target_object = ob.name
        build_layers(child)
        snode.path.append(child, node=active)
        return {'FINISHED'}


class NODE_OT_grease_pencil_peg_back(Operator):
    """Go back up one level"""
    bl_idname = "node.grease_pencil_peg_back"
    bl_label = "Back"

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return (
            space is not None
            and space.type == 'NODE_EDITOR'
            and space.tree_type == _TREE_ID
            and len(space.path) > 1
        )

    def execute(self, context):
        context.space_data.path.pop()
        return {'FINISHED'}


def _controlling_peg(ob):
    """The peg that controls an object: itself if it is a peg, else the nearest peg ancestor."""
    if ob is None:
        return None
    if _is_peg(ob):
        return ob
    parent = ob.parent
    while parent is not None and not _is_peg(parent):
        parent = parent.parent
    return parent


class OBJECT_OT_grease_pencil_peg_select(Operator):
    """Select the peg controlling whatever is under the cursor (this tool only selects pegs)"""
    bl_idname = "object.grease_pencil_peg_select"
    bl_label = "Select Peg"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and context.region_data is not None

    def _select_only(self, context, target):
        for ob in context.selected_objects:
            ob.select_set(False)
        if target is not None:
            target.select_set(True)
        context.view_layer.objects.active = target

    def invoke(self, context, event):
        # Identify what is under the cursor using the native object pick, then redirect the
        # selection to its controlling peg. The click is always consumed so it never leaves a
        # drawing selected (those are for the native select tools).
        bpy.ops.view3d.select(
            location=(event.mouse_region_x, event.mouse_region_y), deselect_all=True)
        picked = context.selected_objects
        hit = picked[0] if picked else None
        self._select_only(context, _controlling_peg(hit))
        return {'FINISHED'}


class OBJECT_OT_grease_pencil_peg_select_parent(Operator):
    """Select the parent peg of the active peg, going up the hierarchy"""
    bl_idname = "object.grease_pencil_peg_select_parent"
    bl_label = "Select Parent Peg"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _is_peg(context.active_object)

    def execute(self, context):
        ob = context.active_object
        parent = ob.parent
        if parent is None or not _is_peg(parent):
            return {'CANCELLED'}
        for other in context.selected_objects:
            other.select_set(False)
        parent.select_set(True)
        context.view_layer.objects.active = parent
        return {'FINISHED'}


class NODE_PT_grease_pencil_peg(Panel):
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Pegs"
    bl_label = "Peg Rig"

    @classmethod
    def poll(cls, context):
        return _peg_editor_poll(context)

    def draw(self, context):
        layout = self.layout
        snode = context.space_data
        tree = snode.edit_tree

        row = layout.row(align=True)
        row.operator("node.grease_pencil_peg_sync", text="Sync", icon='FILE_REFRESH')
        sub = row.row(align=True)
        sub.enabled = len(snode.path) > 1
        sub.operator("node.grease_pencil_peg_back", text="Back", icon='BACK')
        layout.separator()

        if tree.level == 'PIECE':
            ob = bpy.data.objects.get(tree.target_object)
            layout.label(text=(ob.name if ob else "—"), icon='OUTLINER_OB_GREASEPENCIL')
            layout.label(text="Layers of this stroke")
        else:  # RIG
            layout.prop(tree, "target_collection")
            col = layout.column(align=True)
            col.operator("node.grease_pencil_peg_add", icon='ADD')
            col.operator("node.grease_pencil_peg_delete_nodes", icon='X')


def _draw_add_menu(self, context):
    if context.space_data.tree_type != _TREE_ID:
        return
    self.layout.operator("node.grease_pencil_peg_add", icon='EMPTY_AXIS')


classes = (
    GreasePencilPegTree,
    GreasePencilPegSocket,
    GreasePencilPegNode,
    GreasePencilStrokeNode,
    GreasePencilLayerNode,
    NODE_OT_grease_pencil_peg_sync,
    NODE_OT_grease_pencil_peg_add,
    NODE_OT_grease_pencil_peg_delete_nodes,
    NODE_OT_grease_pencil_peg_enter,
    NODE_OT_grease_pencil_peg_back,
    OBJECT_OT_grease_pencil_peg_select,
    OBJECT_OT_grease_pencil_peg_select_parent,
    NODE_PT_grease_pencil_peg,
)

_addon_keymaps = []


def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)
    bpy.types.NODE_MT_add.append(_draw_add_menu)

    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is not None:
        km = kc.keymaps.new(name="Node Editor", space_type='NODE_EDITOR')
        _addon_keymaps.append(
            (km, km.keymap_items.new("node.grease_pencil_peg_enter", 'TAB', 'PRESS')))
        _addon_keymaps.append(
            (km, km.keymap_items.new("node.grease_pencil_peg_back", 'TAB', 'PRESS', ctrl=True)))
        for key in ('X', 'DEL'):
            _addon_keymaps.append(
                (km, km.keymap_items.new("node.grease_pencil_peg_delete_nodes", key, 'PRESS')))


def unregister():
    for km, kmi in _addon_keymaps:
        km.keymap_items.remove(kmi)
    _addon_keymaps.clear()
    bpy.types.NODE_MT_add.remove(_draw_add_menu)
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)


if __name__ == "__main__":
    register()
