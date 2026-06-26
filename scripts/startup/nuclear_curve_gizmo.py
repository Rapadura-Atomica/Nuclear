# SPDX-FileCopyrightText: 2024 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Nuclear: bezier-deform control-point gizmos for Grease Pencil "Curve" modifiers.

Whenever a Grease Pencil object that carries a "Curve" deform modifier is the active
object (any tool, Object mode), this draws draggable handles on the deform curve right
in the viewport - one dot per bezier control point (blue) plus two small dots for its
left/right tangent handles (red) - plus thin lines connecting them, so the curve can be
shaped exactly like in Edit Mode without selecting the curve object.

Interaction (each dot is a custom gizmo):
- Click a dot       -> SELECT only that point/handle (turns yellow). The selection is
                       stored in the curve's own Bezier select flags, so "Reset Selected"
                       (modifier panel / N-panel / Alt+R) resets exactly these.
- Shift+click a dot -> add/remove it from the selection (build a multi-selection).
- Drag a dot        -> move it (a control point carries both tangents; a tangent is freed
                       first, like grabbing a handle in Edit Mode). With Auto Keying on,
                       the drag inserts keyframes so the deformation can be animated.
"""

import bpy
import gpu
from bpy.types import Gizmo, GizmoGroup
from gpu_extras.batch import batch_for_shader
from mathutils import Vector, Matrix
from bpy_extras.view3d_utils import region_2d_to_location_3d, location_3d_to_region_2d

# kind of a handle slot
_CO = 'CO'        # the control point itself (moves the point and both tangents)
_HL = 'HL'        # left tangent handle
_HR = 'HR'        # right tangent handle

# colors (RGB)
_COL_POINT = (0.12, 0.6, 1.0)      # blue: control point
_COL_HANDLE = (1.0, 0.05, 0.05)    # vivid red: tangent handle
_COL_SELECT = (1.0, 0.8, 0.1)      # amber: selected
_COL_LINE = (1.0, 0.1, 0.1, 0.7)   # RGBA: handle arms (red)

_POINT_PX = 9.0      # on-screen radius of a control-point dot
_HANDLE_PX = 6.0     # on-screen radius of a tangent dot
_CLICK_SLOP_PX = 4.0  # mouse travel under this (in pixels) counts as a click, not a drag


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


def _is_selected(bp, kind):
    if kind == _CO:
        return bool(bp.select_control_point)
    if kind == _HL:
        return bool(bp.select_left_handle)
    return bool(bp.select_right_handle)


def _set_selected(bp, kind, value):
    if kind == _CO:
        bp.select_control_point = value
    elif kind == _HL:
        bp.select_left_handle = value
    else:
        bp.select_right_handle = value


def _deselect_all(curve_ob):
    for (si, pi) in _bezier_points(curve_ob):
        bp = curve_ob.data.splines[si].bezier_points[pi]
        bp.select_control_point = False
        bp.select_left_handle = False
        bp.select_right_handle = False


def _world_radius(context, world_co, px):
    """World-space radius that projects to roughly ``px`` pixels at ``world_co``."""
    region = context.region
    rv3d = context.region_data
    c = location_3d_to_region_2d(region, rv3d, world_co)
    if c is None:
        return 0.05
    w0 = region_2d_to_location_3d(region, rv3d, c, world_co)
    w1 = region_2d_to_location_3d(region, rv3d, c + Vector((px, 0.0)), world_co)
    return max((w1 - w0).length, 1e-5)


def _billboard_matrix(context, world_co, radius):
    """A view-facing matrix that places a unit circle at ``world_co`` scaled to ``radius``."""
    rv3d = context.region_data
    rot = rv3d.view_matrix.inverted().to_3x3()
    m = rot.to_4x4()
    m.translation = world_co
    return m @ Matrix.Scale(radius, 4)


class NUCLEAR_GT_curve_point(Gizmo):
    """One selectable/draggable dot for a bezier control point or tangent handle."""
    bl_idname = "NUCLEAR_GT_curve_point"

    # ``si``/``pi``/``kind``/``curve_ob`` are stamped on each gizmo by the group's _build().

    def _bp(self):
        return self.curve_ob.data.splines[self.si].bezier_points[self.pi]

    def _local(self, bp):
        return {_CO: bp.co, _HL: bp.handle_left, _HR: bp.handle_right}[self.kind]

    def _world_co(self):
        return self.curve_ob.matrix_world @ self._local(self._bp())

    def _radius_px(self):
        return _POINT_PX if self.kind == _CO else _HANDLE_PX

    # -- drawing & picking ---------------------------------------------------------------------

    def draw(self, context):
        bp = self._bp()
        if _is_selected(bp, self.kind):
            self.color = _COL_SELECT
            self.alpha = 1.0
        else:
            self.color = _COL_POINT if self.kind == _CO else _COL_HANDLE
            self.alpha = 0.85
        world = self._world_co()
        radius = _world_radius(context, world, self._radius_px())
        self.draw_preset_circle(_billboard_matrix(context, world, radius))

    def test_select(self, context, location):
        co2d = location_3d_to_region_2d(context.region, context.region_data, self._world_co())
        if co2d is None:
            return -1
        if (Vector(location) - co2d).length <= self._radius_px() + 3.0:
            return 0
        return -1

    # -- interaction ---------------------------------------------------------------------------

    def setup(self):
        self._moved = False
        self._shift = False
        self._init_mouse = Vector((0.0, 0.0))
        self._init_world = Vector((0.0, 0.0, 0.0))

    def invoke(self, context, event):
        self._moved = False
        self._shift = event.shift
        self._init_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self._init_world = self._world_co()
        return {'RUNNING_MODAL'}

    def modal(self, context, event, tweak):
        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        if not self._moved and (mouse - self._init_mouse).length > _CLICK_SLOP_PX:
            self._moved = True
            # A drag on an unselected dot selects it (exclusively) first, Blender-style.
            if not _is_selected(self._bp(), self.kind):
                self._select(context, additive=False)
        if self._moved:
            new_world = region_2d_to_location_3d(
                context.region, context.region_data, mouse, self._init_world)
            if new_world is not None:
                self._apply_move(new_world)
        return {'RUNNING_MODAL'}

    def exit(self, context, cancel):
        if cancel:
            return
        if self._moved:
            self._autokey()
        else:
            self._select(context, additive=self._shift)

    # -- helpers -------------------------------------------------------------------------------

    def _select(self, context, additive):
        bp = self._bp()
        if additive:
            _set_selected(bp, self.kind, not _is_selected(bp, self.kind))
        else:
            _deselect_all(self.curve_ob)
            _set_selected(bp, self.kind, True)
        self.curve_ob.data.update_tag()
        if context.area is not None:
            context.area.tag_redraw()

    def _apply_move(self, new_world):
        curve_ob = self.curve_ob
        bp = self._bp()
        new_local = curve_ob.matrix_world.inverted() @ Vector(new_world)
        if self.kind == _CO:
            delta = new_local - bp.co
            bp.co = new_local
            bp.handle_left = bp.handle_left + delta
            bp.handle_right = bp.handle_right + delta
        else:
            bp.handle_left_type = 'FREE'
            bp.handle_right_type = 'FREE'
            if self.kind == _HL:
                bp.handle_left = new_local
            else:
                bp.handle_right = new_local
        curve_ob.data.update_tag()

    def _autokey(self):
        scene = bpy.context.scene
        if scene is None or not scene.tool_settings.use_keyframe_insert_auto:
            return
        base = "splines[%d].bezier_points[%d]" % (self.si, self.pi)
        for prop in (".co", ".handle_left", ".handle_right"):
            try:
                self.curve_ob.data.keyframe_insert(data_path=base + prop)
            except RuntimeError:
                pass


class NUCLEAR_GGT_curve_deform_points(GizmoGroup):
    bl_idname = "NUCLEAR_GGT_curve_deform_points"
    bl_label = "Bezier Deform Points"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'3D', 'PERSISTENT', 'SHOW_MODAL_ALL'}

    @classmethod
    def poll(cls, context):
        return _active_deform_curve(context) is not None

    def _new_gizmo(self, si, pi, kind):
        gz = self.gizmos.new(NUCLEAR_GT_curve_point.bl_idname)
        gz.curve_ob = self._curve_ob
        gz.si = si
        gz.pi = pi
        gz.kind = kind
        gz.use_draw_modal = True
        gz.color_highlight = 1.0, 1.0, 1.0
        gz.alpha_highlight = 1.0
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

    def setup(self, context):
        self._curve_ob = None
        self._slots = []
        self._build(context)

    def refresh(self, context):
        if _active_deform_curve(context) is not getattr(self, "_curve_ob", None) or \
                len(self._slots) != self._expected_count(context):
            self._build(context)
            return
        # Keep each gizmo pointing at the live curve (object can be re-evaluated).
        for gz in self.gizmos:
            gz.curve_ob = self._curve_ob
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
    NUCLEAR_GT_curve_point,
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
