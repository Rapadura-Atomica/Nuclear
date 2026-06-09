# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Nuclear presence-telemetry server.

A tiny Flask + SQLite service that receives "I am running" pings from Nuclear
clients and shows, on a web page, which machines are online right now and which
are offline (with their last-seen time).

It does NOT limit or gate anything - it only records presence.

Endpoints:
  POST /api/ping   receive a ping (JSON: machine_id, hostname, user, version, event)
  GET  /           HTML dashboard
  GET  /api/machines   JSON list of machines (used by the dashboard / for scripting)

Run locally:
  pip install flask
  python app.py                 # http://127.0.0.1:8000

Behind your hosting, serve `app` with gunicorn / mod_wsgi / Passenger, e.g.:
  gunicorn -b 0.0.0.0:8000 app:app

Configuration (environment variables):
  NUCLEAR_DB           path to the SQLite file (default: ./telemetry.db)
  NUCLEAR_TOKEN        if set, pings must carry a matching X-Nuclear-Token header
  NUCLEAR_ONLINE_SECS  seconds since last ping to still count as "online" (default: 600)
  PORT                 port for the built-in dev server (default: 8000)
"""

import os
import sqlite3
from datetime import datetime, timezone

from flask import Flask, g, jsonify, render_template, request

DB_PATH = os.environ.get("NUCLEAR_DB", os.path.join(os.path.dirname(__file__), "telemetry.db"))
# Shared secret: pings must carry a matching X-Nuclear-Token header. Must match
# SHARED_TOKEN in the Nuclear client. Override with the NUCLEAR_TOKEN env var.
TOKEN = os.environ.get("NUCLEAR_TOKEN", "6a50f72f178f5c02b526418301fea046")
ONLINE_SECS = int(os.environ.get("NUCLEAR_ONLINE_SECS", "600"))

app = Flask(__name__)


# --- database ----------------------------------------------------------------

def get_db():
    db = getattr(g, "_db", None)
    if db is None:
        db = g._db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_db(exc):
    db = getattr(g, "_db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS machines (
            machine_id  TEXT PRIMARY KEY,
            hostname    TEXT,
            username    TEXT,
            version     TEXT,
            last_event  TEXT,
            first_seen  TEXT,
            last_seen   TEXT
        )
        """
    )
    db.commit()
    db.close()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# --- ingest ------------------------------------------------------------------

@app.route("/api/ping", methods=["POST"])
def ping():
    if TOKEN and request.headers.get("X-Nuclear-Token", "") != TOKEN:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    machine_id = (data.get("machine_id") or "").strip()
    if not machine_id:
        return jsonify({"error": "machine_id required"}), 400

    hostname = (data.get("hostname") or "")[:200]
    username = (data.get("user") or "")[:200]
    version = (data.get("version") or "")[:100]
    event = (data.get("event") or "")[:50]
    ts = now_iso()

    db = get_db()
    db.execute(
        """
        INSERT INTO machines (machine_id, hostname, username, version, last_event, first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(machine_id) DO UPDATE SET
            hostname=excluded.hostname,
            username=excluded.username,
            version=excluded.version,
            last_event=excluded.last_event,
            last_seen=excluded.last_seen
        """,
        (machine_id, hostname, username, version, event, ts, ts),
    )
    db.commit()
    return jsonify({"ok": True})


# --- read --------------------------------------------------------------------

def _machine_rows():
    db = get_db()
    rows = db.execute("SELECT * FROM machines ORDER BY last_seen DESC").fetchall()
    out = []
    now = datetime.now(timezone.utc)
    for r in rows:
        online = False
        age = None
        try:
            last = datetime.fromisoformat(r["last_seen"])
            age = (now - last).total_seconds()
            online = age <= ONLINE_SECS and r["last_event"] != "shutdown"
        except Exception:
            pass
        out.append(
            {
                "machine_id": r["machine_id"],
                "hostname": r["hostname"],
                "username": r["username"],
                "version": r["version"],
                "last_event": r["last_event"],
                "first_seen": r["first_seen"],
                "last_seen": r["last_seen"],
                "age_seconds": age,
                "online": online,
            }
        )
    return out


@app.route("/api/machines")
def api_machines():
    return jsonify(_machine_rows())


@app.route("/")
def dashboard():
    machines = _machine_rows()
    online = sum(1 for m in machines if m["online"])
    return render_template(
        "dashboard.html",
        machines=machines,
        online_count=online,
        total_count=len(machines),
        online_secs=ONLINE_SECS,
    )


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
