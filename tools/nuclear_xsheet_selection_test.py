# SPDX-FileCopyrightText: 2026 Nuclear Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Headless checks for the Nuclear Xsheet cell selection (T5.1/T5.2).

Covers the parts that are pure data work — block move/duplicate, the all-or-nothing gate,
selection pruning and block delete. The drawing (white outline, ghosts, rubber band) and the
click/keymap routing need a real region and are validated in the GUI.

Run with::

    build/bin/nuclear -b --factory-startup --python tools/nuclear_xsheet_selection_test.py
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


def load_template():
    """Import the shared Xsheet module without activating any app template.

    The Xsheet used to live inside the Nuclear template (Seam 7); it now lives in
    scripts/modules/nuclear_xsheet.py so every template can have the same timeline.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, os.pardir, "scripts", "modules", "nuclear_xsheet.py")
    spec = importlib.util.spec_from_file_location("nuclear_xsheet_under_test",
                                                  os.path.normpath(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_gp(name, layer_specs):
    """A Grease Pencil object whose layers hold keyframes at the given frame numbers."""
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


class FakeOp:
    """Stands in for an Operator: collects what would be reported to the user."""

    def __init__(self):
        self.reports = []

    def report(self, kind, message):
        self.reports.append((tuple(kind)[0], message))


def main():
    xs = load_template()

    # --- 1. block move keeps the relative spacing --------------------------------------
    ob = make_gp("blockmove", [("A", [1, 5, 9]), ("B", [3, 4])])
    cells = [("A", 5), ("A", 9), ("B", 3)]
    moved, err = xs._xsheet_shift_cells(ob, cells, 10, duplicate=False)
    check("block move: no error", err, None)
    check("block move: A shifted", frames_of(ob, "A"), [1, 15, 19])
    check("block move: B shifted", frames_of(ob, "B"), [4, 13])
    check("block move: reports new keys", sorted(moved), [("A", 15), ("A", 19), ("B", 13)])

    # --- 2. moving left over its own vacated cells is legal ----------------------------
    ob = make_gp("shiftleft", [("A", [10, 11, 12])])
    _, err = xs._xsheet_shift_cells(ob, [("A", 10), ("A", 11), ("A", 12)], -4, duplicate=False)
    check("overlapping shift left: no error", err, None)
    check("overlapping shift left: frames", frames_of(ob, "A"), [6, 7, 8])

    # --- 3. an occupied target refuses the WHOLE gesture ------------------------------
    ob = make_gp("blocked", [("A", [1, 2]), ("B", [1, 7])])
    before_a, before_b = frames_of(ob, "A"), frames_of(ob, "B")
    moved, err = xs._xsheet_shift_cells(ob, [("A", 1), ("B", 1)], 6, duplicate=False)
    check("occupied target: refuses", err is not None, True)
    check("occupied target: nothing moved", moved, [])
    check("occupied target: A untouched", frames_of(ob, "A"), before_a)
    check("occupied target: B untouched", frames_of(ob, "B"), before_b)

    # --- 4. a negative destination refuses too ----------------------------------------
    ob = make_gp("negative", [("A", [2, 6])])
    _, err = xs._xsheet_shift_cells(ob, [("A", 2), ("A", 6)], -5, duplicate=False)
    check("negative target: refuses", err is not None, True)
    check("negative target: untouched", frames_of(ob, "A"), [2, 6])

    # --- 5. a locked layer refuses before touching anything ---------------------------
    ob = make_gp("locked", [("A", [1, 4])])
    ob.data.layers["A"].lock = True
    _, err = xs._xsheet_shift_cells(ob, [("A", 1)], 3, duplicate=False)
    check("locked layer: refuses", err is not None, True)
    check("locked layer: untouched", frames_of(ob, "A"), [1, 4])

    # --- 6. block duplicate keeps the sources ------------------------------------------
    ob = make_gp("blockdup", [("A", [1, 3])])
    moved, err = xs._xsheet_shift_cells(ob, [("A", 1), ("A", 3)], 10, duplicate=True)
    check("block duplicate: no error", err, None)
    check("block duplicate: sources kept", frames_of(ob, "A"), [1, 3, 11, 13])
    check("block duplicate: new keys", sorted(moved), [("A", 11), ("A", 13)])

    # A duplicate landing on a source is refused (the source stays, so it IS occupied).
    ob = make_gp("dupclash", [("A", [1, 3])])
    _, err = xs._xsheet_shift_cells(ob, [("A", 1)], 2, duplicate=True)
    check("duplicate onto a source: refuses", err is not None, True)
    check("duplicate onto a source: untouched", frames_of(ob, "A"), [1, 3])

    # --- 7. delta 0 is a no-op ---------------------------------------------------------
    ob = make_gp("nodelta", [("A", [1, 2])])
    moved, err = xs._xsheet_shift_cells(ob, [("A", 1)], 0, duplicate=False)
    check("zero delta: no-op", (moved, err), ([], None))

    # --- 8. the live selection prunes what no longer exists ----------------------------
    ob = make_gp("prune", [("A", [1, 5])])
    xs._xsheet_selected.clear()
    xs._xsheet_selected.update({("A", 1), ("A", 99), ("Ghost", 1)})
    check("live selection prunes", xs._xsheet_live_selection(ob), {"A": [1]})

    # --- 9. block delete removes every selected cell ----------------------------------
    ob = make_gp("blockdel", [("A", [1, 5, 9]), ("B", [2, 6])])
    bpy.context.view_layer.objects.active = ob
    xs._xsheet_selected.clear()
    xs._xsheet_selected.update({("A", 5), ("A", 9), ("B", 2)})
    op = FakeOp()
    result = xs._xsheet_delete_selection(op, bpy.context)
    check("block delete: finished", result, {'FINISHED'})
    check("block delete: A", frames_of(ob, "A"), [1])
    check("block delete: B", frames_of(ob, "B"), [6])
    check("block delete: selection emptied", xs._xsheet_selected, set())

    # --- 10. block delete skips locked layers and says so ------------------------------
    ob = make_gp("dellocked", [("A", [1, 5]), ("B", [1, 5])])
    bpy.context.view_layer.objects.active = ob
    ob.data.layers["B"].lock = True
    xs._xsheet_selected.clear()
    xs._xsheet_selected.update({("A", 5), ("B", 5)})
    op = FakeOp()
    xs._xsheet_delete_selection(op, bpy.context)
    check("locked delete: unlocked layer emptied", frames_of(ob, "A"), [1])
    check("locked delete: locked layer kept", frames_of(ob, "B"), [1, 5])
    check("locked delete: warns", [k for k, _ in op.reports], ['WARNING'])
    check("locked delete: keeps the locked cell selected", xs._xsheet_selected, {("B", 5)})

    # --- 11. box select: rectangle -> cells ------------------------------------------------
    # Synthetic geometry: 10 px per frame starting at the name column, rows 20 px from `top`.
    ob = make_gp("boxsel", [("A", [1, 3, 6, 9]), ("B", [2, 5, 9]), ("C", [4])])
    layers = list(ob.data.layers)
    name_w, row_h, top = 150.0, 20.0, 100.0

    def frame_at(x):
        return (x - name_w) / 10.0 + 1.0

    def box(x_from, x_to, y_from, y_to):
        return sorted(xs._xsheet_cells_in_box(layers, x_from, x_to, y_from, y_to,
                                              name_w, row_h, top, frame_at))

    # Row 0 only (y from top-20 to top), frames 3..6.
    check("box: one row", box(name_w + 20, name_w + 59, top - 19, top - 1),
          [("A", 3), ("A", 6)])
    # Rows 0..1, frames 1..5.
    check("box: two rows", box(name_w + 1, name_w + 49, top - 39, top - 1),
          [("A", 1), ("A", 3), ("B", 2), ("B", 5)])
    # Corners dragged bottom-right -> top-left select the same cells.
    check("box: reversed corners", box(name_w + 59, name_w + 20, top - 1, top - 19),
          [("A", 3), ("A", 6)])
    # A box entirely inside the name column selects nothing.
    check("box: name column only", box(0, name_w - 5, top - 19, top - 1), [])
    # A box starting over the name column still catches the cells to its right.
    check("box: clamped to the cell area", box(10, name_w + 29, top - 19, top - 1),
          [("A", 1), ("A", 3)])
    # A box below the last row is empty, not an index error.
    check("box: below the last row", box(name_w + 1, name_w + 99, 0, 20), [])
    # A box taller than the sheet reaches every row and stops at the last layer (frames 4..5
    # here, so layer A — keyed at 1/3/6/9 — correctly contributes nothing).
    check("box: past the last row", box(name_w + 30, name_w + 45, 0, top - 1),
          [("B", 5), ("C", 4)])

    # --- 12. Shift+click toggling one cell -------------------------------------------------
    ob = make_gp("toggle", [("A", [1, 5])])
    xs._xsheet_selected.clear()
    check("toggle: adds", (xs._xsheet_toggle_selected(ob, 0, 5), xs._xsheet_selected),
          (True, {("A", 5)}))
    check("toggle: removes", (xs._xsheet_toggle_selected(ob, 0, 5), xs._xsheet_selected),
          (True, set()))
    check("toggle: refuses an empty cell", xs._xsheet_toggle_selected(ob, 0, 4), False)
    check("toggle: refuses a bad row", xs._xsheet_toggle_selected(ob, 7, 5), False)
    check("toggle: refuses no row", xs._xsheet_toggle_selected(ob, None, 5), False)

    # --- 13. nothing selected is a refusal, not a crash --------------------------------
    xs._xsheet_selected.clear()
    op = FakeOp()
    check("empty selection: cancelled",
          xs._xsheet_delete_selection(op, bpy.context), {'CANCELLED'})

    print("\n%s" % ("FAILED: %s" % ", ".join(FAILED) if FAILED else "ALL PASS"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
