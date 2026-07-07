# SPDX-FileCopyrightText: 2011-2023 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

# Nuclear 2D — build preset for the 2D / Grease Pencil cut-out pipeline.
#
# Strategy: start from the UPSTREAM DEFAULT feature set and turn OFF *only* the
# heavy 3D subsystems that the 2D/GP pipeline does not use. Everything the
# workflow depends on (FFmpeg, OpenEXR/JP2/WebP/Cineon, OpenColorIO, TBB,
# IK solver / Spline IK, i18n, the native SVG->GP importer, audio) is left at
# its upstream default (ON) and is deliberately NOT listed here.
#
# This is the reversible, measurable "Phase 1" of demanda #6: no source is
# deleted, only build features are toggled. Each flag below is verified to
# exist and default ON in the top-level CMakeLists.txt.
#
# Example usage (out-of-source build):
#   cmake -C../blender/build_files/cmake/config/nuclear_2d.cmake  ../blender
#
# NOTE: This preset does NOT relicense anything. Nuclear remains a GPL-2.0-or-later
# derivative of Blender; license headers and attribution are kept intact. It only
# reduces the compiled feature set.

# --- 3D photoreal / render engines (GP renders via draw/engines/gpencil) ---
set(WITH_CYCLES              OFF CACHE BOOL "" FORCE)  # path tracer; OSL/Embree auto-follow
set(WITH_OPENIMAGEDENOISE    OFF CACHE BOOL "" FORCE)  # Cycles denoiser

# --- 3D physics / simulation ---
set(WITH_BULLET              OFF CACHE BOOL "" FORCE)  # rigid body / collision
set(WITH_MOD_FLUID           OFF CACHE BOOL "" FORCE)  # Mantaflow fluid/smoke/fire
set(WITH_MOD_OCEANSIM        OFF CACHE BOOL "" FORCE)  # ocean modifier
set(WITH_MOD_REMESH          OFF CACHE BOOL "" FORCE)  # remesh modifier

# --- 3D mesh geometry tooling ---
set(WITH_FREESTYLE           OFF CACHE BOOL "" FORCE)  # NPR edge render for 3D meshes
set(WITH_QUADRIFLOW          OFF CACHE BOOL "" FORCE)  # quad remesher
set(WITH_OPENSUBDIV          OFF CACHE BOOL "" FORCE)  # Catmull-Clark subdivision
set(WITH_OPENVDB             OFF CACHE BOOL "" FORCE)  # volumes / VDB
set(WITH_NANOVDB             OFF CACHE BOOL "" FORCE)  # follows OpenVDB
set(WITH_GMP                 OFF CACHE BOOL "" FORCE)  # exact mesh boolean (libgmp)

# --- Motion tracking (match-move solver) ---
# NOTE: this only stubs the solver in blenkernel; the Movie Clip Editor still
# compiles. Hiding that editor from the UI is a separate, later step.
set(WITH_LIBMV               OFF CACHE BOOL "" FORCE)  # libmv + ceres camera solver

# --- 3D scene interchange ---
set(WITH_USD                 OFF CACHE BOOL "" FORCE)  # Pixar USD
set(WITH_HYDRA               OFF CACHE BOOL "" FORCE)  # Hydra render delegate
set(WITH_ALEMBIC             OFF CACHE BOOL "" FORCE)  # Alembic geometry cache

# --- 3D mesh import/export (NOT WITH_IO_GREASE_PENCIL, which stays ON) ---
set(WITH_IO_FBX              OFF CACHE BOOL "" FORCE)  # FBX mesh IO (ufbx)
set(WITH_IO_WAVEFRONT_OBJ    OFF CACHE BOOL "" FORCE)  # .obj mesh IO
set(WITH_IO_PLY              OFF CACHE BOOL "" FORCE)  # .ply mesh IO
set(WITH_IO_STL              OFF CACHE BOOL "" FORCE)  # .stl mesh IO
set(WITH_DRACO               OFF CACHE BOOL "" FORCE)  # glTF mesh compression

# --- VR / XR ---
set(WITH_XR_OPENXR           OFF CACHE BOOL "" FORCE)  # VR headset support

# -----------------------------------------------------------------------------
# DELIBERATELY LEFT AT UPSTREAM DEFAULT (ON) — do NOT disable, the 2D/GP
# pipeline depends on these (documented here so future edits don't "clean" them):
#   WITH_IO_GREASE_PENCIL  -> native SVG->GP import (base of Auto-Patch)
#   WITH_CODEC_FFMPEG      -> video / animatics in the VSE + video render
#   WITH_IMAGE_OPENEXR / _OPENJPEG / _WEBP / _CINEON -> render & image IO
#   WITH_OPENCOLORIO       -> colour management (render fidelity)
#   WITH_TBB               -> threading / performance
#   WITH_IK_SOLVER         -> Spline IK used by the GP cut-out rigs
#   WITH_INTERNATIONAL     -> bpy.app.translations rebranding seam
#   WITH_AUDASPACE         -> audio kept ON (israel's decision, 2026-07-06)
#   compositor, sequencer/VSE, shader_fx (GP effects) -> not flag-gated; kept
# -----------------------------------------------------------------------------
