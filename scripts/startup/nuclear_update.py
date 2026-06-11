# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Nuclear: in-app update notifier.

Checks a small JSON manifest on the Nuclear web host, compares it against the build
this binary was stamped with, and - if a newer build exists - shows a discreet notice
in the status bar plus a one-time popup. It never blocks or limits anything: if the
network is down or the manifest is unreachable, Blender behaves exactly as normal and
the check fails silently in a background thread.

Two version sources, single source of truth:
  - This running build knows its own build number from `nuclear_version.json`, a tiny
    file shipped next to the `blender` binary and stamped at release time by
    `tools/nuclear_release.py` (which reads the NUCLEAR_* defines in
    BKE_blender_version.h - edit the version there and nowhere else).
  - The server advertises the latest build in `version.json` (same script writes it).

The comparison is a plain integer compare of `build`, so it is robust regardless of how
the human-readable version string is formatted.

What this module does NOT do yet: actually download and apply the update. The status-bar
button currently opens the release notes / download page. The download + atomic
symlink-swap apply (Linux) and the quit/helper/relaunch apply (Windows) land in a later
phase; the hook (`_run_update_action`) is isolated so wiring it in is a one-spot change.

Configuration (no rebuild needed - environment variables override the constants):
  NUCLEAR_UPDATE_URL    full URL of the version manifest (version.json)
  NUCLEAR_UPDATE_OFF    set to "1" to disable the update check entirely
  NUCLEAR_UPDATE_BUILD  pretend this build number is installed (for testing the notice)
