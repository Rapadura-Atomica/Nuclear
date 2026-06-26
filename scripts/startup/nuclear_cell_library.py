# SPDX-FileCopyrightText: 2026 Nuclear (derivative of Blender)
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Nuclear — Drawing Substitution (Phase 1 + 2 + 3).

Toon Boom-style drawing substitution for Grease Pencil cut-out: a layer keeps a
set of *cells* (drawings) parked as keyframes OUT of the playback range (the
"bank"); the cell exposed at the current frame is swapped via native drawing
*instancing* (no geometry copy). UI = N-panel slider + thumbnail strip + keymap.

Phase 3 adds GPU-rendered cell thumbnails (colour + fill, cached by drawing ptr).

See tools/nuclear_claude/CellLibraryFeature.md for the design.
Pure Python — no C changes. This is a startup module: it auto-registers.
"""

import bpy

# Cells live as keyframes at frame numbers >= BANK_START, well past any sane
# playback range, so they persist (a drawing needs user_count > 0) without
# showing up in the animation. One bank keyframe == one cell.
BANK_START = 100000

# Thumbnail dimensions (pixels per side). 128 gives 4× more pixels than 64
# while staying well within GPU memory limits.
_THUMB_SIZE = 128


# ---------------------------------------------------------------------------
# Core helpers (data layer — no UI, headless-testable)
# ---------------------------------------------------------------------------

def _active_layer(context):
    ob = context.object
    if ob is None or ob.type != 'GREASEPENCIL':
        return None
    return ob.data.layers.active


def is_cell_layer(layer):
    """Return True if this layer participates in the cell system.

    Layers whose name starts with '~' are opted OUT — their drawings are
    never banked by adopt_all, never exposed by expose_key, and never
    composited into thumbnails. Rename '2F-PUPILAS' → '~2F-PUPILAS' to keep
    the pupil animating independently while excluding it from substitution.
    """
    return not layer.name.startswith('~')


def bank_cells(layer):
    """Bank keyframes (the cell set), sorted by frame number."""
    return sorted(
        (f for f in layer.frames if f.frame_number >= BANK_START),
        key=lambda f: f.frame_number,
    )


def cell_count(layer):
    return len(bank_cells(layer))


# --- Frame-keyed, group-aware cell model ------------------------------------
# A cell is identified by a KEY = (bank_frame_number - BANK_START). adopt_all and
# import key each cell by its SOURCE frame number, so "cell key K" means the pose
# as it was at frame K on every layer. A layer that holds (no bank frame exactly
# at K) falls back to its nearest earlier bank frame, keeping every layer
# temporally aligned even when they have different keyframe counts.
#
# Cells span a GROUP of GP objects: every function below takes a LIST of objects.
# Objects sharing the same `nuclear_cell_group` custom property (a string stored
# on the object ID, so it travels with the character on append) are exposed in
# lock-step. An untagged object is a singleton group of itself. This is how two
# separate eyelid objects (palpebra_sup / palpebra_inf) stay synchronized while
# the pupil object — left untagged or excluded — animates freely.

GROUP_PROP = "nuclear_cell_group"


def _participating_layers(objects):
    """Yield (obj, layer) for every cell-participating layer across `objects`
    (skips ~ layers). `objects` is a list of GP objects (a cell group)."""
    for obj in objects:
        if obj is None or obj.type != 'GREASEPENCIL':
            continue
        for lay in obj.data.layers:
            if is_cell_layer(lay):
                yield obj, lay


def cell_keys(objects):
    """Sorted union of cell keys across all participating layers of the group."""
    keys = set()
    for _obj, lay in _participating_layers(objects):
        for f in lay.frames:
            if f.frame_number >= BANK_START:
                keys.add(f.frame_number - BANK_START)
    return sorted(keys)


def cell_position_count(objects):
    """Number of distinct cell positions shown in the strip for the group."""
    return len(cell_keys(objects))


def _bank_frame_for_key(layer, key):
    """Bank frame this layer exposes for `key`: the one at BANK_START+key, else the
    nearest EARLIER bank frame (a hold — a drawing persists forward until the next
    one). Returns None when the key is BEFORE the layer's first bank frame: that
    part did not exist yet at this cell, so it must show nothing (Toon Boom
    exposure semantics) — the caller exposes an empty frame in that case."""
    target = BANK_START + key
    best = None
    for f in layer.frames:
        if f.frame_number < BANK_START or f.frame_number > target:
            continue
        if best is None or f.frame_number > best.frame_number:
            best = f
    return best


def _is_banked(layer, frame_no):
    """True if the drawing exposed at frame_no is already one of layer's cells."""
    exposed = layer.get_frame_at(frame_no)
    if exposed is None:
        return False
    ptr = exposed.drawing.as_pointer()
    return any(
        f.frame_number >= BANK_START and f.drawing.as_pointer() == ptr
        for f in layer.frames
    )


def current_key(objects, frame_no):
    """Cell key currently exposed, judged by the RICHEST participating layer (most
    cells) since it is most likely to span every key — a narrow layer (e.g. skin
    keyed only on a few frames) would otherwise report a stale/approximate key.
    Returns None if nothing resolves."""
    layers = sorted(
        _participating_layers(objects),
        key=lambda ol: cell_count(ol[1]),
        reverse=True,
    )
    for _obj, lay in layers:
        exposed = lay.get_frame_at(frame_no)
        if exposed is None:
            continue
        ptr = exposed.drawing.as_pointer()
        for f in lay.frames:
            if f.frame_number >= BANK_START and f.drawing.as_pointer() == ptr:
                return f.frame_number - BANK_START
    return None


def current_position(objects, frame_no):
    """Index of the exposed cell within cell_keys(objects), or -1."""
    k = current_key(objects, frame_no)
    if k is None:
        return -1
    keys = cell_keys(objects)
    try:
        return keys.index(k)
    except ValueError:
        return -1


def _next_bank_fno(layer):
    cells = bank_cells(layer)
    return (cells[-1].frame_number + 1) if cells else BANK_START


def _next_free_key(objects):
    keys = cell_keys(objects)
    return (keys[-1] + 1) if keys else 1


