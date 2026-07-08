# SPDX-FileCopyrightText: 2026 Rapadura Atômica
# SPDX-FileCopyrightText: 2020-2023 Blender Authors (derived from the 2D Animation template)
#
# SPDX-License-Identifier: GPL-2.0-or-later

# Initialization script for the Nuclear application template.
#
# This template is the "seam" for Nuclear's UI overhaul: it is the single place where
# native Blender panels/menus are hidden or relocated and where UI labels are renamed,
# WITHOUT editing upstream files in-place (keeps rebase divergence near zero).
# See tools/nuclear_claude/CLAUDE.md and NUCLEAR_DIVERGENCE.md.
#
# NOTE: startup.blend here is currently a copy of the 2D Animation layout, used as a
# base. Regenerate it from inside Nuclear once the target 2D/cut-out layout is designed:
# arrange the desired editors/panels, then File > Defaults > Save Startup File while this
# template is active (or save a .blend over this file). The screen names referenced below
# come from that startup.blend.

import bpy
from bpy.app.handlers import persistent

# GPU/text modules for the Toon Boom-style Xsheet timeline (Seam 7). Guarded so a build
# without the gpu module still loads the template (the Xsheet just won't draw).
try:
    import gpu
    import blf
    from gpu_extras.batch import batch_for_shader
    _GPU_OK = True
except Exception:
    _GPU_OK = False


# --------------------------------------------------------------------------------------
# Startup screen / scene configuration (applied after the template's startup.blend loads)
# --------------------------------------------------------------------------------------

def _update_startup_screens():
    # Defensive: screen names depend on the bundled startup.blend. Guard each lookup so a
    # regenerated .blend with different screen names never breaks template registration.
    # (Per-box Properties context is handled by _apply_default_tabs, not here.)
    screen = bpy.data.screens.get("2D Animation")
    if screen is not None:
        for area in screen.areas:
            if area.type == 'DOPESHEET_EDITOR':
                try:
                    area.spaces.active.show_region_ui = True
                except Exception:
                    pass

    screen = bpy.data.screens.get("2D Full Canvas")
    if screen is not None:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                space = area.spaces.active
                space.shading.type = 'MATERIAL'
                space.shading.use_scene_world = True


def _update_startup_scenes():
    for scene in bpy.data.scenes:
        scene.tool_settings.use_keyframe_insert_auto = True
        scene.tool_settings.gpencil_sculpt.use_scale_thickness = True


def _update_startup_grease_pencils():
    for grease_pencil in bpy.data.grease_pencils:
        grease_pencil.onion_keyframe_type = 'ALL'


# --------------------------------------------------------------------------------------
# Seam 1 — UI label remapping (the "translation trick")
#   Rename native labels in bulk (e.g. "Object" -> "...", "Grease Pencil" -> "...")
#   without touching IFACE_() strings in C. Fill _TRANSLATIONS as the naming is decided
#   (P1 of the roadmap). Format: {locale: {(context, source): translated}}.
# --------------------------------------------------------------------------------------

# Format: {locale: {(context, source): translated}}. "*" = the default i18n context
# (what IFACE_() uses). Registered under "en_US" and applied with interface translation
# enabled (see _ensure_interface_translation) so the overrides show even in English.
#
# This currently holds only pure branding (Blender -> Nuclear) on residual UI strings
# that the C-level branding pass would otherwise have to chase in hot files. The
# feature-level nomenclature remap (e.g. "Object"/"Grease Pencil" -> Nuclear terms) is
# added here once the scope document fixes the final naming.
_TRANSLATIONS = {
    "en_US": {
        ("*", "Blender Version"): "Nuclear Version",
        ("*", "Blender Drivers Editor"): "Nuclear Drivers Editor",
        ("*", "Blender Info Log"): "Nuclear Info Log",
        ("*", "Load Factory Blender Preferences"): "Load Factory Nuclear Preferences",
        ("*", "Blender File View"): "Nuclear File View",
        ("*", "Blender Preferences"): "Nuclear Preferences",
        # Save/load dialogs (wm_files.cc).
        ("*", "Blender will start next time as it is now."):
            "Nuclear will start next time as it is now.",
        ("*", "This file was saved by a newer version of Blender (%s)."):
            "This file was saved by a newer version of Nuclear (%s).",
        ("*", "Saving it with this Blender (%s) may cause loss of data."):
            "Saving it with this Nuclear (%s) may cause loss of data.",
        ("*", "This file is managed by the Blender asset system. It can only be"):
            "This file is managed by the Nuclear asset system. It can only be",
        ("*", "with an older Blender version?"): "with an older Nuclear version?",
        ("*", "Overwrite file with an older Blender version?"):
            "Overwrite file with an older Nuclear version?",
        # File browser filters (rna_space.cc / space_filebrowser.py).
        ("*", "Filter Blender"): "Filter Nuclear",
        ("*", "Filter Blender Backup Files"): "Filter Nuclear Backup Files",
        ("*", "Filter Blender IDs"): "Filter Nuclear IDs",
        ("*", "Blender IDs"): "Nuclear IDs",
        ("*", "Blender File"): "Nuclear File",
    },
}


def _ensure_interface_translation():
    # The translation overrides above only take effect when interface translation is on
    # and the active language matches a registered locale. Force both so Nuclear's labels
    # show regardless of the user's prior preference. (pt_BR/others can be added later.)
    try:
        view = bpy.context.preferences.view
        view.use_translate_interface = True
        view.language = 'en_US'
    except Exception:
        pass


def _register_translations():
    if _TRANSLATIONS:
        try:
            bpy.app.translations.register(__name__, _TRANSLATIONS)
        except Exception:
            # Already registered (e.g. register() called twice) — don't crash.
            pass
        _ensure_interface_translation()


