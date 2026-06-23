# SPDX-FileCopyrightText: 2026 Nuclear (derivative of Blender)
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Nuclear — Drawing Substitution (Phase 1).

Toon Boom-style drawing substitution for Grease Pencil cut-out: a layer keeps a
set of *cells* (drawings) parked as keyframes OUT of the playback range (the
"bank"); the cell exposed at the current frame is swapped via native drawing
*instancing* (no geometry copy). UI = N-panel slider + prev/next + keymap.

See tools/nuclear_claude/CellLibraryFeature.md for the design.
Pure Python — no C changes. This is a startup module: it auto-registers.
"""

import bpy

# Cells live as keyframes at frame numbers >= BANK_START, well past any sane
# playback range, so they persist (a drawing needs user_count > 0) without
# showing up in the animation. One bank keyframe == one cell.
BANK_START = 100000


# ---------------------------------------------------------------------------
# Core helpers (data layer — no UI, headless-testable)
# ---------------------------------------------------------------------------

def _active_layer(context):
    ob = context.object
    if ob is None or ob.type != 'GREASEPENCIL':
        return None
    return ob.data.layers.active


def bank_cells(layer):
    """Bank keyframes (the cell set), sorted by frame number."""
    return sorted(
        (f for f in layer.frames if f.frame_number >= BANK_START),
        key=lambda f: f.frame_number,
    )


def cell_count(layer):
    return len(bank_cells(layer))


def current_cell(layer, frame_no):
    """Index of the bank cell exposed at frame_no, or -1.

    Matched by the underlying drawing pointer — instancing means the exposed
    frame and its bank cell share the exact same drawing.
    """
    exposed = layer.get_frame_at(frame_no)
    if exposed is None:
        return -1
    ptr = exposed.drawing.as_pointer()
    for i, bf in enumerate(bank_cells(layer)):
        if bf.drawing.as_pointer() == ptr:
            return i
    return -1


def ensure_current_banked(layer, frame_no):
    """Make sure the drawing currently exposed at frame_no is registered in the
    bank (as a cell). If it already is, no-op. Otherwise *instance* it into a new
    bank frame (zero-copy, shared) so it is never lost when another cell is
    exposed over it. Returns the cell index of the current drawing, or -1.

    This is the "link an existing drawing as a cell" primitive (the Adopt op).
    """
    idx = current_cell(layer, frame_no)
    if idx >= 0:
        return idx
    exposed = layer.get_frame_at(frame_no)
    if exposed is None:
        return -1
    layer.frames.copy(
        from_frame_number=exposed.frame_number,
        to_frame_number=_next_bank_fno(layer),
        instance_drawing=True,
    )
    return current_cell(layer, frame_no)


def expose_cell(layer, frame_no, index):
    """Expose bank cell `index` at `frame_no` by instancing (zero-copy).

    NOTE: `frame.drawing = other` COPIES the geometry (verified), so it would
    break the shared-cell model. We instance via frames.copy(instance=True).

    Always banks the currently-exposed drawing first (ensure_current_banked), so
    a loose drawing on the timeline is never destroyed by exposing a cell.
    """
    ensure_current_banked(layer, frame_no)
    cells = bank_cells(layer)
    if not cells:
        return False
    index = max(0, min(index, len(cells) - 1))
    bank_fno = cells[index].frame_number
    exposed = layer.get_frame_at(frame_no)
    # Only replace a key sitting exactly on this frame; an earlier key that
    # merely *covers* frame_no is left alone (we add a new exposure here).
    if exposed is not None and exposed.frame_number == frame_no:
        if exposed.drawing.as_pointer() == cells[index].drawing.as_pointer():
            return True  # already exposing this cell — nothing to do
        layer.frames.remove(frame_no)
    layer.frames.copy(
        from_frame_number=bank_fno,
        to_frame_number=frame_no,
        instance_drawing=True,
    )
    return True


def _next_bank_fno(layer):
    cells = bank_cells(layer)
    return (cells[-1].frame_number + 1) if cells else BANK_START


def add_cell(layer, frame_no=None, copy_exposed=False):
    """Append a new (empty) cell to the bank. Returns its bank frame number.

    If copy_exposed, seed it from the drawing currently exposed at frame_no
    (uses the copying assignment on purpose — a new cell is an independent copy).
    """
    new_fno = _next_bank_fno(layer)
    nf = layer.frames.new(new_fno)
    if copy_exposed and frame_no is not None:
        ex = layer.get_frame_at(frame_no)
        if ex is not None:
            nf.drawing = ex.drawing  # copies content into the new cell
    return new_fno


def delete_cell(layer, index, frame_no):
    """Remove bank cell `index`.

    If it is the one exposed at frame_no, move the exposure to a neighbour FIRST
    (while the doomed cell is still in the bank, so expose_cell's auto-protect
    recognises it as a cell and does NOT re-bank it), then remove it. If it is
    the only cell, the exposed drawing is left as a loose drawing (art kept).
    """
    cells = bank_cells(layer)
    if not (0 <= index < len(cells)):
        return False
    doomed_fno = cells[index].frame_number
    was_current = current_cell(layer, frame_no) == index
    if was_current and len(cells) > 1:
        neighbour = index - 1 if index > 0 else index + 1
        expose_cell(layer, frame_no, neighbour)
    layer.frames.remove(doomed_fno)
    return True


# ---------------------------------------------------------------------------
# Cross-file library (Phase 2 — baked copy, pure Python)
#
# Verified 2026-06-22: `frame.drawing = other_gp_frame.drawing` does a FULL
# CurvesGeometry copy ACROSS datablocks (geometry + material_index + cyclic +
# radius + all attributes), independent of the source. So importing a cell from
# a library .blend is just: append the library GreasePencil datablock, create a
# bank frame, assign its drawing, remap materials, drop the temp datablock.
# No C++, no rebuild. The only real gotcha is material_index (slot index differs
# between files) — remapped by material NAME below.
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
    """Bake every frame of src_layer into dst_layer's bank as a new cell,
    remapping material slots. Returns the number of cells imported."""
    mapping = material_remap(dst_gp, src_gp)
    count = 0
    for sf in sorted(src_layer.frames, key=lambda f: f.frame_number):
        nf = dst_layer.frames.new(_next_bank_fno(dst_layer))
        nf.drawing = sf.drawing  # baked cross-datablock copy
        mi = nf.drawing.attributes.get('material_index')
        if mi is not None and mapping:
            for d in mi.data:
                d.value = mapping.get(d.value, d.value)
        count += 1
    return count


def import_cells_from_file(dst_gp, dst_layer, filepath, gp_name="", layer_name=""):
    """Append a GreasePencil datablock from `filepath` and import its cells.
    Returns (count, error_or_None). Cleans up the temp datablock + orphan mats."""
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
        # drop appended-but-deduped materials (matched to existing by name)
        for name in set(_bpy.data.materials.keys()) - mats_before:
            m = _bpy.data.materials.get(name)
            if m is not None and m.users == 0:
                _bpy.data.materials.remove(m)
    return count, None


def export_cells_to_file(src_gp, src_layer, filepath, set_name):
    """Write src_layer's bank cells to a standalone library .blend as a fresh
    GreasePencil datablock (self-contained: drawings baked + materials). Returns
    the number of cells written."""
    import bpy as _bpy
    tmp = _bpy.data.grease_pencils.new(set_name)
    tlay = tmp.layers.new(src_layer.name)
    for m in src_gp.materials:  # preserve slot indices so material_index stays valid
        tmp.materials.append(m)
    n = 0
    for cf in bank_cells(src_layer):
        nf = tlay.frames.new(1 + n)
        nf.drawing = cf.drawing  # baked copy into the temp datablock
        n += 1
    tmp.use_fake_user = True
    _bpy.data.libraries.write(filepath, {tmp}, fake_user=True)
    _bpy.data.grease_pencils.remove(tmp)
    return n


# ---------------------------------------------------------------------------
# WindowManager slider property (drives substitution)
# ---------------------------------------------------------------------------

def _cell_index_get(self):
    ctx = bpy.context
    layer = _active_layer(ctx)
    if layer is None:
        return 0
    idx = current_cell(layer, ctx.scene.frame_current)
    return max(0, idx)


def _cell_index_set(self, value):
    ctx = bpy.context
    layer = _active_layer(ctx)
    if layer is None:
        return
    expose_cell(layer, ctx.scene.frame_current, value)


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
        layer = _active_layer(context)
        n = cell_count(layer)
        if n == 0:
            self.report({'WARNING'}, "No cells in this layer's bank")
            return {'CANCELLED'}
        fno = context.scene.frame_current
        cur = current_cell(layer, fno)
        if cur < 0:
            cur = 0
        nxt = cur + self.delta
        nxt = (nxt % n) if self.wrap else max(0, min(nxt, n - 1))
        expose_cell(layer, fno, nxt)
        context.area.tag_redraw() if context.area else None
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
        layer = _active_layer(context)
        fno = context.scene.frame_current
        # Adopt the existing drawing first so it becomes the earlier cell and is
        # never lost when the new (blank/duplicate) cell is exposed over it.
        ensure_current_banked(layer, fno)
        add_cell(layer, fno, self.copy_exposed)
        if self.expose:
            expose_cell(layer, fno, cell_count(layer) - 1)
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
        # only meaningful when something is shown that isn't a cell yet
        return layer.get_frame_at(context.scene.frame_current) is not None

    def execute(self, context):
        layer = _active_layer(context)
        fno = context.scene.frame_current
        if current_cell(layer, fno) >= 0:
            self.report({'INFO'}, "Current drawing is already a cell")
            return {'CANCELLED'}
        idx = ensure_current_banked(layer, fno)
        if idx < 0:
            self.report({'WARNING'}, "No drawing at the current frame")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Linked as cell {idx + 1}")
        return {'FINISHED'}


class NUCLEAR_OT_cell_delete(bpy.types.Operator):
    """Delete the currently exposed drawing cell from the bank"""
    bl_idname = "nuclear.cell_delete"
    bl_label = "Delete Drawing Cell"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        layer = _active_layer(context)
        return layer is not None and cell_count(layer) > 0

    def execute(self, context):
        layer = _active_layer(context)
        fno = context.scene.frame_current
        idx = current_cell(layer, fno)
        if idx < 0:
            idx = 0
        delete_cell(layer, idx, fno)
        return {'FINISHED'}


class NUCLEAR_OT_cells_import(bpy.types.Operator):
    """Import drawing cells from a library .blend into this layer's bank"""
    bl_idname = "nuclear.cells_import"
    bl_label = "Import Cells from Library"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filter_glob: bpy.props.StringProperty(default="*.blend", options={'HIDDEN'})
    datablock: bpy.props.StringProperty(
        name="Cell Set",
        description="Grease Pencil datablock to read (blank = first in file)",
    )
    layer_name: bpy.props.StringProperty(
        name="Layer",
        description="Layer to read cells from (blank = first layer)",
    )

    @classmethod
    def poll(cls, context):
        return _active_layer(context) is not None

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if not self.filepath:
            self.report({'WARNING'}, "No file selected")
            return {'CANCELLED'}
        dst_gp = context.object.data
        dst_layer = _active_layer(context)
        count, err = import_cells_from_file(
            dst_gp, dst_layer, self.filepath, self.datablock, self.layer_name)
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        self.report({'INFO'}, f"Imported {count} cell(s)")
        return {'FINISHED'}


