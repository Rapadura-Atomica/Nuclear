# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Nuclear: in-app update notifier + applier.

Checks a small JSON manifest on the Nuclear web host, compares it against the build this
binary was stamped with, and - if a newer build exists - shows a discreet notice in the
status bar plus a one-time popup. It never blocks or limits anything: if the network is
down or the manifest is unreachable, Blender behaves exactly as normal and the check
fails silently in a background thread.

Two version sources, single source of truth:
  - This running build knows its own build number from `nuclear_version.json`, a tiny file
    shipped next to the `blender` binary, stamped at release time by
    `tools/nuclear_release.py` (which reads the NUCLEAR_* defines in BKE_blender_version.h
    - edit the version there and nowhere else).
  - The server advertises the latest build in `version.json` (same script writes it).

The comparison is a plain integer compare of `build`.

Applying the update (Linux, phase 2):
  The install is laid out as versioned directories behind an atomic `current` symlink:

      <base>/versions/<version>-b<build>/   (a full portable Blender folder)
      <base>/current -> versions/<...>      (symlink; the .desktop launches this)

  Updating downloads the zip, verifies its sha256 against the manifest, extracts it into
  `versions/`, flips the `current` symlink atomically, prunes old versions and offers to
  restart. Because the swap is a single rename, the install is never left half-written, and
  rolling back is just pointing `current` at the previous directory.

  A flat install (a freshly-unzipped folder with the binary sitting directly in it, no
  `current`/`versions` yet) is migrated in place: the new build lands in `<folder>/versions/`
  and `<folder>/current` is created pointing at it, all WITHIN the user's own Nuclear folder.
  The old flat binary is left untouched as a fallback.

  On Windows (phase 3) the running blender.exe cannot be replaced in place, so the button
  falls back to opening the page until the quit/helper/relaunch path lands. The only other
  fallback is a non-writable install (or macOS), which opens the repository home page.

Configuration (no rebuild needed - environment variables override the constants):
  NUCLEAR_UPDATE_URL    full URL of the version manifest (version.json)
  NUCLEAR_UPDATE_OFF    set to "1" to disable the update check entirely
  NUCLEAR_UPDATE_BUILD  pretend this build number is installed (for testing the notice)