def ensure_current_banked(layer, frame_no):
    """Ensure the drawing exposed at frame_no is in `layer`'s bank. Banks it at
    key = frame_no (its source frame) when that slot is free, else appends.
    Returns the resulting cell key, or -1 if nothing is exposed."""
    exposed = layer.get_frame_at(frame_no)
    if exposed is None:
        return -1
    ptr = exposed.drawing.as_pointer()
    for f in layer.frames:
        if f.frame_number >= BANK_START and f.drawing.as_pointer() == ptr:
            return f.frame_number - BANK_START  # already banked
    src_fno = exposed.frame_number  # capture int before any realloc
    target = BANK_START + frame_no
    if frame_no > 0 and not any(f.frame_number == target for f in layer.frames):
        bank_fno = target
    else:
        bank_fno = _next_bank_fno(layer)
    layer.frames.copy(
        from_frame_number=src_fno,
        to_frame_number=bank_fno,
        instance_drawing=True,
    )
    return bank_fno - BANK_START


def _expose_bank_frame(layer, frame_no, bank_frame, protect_loose):
    """Instance `bank_frame`'s drawing onto frame_no (zero-copy)."""
    # Capture as ints/ptr BEFORE any remove()/copy() — those realloc the frames
    # collection and invalidate the bank_frame Python reference (RNA gotcha).
    bank_fno = bank_frame.frame_number
    bank_ptr = bank_frame.drawing.as_pointer()
    if protect_loose:
        ensure_current_banked(layer, frame_no)
    exposed = layer.get_frame_at(frame_no)
    if exposed is not None and exposed.frame_number == frame_no:
        if exposed.drawing.as_pointer() == bank_ptr:
            return  # already exposing this cell
        layer.frames.remove(frame_no)
    layer.frames.copy(
        from_frame_number=bank_fno,
        to_frame_number=frame_no,
        instance_drawing=True,
    )


def _expose_empty(layer, frame_no):
    """Make `layer` show NOTHING at frame_no by putting an explicit empty keyframe
    there (used when a part did not exist yet at the requested cell). A bare
    remove would hold the earlier drawing, so we create a fresh empty frame."""
    exposed = layer.get_frame_at(frame_no)
    if exposed is not None and exposed.frame_number == frame_no:
        try:
            if len(exposed.drawing.strokes) == 0:
                return  # already empty here
        except Exception:
            pass
        layer.frames.remove(frame_no)
    layer.frames.new(frame_no)  # fresh, empty drawing


def expose_key(objects, frame_no, key, protect_loose=False):
    """Expose cell `key` across every participating layer of the group. A layer
    that holds (has a bank frame at/before key) shows it; a layer whose range
    starts AFTER key shows an empty frame (the part is absent at this cell)."""
    for _obj, lay in _participating_layers(objects):
        bf = _bank_frame_for_key(lay, key)
        if bf is not None:
            _expose_bank_frame(lay, frame_no, bf, protect_loose)
        else:
            _expose_empty(lay, frame_no)


def expose_position(objects, frame_no, pos, protect_loose=False):
    """Expose the cell at strip position `pos` (index into cell_keys)."""
    keys = cell_keys(objects)
    if 0 <= pos < len(keys):
        expose_key(objects, frame_no, keys[pos], protect_loose=protect_loose)
        return True
    return False


def add_cell(objects, layer, frame_no=None, copy_exposed=False):
    """Add a new empty cell at the next free key (shared across the group) on
    `layer`. Returns the new cell key."""
    new_key = _next_free_key(objects)
    nf = layer.frames.new(BANK_START + new_key)
    if copy_exposed and frame_no is not None:
        ex = layer.get_frame_at(frame_no)
        if ex is not None:
            nf.drawing = ex.drawing  # independent copy into the new cell
    return new_key


def delete_key(objects, frame_no, key):
    """Delete cell `key` from every participating layer of the group that holds a
    bank frame exactly at BANK_START+key. Re-exposes a neighbour key first so the
    timeline keeps no dangling instance of the doomed cell."""
    keys = cell_keys(objects)
    if key not in keys:
        return False
    if len(keys) > 1:
        i = keys.index(key)
        neighbour = keys[i - 1] if i > 0 else keys[i + 1]
        expose_key(objects, frame_no, neighbour, protect_loose=False)
    target = BANK_START + key
    for _obj, lay in _participating_layers(objects):
        if any(f.frame_number == target for f in lay.frames):
            lay.frames.remove(target)
    return True


def group_objects(context):
    """The cell group of context.object: all GP objects in the scene sharing its
    `nuclear_cell_group` tag. Untagged → just [context.object]. Sorted by name."""
    obj = context.object
    if obj is None or obj.type != 'GREASEPENCIL':
        return []
    tag = obj.get(GROUP_PROP, "")
    if not tag:
        return [obj]
    objs = [
        o for o in context.scene.objects
        if o.type == 'GREASEPENCIL' and o.get(GROUP_PROP, "") == tag
    ]
    objs.sort(key=lambda o: o.name)
    return objs or [obj]


def _tag_redraw(context):
    """Force the N-panel and surrounding UI to reflect the new cell state."""
    if context.area:
        context.area.tag_redraw()


# ---------------------------------------------------------------------------
# Cross-file library (Phase 2 — baked copy, pure Python)
# ---------------------------------------------------------------------------

def _base_name(name):
    """Strip a trailing .NNN duplicate suffix (Blender append collision)."""
    head, _, tail = name.rpartition('.')
    return head if (head and tail.isdigit()) else name


def material_remap(dst_gp, src_gp):
    """Map src_gp material slot index -> dst_gp slot index, by material name.
    Appends materials missing from dst_gp. Returns {src_index: dst_index}."""
    mapping = {}
    existing = {}
    for i, m in enumerate(dst_gp.materials):
        if m:
            existing.setdefault(m.name, i)
            existing.setdefault(_base_name(m.name), i)
    for si, sm in enumerate(src_gp.materials):
        if sm is None:
            mapping[si] = 0
            continue
        tgt = existing.get(sm.name)
        if tgt is None:
            tgt = existing.get(_base_name(sm.name))
        if tgt is None:
            dst_gp.materials.append(sm)
            tgt = len(dst_gp.materials) - 1
            existing[sm.name] = tgt
            existing.setdefault(_base_name(sm.name), tgt)
        mapping[si] = tgt
    return mapping


