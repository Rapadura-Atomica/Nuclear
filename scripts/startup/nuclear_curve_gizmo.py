# SPDX-FileCopyrightText: 2024 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Nuclear: bezier-deform control-point gizmos for Grease Pencil "Curve" modifiers.

Whenever a Grease Pencil object that carries a "Curve" deform modifier is the active
object (any tool, Object mode), this draws draggable handles on the deform curve
right in the viewport - one big ring per bezier control point plus two small rings
for its left/right tangent handles - plus thin lines connecting them, so the curve
can be shaped exactly like in Edit Mode without selecting the curve object.

- Dragging a point ring moves the point and carries both tangents.
- Dragging a tangent ring shapes the curvature (the handle is freed first, like
  grabbing a handle in Edit Mode).
- With Auto Keying on, dragging inserts keyframes on the affected control point, so
  the deformation can be animated.

The gizmo group is tool-independent (poll-driven): it appears for the active GP, so
you can deform with the GP object active instead of having to engage the curve.
"""

import bpy
import gpu
from bpy.types import GizmoGroup
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

# kind of a handle slot
_CO = 'CO'        # the control point itself (moves the point and both tangents)
_HL = 'HL'        # left tangent handle
_HR = 'HR'        # right tangent handle

# colors (RGB)
_COL_POINT = (0.12, 0.6, 1.0)      # blue: control point
_COL_HANDLE = (1.0, 0.05, 0.05)    # vivid red: tangent handle
_COL_LINE = (1.0, 0.1, 0.1, 0.7)   # RGBA: handle arms (red)


def _find_curve_modifier(ob):
    """Return the first bound-capable GREASE_PENCIL_CURVE modifier of ``ob``, or None."""
    if ob is None or ob.type != 'GREASEPENCIL':
        return None
    for md in ob.modifiers:
        if md.type == 'GREASE_PENCIL_CURVE' and md.object is not None and md.object.type == 'CURVE':
            return md
    return None


def _bezier_points(curve_ob):
    """Yield (spline_index, point_index) for every bezier control point of the curve object."""
    for si, spline in enumerate(curve_ob.data.splines):
        if spline.type != 'BEZIER':
            continue
        for pi in range(len(spline.bezier_points)):
            yield (si, pi)


def _active_deform_curve(context):
    if context.mode != 'OBJECT':
        return None
    md = _find_curve_modifier(context.object)
    return md.object if md is not None else None


class NUCLEAR_GGT_curve_deform_points(GizmoGroup):
    bl_idname = "NUCLEAR_GGT_curve_deform_points"
    bl_label = "Bezier Deform Points"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'3D', 'PERSISTENT', 'SHOW_MODAL_ALL'}

    @classmethod
    def poll(cls, context):
        return _active_deform_curve(context) is not None

    # -- helpers -------------------------------------------------------------------------------

    def _coord_world(self, si, pi, kind):
        bp = self._curve_ob.data.splines[si].bezier_points[pi]
        local = {_CO: bp.co, _HL: bp.handle_left, _HR: bp.handle_right}[kind]
        return self._curve_ob.matrix_world @ local

    def _autokey(self, curve_ob, si, pi):
        scene = bpy.context.scene
        if scene is None or not scene.tool_settings.use_keyframe_insert_auto:
            return
        base = "splines[%d].bezier_points[%d]" % (si, pi)
        for prop in (".co", ".handle_left", ".handle_right"):
            try:
                curve_ob.data.keyframe_insert(data_path=base + prop)
            except RuntimeError:
                pass

    def _make_get(self, si, pi, kind):
        def _get():
            if self._curve_ob is None:
                return Vector((0.0, 0.0, 0.0))
            return self._coord_world(si, pi, kind)
        return _get

    def _make_set(self, si, pi, kind):
        def _set(value):
            curve_ob = self._curve_ob
            if curve_ob is None:
                return
            bp = curve_ob.data.splines[si].bezier_points[pi]
            new_local = curve_ob.matrix_world.inverted() @ Vector(value)
            if kind == _CO:
                # Move the point and carry both tangents, so grabbing a point translates it rigidly.
                delta = new_local - bp.co
                bp.co = new_local
                bp.handle_left = bp.handle_left + delta
                bp.handle_right = bp.handle_right + delta
            else:
                # Editing a tangent: free the handles so the manual position sticks (auto/aligned
                # handles would be recomputed), exactly like grabbing a handle in Edit Mode.
                bp.handle_left_type = 'FREE'
                bp.handle_right_type = 'FREE'
                if kind == _HL:
                    bp.handle_left = new_local
                else:
                    bp.handle_right = new_local
            self._autokey(curve_ob, si, pi)
            curve_ob.data.update_tag()
        return _set

    def _new_gizmo(self, si, pi, kind):
        gz = self.gizmos.new("GIZMO_GT_move_3d")
        gz.draw_style = 'RING_2D'
        gz.draw_options = {'ALIGN_VIEW'}
        gz.use_draw_modal = True
        if kind == _CO:
            gz.scale_basis = 0.13
            gz.color = _COL_POINT
            gz.alpha = 0.8
        else:
            gz.scale_basis = 0.08
            gz.color = _COL_HANDLE
            gz.alpha = 0.7
        gz.color_highlight = 1.0, 1.0, 1.0
        gz.alpha_highlight = 1.0
        gz.target_set_handler("offset", get=self._make_get(si, pi, kind), set=self._make_set(si, pi, kind))
        return gz

    def _build(self, context):
        self.gizmos.clear()
        self._slots = []
        self._curve_ob = _active_deform_curve(context)
        if self._curve_ob is None:
            return
        for (si, pi) in _bezier_points(self._curve_ob):
            for kind in (_CO, _HL, _HR):
                self._new_gizmo(si, pi, kind)
                self._slots.append((si, pi, kind))

    def _expected_count(self, context):
        cur = _active_deform_curve(context)
        if cur is None:
            return 0
        return sum(1 for _ in _bezier_points(cur)) * 3

    # -- gizmo group callbacks -----------------------------------------------------------------

    def setup(self, context):
        self._curve_ob = None
        self._slots = []
        self._build(context)

    def refresh(self, context):
        if _active_deform_curve(context) is not getattr(self, "_curve_ob", None) or \
                len(self._slots) != self._expected_count(context):
            self._build(context)
            return
        for gz in self.gizmos:
            gz.matrix_basis.identity()


# -------------------------------------------------------------------------------------------------
# Overlay: thin lines from each control point to its tangent handles (the Edit Mode look).
# -------------------------------------------------------------------------------------------------

_draw_handle = None
_line_shader = None


def _draw_curve_handles():
    context = bpy.context
    curve_ob = _active_deform_curve(context)
    if curve_ob is None:
        return
    mw = curve_ob.matrix_world
    coords = []
    for (si, pi) in _bezier_points(curve_ob):
        bp = curve_ob.data.splines[si].bezier_points[pi]
        co = mw @ bp.co
        coords.append(mw @ bp.handle_left)
        coords.append(co)
        coords.append(co)
        coords.append(mw @ bp.handle_right)
    if not coords:
        return
    global _line_shader
    if _line_shader is None:
        _line_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(_line_shader, 'LINES', {"pos": coords})
    gpu.state.line_width_set(1.5)
    gpu.state.blend_set('ALPHA')
    _line_shader.bind()
    _line_shader.uniform_float("color", _COL_LINE)
    batch.draw(_line_shader)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


classes = (
    NUCLEAR_GGT_curve_deform_points,
)


def register():
    global _draw_handle
    for cls in classes:
        bpy.utils.register_class(cls)
    if _draw_handle is None:
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_curve_handles, (), 'WINDOW', 'POST_VIEW')


def unregister():
    global _draw_handle
    if _draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
