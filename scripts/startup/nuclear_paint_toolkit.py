# SPDX-FileCopyrightText: 2024 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Nuclear: Grease Pencil paint toolkit — the "Paint" Properties tab.

Nuclear adds a dedicated "Paint" tab to the Properties editor (the C side registers
``BCONTEXT_PAINT`` and shows the tab only for a Grease Pencil object in Paint mode; panels
match it with ``bl_context = "paint"``). This module fills that tab with the drawing
controls an artist reaches for constantly, gathered Krita-style into one native place
instead of being scattered across sidebar popovers:

- Brush category row (Draw / Erase / Fill / Tint) that activates the matching brush tool,
  plus the stock brush-asset preview selector.
- Precise brush size: an exact numeric pixel field beside the slider + the pixels/units lock.
- Stabilizer (smooth stroke): radius + factor.
- Recently used colors: a session ring buffer captured whenever the brush color changes,
  shown as clickable swatches.

This is baked into Nuclear as a startup module (not an installable add-on) and draws in the
Properties editor (not the viewport sidebar). The engine-level items (gradient along a
stroke, textured smudge, brush-tip textures, native lasso-fill) and the symmetry/mirror and
primitive-brush-sync behaviors are tracked separately and intentionally not registered here.
"""

import bpy
from bpy.types import Operator, Panel
from bpy.props import BoolProperty
from bpy.app.handlers import persistent

# Brush "category" row -> (label, tool idname activated when clicked). Activating the tool is
# what makes the native asset shelf show that category's brushes.
_BRUSH_TABS = (
    ("Draw", "builtin.brush"),
    ("Erase", "builtin_brush.Erase"),
    ("Fill", "builtin_brush.Fill"),
    ("Tint", "builtin.brush"),
)

_MAX_RECENT_COLORS = 24

# Poll interval (seconds) for the recent-colors capture timer.
_COLOR_POLL_INTERVAL = 0.3
# Stroke count on the active drawing at the last tick, so the timer can detect a NEW stroke
# (list so the timer closure can mutate it). None = not yet initialized.
_last_stroke_count = [None]
# Active object at the last tick — when it changes (or a file loads) the stroke baseline must
# reset, else a switch to an object with fewer strokes stops recent-color capture.
_last_object = [None]
# Symmetry mirrors only AFTER a stroke finishes (its point count stops growing), never mid-stroke.
_pending_mirror = [None]      # (start, end) stroke range awaiting a stable point count, or None
_last_pointcount = [None]     # point count of the active drawing's last stroke at the last tick
# Brushes already given the Krita-style pixel-size default this session (one-time per brush,
# so the artist's later View/Scene toggle is respected).
_px_defaulted = set()


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _gp_paint_brush(context):
    """Active Grease Pencil paint brush, or None."""
    ts = getattr(context, "tool_settings", None)
    paint = getattr(ts, "gpencil_paint", None) if ts else None
    return getattr(paint, "brush", None) if paint else None


def _is_gp_paint(context):
    return context.mode == 'PAINT_GREASE_PENCIL'


def _unified(context):
    """The Paint's unified_paint_settings, or None (GP 5.0 keeps them per-Paint)."""
    ts = getattr(context, "tool_settings", None)
    paint = getattr(ts, "gpencil_paint", None) if ts else None
    return getattr(paint, "unified_paint_settings", None) if paint else None


def _effective_color(context):
    """The GP paint color. Grease Pencil paints strokes with ``brush.color`` (its vertex color)
    when the paint color mode is VERTEXCOLOR — NOT the unified color, which GP ignores."""
    brush = _gp_paint_brush(context)
    return tuple(brush.color) if brush is not None else None


def _set_effective_color(context, rgb):
    brush = _gp_paint_brush(context)
    if brush is not None:
        brush.color = rgb


def _drawn_stroke_count(context):
    """Number of strokes on the active layer's current frame, or None if unavailable."""
    ob = getattr(context, "object", None)
    if not ob or ob.type != 'GREASEPENCIL':
        return None
    try:
        layer = ob.data.layers.active
        frame = layer.current_frame() if layer else None
        return len(frame.drawing.strokes) if frame and frame.drawing else 0
    except Exception:
        return None


