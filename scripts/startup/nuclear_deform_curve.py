# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Nuclear — the deform-curve workflow in one panel (fit · bind · drive the rig).

A bendy limb in a cut-out rig is three things that must agree with each other:

* a **curve** laid over the drawing, spanning it end to end;
* the **binding** of the drawing to that curve (the ``Curve`` modifier is a silent
  no-op until it is bound — no error, no warning, the drawing simply never bends);
* a **peg driven by the curve's tip**, so everything hanging off the piece (the
  forearm on an arm, the head and arms on a torso) travels with the deformation
  instead of staying behind.

Doing that by hand is where the studio kept losing hours: a curve fitted to 87% of
the drawing leaves slack at both ends (the head visibly leaves the collar), a curve
that sits off the drawing binds every point to the same ``u`` and the piece turns
into a rigid blob, binding parents the curve to the drawing which double-transforms a
curve that already follows a peg, and moving the control points of a *driving* curve
without refreshing its rest pose drops the limb off the body.

Every operator here is idempotent, refuses to run with Auto Keying on (it would
silently key — and un-do — the edit on the next frame change), and reports what it
measured. "Check Deform Curves" is the read-only version: it names every problem
above without touching the file.

A binding covers the points that existed when it was made, and nothing else. Editing a
bound drawing is safe (the deformer measures the offset against the live points), but a
cell drawn *after* the bind has no binding at all and stays rigid while its neighbours
bend, and a stroke added to a bound cell does not bend either. Both are counted by
``_stale_bind`` and called out in the panel, because neither shows up as an error —
the piece just quietly stops agreeing with itself.
"""

import contextlib

import bpy
import mathutils
from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import Operator, Panel

_MOD_TYPE = "GREASE_PENCIL_CURVE"
_U_ATTR = ".gp_curve_u"
# Written by the bind on the points it covered. Points drawn afterwards default to False and the
# deformer skips them, so they stay where they were drawn instead of piling onto the curve's start.
_BOUND_ATTR = ".gp_curve_bound"
# nuclear_cell_library parks its drawing library in a frame bank up here; those frames are
# alternative drawings (mouths, hands), never part of the piece's own extent.
_BANK_START = 100000
# Auto Rig's two-peg pattern: a skeleton piece binds to its own drawing peg under the joint.
_DRAW_PEG_SUFFIX = " (ctrl)"
_PEG_SUFFIX = "_curva"
# Stamped on the curve OBJECT by the C bind/setup: the rest control points, 9 floats per Bezier
# point (handle_left, co, handle_right), in curve-local space.
_REST_PROP = "nuclear_curve_rest"


# --------------------------------------------------------------------------- #
# Drawing / curve geometry
# --------------------------------------------------------------------------- #
def _drawings(ob):
    """Every drawing that makes up the piece as it reads now: the current frame of each
    visible layer, skipping the cell-library bank and empty layers."""
    out = []
    for layer in ob.data.layers:
        if layer.hide:
            continue
        frame = layer.current_frame()
        if frame is None or frame.frame_number >= _BANK_START:
            continue
        out.append(frame.drawing)
    return out


def _drawing_bounds(ob):
    """World-space (min, max) of the piece's stroke points, or None when it has none.

    Measured from the points, not from ``bound_box``/``dimensions``: a Grease Pencil bounding
    box is often degenerate, and ``dimensions`` can report the shape *after* the curve modifier
    already deformed it — which is exactly the number you must not calibrate the curve with."""
    lo = mathutils.Vector((float("inf"),) * 3)
    hi = mathutils.Vector((float("-inf"),) * 3)
    mw = ob.matrix_world
    found = False
    for drawing in _drawings(ob):
        attr = drawing.attributes.get("position")
        if attr is None:
            continue
        for element in attr.data:
            w = mw @ element.vector
            found = True
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    return (lo, hi) if found else None


def _curve_modifier(ob, name=None):
    for md in ob.modifiers:
        if md.type == _MOD_TYPE and (name is None or md.name == name):
            return md
    return None


def _spline(curve_ob):
    for spline in curve_ob.data.splines:
        if spline.type == "BEZIER" and len(spline.bezier_points) >= 2:
            return spline
    return None


def _tips(curve_ob):
    """(tip, opposite) control-point indices. The tip is the END OF THE CHAIN — the top for an
    upright limb — because that is the end whose displacement the children must inherit.

    The opposite end is only a fallback shape reference now: the tilt driver reads the tip's own
    HANDLE (see ``_write_drivers``), because the chord between the two ends underreports the
    lean the modifier actually applies."""
    bp = _spline(curve_ob).bezier_points
    first, last = bp[0].co, bp[-1].co
    # Z decides (an upright limb); a flat one (a tail) falls back to X.
    top = 0 if (first.z, first.x) >= (last.z, last.x) else len(bp) - 1
    return top, (len(bp) - 1 if top == 0 else 0)


def _control_points_world(curve_ob):
    mw = curve_ob.matrix_world
    return [(mw @ bp.co, mw @ bp.handle_left, mw @ bp.handle_right)
            for bp in _spline(curve_ob).bezier_points]


def _set_control_points_world(curve_ob, triples):
    inv = curve_ob.matrix_world.inverted()
    bezier = _spline(curve_ob).bezier_points
    for bp, (co, hl, hr) in zip(bezier, triples):
        bp.co = inv @ co
        bp.handle_left = inv @ hl
        bp.handle_right = inv @ hr
    curve_ob.data.update_tag()


def _box_corners(lo, hi):
    return [mathutils.Vector((x, y, z))
            for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]


def _ensure_point_count(curve_ob, count):
    spline = _spline(curve_ob)
    missing = count - len(spline.bezier_points)
    if missing > 0:
        spline.bezier_points.add(missing)
    return _spline(curve_ob)


def _dominant_axis(lo, hi):
    """Unit vector along the axis the piece is longest in, within the character plane (the
    thinnest axis is the drawing's depth and never carries a limb)."""
    ext = [hi[i] - lo[i] for i in range(3)]
    thin = ext.index(min(ext))
    planar = [i for i in range(3) if i != thin]
    main = max(planar, key=lambda i: ext[i])
    v = mathutils.Vector((0.0, 0.0, 0.0))
    v[main] = 1.0
    return v


def _straight_points(lo, hi, count, coverage):
    """A straight run of control points down the middle of the drawing, tip first."""
    axis = _dominant_axis(lo, hi)
    center = (lo + hi) * 0.5
    span = abs((hi - lo).dot(axis)) * coverage
    half = axis * (span * 0.5)
    # Tip first: the end with the greater Z (or X for a flat piece) leads, so children hang off it.
    a, b = center + half, center - half
    if (a.z, a.x) < (b.z, b.x):
        a, b = b, a
    out = []
    step = (b - a) / (count - 1)
    for i in range(count):
        co = a + step * i
        out.append((co, co - step / 3.0, co + step / 3.0))
    return out


def _refit_points(curve_ob, lo, hi, coverage):
    """The curve's own shape, scaled and re-centred over the drawing.

    Keeps whatever the artist shaped (a tail's diagonal, a leg's slight bow) and only corrects
    what is measurable: the length along the curve's own direction, and where it sits."""
    triples = _control_points_world(curve_ob)
    cos = [t[0] for t in triples]
    axis = (cos[-1] - cos[0])
    if axis.length < 1e-6:
        return _straight_points(lo, hi, len(triples), coverage)
    axis.normalize()

    ts = [c.dot(axis) for c in cos]
    span_curve = max(ts) - min(ts)
    # Project the whole box onto the axis: on a diagonal curve lo/hi alone under-measure it.
    proj = [c.dot(axis) for c in _box_corners(lo, hi)]
    span_draw = (max(proj) - min(proj)) * coverage
    if span_curve < 1e-6:
        return _straight_points(lo, hi, len(triples), coverage)

    scale = span_draw / span_curve
    src = sum(cos, mathutils.Vector()) / len(cos)
    dst = (lo + hi) * 0.5
    return [(dst + (co - src) * scale,
             dst + (hl - src) * scale,
             dst + (hr - src) * scale) for co, hl, hr in triples]


# --------------------------------------------------------------------------- #
# Peg helpers (a local copy so the module also works as a stand-alone add-on)
# --------------------------------------------------------------------------- #
def _peg_local_matrix(peg):
    from mathutils import Euler, Matrix, Vector
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


def _set_pivot_world(rig, peg_index, world_pt):
    peg = rig.pegs[peg_index]
    parent = peg.parent_index
    pw = (_peg_world_matrix(rig, parent) if 0 <= parent < len(rig.pegs)
          else mathutils.Matrix.Identity(4))
    peg.pivot = pw.inverted() @ world_pt


def _followpeg(ob):
    for con in ob.constraints:
        if con.type == "FOLLOW_PEG":
            return con
    return None


def _peg_of(ob):
    """(rig, peg index) the object follows, or (None, -1)."""
    con = _followpeg(ob)
    if con is None or con.rig is None:
        return None, -1
    return con.rig, (con.rig.pegs.find(con.peg_name) if con.peg_name else -1)


def _carried_pegs(rig, draw_peg, curve_peg=-1):
    """Peg names that would travel with the deformation if the curve drove a peg: what hangs off
    the piece's own JOINT beside the piece itself (the forearm under an arm, the foot under a
    shin). Empty means nothing depends on this piece bending.

    Only the two-peg pattern qualifies — a piece bound straight to a leaf peg (a tail, a wing, a
    mouth) has no joint of its own, so its peg siblings are neighbours, not dependents."""
    if rig is None or draw_peg < 0 or not rig.pegs[draw_peg].name.endswith(_DRAW_PEG_SUFFIX):
        return []
    base = rig.pegs[draw_peg].parent_index
    if base < 0:
        return []
    return [p.name for i, p in enumerate(rig.pegs)
            if p.parent_index == base and i not in (draw_peg, curve_peg)]


def _driven_peg(rig, curve_data):
    """Index of the peg whose drivers read ``curve_data``, or -1."""
    if rig is None or rig.animation_data is None:
        return -1
    for fcurve in rig.animation_data.drivers:
        for var in fcurve.driver.variables:
            if var.targets and var.targets[0].id is curve_data:
                path = fcurve.data_path
                if path.startswith("pegs[") and "]" in path:
                    return int(path[5:path.index("]")])
    return -1


def _users_of_curve(curve_ob):
    """The Grease Pencil pieces deformed by this curve, with their modifier."""
    out = []
    for ob in bpy.data.objects:
        if ob.type != "GREASEPENCIL":
            continue
        for md in ob.modifiers:
            if md.type == _MOD_TYPE and md.object is curve_ob:
                out.append((ob, md))
    return out


def _rebuild_graph(rig):
    """Redraw the Peg Graph: it is a separate datablock, so a peg added here is invisible in the
    editor until the tree is rebuilt (and it evaporates on save without a fake user)."""
    try:
        import nuclear_peg_graph as npg
        npg.compute_grouped_layout(rig)
        for tree in bpy.data.node_groups:
            if tree.bl_idname == "NuclearPegTree" and tree.rig is rig:
                npg.rebuild(tree)
                tree.use_fake_user = True
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Bind
# --------------------------------------------------------------------------- #
@contextlib.contextmanager
def _autokey_off(context):
    """Auto Keying is on by default in this pipeline's files (every peg carries a one-key action
    = the assembly pose). Editing anything through Python with it on writes a keyframe, and the
    next frame change replays that key over the edit — the fix that 'did not stick'."""
    ts = context.scene.tool_settings
    was = ts.use_keyframe_insert_auto
    ts.use_keyframe_insert_auto = False
    try:
        yield
    finally:
        ts.use_keyframe_insert_auto = was


@contextlib.contextmanager
def _as_active(context, ob):
    """Modifier operators read the active object; restore the artist's selection afterwards."""
    view_layer = context.view_layer
    prev_active = view_layer.objects.active
    prev_sel = [o for o in context.selected_objects]
    for o in prev_sel:
        o.select_set(False)
    view_layer.objects.active = ob
    ob.select_set(True)
    try:
        yield
    finally:
        ob.select_set(False)
        for o in prev_sel:
            if o.name in view_layer.objects:
                o.select_set(True)
        if prev_active is not None and prev_active.name in view_layer.objects:
            view_layer.objects.active = prev_active


def _bind_quality(ob):
    """(u_min, u_max) over every bound point, or None when the piece is not bound.

    Points drawn after the bind are excluded: they carry a default ``u`` of 0 that would drag
    ``u_min`` to zero and make a perfectly fitted curve read as "runs past the drawing"."""
    us = []
    for layer in ob.data.layers:
        for frame in layer.frames:
            attrs = frame.drawing.attributes
            attr = attrs.get(_U_ATTR)
            if attr is None:
                continue
            flag = attrs.get(_BOUND_ATTR)
            if flag is not None and len(flag.data) == len(attr.data):
                us += [v.value for v, f in zip(attr.data, flag.data) if f.value]
            else:
                us += [v.value for v in attr.data]
    return (min(us), max(us)) if us else None


def _has_binding(ob):
    """Whether any drawing of ``ob`` carries a binding. Cheap enough for a panel redraw — it
    stops at the first one and never touches individual points."""
    for layer in ob.data.layers:
        for frame in layer.frames:
            if frame.drawing.attributes.get(_U_ATTR) is not None:
                return True
    return False


def _count_true(attr, count):
    """How many entries of a boolean attribute are True, read in bulk.

    The panel calls this on every redraw, so it goes through ``foreach_get`` (a C-level copy)
    instead of walking thousands of RNA elements in Python."""
    try:
        import numpy as np
        buf = np.zeros(count, dtype=bool)
        attr.data.foreach_get("value", buf)
        return int(buf.sum())
    except Exception:
        return sum(1 for v in attr.data if v.value)


def _stale_bind(ob):
    """What the binding of ``ob`` no longer covers, as (cells_unbound, cells_total, loose_points).

    A binding is per drawing and per point. Three things make it fall behind without anyone
    touching the curve: a cell drawn after the bind has no binding at all (it stays rigid while
    its neighbours bend), a stroke added to a bound cell has no binding of its own, and a
    drawing whose point count no longer matches turns the whole cell unbound."""
    cells_unbound = cells_total = loose = 0
    for layer in ob.data.layers:
        for frame in layer.frames:
            if frame.frame_number >= _BANK_START:
                continue
            attrs = frame.drawing.attributes
            points = attrs.get("position")
            if points is None or len(points.data) == 0:
                continue
            n = len(points.data)
            cells_total += 1
            u = attrs.get(_U_ATTR)
            if u is None or len(u.data) != n:
                cells_unbound += 1
                continue
            flag = attrs.get(_BOUND_ATTR)
            if flag is not None and len(flag.data) == n:
                loose += n - _count_true(flag, n)
    return cells_unbound, cells_total, loose


def _is_animated(curve_ob):
    for holder in (curve_ob, curve_ob.data):
        ad = getattr(holder, "animation_data", None)
        if ad is not None and (ad.action is not None or ad.drivers):
            return True
    return False


@contextlib.contextmanager
def _at_rest(curve_ob):
    """Put an ANIMATED curve back on its stamped rest shape for the duration of the block.

    Binding takes the curve's current shape as the new rest. For a curve the artist shaped by
    hand that is exactly right, but an animated curve is *posed* at whatever frame happens to be
    current — binding there would nail the pose down as the rest and leave the limb permanently
    bent. Measured on the EP06 dinosaur at frame 1: the tail curve sits 0.563 away from its rest,
    the shin 0.077, the third 0.214.

    The action is detached (the evaluated curve is what the bind samples, and the animation would
    write straight over the restored points), the rest is restored, and both are put back
    afterwards. Yields True when it had to do this."""
    rest = curve_ob.get(_REST_PROP)
    spline = _spline(curve_ob)
    if not _is_animated(curve_ob) or rest is None or spline is None \
            or len(rest) < len(spline.bezier_points) * 9:
        yield False
        return

    posed = [(bp.co.copy(), bp.handle_left.copy(), bp.handle_right.copy())
             for bp in spline.bezier_points]
    ad = curve_ob.data.animation_data
    action = ad.action if ad else None
    slot = getattr(ad, "action_slot", None) if ad else None
    if ad is not None:
        ad.action = None
    for i, bp in enumerate(spline.bezier_points):
        bp.handle_left = rest[i * 9 + 0], rest[i * 9 + 1], rest[i * 9 + 2]
        bp.co = rest[i * 9 + 3], rest[i * 9 + 4], rest[i * 9 + 5]
        bp.handle_right = rest[i * 9 + 6], rest[i * 9 + 7], rest[i * 9 + 8]
    curve_ob.data.update_tag()
    bpy.context.view_layer.update()
    try:
        yield True
    finally:
        for bp, (co, hl, hr) in zip(spline.bezier_points, posed):
            bp.co, bp.handle_left, bp.handle_right = co, hl, hr
        if ad is not None:
            ad.action = action
            if slot is not None:
                try:
                    ad.action_slot = slot
                except Exception:
                    pass
        curve_ob.data.update_tag()
        bpy.context.view_layer.update()


def _bind(context, ob, md, unbind=False):
    """Bind (or unbind) the piece, keeping the curve's own rig wiring intact.

    The C operator parents the curve to the drawing so it tracks the piece. That is right for a
    curve that has no rig wiring of its own, but a curve that already follows a peg would then be
    transformed twice (invisible at rest, wrong the moment the peg moves), so the parent is
    dropped again — its ``parentinv`` already preserves the world matrix."""
    curve_ob = md.object
    had_constraint = curve_ob is not None and _followpeg(curve_ob) is not None
    if curve_ob is None or unbind:
        with _as_active(context, ob):
            bpy.ops.object.greasepencil_curve_bind(modifier=md.name, unbind=unbind)
    else:
        with _at_rest(curve_ob) as restored:
            if restored:
                print("[Deform Curve] %s: curva animada -> bindando contra o repouso carimbado"
                      % ob.name)
            with _as_active(context, ob):
                bpy.ops.object.greasepencil_curve_bind(modifier=md.name, unbind=False)
    if curve_ob is not None and had_constraint and curve_ob.parent is not None:
        curve_ob.parent = None
        curve_ob.matrix_parent_inverse = mathutils.Matrix.Identity(4)
    context.view_layer.update()
    return _bind_quality(ob)


# --------------------------------------------------------------------------- #
# Drivers: the curve tip drives a peg, so the children follow the deformation
# --------------------------------------------------------------------------- #
def _add_var(driver, name, curve_data, point, axis, prop="co"):
    var = driver.variables.new()
    var.name = name
    var.type = "SINGLE_PROP"
    target = var.targets[0]
    target.id_type = "CURVE"
    target.id = curve_data
    target.data_path = "splines[0].bezier_points[%d].%s[%d]" % (point, prop, axis)
    return var


def _clear_drivers(rig, peg_index):
    if rig.animation_data is None:
        return
    prefix = "pegs[%d]." % peg_index
    for fcurve in list(rig.animation_data.drivers):
        if fcurve.data_path.startswith(prefix):
            rig.animation_data.drivers.remove(fcurve)


def _write_drivers(rig, peg_index, curve_ob, use_rotation=True):
    """(Re)wire the peg to the curve's tip and stamp the CURRENT shape as the rest pose.

    Rest is the whole point: the drivers report *displacement from rest*, so re-fitting a curve
    without rewriting them leaves the peg pushing the limb off the body by however much the
    control points moved."""
    curve_data = curve_ob.data
    top, _far = _tips(curve_ob)
    bezier = _spline(curve_ob).bezier_points
    p_top = bezier[top].co.copy()

    _clear_drivers(rig, peg_index)
    peg = rig.pegs[peg_index]
    peg.translation = (0.0, 0.0, 0.0)
    peg.rotation = (0.0, 0.0, 0.0)
    _set_pivot_world(rig, peg_index, curve_ob.matrix_world @ p_top)

    for axis, comp in ((0, "x"), (2, "z")):
        driver = rig.driver_add("pegs[%d].translation" % peg_index, axis).driver
        driver.type = "SCRIPTED"
        _add_var(driver, "p", curve_data, top, axis)
        driver.expression = "p - (%r)" % getattr(p_top, comp)

    if use_rotation:
        # The tilt to copy is the curve's TANGENT at the tip, read off that point's own handle.
        # That tangent is what the modifier uses to orient the drawing at u = 0, so it is what
        # the peg must reproduce for the head and arms to stay welded to the collar.
        #
        # Until 2026-07-31 this measured the chord to the OPPOSITE end, and underreported the
        # turn: on the EP05 servants, moving the tip 0.6 sideways leans the drawing 32.3° while
        # the chord reads 17.6° — 15° that the head and arms never got. Worse when only the
        # MIDDLE point is bent: neither end moves, the chord sees no rotation at all and the peg
        # sits still while the drawing leans those same 32°.
        # (The fear that motivated the chord — "between neighbours the angle explodes" — does
        # not apply to the handle: it IS the slope of the curve there, not a secant between two
        # control points.)
        #
        # Rotating a peg about Y takes +Z to +X, the same sign as atan2 in the character plane.
        side = "handle_left" if top == 0 else "handle_right"    # the handle pointing outwards
        h_top = getattr(bezier[top], side).copy()
        driver = rig.driver_add("pegs[%d].rotation" % peg_index, 1).driver
        driver.type = "SCRIPTED"
        _add_var(driver, "x0", curve_data, top, 0, side)
        _add_var(driver, "z0", curve_data, top, 2, side)
        _add_var(driver, "x1", curve_data, top, 0)
        _add_var(driver, "z1", curve_data, top, 2)
        driver.expression = "atan2(x0 - x1, z0 - z1) - atan2(%r, %r)" % (
            h_top.x - p_top.x, h_top.z - p_top.z)


def _link_curve_to_rig(context, ob, curve_ob, use_rotation=True):
    """Insert (or reuse) the ``<joint>_curva`` peg between the piece's joint and its children.

    The modifier only deforms the drawing it sits on: bending a torso bends the torso and leaves
    the arms, collar and head standing still. A peg driven by the curve closes that gap. It has
    to be a peg and not a constraint on the objects: the curve lives in the piece's own space, so
    anything reading it in world space would carry the piece's transform a second time."""
    rig, draw_peg = _peg_of(ob)
    if rig is None:
        return None, "'%s' does not follow a peg rig" % ob.name
    if draw_peg < 0:
        return None, "'%s' follows the rig but no peg" % ob.name
    base = rig.pegs[draw_peg].parent_index
    if base < 0:
        return None, "'%s' hangs on the rig root — nothing to insert the curve peg under" % ob.name
    base_name = rig.pegs[base].name

    # Reuse the peg already driven by this curve, else the one named after the joint, else make it.
    idx = _driven_peg(rig, curve_ob.data)
    if idx < 0:
        name = base_name.replace("_grp", "") + _PEG_SUFFIX
        idx = rig.pegs.find(name)
        if idx < 0:
            rig.pegs.new(name, parent_index=base)
            idx = len(rig.pegs) - 1
    rig.pegs[idx].parent_index = base

    # Everything under the joint travels with the deformation — except the drawing being deformed
    # (the modifier already bends it; the peg would move it a second time) and the curve peg itself.
    moved = []
    for i, peg in enumerate(rig.pegs):
        if peg.parent_index == base and i not in (draw_peg, idx):
            peg.parent_index = idx
            moved.append(peg.name)

    context.view_layer.update()
    _write_drivers(rig, idx, curve_ob, use_rotation=use_rotation)
    _rebuild_graph(rig)
    context.view_layer.update()
    return (rig, idx, rig.pegs[idx].name, base_name, moved), None


def _refresh_driven_peg(context, curve_ob):
    """Restamp the rest pose of whatever peg this curve drives. Returns the peg name or None."""
    for rig in bpy.data.pegrigs:
        idx = _driven_peg(rig, curve_ob.data)
        if idx >= 0:
            use_rotation = any(
                fc.data_path == "pegs[%d].rotation" % idx for fc in rig.animation_data.drivers)
            _write_drivers(rig, idx, curve_ob, use_rotation=use_rotation)
            context.view_layer.update()
            return rig.pegs[idx].name
    return None


# --------------------------------------------------------------------------- #
# Targets
# --------------------------------------------------------------------------- #
def _gp_targets(context, selected_only):
    """The pieces to work on: the selection when there is one, otherwise every visible drawing."""
    sel = [o for o in context.selected_objects if o.type == "GREASEPENCIL"]
    if sel:
        return sel
    if selected_only:
        return []
    return [o for o in context.view_layer.objects
            if o.type == "GREASEPENCIL" and o.visible_get()]


def _curve_pieces(context, selected_only):
    """(piece, modifier) for every target that carries a curve modifier."""
    out = []
    for ob in _gp_targets(context, selected_only):
        for md in ob.modifiers:
            if md.type == _MOD_TYPE:
                out.append((ob, md))
    return out


# --------------------------------------------------------------------------- #
# Operators
# --------------------------------------------------------------------------- #
class OBJECT_OT_nuclear_curve_fit(Operator):
    bl_idname = "object.nuclear_curve_fit"
    bl_label = "Fit Curve to Drawing"
    bl_description = ("Lay the deform curve over the selected drawing end to end (creating it if "
                      "needed), bind it, and restamp the rest pose of the peg it drives")
    bl_options = {"REGISTER", "UNDO"}

    coverage: FloatProperty(
        name="Coverage", default=1.0, min=0.1, max=1.5, subtype="FACTOR",
        description=("How much of the drawing the curve spans. 1.0 (end to end) is the studio "
                     "default: slack above the drawing lets the head leave the collar, slack "
                     "below piles every point onto the last u and the piece turns rigid"))
    points: IntProperty(
        name="Points", default=3, min=2, max=16,
        description="Control points of a curve created from scratch")
    keep_shape: BoolProperty(
        name="Keep Shape", default=True,
        description=("Scale and re-centre the existing curve instead of straightening it, so a "
                     "shaped tail or a bowed leg keeps its silhouette"))
    rebind: BoolProperty(
        name="Bind", default=True,
        description="Bind the drawing to the fitted curve (without this the modifier does nothing)")

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def execute(self, context):
        targets = _gp_targets(context, selected_only=True)
        if not targets:
            self.report({"ERROR"}, "Select the Grease Pencil piece(s) to fit a curve to")
            return {"CANCELLED"}

        done, notes = 0, []
        with _autokey_off(context):
            for ob in targets:
                bounds = _drawing_bounds(ob)
                if bounds is None:
                    notes.append("%s: no stroke points" % ob.name)
                    continue
                lo, hi = bounds

                md = _curve_modifier(ob)
                created = False
                if md is None or md.object is None:
                    with _as_active(context, ob):
                        bpy.ops.object.greasepencil_curve_setup(
                            **({"modifier": md.name} if md is not None else {}))
                    md = _curve_modifier(ob, None if md is None else md.name)
                    if md is None or md.object is None:
                        notes.append("%s: could not create a curve" % ob.name)
                        continue
                    created = True
                curve_ob = md.object
                if _spline(curve_ob) is None:
                    notes.append("%s: '%s' has no bezier spline" % (ob.name, curve_ob.name))
                    continue

                context.view_layer.update()
                if created or not self.keep_shape:
                    count = max(self.points, 2) if created else len(_spline(curve_ob).bezier_points)
                    _ensure_point_count(curve_ob, count)
                    _set_control_points_world(curve_ob, _straight_points(lo, hi, count, self.coverage))
                else:
                    _set_control_points_world(curve_ob, _refit_points(curve_ob, lo, hi, self.coverage))
                context.view_layer.update()

                if self.rebind:
                    _bind(context, ob, md, unbind=True)
                    quality = _bind(context, ob, md)
                    if quality is None:
                        notes.append("%s: bind produced no binding" % ob.name)
                    else:
                        notes.append("%s: u %.3f–%.3f" % (ob.name, quality[0], quality[1]))
                peg = _refresh_driven_peg(context, curve_ob)
                if peg:
                    notes.append("%s: rest restamped on '%s'" % (ob.name, peg))
                done += 1

        for line in notes:
            print("[Deform Curve] " + line)
        if not done:
            self.report({"ERROR"}, notes[0] if notes else "Nothing to fit")
            return {"CANCELLED"}
        self.report({"INFO"}, "Fitted %d curve(s) — %s" % (done, "; ".join(notes[:3])))
        return {"FINISHED"}


class OBJECT_OT_nuclear_curve_bind(Operator):
    bl_idname = "object.nuclear_curve_bind"
    bl_label = "Bind Curves"
    bl_description = ("Bind every selected piece to its deform curve in the current rest pose "
                      "(an unbound Curve modifier deforms nothing, silently)")
    bl_options = {"REGISTER", "UNDO"}

    unbind: BoolProperty(name="Unbind", default=False,
                         description="Remove the binding instead, to measure or reposition freely")
    only_unbound: BoolProperty(
        name="Skip Bound", default=False,
        description="Leave pieces that are already bound alone")

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def execute(self, context):
        pieces = _curve_pieces(context, selected_only=False)
        if not pieces:
            self.report({"ERROR"}, "No piece with a Curve modifier found")
            return {"CANCELLED"}

        done, notes = 0, []
        with _autokey_off(context):
            for ob, md in pieces:
                if md.object is None:
                    notes.append("%s: modifier has no curve" % ob.name)
                    continue
                if self.only_unbound and _bind_quality(ob) is not None:
                    continue
                quality = _bind(context, ob, md, unbind=self.unbind)
                done += 1
                if self.unbind:
                    notes.append("%s: unbound" % ob.name)
                elif quality is None:
                    notes.append("%s: NOT bound" % ob.name)
                else:
                    flag = "" if quality[1] - quality[0] > 0.5 else "  <- degenerate, refit it"
                    notes.append("%s: u %.3f–%.3f%s" % (ob.name, quality[0], quality[1], flag))
        for line in notes:
            print("[Deform Curve] " + line)
        self.report({"INFO"}, "%d piece(s) — %s" % (done, "; ".join(notes[:3])))
        return {"FINISHED"}


class OBJECT_OT_nuclear_curve_link_peg(Operator):
    bl_idname = "object.nuclear_curve_link_peg"
    bl_label = "Link Curve to Rig"
    bl_description = ("Insert a peg driven by the curve's tip between the piece's joint and its "
                      "children, so everything hanging off the piece follows the deformation")
    bl_options = {"REGISTER", "UNDO"}

    use_rotation: BoolProperty(
        name="Follow Tilt", default=True,
        description="Also rotate the children by how much the curve's tip leaned")

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return (context.mode == "OBJECT" and ob is not None and ob.type == "GREASEPENCIL"
                and _curve_modifier(ob) is not None)

    def execute(self, context):
        ob = context.active_object
        md = _curve_modifier(ob)
        if md is None or md.object is None:
            self.report({"ERROR"}, "The active piece has no deform curve")
            return {"CANCELLED"}
        with _autokey_off(context):
            result, error = _link_curve_to_rig(context, ob, md.object, self.use_rotation)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        _rig, _idx, peg_name, base_name, moved = result
        print("[Deform Curve] %s under %s carries: %s" % (peg_name, base_name, ", ".join(moved) or "-"))
        self.report({"INFO"}, "Peg '%s' under '%s' carries %d child peg(s)"
                    % (peg_name, base_name, len(moved)))
        return {"FINISHED"}


class OBJECT_OT_nuclear_curve_refresh(Operator):
    bl_idname = "object.nuclear_curve_refresh"
    bl_label = "Restamp Rest Pose"
    bl_description = ("Take the curve's current shape as the new rest pose of the peg it drives — "
                      "run this after editing the control points of a driving curve, or the limb "
                      "drifts off the body")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and context.active_object is not None

    def execute(self, context):
        ob = context.active_object
        curves = []
        if ob.type == "CURVE":
            curves = [ob]
        else:
            md = _curve_modifier(ob) if ob.type == "GREASEPENCIL" else None
            if md is not None and md.object is not None:
                curves = [md.object]
        if not curves:
            self.report({"ERROR"}, "Select a deform curve, or the piece that uses it")
            return {"CANCELLED"}

        names = []
        with _autokey_off(context):
            for curve_ob in curves:
                peg = _refresh_driven_peg(context, curve_ob)
                if peg:
                    names.append(peg)
        if not names:
            self.report({"WARNING"}, "This curve drives no peg — use Link Curve to Rig first")
            return {"CANCELLED"}
        self.report({"INFO"}, "Rest pose restamped on %s" % ", ".join(names))
        return {"FINISHED"}


class OBJECT_OT_nuclear_curve_check(Operator):
    bl_idname = "object.nuclear_curve_check"
    bl_label = "Check Deform Curves"
    bl_description = ("Report every deform curve in the file: bound or not, how well it covers its "
                      "drawing, double transforms, and whether the peg it drives is wired. "
                      "Changes nothing")
    bl_options = {"REGISTER"}

    def execute(self, context):
        lines = []
        if context.scene.tool_settings.use_keyframe_insert_auto:
            lines.append("! Auto Keying is ON — edits get keyed and replayed over")

        pieces = _curve_pieces(context, selected_only=False)
        if not pieces:
            lines.append("no piece carries a Curve modifier")

        problems = 0
        for ob, md in pieces:
            curve_ob = md.object
            if curve_ob is None:
                lines.append("%s: modifier '%s' has no curve" % (ob.name, md.name))
                problems += 1
                continue
            issues = []
            quality = _bind_quality(ob)
            if quality is None:
                issues.append("NOT BOUND (deforms nothing)")
            elif quality[1] - quality[0] < 0.5:
                issues.append("bind collapsed u %.3f-%.3f (rigid blob)" % quality)
            elif quality[0] > 0.05 or quality[1] < 0.95:
                # u = 0 is the tip: slack there is what makes a head leave its collar.
                issues.append("bind u %.3f-%.3f (curve runs past the drawing)" % quality)

            if quality is not None:
                cells_unbound, cells_total, loose = _stale_bind(ob)
                if cells_unbound:
                    issues.append("%d of %d cell(s) drawn after the bind (they stay rigid)"
                                  % (cells_unbound, cells_total))
                if loose:
                    issues.append("%d point(s) drawn after the bind (they do not bend)" % loose)

            bounds = _drawing_bounds(ob)
            if bounds is not None and _spline(curve_ob) is not None:
                lo, hi = bounds
                cos = [t[0] for t in _control_points_world(curve_ob)]
                axis = (cos[-1] - cos[0])
                if axis.length > 1e-6:
                    axis.normalize()
                    corners = [mathutils.Vector((x, y, z)) for x in (lo.x, hi.x)
                               for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
                    span_draw = max(c.dot(axis) for c in corners) - min(c.dot(axis) for c in corners)
                    ts = [c.dot(axis) for c in cos]
                    ratio = (max(ts) - min(ts)) / span_draw if span_draw > 1e-9 else 0.0
                    if ratio < 0.9 or ratio > 1.1:
                        issues.append("curve spans %.0f%% of the drawing" % (ratio * 100.0))

            if curve_ob.parent is not None and _followpeg(curve_ob) is not None:
                issues.append("parented AND follows a peg (transformed twice when the peg moves)")
            con = _followpeg(curve_ob)
            if con is not None and curve_ob.location.length < 1e-6:
                issues.append("follows a peg from the origin (bind degenerates under a root flip)")
            if curve_ob.parent is None and con is None:
                issues.append("neither parented nor following a peg (stays behind when posed)")

            rig = None
            peg_idx = -1
            for candidate in bpy.data.pegrigs:
                peg_idx = _driven_peg(candidate, curve_ob.data)
                if peg_idx >= 0:
                    rig = candidate
                    break
            own_rig, draw_peg = _peg_of(ob)
            carried = _carried_pegs(own_rig, draw_peg, peg_idx)
            if rig is None:
                # Only worth flagging when there IS something to carry: a leaf piece (tail, shin
                # at the end of the chain) deforms alone and needs no driving peg.
                if carried:
                    issues.append("drives no peg — %s stay(s) behind" % ", ".join(carried[:3]))
            else:
                top, _far = _tips(curve_ob)
                p_top = _spline(curve_ob).bezier_points[top].co
                for fcurve in rig.animation_data.drivers:
                    if fcurve.data_path != "pegs[%d].translation" % peg_idx:
                        continue
                    expr = fcurve.driver.expression
                    try:
                        rest = float(expr.split("(")[-1].rstrip(")"))
                    except ValueError:
                        continue
                    now = p_top[fcurve.array_index]
                    if abs(now - rest) > 1e-3:
                        issues.append("driver rest is stale by %.3f on axis %d — Restamp Rest Pose"
                                      % (now - rest, fcurve.array_index))
                        break

            if issues:
                problems += 1
                lines.append("%s -> %s: %s" % (ob.name, curve_ob.name, "; ".join(issues)))
            else:
                drives = ("peg '%s'" % rig.pegs[peg_idx].name) if rig is not None else "leaf piece"
                lines.append("%s -> %s: ok (u %.2f-%.2f, %s)"
                             % (ob.name, curve_ob.name, quality[0], quality[1], drives))

        for line in lines:
            print("[Deform Curve] " + line)
        context.scene.nuclear_curve_report = "\n".join(lines)
        self.report({"INFO"} if not problems else {"WARNING"},
                    "%d curve(s), %d with problems — see the panel" % (len(pieces), problems))
        return {"FINISHED"}


# --------------------------------------------------------------------------- #
# Panel
# --------------------------------------------------------------------------- #
class VIEW3D_PT_nuclear_deform_curve(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Rig"
    bl_label = "Deform Curve"

    def draw(self, context):
        layout = self.layout
        if context.mode != "OBJECT":
            # Nuclear opens straight into a drawing mode, where every one of these is greyed out.
            layout.label(text="Switch to Object Mode", icon="INFO")
        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("object.nuclear_curve_fit", icon="MOD_CURVE")
        col.operator("object.nuclear_curve_link_peg", icon="LINKED")

        row = layout.row(align=True)
        row.operator("object.nuclear_curve_bind", icon="CON_FOLLOWPATH")
        row.operator("object.nuclear_curve_refresh", text="Restamp", icon="FILE_REFRESH")

        if context.scene.tool_settings.use_keyframe_insert_auto:
            layout.label(text="Auto Keying is on", icon="ERROR")

        # The binding only covers what was on screen when it was made. Say so where the artist is
        # looking, instead of letting a new stroke sit there refusing to bend.
        ob = context.active_object
        if (ob is not None and ob.type == "GREASEPENCIL" and _curve_modifier(ob) is not None
                and _has_binding(ob)):
            cells_unbound, _cells_total, loose = _stale_bind(ob)
            if cells_unbound or loose:
                box = layout.box()
                box.label(text="Drawn after the bind:", icon="ERROR")
                if cells_unbound:
                    box.label(text="%d cell(s) do not bend" % cells_unbound)
                if loose:
                    box.label(text="%d point(s) do not bend" % loose)
                box.operator("object.nuclear_curve_bind", text="Bind Again", icon="CON_FOLLOWPATH")

        layout.separator()
        layout.operator("object.nuclear_curve_check", icon="VIEWZOOM")
        report = context.scene.nuclear_curve_report
        if report:
            box = layout.box()
            box.scale_y = 0.7
            for line in report.split("\n")[:14]:
                box.label(text=line)


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #
_classes = (
    OBJECT_OT_nuclear_curve_fit,
    OBJECT_OT_nuclear_curve_bind,
    OBJECT_OT_nuclear_curve_link_peg,
    OBJECT_OT_nuclear_curve_refresh,
    OBJECT_OT_nuclear_curve_check,
    VIEW3D_PT_nuclear_deform_curve,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.nuclear_curve_report = StringProperty(
        name="Deform Curve Report", default="",
        description="Result of the last Check Deform Curves run")


def unregister():
    del bpy.types.Scene.nuclear_curve_report
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
