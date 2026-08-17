# SPDX-FileCopyrightText: 2026 Nuclear (derivative of Blender)
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Nuclear — Clear Camera.

Puts the active scene back to the state of a freshly opened template: every
object goes (drawings, meshes, rigs, lights) along with its animation, the
collections that held them go, timeline markers go, and a single default camera
is rebuilt in the "Camera" collection. Orphan data is purged afterwards so the
deleted drawings do not stay parked in the file.

Only the ACTIVE scene is touched. Other scenes — the takes of a storyboard —
are left alone, and an object still linked to one of them is unlinked here but
survives in the file.

Pure Python — no C changes. This is a startup module: it auto-registers.
"""

import math

import bpy

# The default camera of the Nuclear template (scripts/startup/
# bl_app_templates_system/Nuclear/startup.blend): 12 units back, aimed down +Y,
# 50 mm on a 36 mm sensor, parked in its own "Camera" collection.
CAMERA_NAME = "Camera"
CAMERA_COLLECTION = "Camera"
CAMERA_LOCATION = (0.0, -12.0, 0.0)
CAMERA_ROTATION = (math.pi / 2.0, 0.0, 0.0)
CAMERA_LENS = 50.0
CAMERA_SENSOR_WIDTH = 36.0
CAMERA_CLIP_START = 0.1
CAMERA_CLIP_END = 1000.0
CAMERA_ORTHO_SCALE = 6.0


# ---------------------------------------------------------------------------
# Core (data layer — no UI, headless-testable)
# ---------------------------------------------------------------------------

def _scene_collections(scene):
    """The scene's master collection plus every collection nested under it."""
    return [scene.collection] + list(scene.collection.children_recursive)


def remove_objects(scene):
    """Unlink every object of `scene` and delete the ones no other scene keeps.

    Deleting through the data API rather than ``object.delete`` means hidden,
    unselectable and locked objects go too — a template wipe should not stop at
    whatever happens to be selectable.

    Returns how many objects left the scene.
    """
    collections = _scene_collections(scene)
    objects = list(scene.objects)

    for ob in objects:
        for col in collections:
            if ob.name in col.objects:
                col.objects.unlink(ob)

    for ob in objects:
        # An object shared with another scene (a storyboard take) is only
        # unlinked from this one.
        if not ob.users_scene:
            bpy.data.objects.remove(ob)

    return len(objects)


def remove_collections(scene):
    """Unlink every collection under the scene root. Empty ones die in the purge."""
    children = list(scene.collection.children)
    for col in children:
        scene.collection.children.unlink(col)
    return len(children)


def build_default_camera(scene):
    """Create the template's camera in a fresh "Camera" collection, and make it active."""
    collection = bpy.data.collections.new(CAMERA_COLLECTION)
    scene.collection.children.link(collection)

    camera_data = bpy.data.cameras.new(CAMERA_NAME)
    camera_data.type = 'PERSP'
    camera_data.lens = CAMERA_LENS
    camera_data.sensor_width = CAMERA_SENSOR_WIDTH
    camera_data.shift_x = 0.0
    camera_data.shift_y = 0.0
    camera_data.clip_start = CAMERA_CLIP_START
    camera_data.clip_end = CAMERA_CLIP_END
    camera_data.ortho_scale = CAMERA_ORTHO_SCALE

    camera = bpy.data.objects.new(CAMERA_NAME, camera_data)
    camera.location = CAMERA_LOCATION
    camera.rotation_mode = 'XYZ'
    camera.rotation_euler = CAMERA_ROTATION
    camera.scale = (1.0, 1.0, 1.0)
    collection.objects.link(camera)

    scene.camera = camera
    view_layer = bpy.context.view_layer
    if view_layer is not None and view_layer.objects.get(CAMERA_NAME) == camera:
        view_layer.objects.active = camera

    return camera


def clear_scene(scene):
    """Wipe `scene` back to a bare default camera. Returns the object count removed."""
    removed = remove_objects(scene)
    remove_collections(scene)

    scene.animation_data_clear()
    scene.timeline_markers.clear()

    # Purge before rebuilding, so the camera we create can claim the plain
    # "Camera" name the deleted one was holding.
    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)

    build_default_camera(scene)
    return removed


# ---------------------------------------------------------------------------
# Operator + menu
# ---------------------------------------------------------------------------

class SCENE_OT_nuclear_clear_camera(bpy.types.Operator):
    """Delete every object, animation and marker of this scene and rebuild the default camera"""
    bl_idname = "scene.nuclear_clear_camera"
    bl_label = "Clear Camera"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self,
            event,
            title="Clear Camera",
            message="Delete every object, animation and marker of this scene?",
            confirm_text="Clear",
            icon='WARNING',
        )

    def execute(self, context):
        # The template opens in Draw mode, so the command is normally fired with a
        # drawing still in paint/edit mode — leave it before deleting the object.
        ob = context.object
        if ob is not None and ob.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        removed = clear_scene(context.scene)
        self.report({'INFO'}, "Cleared {:d} object(s)".format(removed))
        return {'FINISHED'}


def _draw_menu_item(self, _context):
    layout = self.layout
    layout.separator()
    layout.operator(SCENE_OT_nuclear_clear_camera.bl_idname, text="Clear Camera", icon='TRASH')


_classes = (
    SCENE_OT_nuclear_clear_camera,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_view_viewpoint.append(_draw_menu_item)


def unregister():
    bpy.types.VIEW3D_MT_view_viewpoint.remove(_draw_menu_item)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