def _unregister_translations():
    if _TRANSLATIONS:
        bpy.app.translations.unregister(__name__)


# --------------------------------------------------------------------------------------
# Seam 2 — UI overrides (hide / relocate native panels & menus)
#   Hide a native class by unregistering it; register Nuclear replacements here.
#   Populate as the overhaul proceeds (P2 of the roadmap). Kept reversible so the
#   template can be toggled cleanly. Prefer this over editing scripts/startup/bl_ui/*.
# --------------------------------------------------------------------------------------

# Phase A — Nuclear's own "View" menu shown in the curated top menu bar. Kept to entries
# that work from the topbar context (screen/window level); enriched later once the Nuclear
# viewport context exists.
# Phase A — the clickable Nuclear logo menu (replaces the native "Blender" app menu).
# Same options the user asked for; reuses the generic, unbranded "System" submenu.
class NUCLEAR_MT_logo(bpy.types.Menu):
    bl_idname = "NUCLEAR_MT_logo"
    bl_label = "Nuclear"

    def draw(self, _context):
        layout = self.layout
        layout.operator("wm.splash", text="Splash Screen")
        layout.operator("wm.splash_about", text="About Nuclear")
        layout.separator()
        layout.operator("preferences.app_template_install", text="Install Application Template...")
        layout.separator()
        layout.menu("TOPBAR_MT_blender_system", text="System")


# Phase A — Nuclear's own "View" menu shown in the curated top menu bar. Kept to entries
# that work from the topbar context (screen/window level); enriched later once the Nuclear
# viewport context exists.
class NUCLEAR_MT_view(bpy.types.Menu):
    bl_idname = "NUCLEAR_MT_view"
    bl_label = "View"

    def draw(self, _context):
        layout = self.layout
        layout.operator("screen.screen_full_area", text="Toggle Maximize Area").use_hide_panels = False
        layout.operator(
            "screen.screen_full_area", text="Toggle Fullscreen Area",
        ).use_hide_panels = True
        layout.operator("wm.window_fullscreen_toggle", text="Toggle System Fullscreen")


# Phase D (100%) — right-panel tabs. Each tab switches the area's OWN editor type, so two
# stacked right areas reproduce the mockup's two tabbed boxes. Per-box DISTINCT tab subsets
# are achieved WITHOUT a DNA change: named tab-sets are assigned to areas by position at
# load time (top-right = "main", the one below = "shading"). See _assign_tabsets.
#   label -> (area.ui_type, properties-context-or-"")
_TAB_DEFS = {
    "Properties": ('PROPERTIES', 'TOOL'),
    "Reference": ('IMAGE_EDITOR', ''),
    "Library": ('ASSETS', ''),
    "Color": ('PROPERTIES', 'MATERIAL'),
    # "Node" tab = Nuclear's Peg Graph (custom node tree from nuclear_peg_graph.py),
    # not the generic shader editor.
    "Peg Graph": ('NuclearPegTree', ''),
}
# Per-box tab subsets (mockup: top box vs bottom box).
_TABSETS = {
    "main": ["Properties", "Reference", "Library"],
    "shading": ["Color", "Peg Graph"],
    "all": ["Properties", "Reference", "Library", "Color", "Peg Graph"],
}
# Editor types that participate in the right-panel tab system.
_TAB_TARGET_AREA_TYPES = {'PROPERTIES', 'IMAGE_EDITOR', 'NODE_EDITOR', 'FILE_BROWSER'}
# Resolved at load time: {(screen.name, area_index): tabset_name}.
_AREA_SETS = {}


def _assign_tabsets():
    # Assign a tab-set to each right-side area by vertical position: topmost = "main",
    # the rest = "shading". Areas with no assignment fall back to "all". Deterministic from
    # the layout, so it's stable across sessions without serializing anything.
    _AREA_SETS.clear()
    for screen in bpy.data.screens:
        targets = [
            (i, area) for i, area in enumerate(screen.areas)
            if area.type in _TAB_TARGET_AREA_TYPES
        ]
        if len(targets) < 2:
            continue
        targets.sort(key=lambda t: -t[1].y)  # higher y = higher on screen = top
        _AREA_SETS[(screen.name, targets[0][0])] = "main"
        for i, _area in targets[1:]:
            _AREA_SETS[(screen.name, i)] = "shading"


def _resolve_tabset(context):
    area = context.area
    screen = context.screen
    if area is None or screen is None:
        return _TABSETS["all"]
    try:
        idx = list(screen.areas).index(area)
    except Exception:
        return _TABSETS["all"]
    return _TABSETS.get(_AREA_SETS.get((screen.name, idx), "all"), _TABSETS["all"])


def _apply_default_tabs():
    # Park each assigned right area on the FIRST tab of its set (main->Properties,
    # shading->Color). Guarded: the Properties context enum can be empty mid-load.
    for (screen_name, idx), setname in _AREA_SETS.items():
        screen = bpy.data.screens.get(screen_name)
        if screen is None or idx >= len(screen.areas):
            continue
        area = screen.areas[idx]
        tabnames = _TABSETS.get(setname) or []
        if not tabnames:
            continue
        ui_type, prop_ctx = _TAB_DEFS[tabnames[0]]
        try:
            area.ui_type = ui_type
        except Exception:
            continue
        if prop_ctx and area.type == 'PROPERTIES':
            try:
                area.spaces.active.context = prop_ctx
            except Exception:
                pass


class NUCLEAR_OT_set_area_tab(bpy.types.Operator):
    bl_idname = "nuclear.set_area_tab"
    bl_label = "Panel Tab"
    bl_description = "Switch this panel to the chosen content"
    bl_options = {'INTERNAL'}

    ui_type: bpy.props.StringProperty()
    prop_context: bpy.props.StringProperty(default="")

    def execute(self, context):
        area = context.area
        if area is None:
            return {'CANCELLED'}
        try:
            area.ui_type = self.ui_type
        except Exception:
            return {'CANCELLED'}
        if self.prop_context and area.type == 'PROPERTIES':
            try:
                area.spaces.active.context = self.prop_context
            except Exception:
                pass
        return {'FINISHED'}


