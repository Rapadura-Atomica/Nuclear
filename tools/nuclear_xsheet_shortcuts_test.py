# SPDX-FileCopyrightText: 2026 Nuclear Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Headless checks for the Nuclear Xsheet keyboard shortcuts (T6).

Covers the half that is pure data work: where F6/F7 decide to act, what they do when they get
there, and which keymap items `_register_xsheet_keymap` puts in place. What needs a real region
is out of scope here and belongs in the GUI pass — the cursor-follows-the-mouse branch of
`_xsheet_key_target`, the Ctrl+D ghost preview, and the modal placement itself.

Run with::

    build/bin/nuclear -b --factory-startup --python tools/nuclear_xsheet_shortcuts_test.py
"""

import importlib.util
import os
import sys

import bpy

FAILED = []


def check(label, got, want):
    ok = got == want
    print("%s %s  (got %r, want %r)" % ("PASS" if ok else "FAIL", label, got, want))
    if not ok:
        FAILED.append(label)


def load_module():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, os.pardir, "scripts", "modules", "nuclear_xsheet.py")
    spec = importlib.util.spec_from_file_location("nuclear_xsheet_under_test",
                                                  os.path.normpath(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_gp(name, layer_specs):
    gp = bpy.data.grease_pencils.new(name)
    ob = bpy.data.objects.new(name, gp)
    bpy.context.scene.collection.objects.link(ob)
    for lname, frames in layer_specs:
        layer = gp.layers.new(lname)
        for f in frames:
            if not any(fr.frame_number == f for fr in layer.frames):
                layer.frames.new(f)
    return ob


def frames_of(ob, lname):
    layer = next(lyr for lyr in ob.data.layers if lyr.name == lname)
    return sorted(fr.frame_number for fr in layer.frames)


def activate(ob):
    """Make `ob` the active object, which is what the operators read."""
    bpy.context.view_layer.objects.active = ob
    return ob


def main():
    xs = load_module()
    xs.register()

    # --- 1. target falls back to the playhead when there is no event ---------------------
    ob = activate(make_gp("target", [("A", [1, 5]), ("B", [2])]))
    ob.data.layers.active = ob.data.layers["B"]
    bpy.context.scene.frame_current = 7
    layer, f = xs._xsheet_key_target(bpy.context, None)
    check("target: active layer", layer.name, "B")
    check("target: current frame", f, 7)

    # An object that is not Grease Pencil yields no target rather than raising.
    empty = bpy.data.objects.new("plain", None)
    bpy.context.scene.collection.objects.link(empty)
    activate(empty)
    check("target: non-GP object", xs._xsheet_key_target(bpy.context, None), (None, 0))
    check("key poll: non-GP object", xs._xsheet_key_poll(bpy.context), False)
    activate(ob)
    check("key poll: GP object", xs._xsheet_key_poll(bpy.context), True)

    # --- 2. F6 exposes a drawing at the playhead ----------------------------------------
    ob = activate(make_gp("f6", [("A", [1])]))
    ob.data.layers.active = ob.data.layers["A"]
    bpy.context.scene.frame_current = 9
    check("F6: finished", bpy.ops.nuclear.xsheet_key_add(), {'FINISHED'})
    check("F6: drawing created", frames_of(ob, "A"), [1, 9])

    # --- 3. F6 on an occupied cell refuses instead of clobbering the drawing -------------
    bpy.context.scene.frame_current = 9
    check("F6: occupied cell cancels", bpy.ops.nuclear.xsheet_key_add(), {'CANCELLED'})
    check("F6: drawing untouched", frames_of(ob, "A"), [1, 9])

    # --- 4. F6 refuses a locked layer ---------------------------------------------------
    ob = activate(make_gp("f6locked", [("A", [1])]))
    ob.data.layers.active = ob.data.layers["A"]
    ob.data.layers["A"].lock = True
    bpy.context.scene.frame_current = 4
    check("F6: locked layer cancels", bpy.ops.nuclear.xsheet_key_add(), {'CANCELLED'})
    check("F6: locked layer untouched", frames_of(ob, "A"), [1])

    # --- 5. F7 deletes the drawing at the playhead --------------------------------------
    ob = activate(make_gp("f7", [("A", [1, 6])]))
    ob.data.layers.active = ob.data.layers["A"]
    xs._xsheet_selected.clear()
    bpy.context.scene.frame_current = 6
    check("F7: finished", bpy.ops.nuclear.xsheet_key_remove(), {'FINISHED'})
    check("F7: drawing removed", frames_of(ob, "A"), [1])

    # --- 6. F7 on an empty cell is a refusal, not a crash -------------------------------
    bpy.context.scene.frame_current = 99
    check("F7: empty cell cancels", bpy.ops.nuclear.xsheet_key_remove(), {'CANCELLED'})
    check("F7: nothing removed", frames_of(ob, "A"), [1])

    # --- 7. F7 refuses a locked layer ---------------------------------------------------
    ob = activate(make_gp("f7locked", [("A", [3])]))
    ob.data.layers.active = ob.data.layers["A"]
    ob.data.layers["A"].lock = True
    xs._xsheet_selected.clear()
    bpy.context.scene.frame_current = 3
    check("F7: locked layer cancels", bpy.ops.nuclear.xsheet_key_remove(), {'CANCELLED'})
    check("F7: locked layer untouched", frames_of(ob, "A"), [3])

    # --- 8. with a selection, F7 deletes the whole block --------------------------------
    ob = activate(make_gp("f7block", [("A", [1, 5, 9]), ("B", [2, 5])]))
    ob.data.layers.active = ob.data.layers["A"]
    xs._xsheet_selected.clear()
    xs._xsheet_selected.update({("A", 5), ("A", 9), ("B", 2)})
    bpy.context.scene.frame_current = 1  # deliberately NOT one of the selected cells
    check("F7: block finished", bpy.ops.nuclear.xsheet_key_remove(), {'FINISHED'})
    check("F7: block removed from A", frames_of(ob, "A"), [1])
    check("F7: block removed from B", frames_of(ob, "B"), [5])
    check("F7: selection emptied", xs._xsheet_selected, set())

    # The cell under the playhead survives: the selection won, as it should.
    check("F7: playhead cell untouched by a block delete", frames_of(ob, "A"), [1])

    # --- 9. F6 ignores the selection and keys its own target ----------------------------
    # Only exposed cells can be selected, so "add" has nothing to do with a selection; it must
    # keep acting on the target or it would be a no-op whenever something is highlighted.
    ob = activate(make_gp("f6sel", [("A", [1, 5])]))
    ob.data.layers.active = ob.data.layers["A"]
    xs._xsheet_selected.clear()
    xs._xsheet_selected.update({("A", 5)})
    bpy.context.scene.frame_current = 12
    check("F6: adds despite a selection", bpy.ops.nuclear.xsheet_key_add(), {'FINISHED'})
    check("F6: added at the playhead", frames_of(ob, "A"), [1, 5, 12])
    check("F6: selection left alone", xs._xsheet_selected, {("A", 5)})
    xs._xsheet_selected.clear()

    # --- 10. the keymap says what it should ---------------------------------------------
    bound = {}
    for _km, kmi in xs._xsheet_keymaps:
        bound.setdefault(kmi.idname, []).append(
            (kmi.type, kmi.ctrl, kmi.shift, kmi.alt))
    if not xs._xsheet_keymaps:
        # `wm.keyconfigs.addon` is None in some background configurations; the keymap half of
        # the suite cannot run there, and silently "passing" would be a lie.
        print("SKIP keymap checks: no addon keyconfig in this session")
    else:
        check("keymap: F6 -> add", ('F6', False, False, False) in bound.get(
            "nuclear.xsheet_key_add", []), True)
        check("keymap: F7 -> remove", ('F7', False, False, False) in bound.get(
            "nuclear.xsheet_key_remove", []), True)
        check("keymap: Ctrl+D -> duplicate", ('D', True, False, False) in bound.get(
            "nuclear.xsheet_duplicate_move", []), True)
        # The gesture the function keys replaced must be gone, or Ctrl+click would keep
        # toggling exposure behind the artist's back.
        check("keymap: Ctrl+click no longer toggles",
              bound.get("nuclear.xsheet_toggle", []), [])
        # F6/F7 are bound twice on purpose: once in the timeline, once over the canvas.
        spaces = {}
        for km, kmi in xs._xsheet_keymaps:
            spaces.setdefault(kmi.idname, set()).add(km.space_type)
        check("keymap: F6 reaches the viewport too",
              spaces.get("nuclear.xsheet_key_add"),
              {'DOPESHEET_EDITOR', 'VIEW_3D'})
        check("keymap: F7 reaches the viewport too",
              spaces.get("nuclear.xsheet_key_remove"),
              {'DOPESHEET_EDITOR', 'VIEW_3D'})
        # Ctrl+D needs the cell grid under the cursor to place the copies, so it stays put.
        check("keymap: Ctrl+D stays in the timeline",
              spaces.get("nuclear.xsheet_duplicate_move"), {'DOPESHEET_EDITOR'})
        # The gestures the artist kept must survive the rewiring.
        check("keymap: Alt+drag still moves", ('LEFTMOUSE', False, False, True) in bound.get(
            "nuclear.xsheet_drag", []), True)
        check("keymap: Shift+Alt+drag still duplicates",
              ('LEFTMOUSE', False, True, True) in bound.get("nuclear.xsheet_drag", []), True)
        check("keymap: X/Del still delete the selection",
              sorted(t[0] for t in bound.get("nuclear.xsheet_delete_selected", [])),
              ['DEL', 'X'])

    # --- 11. duplicate-move is gated on the Xsheet, not just on a GP object -------------
    # Its poll is the strict one: without a dope sheet under the cursor there is no way to
    # map mouse movement onto frames, so it must not fire from the viewport.
    check("Ctrl+D: refuses outside the Xsheet",
          xs.NUCLEAR_OT_xsheet_duplicate_move.poll(bpy.context), False)

    xs.unregister()
    print("\n%s" % ("FAILED: %s" % ", ".join(FAILED) if FAILED else "ALL PASS"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
