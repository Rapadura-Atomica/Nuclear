# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-FileCopyrightText: 2026 Rapadura Atômica
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Nuclear: crash reporter (presence-telemetry's sibling).

Goal: when Nuclear is closed abnormally (segfault, OOM kill, power loss, hard
kill - anything that skips the normal quit path), the NEXT launch offers a small
pop-up asking whether to send a crash report to us, so the beta can be improved.

How an unclean exit is detected (dead-man's switch):
  - On startup we drop a per-session sentinel file `session_<pid>.json` in the
    user config dir and register a clean-exit handler that deletes it.
  - A normal quit deletes the sentinel; a crash does NOT (the handler never runs).
  - So on the next startup, any leftover sentinel whose PID is no longer alive is
    evidence that *that* session crashed. We collect it, attach Blender's own
    `*.crash.txt` backtrace if we can find a fresh one, and offer to report it.

What is sent (only on the user's explicit click, never automatically):
  - studio / responsible person (free text, remembered between runs)
  - an optional description of what happened
  - machine_id (same anonymous id as the presence telemetry), hostname, OS user,
    version, the crashed session's version/time, and Blender's crash backtrace.

NO user document/.blend is ever sent - only the technical crash text. Transport is
an HTTPS POST to `crash.php` (same shape/token as the presence ping); the server
writes it as a .txt. There is NO new secret embedded in the build.

Configuration (environment variables, no rebuild needed):
  NUCLEAR_CRASH_URL        full URL of the crash endpoint (overrides the default)
  NUCLEAR_TELEMETRY_TOKEN  shared secret header (reused from the presence telemetry)
  NUCLEAR_STUDIO           pre-fills the "studio / responsible" field
  NUCLEAR_CRASH_OFF        set to "1" to disable crash reporting entirely
  NUCLEAR_CRASH_TEST       set to "1" to force a synthetic crash on the next launch
                           (controlled test of the prompt + upload, no real crash)
"""

import atexit
import glob
import json
import os
import ssl
import tempfile
import threading
import urllib.request
import uuid
from datetime import datetime, timezone

import bpy
from bpy.props import StringProperty

# --- configuration -----------------------------------------------------------

# Default endpoint. Sibling of the presence ping; override with NUCLEAR_CRASH_URL.
CRASH_URL = "https://rapaduraatomica.com.br/nuclear/nuclear-api/crash.php"

# Shared secret sent as "X-Nuclear-Token". This is the SAME public ping token that
# already ships in every build (presence telemetry) - reused on purpose, it is not
# a new secret. Override with NUCLEAR_TELEMETRY_TOKEN.
SHARED_TOKEN = "6a50f72f178f5c02b526418301fea046"

# Network timeout for the upload, in seconds (kept short - never hang the user).
REQUEST_TIMEOUT = 8

# Cap on how much of Blender's crash backtrace we read/send (bytes).
MAX_LOG_BYTES = 256 * 1024

# -----------------------------------------------------------------------------

# Crash data discovered for the *previous* (crashed) session, filled at register().
_pending_crash = None


def _config_url():
    return os.environ.get("NUCLEAR_CRASH_URL", CRASH_URL)


def _config_token():
    return os.environ.get("NUCLEAR_TELEMETRY_TOKEN", SHARED_TOKEN)


def _is_disabled():
    if os.environ.get("NUCLEAR_CRASH_OFF") == "1":
        return True
    url = _config_url()
    # Not configured yet - stay silent instead of pointing at a placeholder host.
    return (not url) or ("CHANGE-ME" in url)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _hostname():
    try:
        import socket
        return socket.gethostname()
    except Exception:
        return "unknown"


def _username():
    try:
        import getpass
        return getpass.getuser()
    except Exception:
        return "unknown"


def _config_dir():
    return bpy.utils.user_resource('CONFIG', create=True)


def _machine_id():
    """The same stable, anonymous per-install id used by the presence telemetry, so
    a crash report lines up with the machine on the dashboard."""
    try:
        path = os.path.join(_config_dir(), "nuclear_machine_id.txt")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                mid = fh.read().strip()
                if mid:
                    return mid
        mid = uuid.uuid4().hex
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(mid)
        return mid
    except Exception:
        return uuid.uuid4().hex


def _studio_path():
    return os.path.join(_config_dir(), "nuclear_studio.txt")


def _load_studio():
    env = os.environ.get("NUCLEAR_STUDIO")
    if env:
        return env.strip()
    try:
        with open(_studio_path(), "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except Exception:
        return ""


def _save_studio(value):
    try:
        with open(_studio_path(), "w", encoding="utf-8") as fh:
            fh.write((value or "").strip())
    except Exception:
        pass


# --- SSL ---------------------------------------------------------------------

_ssl_ctx = None
_ssl_ctx_done = False


def _ssl_context():
    """SSL context with a CA bundle that verifies. Blender's bundled Python often
    can't find one, so plain HTTPS fails with CERTIFICATE_VERIFY_FAILED and the
    upload is silently dropped. Try certifi -> system CA bundles -> default."""
    global _ssl_ctx, _ssl_ctx_done
    if _ssl_ctx_done:
        return _ssl_ctx
    _ssl_ctx_done = True
    try:
        import certifi
        _ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        return _ssl_ctx
    except Exception:
        pass
    for path in ("/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",
                 "/etc/ssl/certs/ca-certificates.crt",
                 "/etc/ssl/cert.pem",
                 "/etc/ssl/ca-bundle.pem"):
        try:
            if os.path.exists(path):
                _ssl_ctx = ssl.create_default_context(cafile=path)
                return _ssl_ctx
        except Exception:
            continue
    try:
        _ssl_ctx = ssl.create_default_context()
    except Exception:
        _ssl_ctx = None
    return _ssl_ctx


# --- session sentinels (crash detection) -------------------------------------

def _sessions_dir():
    d = os.path.join(_config_dir(), "nuclear_sessions")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def _own_sentinel_path():
    return os.path.join(_sessions_dir(), "session_%d.json" % os.getpid())


def _pid_alive(pid):
    """Best-effort 'is this PID still running'. POSIX-accurate; on platforms where
    we cannot tell, return False so a real crash is not suppressed (at the cost of a
    rare false prompt when a sibling instance was closed uncleanly)."""
    try:
        pid = int(pid)
    except Exception:
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def _write_own_sentinel():
    try:
        with open(_own_sentinel_path(), "w", encoding="utf-8") as fh:
            json.dump({
                "pid": os.getpid(),
                "start_time": _now_iso(),
                "version": bpy.app.version_string,
                "hostname": _hostname(),
                "username": _username(),
                "machine_id": _machine_id(),
            }, fh)
    except Exception:
        pass


def _on_clean_exit():
    # Normal quit: remove our sentinel so we are not reported as a crash next time.
    try:
        os.remove(_own_sentinel_path())
    except Exception:
        pass


def _find_blender_crash_log(since_iso=None):
    """Newest `*.crash.txt` Blender wrote to a temp dir, read up to MAX_LOG_BYTES.
    Best-effort: power-loss/OOM crashes leave no such file, that's fine."""
    dirs = set()
    try:
        dirs.add(tempfile.gettempdir())
    except Exception:
        pass
    try:
        td = bpy.app.tempdir
        if td:
            # bpy.app.tempdir is this session's subfolder; the crashed one wrote to
            # the parent (the configured Blender temp).
            dirs.add(os.path.dirname(os.path.normpath(td)))
    except Exception:
        pass

    candidates = []
    for d in dirs:
        try:
            candidates += glob.glob(os.path.join(d, "*.crash.txt"))
        except Exception:
            pass
    if not candidates:
        return ""
    try:
        candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        with open(candidates[0], "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(MAX_LOG_BYTES)
    except Exception:
        return ""


def _detect_previous_crash():
    """Scan for sentinels left by sessions that never reached a clean exit. Fills
    the module-level _pending_crash with the most recent one and clears the stale
    sentinels so we prompt exactly once."""
    global _pending_crash
    crashed = []
    try:
        paths = glob.glob(os.path.join(_sessions_dir(), "session_*.json"))
    except Exception:
        paths = []
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            data = {}
        pid = data.get("pid")
        if pid == os.getpid():
            continue
        if _pid_alive(pid):
            # A sibling instance is still running - not a crash.
            continue
        crashed.append((path, data))

    if crashed:
        crashed.sort(key=lambda pd: pd[1].get("start_time", ""), reverse=True)
        _, data = crashed[0]
        _pending_crash = {
            "crashed_at": data.get("start_time", ""),
            "crashed_version": data.get("version", ""),
            "blender_log": _find_blender_crash_log(data.get("start_time")),
        }
        # Remove every crashed sentinel so the prompt does not reappear on later boots.
        for path, _ in crashed:
            try:
                os.remove(path)
            except Exception:
                pass

    # Debug hook: force a synthetic crash so the whole prompt + upload path can be
    # exercised without an actual crash. Off unless NUCLEAR_CRASH_TEST=1.
    if _pending_crash is None and os.environ.get("NUCLEAR_CRASH_TEST") == "1":
        _pending_crash = {
            "crashed_at": _now_iso(),
            "crashed_version": bpy.app.version_string,
            "blender_log": "(relatorio de TESTE - NUCLEAR_CRASH_TEST=1, nenhum crash real)",
        }


# --- upload ------------------------------------------------------------------

def _send_report(studio, description):
    if _is_disabled():
        return
    pc = _pending_crash or {}
    payload = {
        "machine_id": _machine_id(),
        "studio": (studio or "").strip(),
        "description": (description or "").strip(),
        "hostname": _hostname(),
        "username": _username(),
        "version": bpy.app.version_string,
        "crashed_version": pc.get("crashed_version", ""),
        "crashed_at": pc.get("crashed_at", ""),
        "blender_log": pc.get("blender_log", ""),
    }

    def worker():
        try:
            data = json.dumps(payload).encode("utf-8")
            # Custom User-Agent: many shared hosts (HostGator mod_security) reject
            # the default "Python-urllib/x.y" with HTTP 406, dropping the upload.
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "Nuclear-CrashReport/1.0",
            }
            token = _config_token()
            if token:
                headers["X-Nuclear-Token"] = token
            req = urllib.request.Request(_config_url(), data=data, headers=headers, method="POST")
            urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=_ssl_context()).close()
        except Exception:
            # A crash report must never disturb the user.
            pass

    threading.Thread(target=worker, daemon=True).start()


# --- UI ----------------------------------------------------------------------

class NUCLEAR_OT_crash_report(bpy.types.Operator):
    """Offer to send a report about the previous unclean shutdown."""
    bl_idname = "nuclear.crash_report"
    bl_label = "Nuclear — relatório de falha"
    bl_options = {'INTERNAL'}

    studio: StringProperty(
        name="Estúdio / responsável",
        description="Quem está rodando (aparece no relatório). Fica salvo para as próximas vezes",
        default="",
    )
    description: StringProperty(
        name="O que aconteceu",
        description="Opcional: o que você estava fazendo quando travou",
        default="",
    )

    def invoke(self, context, event):
        self.studio = _load_studio() or _hostname()
        return context.window_manager.invoke_props_dialog(
            self, width=440, confirm_text="Enviar relatório")

    def draw(self, context):
        col = self.layout.column()
        col.label(text="O Nuclear fechou de forma inesperada na sessão anterior.", icon='ERROR')
        col.label(text="Quer nos enviar um relatório para ajudar a corrigir?")
        col.separator()
        col.prop(self, "studio")
        col.prop(self, "description")
        col.separator()
        col.label(text="Nenhum arquivo seu é enviado — apenas o log técnico da falha.", icon='INFO')

    def execute(self, context):
        _save_studio(self.studio)
        _send_report(self.studio, self.description)
        self.report({'INFO'}, "Relatório de falha enviado. Obrigado!")
        return {'FINISHED'}

    def cancel(self, context):
        # User declined: send nothing. The sentinel was already cleared on detection.
        return None


def _show_dialog_when_ready():
    """Timer callback: wait until a window exists, then open the dialog once."""
    try:
        wm = bpy.context.window_manager
        if not wm or not wm.windows:
            return 1.0  # UI not up yet - try again shortly
        bpy.ops.nuclear.crash_report('INVOKE_DEFAULT')
    except Exception:
        pass
    return None  # stop the timer


# --- register ----------------------------------------------------------------

def register():
    # No UI in background mode - nothing to prompt, and headless render farms would
    # only generate noise. Skip the whole subsystem there.
    if bpy.app.background:
        return

    try:
        bpy.utils.register_class(NUCLEAR_OT_crash_report)
    except Exception:
        pass

    _detect_previous_crash()
    _write_own_sentinel()
    atexit.register(_on_clean_exit)

    if _pending_crash and not _is_disabled():
        # Defer so the prompt appears after the UI has settled.
        bpy.app.timers.register(_show_dialog_when_ready, first_interval=4.0)


def unregister():
    _on_clean_exit()
    try:
        atexit.unregister(_on_clean_exit)
    except Exception:
        pass
    try:
        bpy.utils.unregister_class(NUCLEAR_OT_crash_report)
    except Exception:
        pass