def import_cells_from_layer(dst_gp, dst_layer, src_gp, src_layer):
    """Bake every frame of src_layer into dst_layer's bank, keyed by SOURCE frame
    number (library frame F → bank key F), remapping material slots. Skips keys
    already present. Returns the number of cells imported."""
    mapping = material_remap(dst_gp, src_gp)
    existing = {f.frame_number for f in dst_layer.frames if f.frame_number >= BANK_START}
    count = 0
    for sf in sorted(src_layer.frames, key=lambda f: f.frame_number):
        target = BANK_START + sf.frame_number
        if target in existing:
            continue  # this key already imported/adopted
        nf = dst_layer.frames.new(target)
        nf.drawing = sf.drawing  # baked cross-datablock copy
        mi = nf.drawing.attributes.get('material_index')
        if mi is not None and mapping:
            for d in mi.data:
                d.value = mapping.get(d.value, d.value)
        existing.add(target)
        count += 1
    return count


def import_cells_from_file(dst_gp, dst_layer, filepath, gp_name="", layer_name=""):
    """Append a GreasePencil datablock from `filepath` and import its cells into
    one specific layer. Returns (count, error_or_None)."""
    import bpy as _bpy
    mats_before = set(_bpy.data.materials.keys())
    with _bpy.data.libraries.load(filepath, link=False) as (src, dst):
        names = list(src.grease_pencils)
        if not names:
            return 0, "No Grease Pencil data in that file"
        pick = gp_name if gp_name in names else names[0]
        dst.grease_pencils = [pick]
    src_gp = dst.grease_pencils[0]
    try:
        src_layer = src_gp.layers.get(layer_name) if layer_name else None
        if src_layer is None:
            src_layer = src_gp.layers[0] if len(src_gp.layers) else None
        if src_layer is None:
            return 0, "Source datablock has no layers"
        count = import_cells_from_layer(dst_gp, dst_layer, src_gp, src_layer)
    finally:
        _bpy.data.grease_pencils.remove(src_gp)
        for name in set(_bpy.data.materials.keys()) - mats_before:
            m = _bpy.data.materials.get(name)
            if m is not None and m.users == 0:
                _bpy.data.materials.remove(m)
    return count, None


def import_layer_set(dst_gp, filepath, gp_name=""):
    """Import cells from ALL layers in the library file into dst_gp.

    Layers are matched by name; missing layers are created in dst_gp.
    Returns (total_count, error_or_None). Cleans up temp datablock + orphan mats.
    """
    import bpy as _bpy
    mats_before = set(_bpy.data.materials.keys())
    with _bpy.data.libraries.load(filepath, link=False) as (src, dst):
        names = list(src.grease_pencils)
        if not names:
            return 0, "No Grease Pencil data in that file"
        pick = gp_name if gp_name in names else names[0]
        dst.grease_pencils = [pick]
    src_gp = dst.grease_pencils[0]
    try:
        if not src_gp.layers:
            return 0, "Source datablock has no layers"
        total = 0
        for src_layer in src_gp.layers:
            dst_layer = dst_gp.layers.get(src_layer.name)
            if dst_layer is None:
                dst_layer = dst_gp.layers.new(src_layer.name)
            total += import_cells_from_layer(dst_gp, dst_layer, src_gp, src_layer)
        if total == 0:
            return 0, "No cells found in any layer of the source"
    finally:
        _bpy.data.grease_pencils.remove(src_gp)
        for name in set(_bpy.data.materials.keys()) - mats_before:
            m = _bpy.data.materials.get(name)
            if m is not None and m.users == 0:
                _bpy.data.materials.remove(m)
    return total, None


def export_cells_to_file(src_gp, src_layer, filepath, set_name):
    """Write src_layer's bank cells to a standalone library .blend. Returns count."""
    import bpy as _bpy
    tmp = _bpy.data.grease_pencils.new(set_name)
    tlay = tmp.layers.new(src_layer.name)
    for m in src_gp.materials:
        tmp.materials.append(m)
    n = 0
    for cf in bank_cells(src_layer):
        # Preserve the cell key as the library frame number so re-import round-trips.
        nf = tlay.frames.new(cf.frame_number - BANK_START)
        nf.drawing = cf.drawing
        n += 1
    tmp.use_fake_user = True
    _bpy.data.libraries.write(filepath, {tmp}, fake_user=True)
    _bpy.data.grease_pencils.remove(tmp)
    return n


def export_layer_set(src_gp, filepath, set_name):
    """Write bank cells from ALL layers of src_gp to a standalone library .blend.

    Each layer with bank cells becomes a same-named layer in the output datablock.
    Returns total cells written.
    """
    import bpy as _bpy
    tmp = _bpy.data.grease_pencils.new(set_name)
    for m in src_gp.materials:
        tmp.materials.append(m)
    total = 0
    for src_layer in src_gp.layers:
        cells = bank_cells(src_layer)
        if not cells:
            continue
        tlay = tmp.layers.new(src_layer.name)
        for cf in cells:
            # Preserve the cell key as the library frame number (round-trips).
            nf = tlay.frames.new(cf.frame_number - BANK_START)
            nf.drawing = cf.drawing
            total += 1
    tmp.use_fake_user = True
    _bpy.data.libraries.write(filepath, {tmp}, fake_user=True)
    _bpy.data.grease_pencils.remove(tmp)
    return total


# ---------------------------------------------------------------------------
# Thumbnail system (Phase 3 — GPU offscreen render, cached by drawing ptr)
#
# Thumbnails are rendered once per unique drawing (identified by as_pointer())
# and stored as custom Blender previews. The first call to get_cell_icon_id()
# during a panel draw() triggers the GPU render (panel draw IS a GL context);
# subsequent calls are a key-in-pcoll lookup.
#
# Cache: _thumb_pcoll (ImagePreviewCollection) is the sole cache — presence of
# key in pcoll means the thumbnail is ready. No secondary set needed.
#
# Empty drawings: a grey checkerboard placeholder is generated so the icon
# system can be verified independently of stroke content. Press "Refresh" after
# drawing into cells to regenerate the actual thumbnails.
# ---------------------------------------------------------------------------

