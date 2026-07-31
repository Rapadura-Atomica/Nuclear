# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Nuclear — open rigged files with a timeline that can actually show the pose keys.

The 2D Animation workspace ships its Dope Sheet in **Grease Pencil** mode, which lists
drawing layers and nothing else: no peg channels, no deform-curve channels. In a cut-out
file that is the whole animation — the artist poses pegs and bends deform curves, keys
every one of them, and the timeline stays empty. It reads as "it is not keying", and the
upstream comment in ``anim_filter.cc`` explains why teaching that mode to list F-Curves
is not an option: nearly every operator in the editor special-cases ``ANIMCONT_GPENCIL``,
so the channels would draw but refuse to be selected, moved or deleted.

Dope Sheet mode has none of that problem and is a superset here — it lists the Grease
Pencil layers *and* the rig channels (the fork already surfaces the controlling PegRig,
and now the deform curves, under the drawing object). So a file that carries a PegRig
opens in Dope Sheet mode.

Only files that actually have a rig are touched, only the Grease Pencil mode is swapped
(any other mode is a deliberate choice and is left alone), and nothing is written to the
file - the switch happens on load, in the UI only.
"""

import bpy
from bpy.app.handlers import persistent


def _switch_gpencil_dopesheets(screens):
    """Swap Grease Pencil mode for Dope Sheet mode. Returns how many editors changed."""
    changed = 0
    for screen in screens:
        for area in screen.areas:
            if area.type != 'DOPESHEET_EDITOR':
                continue
            for space in area.spaces:
                if getattr(space, "mode", None) == 'GPENCIL':
                    space.mode = 'DOPESHEET'
                    changed += 1
    return changed


@persistent
def _on_load_post(_file_path):
    if not bpy.data.pegrigs:
        # No rig: a storyboard or a plain drawing file, where the Grease Pencil mode is
        # exactly what the artist wants.
        return
    _switch_gpencil_dopesheets(bpy.data.screens)


def register():
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister():
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
