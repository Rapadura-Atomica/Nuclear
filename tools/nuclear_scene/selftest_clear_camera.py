"""Self-test for "Clear Camera" (View > Viewpoint), the one-click template wipe.

The command exists so an animator can start over inside the file they already have open,
which makes three things load-bearing and all three are checked here.

It must take EVERYTHING, not what happens to be selectable: a hidden layer, a locked
piece or an unselectable peg is exactly what an animator forgets about and would find
still sitting in a "clean" file. Deletion therefore goes through the data API, never
through `object.delete`, and the checks below hide and lock objects on purpose.

It must stop at the active scene. A storyboard keeps one scene per take, so wiping take
03 while take 04 loses its drawings would be worse than useless. An object linked into
both scenes is a real case (a reused background): it leaves this scene and stays alive in
the other one.

And what is rebuilt has to be the TEMPLATE camera -- 12 units back, 50 mm, in its own
"Camera" collection -- not the camera that happened to be in the file, so a wipe after
someone dollied and keyed the camera comes back to the same framing every time.

Run headless, from the repository root:

    ./build/bin/nuclear -b --factory-startup --python tools/nuclear_scene/selftest_clear_camera.py
"""
import math
import sys

import bpy

FAIL = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


def build_dirty_scene(scene):
    """Fill `scene` with the kind of mess a shot accumulates."""
    for ob in list(scene.objects):
        for col in [scene.collection] + list(scene.collection.children_recursive):
            if ob.name in col.objects:
                col.objects.unlink(ob)

    drawing = bpy.data.objects.new("Desenho", bpy.data.grease_pencils.new("Desenho"))
    scene.collection.objects.link(drawing)
    drawing.location = (1.0, 2.0, 3.0)
    drawing.keyframe_insert("location", frame=1)

    mesh = bpy.data.objects.new("Cube", bpy.data.meshes.new("Cube"))
    scene.collection.objects.link(mesh)
    # The forgettable ones: invisible and unclickable, but still in the file.
    mesh.hide_viewport = True
    mesh.hide_select = True

    sub = bpy.data.collections.new("Personagens")
    scene.collection.children.link(sub)
    sub.objects.link(bpy.data.objects.new("Peg", None))
    sub.objects.link(bpy.data.objects.new("Light", bpy.data.lights.new("Light", 'POINT')))

    camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    scene.collection.objects.link(camera)
    camera.location = (7.0, 7.0, 7.0)
    camera.rotation_euler = (0.5, 0.5, 0.5)
    camera.data.lens = 135.0
    camera.keyframe_insert("location", frame=1)
    scene.camera = camera

    scene.timeline_markers.new("MARK", frame=10)
    scene.frame_start = 5
    scene.frame_end = 42
    return drawing


def main():
    scene = bpy.context.scene
    build_dirty_scene(scene)

    # A second take, plus a background reused by both.
    other = bpy.data.scenes.new("Take02")
    other.collection.objects.link(bpy.data.objects.new("Fundo", bpy.data.meshes.new("Fundo")))
    shared = bpy.data.objects.new("Compartilhado", None)
    scene.collection.objects.link(shared)
    other.collection.objects.link(shared)

    result = bpy.ops.scene.nuclear_clear_camera()
    check(result == {'FINISHED'}, "operator finished, got %r" % (result,))

    names = [ob.name for ob in scene.objects]
    check(names == ["Camera"], "only the camera is left, got %r" % (names,))

    camera = scene.objects.get("Camera")
    check(camera is not None and camera.type == 'CAMERA', "the survivor is a camera")
    check(scene.camera == camera, "it is the active camera of the scene")
    check(tuple(round(v, 4) for v in camera.location) == (0.0, -12.0, 0.0),
          "location back to the template, got %r" % (tuple(camera.location),))
    check(abs(camera.rotation_euler[0] - math.pi / 2.0) < 1e-5
          and abs(camera.rotation_euler[1]) < 1e-6
          and abs(camera.rotation_euler[2]) < 1e-6,
          "rotation back to the template, got %r" % (tuple(camera.rotation_euler),))
    check(camera.data.lens == 50.0, "50 mm again, got %r" % (camera.data.lens,))
    check(camera.data.clip_end == 1000.0, "clip end 1000, got %r" % (camera.data.clip_end,))
    check(camera.animation_data is None, "the keyed camera move is gone")

    children = [col.name for col in scene.collection.children]
    check(children == ["Camera"], "the camera sits alone in its collection, got %r" % (children,))
    check("Personagens" not in bpy.data.collections, "emptied collections are purged")
    check(len(scene.timeline_markers) == 0, "markers cleared")
    check(len(bpy.data.actions) == 0, "orphan actions purged, %d left" % len(bpy.data.actions))
    check(len(bpy.data.grease_pencils) == 0,
          "orphan drawings purged, %d left" % len(bpy.data.grease_pencils))
    check(bpy.data.objects.get("Cube") is None, "the hidden, unselectable mesh went too")

    # Frame range is deliberately NOT reset: it is shot data, not template data.
    check(scene.frame_start == 5 and scene.frame_end == 42, "frame range left alone")

    survivors = sorted(ob.name for ob in other.objects)
    check(survivors == ["Compartilhado", "Fundo"], "the other take is untouched, got %r" % (survivors,))

    # Running it on an already clean scene must not pile up "Camera.001".
    bpy.ops.scene.nuclear_clear_camera()
    check([ob.name for ob in scene.objects] == ["Camera"]
          and [col.name for col in scene.collection.children] == ["Camera"],
          "a second run stays clean, got %r / %r"
          % ([ob.name for ob in scene.objects], [col.name for col in scene.collection.children]))

    import nuclear_clear_camera
    check(nuclear_clear_camera._draw_menu_item
          in bpy.types.VIEW3D_MT_view_viewpoint._dyn_ui_initialize(),
          "the menu item is wired into View > Viewpoint")

    print("\n%d FAIL(s)" % len(FAIL))
    for msg in FAIL:
        print(" -", msg)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