def _last_stroke_pointcount(context):
    """Point count of the active drawing's last stroke (to detect when a stroke stops growing)."""
    ob = getattr(context, "object", None)
    if not ob or ob.type != 'GREASEPENCIL':
        return None
    try:
        frame = ob.data.layers.active.current_frame()
        strokes = frame.drawing.strokes if frame and frame.drawing else None
        return len(strokes[-1].points) if strokes and len(strokes) else 0
    except Exception:
        return None


# -----------------------------------------------------------------------------
# Symmetry — Krita-style live mirroring. Done by copying stroke DATA (never operators or
# mode switches, which crash from paint context) across the object-local origin planes.
# -----------------------------------------------------------------------------

def _symmetry_signs(wm):
    """Sign-flip tuples for every enabled mirror axis + their combinations (no identity)."""
    axes = [i for i, on in enumerate((wm.nuclear_mirror_x, wm.nuclear_mirror_y, wm.nuclear_mirror_z)) if on]
    if not axes:
        return []
    from itertools import combinations
    combos = []
    for r in range(1, len(axes) + 1):
        for subset in combinations(axes, r):
            signs = [1.0, 1.0, 1.0]
            for ax in subset:
                signs[ax] = -1.0
            combos.append(tuple(signs))
    return combos


def _snapshot_stroke(src):
    """Copy a stroke's geometry to plain Python so it survives add_strokes() reallocation."""
    return (
        src.material_index,
        src.cyclic,
        tuple(src.fill_color),
        src.fill_opacity,
        [(tuple(p.position), p.radius, p.opacity, tuple(p.vertex_color)) for p in src.points],
    )


def _mirror_new_strokes(context, start, end, combos):
    """Mirror strokes [start:end) of the active drawing across each sign combo."""
    ob = context.object
    try:
        drawing = ob.data.layers.active.current_frame().drawing
    except Exception:
        return
    strokes = drawing.strokes
    snaps = [_snapshot_stroke(strokes[i]) for i in range(start, min(end, len(strokes)))]
    for mat, cyclic, fcol, fop, pts in snaps:
        for sx, sy, sz in combos:
            drawing.add_strokes([len(pts)])
            dst = drawing.strokes[-1]
            dst.material_index = mat
            dst.cyclic = cyclic
            dst.fill_color = fcol
            dst.fill_opacity = fop
            for i, (pos, rad, op, vc) in enumerate(pts):
                dp = dst.points[i]
                dp.position = (pos[0] * sx, pos[1] * sy, pos[2] * sz)
                dp.radius = rad
                dp.opacity = op
                dp.vertex_color = vc
    try:
        drawing.tag_positions_changed()
        ob.data.update_tag()
    except Exception:
        pass


def _gradient_new_strokes(context, start, end, c0, c1):
    """Paint a start->end color gradient along each new stroke, as per-point vertex color.
    (Needs the paint color mode = VERTEXCOLOR to be visible; that is Nuclear's default.)"""
    ob = context.object
    try:
        drawing = ob.data.layers.active.current_frame().drawing
    except Exception:
        return
    strokes = drawing.strokes
    for si in range(start, min(end, len(strokes))):
        pts = strokes[si].points
        n = len(pts)
        for i, p in enumerate(pts):
            t = i / (n - 1) if n > 1 else 0.0
            p.vertex_color = (c0[0] + (c1[0] - c0[0]) * t,
                              c0[1] + (c1[1] - c0[1]) * t,
                              c0[2] + (c1[2] - c0[2]) * t, 1.0)
    try:
        ob.data.update_tag()
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Recently used colors — kept in a Palette so they render as tinted, clickable
# swatches via the native ``template_palette`` widget (a click applies to the brush).
# -----------------------------------------------------------------------------

_RECENT_PALETTE_NAME = "Nuclear Recent"


def _recent_palette(create=True):
    pal = bpy.data.palettes.get(_RECENT_PALETTE_NAME)
    if pal is None and create:
        pal = bpy.data.palettes.new(_RECENT_PALETTE_NAME)
    return pal