"""

import hashlib
import json
import os
import platform
import shutil
import ssl
import subprocess
import tempfile
import threading
import urllib.request
import zipfile

# Guarded so the pure filesystem helpers below can be imported and unit-tested headless
# (outside Blender). Inside Blender, bpy is always present.
try:
    import bpy
except ImportError:
    bpy = None

# --- configuration -----------------------------------------------------------

# Default manifest endpoint. Static JSON served straight off the web host - no PHP, no
# token, cacheable. Override at runtime with the NUCLEAR_UPDATE_URL env var.
MANIFEST_URL = "https://rapaduraatomica.com.br/estacao/version.json"

# How long after launch to run the first check, and how often to re-check while open.
# Short so the notice shows promptly, but not 0 - the window/UI must exist first.
FIRST_CHECK_SECONDS = 3
RECHECK_SECONDS = 6 * 60 * 60  # 6 hours

# Network timeouts, in seconds. The manifest is tiny; the zip is large, so its connect
# timeout is longer (the timeout is per socket operation, not for the whole transfer).
REQUEST_TIMEOUT = 8
DOWNLOAD_TIMEOUT = 30

# How many old version directories to keep after an update (plus the running one).
KEEP_VERSIONS = 3

# -----------------------------------------------------------------------------

# Set by the manifest-fetch worker (plain Python only - NEVER touch bpy off-thread).
_latest = None            # parsed manifest dict, or None until a successful fetch
_fetch_done = False
_popup_shown = False
_statusbar_installed = False
_current_cache = None

# Apply state, written by the download/apply worker, read by the modal operator.
_apply_thread = None
_apply_state = "idle"     # idle | downloading | verifying | extracting | applying | done | error
_apply_progress = 0.0     # 0..1 during download
_apply_message = ""       # human-readable status / error
_apply_target = None      # path of the newly installed version dir, once applied


def _config_url():
    return os.environ.get("NUCLEAR_UPDATE_URL", MANIFEST_URL)


def _is_disabled():
    if os.environ.get("NUCLEAR_UPDATE_OFF") == "1":
        return True
    url = _config_url()
    return (not url) or ("CHANGE-ME" in url)


# --- version detection -------------------------------------------------------


def _current_info():
    """The build this binary was stamped with, read from `nuclear_version.json`.

    Returns a dict (at least {"build": int}) or None when it cannot be found - e.g. a
    developer build run from the build tree, where the updater stays quiet.
    """
    global _current_cache
    if _current_cache is not None:
        return _current_cache

    forced = os.environ.get("NUCLEAR_UPDATE_BUILD")
    if forced is not None:
        try:
            _current_cache = {"build": int(forced), "version_string": "(forced)"}
            return _current_cache
        except ValueError:
            pass

    try:
        bin_dir = os.path.dirname(bpy.app.binary_path or "") if bpy else ""
    except Exception:
        bin_dir = ""

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


# --- manifest fetch ----------------------------------------------------------


_ssl_ctx = None
_ssl_ctx_done = False


def _ssl_context():
    """A urllib SSL context with a CA bundle that actually verifies.

    Blender's bundled Python frequently can't find a CA bundle, so plain HTTPS fails with
    CERTIFICATE_VERIFY_FAILED (which silently broke the update check AND the telemetry).
    Try certifi (ships with the app), then common system CA bundles, then the platform
    default. Cached after the first call.
    """
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


def _fetch_worker():
    global _latest, _fetch_done
    try:
        headers = {"User-Agent": "Nuclear-Updater/1.0"}
        req = urllib.request.Request(_config_url(), headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=_ssl_context()) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8"))
        if isinstance(data, dict) and "build" in data:
            data["build"] = int(data["build"])
            _latest = data
    except Exception:
        pass
    finally:
        _fetch_done = True


def _start_fetch():
    global _latest, _fetch_done
    _latest = None
    _fetch_done = False
    threading.Thread(target=_fetch_worker, daemon=True).start()


# --- install layout & apply (pure helpers, no bpy) ---------------------------


def _detect_layout(binary_path):
    """Map a blender binary path to the versioned-install directories.

    Returns {base, versions, current, install_root} or None. Handles both the new
    versioned layout (`<base>/versions/<v>/blender`) and a legacy flat layout
    (`<base>/<v>/blender`), in both cases placing new versions under `<base>/versions`.
    """
    if not binary_path:
        return None
    install_root = os.path.dirname(os.path.realpath(binary_path))
    parent = os.path.dirname(install_root)
    if os.path.basename(parent) == "versions":
        # Versioned layout: <base>/versions/<v>/blender -> base is two levels up.
        base = os.path.dirname(parent)
    else:
        # Flat layout: the binary sits directly in its folder (<base>/blender). The base IS
        # that folder, so versions/ and current land INSIDE it - never scattered into the
        # parent (which, for ~/Nuclear/blender, would wrongly be the home dir).
        base = install_root
    return {
        "base": base,
        "versions": os.path.join(base, "versions"),
        "current": os.path.join(base, "current"),
        "install_root": install_root,
    }


def _version_dirname(manifest):
    """Directory name for a manifest's build, e.g. "1.0.0-b2"."""
    version = str(manifest.get("version", "0")).strip() or "0"
    build = int(manifest.get("build", 0))
    return "%s-b%d" % (version, build)


def _find_binary_root(tree):
    """Directory inside an extracted tree that holds the `blender` executable."""
    for exe in ("blender", "blender.exe"):
        if os.path.isfile(os.path.join(tree, exe)):
            return tree
    for root, _dirs, files in os.walk(tree):
        if "blender" in files or "blender.exe" in files:
            return root
    return None


def _sha256_file(path, progress_cb=None, size_hint=0):
    h = hashlib.sha256()
    done = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
            done += len(chunk)
            if progress_cb and size_hint:
                progress_cb(min(1.0, done / size_hint))
    return h.hexdigest()


def _download(url, dest, progress_cb=None):
    """Stream a URL to `dest`, reporting 0..1 progress when Content-Length is known."""
    headers = {"User-Agent": "Nuclear-Updater/1.0"}
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT, context=_ssl_context()) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        got = 0
        with open(dest, "wb") as fh:
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                got += len(chunk)
                if progress_cb and total:
                    progress_cb(got / total)


