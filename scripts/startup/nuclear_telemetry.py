# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Nuclear: presence telemetry client.

Reports "this machine is running Nuclear" to a small web service so the studio can
see, on a web dashboard, which machines are online right now and which are not.

This is PRESENCE telemetry, not a license check: it never blocks, gates or limits
anything. If the network is down or the server is unreachable, Blender behaves
exactly as normal - the ping just fails silently in a background thread.

What is sent on each ping:
  - machine_id : a random UUID generated once and stored in the user config dir
                 (stable per install, not tied to any personal data)
  - hostname   : the machine name, so the dashboard is human-readable
  - user       : the OS login name (helps tell machines apart in a studio)
  - version    : the Nuclear/Blender version string
  - event      : "startup" | "heartbeat" | "shutdown"

Flow:
  - one "startup" ping when Blender launches,
  - a "heartbeat" every HEARTBEAT_SECONDS while it stays open,
  - a best-effort "shutdown" ping on quit.
The server marks a machine "offline" once it stops hearing heartbeats.

Configuration (no rebuild needed - environment variables override the constants):
  NUCLEAR_TELEMETRY_URL      full URL of the ping endpoint
  NUCLEAR_TELEMETRY_TOKEN    shared secret sent as a header (optional)
  NUCLEAR_TELEMETRY_OFF      set to "1" to disable telemetry entirely
"""

import atexit
import json
import os
import threading
import urllib.request
import uuid

import bpy

# --- configuration -----------------------------------------------------------

# Default endpoint. Point this at your hosting, e.g. "https://studio.example.com/api/ping".
# Can be overridden at runtime with the NUCLEAR_TELEMETRY_URL environment variable.
SERVER_URL = "https://rapaduraatomica.com.br/nuclear/api/ping"

# Shared secret sent as the "X-Nuclear-Token" header so random clients cannot spam
# your dashboard. Must match NUCLEAR_TOKEN on the server. Override with the
# NUCLEAR_TELEMETRY_TOKEN environment variable.
SHARED_TOKEN = "6a50f72f178f5c02b526418301fea046"

# How often to send a heartbeat while Blender is open, in seconds.
HEARTBEAT_SECONDS = 300

# Network timeout for a single ping, in seconds (kept short - we never want to hang).
REQUEST_TIMEOUT = 5

# -----------------------------------------------------------------------------

_machine_id = None


def _config_url():
    return os.environ.get("NUCLEAR_TELEMETRY_URL", SERVER_URL)


def _config_token():
    return os.environ.get("NUCLEAR_TELEMETRY_TOKEN", SHARED_TOKEN)


def _is_disabled():
    if os.environ.get("NUCLEAR_TELEMETRY_OFF") == "1":
        return True
    url = _config_url()
    # Not configured yet - stay silent instead of spamming a placeholder host.
    return (not url) or ("CHANGE-ME" in url)


def _get_machine_id():
    """A stable, anonymous per-install id, persisted in the user config dir."""
    global _machine_id
    if _machine_id is not None:
        return _machine_id
    try:
        config_dir = bpy.utils.user_resource('CONFIG', create=True)
        id_path = os.path.join(config_dir, "nuclear_machine_id.txt")
        if os.path.exists(id_path):
            with open(id_path, "r", encoding="utf-8") as fh:
                _machine_id = fh.read().strip()
        if not _machine_id:
            _machine_id = uuid.uuid4().hex
            with open(id_path, "w", encoding="utf-8") as fh:
                fh.write(_machine_id)
    except Exception:
        # Fall back to an ephemeral id rather than failing.
        _machine_id = uuid.uuid4().hex
    return _machine_id


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


def _send(event):
    """Fire one ping in a background thread; never raises into Blender."""
    if _is_disabled():
        return

    payload = {
        "machine_id": _get_machine_id(),
        "hostname": _hostname(),
        "user": _username(),
        "version": bpy.app.version_string,
        "event": event,
    }

    def worker():
        try:
            data = json.dumps(payload).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            token = _config_token()
            if token:
                headers["X-Nuclear-Token"] = token
            req = urllib.request.Request(_config_url(), data=data, headers=headers, method="POST")
            urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT).close()
        except Exception:
            # Presence telemetry must never disturb the user.
            pass

    threading.Thread(target=worker, daemon=True).start()


def _heartbeat():
    """Timer callback: ping, then ask to be called again later."""
    _send("heartbeat")
    return HEARTBEAT_SECONDS


def _on_exit():
    # Best-effort goodbye; the daemon thread may not finish on a hard kill, which is fine.
    _send("shutdown")


def register():
    _send("startup")
    if not bpy.app.timers.is_registered(_heartbeat):
        bpy.app.timers.register(_heartbeat, first_interval=HEARTBEAT_SECONDS, persistent=True)
    atexit.register(_on_exit)


def unregister():
    if bpy.app.timers.is_registered(_heartbeat):
        bpy.app.timers.unregister(_heartbeat)
    try:
        atexit.unregister(_on_exit)
    except Exception:
        pass