class NUCLEAR_OT_palette_add(bpy.types.Operator):
    # Color-palette "+": create a real Grease Pencil material (not an empty slot) so the new
    # entry is immediately editable (swatch + name). Plain object.material_slot_add adds an
    # empty slot with no material -> nothing to edit, which is the bug this fixes.
    bl_idname = "nuclear.palette_add"
    bl_label = "Add Color"
    bl_description = "Add a new color (Grease Pencil material) to the palette"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.type == 'GREASEPENCIL'

    def execute(self, context):
        ob = context.object
        mat = bpy.data.materials.new(name="Color")
        try:
            bpy.data.materials.create_gpencil_data(mat)
            mat.grease_pencil.show_stroke = True
        except Exception:
            pass
        ob.data.materials.append(mat)
        ob.active_material_index = len(ob.material_slots) - 1
        return {'FINISHED'}


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
            context.scene.frame_current = hit[1]
            if hit[2] is not None:
                try:
                    ob.data.layers.active = layers[hit[2]]
                except Exception:
                    pass
            if context.area:
                context.area.tag_redraw()
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}

    def modal(self, context, event):
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
    # it (layer.frames.copy). Both preserve the drawing. A ghost cell previews the target
    # frame while dragging (_xsheet_drag, read by the draw handler).
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
        _xsheet_drag = {"row": row, "from": f, "to": f, "dup": self.duplicate}
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
            layers = list(ob.data.layers)
            d = _xsheet_drag
            _xsheet_drag = None
            layer = layers[d["row"]] if d["row"] < len(layers) else None
            src, dst = d["from"], d["to"]
            if layer is not None and dst != src:
                existing = [fr.frame_number for fr in layer.frames]
                if dst not in existing:
                    try:
                        if d["dup"]:
                            layer.frames.copy(src, dst)
                        else:
                            layer.frames.move(src, dst)
                        ob.data.update_tag()
                    except Exception as e:
                        self.report({'WARNING'}, "Exposição: {:s}".format(str(e)))
            context.scene.frame_current = dst
            if context.area:
                context.area.tag_redraw()
            return {'FINISHED'}
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            _xsheet_drag = None
            if context.area:
                context.area.tag_redraw()
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


class NUCLEAR_MT_add_tab(bpy.types.Menu):
    bl_idname = "NUCLEAR_MT_add_tab"
    bl_label = "Add Tab"

    def draw(self, _context):
        layout = self.layout
        for label, ui_type, prop_ctx in (
            ("Image", 'IMAGE_EDITOR', ''),
            ("Compositor", 'CompositorNodeTree', ''),
            ("Outliner", 'OUTLINER', ''),
            ("Spreadsheet", 'SPREADSHEET', ''),
        ):
            op = layout.operator("nuclear.set_area_tab", text=label)
            op.ui_type = ui_type
            op.prop_context = prop_ctx


# Phase A — Nuclear's own "View" menu shown in the curated top menu bar. Kept to entries
# that work from the topbar context (screen/window level); enriched later once the Nuclear
# viewport context exists.
class NUCLEAR_MT_view(bpy.types.Menu):
    bl_idname = "NUCLEAR_MT_view"
    bl_label = "View"

    def draw(self, _context):
        layout = self.layout
        layout.operator("screen.screen_full_area", text="Toggle Maximize Area").use_hide_panels = False
        layout.operator(
            "screen.screen_full_area", text="Toggle Fullscreen Area",
        ).use_hide_panels = True
        layout.operator("wm.window_fullscreen_toggle", text="Toggle System Fullscreen")


# Phase D (#9) — the Color tab: a clean palette of the object's GP materials, faithful to
# the mockup. Each row = a rounded color swatch (theme roundness) + the material name (what
# the color is for, e.g. "Line Personagem 1"), renamable inline. The native row clutter
# (ghost/hide/lock) and the stroke/fill marks+dropdowns are gone; the verbose native material
# sub-panels are hidden via _HIDDEN_CLASS_NAMES.
class NUCLEAR_UL_color_palette(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, icon, _active_data, _active_propname, _index):
        ma = item.material
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            gp = ma.grease_pencil if (ma is not None) else None
            if gp is not None:
                # Swatch = the enabled color (stroke if shown, else fill). Rounded via theme.
                swatch = "fill_color" if (gp.show_fill and not gp.show_stroke) else "color"
                sub = row.row(align=True)
                sub.scale_x = 0.5
                sub.prop(gp, swatch, text="")
                row.separator(factor=0.6)
                row.prop(ma, "name", text="", emboss=False)
            elif ma is not None:
                row.prop(ma, "name", text="", emboss=False, icon_value=icon)
            else:
                row.label(text="", icon_value=icon)
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon_value=icon)


class NUCLEAR_PT_color_palette(bpy.types.Panel):
    bl_idname = "NUCLEAR_PT_color_palette"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"
    bl_label = "Color Palette"
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, context):
        ob = context.object
        return ob is not None and ob.type == 'GREASEPENCIL'

    def draw(self, context):
        layout = self.layout
        ob = context.object
        layout.label(text="Color Palette")
        row = layout.row()
        row.template_list(
            "NUCLEAR_UL_color_palette", "", ob, "material_slots", ob, "active_material_index", rows=10,
        )
        # Discreet palette management (add / remove / reorder). No stroke/fill editing here.
        col = row.column(align=True)
        col.operator("nuclear.palette_add", icon='ADD', text="")
        col.operator("object.material_slot_remove", icon='REMOVE', text="")
        if len(ob.material_slots) > 1:
            col.separator()
            col.operator("object.material_slot_move", icon='TRIA_UP', text="").direction = 'UP'
            col.operator("object.material_slot_move", icon='TRIA_DOWN', text="").direction = 'DOWN'


