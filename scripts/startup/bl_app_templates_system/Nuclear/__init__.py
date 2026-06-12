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

# Native classes to hide while this template is active (filled in P2).
_HIDDEN_CLASSES = []
# Nuclear's own panels/menus to register (filled in P2).
_NUCLEAR_CLASSES = []

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
# Wiring
# --------------------------------------------------------------------------------------

@persistent
def load_handler(_):
    _update_startup_screens()
    _update_startup_scenes()
    _update_startup_grease_pencils()
    if _TRANSLATIONS:
        _ensure_interface_translation()


def register():
    bpy.app.handlers.load_factory_startup_post.append(load_handler)
    _register_translations()
    _apply_ui_overrides()


def unregister():
    _revert_ui_overrides()
    _unregister_translations()
    if load_handler in bpy.app.handlers.load_factory_startup_post:
        bpy.app.handlers.load_factory_startup_post.remove(load_handler)
