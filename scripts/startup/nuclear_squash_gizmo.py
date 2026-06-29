# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Nuclear: squash & stretch gizmos for peg rigs (see tools/nuclear_claude/SquashFeature.md).

When the active Grease Pencil object's controlled peg has squash enabled (use_squash),
this draws two draggable rings in the viewport - a base/anchor ring (planted) and a top/
tip ring - plus a thin line along the squash axis. Dragging the tip away from the anchor
stretches the body; dragging it closer squashes it, with the orthogonal axis compensating
to preserve area. The anchor stays put because both points live in the peg's PARENT space.

- The gizmo group is tool-independent (poll-driven): it appears for the active GP whose
  controlled peg (honouring the Ctrl+B climb) has squash on, in Object mode.
- With Auto Keying on, dragging inserts keyframes on the moved point so squash animates.

This mirrors nuclear_curve_gizmo.py (the GIZMO_GT_move_3d + offset-handler pattern) and
replicates the peg world-matrix math from nuclear_peg_graph.py to stay self-contained.
"""

import bpy
import gpu
from bpy.types import GizmoGroup
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector, Euler

_ANCHOR = 'ANCHOR'  # planted base point (also the squash pivot)
_TIP = 'TIP'        # top point; anchor->tip defines the squash axis and length

_COL_ANCHOR = (0.2, 0.8, 0.3)   # green: planted base
_COL_TIP = (1.0, 0.5, 0.1)      # orange: movable top
_COL_AXIS = (1.0, 0.7, 0.2, 0.7)  # RGBA: the axis line


def _followpeg(ob):
    """Return the object's Follow Peg constraint, or None."""
    if ob is None or ob.type != 'GREASEPENCIL':
        return None
    for con in ob.constraints:
        if con.type == 'FOLLOW_PEG':
            return con
    return None


def _is_ancestor(rig, ancestor, idx):
    p = rig.pegs[idx].parent_index
    guard = 0
    while 0 <= p < len(rig.pegs) and guard <= len(rig.pegs):
        if p == ancestor:
            return True
        p = rig.pegs[p].parent_index
        guard += 1
    return False


def _active_squash(context):
    """Resolve the controlled peg of the active object when it has squash enabled.
    Honours the Ctrl+B climb (active_peg_index) like nuclear_peg_graph.active_peg.
    \return (rig, peg, idx) or None."""
    if context.mode != 'OBJECT':
        return None
    ob = context.active_object
    con = _followpeg(ob)
    if con is None or con.rig is None:
        return None
    rig = con.rig
    obj_idx = rig.pegs.find(con.peg_name)
    if obj_idx < 0:
        return None
    idx = obj_idx
    a = rig.active_peg_index
    if 0 <= a < len(rig.pegs) and (a == obj_idx or _is_ancestor(rig, a, obj_idx)):
        idx = a
    peg = rig.pegs[idx]
    if not peg.use_squash:
        return None
    return rig, peg, idx


def _peg_local_matrix(peg):
    """T(t+p) * R * S * T(-p) - matches BKE_pegrig peg local matrix (without squash, which is
    not needed for a parent/ancestor frame)."""
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
        chain.append(rig.pegs[i])
        i = rig.pegs[i].parent_index
        guard += 1
    m = Matrix.Identity(4)
    for peg in reversed(chain):
        m = m @ _peg_local_matrix(peg)
    return m


def _parent_world(rig, peg):
    """World matrix of the peg's PARENT (the space anchor/tip live in), or identity for a root."""
    p = peg.parent_index
    if 0 <= p < len(rig.pegs):
        return _peg_world_matrix(rig, p)
    return Matrix.Identity(4)