def _atomic_symlink(target, link):
    """Point `link` at `target` atomically, replacing an existing symlink (POSIX)."""
    tmp = link + ".tmp-new"
    if os.path.lexists(tmp):
        os.remove(tmp)
    os.symlink(target, tmp)
    os.replace(tmp, link)  # atomic on POSIX; replaces an existing symlink in place


def _rmdir_junction(path):
    """Remove a directory symlink/junction WITHOUT touching its target contents."""
    if not os.path.lexists(path):
        return
    # os.rmdir removes a junction/dir-symlink reparse point without recursing into
    # the target on Windows; os.unlink handles a dir symlink on POSIX.
    try:
        os.rmdir(path)
    except OSError:
        os.unlink(path)


def _flip_current_windows(target, link):
    """Point `link` at `target` via a directory junction (no admin rights needed).

    The running blender.exe lives inside `target`'s *previous* sibling, which we never
    touch, so there is no in-use-file conflict. We build the new junction under a temp
    name first, then swap, to keep the window where `current` is missing as small as
    possible (junctions cannot be atomically replaced like a POSIX symlink).
    """
    tmp = link + ".new"
    _rmdir_junction(tmp)
    # mklink needs cmd's built-in; shell=False with the explicit cmd /c form.
    subprocess.run(["cmd", "/c", "mklink", "/J", tmp, target], check=True)
    _rmdir_junction(link)
    os.rename(tmp, link)


def _flip_current(target, link):
    """Repoint the `current` pointer at `target`, using the right primitive per OS."""
    if os.name == "nt":
        _flip_current_windows(target, link)
    else:
        _atomic_symlink(target, link)


