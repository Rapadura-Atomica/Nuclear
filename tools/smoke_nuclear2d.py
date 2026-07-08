# SPDX-License-Identifier: GPL-2.0-or-later
# Headless smoke check for the Nuclear 2D stripped build.
# Exits non-zero on any failure so it can gate the release flow.
import sys

import bpy

bo = bpy.app.build_options
def has(name): return getattr(bo, name, None)

# Render engines available (Cycles must be gone)
prop = bpy.types.RenderSettings.bl_rna.properties['engine']
engines = [e.identifier for e in prop.enum_items]

# Constraint types (Spline IK must survive -> WITH_IK_SOLVER)
cprop = bpy.types.Constraint.bl_rna.properties['type']
ctypes = [e.identifier for e in cprop.enum_items]

def op_ok(mod, name):
    # get_rna_type() raises for unregistered operators; idname_py() does NOT
    # (bpy.ops wrappers are lazy), which would make this check unfalsifiable.
    try:
        getattr(getattr(bpy.ops, mod), name).get_rna_type()
        return True
    except Exception:
        return False

results = {
    # --- MUST be OFF (stripped 3D) ---
    "cycles OFF":        has("cycles") is False,
    "freestyle OFF":     has("freestyle") is False,
    "alembic OFF":       has("alembic") is False,
    "usd OFF":           has("usd") is False,
    "fluid OFF":         has("fluid") is False,
    "bullet OFF":        has("bullet") is False,
    "opensubdiv OFF":    has("opensubdiv") is False,
    "CYCLES not in engines": "CYCLES" not in engines,
    # --- MUST be ON (MANTER / 2D pipeline) ---
    "audaspace ON":      has("audaspace") is True,
    "international ON":  has("international") is True,
    "codec_ffmpeg ON":   has("codec_ffmpeg") is True,
    "image_openexr ON":  has("image_openexr") is True,
    "SPLINE_IK present": "SPLINE_IK" in ctypes,
    "SVG->GP import op": op_ok("wm", "grease_pencil_import_svg"),
    "3D mesh IO ops gone": not any(
        op_ok("wm", n) for n in ("obj_import", "stl_import", "ply_import",
                                 "usd_import", "alembic_import")),
}

print("\n===== NUCLEAR 2D SMOKE =====")
allok = True
for k, v in results.items():
    print(f"  [{'PASS' if v else 'FAIL'}] {k}")
    allok = allok and v
print(f"engines available: {engines}")
print(f"build_options ON: {[a for a in dir(bo) if not a.startswith('__') and getattr(bo,a) is True]}")
print(f"RESULT: {'ALL PASS' if allok else 'HAS FAILURES'}")
print("============================\n")

if not allok:
    sys.exit(1)