_thumb_pcoll = None  # bpy.utils.previews.ImagePreviewCollection


def _thumb_collection():
    global _thumb_pcoll
    if _thumb_pcoll is None:
        import bpy.utils.previews
        _thumb_pcoll = bpy.utils.previews.new()
    return _thumb_pcoll


def _make_ortho(left, right, bottom, top):
    """Build an orthographic projection Matrix for gpu.matrix.load_projection_matrix."""
    from mathutils import Matrix
    rx = 2.0 / (right - left)
    ry = 2.0 / (top - bottom)
    tx = -(right + left) / (right - left)
    ty = -(top + bottom) / (top - bottom)
    return Matrix((
        (rx,  0,  0, tx),
        (0,  ry,  0, ty),
        (0,   0, -1,  0),
        (0,   0,  0,  1),
    ))


def _placeholder_pixels():
    """Grey checkerboard RGBA-float pixels for empty/unrenderable drawings."""
    SIZE = _THUMB_SIZE
    px = []
    for y in range(SIZE):
        for x in range(SIZE):
            if (x // 8 + y // 8) % 2 == 0:
                px.extend([0.18, 0.18, 0.18, 1.0])
            else:
                px.extend([0.12, 0.12, 0.12, 1.0])
    return px


def _stroke_world_xz(stroke, mw):
    """Stroke points projected to world XZ (mw = obj.matrix_world). GP draws in
    the XZ plane; world transform lets a multi-object group composite correctly."""
    out = []
    for pt in stroke.points:
        wp = mw @ pt.position
        out.append((wp.x, wp.z))
    return out


def _collect_strokes_pos(items):
    """Collect world (x, z) positions across (drawing, obj) items for bbox."""
    all_pos = []
    for drawing, obj in items:
        mw = obj.matrix_world
        try:
            strokes = drawing.strokes
        except Exception:
            continue
        for stroke in (strokes or []):
            try:
                all_pos.extend(_stroke_world_xz(stroke, mw))
            except Exception:
                pass
    return all_pos


def _render_drawing_set_to_pixels(items):
    """Composite-render (drawing, obj) items into one _THUMB_SIZE² RGBA-float list.

    `items` ordered bottom-first (painter's algorithm). Points are projected to
    world XZ so objects with different transforms composite correctly; materials
    are taken per-object. Must run inside a GL context (panel draw() qualifies).
    Returns pixel list, or None when all drawings are empty / hard GPU failure.
    """
    import gpu
    from gpu_extras.batch import batch_for_shader
    from mathutils import Matrix

    all_pos = _collect_strokes_pos(items)
    if not all_pos:
        return None

    xs = [p[0] for p in all_pos]
    ys = [p[1] for p in all_pos]
    cx = (min(xs) + max(xs)) * 0.5
    cy = (min(ys) + max(ys)) * 0.5
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1e-6)
    half = span * 0.5 + span * 0.15
    proj = _make_ortho(cx - half, cx + half, cy - half, cy + half)

    SIZE = _THUMB_SIZE
    offscreen = gpu.types.GPUOffScreen(SIZE, SIZE)
    buffer = None

    try:
        with offscreen.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.22, 0.22, 0.22, 1.0))

            try:
                gpu.state.blend_set('ALPHA')
                shader = gpu.shader.from_builtin('UNIFORM_COLOR')
                shader.bind()

                with gpu.matrix.push_pop():
                    gpu.matrix.load_matrix(Matrix.Identity(4))
                    gpu.matrix.load_projection_matrix(proj)

                    from mathutils.geometry import tessellate_polygon

                    for drawing, obj in items:
                        mw = obj.matrix_world
                        mats = obj.data.materials
                        try:
                            strokes = drawing.strokes
                        except Exception:
                            continue
                        if not strokes:
                            continue

                        # Fill pass
                        for stroke in strokes:
                            mi = stroke.material_index
                            mat = mats[mi] if (mats and 0 <= mi < len(mats)) else None
                            gp_mat = getattr(mat, 'grease_pencil', None) if mat else None
                            if not gp_mat or not gp_mat.show_fill:
                                continue
                            pts_xy = _stroke_world_xz(stroke, mw)
                            if len(pts_xy) < 3:
                                continue
                            try:
                                tris = tessellate_polygon(
                                    [[(x, y, 0.0) for x, y in pts_xy]])
                                if not tris:
                                    continue
                                fc = gp_mat.fill_color
                                shader.uniform_float(
                                    "color", (fc[0], fc[1], fc[2], fc[3]))
                                batch_for_shader(
                                    shader, 'TRIS',
                                    {"pos": [pts_xy[idx] for tri in tris for idx in tri]}
                                ).draw(shader)
                            except Exception:
                                pass

                        # Stroke pass
                        try:
                            gpu.state.line_width_set(2.0)
                        except Exception:
                            pass
                        for stroke in strokes:
                            mi = stroke.material_index
                            mat = mats[mi] if (mats and 0 <= mi < len(mats)) else None
                            gp_mat = getattr(mat, 'grease_pencil', None) if mat else None
                            if gp_mat and not gp_mat.show_stroke:
                                continue
                            pts_xy = _stroke_world_xz(stroke, mw)
                            if len(pts_xy) < 2:
                                continue
                            if stroke.cyclic:
                                pts_xy = pts_xy + [pts_xy[0]]
                            if gp_mat:
                                sc = gp_mat.color
                                color = (sc[0], sc[1], sc[2], max(sc[3], 0.8))
                            else:
                                color = (1.0, 1.0, 1.0, 1.0)
                            shader.uniform_float("color", color)
                            batch_for_shader(
                                shader, 'LINE_STRIP', {"pos": pts_xy}
                            ).draw(shader)
                        try:
                            gpu.state.line_width_set(1.0)
                        except Exception:
                            pass
            finally:
                gpu.state.blend_set('NONE')

            buffer = offscreen.texture_color.read()

    except Exception as e:
        import traceback
        print(f"[Nuclear Cells] thumbnail GPU error: {e}")
        traceback.print_exc()
        try:
            gpu.state.blend_set('NONE')
        except Exception:
            pass
    finally:
        offscreen.free()

    if buffer is None:
        return None

    SIZE = _THUMB_SIZE
    return [buffer[y][x][c] / 255.0
            for y in range(SIZE) for x in range(SIZE) for c in range(4)]