def _push_recent_color(context, rgb):
    """Add a painted color to the recent palette: dedup, append, cap. Adopt it as the GP paint
    palette when none is set, so its swatches apply to the brush on click."""
    pal = _recent_palette()
    if pal is None:
        return
    paint = getattr(context.tool_settings, "gpencil_paint", None)
    if paint is not None and paint.palette is None:
        paint.palette = pal

    for c in list(pal.colors):
        if all(abs(c.color[i] - rgb[i]) < 1.0e-4 for i in range(3)):
            pal.colors.remove(c)
            break
    pal.colors.new().color = rgb
    while len(pal.colors) > _MAX_RECENT_COLORS:
        pal.colors.remove(pal.colors[0])


def _color_poll_timer():
    """Timer: record a color into the history when a stroke is actually DRAWN with it.

    Recent colors are the colors the artist painted with, not every color merely hovered in the
    picker. A stroke landing = the active drawing's stroke count grows; we then capture the
    effective (unified-aware) color. ``bpy.msgbus`` is unusable here — it never fires for
    ``Brush.color``. Cost is one stroke-count read per tick, gated on GP Paint mode.
    """
    context = bpy.context
    if _is_gp_paint(context):
        ob = getattr(context, "object", None)
        ob_key = ob.name_full if ob else None
        if ob_key != _last_object[0]:          # object switched -> restart stroke tracking
            _last_object[0] = ob_key
            _last_stroke_count[0] = None
            _pending_mirror[0] = None
            _last_pointcount[0] = None
        cnt = _drawn_stroke_count(context)
        wm = context.window_manager
        if cnt is not None:
            last = _last_stroke_count[0]
            if last is not None and cnt > last:
                # New stroke started: capture its color now (only for the Draw brush, so smudge
                # and fill strokes don't pollute recents). A stroke pending from before is
                # certainly finished, so mirror it; then queue the new one (mirrored on finish).
                _b = _gp_paint_brush(context)
                if _b is not None and _b.gpencil_brush_type == 'DRAW':
                    rgb = _effective_color(context)
                    if rgb is not None:
                        _push_recent_color(context, rgb)
                if _pending_mirror[0] is not None:
                    ps, pe = _pending_mirror[0]
                    combos = _symmetry_signs(wm) if wm is not None else []
                    if combos:
                        _mirror_new_strokes(context, ps, pe, combos)
                _pending_mirror[0] = (last, cnt) if (wm is not None and _symmetry_signs(wm)) else None
                _last_pointcount[0] = _last_stroke_pointcount(context)
                cnt = _drawn_stroke_count(context) or cnt
            elif _pending_mirror[0] is not None and last is not None and cnt == last:
                # Same count: mirror once the last stroke's point count settles (stroke finished).
                pc = _last_stroke_pointcount(context)
                if pc is not None and pc == _last_pointcount[0]:
                    start, end = _pending_mirror[0]
                    _pending_mirror[0] = None
                    combos = _symmetry_signs(wm) if wm is not None else []
                    if combos:
                        _mirror_new_strokes(context, start, end, combos)
                        cnt = _drawn_stroke_count(context) or cnt
                else:
                    _last_pointcount[0] = pc
            _last_stroke_count[0] = cnt
        # One-time Krita-style pixel-size default per brush (respects later toggling).
        brush = _gp_paint_brush(context)
        if brush is not None:
            key = brush.name_full
            if key not in _px_defaulted:
                _px_defaulted.add(key)
                try:
                    brush.use_locked_size = 'VIEW'
                except Exception:
                    pass
    return _COLOR_POLL_INTERVAL


@persistent
def _apply_paint_defaults(*_args):
    """On file load, apply Nuclear's Krita-like GP paint default: paint the picked color
    (VERTEXCOLOR mode). Reversible per-scene via the Color panel's Material/Vertex toggle."""
    _px_defaulted.clear()  # re-apply the pixel-size default to the freshly loaded file's brushes
    _last_stroke_count[0] = None  # restart recent-color tracking for the new file
    _last_object[0] = None
    _pending_mirror[0] = None
    _last_pointcount[0] = None
    # Recents start EMPTY every file/session and only fill as colors are actually painted.
    pal = _recent_palette(create=False)
    if pal is not None:
        pal.colors.clear()
    for scene in bpy.data.scenes:
        gpp = getattr(scene.tool_settings, "gpencil_paint", None)
        if gpp is not None:
            try:
                gpp.color_mode = 'VERTEXCOLOR'
            except Exception:
                pass


# -----------------------------------------------------------------------------
# Brush category row
# -----------------------------------------------------------------------------

