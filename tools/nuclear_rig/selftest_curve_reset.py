# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Gate for "Reset Deform Curve" (``OBJECT_OT_greasepencil_curve_reset``).

Run headless::

    nuclear -b --factory-startup --python tools/nuclear_rig/selftest_curve_reset.py

The case that matters: a curve whose SHAPE is keyed. Writing the control points alone is a silent
no-op there -- the next evaluation replays the F-Curve over the reset and the deformed shape comes
back, on the next frame change and again after save/reload. The reset therefore carries the rest
value into the keyed channels as well, at the current frame only, which is what the second half of
these checks pins down: the animation on every other frame has to survive untouched.
"""

import os
import sys
import tempfile

import bpy
from mathutils import Vector

FAILURES = []
CHECKS = 0


def check(label, ok, detail=""):
    global CHECKS
    CHECKS += 1
    print("%s  %s%s" % ("PASS" if ok else "FAIL", label, ("  [%s]" % detail) if detail else ""))
    if not ok:
        FAILURES.append(label)


def close(a, b, tol=1e-4):
    return abs(a - b) <= tol


def build_scene():
    """A vertical Grease Pencil stroke bound to a straight three-point deform curve."""
    if bpy.context.object is not None and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()

    bpy.ops.object.grease_pencil_add(type='EMPTY', location=(0, 0, 0))
    gp = bpy.context.object
    gp.name = "peca"
    layer = gp.data.layers[0] if gp.data.layers else gp.data.layers.new("Color")
    frame = layer.current_frame() or layer.frames.new(1)
    drawing = frame.drawing
    drawing.add_strokes([20])
    positions = drawing.attributes['position'].data
    for i in range(20):
        positions[i].vector = (0.0, 0.0, -1.0 + 2.0 * i / 19.0)

    data = bpy.data.curves.new("Deform Curve", 'CURVE')
    data.dimensions = '3D'
    spline = data.splines.new('BEZIER')
    spline.bezier_points.add(2)
    for i, z in enumerate((1.0, 0.0, -1.0)):
        point = spline.bezier_points[i]
        point.co = (0.0, 0.0, z)
        point.handle_left_type = point.handle_right_type = 'AUTO'
    curve_ob = bpy.data.objects.new("Deform Curve", data)
    bpy.context.scene.collection.objects.link(curve_ob)

    md = gp.modifiers.new("Curve", 'GREASE_PENCIL_CURVE')
    md.object = curve_ob
    bpy.context.view_layer.objects.active = gp
    gp.select_set(True)
    bpy.ops.object.greasepencil_curve_bind(modifier=md.name)
    return gp, curve_ob, md


def knots(curve_ob):
    return [tuple(round(v, 4) for v in p.co) for p in curve_ob.data.splines[0].bezier_points]


def drift(gp):
    """How far the evaluated drawing sits from the drawing as authored."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = gp.evaluated_get(depsgraph).data.layers[0].current_frame().drawing
    source = gp.data.layers[0].current_frame().drawing
    a = [Vector(v.vector) for v in evaluated.attributes['position'].data]
    b = [Vector(v.vector) for v in source.attributes['position'].data]
    return max((x - y).length for x, y in zip(a, b))


def key_whole_curve(curve_ob):
    import nuclear_curve_gizmo
    nuclear_curve_gizmo.keyframe_whole_curve(curve_ob)


def shape_fcurves(curve_ob):
    ad = curve_ob.data.animation_data
    if ad is None or ad.action is None:
        return {}
    out = {}
    for layer in ad.action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for fc in bag.fcurves:
                    out[(fc.data_path, fc.array_index)] = fc
    return out


# --------------------------------------------------------------------------- #
# 1. A keyed curve: the reset has to survive evaluation, a frame change and a reload
# --------------------------------------------------------------------------- #
gp, curve_ob, md = build_scene()
scene = bpy.context.scene
scene.tool_settings.use_keyframe_insert_auto = True
curve_ob.data.splines[0].bezier_points[1].co = (0.6, 0.0, 0.0)
key_whole_curve(curve_ob)
bpy.context.view_layer.update()
check("keyed curve: posing deforms the drawing", drift(gp) > 0.5, "%.4f" % drift(gp))
check("keyed curve: the gizmo keys all 27 channels", len(shape_fcurves(curve_ob)) == 27,
      str(len(shape_fcurves(curve_ob))))

bpy.context.view_layer.objects.active = gp
bpy.ops.object.greasepencil_curve_reset(modifier=md.name, mode='ALL')
bpy.context.view_layer.update()
check("keyed curve: reset lands", close(drift(gp), 0.0), "%.4f" % drift(gp))

scene.frame_set(2)
scene.frame_set(1)
check("keyed curve: reset survives a frame change", close(drift(gp), 0.0), "%.4f" % drift(gp))

