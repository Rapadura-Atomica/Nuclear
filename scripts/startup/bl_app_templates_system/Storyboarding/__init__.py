# SPDX-FileCopyrightText: 2025 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

# Initialization script for Storyboarding template

import bpy
from bpy.app.handlers import persistent

# Nuclear's Xsheet timeline (the same one the Nuclear template uses). Only the timeline: the
# transport row with + KF / - KF and the play controls is a Nuclear-template header override
# and is NOT pulled in here, so this template keeps its native dope-sheet header and footer.
import nuclear_xsheet


def update_factory_startup_screens():
    # Storyboarding.
    screen = bpy.data.screens["Storyboarding"]
    for area in screen.areas:
        if area.type == 'PROPERTIES':
            # Set Tool settings as default in properties panel.
            space = area.spaces.active
            space.context = 'TOOL'
        elif area.type == 'DOPESHEET_EDITOR':
            # Open sidebar in Dope-sheet.
            space = area.spaces.active
            space.show_region_ui = True


def update_factory_startup_scenes():
    for scene in bpy.data.scenes:
        scene.tool_settings.use_keyframe_insert_auto = True
        scene.tool_settings.gpencil_sculpt.use_scale_thickness = True

        if scene.name == "Edit":
            scene.tool_settings.use_keyframe_insert_auto = False


def update_factory_startup_grease_pencils():
    for grease_pencil in bpy.data.grease_pencils:
        grease_pencil.onion_keyframe_type = 'ALL'


@persistent
def load_handler(_):
    nuclear_xsheet.reset_state()
    update_factory_startup_screens()
    update_factory_startup_scenes()
    update_factory_startup_grease_pencils()
    # Point the Dope Sheet at Grease Pencil mode and drop the duplicated channel list; the
    # footer stays, since this template has no transport header of its own.
    nuclear_xsheet.apply_timeline_layout()


def register():
    bpy.app.handlers.load_factory_startup_post.append(load_handler)
    nuclear_xsheet.register()


def unregister():
    nuclear_xsheet.unregister()
    bpy.app.handlers.load_factory_startup_post.remove(load_handler)