def _cell_drawings_at(objects, position):
    """Return (drawing, obj) items for every participating layer of the GROUP at
    strip `position`, applying hold fallback per layer. Ordered bottom→top within
    each object (painter's algorithm). Objects are composited in group order.
    """
    result = []
    keys = cell_keys(objects)
    if not (0 <= position < len(keys)):
        return result
    key = keys[position]
    for obj in objects:
        if obj is None or obj.type != 'GREASEPENCIL':
            continue
        for lay in reversed(list(obj.data.layers)):
            if not is_cell_layer(lay):
                continue
            bf = _bank_frame_for_key(lay, key)
            if bf is not None and bf.drawing is not None:
                result.append((bf.drawing, obj))
    return result


def resolve_group_cells(objects):
    """One-pass resolution of the WHOLE strip for `objects`. Returns
    (keys, items_by_pos) where items_by_pos[i] is the list of (drawing, obj) for
    strip position i (bottom→top per object, hold fallback applied) — i.e. exactly
    what _cell_drawings_at(objects, i) returns, but computed for every position in a
    single O(layers × frames) pass instead of O(positions × layers × frames).

    This is the hot path that kept the Cells panel quadratic in keyframe count: the
    panel draws one thumbnail per cell, and each call used to re-scan cell_keys and
    every layer's frames. Resolve once, reuse across the strip.
    """
    keys = cell_keys(objects)
    if not keys:
        return keys, []

    # Snapshot each participating layer's bank frames once, sorted, in the same
    # draw order _cell_drawings_at uses (objects in group order, layers bottom→top).
    layer_banks = []  # list of (obj, [(frame_number, drawing), ...] sorted)
    for obj in objects:
        if obj is None or obj.type != 'GREASEPENCIL':
            continue
        for lay in reversed(list(obj.data.layers)):
            if not is_cell_layer(lay):
                continue
            banks = sorted(
                ((f.frame_number, f.drawing) for f in lay.frames
                 if f.frame_number >= BANK_START and f.drawing is not None),
                key=lambda t: t[0],
            )
            layer_banks.append((obj, banks))

    # Two-pointer merge: keys and each layer's bank frames are both sorted, so the
    # nearest-bank-at-or-before-key (the hold fallback) advances monotonically.
    items_by_pos = [[] for _ in keys]
    for obj, banks in layer_banks:
        bi = 0
        best = None
        for ki, key in enumerate(keys):
            target = BANK_START + key
            while bi < len(banks) and banks[bi][0] <= target:
                best = banks[bi][1]
                bi += 1
            if best is not None:
                items_by_pos[ki].append((best, obj))
    return keys, items_by_pos


def _icon_key_for_items(items, position):
    """Cache key for a resolved cell: pointer-keyed so it invalidates when the
    underlying drawings change; positional placeholder when the cell is empty."""
    if not items:
        return f"empty_{position}"
    return "ml_" + "_".join(str(d.as_pointer()) for d, _ in items)


def get_cell_icon_id_for_items(items, position):
    """icon_id for an already-resolved item list. Checks the cache FIRST (so a warm
    cache costs one dict lookup, never a GPU render); renders only on a miss."""
    key = _icon_key_for_items(items, position)
    pcoll = _thumb_collection()
    if key in pcoll:
        return pcoll[key].icon_id

    pixels = _render_drawing_set_to_pixels(items) if items else None
    if pixels is None:
        pixels = _placeholder_pixels()

    preview = pcoll.new(key)
    preview.image_size = (_THUMB_SIZE, _THUMB_SIZE)
    preview.image_pixels_float = pixels
    return preview.icon_id


def get_cell_icon_id_at(objects, position):
    """Return composite icon_id for the cell at strip `position` across the GROUP.

    Generates and caches on first call (needs GL context — panel draw() qualifies).
    Always returns a valid non-zero icon_id (checkerboard placeholder if all empty).

    Single-position convenience wrapper; the panel uses resolve_group_cells() +
    get_cell_icon_id_for_items() to avoid the per-cell re-scan.
    """
    return get_cell_icon_id_for_items(_cell_drawings_at(objects, position), position)


def invalidate_thumb(_drawing_ptr=None):
    """Invalidate cached thumbnails. Clears the entire collection so all cells
    regenerate on the next panel draw — simpler and safer than per-entry removal."""
    _thumb_collection().clear()


def clear_all_thumbs():
    """Free the entire preview collection (called on unregister or full refresh)."""
    global _thumb_pcoll
    if _thumb_pcoll is not None:
        bpy.utils.previews.remove(_thumb_pcoll)
        _thumb_pcoll = None


# ---------------------------------------------------------------------------
# WindowManager slider property (drives substitution)
# ---------------------------------------------------------------------------

def _cell_index_get(self):
    ctx = bpy.context
    objects = group_objects(ctx)
    if not objects:
        return 0
    pos = current_position(objects, ctx.scene.frame_current)
    return max(0, pos)


def _cell_index_set(self, value):
    ctx = bpy.context
    objects = group_objects(ctx)
    if not objects:
        return
    expose_position(objects, ctx.scene.frame_current, value)


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class NUCLEAR_OT_cell_step(bpy.types.Operator):
    """Expose the next/previous cell at the current frame"""
    bl_idname = "nuclear.cell_step"
    bl_label = "Step Drawing Cell"
    bl_options = {'REGISTER', 'UNDO'}

    delta: bpy.props.IntProperty(default=1)
    wrap: bpy.props.BoolProperty(default=True)

    @classmethod
    def poll(cls, context):
        return _active_layer(context) is not None

    def execute(self, context):
        objects = group_objects(context)
        n = cell_position_count(objects)
        if n == 0:
            self.report({'WARNING'}, "No cells in this object's bank")
            return {'CANCELLED'}
        fno = context.scene.frame_current
        cur = current_position(objects, fno)
        if cur < 0:
            cur = 0
        nxt = cur + self.delta
        nxt = (nxt % n) if self.wrap else max(0, min(nxt, n - 1))
        expose_position(objects, fno, nxt, protect_loose=False)
        _tag_redraw(context)
        return {'FINISHED'}