class NUCLEAR_OT_brush_tab(Operator):
    """Switch brush category and show its brushes"""
    bl_idname = "nuclear.brush_tab"
    bl_label = "Brush Category"

    tool_id: bpy.props.StringProperty()

    def execute(self, context):
        try:
            bpy.ops.wm.tool_set_by_id(name=self.tool_id)
        except RuntimeError as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        return {'FINISHED'}


class NUCLEAR_OT_smudge_toggle(Operator):
    """Toggle the active brush between Draw and Smudge (smear/blur existing strokes)"""
    bl_idname = "nuclear.gp_smudge_toggle"
    bl_label = "Smudge"

    @classmethod
    def poll(cls, context):
        return _gp_paint_brush(context) is not None

    def execute(self, context):
        brush = _gp_paint_brush(context)
        brush.gpencil_brush_type = 'DRAW' if brush.gpencil_brush_type == 'SMUDGE' else 'SMUDGE'
        return {'FINISHED'}


class NUCLEAR_OT_add_tip_texture(Operator):
    """Create a grunge tip texture (procedural noise, spatial 3D mapping) for textured strokes"""
    bl_idname = "nuclear.gp_add_tip_texture"
    bl_label = "Add Grunge Texture"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _gp_paint_brush(context) is not None

    def execute(self, context):
        import numpy as np
        brush = _gp_paint_brush(context)
        # GP brushes ship as linked library assets (read-only), so texture assignment is silently
        # ignored. Make the brush local first, then a fresh local IMAGE texture sticks.
        if brush.library is not None:
            brush.make_local()
            brush = _gp_paint_brush(context)
        if brush is None:
            return {'CANCELLED'}
        img = bpy.data.images.get("Nuclear Grunge")
        if img is None:
            size = 256
            rng = np.random.default_rng(5)
            grey = np.clip((rng.random((size, size)).astype('float32') - 0.5) * 1.9 + 0.5, 0.0, 1.0)
            rgba = np.empty((size, size, 4), 'float32')
            rgba[..., 0] = grey
            rgba[..., 1] = grey
            rgba[..., 2] = grey
            rgba[..., 3] = 1.0
            img = bpy.data.images.new("Nuclear Grunge", size, size)
            img.pixels.foreach_set(rgba.ravel())
            img.pack()
        tex = bpy.data.textures.new("Nuclear Grunge Tex", type='IMAGE')
        tex.image = img
        brush.texture = tex
        # Spatial 3D mapping is what the paint-op sampler (world position) expects; a fine scale
        # gives a visible grain along the stroke.
        slot = brush.texture_slot
        slot.map_mode = '3D'
        slot.scale = (12.0, 12.0, 12.0)
        self.report({'INFO'}, "Grunge tip texture added (brush made local)")
        return {'FINISHED'}


def _lasso_draw_px(op, context):
    """Draw the in-progress lasso outline in the viewport (pixel space)."""
    if not getattr(op, "_points", None) or len(op._points) < 2:
        return
    import gpu
    from gpu_extras.batch import batch_for_shader
    coords = [(float(x), float(y)) for (x, y) in op._points]
    coords.append(coords[0])  # close the loop visually
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": coords})
    gpu.state.line_width_set(1.5)
    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float("color", (0.9, 0.9, 0.2, 0.9))
    batch.draw(shader)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


def _ensure_fill_material(ob, rgb):
    """Index of a fill-enabled GP material on ``ob`` (reuse one, else create 'Lasso Fill')."""
    for i, ms in enumerate(ob.material_slots):
        m = ms.material
        if m is not None and m.grease_pencil is not None and m.grease_pencil.show_fill:
            return i
    mat = bpy.data.materials.new("Lasso Fill")
    bpy.data.materials.create_gpencil_data(mat)
    gp = mat.grease_pencil
    gp.show_fill = True
    gp.show_stroke = False
    gp.fill_color = (1.0, 1.0, 1.0, 1.0)  # white base; the per-stroke fill_color tints it
    ob.data.materials.append(mat)
    return len(ob.material_slots) - 1


