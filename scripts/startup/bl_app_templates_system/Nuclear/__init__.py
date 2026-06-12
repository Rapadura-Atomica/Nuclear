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
    screen = bpy.data.screens.get("2D Animation")
    if screen is not None:
        for area in screen.areas:
            if area.type == 'PROPERTIES':
                area.spaces.active.context = 'TOOL'
            elif area.type == 'DOPESHEET_EDITOR':
                area.spaces.active.show_region_ui = True

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


# Native classes to hide while this template is active (filled in later phases).
_HIDDEN_CLASSES = []
# Nuclear's own panels/menus to register.
_NUCLEAR_CLASSES = [
    NUCLEAR_MT_logo,
    NUCLEAR_MT_view,
]

_unregistered = []


def _apply_ui_overrides():
    for cls in _HIDDEN_CLASSES:
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


# Overrides applied while the template is active: (bpy.types class name, attr, Nuclear fn).
# Generalized to any method (not just "draw") so headers that dispatch (e.g. draw_left)
# can be curated too.
_HEADER_OVERRIDES = [
    ("TOPBAR_MT_editor_menus", "draw", _nuclear_editor_menus_draw),
    ("TOPBAR_HT_upper_bar", "draw_left", _nuclear_topbar_draw_left),
    ("VIEW3D_HT_header", "draw", _nuclear_view3d_header_draw),
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
            # Keep overlays on (Grease Pencil needs them) but drop 3D scaffolding.
            overlay = space.overlay
            overlay.show_floor = False
            overlay.show_axis_x = False
            overlay.show_axis_y = False
            overlay.show_axis_z = False
            overlay.show_ortho_grid = False
            overlay.show_cursor = False


# --------------------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------------------

@persistent
def load_handler(_):
    _update_startup_screens()
    _update_startup_scenes()
    _update_startup_grease_pencils()
    _update_startup_canvas()
    if _TRANSLATIONS:
        _ensure_interface_translation()


def register():
    bpy.app.handlers.load_factory_startup_post.append(load_handler)
    _register_translations()
    _apply_ui_overrides()
    _load_logo()
    _apply_header_overrides()


def unregister():
    _revert_header_overrides()
    _unload_logo()
    _revert_ui_overrides()
    _unregister_translations()
    if load_handler in bpy.app.handlers.load_factory_startup_post:
        bpy.app.handlers.load_factory_startup_post.remove(load_handler)
