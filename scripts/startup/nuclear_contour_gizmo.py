# SPDX-FileCopyrightText: 2024 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Nuclear: control-point gizmos for the Grease Pencil "Contour" envelope/spine rig.

This is the envelope counterpart of ``nuclear_curve_gizmo.py``. The Curve deform is shaped
by selecting bezier control points; the Contour envelope is shaped by its Object-Mode
controller Empties (one anchor per cage knot, two tangent handles parented to it). Hunting
for those small Empties - and, worse, clicking one makes it the active object so the Grease
Pencil's modifier panel disappears - is exactly the friction the Curve gizmo removes. So we
mirror it here: whenever a Grease Pencil that carries a Contour modifier with controllers is
the active object (Object mode, controllers shown), this draws a dot per controller right in
the viewport - anchors orange, tangent handles blue - plus thin arms from each anchor to its
handles.

Interaction (each dot is a custom gizmo):
- Click a dot       -> SELECT only that controller (turns yellow). The selection is the
                       Empty's own object selection, so "Reset Controllers > Selected"
                       (Alt+R / modifier panel) resets exactly these - and the Grease Pencil
                       stays the active object the whole time.
- Shift+click a dot -> add/remove it from the selection (build a multi-selection).
- Drag a dot        -> move the controller (an anchor carries its two handles, which are
                       parented to it; a handle bends its tangent). With Auto Keying on, the
                       drag inserts location keyframes so the envelope can be animated.

Controllers are real Empties, so this only shows them while they are visible: toggling the
controllers off (Show/Hide Controllers) hides the dots too, and selecting a hidden Empty is
not allowed anyway.
"""

import bpy
import gpu
from bpy.types import Gizmo, GizmoGroup
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from bpy_extras.view3d_utils import region_2d_to_location_3d, location_3d_to_region_2d

# Custom-property key that both stores a controller's rest pose and marks it as a controller
# (must match ENVELOPE_REST_PROP in editors/object/object_modifier.cc).
_REST_PROP = "nuclear_envelope_rest"

# colors (RGB) - match the Empties' own draw colors set at creation (envelope_add_controls).
_COL_ANCHOR = (1.0, 0.55, 0.1)     # warm: anchor (the knot)
_COL_HANDLE = (0.25, 0.7, 1.0)     # cool: tangent handle
_COL_SELECT = (1.0, 0.9, 0.15)     # bright yellow: selected (reads against both base colors)
_COL_LINE = (0.25, 0.7, 1.0, 0.6)  # RGBA: handle arms

_ANCHOR_PX = 9.0      # on-screen radius of an anchor dot
_HANDLE_PX = 6.0      # on-screen radius of a handle dot
_CLICK_SLOP_PX = 4.0  # mouse travel under this (in pixels) counts as a click, not a drag


def _is_controller(ob):
    """True when ``ob`` is an envelope/spine controller Empty (carries the rest property)."""
    if ob is None:
        return False
    try:
        return ob.get(_REST_PROP) is not None
    except ReferenceError:
        return False


def _find_contour_cage(ob):
    """Return the cage curve of ``ob``'s first Contour modifier, or None."""
    if ob is None or ob.type != 'GREASEPENCIL':
        return None
    for md in ob.modifiers:
        if md.type == 'GREASE_PENCIL_CONTOUR' and md.object is not None and md.object.type == 'CURVE':
            return md.object
    return None


def _controllers(cage_ob):
    """Yield the controller Empties hooked onto ``cage_ob`` (anchors and tangent handles)."""
    if cage_ob is None:
        return
    for md in cage_ob.modifiers:
        if md.type == 'HOOK' and md.object is not None and _is_controller(md.object):
            yield md.object


def _active_controllers(context):
    """(cage, [visible controller Empties]) for the active GP's Contour guide, else (None, [])."""
    if context.mode != 'OBJECT':
        return None, []
    cage = _find_contour_cage(context.object)
    if cage is None:
        return None, []
    return cage, [e for e in _controllers(cage) if e.visible_get()]


def _safe_select(emp, state):
    # Selecting a hidden/excluded object raises; the controller may have just been toggled off.
    try:
        emp.select_set(state)
    except RuntimeError:
        pass


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
    from mathutils import Matrix
    rv3d = context.region_data
    m = rv3d.view_matrix.inverted().to_3x3().to_4x4()
    m.translation = world_co
    return m @ Matrix.Scale(radius, 4)


