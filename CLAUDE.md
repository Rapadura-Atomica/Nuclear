# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

This repository (`Nuclear`) is a fork of [Blender](https://www.blender.org), the free and open source 3D creation suite (modeling, rigging, animation, simulation, rendering, compositing, motion tracking, video editing). It tracks upstream Blender closely; fork-specific changes are individual commits on top of the upstream tree (e.g. the `feat:` commits like Bezier curve support for Grease Pencil). Upstream remote is `lfs-fallback` (`projects.blender.org/blender/blender.git`); `origin` is the fork. The codebase is large (C, C++, Python, GLSL/OSL/MSL shaders) and built with CMake.

Build instructions: https://developer.blender.org/docs/handbook/building_blender/ — Code layout: https://developer.blender.org/docs/features/code_layout/

## Building

Use the top-level `GNUmakefile` wrapper around CMake (run `make help` for the full target list). The build directory defaults to a **sibling** of the source tree: `../build_linux` (so the working copy stays clean). Targets compose, and order is irrelevant.

```sh
make                       # default optimized build into ../build_linux
make developer             # RECOMMENDED for dev: faster builds, error checking, tests enabled
make debug                 # debug binary -> ../build_linux_debug
make full                  # enable all supported deps/options
make lite                  # minimal feature set, fast build -> ../build_linux_lite
make ninja ccache          # use ninja + ccache (combine with the above, e.g. `make developer ninja ccache`)
make config                # open the interactive CMake config tool to toggle options
```

Override with `BUILD_DIR=path`, pass extra CMake args via `BUILD_CMAKE_ARGS='...'`. Each variant (debug/lite/full/bpy) builds into its own suffixed directory, so they don't clobber each other.

Library dependencies are normally **pre-built** and pulled into `lib/` (do not rebuild them). `make deps` is only for platform maintainers; locally-built deps in `lib/` override the precompiled ones and must be manually removed to revert.

`make update` syncs both the repo and the precompiled libraries — run it after pulling if the build breaks on missing/outdated libs.

## Testing

```sh
make test                  # run the full ctest suite (build must have tests enabled, e.g. `make developer`)
```

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