class NUCLEAR_OT_lasso_fill(Operator):
    """Draw a lasso to enclose a region and fill it with a closed stroke"""
    bl_idname = "nuclear.gp_lasso_fill"
    bl_label = "Lasso Fill"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.type == 'GREASEPENCIL' and _is_gp_paint(context)

    def invoke(self, context, event):
        # Invoked from a Properties-panel button, so locate the 3D viewport explicitly.
        area = next((a for a in context.screen.areas if a.type == 'VIEW_3D'), None)
        region = next((r for r in area.regions if r.type == 'WINDOW'), None) if area else None
        if area is None or region is None:
            self.report({'WARNING'}, "Lasso Fill needs a 3D viewport open")
            return {'CANCELLED'}
        self._area = area
        self._region = region
        self._rv3d = area.spaces.active.region_3d
        self._points = []
        self._drawing = False
        # When launched by the toolbar tool's LMB press, begin the lasso immediately.
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self._drawing = True
            self._points = [(event.mouse_x - region.x, event.mouse_y - region.y)]
        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            _lasso_draw_px, (self, context), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set(
            "Lasso Fill: drag to enclose a region, release to fill  |  RMB/Esc: cancel")
        return {'RUNNING_MODAL'}

    def _end(self, context):
        try:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
        except Exception:
            pass
        context.workspace.status_text_set(None)
        if self._region:
            self._region.tag_redraw()

    def modal(self, context, event):
        # Mouse events are window-absolute; convert to the viewport region we grabbed at invoke.
        mx = event.mouse_x - self._region.x
        my = event.mouse_y - self._region.y
        if event.type == 'MOUSEMOVE':
            if self._drawing:
                self._points.append((mx, my))
                self._region.tag_redraw()
        elif event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                self._drawing = True
                self._points = [(mx, my)]
            elif event.value == 'RELEASE' and self._drawing:
                self._create_fill(context)
                self._end(context)
                return {'FINISHED'}
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            self._end(context)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def _create_fill(self, context):
        from bpy_extras.view3d_utils import region_2d_to_location_3d
        if len(self._points) < 3:
            return
        ob = context.object
        region = self._region
        rv3d = self._rv3d
        origin = ob.matrix_world.translation
        mat_inv = ob.matrix_world.inverted()
        pts = []
        for (x, y) in self._points:
            loc = region_2d_to_location_3d(region, rv3d, (float(x), float(y)), origin)
            if loc is not None:
                lp = mat_inv @ loc
                pts.append((lp.x, lp.y, lp.z))
        if len(pts) < 3:
            return
        try:
            layer = ob.data.layers.active
            frame = layer.current_frame() if layer else None
            drawing = frame.drawing if frame else None
        except Exception:
            drawing = None
        if drawing is None:
            return
        drawing.add_strokes([len(pts)])
        s = drawing.strokes[-1]
        s.cyclic = True
        brush = _gp_paint_brush(context)
        rgb = tuple(brush.color) if brush is not None else (0.5, 0.5, 0.5)
        s.material_index = _ensure_fill_material(ob, rgb)
        # Per-stroke fill color = the currently selected brush color (tints the white material fill).
        s.fill_color = (rgb[0], rgb[1], rgb[2], 1.0)
        s.fill_opacity = 1.0
        for i, (px, py, pz) in enumerate(pts):
            p = s.points[i]
            p.position = (px, py, pz)
            p.radius = 0.01
            p.opacity = 1.0
        # Mirror the fill immediately if symmetry is on (so the mirror keeps the fill color), and
        # stop the color-capture timer from treating this fill as a painted stroke.
        wm = context.window_manager
        combos = _symmetry_signs(wm) if wm is not None else []
        if combos:
            idx = len(drawing.strokes) - 1
            _mirror_new_strokes(context, idx, idx + 1, combos)
        _last_stroke_count[0] = _drawn_stroke_count(context)
        _pending_mirror[0] = None
        try:
            drawing.tag_positions_changed()
            ob.data.update_tag()
        except Exception:
            pass


# -----------------------------------------------------------------------------
# UI — the "Paint" Properties tab (bl_context = "paint")
# -----------------------------------------------------------------------------

class _NuclearPaintPanel:
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "paint"

    @classmethod
    def poll(cls, context):
        return _is_gp_paint(context)


