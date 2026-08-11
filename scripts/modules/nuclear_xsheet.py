# SPDX-FileCopyrightText: 2026 Rapadura Atômica
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Nuclear Xsheet — the Toon Boom-style timeline, shared by every app template.

Read-only GPU render over the bottom Dope Sheet plus its interaction operators: a grid of
per-layer × per-frame cells, where a filled cell is an exposed drawing, a bright square marks
the keyframe start and a "hold" bar spans held frames. Frame ruler + playhead + layer-name
column; the native dope sheet underneath is hidden by an opaque background.

This used to live inside the Nuclear application template (Seam 7). It was extracted here so
the 2D Animation and Storyboarding templates get the SAME timeline without copying ~600 lines
— the templates only call `register()` / `unregister()` and `apply_timeline_layout()`.

What is deliberately NOT here: the Nuclear transport header (+ KF / - KF, play controls, frame
fields). That is Nuclear's own header override and stays in its template; the other templates
keep their native dope-sheet header and footer, so they gain the Xsheet and nothing else.

No `bpy` import at module scope beyond the usual — but note this module DOES import bpy, so it
is a UI module, not a pure-data one.
"""

import bpy

# GPU/text modules. Guarded so a build without the gpu module still loads the template (the
# Xsheet just won't draw).
try:
    import gpu
    import blf
    from gpu_extras.batch import batch_for_shader
    _GPU_OK = True
except Exception:
    _GPU_OK = False


# --------------------------------------------------------------------------------------
# State, geometry and editing helpers
# --------------------------------------------------------------------------------------

_xsheet_handle = None
# Active drag (T4.1): {"row", "from", "to", "dup", "cells"} while moving/duplicating, else
# None. "cells" is the list of (layer_name, frame) the drag carries — one entry for a plain
# grab, the whole selection when the grabbed cell belongs to it (T5.2).
_xsheet_drag = None
# T5.1 — selected keyframes tracked as (layer_name, frame_number) tuples.  We keep a
# pure-Python set so selection works independently of the GP v3 RNA write path (the
# draw handler reads this set, the click/toggle operators write to it).
_xsheet_selected = set()
# Set once the draw handler has reported a failure, so the console gets one traceback and not
# one per redraw.
_xsheet_draw_failed = False
# T5.2 — box select in progress: {"x0","y0","x1","y1","armed"} while B is running, else None.
# "armed" is False between pressing B and pressing the mouse button (nothing to draw yet).
_xsheet_box = None

# Layout + palette (navy theme).
_XS = {
    "name_w": 150.0, "ruler_h": 20.0, "row_h": 22.0,
    "cell_min": 8.0, "cell_max": 22.0, "frame_cap": 400,
    "bg": (0.07, 0.07, 0.13, 1.0), "panel": (0.11, 0.11, 0.19, 1.0),
    "grid": (0.20, 0.20, 0.30, 1.0), "hold": (0.30, 0.34, 0.55, 1.0),
    "key": (0.38, 0.30, 0.72, 1.0), "play": (0.95, 0.55, 0.20, 1.0),
    "text": (0.90, 0.90, 0.96, 1.0),
    "active_row": (0.18, 0.16, 0.30, 1.0), "frame_col": (0.16, 0.16, 0.26, 1.0),
    "vis_on": (0.50, 0.80, 0.55, 1.0), "lock_on": (0.92, 0.62, 0.28, 1.0),
    "state_off": (0.24, 0.24, 0.30, 1.0),
    "grid5": (0.30, 0.30, 0.44, 1.0), "ghost": (0.95, 0.55, 0.20, 0.55),
    "num": (0.08, 0.06, 0.14, 1.0),
    # T5.1 — selection is an OUTLINE, not a fill: the cell keeps its "key" purple so the
    # drawing number stays readable, and the bright edge reads over key, hold and the
    # active-row highlight alike (Harmony does the same).
    "sel_edge": (1.0, 1.0, 1.0, 1.0), "sel_edge_w": 2.0,
    "box": (1.0, 1.0, 1.0, 0.85),
    # Pixels of travel below which a Shift gesture counts as a click, not a box drag.
    "drag_slop": 4.0,
}


def _xsheet_layout(region, scene):
    # Geometry shared by the draw handler and the click operator. X is mapped through the
    # NATIVE view2d (region.view2d) so our cells/playhead align exactly with the native frame
    # ruler and the native current-frame indicator (which is drawn on top and can't be
    # covered). This is the real fix for the "needle ahead" mismatch — one coordinate system,
    # the native one — and gives native scroll/zoom of the frame range for free.
    rw, rh = region.width, region.height
    name_w = _XS["name_w"]
    ruler_h = _XS["ruler_h"]
    row_h = _XS["row_h"]
    top = rh - ruler_h
    v2d = region.view2d
    f_lo = int(v2d.region_to_view(name_w, 0.0)[0])
    f_hi = int(v2d.region_to_view(rw, 0.0)[0]) + 2
    # Clamp the visible span so a zoomed-out view never iterates a huge range.
    if f_hi - f_lo > _XS["frame_cap"]:
        f_hi = f_lo + _XS["frame_cap"]
    return rw, rh, name_w, ruler_h, row_h, top, f_lo, f_hi


def _xsheet_fx(region, f):
    # Frame number -> region pixel X via the native view2d.
    return region.view2d.view_to_region(float(f), 0.0, clip=False)[0]


def _xsheet_poll(context):
    # Shared poll for the Xsheet operators: only act inside our active GP Xsheet.
    area = context.area
    if area is None or area.type != 'DOPESHEET_EDITOR':
        return False
    if getattr(area.spaces.active, "mode", None) != 'GPENCIL':
        return False
    region = context.region
    ob = context.active_object
    return (ob is not None and ob.type == 'GREASEPENCIL'
            and _xsheet_handle is not None
            and region is not None and region.type == 'WINDOW')


def _xsheet_hit(context, event):
    # Map a mouse event to ('frame', f, row) / ('vis'|'lock'|'layer', row) / None, using the
    # same geometry + native view2d as the draw (so clicks land on the right cell).
    region = context.region
    ob = context.active_object
    layers = list(ob.data.layers)
    _, _, name_w, _, row_h, top, _, _ = _xsheet_layout(region, context.scene)
    mx, my = event.mouse_region_x, event.mouse_region_y
    row = None
    if my <= top:
        ri = int((top - my) // row_h)
        if 0 <= ri < len(layers):
            row = ri
    if mx < name_w:
        if row is None:
            return None
        sq, vis_x, lock_x = 10.0, name_w - 34.0, name_w - 18.0
        yc = top - row * row_h - row_h * 0.5
        if vis_x <= mx <= vis_x + sq and yc - sq / 2 <= my <= yc + sq / 2:
            return ('vis', row)
        if lock_x <= mx <= lock_x + sq and yc - sq / 2 <= my <= yc + sq / 2:
            return ('lock', row)
        return ('layer', row)
    f = int(region.view2d.region_to_view(mx, 0.0)[0])
    return ('frame', f, row)


def _xsheet_draw_error_log():
    """Where a draw failure is recorded, so it survives a session launched from the desktop."""
    import os
    import tempfile
    # NOT bpy.app.tempdir: that is a per-session directory Blender deletes on quit, so the
    # report would vanish exactly when someone goes looking for it.
    return os.path.join(tempfile.gettempdir(), "nuclear_xsheet_draw_error.log")


def _xsheet_report_draw_error(where):
    """Report a swallowed draw error once per session, to the console AND to a log file.

    A draw handler that dies half-way leaves a plausible-looking Xsheet with everything after
    the failure simply absent (grid, playhead, layer names, drawing numbers) — it reads as "the
    UI went blank" with nothing to go on. `pass` alone made that undiagnosable, and a session
    started from the desktop launcher has no console to print to, hence the file.
    """
    global _xsheet_draw_failed
    if _xsheet_draw_failed:
        return
    _xsheet_draw_failed = True
    import traceback
    text = "Nuclear Xsheet: draw failed in %s, overlay is incomplete:\n%s" % (
        where, traceback.format_exc())
    print(text)
    try:
        with open(_xsheet_draw_error_log(), "w", encoding="utf-8") as fh:
            fh.write(text)
    except Exception:
        pass


def _xsheet_toggle_selected(ob, row, f):
    """Add/remove one cell from the selection. Only keyframe cells can be selected."""
    if row is None:
        return False
    layers = list(ob.data.layers)
    if not 0 <= row < len(layers):
        return False
    layer = layers[row]
    if not any(fr.frame_number == f for fr in layer.frames):
        return False
    key = (layer.name, f)
    if key in _xsheet_selected:
        _xsheet_selected.discard(key)
    else:
        _xsheet_selected.add(key)
    return True


def _xsheet_cells_in_box(layers, x0, x1, y0, y1, name_w, row_h, top, frame_at):
    """Every (layer_name, frame) keyframe cell inside a pixel rectangle.

    Split out of the operator so the rectangle → cells mapping is testable without a region:
    `frame_at` is the pixel-X → frame mapping (the native view2d in the real editor), `layers`
    the rows top to bottom. Corners may come in any order — the box is whatever the animator
    dragged, in whichever direction.
    """
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    # The name column is not a cell area; clamp so a box started over it still works.
    x0 = max(x0, name_w)
    if x1 <= name_w:
        return []
    f_lo = int(frame_at(x0))
    f_hi = int(frame_at(x1))
    # Rows run downwards from `top`; a box entirely below the last row yields an empty range.
    r_lo = int((top - min(y1, top)) // row_h)
    r_hi = int((top - max(y0, 0.0)) // row_h)
    out = []
    for ri in range(max(r_lo, 0), min(r_hi, len(layers) - 1) + 1):
        layer = layers[ri]
        for fr in layer.frames:
            if f_lo <= fr.frame_number <= f_hi:
                out.append((layer.name, fr.frame_number))
    return out


def _xsheet_select_box(context, box, extend):
    """Apply a dragged rectangle to the selection."""
    region = context.region
    layers = list(context.active_object.data.layers)
    _, _, name_w, _, row_h, top, _, _ = _xsheet_layout(region, context.scene)
    cells = _xsheet_cells_in_box(
        layers, box["x0"], box["x1"], box["y0"], box["y1"], name_w, row_h, top,
        lambda x: region.view2d.region_to_view(x, 0.0)[0])
    if not extend:
        _xsheet_selected.clear()
    _xsheet_selected.update(cells)
    return cells


def _xsheet_live_selection(ob):
    # The selection, pruned to what still exists: {layer_name: sorted([frame, ...])}. The set
    # is keyed by name and survives across redraws, so a deleted layer/frame can linger in it.
    out = {}
    for layer in ob.data.layers:
        frames = sorted(fr.frame_number for fr in layer.frames
                        if (layer.name, fr.frame_number) in _xsheet_selected)
        if frames:
            out[layer.name] = frames
    return out


def _xsheet_shift_cells(ob, cells, delta, duplicate):
    # Move (or copy) every (layer_name, frame) in `cells` by `delta`, all or nothing.
    #
    # All-or-nothing matters: a partially applied block drag silently rearranges the
    # animator's timing, and there is no way to see which half moved. So we validate every
    # target first and refuse the whole gesture with a message naming the reason.
    #
    # Returns (moved_cells, error_message). On success error_message is None and moved_cells
    # holds the new (layer_name, frame) keys so the caller can keep the selection on them.
    if not delta:
        return [], None
    by_layer = {}
    for (lname, f) in cells:
        by_layer.setdefault(lname, []).append(f)
    layers = {lyr.name: lyr for lyr in ob.data.layers}

    for lname, frames in by_layer.items():
        layer = layers.get(lname)
        if layer is None:
            return [], "camada '%s' não existe mais" % lname
        if layer.lock:
            return [], "camada '%s' está travada" % lname
        existing = {fr.frame_number for fr in layer.frames}
        moving = set(frames) if not duplicate else set()
        for f in frames:
            dst = f + delta
            if dst < 0:
                return [], "o bloco sairia do início da cena"
            # A cell the block itself is vacating is a legal target; anything else is not.
            if dst in existing and dst not in moving:
                return [], "frame %d da camada '%s' já está ocupado" % (dst, lname)

    moved = []
    for lname, frames in by_layer.items():
        layer = layers[lname]
        # Walk away from the destination so a source is never overwritten before it is read:
        # moving right, handle the rightmost first; moving left, the leftmost first.
        for f in sorted(frames, reverse=delta > 0):
            dst = f + delta
            try:
                if duplicate:
                    layer.frames.copy(f, dst)
                else:
                    layer.frames.move(f, dst)
            except Exception as exc:
                return moved, str(exc)
            moved.append((lname, dst))
    ob.data.update_tag()
    return moved, None


def _xsheet_delete_selection(op, context):
    # Remove every selected keyframe. Locked layers are skipped (never silently): they are
    # named in the report, so a partial delete is always accounted for.
    ob = context.active_object
    live = _xsheet_live_selection(ob)
    if not live:
        op.report({'WARNING'}, "Nada selecionado")
        return {'CANCELLED'}
    layers = {lyr.name: lyr for lyr in ob.data.layers}
    removed, locked, failed = 0, [], []
    for lname, frames in live.items():
        layer = layers[lname]
        if layer.lock:
            locked.append(lname)
            continue
        for f in frames:
            try:
                layer.frames.remove(f)
            except Exception as exc:
                failed.append(str(exc))
                continue
            _xsheet_selected.discard((lname, f))
            removed += 1
    if removed:
        ob.data.update_tag()
    if locked:
        op.report({'WARNING'}, "Camadas travadas ignoradas: %s" % ", ".join(sorted(locked)))
    elif failed:
        op.report({'WARNING'}, "Exposição: {:s}".format(failed[0]))
    if context.area:
        context.area.tag_redraw()
    return {'FINISHED'} if removed else {'CANCELLED'}


def _xsheet_exposed(layer, f_start, f_end):
    # frame -> 'key' (drawing starts here) or 'hold' (previous drawing held).
    keys = sorted(f.frame_number for f in layer.frames)
    out = {}
    for i, k in enumerate(keys):
        nxt = keys[i + 1] if i + 1 < len(keys) else f_end + 1
        lo = max(k, f_start)
        hi = min(nxt, f_end + 1)
        for f in range(lo, hi):
            out[f] = 'key' if f == k else 'hold'
    return out


def _xsheet_draw():
    if not _GPU_OK:
        return
    try:
        area = bpy.context.area
        region = bpy.context.region
        if area is None or area.type != 'DOPESHEET_EDITOR':
            return
        if region is None or region.type != 'WINDOW':
            return
        space = area.spaces.active
        if getattr(space, "mode", None) != 'GPENCIL':
            return
        ob = bpy.context.active_object
        if ob is None or ob.type != 'GREASEPENCIL':
            return
        layers = list(ob.data.layers)
        if not layers:
            return
        scene = bpy.context.scene
        rw, rh, name_w, ruler_h, row_h, top, f_lo, f_hi = _xsheet_layout(region, scene)

        def fx(f):
            return _xsheet_fx(region, f)

        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')

        def fill(rects, color):
            if not rects:
                return
            verts = []
            for (x0, y0, x1, y1) in rects:
                verts += [(x0, y0), (x1, y0), (x1, y1), (x0, y0), (x1, y1), (x0, y1)]
            batch = batch_for_shader(shader, 'TRIS', {"pos": verts})
            shader.uniform_float("color", color)
            batch.draw(shader)

        def lines(segs, color):
            if not segs:
                return
            verts = []
            for (x0, y0, x1, y1) in segs:
                verts += [(x0, y0), (x1, y1)]
            batch = batch_for_shader(shader, 'LINES', {"pos": verts})
            shader.uniform_float("color", color)
            batch.draw(shader)

        def outline(rects, color, width=1.0):
            if not rects:
                return
            gpu.state.line_width_set(width)
            segs = []
            for (x0, y0, x1, y1) in rects:
                segs += [(x0, y0, x1, y0), (x1, y0, x1, y1),
                         (x1, y1, x0, y1), (x0, y1, x0, y0)]
            lines(segs, color)
            gpu.state.line_width_set(1.0)

        def clipx(x):
            return x if x > name_w else name_w

        # Backgrounds (cover the native dope sheet keyframes/area; leave the native ruler +
        # current-frame indicator visible at top — they now align with our view2d-mapped cells).
        fill([(0, 0, rw, top)], _XS["bg"])
        fill([(0, 0, name_w, rh)], _XS["panel"])

        cf = scene.frame_current

        # T2 — active layer row highlight + current frame column highlight.
        active_layer = getattr(ob.data.layers, "active", None)
        active_idx = next((i for i, lyr in enumerate(layers) if lyr == active_layer), None)
        if active_idx is not None:
            ay1 = top - active_idx * row_h
            fill([(name_w, ay1 - row_h, rw, ay1)], _XS["active_row"])
        cfx0, cfx1 = fx(cf), fx(cf + 1)
        if cfx1 > name_w:
            fill([(clipx(cfx0), 0, max(cfx1, name_w + 1), top)], _XS["frame_col"])

        # Exposure cells (X via native view2d → aligned with the native ruler/indicator).
        # key_cells collects (x_left, y_center, drawing_number, cell_width) for T5 numbering.
        hold_r, key_r, key_sel_r, key_cells = [], [], [], []
        for ri, layer in enumerate(layers):
            y1 = top - ri * row_h
            y0 = y1 - row_h
            keys_sorted = sorted(fr.frame_number for fr in layer.frames)
            kindex = {k: i + 1 for i, k in enumerate(keys_sorted)}
            # T5.1 — selected keyframes for this layer (pure-Python set, no RNA write dependency).
            selected_set = {fn for (ln, fn) in _xsheet_selected if ln == layer.name}
            for f, kind in _xsheet_exposed(layer, f_lo, f_hi).items():
                x0, x1 = fx(f), fx(f + 1)
                if x1 <= name_w:
                    continue
                xc0 = clipx(x0)
                rect = (xc0 + 1, y0 + 2, x1 - 1, y1 - 2)
                if kind == 'key':
                    key_r.append(rect)
                    # T5.1 — selection is drawn as an outline on top of the normal cell.
                    if f in selected_set:
                        key_sel_r.append(rect)
                    key_cells.append((xc0, (y0 + y1) * 0.5, kindex.get(f, 0), x1 - xc0))
                else:
                    hold_r.append(rect)
        fill(hold_r, _XS["hold"])
        fill(key_r, _XS["key"])

        # Selection outline and drag ghosts depend on interaction state that outlives a single
        # redraw (_xsheet_selected, _xsheet_drag). They are guarded on their own so a surprise
        # in that state costs at most its own decoration — never the grid, the playhead, the
        # layer names and the drawing numbers that come after it.
        try:
            outline(key_sel_r, _XS["sel_edge"], _XS["sel_edge_w"])

            # T4.1/T5.2 — ghost preview while dragging: one cell per carried keyframe, all
            # shifted by the same delta, so a multi-cell drag shows where the block will land.
            if _xsheet_drag is not None:
                delta = _xsheet_drag["to"] - _xsheet_drag["from"]
                row_of = {lyr.name: i for i, lyr in enumerate(layers)}
                ghosts = []
                for (lname, f) in _xsheet_drag.get("cells", ()):
                    ri = row_of.get(lname)
                    if ri is None:
                        continue
                    gy1 = top - ri * row_h
                    gx0, gx1 = fx(f + delta), fx(f + delta + 1)
                    if gx1 > name_w:
                        ghosts.append((clipx(gx0) + 1, gy1 - row_h + 2, gx1 - 1, gy1 - 2))
                fill(ghosts, _XS["ghost"])
        except Exception:
            _xsheet_report_draw_error("selection/drag decoration")
            gpu.state.line_width_set(1.0)

        # Grid: per-frame lines + emphasized line every 5 frames + per-layer rows.
        segs, emph = [], []
        for f in range(f_lo, f_hi + 1):
            x = fx(f)
            if x >= name_w:
                (emph if f % 5 == 0 else segs).append((x, 0, x, top))
        for ri in range(len(layers) + 1):
            y = top - ri * row_h
            segs.append((name_w, y, rw, y))
        lines(segs, _XS["grid"])
        lines(emph, _XS["grid5"])

        # Playhead (view2d → coincides with the native indicator).
        px = fx(cf)
        if px >= name_w:
            lines([(px, 0, px, top)], _XS["play"])

        # T2 — visibility / lock state squares in the name column (clickable in T3).
        sq = 10.0
        vis_x = name_w - 34.0
        lock_x = name_w - 18.0
        vis_on, vis_off, lock_on, lock_off = [], [], [], []
        for ri, layer in enumerate(layers):
            yc = top - ri * row_h - row_h * 0.5
            r_vis = (vis_x, yc - sq / 2, vis_x + sq, yc + sq / 2)
            r_lock = (lock_x, yc - sq / 2, lock_x + sq, yc + sq / 2)
            (vis_off if layer.hide else vis_on).append(r_vis)
            (lock_on if layer.lock else lock_off).append(r_lock)
        fill(vis_on, _XS["vis_on"])
        fill(vis_off, _XS["state_off"])
        fill(lock_on, _XS["lock_on"])
        fill(lock_off, _XS["state_off"])

        # T5.2 — box select rubber band (guarded for the same reason as the selection above).
        try:
            if _xsheet_box is not None and _xsheet_box.get("armed"):
                bx0, bx1 = sorted((_xsheet_box["x0"], _xsheet_box["x1"]))
                by0, by1 = sorted((_xsheet_box["y0"], _xsheet_box["y1"]))
                outline([(bx0, by0, bx1, by1)], _XS["box"], 1.0)
        except Exception:
            _xsheet_report_draw_error("box select band")
            gpu.state.line_width_set(1.0)

        gpu.state.blend_set('NONE')

        # Layer names in the column (frame numbers come from the native ruler now).
        fid = 0
        blf.size(fid, 11)
        blf.color(fid, *_XS["text"])
        for ri, layer in enumerate(layers):
            blf.position(fid, 6, top - ri * row_h - row_h * 0.7, 0)
            blf.draw(fid, layer.name)

        # T5 — drawing number inside each keyframe cell (when the cell is wide enough).
        blf.size(fid, 10)
        blf.color(fid, *_XS["num"])
        for (cx, cy, num, cwidth) in key_cells:
            if cwidth >= 13.0 and num:
                blf.position(fid, cx + 3, cy - 5, 0)
                blf.draw(fid, str(num))
    except Exception:
        # Never let a draw error break the UI; best-effort overlay.
        _xsheet_report_draw_error("overlay")


def _enable_xsheet():
    global _xsheet_handle
    if _GPU_OK and _xsheet_handle is None:
        _xsheet_handle = bpy.types.SpaceDopeSheetEditor.draw_handler_add(
            _xsheet_draw, (), 'WINDOW', 'POST_PIXEL',
        )


def _disable_xsheet():
    global _xsheet_handle, _xsheet_drag, _xsheet_box
    _xsheet_selected.clear()
    _xsheet_drag = None
    _xsheet_box = None
    if _xsheet_handle is not None:
        try:
            bpy.types.SpaceDopeSheetEditor.draw_handler_remove(_xsheet_handle, 'WINDOW')
        except Exception:
            pass
        _xsheet_handle = None


# Keymap that routes LEFTMOUSE in the Dope Sheet to the Xsheet operator (poll-gated, so it
# only fires inside our GP Xsheet; otherwise the event falls through to native).
_xsheet_keymaps = []


def _register_xsheet_keymap():
    wm = bpy.context.window_manager
    kc = getattr(wm.keyconfigs, "addon", None)
    if kc is None:
        return
    km = kc.keymaps.new(name='Dopesheet', space_type='DOPESHEET_EDITOR')
    kmi = km.keymap_items.new("nuclear.xsheet_click", 'LEFTMOUSE', 'PRESS')
    _xsheet_keymaps.append((km, kmi))
    # T5.1 — Shift+LEFTMOUSE adds/removes a cell from the selection. It needs its OWN keymap
    # item: a binding created with shift unset means "Shift must be RELEASED", so the operator's
    # event.shift branch was unreachable and Shift+click fell through to the native dope sheet.
    kmi1b = km.keymap_items.new("nuclear.xsheet_click", 'LEFTMOUSE', 'PRESS', shift=True)
    _xsheet_keymaps.append((km, kmi1b))
    # T4 — Ctrl+LEFTMOUSE toggles a cell's exposure (create/delete drawing).
    kmi2 = km.keymap_items.new("nuclear.xsheet_toggle", 'LEFTMOUSE', 'PRESS', ctrl=True)
    _xsheet_keymaps.append((km, kmi2))
    # T4.1 — Alt+drag = move exposure; Shift+Alt+drag = duplicate exposure.
    kmi3 = km.keymap_items.new("nuclear.xsheet_drag", 'LEFTMOUSE', 'PRESS', alt=True)
    kmi3.properties.duplicate = False
    _xsheet_keymaps.append((km, kmi3))
    kmi4 = km.keymap_items.new("nuclear.xsheet_drag", 'LEFTMOUSE', 'PRESS', shift=True, alt=True)
    kmi4.properties.duplicate = True
    _xsheet_keymaps.append((km, kmi4))
    # T5.2 — X / DEL = delete the selected cells.
    #
    # Box select lives on **Shift+drag** (NUCLEAR_OT_xsheet_click), not here: B is claimed by
    # `action.select_box` in the active Nuclear keyconfig, which wins over this addon item, so a
    # B binding does not reach us. B is still registered for whoever runs another keyconfig —
    # it is the same gesture either way — but Shift+drag is the one that is guaranteed to work.
    kmi5 = km.keymap_items.new("nuclear.xsheet_box_select", 'B', 'PRESS')
    _xsheet_keymaps.append((km, kmi5))
    for key in ('X', 'DEL'):
        kmi6 = km.keymap_items.new("nuclear.xsheet_delete_selected", key, 'PRESS')
        _xsheet_keymaps.append((km, kmi6))


def _unregister_xsheet_keymap():
    for km, kmi in _xsheet_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _xsheet_keymaps.clear()


# ----------------------------------------------------------------------------------
# Operators (interaction: click/scrub, toggle exposure, move/duplicate, box select, delete)
# ----------------------------------------------------------------------------------

class NUCLEAR_OT_xsheet_click(bpy.types.Operator):
    # T3 — Xsheet interaction. Intercepts LEFTMOUSE in the bottom Dope Sheet (while the
    # Nuclear Xsheet is active) and maps the click with the SAME geometry the draw handler
    # uses (_xsheet_layout) — so the click→frame mapping matches the visual grid (fixes the
    # "needle ahead" mismatch caused by the native view2d). Click a cell → set frame + active
    # layer; click the vis/lock squares → toggle; click a name → activate layer. Drag = scrub.
    bl_idname = "nuclear.xsheet_click"
    bl_label = "Xsheet Click"

    @classmethod
    def poll(cls, context):
        return _xsheet_poll(context)

    def invoke(self, context, event):
        ob = context.active_object
        layers = list(ob.data.layers)
        hit = _xsheet_hit(context, event)
        if hit is None:
            return {'PASS_THROUGH'}
        kind = hit[0]
        if kind == 'vis':
            layers[hit[1]].hide = not layers[hit[1]].hide
        elif kind == 'lock':
            layers[hit[1]].lock = not layers[hit[1]].lock
        elif kind == 'layer':
            try:
                ob.data.layers.active = layers[hit[1]]
            except Exception:
                pass
        elif kind == 'frame':
            f, row = hit[1], hit[2]
            # T5.2 — Shift takes over the gesture entirely: press and release in place toggles
            # the cell, press and DRAG box-selects. Both live here, on the LEFTMOUSE binding,
            # because that is the event path this space actually delivers to us — B is claimed
            # by `action.select_box` in the active Nuclear keyconfig (see _register_xsheet_keymap).
            if event.shift:
                global _xsheet_box
                mx, my = event.mouse_region_x, event.mouse_region_y
                _xsheet_box = {"x0": mx, "y0": my, "x1": mx, "y1": my, "armed": True}
                self._shift_anchor = (mx, my, f, row)
                context.window_manager.modal_handler_add(self)
                return {'RUNNING_MODAL'}
            # T5.1 — plain click selects just this cell (a hold/empty cell deselects, as
            # everywhere else in Blender — otherwise a stale selection keeps catching later
            # block drags).
            if row is not None:
                layer = layers[row]
                if any(fr.frame_number == f for fr in layer.frames):
                    _xsheet_selected.clear()
                    _xsheet_selected.add((layer.name, f))
                else:
                    _xsheet_selected.clear()
            context.scene.frame_current = f
            if row is not None:
                try:
                    ob.data.layers.active = layers[row]
                except Exception:
                    pass
            if context.area:
                context.area.tag_redraw()
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}

    # Set while a Shift gesture is in flight: (anchor_x, anchor_y, frame, row).
    _shift_anchor = None

    def modal(self, context, event):
        if self._shift_anchor is not None:
            return self._modal_shift(context, event)
        if event.type == 'MOUSEMOVE':
            hit = _xsheet_hit(context, event)
            if hit and hit[0] == 'frame':
                context.scene.frame_current = hit[1]
                if context.area:
                    context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            return {'FINISHED'}
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def _modal_shift(self, context, event):
        # Shift+press already happened; the release decides which gesture it was. Staying still
        # means "toggle this cell", moving means "box select" — so the animator does not have to
        # pick the gesture up front, and a shaky hand on a toggle does not select a stray block.
        global _xsheet_box
        if _xsheet_box is None:
            self._shift_anchor = None
            return {'CANCELLED'}
        ax, ay, af, arow = self._shift_anchor
        if event.type == 'MOUSEMOVE':
            _xsheet_box.update({"x1": event.mouse_region_x, "y1": event.mouse_region_y})
            if context.area:
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            box = _xsheet_box
            _xsheet_box = None
            self._shift_anchor = None
            travel = max(abs(box["x1"] - ax), abs(box["y1"] - ay))
            if travel <= _XS["drag_slop"]:
                _xsheet_toggle_selected(context.active_object, arow, af)
            else:
                # Shift means "add to what I have" for the box just as it does for a click.
                _xsheet_select_box(context, box, extend=True)
            if context.area:
                context.area.tag_redraw()
            return {'FINISHED'}
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            _xsheet_box = None
            self._shift_anchor = None
            if context.area:
                context.area.tag_redraw()
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


class NUCLEAR_OT_xsheet_toggle(bpy.types.Operator):
    # T4 — Ctrl+click a cell to toggle its exposure (drawing): create a blank keyframe if the
    # cell is empty, delete it if a keyframe is there. Works per clicked layer+frame via the
    # data API (mode-independent), with undo.
    bl_idname = "nuclear.xsheet_toggle"
    bl_label = "Toggle Exposure"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _xsheet_poll(context)

    def invoke(self, context, event):
        hit = _xsheet_hit(context, event)
        if not hit or hit[0] != 'frame':
            return {'PASS_THROUGH'}
        ob = context.active_object
        layers = list(ob.data.layers)
        f, row = hit[1], hit[2]
        layer = layers[row] if row is not None else getattr(ob.data.layers, "active", None)
        if layer is None:
            return {'CANCELLED'}
        # T5.2 — Ctrl+clicking a cell that is part of the selection clears the whole selection
        # instead of that single cell: the gesture acts on what is highlighted.
        if (layer.name, f) in _xsheet_selected and len(_xsheet_selected) > 1:
            return _xsheet_delete_selection(self, context)
        if layer.lock:
            self.report({'WARNING'}, "Camada travada")
            return {'CANCELLED'}
        nums = [fr.frame_number for fr in layer.frames]
        try:
            if f in nums:
                layer.frames.remove(f)
            else:
                layer.frames.new(f)
        except Exception as e:
            self.report({'WARNING'}, "Exposição: {:s}".format(str(e)))
            return {'CANCELLED'}
        try:
            ob.data.layers.active = layer
        except Exception:
            pass
        context.scene.frame_current = f
        ob.data.update_tag()
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class NUCLEAR_OT_xsheet_drag(bpy.types.Operator):
    # T4.1 — Alt+drag a keyframe to MOVE it (layer.frames.move); Shift+Alt+drag to DUPLICATE
    # it (layer.frames.copy). Both preserve the drawing. Ghost cells preview the target
    # frames while dragging (_xsheet_drag, read by the draw handler).
    # T5.2 — grabbing a cell that belongs to the selection drags the WHOLE selection, across
    # layers, keeping the relative spacing; grabbing anything else drags that cell alone.
    bl_idname = "nuclear.xsheet_drag"
    bl_label = "Move/Duplicate Exposure"
    bl_options = {'REGISTER', 'UNDO'}

    duplicate: bpy.props.BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        return _xsheet_poll(context)

    def invoke(self, context, event):
        global _xsheet_drag
        hit = _xsheet_hit(context, event)
        if not hit or hit[0] != 'frame':
            return {'PASS_THROUGH'}
        ob = context.active_object
        layers = list(ob.data.layers)
        f, row = hit[1], hit[2]
        if row is None:
            return {'PASS_THROUGH'}
        layer = layers[row]
        if layer.lock:
            self.report({'WARNING'}, "Camada travada")
            return {'CANCELLED'}
        if f not in [fr.frame_number for fr in layer.frames]:
            return {'PASS_THROUGH'}  # nothing to grab on an empty cell

        # T5.2 — the grabbed cell decides the scope: inside the selection drags the block,
        # outside it drags just that cell (and takes over the selection, so what moves is
        # always what is highlighted).
        live = _xsheet_live_selection(ob)
        if (layer.name, f) in _xsheet_selected:
            cells = [(lname, fn) for lname, frames in live.items() for fn in frames]
        else:
            cells = [(layer.name, f)]
            _xsheet_selected.clear()
            _xsheet_selected.add((layer.name, f))
        _xsheet_drag = {"row": row, "from": f, "to": f, "dup": self.duplicate, "cells": cells}
        if context.area:
            context.area.tag_redraw()
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        global _xsheet_drag
        if _xsheet_drag is None:
            return {'CANCELLED'}
        if event.type == 'MOUSEMOVE':
            hit = _xsheet_hit(context, event)
            if hit and hit[0] == 'frame':
                _xsheet_drag["to"] = hit[1]
                if context.area:
                    context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            ob = context.active_object
            d = _xsheet_drag
            _xsheet_drag = None
            delta = d["to"] - d["from"]
            moved, err = _xsheet_shift_cells(ob, d["cells"], delta, d["dup"])
            if moved:
                # Keep the selection on the cells the animator can now see at the new frames
                # (on a duplicate the originals stay put, but the copies are the new block).
                if d["dup"]:
                    _xsheet_selected.clear()
                else:
                    # Drop only the sources that really moved, so a refused tail (see
                    # _xsheet_shift_cells) leaves its cells selected where they still are.
                    for (lname, dst) in moved:
                        _xsheet_selected.discard((lname, dst - delta))
                _xsheet_selected.update(moved)
            if err:
                self.report({'WARNING'}, "Exposição: {:s}".format(err))
            context.scene.frame_current = d["to"]
            if context.area:
                context.area.tag_redraw()
            return {'FINISHED'}
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            _xsheet_drag = None
            if context.area:
                context.area.tag_redraw()
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


class NUCLEAR_OT_xsheet_box_select(bpy.types.Operator):
    # T5.2 — B then click-drag a rectangle to select every keyframe cell inside it, across
    # layers (Blender's own box-select convention, so the muscle memory carries over). Hold
    # Shift while releasing to add to the current selection instead of replacing it.
    bl_idname = "nuclear.xsheet_box_select"
    bl_label = "Box Select Cells"

    @classmethod
    def poll(cls, context):
        return _xsheet_poll(context)

    def invoke(self, context, _event):
        global _xsheet_box
        _xsheet_box = {"x0": 0.0, "y0": 0.0, "x1": 0.0, "y1": 0.0, "armed": False}
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        global _xsheet_box
        if _xsheet_box is None:
            return {'CANCELLED'}
        mx, my = event.mouse_region_x, event.mouse_region_y
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            _xsheet_box.update({"x0": mx, "y0": my, "x1": mx, "y1": my, "armed": True})
            return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE' and _xsheet_box["armed"]:
            _xsheet_box.update({"x1": mx, "y1": my})
            if context.area:
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE' and _xsheet_box["armed"]:
            box = _xsheet_box
            _xsheet_box = None
            self._select(context, box, extend=event.shift)
            if context.area:
                context.area.tag_redraw()
            return {'FINISHED'}
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            _xsheet_box = None
            if context.area:
                context.area.tag_redraw()
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def _select(self, context, box, extend):
        _xsheet_select_box(context, box, extend)


class NUCLEAR_OT_xsheet_delete_selected(bpy.types.Operator):
    # T5.2 — X / Delete removes every selected cell at once (the block delete an Xsheet needs;
    # Ctrl+click still handles the single-cell create/delete).
    bl_idname = "nuclear.xsheet_delete_selected"
    bl_label = "Delete Selected Cells"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _xsheet_poll(context) and bool(_xsheet_selected)

    def execute(self, context):
        return _xsheet_delete_selection(self, context)


# --------------------------------------------------------------------------------------
# Public API — what the app templates call
# --------------------------------------------------------------------------------------

_CLASSES = (
    NUCLEAR_OT_xsheet_click,
    NUCLEAR_OT_xsheet_toggle,
    NUCLEAR_OT_xsheet_drag,
    NUCLEAR_OT_xsheet_box_select,
    NUCLEAR_OT_xsheet_delete_selected,
)

# Templates are registered/unregistered as the user switches between them, and more than one
# template can call in during a switch, so every entry point below is idempotent.
_registered = False


def register():
    """Register the Xsheet operators, draw handler and keymap. Safe to call twice."""
    global _registered
    if _registered:
        return
    for cls in _CLASSES:
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass
    _enable_xsheet()
    _register_xsheet_keymap()
    _registered = True


def unregister():
    """Tear down everything `register()` put in place. Safe to call twice."""
    global _registered
    if not _registered:
        return
    _unregister_xsheet_keymap()
    _disable_xsheet()
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    _registered = False


def reset_state():
    """Drop selection/drag/box state — call from the template's file-load handler."""
    global _xsheet_drag, _xsheet_box
    _xsheet_selected.clear()
    _xsheet_drag = None
    _xsheet_box = None


def apply_timeline_layout(hide_footer=False):
    """Point every Dope Sheet at Grease Pencil mode and hide the duplicated channel list.

    The Xsheet draws its own layer column, so the native channel list would show the same
    Stroke/Lines/Fills rows twice.

    `hide_footer` only makes sense for a template that provides its own transport (Nuclear
    does, in the dope-sheet header). Templates without one keep the native footer, otherwise
    they would lose the playback controls entirely.
    """
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != 'DOPESHEET_EDITOR':
                continue
            space = area.spaces.active
            try:
                space.mode = 'GPENCIL'
            except Exception:
                pass
            if hide_footer:
                try:
                    space.show_region_footer = False
                except Exception:
                    pass
            try:
                space.show_region_channels = False
            except Exception:
                pass
