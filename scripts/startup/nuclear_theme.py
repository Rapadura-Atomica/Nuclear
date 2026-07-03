# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Nuclear theme (the navy + rounded "pill" look) — applied GLOBALLY.

The Nuclear application template used to apply this theme in its own register()
and revert it on unregister(), so switching to another template (2D Animation,
Storyboarding) fell back to Blender's default grey theme. Nuclear is a single
product: every starting environment should share its identity.

This global startup script owns the theme instead. It mutates `themes[0]` on
register and re-applies it after every file/template load via a @persistent
`load_post` handler, so all templates — Nuclear, 2D Animation, Storyboarding —
carry the same colors. It is data-only (theme properties, incl. per-widget
`roundness`), so there is zero C divergence / rebase risk.
"""

import bpy
from bpy.app.handlers import persistent

# RGB(A) 0..1. Navy base, purple/blue accents, light text — from the mockup.
_NUCLEAR_THEME = {
    "bg":       (0.07, 0.07, 0.13),
    "panel":    (0.11, 0.11, 0.19),
    "widget":   (0.15, 0.15, 0.25),
    "accent":   (0.42, 0.30, 0.84),
    "text":     (0.90, 0.90, 0.96),
    "text_sel": (1.00, 1.00, 1.00),
    # Viewport selection outline: a blue silhouette around selected objects.
    "select":        (0.15, 0.55, 1.00),
    "select_active": (0.40, 0.78, 1.00),
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


def _theme_set(obj, attr, value):
    if obj is None or not hasattr(obj, attr):
        return
    try:
        setattr(obj, attr, value)
    except Exception:
        pass


def apply_nuclear_theme():
    """Stamp the Nuclear palette onto the active theme. Idempotent."""
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
    # Viewport: blue outline around selected/active objects (the peg "selection" cue).
    v3d = getattr(theme, "view_3d", None)
    if v3d is not None:
        _theme_set(v3d, "object_selected", p["select"])
        _theme_set(v3d, "object_active", p["select_active"])


@persistent
def _reapply_on_load(*_args):
    # Runs after every file / app-template load, so the Nuclear look survives
    # File > New > (2D Animation | Storyboarding | Nuclear) and opening files.
    apply_nuclear_theme()


def register():
    apply_nuclear_theme()
    if _reapply_on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_reapply_on_load)


def unregister():
    if _reapply_on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_reapply_on_load)