class NUCLEAR_PT_paint_brushes(_NuclearPaintPanel, Panel):
    bl_label = "Brushes"
    bl_idname = "NUCLEAR_PT_paint_brushes"

    def draw(self, context):
        layout = self.layout
        brush = _gp_paint_brush(context)

        # Category row (Krita-style): each button activates that brush tool.
        row = layout.row(align=True)
        for label, tool_id in _BRUSH_TABS:
            row.operator("nuclear.brush_tab", text=label).tool_id = tool_id

        if brush is None:
            return

        from bl_ui.properties_paint_common import BrushAssetShelf
        # Brush selector only — no large preview thumbnail.
        BrushAssetShelf.draw_popup_selector(layout.row(), context, brush)

        # Smudge: toggles the active brush's type (smears strokes; click again to draw).
        layout.operator("nuclear.gp_smudge_toggle", text="Smudge Mode", icon='BRUSH_DATA',
                        depress=(brush.gpencil_brush_type == 'SMUDGE'))

        # Tip texture: Nuclear samples brush.texture per stroke sample and modulates opacity,
        # giving textured/grungy strokes. Assign an image or procedural texture here.
        box = layout.box()
        box.label(text="Tip Texture (textured strokes):")
        box.operator("nuclear.gp_add_tip_texture", icon='TEXTURE')
        box.template_ID(brush, "texture", new="texture.new")
        if brush.texture is not None:
            slot = brush.texture_slot
            box.prop(slot, "map_mode", text="Mapping")
            box.prop(slot, "scale", text="Scale")


class NUCLEAR_PT_paint_size(_NuclearPaintPanel, Panel):
    bl_label = "Size"
    bl_idname = "NUCLEAR_PT_paint_size"
    bl_order = 2

    def draw(self, context):
        layout = self.layout
        brush = _gp_paint_brush(context)
        if brush is None:
            return
        # Grease Pencil reads the brush directly (it ignores unified size) — same values as the
        # top tool-header, so editing here moves that too. View = pixels (Krita-style), Scene =
        # world units.
        px = brush.use_locked_size != 'SCENE'
        size_prop = "size" if px else "unprojected_size"
        layout.row().prop(brush, "use_locked_size", expand=True)
        col = layout.column(align=True)
        row = col.row(align=True)
        row.prop(brush, size_prop, slider=True, text=("Size (px)" if px else "Size (units)"))
        row.prop(brush, "use_pressure_size", text="")
        col.prop(brush, size_prop, text="Exact")  # precise numeric entry


class NUCLEAR_PT_paint_stabilizer(_NuclearPaintPanel, Panel):
    bl_label = "Stabilizer"
    bl_idname = "NUCLEAR_PT_paint_stabilizer"
    bl_order = 3

    def draw_header(self, context):
        brush = _gp_paint_brush(context)
        if brush is not None:
            self.layout.prop(brush, "use_smooth_stroke", text="")

    def draw(self, context):
        layout = self.layout
        brush = _gp_paint_brush(context)
        if brush is None:
            return
        col = layout.column(align=True)
        col.active = brush.use_smooth_stroke
        col.prop(brush, "smooth_stroke_radius", text="Radius", slider=True)
        col.prop(brush, "smooth_stroke_factor", text="Factor", slider=True)


class NUCLEAR_PT_paint_colors(_NuclearPaintPanel, Panel):
    bl_label = "Color"
    bl_idname = "NUCLEAR_PT_paint_colors"
    bl_order = 1  # sit right below Brushes, Krita-style always-visible picker

    def draw(self, context):
        layout = self.layout
        brush = _gp_paint_brush(context)
        if brush is not None:
            from bl_ui.properties_paint_common import brush_basic__draw_color_selector
            # Native GP color source: Material vs Vertex-Color toggle + the material/color swatch.
            # The stroke is painted in brush.color only in VERTEXCOLOR mode; in MATERIAL mode it
            # takes the material's color (so the wheel below appears to "do nothing" — that is why).
            brush_basic__draw_color_selector(context, layout, brush, brush.gpencil_settings)
            # Always-visible advanced selector (hue/sat wheel + value bar), bound to brush.color.
            # Blender has no triangle-in-ring variant.
            layout.template_color_picker(brush, "color", value_slider=True)
            layout.prop(brush, "color", text="")

        layout.separator()
        layout.label(text="Recent (painted):")
        # Tinted, clickable swatches via the native palette widget — a click applies to the brush.
        paint = context.tool_settings.gpencil_paint
        if paint is not None and paint.palette is not None and len(paint.palette.colors):
            layout.template_palette(paint, "palette", color=True)
        else:
            layout.label(text="No recent colors yet", icon='INFO')