def _stamp_version(install_dir, manifest):
    """Ensure the installed version knows its own build (for the next update check)."""
    path = os.path.join(install_dir, "nuclear_version.json")
    if os.path.isfile(path):
        return
    info = {k: manifest[k] for k in ("name", "build", "version", "stage", "version_string")
            if k in manifest}
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(info, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    except Exception:
        pass


def _apply_extracted(extract_tree, layout, manifest):
    """Move an extracted build into versions/ and flip `current` to it. Returns its path."""
    src = _find_binary_root(extract_tree)
    if src is None:
        raise RuntimeError("nenhum binário 'blender' encontrado no pacote baixado")

    os.makedirs(layout["versions"], exist_ok=True)
    dest = os.path.join(layout["versions"], _version_dirname(manifest))
    if os.path.realpath(dest) == os.path.realpath(layout["install_root"]):
        raise RuntimeError("esta versão já está instalada")
    if os.path.exists(dest):
        shutil.rmtree(dest, ignore_errors=True)
    shutil.move(src, dest)
    _stamp_version(dest, manifest)
    _flip_current(os.path.abspath(dest), layout["current"])
    return dest


def _refresh_desktop(layout):
    """Best-effort: repoint a Nuclear.desktop launcher at `current/blender` after an update.

    Existing machines were installed with a flat layout and a launcher that names a specific
    version directory; once we move to the versioned `current` symlink, the launcher must
    follow or it would keep opening the old build. Conservative on purpose: only rewrites an
    Exec line that already points somewhere inside this install's base, so we never touch an
    unrelated .desktop. Never raises into the update flow.

    Linux only: on Windows the `current` junction means the Start-Menu shortcut keeps
    resolving to the new build with no rewrite needed.
    """
    if os.name == "nt":
        return
    target_exec = os.path.join(layout["current"], "blender")
    base_real = os.path.realpath(layout["base"])
    candidates = [
        os.path.expanduser("~/.local/share/applications/Nuclear.desktop"),
        os.path.join(layout["base"], "Nuclear.desktop"),
    ]
    for path in candidates:
        try:
            if not os.path.isfile(path):
                continue
            with open(path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
            changed = False
            for i, line in enumerate(lines):
                if not line.startswith("Exec="):
                    continue
                cur = line[len("Exec="):].strip().split()[0] if line[len("Exec="):].strip() else ""
                # Only touch a launcher that already points into our install base.
                if cur and os.path.realpath(os.path.dirname(cur)).startswith(base_real):
                    lines[i] = "Exec=%s\n" % target_exec
                    changed = True
            if changed:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.writelines(lines)
        except Exception:
            continue


def _prune_versions(versions_dir, keep_paths, keep=KEEP_VERSIONS):
    """Keep the newest `keep` version dirs plus everything in `keep_paths`; remove the rest.

    `keep_paths` may be a single path or an iterable. The currently-running install is
    always passed in so we never try to delete it (it is locked on Windows anyway).
    """
    if isinstance(keep_paths, (str, bytes)):
        keep_paths = [keep_paths]
    try:
        entries = [os.path.join(versions_dir, d) for d in os.listdir(versions_dir)]
    except OSError:
        return
    dirs = [d for d in entries if os.path.isdir(d) and not os.path.basename(d).startswith(".")]
    dirs.sort(key=lambda d: os.path.getmtime(d), reverse=True)
    survivors = set(dirs[:keep])
    for p in keep_paths:
        if p:
            survivors.add(os.path.realpath(p))
    for d in dirs:
        if os.path.realpath(d) in survivors or d in survivors:
            continue
        shutil.rmtree(d, ignore_errors=True)


def _can_apply(layout):
    """Self-apply on Linux/Windows whenever the install folder is writable.

    Both layouts are handled: a versioned install updates by flipping `current`, and a flat
    install (freshly unzipped, binary directly in its folder) is migrated in place -
    `_detect_layout` anchors `base` at that folder, so `versions/` and `current` are created
    INSIDE it, never scattered elsewhere. The only fall-backs (which open the repo page) are
    a non-writable install or macOS. Developer builds run from the build tree are already
    excluded upstream: they have no `nuclear_version.json`, so `_update_available()` is False
    and the apply path is never reached.
    """
    if platform.system() not in ("Linux", "Windows"):
        return False
    if not layout or not os.access(layout["base"], os.W_OK):
        return False
    return True


def _run_apply(manifest, layout):
    """Full download -> verify -> extract -> swap -> prune. Sets the _apply_* globals."""
    global _apply_state, _apply_progress, _apply_message, _apply_target
    work = None
    try:
        os.makedirs(layout["versions"], exist_ok=True)
        # Work inside versions/ so the final move is a same-filesystem rename.
        work = tempfile.mkdtemp(prefix=".update-", dir=layout["versions"])
        zip_path = os.path.join(work, "nuclear.zip")

        _apply_state = "downloading"
        _apply_progress = 0.0

        def on_dl(p):
            global _apply_progress
            _apply_progress = p
        _download(manifest["url"], zip_path, on_dl)

        expected = (manifest.get("sha256") or "").lower().strip()
        if expected:
            _apply_state = "verifying"
            _apply_progress = 0.0
            got = _sha256_file(zip_path, lambda p: _set_progress(p),
                               size_hint=manifest.get("size", 0))
            if got.lower() != expected:
                raise RuntimeError("checksum não confere - download corrompido")

        _apply_state = "extracting"
        extract_dir = os.path.join(work, "x")
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)

        _apply_state = "applying"
        dest = _apply_extracted(extract_dir, layout, manifest)
        _apply_target = dest
        _refresh_desktop(layout)
        # Keep the new build and the still-running one (locked on Windows).
        _prune_versions(layout["versions"], [dest, layout["install_root"]])

        _apply_state = "done"
        _apply_message = "Atualização instalada. Reinicie o Nuclear para usá-la."
    except Exception as ex:
        _apply_state = "error"
        _apply_message = str(ex)
    finally:
        if work and os.path.isdir(work):
            shutil.rmtree(work, ignore_errors=True)


def _set_progress(p):
    global _apply_progress
    _apply_progress = p


def _restart_into_current(layout):
    """Spawn the freshly-installed build (via the `current` pointer) detached, then quit."""
    exe_name = "blender.exe" if os.name == "nt" else "blender"
    exe = os.path.join(layout["current"], exe_name)
    try:
        if os.name == "nt":
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | \
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen([exe], cwd=layout["base"], creationflags=flags, close_fds=True)
        else:
            subprocess.Popen([exe], start_new_session=True, cwd=layout["base"])
    except Exception:
        return False
    try:
        bpy.ops.wm.quit_blender()
    except Exception:
        pass
    return True


# --- UI ----------------------------------------------------------------------


def _notes_text():
    if isinstance(_latest, dict) and _latest.get("notes"):
        return str(_latest["notes"])
    return ""


def _latest_label():
    if isinstance(_latest, dict):
        return str(_latest.get("version_string") or ("build %s" % _latest.get("build", "?")))
    return "?"


def _open_page():
    """Fallback when we can't self-install: open the repository HOME page.

    Deliberately not the `/releases` page (which is empty and a dead end) - the home page
    always has the README, the installer and instructions. Ignores the manifest's notes_url
    on purpose, so users never land somewhere they can't act.
    """
    try:
        bpy.ops.wm.url_open(url="https://github.com/Rapadura-Atomica/Nuclear")
    except Exception:
        pass


def _layout_now():
    try:
        return _detect_layout(bpy.app.binary_path) if bpy else None
    except Exception:
        return None


def _begin_apply():
    """Kick off the background download+apply (or open the page when not self-applicable).

    Returns True when a download was started/already running, False when it fell back to the
    page. Safe to call from an operator execute() or a button.
    """
    global _apply_thread, _apply_state, _apply_progress, _apply_message
    if bpy is None or not _update_available():
        return False
    layout = _layout_now()
    if not _can_apply(layout):
        # macOS / dev / flat (un-migrated) / non-writable install: open the page.
        _open_page()
        return False
    if _apply_thread and _apply_thread.is_alive():
        return True
    _apply_state = "downloading"
    _apply_progress = 0.0
    _apply_message = ""
    manifest = dict(_latest)
    _apply_thread = threading.Thread(target=_run_apply, args=(manifest, layout), daemon=True)
    _apply_thread.start()
    if not bpy.app.timers.is_registered(_apply_progress_tick):
        bpy.app.timers.register(_apply_progress_tick, first_interval=0.3)
    return True


if bpy is not None:

    class NUCLEAR_OT_update_dialog(bpy.types.Operator):
        """Mostrar a tela de atualização disponível"""
        bl_idname = "nuclear.update_dialog"
        bl_label = "Atualização do Nuclear"
        bl_options = {'INTERNAL'}

        # A persistent dialog (invoke_props_dialog), not a popup_menu: it stays put like the
        # About screen and only closes on an explicit choice, instead of vanishing when the
        # mouse leaves it.
        def invoke(self, context, event):
            wm = context.window_manager
            applies = _can_apply(_layout_now())
            confirm = "Baixar e instalar" if applies else "Abrir página de download"
            try:
                return wm.invoke_props_dialog(
                    self, width=440, title="Atualização do Nuclear", confirm_text=confirm)
            except TypeError:
                return wm.invoke_props_dialog(self, width=440)

        def draw(self, context):
            col = self.layout.column()
            col.scale_y = 1.05
            col.label(text="Nova versão disponível", icon='IMPORT')
            big = col.row()
            big.scale_y = 1.4
            big.label(text=_latest_label())
            notes = _notes_text()
            if notes:
                col.separator()
                box = col.box().column(align=True)
                box.label(text="Novidades:")
                for line in notes.splitlines():
                    if line.strip():
                        box.label(text="• " + line.strip())
            cur = _current_info()
            if cur and cur.get("version_string") and cur.get("version_string") != "(forced)":
                col.separator()
                col.label(text="Instalada: %s" % cur["version_string"], icon='BLENDER')

        def execute(self, context):
            _begin_apply()
            return {'FINISHED'}

    class NUCLEAR_OT_update_done_dialog(bpy.types.Operator):
        """Tela de atualização concluída"""
        bl_idname = "nuclear.update_done_dialog"
        bl_label = "Nuclear atualizado"
        bl_options = {'INTERNAL'}

        def invoke(self, context, event):
            wm = context.window_manager
            try:
                return wm.invoke_props_dialog(
                    self, width=400, title="Nuclear atualizado", confirm_text="Reiniciar agora")
            except TypeError:
                return wm.invoke_props_dialog(self, width=400)

        def draw(self, context):
            col = self.layout.column()
            col.scale_y = 1.1
            col.label(text="Atualização instalada com sucesso!", icon='CHECKMARK')
            col.separator()
            col.label(text="Reinicie o Nuclear para começar a usar a nova versão.")

        def execute(self, context):
            layout = _layout_now()
            if layout:
                _restart_into_current(layout)
            return {'FINISHED'}

    class NUCLEAR_OT_update_error_dialog(bpy.types.Operator):
        """Tela de falha na atualização"""
        bl_idname = "nuclear.update_error_dialog"
        bl_label = "Atualização do Nuclear"
        bl_options = {'INTERNAL'}

        def invoke(self, context, event):
            wm = context.window_manager
            try:
                return wm.invoke_props_dialog(
                    self, width=400, title="Falha na atualização",
                    confirm_text="Abrir página de download")
            except TypeError:
                return wm.invoke_props_dialog(self, width=400)

        def draw(self, context):
            col = self.layout.column()
            col.label(text="Não foi possível instalar a atualização:", icon='ERROR')
            for line in (_apply_message or "falha desconhecida").splitlines():
                if line.strip():
                    col.label(text=line)

        def execute(self, context):
            _open_page()
            return {'FINISHED'}

    _CLASSES = (NUCLEAR_OT_update_dialog,
                NUCLEAR_OT_update_done_dialog,
                NUCLEAR_OT_update_error_dialog)
else:
    _CLASSES = ()


def _show_dialog(opname):
    """Open one of the dialog operators, even from a timer (no event of our own).

    Uses a window override so `bpy.ops.nuclear.<op>('INVOKE_DEFAULT')` has the window context
    invoke_props_dialog needs. Returns True if it was opened.
    """
    if bpy is None:
        return False
    try:
        wm = bpy.context.window_manager
        win = wm.windows[0] if (wm and wm.windows) else None
    except Exception:
        win = None
    if win is None:
        return False
    op = getattr(bpy.ops.nuclear, opname, None)
    if op is None:
        return False
    try:
        with bpy.context.temp_override(window=win):
            op('INVOKE_DEFAULT')
        return True
    except Exception:
        return False


def _apply_progress_tick():
    """Main-thread timer: mirror the worker's progress to the status bar, then on
    completion clear it and show the restart/error popup. Returns the next interval, or
    None to stop."""
    ws = None
    try:
        ws = bpy.context.workspace
    except Exception:
        ws = None

    state = _apply_state
    if state == "downloading":
        if ws:
            ws.status_text_set("Baixando atualização do Nuclear... %d%%" % int(_apply_progress * 100))
        return 0.3
    if state in {"verifying", "extracting", "applying"}:
        if ws:
            ws.status_text_set("Instalando atualização... (%s)" % state)
        return 0.3

    # Terminal state (done / error / idle): clear the status text and report.
    if ws:
        try:
            ws.status_text_set(None)
        except Exception:
            pass
    if state == "done":
        _show_dialog("update_done_dialog")
    elif state == "error":
        _show_dialog("update_error_dialog")
    return None


def _draw_statusbar(self, context):
    if not _update_available():
        return
    row = self.layout.row(align=True)
    row.operator("nuclear.update_dialog",
                 text="Nuclear %s disponível" % _latest_label(), icon='IMPORT')


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


def _show_dialog_once():
    """Auto-open the 'update available' dialog a single time per session."""
    global _popup_shown
    if _popup_shown:
        return
    if _show_dialog("update_dialog"):
        _popup_shown = True


def _tick():
    if _update_available():
        _install_statusbar()
        _show_dialog_once()
        try:
            for win in bpy.context.window_manager.windows:
                for area in win.screen.areas:
                    area.tag_redraw()
        except Exception:
            pass

    if _fetch_done:
        _start_periodic()
        return None
    return 2.0


def _start_periodic():
    if bpy.app.timers.is_registered(_periodic_check):
        return
    bpy.app.timers.register(_periodic_check, first_interval=RECHECK_SECONDS, persistent=True)


def _periodic_check():
    if _is_disabled():
        return None
    _start_fetch()
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=2.0, persistent=True)
    return None


# --- registration ------------------------------------------------------------


def register():
    if bpy is None:
        return
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    if _is_disabled():
        return
    _start_fetch()
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=FIRST_CHECK_SECONDS, persistent=True)


def unregister():
    if bpy is None:
        return
    for fn in (_tick, _periodic_check, _apply_progress_tick):
        if bpy.app.timers.is_registered(fn):
            bpy.app.timers.unregister(fn)
    _remove_statusbar()
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
