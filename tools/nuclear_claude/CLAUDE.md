# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Nuclear — project context (READ FIRST)

> **This folder (`tools/nuclear_claude/`) is the canonical, cross-machine project
> context.** It is version-controlled and pushed to `origin`, so every session on every
> machine shares the same source of truth. **Keep it updated** as the project evolves —
> when something here goes stale, fix it here, not in a side note. The repo-root
> `CLAUDE.md` is a thin pointer that imports this file so it auto-loads in every session.
>
> Files in this folder:
> - `CLAUDE.md` (this file) — context for Claude Code.
> - `NUCLEAR_DIVERGENCE.md` — **the divergence/rebase registry** (every change this fork
>   makes vs. upstream). Consult it before editing core files and update it whenever you
>   add divergence.
> - `readme.txt` — notes for human devs (kept separately from Claude context).

**What Nuclear is.** A fork of Blender 5.0.0 being shaped into an increasingly
independent **2D / cut-out animation** application (Toon Boom-style), built on Grease
Pencil. The long-term goal is a distinct product that is *proudly derived from Blender*
(GPL kept, attribution kept, Blender trademark removed from product identity). It is
**not** a general 3D suite anymore in intent — 3D stays in the code but is hidden in the
UI.

**Fork-specific systems already in C** (see `NUCLEAR_DIVERGENCE.md` for exact files):
PegRig (peg-based cut-out rig), Follow Peg constraint, Grease Pencil "Curve" modifier
(arc-length deform), the "Peg Pose" tool, and a Peg Graph node editor.

**Strategic decisions that govern all work here:**
- **Upstream sync = rebase per release** (stay on 5.0; move to 5.1/5.2 as concentrated
  merges). `origin` is the fork; `lfs-fallback` is upstream Blender.
- **3D = hide in the UI only** — never remove 3D/object/depsgraph code (Grease Pencil v3
  depends on it).
- **Minimize and isolate C divergence.** New Nuclear features should live in *new files*
  (e.g. `*_pegrig.*`, `nuclear_*.py`, new modifiers), not as edits scattered across
  upstream-maintained files. Where touching an upstream file is unavoidable, keep it to a
  minimal "seam" and **record it in `NUCLEAR_DIVERGENCE.md`** — that file is the rebase
  checklist.
- **Prefer upper layers over C** for UI/branding: Application Template + `bpy.app.translations`
  (rename UI labels in bulk) + theme/startup data, before editing C.