class NUCLEAR_GT_contour_point(Gizmo):
    """One selectable/draggable dot for an envelope controller Empty (anchor or handle)."""
    bl_idname = "NUCLEAR_GT_contour_point"

    # ``emp`` (the controller Object) is stamped on each gizmo by the group's _build().

    def _emp(self):
        # The Empty can be deleted (rig rebuilt) without the slot count changing; touch the
        # datablock so a removed reference returns None instead of raising into draw/test_select.
        emp = getattr(self, "emp", None)
        if emp is None:
            return None
        try:
            _ = emp.name
        except ReferenceError:
            return None
        return emp

    def _is_handle(self):
        emp = self._emp()
        return emp is not None and _is_controller(emp.parent)

    def _world_co(self):
        return self._emp().matrix_world.translation.copy()

    def _radius_px(self):
        return _HANDLE_PX if self._is_handle() else _ANCHOR_PX

    # -- drawing & picking ---------------------------------------------------------------------

    def draw(self, context):
        emp = self._emp()
        if emp is None:
            return
        if emp.select_get():
            self.color = _COL_SELECT
            self.alpha = 1.0
        else:
            self.color = _COL_HANDLE if self._is_handle() else _COL_ANCHOR
            self.alpha = 0.9
        world = self._world_co()
        radius = _world_radius(context, world, self._radius_px())
        self.draw_preset_circle(_billboard_matrix(context, world, radius))

    def test_select(self, context, location):
        if self._emp() is None:
            return -1
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
        emp = self._emp()
        if emp is None:
            return {'FINISHED'}
        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        if not self._moved and (mouse - self._init_mouse).length > _CLICK_SLOP_PX:
            self._moved = True
            # A drag on an unselected dot selects it (exclusively) first, Blender-style.
            if not emp.select_get():
                self._select(context, additive=False)
        if self._moved:
            new_world = region_2d_to_location_3d(
                context.region, context.region_data, mouse, self._init_world)
            if new_world is not None:
                self._apply_move(emp, new_world)
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
        emp = self._emp()
        if emp is None:
            return
        if additive:
            _safe_select(emp, not emp.select_get())
        else:
            # Exclusive within this guide only: leave the Grease Pencil (and unrelated objects)
            # untouched so the GP stays active and its modifier panel/gizmo persist.
            for other in _controllers(_find_contour_cage(context.object)):
                _safe_select(other, False)
            _safe_select(emp, True)
        if context.area is not None:
            context.area.tag_redraw()

    def _apply_move(self, emp, new_world):
        # Controllers are translation-only (rot/scale locked); back-solve the parent-space
        # location from the desired world point. An anchor's handles are parented to it, so they
        # ride along automatically (matches grabbing a control point in the Curve gizmo).
        if emp.parent is not None:
            parent_space = emp.parent.matrix_world @ emp.matrix_parent_inverse
            emp.location = parent_space.inverted() @ Vector(new_world)
        else:
            emp.location = Vector(new_world)

    def _autokey(self):
        scene = bpy.context.scene
        if scene is None or not scene.tool_settings.use_keyframe_insert_auto:
            return
        emp = self._emp()
        if emp is None:
            return
        try:
            emp.keyframe_insert(data_path="location")
        except RuntimeError:
            pass


class NUCLEAR_GGT_contour_controllers(GizmoGroup):
    bl_idname = "NUCLEAR_GGT_contour_controllers"
    bl_label = "Envelope Controllers"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'3D', 'PERSISTENT', 'SHOW_MODAL_ALL'}

    @classmethod
    def poll(cls, context):
        _, emps = _active_controllers(context)
        return len(emps) > 0

    def _new_gizmo(self, emp):
        gz = self.gizmos.new(NUCLEAR_GT_contour_point.bl_idname)
        gz.emp = emp
        gz.use_draw_modal = True
        gz.color_highlight = 1.0, 1.0, 1.0
        gz.alpha_highlight = 1.0
        return gz

    def _build(self, context):
        self.gizmos.clear()
        _, self._emps = _active_controllers(context)
        for emp in self._emps:
            self._new_gizmo(emp)

    def setup(self, context):
        self._emps = []
        self._build(context)

    def refresh(self, context):
        _, emps = _active_controllers(context)
        if len(emps) != len(getattr(self, "_emps", [])):
            self._build(context)
            return
        # Re-stamp the live Empties (they can be re-evaluated) and reset the gizmo transforms.
        self._emps = emps
        for gz, emp in zip(self.gizmos, emps):
            gz.emp = emp
            gz.matrix_basis.identity()


# -------------------------------------------------------------------------------------------------
# Overlay: thin arms from each anchor to its tangent handles (the Edit Mode look).
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
def _draw_contour_arms():
    context = bpy.context
    _, emps = _active_controllers(context)
    if not emps:
        return
    visible = set(emps)
    coords = []
    for emp in emps:
        parent = emp.parent
        # Only handles carry a controller parent; draw the arm anchor -> handle.
        if _is_controller(parent) and parent in visible:
            coords.append(parent.matrix_world.translation.copy())
            coords.append(emp.matrix_world.translation.copy())
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
    NUCLEAR_GT_contour_point,
    NUCLEAR_GGT_contour_controllers,
)


def register():
    global _draw_handle
    for cls in classes:
        bpy.utils.register_class(cls)
    if _draw_handle is None:
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_contour_arms, (), 'WINDOW', 'POST_VIEW')


def unregister():
    global _draw_handle
    if _draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