# Native classes to hide (by name) while the template is active. Resolved at apply time so
# import order is irrelevant; re-registered on revert. The GP material sub-panels are hidden
# to keep the Color tab compact (the palette + quick color edit live in NUCLEAR_PT_color_palette).
_HIDDEN_CLASS_NAMES = [
    "MATERIAL_PT_gpencil_slots",
    "MATERIAL_PT_gpencil_surface",   # parent → also hides Stroke/Fill children
    "MATERIAL_PT_gpencil_animation",
    "MATERIAL_PT_gpencil_preview",
    "MATERIAL_PT_gpencil_custom_props",
    "MATERIAL_PT_gpencil_settings",
]
# Nuclear's own panels/menus to register.
_NUCLEAR_CLASSES = [
    NUCLEAR_OT_set_area_tab,
    NUCLEAR_OT_palette_add,
    NUCLEAR_OT_xsheet_click,
    NUCLEAR_OT_xsheet_toggle,
    NUCLEAR_OT_xsheet_drag,
    NUCLEAR_MT_add_tab,
    NUCLEAR_UL_color_palette,
    NUCLEAR_PT_color_palette,
    NUCLEAR_MT_logo,
    NUCLEAR_MT_view,
]

_unregistered = []


def _apply_ui_overrides():
    for name in _HIDDEN_CLASS_NAMES:
        cls = getattr(bpy.types, name, None)
        if cls is None:
            continue
        try:
            bpy.utils.unregister_class(cls)
            _unregistered.append(cls)
        except Exception:
            pass
    for cls in _NUCLEAR_CLASSES:
        bpy.utils.register_class(cls)


