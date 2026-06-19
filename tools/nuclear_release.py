#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Nuclear release helper - keeps the fork version single-sourced.

The NUCLEAR_* defines in `source/blender/blenkernel/BKE_blender_version.h` are the ONLY
place the fork version is written. This script reads them and derives everything the
auto-updater needs, so a release never drifts out of sync:

  1. `bump {patch|minor|major}`  edit BKE_blender_version.h in place: bump the requested
                          semver field (and zero the ones below it) and ALWAYS +1
                          NUCLEAR_BUILD, since that is what the updater compares.
  2. `version`            print the parsed version as JSON (sanity check).
  3. `stamp <install>`    write `nuclear_version.json` next to the `blender` binary in a
                          built/portable install. The running build reads this to know
                          its own build number (see scripts/startup/nuclear_update.py).
  4. `manifest --zip Z`   compute the zip's sha256 + size and emit the server manifest
                          (`version.json`) that the updater fetches to detect new builds.
  5. `verify-zip --zip Z` check that the zip carries the auto-updater and the fork's
                          Python deps (golden rules #3/#4) before anyone wastes time
                          publishing a broken build.
  6. `check-manifest --zip Z --manifest version.json`
                          recompute sha256/size and diff against a manifest already on
                          disk -- the one-command fix for "checksum nao confere".

Typical release flow (Linux portable build) -- or just run `tools/nuclear_release.sh`,
which chains all of this for you:

    python tools/nuclear_release.py bump minor   # edits BKE_blender_version.h
    # rebuild, then package the zip however you do (see nuclear_release.sh), then:
    python tools/nuclear_release.py stamp ../build_linux/bin
    ( cd ../build_linux && zip -r nuclear.zip Nuclear/ )      # however you package
    python tools/nuclear_release.py verify-zip --zip ../build_linux/nuclear.zip
    python tools/nuclear_release.py manifest --zip ../build_linux/nuclear.zip \\
        --url https://rapaduraatomica.com.br/estacao/nuclear.zip \\
        --notes "O que mudou nesta versao" -o version.json
    # then upload nuclear.zip and version.json to estacao/ on the host, together.

This script has no third-party dependencies and does not touch the network.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile

HEADER_REL = os.path.join("source", "blender", "blenkernel", "BKE_blender_version.h")

# Fields we pull out of the header. int fields are parsed as ints, str fields keep the
# inner text of their string literal.
_INT_FIELDS = ("NUCLEAR_VERSION_MAJOR", "NUCLEAR_VERSION_MINOR", "NUCLEAR_VERSION_PATCH",
               "NUCLEAR_BUILD")
_STR_FIELDS = ("NUCLEAR_NAME", "NUCLEAR_VERSION_STAGE")

# Golden rule #3: the zip must carry the auto-updater client and the version stamp.
_REQUIRED_ZIP_MEMBERS = (
    "Nuclear/5.0/scripts/startup/nuclear_update.py",
    "Nuclear/nuclear_version.json",
)
# Golden rule #4: the zip must bundle the fork's Python deps (checked via scipy as a
# stand-in for the whole site-packages bundle -- see nuclear-release.md golden rule #4).
_REQUIRED_SITE_PACKAGES_MARKER = "site-packages/scipy"


def _repo_root():
    """Repo root, found by walking up from this script until the header exists."""
    here = os.path.dirname(os.path.abspath(__file__))
    cur = here
    while True:
        if os.path.isfile(os.path.join(cur, HEADER_REL)):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            # Fall back to the script's parent dir (tools/ -> repo root).
            return os.path.dirname(here)
        cur = parent


def parse_version(header_path=None):
    """Read the NUCLEAR_* defines and return the version dict the updater uses."""
    if header_path is None:
        header_path = os.path.join(_repo_root(), HEADER_REL)
    with open(header_path, "r", encoding="utf-8") as fh:
        text = fh.read()

    out = {}
    for name in _INT_FIELDS:
        m = re.search(r"#define\s+%s\s+(\d+)" % name, text)
        if not m:
            raise SystemExit("error: %s not found in %s" % (name, header_path))
        out[name] = int(m.group(1))
    for name in _STR_FIELDS:
        m = re.search(r'#define\s+%s\s+"([^"]*)"' % name, text)
        if not m:
            raise SystemExit("error: %s not found in %s" % (name, header_path))
        out[name] = m.group(1)

    major = out["NUCLEAR_VERSION_MAJOR"]
    minor = out["NUCLEAR_VERSION_MINOR"]
    patch = out["NUCLEAR_VERSION_PATCH"]
    stage = out["NUCLEAR_VERSION_STAGE"]
    name = out["NUCLEAR_NAME"]
    version = "%d.%d.%d" % (major, minor, patch)
    version_string = "%s %s (%s)" % (name, version, stage)

    return {
        "name": name,
        "build": out["NUCLEAR_BUILD"],
        "version": version,
        "stage": stage,
        "version_string": version_string,
    }


def _read_int_field(text, name):
    m = re.search(r"#define\s+%s\s+(\d+)" % name, text)
    if not m:
        raise SystemExit("error: %s not found in header" % name)
    return int(m.group(1))


def _write_int_field(text, name, value):
    pattern = re.compile(r"(#define\s+%s\s+)(\d+)" % name)
    new_text, count = pattern.subn(r"\g<1>%d" % value, text, count=1)
    if count != 1:
        raise SystemExit("error: could not update %s in header" % name)
    return new_text


def _sha256_and_size(path):
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def _find_binary_dir(install):
    """Locate the directory that holds the `blender` executable inside an install tree."""
    for cand in (install, os.path.join(install, "Nuclear")):
        for exe in ("blender", "blender.exe"):
            if os.path.isfile(os.path.join(cand, exe)):
                return cand
    # Search shallowly for a blender binary.
    for root, _dirs, files in os.walk(install):
        if "blender" in files or "blender.exe" in files:
            return root
    return None


def cmd_bump(args):
    header_path = args.header or os.path.join(_repo_root(), HEADER_REL)
    with open(header_path, "r", encoding="utf-8") as fh:
        text = fh.read()

    major = _read_int_field(text, "NUCLEAR_VERSION_MAJOR")
    minor = _read_int_field(text, "NUCLEAR_VERSION_MINOR")
    patch = _read_int_field(text, "NUCLEAR_VERSION_PATCH")
    build = _read_int_field(text, "NUCLEAR_BUILD")
    before = "%d.%d.%d (build %d)" % (major, minor, patch, build)

    if args.kind == "major":
        major, minor, patch = major + 1, 0, 0
    elif args.kind == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    # Golden rule #1: every release bumps NUCLEAR_BUILD, regardless of semver kind --
    # that is the only number the updater actually compares.
    build += 1

    text = _write_int_field(text, "NUCLEAR_VERSION_MAJOR", major)
    text = _write_int_field(text, "NUCLEAR_VERSION_MINOR", minor)
    text = _write_int_field(text, "NUCLEAR_VERSION_PATCH", patch)
    text = _write_int_field(text, "NUCLEAR_BUILD", build)

    with open(header_path, "w", encoding="utf-8") as fh:
        fh.write(text)

    after = "%d.%d.%d (build %d)" % (major, minor, patch, build)
    print("%s: %s -> %s  [%s]" % (header_path, before, after, args.kind))
    return 0


def cmd_version(args):
    print(json.dumps(parse_version(args.header), indent=2, ensure_ascii=False))
    return 0


def cmd_stamp(args):
    info = parse_version(args.header)
    bin_dir = _find_binary_dir(args.install)
    if bin_dir is None:
        raise SystemExit("error: no 'blender' binary found under %s" % args.install)
    out_path = os.path.join(bin_dir, "nuclear_version.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(info, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("stamped %s -> build %d (%s)" % (out_path, info["build"], info["version_string"]))
    return 0


def cmd_manifest(args):
    info = parse_version(args.header)
    sha, size = _sha256_and_size(args.zip)

    notes = args.notes or ""
    if args.notes_file:
        with open(args.notes_file, "r", encoding="utf-8") as fh:
            notes = fh.read().strip()

    manifest = dict(info)
    manifest.update({
        "url": args.url,
        "sha256": sha,
        "size": size,
        "min_build": args.min_build,
        "notes_url": args.notes_url,
        "notes": notes,
    })

    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    if args.output and args.output != "-":
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("wrote %s (build %d, sha256 %s)" % (args.output, info["build"], sha), file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


def cmd_verify_zip(args):
    with zipfile.ZipFile(args.zip) as zf:
        names = set(zf.namelist())

    problems = []
    missing_members = [m for m in _REQUIRED_ZIP_MEMBERS if m not in names]
    if missing_members:
        problems.append("regra de ouro #3 (updater ausente): falta %s" % ", ".join(missing_members))

    scipy_count = sum(1 for n in names if _REQUIRED_SITE_PACKAGES_MARKER in n)
    if scipy_count == 0:
        problems.append("regra de ouro #4 (deps Python ausentes): nao achei '%s'" %
                         _REQUIRED_SITE_PACKAGES_MARKER)

    if problems:
        print("FALHOU: %s nao esta pronto para publicar:" % args.zip, file=sys.stderr)
        for p in problems:
            print("  - %s" % p, file=sys.stderr)
        raise SystemExit(1)

    print("OK: %s contem o updater e as deps do fork (%d arquivos em site-packages/scipy)" %
          (args.zip, scipy_count))
    return 0


def cmd_check_manifest(args):
    sha, size = _sha256_and_size(args.zip)
    with open(args.manifest, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)

    problems = []
    if manifest.get("sha256") != sha:
        problems.append("sha256: manifesto=%s atual=%s" % (manifest.get("sha256"), sha))
    if manifest.get("size") != size:
        problems.append("size: manifesto=%s atual=%s" % (manifest.get("size"), size))

    if problems:
        print("checksum NAO confere entre %s e %s:" % (args.manifest, args.zip), file=sys.stderr)
        for p in problems:
            print("  - %s" % p, file=sys.stderr)
        raise SystemExit(1)

    print("OK: %s casa com %s (sha256 %s, %d bytes)" % (args.manifest, args.zip, sha, size))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Nuclear release helper (single-source version).")
    p.add_argument("--header", default=None,
                   help="path to BKE_blender_version.h (default: auto-detect from repo)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("bump", help="bump the semver field and +1 NUCLEAR_BUILD in the header")
    sp.add_argument("kind", choices=("patch", "minor", "major"), help="semver field to bump")
    sp.set_defaults(func=cmd_bump)

    sp = sub.add_parser("version", help="print parsed version as JSON")
    sp.set_defaults(func=cmd_version)

    sp = sub.add_parser("stamp", help="write nuclear_version.json into a built install")
    sp.add_argument("install", help="path to the install tree (holds the blender binary)")
    sp.set_defaults(func=cmd_stamp)

    sp = sub.add_parser("manifest", help="emit the server version.json for a packaged zip")
    sp.add_argument("--zip", required=True, help="path to the packaged nuclear.zip")
    sp.add_argument("--url", default="https://rapaduraatomica.com.br/estacao/nuclear.zip",
                    help="download URL the manifest should advertise")
    sp.add_argument("--notes", default="", help="release notes text")
    sp.add_argument("--notes-file", default=None, help="read release notes from a file")
    sp.add_argument("--notes-url", default="https://github.com/Rapadura-Atomica/Nuclear/releases",
                    help="URL for full release notes")
    sp.add_argument("--min-build", type=int, default=0,
                    help="oldest build that may upgrade directly to this one")
    sp.add_argument("-o", "--output", default="-", help="output file (default: stdout)")
    sp.set_defaults(func=cmd_manifest)

    sp = sub.add_parser("verify-zip", help="check golden rules #3/#4 (updater + Python deps) on a zip")
    sp.add_argument("--zip", required=True, help="path to the packaged nuclear.zip")
    sp.set_defaults(func=cmd_verify_zip)

    sp = sub.add_parser("check-manifest", help="recompute sha256/size and diff against a version.json")
    sp.add_argument("--zip", required=True, help="path to the packaged nuclear.zip")
    sp.add_argument("--manifest", required=True, help="path to the version.json to check against")
    sp.set_defaults(func=cmd_check_manifest)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