"""

import json
import os
import threading
import urllib.request

import bpy

# --- configuration -----------------------------------------------------------

# Default manifest endpoint. Static JSON served straight off the web host - no PHP,
# no token, cacheable. Override at runtime with the NUCLEAR_UPDATE_URL env var.
MANIFEST_URL = "https://rapaduraatomica.com.br/estacao/version.json"

# How long after launch to run the first check, and how often to re-check while open.
# Kept lazy: there is no value in hammering the host, a new build is a rare event.
FIRST_CHECK_SECONDS = 12
RECHECK_SECONDS = 6 * 60 * 60  # 6 hours

# Network timeout for the manifest fetch, in seconds (kept short - never hang the UI).
REQUEST_TIMEOUT = 8

# -----------------------------------------------------------------------------

# Set by the background worker thread (plain Python only - NEVER touch bpy off-thread).
# The main-thread timer reads these and drives all UI.
_latest = None            # parsed manifest dict, or None until a successful fetch
_fetch_done = False       # worker finished (success or failure)
_popup_shown = False      # the one-time popup has been shown this session
_statusbar_installed = False
_current_cache = None     # memoized result of _current_info()


def _config_url():
    return os.environ.get("NUCLEAR_UPDATE_URL", MANIFEST_URL)


def _is_disabled():
    if os.environ.get("NUCLEAR_UPDATE_OFF") == "1":
        return True
    url = _config_url()
    return (not url) or ("CHANGE-ME" in url)


def _current_info():
    """The build this binary was stamped with, read from `nuclear_version.json`.

    The file is shipped next to the `blender` executable by the release script. Returns
    a dict (at least {"build": int}) or None when it cannot be found/parsed - e.g. a
    local developer build run straight from the build tree, where the updater stays quiet.
    """
    global _current_cache
    if _current_cache is not None:
        return _current_cache

    # Test override: NUCLEAR_UPDATE_BUILD=0 makes any server build look newer.
    forced = os.environ.get("NUCLEAR_UPDATE_BUILD")
    if forced is not None:
        try:
            _current_cache = {"build": int(forced), "version_string": "(forced)"}
            return _current_cache
        except ValueError:
            pass

    try:
        bin_dir = os.path.dirname(bpy.app.binary_path or "")
    except Exception:
        bin_dir = ""

    # Look next to the binary, then one directory up (covers a couple of layouts).
    candidates = []
    if bin_dir:
        candidates.append(os.path.join(bin_dir, "nuclear_version.json"))
        candidates.append(os.path.join(os.path.dirname(bin_dir), "nuclear_version.json"))

    for path in candidates:
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as fh:
                    info = json.load(fh)
                if isinstance(info, dict) and "build" in info:
                    info["build"] = int(info["build"])
                    _current_cache = info
                    return _current_cache
        except Exception:
            continue
    return None


def _update_available():
    """True only when we know both sides and the server build is strictly newer."""
    cur = _current_info()
    if not cur or not isinstance(_latest, dict):
        return False
    try:
        return int(_latest.get("build", -1)) > int(cur.get("build", 0))
    except (TypeError, ValueError):
        return False


def _fetch_worker():
    """Background: fetch + parse the manifest. Touches no bpy state, only globals."""
    global _latest, _fetch_done
    try:
        headers = {
            # A custom User-Agent is REQUIRED: many shared hosts (HostGator mod_security)
            # reject the default "Python-urllib/x.y" agent with HTTP 406.
            "User-Agent": "Nuclear-Updater/1.0",
        }
        req = urllib.request.Request(_config_url(), headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8"))
        if isinstance(data, dict) and "build" in data:
            data["build"] = int(data["build"])
            _latest = data
    except Exception:
        # The update check must never disturb the user.
        pass
    finally:
        _fetch_done = True


def _start_fetch():
    global _latest, _fetch_done
    _latest = None
    _fetch_done = False
    threading.Thread(target=_fetch_worker, daemon=True).start()


# --- UI ----------------------------------------------------------------------


def _notes_text():
    if isinstance(_latest, dict):
        notes = _latest.get("notes")
        if notes:
            return str(notes)
    return ""


def _latest_label():
    if isinstance(_latest, dict):
        vs = _latest.get("version_string")
        if vs:
            return str(vs)
        return "build %s" % _latest.get("build", "?")
    return "?"


def _run_update_action():
    """Phase 1: open the release notes / download page.

    Phase 2 replaces this with the real download + verify + atomic apply. Keeping it in
    one function means wiring the apply in later touches exactly one place.
    """
    url = ""
    if isinstance(_latest, dict):
        url = _latest.get("notes_url") or _latest.get("url") or ""
    if not url:
        url = "https://github.com/Rapadura-Atomica/Nuclear/releases"
    try:
        bpy.ops.wm.url_open(url=url)
    except Exception:
        pass


class NUCLEAR_OT_update(bpy.types.Operator):
    """Abrir a página da atualização do Nuclear"""
    bl_idname = "nuclear.update"
    bl_label = "Atualizar o Nuclear"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        _run_update_action()
        return {'FINISHED'}


def _draw_statusbar(self, context):
    if not _update_available():
        return
    row = self.layout.row(align=True)
    row.operator("nuclear.update", text="Nuclear %s disponível" % _latest_label(), icon='IMPORT')


def _install_statusbar():
    global _statusbar_installed
    if _statusbar_installed:
        return
    try:
        bpy.types.STATUSBAR_HT_header.append(_draw_statusbar)
        _statusbar_installed = True
    except Exception:
        pass


def _remove_statusbar():
    global _statusbar_installed
    if not _statusbar_installed:
        return
    try:
        bpy.types.STATUSBAR_HT_header.remove(_draw_statusbar)
    except Exception:
        pass
    _statusbar_installed = False


def _show_popup():
    """One-time popup. Must run on the main thread (called from the timer)."""
    global _popup_shown
    if _popup_shown:
        return
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None or not getattr(bpy.context, "window", None):
        return  # No usable UI context yet; try again on the next timer tick.

    notes = _notes_text()
    label = _latest_label()

    def draw(self, context):
        col = self.layout.column()
        col.label(text="Nova versão disponível: %s" % label, icon='IMPORT')
        for line in notes.splitlines():
            if line.strip():
                col.label(text=line)
        col.separator()
        col.operator("nuclear.update", text="Baixar / Ver notas", icon='URL')

    try:
        wm.popup_menu(draw, title="Atualização do Nuclear", icon='INFO')
        _popup_shown = True
    except Exception:
        pass


def _tick():
    """Main-thread timer: drive UI once the worker reports back, then re-check later."""
    if _update_available():
        _install_statusbar()
        _show_popup()
        # Nudge the UI so the status-bar notice appears without a manual redraw.
        try:
            for win in bpy.context.window_manager.windows:
                for area in win.screen.areas:
                    area.tag_redraw()
        except Exception:
            pass

    if _fetch_done:
        # Done with this round; schedule the next periodic re-check.
        _start_fetch_later()
        return None  # stop this timer
    return 2.0  # keep polling the worker every couple of seconds


def _start_fetch_later():
    if bpy.app.timers.is_registered(_periodic_check):
        return
    bpy.app.timers.register(_periodic_check, first_interval=RECHECK_SECONDS, persistent=True)


def _periodic_check():
    if _is_disabled():
        return None
    _start_fetch()
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=2.0, persistent=True)
    return None  # one-shot; _tick reschedules the next round when it finishes


# --- registration ------------------------------------------------------------


def register():
    bpy.utils.register_class(NUCLEAR_OT_update)
    if _is_disabled():
        return
    _start_fetch()
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=FIRST_CHECK_SECONDS, persistent=True)


def unregister():
    for fn in (_tick, _periodic_check):
        if bpy.app.timers.is_registered(fn):
            bpy.app.timers.unregister(fn)
    _remove_statusbar()
    try:
        bpy.utils.unregister_class(NUCLEAR_OT_update)
    except Exception:
        pass