def _revert_ui_overrides():
    for cls in reversed(_NUCLEAR_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    for cls in reversed(_unregistered):
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass
    _unregistered.clear()


# --------------------------------------------------------------------------------------
# Seam 3 — header draw overrides (Phase A: top menu bar + viewport header)
#   Some native headers draw their items inline (not as separable classes), so they can't
#   be curated by unregistering. Instead we swap the .draw method for a Nuclear version and
#   restore the original on unregister. This is the seam for the "airplane-cockpit"
#   simplification. Each override is recorded in NUCLEAR_UI_LAYOUT.md.
# --------------------------------------------------------------------------------------

# Saved originals: {(bpy.types class, attr): original function}.
_orig_draws = {}

# Preview collection holding the Nuclear logo PNG shown in the top bar corner.
_preview_icons = None


def _load_logo():
    global _preview_icons
    import os
    import bpy.utils.previews
    _preview_icons = bpy.utils.previews.new()
    logo_path = os.path.join(os.path.dirname(__file__), "nuclear_logo.png")
    try:
        _preview_icons.load("nuclear_logo", logo_path, 'IMAGE')
    except Exception:
        pass


def _unload_logo():
    global _preview_icons
    if _preview_icons is not None:
        try:
            import bpy.utils.previews
            bpy.utils.previews.remove(_preview_icons)
        except Exception:
            pass
        _preview_icons = None


def _nuclear_editor_menus_draw(self, context):
    # Curated top menu bar: File, Edit, View, Render, Help.
    # Drops the "Blender" app menu and the "Window" menu (clutter / branding).
    layout = self.layout
    layout.menu("TOPBAR_MT_file")
    layout.menu("TOPBAR_MT_edit")
    layout.menu("NUCLEAR_MT_view")
    layout.menu("TOPBAR_MT_render")
    layout.menu("TOPBAR_MT_help")


def _nuclear_topbar_draw_left(self, context):
    # Left side of the top bar: Nuclear logo + the curated menus. The native workspace
    # tabs are intentionally hidden (Nuclear is a single-workspace app); the fullscreen
    # "Back to Previous" affordance is preserved.
    from bl_ui.space_topbar import TOPBAR_MT_editor_menus
    layout = self.layout
    screen = context.screen
    # Clickable Nuclear logo -> the app menu (Splash, About, Install Template, System).
    if _preview_icons is not None and "nuclear_logo" in _preview_icons:
        layout.menu("NUCLEAR_MT_logo", text="", icon_value=_preview_icons["nuclear_logo"].icon_id)
    else:
        layout.menu("NUCLEAR_MT_logo", text="Nuclear")
    TOPBAR_MT_editor_menus.draw_collapsible(context, layout)
    if screen.show_fullscreen:
        layout.separator(type='LINE')
        layout.operator("screen.back_to_previous", icon='SCREEN_BACK', text="Back to Previous")


def _nuclear_view3d_header_draw(self, context):
    # Minimal viewport header: just the mode selector ("Draw Mode" etc.). The native
    # View/Select/Add/Object menus and the shading/overlay/gizmo popovers are intentionally
    # dropped here to keep the canvas row clean (functions remain reachable elsewhere).
    layout = self.layout
    obj = context.active_object
    object_mode = 'OBJECT' if obj is None else obj.mode
    row = layout.row(align=True)
    try:
        act_mode_item = bpy.types.Object.bl_rna.properties["mode"].enum_items[object_mode]
        row.operator_menu_enum(
            "object.mode_set", "mode",
            text=act_mode_item.name, icon=act_mode_item.icon,
        )
    except Exception:
        row.operator_menu_enum("object.mode_set", "mode")

    # Onion skin on/off (viewport visualization). space_data here is the View3D.
    overlay = getattr(context.space_data, "overlay", None)
    if overlay is not None and hasattr(overlay, "use_gpencil_onion_skin"):
        layout.separator()
        icon = 'ONIONSKIN_ON' if overlay.use_gpencil_onion_skin else 'ONIONSKIN_OFF'
        layout.prop(overlay, "use_gpencil_onion_skin", text="Onion", icon=icon, toggle=True)


# Phase E — the DYNAMIC "ADDONS" bar (mockup row 3), drawn in the viewport TOOL_HEADER.
# Concept: panels that addons register into the right N-panel (sidebar) are surfaced HERE as
# popover groups, so the sidebar's content moves to the top and the bar grows/shrinks as
# addons (and their categories) come and go. Brush settings live in the right Properties/Tool
# tab, so this row is free. `popover_group` only draws panels that pass their poll in the
# current mode, so the bar stays lean.

_sidebar_cats_cache = None
_sidebar_cats_stamp = 0.0


def _sidebar_categories():
    # Distinct categories of the VIEW_3D sidebar (N-panel) across registered panels.
    # Scanning all of dir(bpy.types) on every tool-header redraw was a per-draw O(types)
    # cost (viewport stutter, worse with many add-ons); throttle to ~1 Hz so newly
    # (un)registered addon panels still appear/disappear "live" within a second.
    import time
    global _sidebar_cats_cache, _sidebar_cats_stamp
    now = time.monotonic()
    if _sidebar_cats_cache is not None and (now - _sidebar_cats_stamp) < 1.0:
        return _sidebar_cats_cache
    seen = set()
    cats = []
    types = bpy.types
    for name in dir(types):
        cls = getattr(types, name, None)
        if (isinstance(cls, type)
                and getattr(cls, "bl_space_type", None) == 'VIEW_3D'
                and getattr(cls, "bl_region_type", None) == 'UI'):
            cat = getattr(cls, "bl_category", "")
            if cat and cat not in seen:
                seen.add(cat)
                cats.append(cat)
    cats.sort()
    _sidebar_cats_cache = cats
    _sidebar_cats_stamp = now
    return cats


def _nuclear_tool_header_draw(self, context):
    layout = self.layout
    for cat in _sidebar_categories():
        layout.popover_group(space_type='VIEW_3D', region_type='UI', context="", category=cat)
    layout.separator_spacer()


def _draw_nuclear_transport(layout, context):
    # Phase C — the simplified transport row shown atop the bottom Dope Sheet (GP mode):
    # audio (left) · +KF/-KF · play controls · frame/start/end (right). Mirrors the mockup.
    scene = context.scene
    screen = context.screen
    if scene is None:
        return

    # Audio: mute + scrubbing.
    row = layout.row(align=True)
    row.prop(scene, "use_audio", text="Mute", toggle=True)
    row.prop(scene, "use_audio_scrub", text="Scrub", toggle=True)

    layout.separator_spacer()

    # Keyframe add/remove (GP frames). NOTE: insert_blank_frame/delete_frame; swap the
    # "+ KF" op for grease_pencil.frame_duplicate if "duplicate current drawing" is wanted.
    row = layout.row(align=True)
    row.operator("grease_pencil.insert_blank_frame", text="+ KF", icon='KEYFRAME')
    row.operator("grease_pencil.delete_frame", text="- KF", icon='KEYFRAME_HLT')

    # Transport.
    row = layout.row(align=True)
    row.operator("screen.frame_jump", text="", icon='REW').end = False
    if screen.is_animation_playing:
        row.operator("screen.animation_play", text="", icon='PAUSE')
    else:
        row.operator("screen.animation_play", text="", icon='PLAY')
    row.operator("screen.frame_jump", text="", icon='FF').end = True

    layout.separator_spacer()

    # Frame fields (right).
    row = layout.row(align=True)
    row.prop(scene, "frame_current", text="Frame")
    sub = row.row(align=True)
    sub.prop(scene, "frame_start", text="Start")
    sub.prop(scene, "frame_end", text="End")


def _nuclear_dopesheet_header_draw(self, context):
    # In Grease Pencil mode, replace the Dope Sheet header with the Nuclear transport.
    # Other dope-sheet modes fall back to the saved original draw (untouched).
    st = context.space_data
    if st.mode == 'GPENCIL':
        _draw_nuclear_transport(self.layout, context)
        return
    orig = _orig_draws.get((bpy.types.DOPESHEET_HT_header, "draw"))
    if orig is not None:
        orig(self, context)


def _draw_nuclear_tabs(layout, context):
    # Phase D — the right-panel tab strip. Tabs come from the area's assigned tab-set
    # (per-box subset). Highlights the active tab by the area's editor type (+ Properties
    # context). Shown on every tab-target editor header so the user can always switch back.
    area = context.area
    if area is None:
        return
    row = layout.row(align=True)
    for label in _resolve_tabset(context):
        ui_type, prop_ctx = _TAB_DEFS[label]
        active = (area.ui_type == ui_type)
        if active and prop_ctx and area.type == 'PROPERTIES':
            active = (area.spaces.active.context == prop_ctx)
        op = row.operator("nuclear.set_area_tab", text=label, depress=active)
        op.ui_type = ui_type
        op.prop_context = prop_ctx
    row.menu("NUCLEAR_MT_add_tab", text="", icon='ADD')
    layout.separator()


def _make_tabbed_header_draw(cls_name):
    # Returns a draw that prepends the Nuclear tab strip, then calls the editor's original
    # header (looked up at draw time from the saved originals).
    def draw(self, context):
        _draw_nuclear_tabs(self.layout, context)
        cls = getattr(bpy.types, cls_name, None)
        orig = _orig_draws.get((cls, "draw"))
        if orig is not None:
            orig(self, context)
    return draw


def _nuclear_help_menu_draw(self, context):
    # Curated Help menu: keeps the useful references, drops the blender.org community
    # links (branding). Manual/API presets still point at the upstream documentation on
    # purpose — that is the real reference for the engine. Bugs go to the Nuclear tracker.
    layout = self.layout
    layout.operator("wm.url_open_preset", text="Manual", icon='URL').type = 'MANUAL'
    layout.operator("wm.url_open", text="Nuclear Website").url = "https://rapaduraatomica.com.br"
    layout.operator(
        "wm.url_open", text="What's New",
    ).url = "https://github.com/Rapadura-Atomica/Nuclear/releases"
    layout.separator()
    if context.preferences.view.show_developer_ui:
        layout.operator("wm.url_open_preset", text="Python API Reference").type = 'API'
        layout.operator("wm.operator_cheat_sheet", icon='TEXT')
        layout.separator()
    layout.operator(
        "wm.url_open", text="Report a Bug", icon='URL',
    ).url = "https://github.com/Rapadura-Atomica/Nuclear/issues"
    layout.operator("wm.sysinfo")


# Overrides applied while the template is active: (bpy.types class name, attr, Nuclear fn).
# Generalized to any method (not just "draw") so headers that dispatch (e.g. draw_left)
# can be curated too.
_HEADER_OVERRIDES = [
    ("TOPBAR_MT_editor_menus", "draw", _nuclear_editor_menus_draw),
    ("TOPBAR_MT_help", "draw", _nuclear_help_menu_draw),
    ("TOPBAR_HT_upper_bar", "draw_left", _nuclear_topbar_draw_left),
    ("VIEW3D_HT_header", "draw", _nuclear_view3d_header_draw),
    ("VIEW3D_HT_tool_header", "draw", _nuclear_tool_header_draw),  # Phase E — ADDONS bar
    ("DOPESHEET_HT_header", "draw", _nuclear_dopesheet_header_draw),
    # Phase D — tab strip on every tab-target editor (so any right area can switch content).
    ("PROPERTIES_HT_header", "draw", _make_tabbed_header_draw("PROPERTIES_HT_header")),
    ("IMAGE_HT_header", "draw", _make_tabbed_header_draw("IMAGE_HT_header")),
    ("NODE_HT_header", "draw", _make_tabbed_header_draw("NODE_HT_header")),
    ("FILEBROWSER_HT_header", "draw", _make_tabbed_header_draw("FILEBROWSER_HT_header")),
]


def _make_safe_override(cls, attr, fn):
    # Wrap a header override so a raise (e.g. after an upstream rebase renames a symbol
    # the override depends on) degrades to the saved original draw instead of leaving the
    # whole header blank. Mirrors the defensive try/except the Xsheet draw already uses.
    def safe(self, context):
        try:
            return fn(self, context)
        except Exception:
            import traceback
            traceback.print_exc()
            orig = _orig_draws.get((cls, attr))
            if orig is not None:
                try:
                    return orig(self, context)
                except Exception:
                    pass
    return safe


def _apply_header_overrides():
    for cls_name, attr, fn in _HEADER_OVERRIDES:
        cls = getattr(bpy.types, cls_name, None)
        if cls is None:
            continue
        # Guard against capturing an already-patched function as the "original" if
        # register() runs twice without an unregister() (script reload / re-activate).
        if (cls, attr) not in _orig_draws:
            _orig_draws[(cls, attr)] = getattr(cls, attr)
        setattr(cls, attr, _make_safe_override(cls, attr, fn))


def _revert_header_overrides():
    for (cls, attr), orig in _orig_draws.items():
        setattr(cls, attr, orig)
    _orig_draws.clear()


# --------------------------------------------------------------------------------------
# Seam 4 — toolbar curation (Phase B: Grease Pencil Draw mode toolbar)
#   The toolbar is generated from VIEW3D_PT_tools_active._tools (a {mode: [ToolDef,...]}
#   class dict). We swap the 'PAINT_GREASE_PENCIL' entry for a curated, minimal set and
#   restore the original dict on unregister. Hidden tools are not removed — their operators
#   stay reachable via menus/shortcuts; they're just dropped from the tool bar.
# --------------------------------------------------------------------------------------

# Saved original _tools dict of VIEW3D_PT_tools_active (None until applied).
_orig_tools = None


def _build_nuclear_gp_draw_tools():
    # Curated Draw-mode toolbar: brush, eraser, fill (bucket), the line/shape group
    # (line first = default), and the color eyedropper. Returns None if the upstream tool
    # defs can't be resolved (then we leave the native toolbar untouched).
    import importlib
    try:
        tb = importlib.import_module("bl_ui.space_toolsystem_toolbar")
        panel = tb.VIEW3D_PT_tools_active
        gp = tb._defs_grease_pencil_paint
        return [
            panel._brush_tool,
            gp.erase,
            gp.fill,
            None,
            (gp.line, gp.polyline, gp.box, gp.circle, gp.arc, gp.curve),
            None,
            gp.eyedropper,
        ]
    except Exception:
        return None


def _apply_toolbar_overrides():
    global _orig_tools
    import importlib
    try:
        panel = importlib.import_module("bl_ui.space_toolsystem_toolbar").VIEW3D_PT_tools_active
    except Exception:
        return
    curated = _build_nuclear_gp_draw_tools()
    if curated is None:
        return
    _orig_tools = panel._tools
    new_tools = dict(_orig_tools)
    new_tools['PAINT_GREASE_PENCIL'] = curated
    panel._tools = new_tools


def _revert_toolbar_overrides():
    global _orig_tools
    if _orig_tools is None:
        return
    import importlib
    try:
        panel = importlib.import_module("bl_ui.space_toolsystem_toolbar").VIEW3D_PT_tools_active
        panel._tools = _orig_tools
    except Exception:
        pass
    _orig_tools = None


# --------------------------------------------------------------------------------------
# Canvas curation (Phase A): camera-locked viewport, 3D overlays/gizmos hidden.
#   Applied on every startup-file load across all VIEW_3D areas (name-agnostic so a
#   regenerated startup.blend keeps working). Grease Pencil overlays stay on; only the
#   3D scaffolding (floor, axes, grid, cursor, navigation/tool gizmos) is hidden.
# --------------------------------------------------------------------------------------

def _update_startup_canvas():
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != 'VIEW_3D':
                continue
            space = area.spaces.active
            # Lock the view to the camera (the drawing frame).
            try:
                space.region_3d.view_perspective = 'CAMERA'
            except Exception:
                pass
            # Hide all gizmos (navigation + tool) for a clean canvas.
            space.show_gizmo = False
            # Show the tool header — Nuclear draws the ADDONS launcher bar there (Phase E).
            try:
                space.show_region_tool_header = True
            except Exception:
                pass
            # Keep overlays on (Grease Pencil needs them) but drop 3D scaffolding.
            overlay = space.overlay
            overlay.show_floor = False
            overlay.show_axis_x = False
            overlay.show_axis_y = False
            overlay.show_axis_z = False
            overlay.show_ortho_grid = False
            overlay.show_cursor = False


def _update_startup_timeline():
    # Phase C — make the bottom Dope Sheet show Grease Pencil layers (the channel list with
    # eye/lock = #15) and keyframes (#16). Name-agnostic across all DOPESHEET_EDITOR areas.
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != 'DOPESHEET_EDITOR':
                continue
            space = area.spaces.active
            try:
                space.mode = 'GPENCIL'
            except Exception:
                pass
            # Transport lives in the header (Nuclear override); keep the footer off so the
            # native playback_controls don't duplicate it.
            try:
                space.show_region_footer = False
            except Exception:
                pass
            # The Xsheet draws its own layer column, so hide the native channel list (removes
            # the duplicate Stroke/Lines/Fills list).
            try:
                space.show_region_channels = False
            except Exception:
                pass


# Phase D — Properties tabs kept for the 2D/cut-out workflow. Everything else (Render,
# Output, View Layer, Scene, World, Collection, Texture, and the 3D-only tabs that don't
# even show for a GP object) is hidden via SpaceProperties' native show_properties_* toggles.
# "Propriedades" (brush) = Tool; the named color palette (#9) = the native Material tab.
_PROPERTIES_KEEP = {
    "show_properties_tool",
    "show_properties_object",
    "show_properties_modifiers",
    "show_properties_effects",
    "show_properties_data",
    "show_properties_material",
}


def _update_startup_properties():
    import importlib
    try:
        tab_list = importlib.import_module("bl_ui.space_properties").tab_list
    except Exception:
        return
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != 'PROPERTIES':
                continue
            space = area.spaces.active
            for attr, _name, _icon in tab_list:
                try:
                    setattr(space, attr, attr in _PROPERTIES_KEEP)
                except Exception:
                    pass


# --------------------------------------------------------------------------------------
# Seam 6 — Nuclear theme: MOVED OUT to scripts/startup/nuclear_theme.py so the navy
# "pill" look is applied GLOBALLY (Nuclear + 2D Animation + Storyboarding), not only
# while this template is active. Still theme-data only, zero C divergence.


# --------------------------------------------------------------------------------------
# Seam 7 — Toon Boom-style Xsheet timeline (T1: read-only GPU render over the bottom Dope
# Sheet). Draws a grid of per-layer × per-frame cells: a filled cell = an exposed drawing,
# a bright square at the keyframe start, a "hold" bar across held frames. Frame ruler +
# playhead + layer-name column. The native dope sheet underneath is hidden by an opaque
# background. Interaction (modal) + editing come in T3/T4.
# --------------------------------------------------------------------------------------

_xsheet_handle = None
# Active drag (T4.1): {"row", "from", "to", "dup"} while moving/duplicating, else None.
_xsheet_drag = None

# Layout + palette (navy theme).
_XS = {
    "name_w": 150.0, "ruler_h": 20.0, "row_h": 22.0,
    "cell_min": 8.0, "cell_max": 22.0, "frame_cap": 400,
    "bg": (0.07, 0.07, 0.13, 1.0), "panel": (0.11, 0.11, 0.19, 1.0),
    "grid": (0.20, 0.20, 0.30, 1.0), "hold": (0.30, 0.34, 0.55, 1.0),
    "key": (0.55, 0.45, 0.95, 1.0), "play": (0.95, 0.55, 0.20, 1.0),
    "text": (0.90, 0.90, 0.96, 1.0),
    "active_row": (0.18, 0.16, 0.30, 1.0), "frame_col": (0.16, 0.16, 0.26, 1.0),
    "vis_on": (0.50, 0.80, 0.55, 1.0), "lock_on": (0.92, 0.62, 0.28, 1.0),
    "state_off": (0.24, 0.24, 0.30, 1.0),
    "grid5": (0.30, 0.30, 0.44, 1.0), "ghost": (0.95, 0.55, 0.20, 0.55),
    "num": (0.08, 0.06, 0.14, 1.0),
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
        hold_r, key_r, key_cells = [], [], []
        for ri, layer in enumerate(layers):
            y1 = top - ri * row_h
            y0 = y1 - row_h
            keys_sorted = sorted(fr.frame_number for fr in layer.frames)
            kindex = {k: i + 1 for i, k in enumerate(keys_sorted)}
            for f, kind in _xsheet_exposed(layer, f_lo, f_hi).items():
                x0, x1 = fx(f), fx(f + 1)
                if x1 <= name_w:
                    continue
                xc0 = clipx(x0)
                rect = (xc0 + 1, y0 + 2, x1 - 1, y1 - 2)
                if kind == 'key':
                    key_r.append(rect)
                    key_cells.append((xc0, (y0 + y1) * 0.5, kindex.get(f, 0), x1 - xc0))
                else:
                    hold_r.append(rect)
        fill(hold_r, _XS["hold"])
        fill(key_r, _XS["key"])

        # T4.1 — ghost cell preview while dragging a keyframe (move/duplicate target).
        if _xsheet_drag is not None and 0 <= _xsheet_drag["row"] < len(layers):
            gy1 = top - _xsheet_drag["row"] * row_h
            gx0, gx1 = fx(_xsheet_drag["to"]), fx(_xsheet_drag["to"] + 1)
            if gx1 > name_w:
                fill([(clipx(gx0) + 1, gy1 - row_h + 2, gx1 - 1, gy1 - 2)], _XS["ghost"])

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
        pass


def _enable_xsheet():
    global _xsheet_handle
    if _GPU_OK and _xsheet_handle is None:
        _xsheet_handle = bpy.types.SpaceDopeSheetEditor.draw_handler_add(
            _xsheet_draw, (), 'WINDOW', 'POST_PIXEL',
        )


def _disable_xsheet():
    global _xsheet_handle
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


def _unregister_xsheet_keymap():
    for km, kmi in _xsheet_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _xsheet_keymaps.clear()


# Alt+R in Object Mode sends the selected envelope/spine controllers back to their rest pose. The
# operator's poll fails (and, when nothing is eligible, it passes the event through) for non-
# controllers, so native Alt+R (Clear Rotation) keeps working everywhere else.
_envelope_reset_keymaps = []


def _register_envelope_reset_keymap():
    wm = bpy.context.window_manager
    kc = getattr(wm.keyconfigs, "addon", None)
    if kc is None:
        return
    km = kc.keymaps.new(name='Object Mode', space_type='EMPTY')
    kmi = km.keymap_items.new(
        "object.greasepencil_contour_reset", 'R', 'PRESS', alt=True)
    kmi.properties.mode = 'SELECTED'
    _envelope_reset_keymaps.append((km, kmi))


def _unregister_envelope_reset_keymap():
    for km, kmi in _envelope_reset_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _envelope_reset_keymaps.clear()


# Alt+R for the Curve deform: in Object Mode (curve active) it resets the whole Deform Curve; in
# Curve Edit Mode it resets the selected control points. Poll/PASS_THROUGH keep native Alt+R intact
# for any non-deform-curve.
_curve_reset_keymaps = []


def _register_curve_reset_keymap():
    wm = bpy.context.window_manager
    kc = getattr(wm.keyconfigs, "addon", None)
    if kc is None:
        return
    km_obj = kc.keymaps.new(name='Object Mode', space_type='EMPTY')
    kmi = km_obj.keymap_items.new("object.greasepencil_curve_reset", 'R', 'PRESS', alt=True)
    kmi.properties.mode = 'ALL'
    _curve_reset_keymaps.append((km_obj, kmi))

    km_edit = kc.keymaps.new(name='Curve', space_type='EMPTY')
    kmi2 = km_edit.keymap_items.new("object.greasepencil_curve_reset", 'R', 'PRESS', alt=True)
    kmi2.properties.mode = 'SELECTED'
    _curve_reset_keymaps.append((km_edit, kmi2))


def _unregister_curve_reset_keymap():
    for km, kmi in _curve_reset_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _curve_reset_keymaps.clear()


# Discoverable reset while shaping a Deform Curve: the GP modifier panel (with the reset buttons) is
# not visible when the curve itself is the active object, so surface the same operator in the 3D
# View N-panel (Item tab) whenever a Deform Curve is active - in Object or Edit Mode.
class NUCLEAR_PT_deform_curve_reset(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Item"
    bl_label = "Deform Curve"

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return (ob is not None and ob.type == 'CURVE'
                and ob.get('nuclear_curve_rest') is not None)

    def draw(self, context):
        col = self.layout.column(align=True)
        col.operator("object.greasepencil_curve_reset", text="Reset Selected").mode = 'SELECTED'
        col.operator("object.greasepencil_curve_reset", text="Reset All").mode = 'ALL'


def _register_curve_reset_panel():
    try:
        bpy.utils.register_class(NUCLEAR_PT_deform_curve_reset)
    except Exception:
        # A real registration failure would otherwise vanish as a silently-missing N-panel.
        import traceback
        traceback.print_exc()


def _unregister_curve_reset_panel():
    try:
        bpy.utils.unregister_class(NUCLEAR_PT_deform_curve_reset)
    except Exception:
        pass


# --------------------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------------------

@persistent
def load_handler(_):
    _update_startup_screens()
    _update_startup_scenes()
    _update_startup_grease_pencils()
    _update_startup_canvas()
    _update_startup_timeline()
    _update_startup_properties()
    _assign_tabsets()
    _apply_default_tabs()
    if _TRANSLATIONS:
        _ensure_interface_translation()


def register():
    bpy.app.handlers.load_factory_startup_post.append(load_handler)
    _register_translations()
    _apply_ui_overrides()
    _load_logo()
    _apply_header_overrides()
    _apply_toolbar_overrides()
    # Nuclear theme is applied GLOBALLY by scripts/startup/nuclear_theme.py
    # (so it also covers 2D Animation / Storyboarding), not here.
    _enable_xsheet()
    _register_xsheet_keymap()
    _register_envelope_reset_keymap()
    _register_curve_reset_keymap()
    _register_curve_reset_panel()


def unregister():
    _unregister_curve_reset_panel()
    _unregister_curve_reset_keymap()
    _unregister_envelope_reset_keymap()
    _unregister_xsheet_keymap()
    _disable_xsheet()
    # Theme is owned globally by nuclear_theme.py (see register); nothing to revert here.
    _revert_toolbar_overrides()
    _revert_header_overrides()
    _unload_logo()
    _revert_ui_overrides()
    _unregister_translations()
    if load_handler in bpy.app.handlers.load_factory_startup_post:
        bpy.app.handlers.load_factory_startup_post.remove(load_handler)
