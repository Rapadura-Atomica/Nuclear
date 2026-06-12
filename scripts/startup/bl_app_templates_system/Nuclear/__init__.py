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
        bpy.app.translations.register(__name__, _TRANSLATIONS)
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


# Phase E — the DYNAMIC "ADDONS" bar (mockup row 3), drawn in the viewport TOOL_HEADER.
# Concept: panels that addons register into the right N-panel (sidebar) are surfaced HERE as
# popover groups, so the sidebar's content moves to the top and the bar grows/shrinks as
# addons (and their categories) come and go. Brush settings live in the right Properties/Tool
# tab, so this row is free. `popover_group` only draws panels that pass their poll in the
# current mode, so the bar stays lean.

def _sidebar_categories():
    # Distinct categories of the VIEW_3D sidebar (N-panel) across registered panels.
    # Recomputed each draw so newly (un)registered addon panels appear/disappear live.
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


# Overrides applied while the template is active: (bpy.types class name, attr, Nuclear fn).
# Generalized to any method (not just "draw") so headers that dispatch (e.g. draw_left)
# can be curated too.
_HEADER_OVERRIDES = [
    ("TOPBAR_MT_editor_menus", "draw", _nuclear_editor_menus_draw),
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


def _apply_header_overrides():
    for cls_name, attr, fn in _HEADER_OVERRIDES:
        cls = getattr(bpy.types, cls_name, None)
        if cls is None:
            continue
        _orig_draws[(cls, attr)] = getattr(cls, attr)
        setattr(cls, attr, fn)


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
# Seam 6 — Nuclear theme (the navy + rounded "pill" look). Done via theme data, NOT C:
#   the theme exposes per-widget `roundness` (0..1) + colors, so the mockup's rounded look
#   needs no interface_widgets.cc surgery (zero rebase risk). Applied on register, fully
#   restored on unregister (originals captured in _THEME_BACKUP).
# --------------------------------------------------------------------------------------

# RGB(A) 0..1. Navy base, purple/blue accents, light text — from the mockup.
_NUCLEAR_THEME = {
    "bg":       (0.07, 0.07, 0.13),
    "panel":    (0.11, 0.11, 0.19),
    "widget":   (0.15, 0.15, 0.25),
    "accent":   (0.42, 0.30, 0.84),
    "text":     (0.90, 0.90, 0.96),
    "text_sel": (1.00, 1.00, 1.00),
    "roundness": 0.6,
}

_THEME_WIDGET_GROUPS = [
    "wcol_regular", "wcol_tool", "wcol_toolbar_item", "wcol_radio", "wcol_text",
    "wcol_option", "wcol_toggle", "wcol_num", "wcol_numslider", "wcol_box",
    "wcol_menu", "wcol_pulldown", "wcol_menu_item", "wcol_list_item", "wcol_tab",
    "wcol_progress",
]
_THEME_SPACE_AREAS = [
    "view_3d", "properties", "dopesheet_editor", "image_editor", "node_editor",
    "file_browser", "outliner", "preferences",
]

# Captured originals: list of (object, attr, original_value) replayed on revert.
_THEME_BACKUP = []


def _theme_set(obj, attr, value):
    if obj is None or not hasattr(obj, attr):
        return
    try:
        cur = getattr(obj, attr)
        orig = tuple(cur) if hasattr(cur, "__len__") else cur
        setattr(obj, attr, value)
        _THEME_BACKUP.append((obj, attr, orig))
    except Exception:
        pass


def _apply_nuclear_theme():
    p = _NUCLEAR_THEME
    try:
        theme = bpy.context.preferences.themes[0]
    except Exception:
        return
    ui = theme.user_interface
    for gname in _THEME_WIDGET_GROUPS:
        w = getattr(ui, gname, None)
        if w is None:
            continue
        _theme_set(w, "roundness", p["roundness"])
        _theme_set(w, "inner", (*p["widget"], 1.0))
        _theme_set(w, "inner_sel", (*p["accent"], 1.0))
        _theme_set(w, "outline", (*p["bg"],))
        _theme_set(w, "text", p["text"])
        _theme_set(w, "text_sel", p["text_sel"])
        _theme_set(w, "show_shaded", False)
    # Editor backgrounds → navy; headers → panel tone.
    for aname in _THEME_SPACE_AREAS:
        ta = getattr(theme, aname, None)
        space = getattr(ta, "space", None) if ta is not None else None
        if space is None:
            continue
        _theme_set(space, "back", p["bg"])
        _theme_set(space, "header", (*p["panel"], 1.0))


def _revert_nuclear_theme():
    for obj, attr, orig in reversed(_THEME_BACKUP):
        try:
            setattr(obj, attr, orig)
        except Exception:
            pass
    _THEME_BACKUP.clear()


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
    _apply_nuclear_theme()


def unregister():
    _revert_nuclear_theme()
    _revert_toolbar_overrides()
    _revert_header_overrides()
    _unload_logo()
    _revert_ui_overrides()
    _unregister_translations()
    if load_handler in bpy.app.handlers.load_factory_startup_post:
        bpy.app.handlers.load_factory_startup_post.remove(load_handler)
