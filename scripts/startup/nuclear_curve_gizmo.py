# SPDX-FileCopyrightText: 2024 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Nuclear: bezier-deform control-point gizmos for the Peg Pose tool.

When a Grease Pencil object that carries a "Curve" deform modifier is active under
the Peg Pose tool, this draws draggable handles on the deform curve directly in the
viewport - one big ring per bezier control point plus two small rings for its left
and right tangent handles - so the artist can shape the curve exactly like in Edit
Mode, without leaving Object mode. Empty clicks/drags fall through to the tool
keymap (pick a drawing / move its peg).

The gizmo group is bound to the tool through the ToolDef ``widget`` field (see
``space_toolsystem_toolbar.py``: ``builtin.peg_pose``), so it only appears while
that tool is active.
"""

import bpy
from bpy.types import GizmoGroup
from mathutils import Vector

# kind of a handle slot
_CO = 'CO'        # the control point itself (moves the point and both tangents)
_HL = 'HL'        # left tangent handle
_HR = 'HR'        # right tangent handle


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


class NUCLEAR_GGT_curve_deform_points(GizmoGroup):
    bl_idname = "NUCLEAR_GGT_curve_deform_points"
    bl_label = "Bezier Deform Points"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'3D', 'PERSISTENT'}

    @classmethod
    def poll(cls, context):
        # Only in object mode, and only for a GP whose Curve modifier targets a real curve.
        if context.mode != 'OBJECT':
            return False
        return _find_curve_modifier(context.object) is not None

    # -- helpers -------------------------------------------------------------------------------

    def _curve_object(self, context):
        md = _find_curve_modifier(context.object)
        return md.object if md is not None else None

    def _coord_world(self, si, pi, kind):
        bp = self._curve_ob.data.splines[si].bezier_points[pi]
        local = {_CO: bp.co, _HL: bp.handle_left, _HR: bp.handle_right}[kind]
        return self._curve_ob.matrix_world @ local

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
                # Editing a tangent: free the handles first so the manual position sticks
                # (auto/aligned handles would be recomputed), exactly like grabbing a handle in
                # Edit Mode.
                bp.handle_left_type = 'FREE'
                bp.handle_right_type = 'FREE'
                if kind == _HL:
                    bp.handle_left = new_local
                else:
                    bp.handle_right = new_local
            curve_ob.data.update_tag()
        return _set

    def _new_gizmo(self, si, pi, kind):
        gz = self.gizmos.new("GIZMO_GT_move_3d")
        gz.draw_style = 'RING_2D'
        gz.draw_options = {'ALIGN_VIEW'}
        gz.use_draw_modal = True
        if kind == _CO:
            gz.scale_basis = 0.14
            gz.color = 0.12, 0.6, 1.0          # blue: control point
            gz.alpha = 0.7
        else:
            gz.scale_basis = 0.09
            gz.color = 1.0, 0.6, 0.1           # orange: tangent handle
            gz.alpha = 0.6
        gz.color_highlight = 1.0, 1.0, 1.0
        gz.alpha_highlight = 1.0
        gz.target_set_handler("offset", get=self._make_get(si, pi, kind), set=self._make_set(si, pi, kind))
        return gz

    def _build(self, context):
        self.gizmos.clear()
        self._slots = []
        curve_ob = self._curve_object(context)
        self._curve_ob = curve_ob
        if curve_ob is None:
            return
        for (si, pi) in _bezier_points(curve_ob):
            for kind in (_CO, _HL, _HR):
                gz = self._new_gizmo(si, pi, kind)
                self._slots.append((gz, si, pi, kind))

    def _expected_count(self, context):
        curve_ob = self._curve_object(context)
        if curve_ob is None:
            return 0
        return sum(1 for _ in _bezier_points(curve_ob)) * 3

    # -- gizmo group callbacks -----------------------------------------------------------------

    def setup(self, context):
        self._curve_ob = None
        self._slots = []
        self._build(context)

    def refresh(self, context):
        # Rebuild when the target curve or its point count changes (object switch, add/remove point).
        if self._curve_object(context) is not getattr(self, "_curve_ob", None) or \
                len(self._slots) != self._expected_count(context):
            self._build(context)
            return
        # Keep each handle world-axis aligned; location is provided by the get handler.
        for (gz, si, pi, kind) in self._slots:
            gz.matrix_basis.identity()


classes = (
    NUCLEAR_GGT_curve_deform_points,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