class NUCLEAR_PT_paint_symmetry(_NuclearPaintPanel, Panel):
    bl_label = "Symmetry"
    bl_idname = "NUCLEAR_PT_paint_symmetry"
    bl_order = 4
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager
        layout.label(text="Live mirror while drawing:")
        row = layout.row(align=True)
        row.prop(wm, "nuclear_mirror_x", text="Horizontal", toggle=True)
        row.prop(wm, "nuclear_mirror_z", text="Vertical", toggle=True)
        layout.label(text="Mirrors across the object origin (front-view plane).", icon='INFO')


# -----------------------------------------------------------------------------
# Toolbar tool + tool-header toggle
# -----------------------------------------------------------------------------

class NuclearLassoFillTool(bpy.types.WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'PAINT_GREASE_PENCIL'
    bl_idname = "nuclear.lasso_fill_tool"
    bl_label = "Lasso Fill"
    bl_description = "Draw a lasso to enclose a region and fill it with a closed stroke"
    bl_icon = "ops.generic.select_lasso"
    bl_widget = None
    bl_keymap = (
        ("nuclear.gp_lasso_fill", {"type": 'LEFTMOUSE', "value": 'PRESS'}, None),
    )


def _draw_symmetry_toolheader(self, context):
    """Mirror toggles in the viewport tool header, so symmetry is reachable while drawing."""
    if context.mode != 'PAINT_GREASE_PENCIL':
        return
    wm = context.window_manager
    row = self.layout.row(align=True)
    row.label(text="", icon='MOD_MIRROR')
    row.prop(wm, "nuclear_mirror_x", text="H", toggle=True)
    row.prop(wm, "nuclear_mirror_z", text="V", toggle=True)


# -----------------------------------------------------------------------------
# Registration
# -----------------------------------------------------------------------------

classes = (
    NUCLEAR_OT_brush_tab,
    NUCLEAR_OT_smudge_toggle,
    NUCLEAR_OT_add_tip_texture,
    NUCLEAR_OT_lasso_fill,
    NUCLEAR_PT_paint_brushes,
    NUCLEAR_PT_paint_size,
    NUCLEAR_PT_paint_stabilizer,
    NUCLEAR_PT_paint_colors,
    NUCLEAR_PT_paint_symmetry,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.nuclear_mirror_x = BoolProperty(name="Mirror X", default=False)
    bpy.types.WindowManager.nuclear_mirror_y = BoolProperty(name="Mirror Y", default=False)
    bpy.types.WindowManager.nuclear_mirror_z = BoolProperty(name="Mirror Z", default=False)
    if not bpy.app.timers.is_registered(_color_poll_timer):
        bpy.app.timers.register(_color_poll_timer, persistent=True)
    if _apply_paint_defaults not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_apply_paint_defaults)
    try:
        bpy.utils.register_tool(NuclearLassoFillTool, after={"builtin.brush"},
                                separator=True, group=False)
    except Exception:
        pass
    try:
        bpy.types.VIEW3D_HT_tool_header.append(_draw_symmetry_toolheader)
    except Exception:
        pass
    try:
        _apply_paint_defaults()  # apply to the already-open file
    except AttributeError:
        # bpy.data is restricted during startup registration; the load_post handler applies it
        # once the startup file has loaded.
        pass


def unregister():
    try:
        bpy.types.VIEW3D_HT_tool_header.remove(_draw_symmetry_toolheader)
    except Exception:
        pass
    try:
        bpy.utils.unregister_tool(NuclearLassoFillTool)
    except Exception:
        pass
    if _apply_paint_defaults in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_apply_paint_defaults)
    if bpy.app.timers.is_registered(_color_poll_timer):
        bpy.app.timers.unregister(_color_poll_timer)
    _last_stroke_count[0] = None
    _px_defaulted.clear()
    for attr in ("nuclear_mirror_x", "nuclear_mirror_y", "nuclear_mirror_z"):
        if hasattr(bpy.types.WindowManager, attr):
            delattr(bpy.types.WindowManager, attr)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