class NUCLEAR_GGT_squash(GizmoGroup):
    bl_idname = "NUCLEAR_GGT_squash"
    bl_label = "Squash & Stretch"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'3D', 'PERSISTENT', 'SHOW_MODAL_ALL'}

    @classmethod
    def poll(cls, context):
        return _active_squash(context) is not None

    def _autokey(self, peg, attr):
        scene = bpy.context.scene
        if scene is None or not scene.tool_settings.use_keyframe_insert_auto:
            return
        try:
            peg.keyframe_insert(data_path=attr)
        except RuntimeError:
            pass

    def _make_get(self, which):
        def _get():
            res = _active_squash(bpy.context)
            if res is None:
                return Vector((0.0, 0.0, 0.0))
            rig, peg, idx = res
            local = peg.squash_anchor if which == _ANCHOR else peg.squash_tip
            # anchor/tip live in the peg's OWN posed frame so the squash follows the rig.
            return _peg_world_matrix(rig, idx) @ Vector(local)
        return _get

    def _make_set(self, which):
        def _set(value):
            res = _active_squash(bpy.context)
            if res is None:
                return
            rig, peg, idx = res
            pw = _peg_world_matrix(rig, idx)
            try:
                local = pw.inverted() @ Vector(value)
            except ValueError:
                local = Vector(value)
            if which == _ANCHOR:
                # Keep the anchor in the XZ drawing plane (Y = depth stays 0).
                peg.squash_anchor = (local.x, 0.0, local.z)
                self._autokey(peg, "squash_anchor")
            else:
                # Lock the tip directly above the anchor along local Z so the squash axis stays
                # vertical/axis-aligned (X/Z) and can never go diagonal. Only its Z (height) drives
                # the squash factor.
                anchor = peg.squash_anchor
                peg.squash_tip = (anchor[0], anchor[1], local.z)
                self._autokey(peg, "squash_tip")
            rig.id_data.update_tag()
            area = bpy.context.area
            if area is not None:
                area.tag_redraw()
        return _set

    def _new_gizmo(self, which):
        gz = self.gizmos.new("GIZMO_GT_move_3d")
        gz.draw_style = 'RING_2D'
        gz.draw_options = {'ALIGN_VIEW'}
        gz.use_draw_modal = True
        gz.scale_basis = 0.12
        gz.color = _COL_ANCHOR if which == _ANCHOR else _COL_TIP
        gz.alpha = 0.8
        gz.color_highlight = 1.0, 1.0, 1.0
        gz.alpha_highlight = 1.0
        gz.target_set_handler("offset", get=self._make_get(which), set=self._make_set(which))
        return gz

    def setup(self, context):
        self._new_gizmo(_ANCHOR)
        self._new_gizmo(_TIP)

    def refresh(self, context):
        # matrix_basis stays identity; the offset handler returns world coordinates directly.
        for gz in self.gizmos:
            gz.matrix_basis.identity()


# -------------------------------------------------------------------------------------------------
# Overlay: a thin line along the squash axis (anchor -> tip), for readability.
# -------------------------------------------------------------------------------------------------

_draw_handle = None
_line_shader = None


def _safe_draw(fn):
    # Wrap a GPU draw callback so a transient bad state (mid-edit/undo/eval) raises into
    # a printed traceback instead of a broken/spamming overlay.
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            import traceback
            traceback.print_exc()
    return wrapper


@_safe_draw
def _draw_squash_axis():
    res = _active_squash(bpy.context)
    if res is None:
        return
    rig, peg, idx = res
    pw = _peg_world_matrix(rig, idx)
    # Draw the axis straight up from the anchor (the squash is vertical/axis-aligned along local Z),
    # so the line always reflects the real deformation axis.
    anchor = Vector(peg.squash_anchor)
    top = Vector((anchor.x, anchor.y, peg.squash_tip[2]))
    coords = [pw @ anchor, pw @ top]
    global _line_shader
    if _line_shader is None:
        _line_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(_line_shader, 'LINES', {"pos": coords})
    gpu.state.line_width_set(1.5)
    gpu.state.blend_set('ALPHA')
    _line_shader.bind()
    _line_shader.uniform_float("color", _COL_AXIS)
    batch.draw(_line_shader)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


classes = (
    NUCLEAR_GGT_squash,
)


def register():
    global _draw_handle
    for cls in classes:
        bpy.utils.register_class(cls)
    if _draw_handle is None:
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_squash_axis, (), 'WINDOW', 'POST_VIEW')


def unregister():
    global _draw_handle
    if _draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