blend = os.path.join(tempfile.gettempdir(), "nuclear_selftest_curve_reset.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend)
bpy.ops.wm.open_mainfile(filepath=blend)
gp = bpy.data.objects['peca']
bpy.context.view_layer.update()
check("keyed curve: reset survives save and reload", close(drift(gp), 0.0), "%.4f" % drift(gp))
os.unlink(blend)

# --------------------------------------------------------------------------- #
# 2. The animation on the other frames must not move
# --------------------------------------------------------------------------- #
gp, curve_ob, md = build_scene()
scene = bpy.context.scene
path = "splines[0].bezier_points[1].co"
for frame, x in ((1, 0.0), (50, 0.6), (100, -0.4)):
    scene.frame_set(frame)
    curve_ob.data.splines[0].bezier_points[1].co = (x, 0.0, 0.0)
    key_whole_curve(curve_ob)

fcurve = shape_fcurves(curve_ob)[(path, 0)]
before = {round(k.co[0]): round(k.co[1], 4) for k in fcurve.keyframe_points}
scene.frame_set(50)
bpy.context.view_layer.objects.active = gp
bpy.ops.object.greasepencil_curve_reset(modifier=md.name, mode='ALL')
bpy.context.view_layer.update()
check("animated curve: reset lands on the current frame", close(drift(gp), 0.0), "%.4f" % drift(gp))

fcurve = shape_fcurves(curve_ob)[(path, 0)]
after = {round(k.co[0]): round(k.co[1], 4) for k in fcurve.keyframe_points}
check("animated curve: the reset frame is keyed to rest", close(after.get(50, 9.0), 0.0),
      str(after.get(50)))
check("animated curve: frame 1 untouched", close(after.get(1, 9.0), before[1]),
      "%s -> %s" % (before.get(1), after.get(1)))
check("animated curve: frame 100 untouched", close(after.get(100, 9.0), before[100]),
      "%s -> %s" % (before.get(100), after.get(100)))
check("animated curve: no key count blow-up", len(after) == len(before), "%d -> %d" % (len(before), len(after)))

scene.frame_set(100)
bpy.context.view_layer.update()
check("animated curve: frame 100 still poses the drawing", drift(gp) > 0.3, "%.4f" % drift(gp))

# A frame with no key of its own: the reset can only hold by adding one, otherwise it evaluates
# straight back to the interpolated pose. The neighbouring keys still must not move.
scene.frame_set(30)
bpy.ops.object.greasepencil_curve_reset(modifier=md.name, mode='ALL')
bpy.context.view_layer.update()
check("keyless frame: reset lands", close(drift(gp), 0.0), "%.4f" % drift(gp))
scene.frame_set(31)
scene.frame_set(30)
check("keyless frame: reset survives a frame change", close(drift(gp), 0.0), "%.4f" % drift(gp))
fcurve = shape_fcurves(curve_ob)[(path, 0)]
added = {round(k.co[0]): round(k.co[1], 4) for k in fcurve.keyframe_points}
check("keyless frame: exactly one key was added", len(added) == len(after) + 1,
      "%d -> %d" % (len(after), len(added)))
check("keyless frame: frame 100 still untouched", close(added.get(100, 9.0), before[100]),
      str(added.get(100)))

# --------------------------------------------------------------------------- #
# 3. "Selected" resets (and keys) only what is selected
# --------------------------------------------------------------------------- #
gp, curve_ob, md = build_scene()
scene = bpy.context.scene
points = curve_ob.data.splines[0].bezier_points
points[0].co = (0.3, 0.0, 1.0)
points[1].co = (0.6, 0.0, 0.0)
key_whole_curve(curve_ob)
for p in points:
    p.select_control_point = False
points[1].select_control_point = True
bpy.context.view_layer.objects.active = gp
bpy.ops.object.greasepencil_curve_reset(modifier=md.name, mode='SELECTED')
bpy.context.view_layer.update()
scene.frame_set(2)
scene.frame_set(1)
shape = knots(curve_ob)
check("selected: the selected knot went back to rest", close(shape[1][0], 0.0), str(shape[1]))
check("selected: the unselected knot stayed posed", close(shape[0][0], 0.3), str(shape[0]))

# --------------------------------------------------------------------------- #
# 4. An unanimated curve keeps working, and nothing gets keyed behind the artist
# --------------------------------------------------------------------------- #
gp, curve_ob, md = build_scene()
bpy.context.scene.tool_settings.use_keyframe_insert_auto = False
curve_ob.data.splines[0].bezier_points[1].co = (0.6, 0.0, 0.0)
bpy.context.view_layer.update()
bpy.context.view_layer.objects.active = gp
bpy.ops.object.greasepencil_curve_reset(modifier=md.name, mode='ALL')
bpy.context.view_layer.update()
check("unanimated: reset lands", close(drift(gp), 0.0), "%.4f" % drift(gp))
check("unanimated: the reset did not create an Action", curve_ob.data.animation_data is None
      or curve_ob.data.animation_data.action is None)

print()
print("%d checks, %d failed" % (CHECKS, len(FAILURES)))
for name in FAILURES:
    print("  FAILED: %s" % name)
sys.exit(1 if FAILURES else 0)