class NUCLEAR_OT_cells_export(bpy.types.Operator):
    """Export this layer's bank cells to a library .blend"""
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

    @classmethod
    def poll(cls, context):
        layer = _active_layer(context)
        return layer is not None and cell_count(layer) > 0

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
        layer = _active_layer(context)
        name = self.set_name or layer.name
        n = export_cells_to_file(gp, layer, self.filepath, name)
        self.report({'INFO'}, f"Exported {n} cell(s)")
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
        layer = _active_layer(context)
        if layer is None:
            layout.label(text="No active layer", icon='INFO')
            return
        n = cell_count(layer)
        cur = current_cell(layer, context.scene.frame_current)

        col = layout.column(align=True)
        row = col.row(align=True)
        op = row.operator("nuclear.cell_step", text="", icon='TRIA_LEFT')
        op.delta = -1
        sub = row.row(align=True)
        sub.enabled = n > 0
        sub.prop(context.window_manager, "nuclear_cell_index", text="", slider=True)
        op = row.operator("nuclear.cell_step", text="", icon='TRIA_RIGHT')
        op.delta = 1

        label = f"Cell {cur + 1} / {n}" if (n and cur >= 0) else (f"— / {n}" if n else "No cells")
        col.label(text=label, icon='GREASEPENCIL')

        # A drawing is shown but isn't a cell yet → offer to link it (no copy,
        # no loss). Adding/duplicating also auto-links it, but this is explicit.
        has_loose = cur < 0 and layer.get_frame_at(context.scene.frame_current) is not None
        if has_loose:
            box = layout.box()
            box.label(text="Current drawing isn't a cell", icon='INFO')
            box.operator("nuclear.cell_adopt", text="Link Current Drawing", icon='LINKED')

        row = layout.row(align=True)
        row.operator("nuclear.cell_add", text="Add", icon='ADD').copy_exposed = False
        row.operator("nuclear.cell_add", text="Duplicate", icon='DUPLICATE').copy_exposed = True
        layout.operator("nuclear.cell_delete", text="Delete", icon='REMOVE')

        box = layout.box()
        box.label(text="Library", icon='ASSET_MANAGER')
        col = box.column(align=True)
        col.operator("nuclear.cells_import", text="Import…", icon='IMPORT')
        sub = col.row(align=True)
        sub.enabled = n > 0
        sub.operator("nuclear.cells_export", text="Export…", icon='EXPORT')


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_classes = (
    NUCLEAR_OT_cell_step,
    NUCLEAR_OT_cell_add,
    NUCLEAR_OT_cell_adopt,
    NUCLEAR_OT_cell_delete,
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

    # Keymap: brackets step cells in Object Mode (free there; brush size only
    # binds them in paint modes). Adjustable; guarded on the addon keyconfig.
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
    for km, kmi in _addon_keymaps:
        km.keymap_items.remove(kmi)
    _addon_keymaps.clear()

    del bpy.types.WindowManager.nuclear_cell_index

    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