class NUCLEAR_OT_cell_expose(bpy.types.Operator):
    """Expose a specific cell by index (used by thumbnail strip)"""
    bl_idname = "nuclear.cell_expose"
    bl_label = "Expose Cell"
    bl_options = {'REGISTER', 'UNDO'}

    index: bpy.props.IntProperty(default=0, min=0)

    @classmethod
    def poll(cls, context):
        return _active_layer(context) is not None

    def execute(self, context):
        # protect_loose=False: don't auto-bank the displaced drawing; the user
        # explicitly chose to replace it by clicking the thumbnail.
        expose_position(
            group_objects(context), context.scene.frame_current, self.index,
            protect_loose=False,
        )
        _tag_redraw(context)
        return {'FINISHED'}


class NUCLEAR_OT_cell_adopt_all(bpy.types.Operator):
    """Register all unique timeline drawings from EVERY layer of EVERY object in
    the cell group as bank cells, keyed by source frame so cell N is the same pose
    across all layers and all grouped objects."""
    bl_idname = "nuclear.cell_adopt_all"
    bl_label = "Link All Timeline Drawings"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.type == 'GREASEPENCIL'

    def execute(self, context):
        objects = group_objects(context)

        count = 0
        for _obj, lay in _participating_layers(objects):
            # Bank each timeline keyframe at its source-frame key (BANK_START+fno),
            # so cell key K is the same pose everywhere. Holds resolve later via
            # _bank_frame_for_key's nearest-earlier fallback.
            existing_keys = {
                f.frame_number for f in lay.frames if f.frame_number >= BANK_START
            }
            # Capture source frame numbers as plain ints BEFORE copying — each
            # frames.copy() reallocs the frames collection and invalidates any
            # held Python frame references (RNA gotcha).
            src_fnos = sorted(
                f.frame_number for f in lay.frames
                if 0 < f.frame_number < BANK_START and f.drawing is not None
            )
            for fno in src_fnos:
                target = BANK_START + fno
                if target in existing_keys:
                    continue
                lay.frames.copy(
                    from_frame_number=fno,
                    to_frame_number=target,
                    instance_drawing=True,
                )
                existing_keys.add(target)
                count += 1

        if count == 0:
            self.report({'INFO'}, "All drawings are already linked as cells")
        else:
            scope = f" across {len(objects)} objects" if len(objects) > 1 else ""
            self.report({'INFO'}, f"Linked {count} drawing(s){scope}")
            invalidate_thumb(None)
            _tag_redraw(context)
        return {'FINISHED'}