**Naming conventions (two tiers — keep consistent, don't rename existing to churn):**
- *Project identity* → `nuclear` / `Nuclear` / `NUCLEAR_`: app name, app template, startup
  add-ons (`nuclear_*.py`), Python classes (`Nuclear*`, `NUCLEAR_GGT_*`), telemetry,
  `tools/nuclear_*`.
- *Feature / domain* → the feature name (reads naturally in UI/API): tool `builtin.peg_pose`,
  operators `object.pegrig_*` / `GREASE_PENCIL_OT_peg_*`, data types `PegRig`/`PegRigPeg`,
  modifier "Curve". New features pick the tier that fits; never mix both in one identifier.

**Active project:** an extreme UI overhaul + rebranding to make Nuclear look like its own
software (hide/relocate native functions, complete the identity). The UI/branding work is
funneled through the **Nuclear application template**
(`scripts/startup/bl_app_templates_system/Nuclear/`) — its `__init__.py` is the seam for
label remapping and panel hiding/relocation, so the overhaul does not edit
`scripts/startup/bl_ui/*` in place. Full plan:
`~/.claude/plans/infelizmente-para-meu-azar-cryptic-rivest.md` (per-machine, local).

---

## What this is

This repository (`Nuclear`) is a fork of [Blender](https://www.blender.org), the free and open source 3D creation suite (modeling, rigging, animation, simulation, rendering, compositing, motion tracking, video editing). It tracks upstream Blender closely; fork-specific changes are individual commits on top of the upstream tree (e.g. the `feat:` commits like Bezier curve support for Grease Pencil). Upstream remote is `lfs-fallback` (`projects.blender.org/blender/blender.git`); `origin` is the fork. The codebase is large (C, C++, Python, GLSL/OSL/MSL shaders) and built with CMake.

Build instructions: https://developer.blender.org/docs/handbook/building_blender/ — Code layout: https://developer.blender.org/docs/features/code_layout/

## Building

The fork builds on both **Linux/macOS** (via the `GNUmakefile` wrapper) and **Windows** (via `make.bat`). Both are thin wrappers around an **out-of-source CMake build** whose directory defaults to a **sibling** of the source tree (e.g. `../build_windows`, `../build_linux`), keeping the working copy clean. Targets/switches compose and order is irrelevant.

### Windows (`make.bat`)

Prerequisites: **Visual Studio** (2019/2022/2026 — auto-detected, MSVC is default on x64), CMake on `PATH`, and the path to the repo must contain **no spaces** (checked by the script). Run from a normal terminal (`make.bat` invokes the MSVC environment itself).

```bat
make update                  :: FIRST: fetch precompiled libs into lib/ + sync git. Required before first build.
make                         :: default optimized build into ..\build_windows
make developer               :: RECOMMENDED for dev: faster builds, error checking, tests enabled
make debug                   :: unoptimized debuggable build
make full                    :: release minus CUDA kernels
make lite                    :: minimal feature set, fast build
make release                 :: identical to official blender.org builds
make with_tests              :: enable building unit tests (or use `developer`)
make 2022                    :: force a specific VS version (2019 / 2022 / 2026, plus b=BuildTools, pre/i variants)
make ninja                   :: build with ninja instead of msbuild
make nobuild                 :: only generate the VS project files (open ..\build_windows\Blender.sln)
make help                    :: full switch list
```

After configuring, you can also open `..\build_windows\Blender.sln` in Visual Studio and build the `INSTALL` target there. The runnable binary lands in `..\build_windows\bin\<Config>\`.

### Linux / macOS (`GNUmakefile`)

```sh
make update                # FIRST: sync repo + precompiled libraries
make                       # default optimized build into ../build_linux
make developer             # RECOMMENDED for dev: faster builds, error checking, tests enabled
make debug                 # debug binary -> ../build_linux_debug
make full / make lite      # all options / minimal fast build (own suffixed dirs)
make ninja ccache          # combine, e.g. `make developer ninja ccache`
make config                # interactive CMake config tool
```

Override the build dir with `builddir <path>` (Windows) / `BUILD_DIR=path` (make), and pass extra CMake args via `BUILD_CMAKE_ARGS='...'`. Each variant builds into its own suffixed directory, so they don't clobber each other.

Library dependencies are **pre-built** and pulled into `lib/` by `make update` (do not rebuild them). `make deps` is only for platform maintainers; locally-built deps in `lib/` override the precompiled ones and must be manually removed to revert. Run `make update` after pulling if the build breaks on missing/outdated libs.

## Testing

```sh
make test                  # Linux/macOS: run the full ctest suite
```
```bat
make test                  :: Windows: same, via make.bat
```
The build must have tests enabled (`make developer` or `make with_tests`).

Tests live in `tests/`:
- `tests/gtests/` — C/C++ unit tests (GoogleTest).
- `tests/python/` — Python integration tests run through the Blender binary (`bl_*.py`, operator tests, IO round-trips, etc.).
- `tests/performance/`, `tests/coverage/`, `tests/files/` (test data), `tests/utils/`.

To run a **single** test, invoke `ctest` directly in the build dir (the makefile only exposes the whole suite):

```sh
cd ../build_linux && ctest -R <test_name_regex> --output-on-failure
ctest -N                   # list available test names without running
```

## Static checks, formatting & spell checking

```sh
make format                # clang-format (C/C++) + autopep8 (Python). Scope with PATHS="source/blender/blenlib ..."
make check_cppcheck        # cppcheck over C/C++
make check_clang_array     # clang array-size checking
make check_pep8            # PEP8 for tagged Python scripts
make check_mypy            # mypy for Python (config in tools/check_source/check_mypy_config.py)
make check_cmake           # validate CMake file-list definitions
make check_licenses        # SPDX license-header conformance (see doc/license/SPDX-license-identifiers.txt)
make check_spelling_c      # C/C++ spelling; also _py, _shaders, _cmake variants
```

Code style is enforced by `.clang-format` (C/C++) and `.clang-tidy`; Python by `pyproject.toml` (`autopep8`, max line length **120**). Always run `make format` before committing. Spell-check word list: `tools/check_source/check_spelling_c_config.py`.

## Architecture — the big picture

Blender is a monolithic C/C++ application with an embedded Python interpreter. The most important cross-cutting system to understand before editing data structures is **DNA → RNA → Python**:

- **DNA** (`source/blender/makesdna/`, the `DNA_*_types.h` headers): the plain-C structs that define every persistent data type (Object, Mesh, Scene, etc.). These structs ARE the `.blend` file format — they are serialized directly. A code generator (`makesdna`) builds a runtime reflection table (`SDNA`) from them, which is what makes `.blend` files forward/backward compatible. **Changing a DNA struct changes the file format**: never reorder/reuse fields casually; pad fields are added deliberately, and renamed/removed fields are handled in versioning (`blenloader`).
- **RNA** (`source/blender/makesrna/`): a second generated reflection layer that wraps DNA structs to expose them as introspectable, animatable, scriptable properties. RNA is what the Python API, the UI (buttons auto-generate from RNA), animation system, and drivers all read/write through. Adding a user-facing property usually means editing both a DNA struct and its `rna_*.c` definition.
- **`blenloader`** (`source/blender/blenloader/`): reads/writes `.blend` files and performs **versioning** (do-version code that migrates old files to the current DNA layout). Any file-format-affecting change needs corresponding versioning here.
- **Python** (`source/blender/python/`): embeds CPython and binds RNA + operators (`bpy`). Most of Blender's UI and add-ons are Python on top of the C core.

Major source areas under `source/blender/`:
- `blenkernel/` (the "BKE" core — datablock lifecycle, depsgraph evaluation hooks, the heart of the data model), `blenlib/` (the "BLI" foundation library — math, containers, strings, threads, used everywhere), `bmesh/` (the editable mesh structure), `geometry/` + `nodes/` + `functions/` (Geometry Nodes / field evaluation system).
- `depsgraph/` — the dependency graph that schedules and parallelizes scene evaluation; central to how changes propagate.
- `draw/` + `gpu/` — the unified draw manager and GPU backend abstraction (Vulkan/Metal/OpenGL).
- `editors/` — all interactive tools/operators and the spaces (3D viewport, sequencer, node editors, etc.); UI logic lives here.
- `render/` (render pipeline), `compositor/`, `sequencer/` (VSE), `modifiers/`, `shader_fx/`, `simulation/`, `freestyle/`.
- `windowmanager/` ("WM" — events, operators, the keymap/tool system), `imbuf/` (image buffers), `gpu/`, `blenfont/`, `blentranslation/`.
- `io/` — importers/exporters (Alembic, USD, OBJ, FBX, glTF C parts, etc.).

`intern/` holds in-house engine/library modules with their own build units, notably `cycles/` (the path-tracing renderer, also buildable standalone via `make cycles`), `ghost/` (the OS/window/input abstraction layer), `guardedalloc/` (`MEM_*` tracked allocator — use it, not raw malloc, for Blender data), `mantaflow/` (fluids), `openvdb/`, `opensubdiv/`, `iksolver`/`itasc` (IK).

`extern/` is third-party code; `source/creator/` is the `main()` entry point / application bootstrap; `release/` holds bundled scripts, themes, datafiles, and the user-facing add-ons.

## Conventions

- Headers: `.h` = C-compatible, `.hh` = C++-only. Function-name prefixes signal the module (`BKE_` blenkernel, `BLI_` blenlib, `WM_` windowmanager, `ED_` editors, `RNA_`, `GPU_`, `DEG_` depsgraph, `MEM_` allocator).
- Every file carries an SPDX license header (checked by `make check_licenses`).
- The `.blend` file format is a hard compatibility contract — treat DNA/RNA/blenloader changes with the versioning discipline described above.
- Generated docs: `make doc_py` (Python API), `make doc_doxy` (C/C++ Doxygen), `make doc_dna` (file-format/DNA).