class NUCLEAR_OT_cell_add(bpy.types.Operator):
    """Add a new drawing cell to this layer's bank"""
    bl_idname = "nuclear.cell_add"
    bl_label = "Add Drawing Cell"
    bl_options = {'REGISTER', 'UNDO'}

    copy_exposed: bpy.props.BoolProperty(
        name="Duplicate Current",
        description="Seed the new cell from the drawing exposed at the current frame",
        default=False,
    )
    expose: bpy.props.BoolProperty(
        name="Expose",
        description="Expose the new cell at the current frame",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return _active_layer(context) is not None

    def execute(self, context):
        objects = group_objects(context)
        layer = _active_layer(context)
        fno = context.scene.frame_current
        ensure_current_banked(layer, fno)
        new_key = add_cell(objects, layer, fno, self.copy_exposed)
        if self.expose:
            expose_key(objects, fno, new_key, protect_loose=False)
        _tag_redraw(context)
        return {'FINISHED'}


class NUCLEAR_OT_cell_adopt(bpy.types.Operator):
    """Register the drawing currently shown at this frame as a cell (link it,
    no copy) — use this to turn an already-drawn pose into the first cell"""
    bl_idname = "nuclear.cell_adopt"
    bl_label = "Link Current Drawing as Cell"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        layer = _active_layer(context)
        if layer is None:
            return False
        # Only meaningful when something is shown that is NOT already a cell.
        # get_frame_at returns the nearest key at-or-before, so this also
        # activates when the current frame is covered by an earlier keyframe.
        fno = context.scene.frame_current
        return (
            layer.get_frame_at(fno) is not None
            and not _is_banked(layer, fno)
        )

    def execute(self, context):
        layer = _active_layer(context)
        fno = context.scene.frame_current
        exposed = layer.get_frame_at(fno)
        if exposed is None:
            self.report({'WARNING'}, "No drawing at the current frame")
            return {'CANCELLED'}
        key = ensure_current_banked(layer, fno)
        if key < 0:
            self.report({'WARNING'}, "Could not link drawing — bank operation failed")
            return {'CANCELLED'}
        src_fno = exposed.frame_number
        msg = f"Linked drawing (cell key {key})"
        if src_fno != fno:
            msg += f" from frame {src_fno}"
        invalidate_thumb(None)
        self.report({'INFO'}, msg)
        _tag_redraw(context)
        return {'FINISHED'}


class NUCLEAR_OT_cell_delete(bpy.types.Operator):
    """Delete the currently exposed drawing cell from the bank"""
    bl_idname = "nuclear.cell_delete"
    bl_label = "Delete Drawing Cell"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.object
        return (ob is not None and ob.type == 'GREASEPENCIL'
                and cell_position_count(group_objects(context)) > 0)

    def execute(self, context):
        objects = group_objects(context)
        fno = context.scene.frame_current
        keys = cell_keys(objects)
        if not keys:
            return {'CANCELLED'}
        pos = current_position(objects, fno)
        key = keys[pos] if 0 <= pos < len(keys) else keys[0]
        delete_key(objects, fno, key)
        invalidate_thumb(None)  # wipes entire cache so stale entry disappears
        _tag_redraw(context)
        return {'FINISHED'}


class NUCLEAR_OT_cell_refresh_thumbs(bpy.types.Operator):
    """Regenerate all cell thumbnails for the active layer (use after editing strokes)"""
    bl_idname = "nuclear.cell_refresh_thumbs"
    bl_label = "Refresh Cell Thumbnails"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        ob = context.object
        return (ob is not None and ob.type == 'GREASEPENCIL'
                and cell_position_count(group_objects(context)) > 0)

    def execute(self, context):
        clear_all_thumbs()   # wipe entire cache; panel draw regenerates on next frame
        _tag_redraw(context)
        self.report({'INFO'}, "Thumbnails queued for regeneration")
        return {'FINISHED'}


class NUCLEAR_OT_cells_import(bpy.types.Operator):
    """Import drawing cells from a library .blend into this GP object"""
    bl_idname = "nuclear.cells_import"
    bl_label = "Import Cells from Library"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filter_glob: bpy.props.StringProperty(default="*.blend", options={'HIDDEN'})
    datablock: bpy.props.StringProperty(
        name="Cell Set",
        description="Grease Pencil datablock to read (blank = first in file)",
    )
    all_layers: bpy.props.BoolProperty(
        name="All Layers",
        description=(
            "Import cells for every layer in the file, matching by name "
            "(creates missing layers). When off, imports only into the active layer"
        ),
        default=True,
    )
    layer_name: bpy.props.StringProperty(
        name="Layer",
        description="Source layer when All Layers is off (blank = first layer)",
    )

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.type == 'GREASEPENCIL'

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if not self.filepath:
            self.report({'WARNING'}, "No file selected")
            return {'CANCELLED'}
        dst_gp = context.object.data
        if self.all_layers:
            count, err = import_layer_set(dst_gp, self.filepath, self.datablock)
        else:
            dst_layer = _active_layer(context)
            if dst_layer is None:
                self.report({'WARNING'}, "No active layer")
                return {'CANCELLED'}
            count, err = import_cells_from_file(
                dst_gp, dst_layer, self.filepath, self.datablock, self.layer_name)
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        self.report({'INFO'}, f"Imported {count} cell(s)")
        _tag_redraw(context)
        return {'FINISHED'}


class NUCLEAR_OT_cells_export(bpy.types.Operator):
    """Export drawing cells from this GP object to a library .blend"""
    bl_idname = "nuclear.cells_export"
    bl_label = "Export Cells to Library"
    bl_options = {'REGISTER'}

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filter_glob: bpy.props.StringProperty(default="*.blend", options={'HIDDEN'})
    set_name: bpy.props.StringProperty(
        name="Cell Set Name",
        description="Name of the Grease Pencil datablock written to the library",
        default="CellSet",
    )
    all_layers: bpy.props.BoolProperty(
        name="All Layers",
        description=(
            "Export cells from every layer that has a bank. "
            "When off, exports only the active layer"
        ),
        default=True,
    )

    @classmethod
    def poll(cls, context):
        ob = context.object
        if ob is None or ob.type != 'GREASEPENCIL':
            return False
        return any(cell_count(lay) > 0 for lay in ob.data.layers)

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = "cells.blend"
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if not self.filepath:
            self.report({'WARNING'}, "No file selected")
            return {'CANCELLED'}
        gp = context.object.data
        if self.all_layers:
            name = self.set_name or gp.name
            n = export_layer_set(gp, self.filepath, name)
        else:
            layer = _active_layer(context)
            if layer is None:
                self.report({'WARNING'}, "No active layer")
                return {'CANCELLED'}
            name = self.set_name or layer.name
            n = export_cells_to_file(gp, layer, self.filepath, name)
        if n == 0:
            self.report({'WARNING'}, "No cells to export")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Exported {n} cell(s)")
        return {'FINISHED'}


class NUCLEAR_OT_cell_group_assign(bpy.types.Operator):
    """Tag every selected Grease Pencil object with a shared cell-group name, so
    they expose cells in lock-step (e.g. two eyelid objects). The tag is stored on
    the object and travels with the character on append."""
    bl_idname = "nuclear.cell_group_assign"
    bl_label = "Group Selected GP Objects"
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty(
        name="Group Name",
        description="Shared cell-group tag (objects with the same tag sync together)",
        default="",
    )

    @classmethod
    def poll(cls, context):
        return any(o.type == 'GREASEPENCIL' for o in context.selected_objects)

    def invoke(self, context, event):
        if not self.name:
            ob = context.object
            existing = ob.get(GROUP_PROP, "") if ob else ""
            self.name = existing or (ob.name if ob else "cell_group")
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        tag = self.name.strip()
        if not tag:
            self.report({'WARNING'}, "Group name cannot be empty")
            return {'CANCELLED'}
        n = 0
        for o in context.selected_objects:
            if o.type == 'GREASEPENCIL':
                o[GROUP_PROP] = tag
                n += 1
        invalidate_thumb(None)
        _tag_redraw(context)
        self.report({'INFO'}, f"Grouped {n} object(s) as '{tag}'")
        return {'FINISHED'}


class NUCLEAR_OT_cell_group_clear(bpy.types.Operator):
    """Remove the cell-group tag from the active GP object (it becomes standalone)"""
    bl_idname = "nuclear.cell_group_clear"
    bl_label = "Ungroup Object"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.object
        return (ob is not None and ob.type == 'GREASEPENCIL'
                and ob.get(GROUP_PROP, ""))

    def execute(self, context):
        ob = context.object
        if GROUP_PROP in ob:
            del ob[GROUP_PROP]
        invalidate_thumb(None)
        _tag_redraw(context)
        self.report({'INFO'}, "Object ungrouped")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

class NUCLEAR_PT_cell_library(bpy.types.Panel):
    bl_label = "Drawing Substitution"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Cells"

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.type == 'GREASEPENCIL'

    def draw(self, context):
        layout = self.layout
        gp_object = context.object
        layer = _active_layer(context)

        if layer is None:
            layout.label(text="No active layer", icon='INFO')
            return

        fno = context.scene.frame_current
        objects = group_objects(context)
        # Resolve the whole strip once (O(layers × frames)); the per-cell thumbnail
        # loop below reuses this instead of re-scanning every layer for every cell
        # (which made the panel quadratic in keyframe count → freeze at ~1000 frames).
        keys, items_by_pos = resolve_group_cells(objects)
        n = len(keys)
        cur = current_position(objects, fno)

        # ---- Cell group status ----
        tag = gp_object.get(GROUP_PROP, "")
        grp_row = layout.row(align=True)
        if tag:
            grp_row.label(text=f"Group: {tag} ({len(objects)})", icon='LINKED')
            grp_row.operator("nuclear.cell_group_clear", text="", icon='X')
        else:
            grp_row.operator(
                "nuclear.cell_group_assign", text="Group Selected", icon='LINKED')

        # ---- Large thumbnail of the active cell ----
        if n > 0 and cur >= 0:
            icon_id = get_cell_icon_id_for_items(items_by_pos[cur], cur)
            col_icon = layout.column()
            col_icon.alignment = 'CENTER'
            col_icon.template_icon(icon_value=icon_id, scale=5.5)

        # ---- Navigation row: prev · slider · next ----
        col = layout.column(align=True)
        row = col.row(align=True)
        op = row.operator("nuclear.cell_step", text="", icon='TRIA_LEFT')
        op.delta = -1
        sub = row.row(align=True)
        sub.enabled = n > 0
        sub.prop(context.window_manager, "nuclear_cell_index", text="", slider=True)
        op = row.operator("nuclear.cell_step", text="", icon='TRIA_RIGHT')
        op.delta = 1

        if n and cur >= 0:
            col.label(text=f"Cell {cur + 1} / {n}", icon='GREASEPENCIL')
        elif n:
            col.label(text=f"— / {n}", icon='GREASEPENCIL')
        else:
            col.label(text="No cells", icon='GREASEPENCIL')

        # Show hint when some layers are opted out via ~ prefix
        skipped = [lay.name for lay in gp_object.data.layers if not is_cell_layer(lay)]
        if skipped:
            row = layout.row()
            row.alert = False
            row.label(
                text=f"Excluded: {', '.join(skipped)}",
                icon='HIDE_ON',
            )

        # ---- "Link Current Drawing" prompt (active layer's drawing not yet a cell) ----
        has_loose = (
            is_cell_layer(layer)
            and layer.get_frame_at(fno) is not None
            and not _is_banked(layer, fno)
        )
        if has_loose:
            box = layout.box()
            box.label(text="Current drawing isn't a cell", icon='INFO')
            row = box.row(align=True)
            row.operator("nuclear.cell_adopt", text="Link Current", icon='LINKED')
            row.operator("nuclear.cell_adopt_all", text="Link All Timeline", icon='LIGHTPROBE_VOLUME')

        # ---- Thumbnail strip (all cells, click to expose) ----
        if n > 0:
            grid = layout.grid_flow(
                row_major=True, columns=0, even_columns=True, even_rows=True, align=True
            )
            for i in range(n):
                cell_col = grid.column(align=True)
                if cur == i:
                    cell_col.alert = True
                icon_id = get_cell_icon_id_for_items(items_by_pos[i], i)
                op = cell_col.operator(
                    "nuclear.cell_expose",
                    text="" if icon_id else str(i + 1),
                    icon_value=icon_id,
                )
                op.index = i

        # ---- Add / Duplicate / Delete / Refresh ----
        row = layout.row(align=True)
        row.operator("nuclear.cell_add", text="Add", icon='ADD').copy_exposed = False
        row.operator("nuclear.cell_add", text="Duplicate", icon='DUPLICATE').copy_exposed = True
        row2 = layout.row(align=True)
        row2.operator("nuclear.cell_delete", text="Delete", icon='REMOVE')
        row2.operator("nuclear.cell_refresh_thumbs", text="", icon='FILE_REFRESH')

        # ---- Library (import / export, all-layers primary) ----
        box = layout.box()
        box.label(text="Library", icon='ASSET_MANAGER')
        col = box.column(align=True)

        row = col.row(align=True)
        row.operator("nuclear.cells_import", text="Import All Layers…", icon='IMPORT').all_layers = True
        row.operator("nuclear.cells_import", text="", icon='LAYER_ACTIVE').all_layers = False

        has_any = any(cell_count(lay) > 0 for lay in gp_object.data.layers)
        sub = col.row(align=True)
        sub.enabled = has_any
        sub.operator("nuclear.cells_export", text="Export All Layers…", icon='EXPORT').all_layers = True
        sub.operator("nuclear.cells_export", text="", icon='LAYER_ACTIVE').all_layers = False


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_classes = (
    NUCLEAR_OT_cell_step,
    NUCLEAR_OT_cell_expose,
    NUCLEAR_OT_cell_add,
    NUCLEAR_OT_cell_adopt,
    NUCLEAR_OT_cell_adopt_all,
    NUCLEAR_OT_cell_delete,
    NUCLEAR_OT_cell_refresh_thumbs,
    NUCLEAR_OT_cell_group_assign,
    NUCLEAR_OT_cell_group_clear,
    NUCLEAR_OT_cells_import,
    NUCLEAR_OT_cells_export,
    NUCLEAR_PT_cell_library,
)

_addon_keymaps = []


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)

    bpy.types.WindowManager.nuclear_cell_index = bpy.props.IntProperty(
        name="Cell",
        description="Drawing cell exposed at the current frame",
        default=0,
        min=0,
        soft_max=64,
        get=_cell_index_get,
        set=_cell_index_set,
    )

    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name="Object Mode", space_type='EMPTY')
        kmi = km.keymap_items.new("nuclear.cell_step", 'RIGHT_BRACKET', 'PRESS')
        kmi.properties.delta = 1
        _addon_keymaps.append((km, kmi))
        kmi = km.keymap_items.new("nuclear.cell_step", 'LEFT_BRACKET', 'PRESS')
        kmi.properties.delta = -1
        _addon_keymaps.append((km, kmi))


def unregister():
    clear_all_thumbs()

    for km, kmi in _addon_keymaps:
        km.keymap_items.remove(kmi)
    _addon_keymaps.clear()

    del bpy.types.WindowManager.nuclear_cell_index

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
