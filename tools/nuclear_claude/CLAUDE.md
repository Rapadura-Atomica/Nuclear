<!-- SPDX-FileCopyrightText: 2026 Blender Authors -->
<!-- SPDX-License-Identifier: GPL-2.0-or-later -->

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
> - `NUCLEAR_UI_LAYOUT.md` — **the P2 UI spec**: the target layout mapped from the author's
>   mockup (region → native editor → hide/relocate/build), locked decisions, and the
>   phased build order. The source of truth for the UI overhaul.
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
- **⚠️ IMPORTANT — Commit messages are written in ENGLISH.** Use Conventional-Commit style
  (`fix(scope): …`, `feat(scope): …`). This is the standing convention for all new commits, even
  though the in-repo prose docs (CLAUDE.md, ADRs, CHANGELOG) stay PT-BR. Historical commits are
  mixed; do not rewrite them — apply this from now on.
- **Upstream sync = rebase per release** (stay on 5.0; move to 5.1/5.2 as concentrated
  merges). `origin` is the fork; `lfs-fallback` is upstream Blender.
- **3D = hide in the UI only** — never remove 3D/object/depsgraph code (Grease Pencil v3
  depends on it). Since 2026-07-07 the heavy 3D subsystems are also **compiled out of
  official releases** via the `build_files/cmake/config/nuclear_2d.cmake` preset (−21%
  binary; Cycles/Bullet/Mantaflow/Freestyle/USD/etc. OFF, everything the 2D/GP pipeline
  needs stays ON — see the preset's comments). The preset also enables ccache + mold.
  Release builds should configure with `-C build_files/cmake/config/nuclear_2d.cmake`;
  regression gate = `tools/smoke_nuclear2d.py` (headless, 14 checks). Physical source
  removal remains forbidden (Fase 2 da demanda #6 teve ROI ruim; ver
  `~/relatorios/demanda-6.md`).
- **Commercial model = hybrid, GPL kept in full** (ADR
  `docs/decisions/2026-07-07-modelo-comercial-hibrido.md`): (1) in-process Python addons
  are always GPL, monetized by paid access/updates/support (Blender Market model);
  (2) high-value features live in **separate proprietary executables** talking to Nuclear
  via IPC/files (Entremeio pattern) with only a thin GPL bridge inside Nuclear — paid code
  NEVER imports `bpy` or links against the binary; (3) services/support/assets under
  contract. Brand protection via `TRADEMARK.md` (GPL covers code, not the "Nuclear"
  name/logo).
- **Minimize and isolate C divergence.** New Nuclear features should live in *new files*
  (e.g. `*_pegrig.*`, `nuclear_*.py`, new modifiers), not as edits scattered across
  upstream-maintained files. Where touching an upstream file is unavoidable, keep it to a
  minimal "seam" and **record it in `NUCLEAR_DIVERGENCE.md`** — that file is the rebase
  checklist.
- **Prefer upper layers over C** for UI/branding: Application Template + `bpy.app.translations`
  (rename UI labels in bulk) + theme/startup data, before editing C.
- **UI language = English for now** (no localization yet). The current priority is
  *simplifying* Blender's "airplane-cockpit" interface so the artist only worries about
  drawing — that is hide/relocate work (P2), not translation. The translation seam stays
  English-base (`en_US`) and only overrides product branding (Blender→Nuclear); PT-BR can
  be populated into the same dict later. Reach ≈60%+ of the target visual mockup.

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

---

# Nuclear — sistema de atualização (documentação viva)

> **Este arquivo é a fonte da verdade do sistema de auto-update do Nuclear.**
> Sempre que QUALQUER peça mudar (versão, fluxo, caminho de servidor, formato do
> `version.json`, etc.), **atualize este documento na mesma leva**. O agente
> `nuclear-release` é obrigado a fazer isso ao final de cada release.

Última atualização: 2026-07-06.

---

## 1. Visão geral

O Nuclear (fork do Blender) tem um atualizador embutido. Ao abrir, ele consulta um
manifesto JSON no servidor, compara com a versão que está rodando e, se houver build
mais novo, mostra uma tela fixa (estilo "Sobre"). O usuário clica e o próprio Nuclear
baixa, verifica o checksum, troca a versão e reinicia. Tudo no `$HOME` — funciona em SO
imutável (Bazzite/Fedora Atomic) sem mexer em `/usr`, sem fork, sem git, sem recompilar.

Prioridade: **Linux (Bazzite)**. Windows é suportado no apply (junction), mas não testado
em máquina real. macOS cai no fallback de abrir a página.

## 2. Modelo de versão — LEIA ANTES DE MEXER

Há **dois** números, com papéis diferentes:

| Campo | Para quê | Regra |
| --- | --- | --- |
| `NUCLEAR_BUILD` (inteiro) | **Comparação** "tem update?" | **SEMPRE +1 a cada release.** Monotônico. É o que o updater compara. |
| `MAJOR.MINOR.PATCH` (ex: 1.1.0) | **Cosmético** (o que o humano vê) | Segue semver. Não é usado na comparação. |

**Esquema semver (a "questão 1.0.1 / 1.1 / 1.2"):**
- **PATCH** (`1.0.0 → 1.0.1`): correção de bug, sem recurso novo.
- **MINOR** (`1.0.0 → 1.1.0`): recurso novo, compatível.
- **MAJOR** (`1.0.0 → 2.0.0`): mudança grande/quebra de compatibilidade.

> ⚠️ Regra de ouro nº1: **toda release incrementa `NUCLEAR_BUILD`**, não importa se foi
> patch, minor ou major. Se esquecer, as máquinas não enxergam o update (build não é
> maior que o instalado).

Fonte única da verdade: as defines em
`source/blender/blenkernel/BKE_blender_version.h`:

```c
#define NUCLEAR_VERSION_MAJOR 1
#define NUCLEAR_VERSION_MINOR 0
#define NUCLEAR_VERSION_PATCH 0
#define NUCLEAR_BUILD         1
#define NUCLEAR_VERSION_STAGE "Beta"
```

`NUCLEAR_VERSION_STRING` ("Nuclear 1.0.0 (Beta)", na barra de título) é **derivado**
dessas defines. Edite os números aqui e em mais lugar nenhum.

## 3. Peças e arquivos

**No repositório:**
| Caminho | O quê |
| --- | --- |
| `source/blender/blenkernel/BKE_blender_version.h` | defines de versão (fonte única) |
| `scripts/startup/nuclear_update.py` | cliente embutido (notifica + baixa + aplica) |
| `tools/nuclear_release.py` | gera `nuclear_version.json` e `version.json` a partir das defines |
| `tools/nuclear_install/instalarNuclear.sh` | instalador (layout versionado + symlink + .desktop) |
| `tools/nuclear_install/instalarNuclear-wizard.sh` | instalador guiado GUI-first (kdialog→zenity→whiptail→texto/`/dev/tty`) por cima da mesma lógica versionada. **Fluxo simplificado:** pré-checagem → 1 tela (o quê `version_string` + onde + confirmar) → download (barra via `manifest.size`) → concluir. Instala **sempre em `$HOME/Nuclear`** (`--dir` só p/ automação; sem seletor de pasta). **Telemetria oculta por ora** (sem tela de consentimento; opt-out ainda via flag `--no-telemetry` → prefixo `env NUCLEAR_TELEMETRY_OFF=1` no `Exec`; reintroduzir a tela depois). **reexec-em-terminal** se cair no texto sem tty numa sessão gráfica. 100% auto-contido. Overrides p/ teste: `NUCLEAR_INSTALLER_UI`, `NUCLEAR_MANIFEST_URL`, `NUCLEAR_ADDONS_URL` |
| `tools/nuclear_install/build-installer.sh` → `dist/Nuclear-Installer` | gera o **executável de clique único** (o wizard + banner) para máquinas sem Nuclear. **Decisão: NÃO usar AppImage** — nada de libs a empacotar e `libfuse2` costuma faltar em Bazzite/Fedora Atomic; um `.sh` de ~23 KB roda em todo lugar. Provado rodando solto fora do repo. Entrega = servir o arquivo e baixar+`chmod +x`+rodar (deploy no site é manual). |
| `tools/nuclear_install/install-launcher.sh` / `test/install-test-launcher.sh` | registram atalhos `.desktop` no menu: **"Instalar Nuclear"** (produção) e **"Nuclear — Testar Wizard"** (harness `test/run-wizard-test.sh`: servidor local + pacote falso + `$HOME` isolado). |
| `tools/nuclear_telemetry/server/version.json` | espelho do manifesto (referência) |
| `tools/nuclear_telemetry/server/ping.php` | espelho do endpoint de telemetria (eco do manifesto) |
| `tools/nuclear_claude/CLAUDE.md` | **este arquivo** |

**No servidor** (HostGator, `ssh araga286`; domínio `rapaduraatomica.com.br` →
`~/public_html/addon/rapaduraatomica/`):
| URL | Arquivo no disco | O quê |
| --- | --- | --- |
| `estacao/version.json` | `…/estacao/version.json` | **o manifesto que o updater lê** |
| `estacao/nuclear.zip` | `…/estacao/nuclear.zip` | o build portátil (topo `Nuclear/<ver>/…`) |
| `estacao/addons.zip` | `…/estacao/addons.zip` | addons externos |
| `nuclear/nuclear-api/ping.php` | idem | telemetria de presença |

## 4. Formato do `version.json`

```json
{
  "name": "Nuclear",
  "build": 1,
  "version": "1.0.0",
  "stage": "Beta",
  "version_string": "Nuclear 1.0.0 (Beta)",
  "url": "https://rapaduraatomica.com.br/estacao/nuclear.zip",
  "sha256": "<sha256 do nuclear.zip ATUAL>",
  "size": 728581557,
  "min_build": 0,
  "notes_url": "https://github.com/Rapadura-Atomica/Nuclear/releases",
  "notes": "texto curto do que mudou"
}
```

O cliente compara `build` com o build instalado (lido de `nuclear_version.json`, que fica
ao lado do binário). `sha256`/`size` precisam casar **exatamente** com o zip servido.

## 5. Fluxo de release (a sequência correta)

> ⚠️ Regra de ouro nº2: **`nuclear.zip` e `version.json` andam SEMPRE em par.** Nunca suba
> um sem o outro. Foi o que causou o erro "checksum não confere" em 2026-06-11: o zip foi
> trocado e o manifesto ficou com o hash velho.

1. **Bump de versão** em `BKE_blender_version.h`: ajuste MAJOR/MINOR/PATCH conforme o tipo
   de mudança e **incremente `NUCLEAR_BUILD`**.
2. **Rebuild** do Nuclear. O Claude **pode** compilar nesta máquina via o container
   distrobox `blender` (fallback `blenderdev`). **Desde 2026-07-07 releases oficiais
   compilam com o preset 2D** (`nuclear_2d.cmake`: 3D fora, −21% de binário, ccache+mold):
   ```sh
   distrobox enter blender -- bash -lc '/usr/bin/cmake -S <repo> -B <builddir> -G Ninja \
     -DCMAKE_BUILD_TYPE=Release -C <repo>/build_files/cmake/config/nuclear_2d.cmake &&
     nice /usr/bin/ninja -C <builddir> -j3 && nice /usr/bin/ninja -C <builddir> install'
   ```
   (`ninja install` sincroniza os scripts Python/UI no `bin/5.0` e é pré-requisito p/
   rodar `--python`). Build dir vigente: `~/Documentos/GitHub/build_nuclear_2d`. Com o
   ccache quente um rebuild limpo leva **~1min** (frio ~30min; medido 2026-07-07:
   28min03s → 35,8s). Pode haver build concorrente em outro processo, então **confirme
   antes de disparar**. Rodar externamente continua sendo opção.
2.5. **Smoke gate 2D** (obrigatório antes de empacotar; o `nuclear_release.sh` roda
   sozinho): `<builddir>/bin/nuclear -b --factory-startup --python
   tools/smoke_nuclear2d.py` — RC≠0 aborta a release (3D voltou ou capacidade 2D sumiu).
   Empacotar um full build deliberado = `--no-smoke`. (Desde 2026-07-08 o binário chama
   **`nuclear`**; `bin/blender` é o shim de compat — o script aceita os dois.)
3. **Carimbar** o build: `python tools/nuclear_release.py stamp <pasta-do-build>`
   → grava `nuclear_version.json` ao lado do binário.
4. **Empacotar** o zip portátil (topo `Nuclear/<ver>/…`).
5. **Gerar o manifesto** do zip empacotado:
   ```sh
   python tools/nuclear_release.py manifest --zip <nuclear.zip> \
     --notes "o que mudou" -o version.json
   ```
   > 🔐 Se for **republicar o `addons.zip`**, passe `--addons-zip <addons.zip>` no
   > mesmo comando: ele grava `addons_url`/`addons_sha256`/`addons_size` no manifesto
   > e os instaladores passam a **verificar o hash do addons.zip** antes de extraí-lo
   > (sem o campo, cai no modo legado sem verificação). Como qualquer artefato, se
   > mexer no `addons.zip` regere o manifesto no mesmo par (regra de ouro nº2).
6. **Subir os dois juntos** pra `estacao/`: `nuclear.zip` **e** `version.json`.
7. **Conferir que o zip contém o updater** (passo 4.1, regra de ouro nº3 abaixo).
8. **Atualizar ESTE CLAUDE.md** (a tabela de versão atual, a data, o que mudou).
9. **Commit** das mudanças do repo (header, version.json espelho, este doc).

> ⚠️ Regra de ouro nº3: **o zip empacotado TEM que conter
> `Nuclear/5.0/scripts/startup/nuclear_update.py`** (e `Nuclear/nuclear_version.json` ao
> lado do binário). Em 2026-06-11 o build publicado foi empacotado **sem** o updater —
> instalações limpas ficavam sem auto-update nenhum. Antes de publicar, confira:
> `unzip -l nuclear.zip | grep nuclear_update.py`

> ⚠️ Regra de ouro nº4: **o zip tem que ser AUTO-CONTIDO** — além do updater, traz as
> deps Python do fork (`pyclipper`, `triangle`, `scipy`, `scikit-image` + transitivas:
> imageio, tifffile, lazy_loader, networkx, PIL, packaging) embutidas em
> `Nuclear/5.0/python/lib/python3.11/site-packages/`. Senão, **cada auto-update troca a
> pasta da versão por uma extraída do zip e PERDE essas libs** → recursos 2D (fill/balde,
> curve) quebram. O instalador antigo escondia isso instalando as deps via pip por fora;
> no mundo versionado/auto-update isso não vale mais. Confira:
> `unzip -l nuclear.zip | grep -c site-packages/scipy` (tem que ser > 0).
> Não duplique a `numpy` (o Blender já bundla a dele).

> ⚠️ Regra de ouro nº5 (rename do executável, 2026-07-08): o binário agora chama
> **`nuclear`** e o zip TEM que conter TAMBÉM o shim de compat **`Nuclear/blender`**
> (script que faz forward pro `nuclear`, instalado pelo CMake a partir de
> `release/bin/blender`). Motivo: o `nuclear_update.py` das máquinas em build ≤ 10
> procura um arquivo chamado `blender` dentro do zip — sem o shim o apply falha com
> "nenhum binário 'blender' encontrado". O shim é arquivo comum (symlink não sobrevive
> ao `zipfile.extractall`). Confira antes de publicar:
> `unzip -l nuclear.zip | grep -E 'Nuclear/(nuclear|blender)$'` (tem que listar OS DOIS).
> Só remova o shim quando não houver mais máquina em build pré-rename.

### Atalho: rodar o release sozinho, sem o Claude
`tools/nuclear_release.sh` encadeia os passos 1-9 acima num script só, pra quem prefere
rodar o release na mão. Ele bumpa a versão (subcomando `bump` novo do
`nuclear_release.py`, que já cuida da regra de ouro nº1 sozinho), empacota, roda
`verify-zip`/`check-manifest` (checagem automática das regras nº3/nº4 e do "checksum não
confere") e só publica/comita depois de confirmação explícita. Nunca builda sem
`--build`, nunca toca `ping.php`/`instalarNuclear.sh`, e nunca edita este CLAUDE.md por
você — ele só imprime o bloco pronto pra colar na seção "Estado atual" (§10).
```sh
tools/nuclear_release.sh patch --build --notes "o que mudou"   # fluxo completo
tools/nuclear_release.sh minor --dry-run                       # só mostra os comandos
tools/nuclear_release.sh --help
```
Os subcomandos novos do `nuclear_release.py` também funcionam soltos, se preferir montar
o fluxo na mão: `bump {patch|minor|major}`, `verify-zip --zip Z`,
`check-manifest --zip Z --manifest version.json`.

Guia completo (flags, exemplos, troubleshooting) em
[`tools/nuclear_release.md`](../nuclear_release.md).

### Atalho: só corrigir o manifesto de um zip que já está no servidor
Se o zip mudou mas a versão não, recalcule e regrave só o manifesto:
```sh
ssh araga286 'sha256sum ~/public_html/addon/rapaduraatomica/estacao/nuclear.zip; \
              stat -c %s ~/public_html/addon/rapaduraatomica/estacao/nuclear.zip'
# edite sha256 + size no version.json e suba só ele
```

### Atalho: injetar o updater num zip já buildado (sem rebuild)
Se o build saiu sem o `nuclear_update.py`, dá pra adicionar sem recompilar (foi como o
build de 2026-06-11 foi consertado). Backup, injeta nos caminhos internos certos, e
**regera o manifesto** (o sha256 muda):
```sh
# staging local com a estrutura interna do zip:
#   Nuclear/5.0/scripts/startup/nuclear_update.py   e   Nuclear/nuclear_version.json
ssh araga286 'cd ~/public_html/addon/rapaduraatomica/estacao && cp -n nuclear.zip nuclear.zip.bak'
cd <staging> && zip -g <…>/estacao/nuclear.zip \
  Nuclear/5.0/scripts/startup/nuclear_update.py Nuclear/nuclear_version.json
# recalcular sha256+size e atualizar version.json (regra de ouro nº2)
```

## 6. Restrições de deploy (IMPORTANTE)

- O classificador de segurança do Claude Code **bloqueia sobrescrever CÓDIGO em produção**
  (ex.: `ping.php`, `instalarNuclear.sh`). Esses deploys precisam de **aprovação explícita
  do usuário** a cada vez. Faça backup antes.
- **Adicionar/atualizar arquivos de dados** que nós criamos (ex.: `version.json`) é
  permitido — foi assim que o manifesto foi publicado e corrigido.
- Token compartilhado da telemetria (header `X-Nuclear-Token`) já está no repo/servidor.

## 7. Layout de instalação (apply)

Esquema versionado com symlink atômico (Linux) / junction (Windows):
```
~/Nuclear/
  versions/<versão>-b<build>/   <- pasta portátil completa
  current -> versions/<...>      <- ponteiro; o .desktop lança ESTE
```
Apply = baixar → verificar sha256 → extrair → mover pra `versions/` → trocar `current` →
prune (mantém os 3 mais novos + o atual + o que está rodando) → oferecer reiniciar.

**Instaladores no servidor:**
- `https://rapaduraatomica.com.br/instalarNuclear.sh` — antigo, **layout flat** (não
  versionado). Quem instala por ele não se auto-atualiza (cai no fallback de abrir a
  página).
- `https://rapaduraatomica.com.br/instalarNuclear-versionado.sh` — **novo, layout
  versionado** (`versions/` + `current`). É o que habilita o apply real. (Subido como
  arquivo additivo porque sobrescrever o antigo é bloqueado; trocar o canônico precisa de
  aprovação manual.)

**Instalações flat agora se auto-atualizam (2026-06-12).** Antes, um binário solto em
`~/Nuclear/blender` (zip recém-descompactado, sem `current`/`versions`) caía no fallback de
abrir a página — beco sem saída. Agora `_detect_layout` ancora a `base` na PRÓPRIA pasta do
binário (não no pai), e `_can_apply` libera o apply para qualquer instalação gravável. O
flat é **migrado no lugar**: o build novo vai pra `<pasta>/versions/`, cria-se
`<pasta>/current`, e o binário flat antigo fica intocado como fallback. O `.desktop` é
repontado pra `current/blender`. (Bug anterior: a `base` virava o pai, então um flat em
`~/Nuclear/blender` espalhava `~/versions/` direto na home.)

**Fallback de "não dá pra instalar aqui" → PÁGINA INICIAL do repo**
(`github.com/Rapadura-Atomica/Nuclear`), nunca mais o `/releases` vazio. Só macOS e
instalação não-gravável caem nesse fallback. Ver `[[nuclear-auto-update]]` na memória.

## 8. Troubleshooting

| Sintoma | Causa provável | Ação |
| --- | --- | --- |
| "checksum não confere" | zip trocado, manifesto com hash velho | regerar `version.json` (seção 5, atalho) |
| Nenhum aviso aparece | build instalado == build do manifesto, ou sem `nuclear_version.json` | conferir `NUCLEAR_BUILD`; testar com `NUCLEAR_UPDATE_BUILD=0` |
| Nenhum aviso E telemetria não chega | (corrigido) Python do Blender falha HTTPS: `CERTIFICATE_VERIFY_FAILED` (sem CA bundle) | já resolvido: `_ssl_context()` (certifi → bundle do sistema → default) em ambos os scripts. Testar: `<install>/5.0/python/bin/python3.11 -c "import urllib.request,ssl,certifi; urllib.request.urlopen('https://rapaduraatomica.com.br/estacao/version.json',context=ssl.create_default_context(cafile=certifi.where()))"` |
| "Invalid operator call" | (corrigido) operador modal chamado sem evento | já resolvido: dialogs via `invoke_props_dialog` |
| Clica e abre a página em vez de instalar | instalação não-gravável ou macOS (flat já se auto-atualiza desde 2026-06-12) | conferir permissão de escrita na pasta; a página agora é a HOME do repo, não `/releases` |
| Aviso some sozinho | (corrigido) era `popup_menu` | já resolvido: `invoke_props_dialog` |

## 9. Variáveis de ambiente do cliente (debug, sem rebuild)

| Var | Efeito |
| --- | --- |
| `NUCLEAR_UPDATE_URL` | troca a URL do manifesto |
| `NUCLEAR_UPDATE_OFF=1` | desliga a checagem |
| `NUCLEAR_UPDATE_BUILD=0` | finge que o build instalado é 0 (força o aviso) |

## 10. Estado atual

Atualizado em 2026-08-12.

- **Nuclear 1.8.1 (Beta) — `NUCLEAR_BUILD = 23` — PUBLICADO (2026-08-12).** PATCH a partir da
  branch `Nuclear` (HEAD `ab2c0839ccad`, pushado antes do build). sha256
  `aa70890466d316463dd51e2776713dabc253096b423f6a764fccc849df652444`, **355.731.401 bytes**;
  backup da b22 = `nuclear.zip.bak-pre-1.8.1`. Conteúdo idêntico ao da 1.8.0 — o que muda é o
  binário.
  ⚠️⚠️ **A 1.8.0 foi publicada com o clique de seleção MORTO.** Clicar num objeto na viewport não
  selecionava nada; a caixa de seleção também não. Valia para **todo** tipo de objeto (mesh,
  Grease Pencil, empty), não só para desenho — só a seleção por API/menu (`Select All`)
  sobrevivia, que é justamente a que os testes headless exercitam. Num app de animação 2D isso é
  bloqueante: o artista não consegue pegar a peça que quer animar.
  ✅ **A causa NÃO era o código.** O commit publicado (`1297c0ac991e`), recompilado num build dir
  diferente, passa em todos os casos de seleção. O que estava errado era o **build dir**
  `build_nuclear_2d`, de onde a release saiu: ele carregava 856 objetos de builds anteriores a
  agosto que o ninja considerou atuais, e o binário linkado saiu quebrado. Configuração idêntica
  (`diff` dos dois `CMakeCache.txt` = 0 linhas), mesmo compilador, mesmo fonte — binários
  diferentes. A 1.8.1 é o mesmo commit + bump, compilado no build dir são
  (`build_nuclear_rel177`) e **verificado no binário extraído do zip**, não no do build dir.
  ⚠️ **Lição que vale para toda release daqui em diante:** um build dir antigo pode produzir
  binário defeituoso sem erro nenhum de compilação ou de link. Não confie no build incremental de
  um dir parado há semanas — e, principalmente, **teste o binário que vai ser publicado**, não o
  que está no build dir.
  ✅ **Gate novo: `tools/nuclear_rig/selftest_selection.py`** — clique, box select e select-all
  contra mesh, GP (desenho e stroke) e empty. Roda **na GUI de propósito**: o buffer de seleção da
  GPU não existe em `--background`, então nenhum teste headless jamais pegaria essa classe de
  regressão. Rodar antes de empacotar, e de novo no binário do zip.
  ⚠️ O caminho até aqui custou 4 builds porque o bisect por commit **inocentou os dois commits de
  C++** (`5039df5` e `7acd089` passam) — quando o bisect inocenta todo mundo e o binário publicado
  falha, o suspeito passa a ser o AMBIENTE de build, não a árvore. O atalho que resolveu foi
  cruzar binário e scripts entre as versões (`BLENDER_SYSTEM_SCRIPTS`): binário 1.8.0 + scripts
  1.7.8 falha, binário 1.7.8 + scripts 1.8.0 passa — em dois minutos isso separa código de
  binário.

- **Nuclear 1.8.0 (Beta) — `NUCLEAR_BUILD = 22` — PUBLICADO (2026-08-12), SUPERSEDIDA pela 1.8.1
  no mesmo dia (binário com a seleção quebrada, ver acima).** MINOR a partir da
  branch `Nuclear` (HEAD `1297c0ac991e`, pushado ANTES do build; o binário carimba esse mesmo
  hash). sha256 `7a0f0cf737ca0eb7bd7b05eff043adedda5f5b5a608a7e00addaea3481859f5f`,
  **357.920.858 bytes**; backup da b21 = `nuclear.zip.bak-pre-1.8.0` (o `bak-pre-1.7.7` saiu pela
  política de dois). **Três frentes.**
  (1) **Opacidade por objeto e por peg, herdada pela cadeia** (`5039df57423`, `7acd0899a3d`,
  `d96b892d61b`): fadear o Master Peg fadeia tudo que está pendurado nele, que é o controle de
  "personagem inteiro" que o fluxo cut-out espera. `Object.opacity` ocupa os bytes de `_pad2` (o
  struct não cresce) e vale no **render**, não só no viewport; a coluna de opacidade no Outliner é
  um NumSlider vizinho do cadeado; o painel Active Peg ganhou o slider e um leitor do valor
  resolvido, que só aparece quando um ancestral está fadeando o peg ativo — sem ele o rigger lê
  1.00 numa mão cujo Master está em 0.2 e não tem onde olhar. Versionamento em (500, 123): sem a
  migração, arquivo anterior abriria com o elenco inteiro invisível.
  ⚠️ A armadilha que custou o segundo commit: a Follow Peg dobrava a opacidade do peg **dentro**
  de `ob->opacity` com `*=`, e a cópia avaliada não é refrescada quando só parâmetros mudam — o
  multiply caía no produto da avaliação anterior e **compunha**. Cada toque escurecia mais (0.5,
  0.5×0.8, …), nunca clareava de volta, e no 0 ficava preso, porque zero é absorvente. Ler o valor
  do objeto original também não serve (a opacidade animada do próprio objeto é escrita na cópia
  avaliada). A saída foi campo próprio `ObjectRuntime::peg_opacity`, que a constraint **ATRIBUI**
  em vez de multiplicar — atribuição é idempotente por quantas vezes a avaliação rodar.
  ⚠️ **Limitação conhecida, publicada assim:** ao abrir um arquivo salvo a herança fica velha até
  algo taggar o rig (`world_opacity` é runtime mas mora no DNA e volta do disco). O
  `tools/nuclear_rig/selftest_opacity.py` reprova essa única checagem **de propósito** — ela se
  chama `BUG:`. As outras 31 passam neste binário; falha ali é o esperado, não regressão.
  ⚠️ Ao conferir a feature no binário, pergunte ao `bl_rna.properties`: `hasattr(bpy.types.Object,
  "opacity")` devolve **False** mesmo com a propriedade registrada — falso negativo que quase
  reprovou uma build boa.
  (2) **O Xsheet (timeline Toon Boom) passa a valer nos três app templates** (`32d77b6f756`):
  vivia inline no template `Nuclear` como Seam 7, então trocar para `2D_Animation` ou
  `Storyboarding` devolvia o artista ao dope sheet nativo. Virou `scripts/modules/nuclear_xsheet.py`
  (auto-contido: bpy, gpu, blf), trazido do fork Nuclear-Ditivado, que já tinha refatorado e somado
  **seleção de células** — box select, mover/duplicar bloco, apagar seleção (camada travada é
  recusada com aviso, não pulada em silêncio). Só a timeline viaja: a fileira de transporte (+KF/
  -KF, play, campos de frame) continua sendo override de header do template `Nuclear`, para que os
  outros dois mantenham header e footer nativos em vez de perder o transporte.
  `tools/nuclear_xsheet_selection_test.py`: 28/28 neste binário.
  (3) **O Nuclear reivindica o duplo-clique, e não só se oferece** (`b5c521b9151`, `fb4850aa5f3`,
  detalhado no item abaixo): instaladores reivindicam sem perguntar, updater só conserta padrão
  ausente ou morto. Junto vai o conserto do updater que **sequestrava launcher alheio**
  (`b390e71ca49`): `Exec=dolphin %u` tem dirname vazio, e o `realpath` resolvia isso contra o
  diretório de trabalho corrente — que fica dentro da base enquanto o Nuclear roda —, então todo
  `.desktop` de terceiro com comando nu era reescrito para apontar ao Nuclear. Agora exige caminho
  absoluto e compara ancorado em fronteira de path (`<base>-old` não conta mais). No mesmo commit,
  a reescrita parou de descartar o prefixo `env NUCLEAR_TELEMETRY_OFF=1` — um update religava a
  telemetria em silêncio numa máquina que tinha optado por sair.
  ⚠️ **O publish desta release saiu em UMA fase, por engano** (`scp` do zip e do manifesto direto
  por cima, em vez de `.new` + `mv` duplo): houve uma janela de ~30s com zip novo e manifesto
  velho, e o backup da b21 **não** foi criado na hora — foi restaurado depois a partir da cópia
  local de `build_nuclear_rel177`, com sha256 conferido contra o que estava publicado. Sem estrago
  permanente, mas é exatamente o risco que as duas fases existem para eliminar.
  ✅ Compilada no repo principal com o build dir `build_nuclear_2d` (sem sessão paralela viva
  nesta máquina, conferido antes de começar); smoke gate 2D ALL PASS.
  ⚠️ **Ficou de FORA da b22:** `e7fdc17289a` (Xsheet: exposição em F6/F7, duplicação em Ctrl+D,
  Ctrl+click desligado) foi pushado às 16:01 de 2026-08-12, **depois** do bump `1297c0ac991e` e
  com o build já rodando. Quem atualizar para a 1.8.0 continua com o Ctrl+click da célula; os
  atalhos novos saem na próxima release. É a versão da corrida "pushe antes de buildar": o commit
  de outra pessoa pode entrar na janela do build, e o que vale é o hash carimbado no binário.

- **Entregue NA 1.8.0 (era o item pendente de 2026-08-12) — o Nuclear reivindica o
  duplo-clique, e não só se oferece.** Sintoma relatado: "o atalho do Nuclear está
  em outros aplicativos". O `.desktop` estava impecável — `Categories=Graphics;2DGraphics;`,
  `desktop-file-validate` limpo, e o `kbuildsycoca6 --menutest` confirma o item em **Gráficos**.
  Quem estava errado era o **`mimeapps.list`**: escrever `MimeType=` apenas OFERECE o app; quem
  decide o duplo-clique é a seção `[Default Applications]`, e todo o resto é rebaixado à gaveta
  "Outros aplicativos". Nenhum dos três pontos que escrevem o lançador (`instalarNuclear.sh`,
  `instalarNuclear-wizard.sh`, `nuclear_update.py`) chamava `xdg-mime default`, então o padrão
  continuava sendo o que a máquina já tivesse — frequentemente uma entrada descartável que o
  **diálogo "Abrir com" do KDE grava sozinho** (`<nome>-N.desktop`, `NoDisplay=true`) apontando
  para um binário que não existe mais; aí o `.nuc`/`.blend` não abre em **nada**. Conserto em
  duas alturas, com políticas deliberadamente diferentes: os **instaladores** reivindicam sem
  perguntar (instalar é ato explícito do usuário) via `xdg-mime default` com fallback inline
  para máquina sem `xdg-utils`; o **updater** (`_claim_file_associations`, chamado do
  `_reconcile_desktop` e do `_run_apply`) é conservador — só reclama padrão **ausente ou
  quebrado**, então escolher outro app para `.blend` continua valendo. ⚠️ **As duas decisões
  usam critérios propositalmente diferentes**, e misturá-las é como se estraga um `mimeapps.list`
  alheio: **podar** exige o `.desktop` fisicamente ausente (não há como errar), enquanto o teste
  mais fraco "o Exec parece morto" fica restrito a decidir se o Nuclear pode reivindicar o
  padrão — ali um falso negativo custa uma reivindicação, nunca a associação de outro app. A
  primeira versão podava pelo teste fraco e apagou uma associação boa na hora do teste (o
  `Exec` do handler tinha o caminho **entre aspas**, e o `"` era lido como parte do caminho).
  ✅ **Sem a lacuna estrutural de sempre:** como roda no `register()` (startup), a máquina se
  conserta na PRIMEIRA abertura depois de receber a build — não precisa de duas releases.
  Testes: 12 checagens headless em HOME falso (padrão morto reclamado, escolha válida
  preservada, arquivo criado do zero, idempotência, poda de órfã, Exec entre aspas, entrada
  zumbi, no-op sem Nuclear utilizável, seção faltante) + fallback shell dos dois instaladores
  exercitado nos dois ramos.

- **Nuclear 1.7.8 (Beta) — `NUCLEAR_BUILD = 21` — PUBLICADO (2026-08-11).** MINOR a partir da
  branch `Nuclear` (HEAD `4b5b83d220fa`, já em `origin/Nuclear` antes do build; o binário
  carimba esse mesmo hash). sha256 `ba33cbf5c88eb2198e81cff4696894754a721aee9384ee5822d20eba29f251a2`,
  **355.372.074 bytes**; backup da b20 = `nuclear.zip.bak-pre-1.7.8` (o `bak-pre-1.7.6` saiu
  pela política de dois). **Uma entrega, em duas metades que só valem juntas.**
  (1) **A aba `Storyboard` no Properties** (`36b3ba53bfa`, `160c296539a`, `63fc45ad5b4`): a
  coluna de planos do storyboard deixa de disputar os 280px da sidebar com episódio, cena,
  biblioteca e entrega, e passa a ocupar a área inteira de um editor — o artista encosta uma
  coluna estreita na lateral e lê a cena de cima para baixo, um plano por linha. Custou ~25
  linhas em 4 arquivos (`BCONTEXT_STORYBOARD` no `DNA_space_enums.h`, item no
  `buttons_context_items` + `filter_items` do `rna_space.cc`, `add_tab` + context string no
  `space_buttons.cc`, `case` do path no `buttons_context.cc`), o mesmo caminho da aba Paint —
  muito mais barato que um SpaceType novo, e sem versionamento (`visible_tabs` nasce `uint(-1)`).
  ⚠️ A armadilha que custou um rebuild: `buttons_context_path` empurra o **view layer** por cima
  da cena para toda aba fora do `ELEM(mainb, BCONTEXT_SCENE, RENDER, OUTPUT, VIEW_LAYER, WORLD,
  STRIP, STRIP_MODIFIER)` — aba ancorada na cena que não entre nessa lista tem o path terminando
  no view layer e `ED_buttons_tabs_list` a derruba **sem erro nenhum**. São DUAS edições no
  `buttons_context.cc`, o `case` e o `ELEM`. Só a GUI pega: em headless o item do enum existe e
  `show_properties_storyboard` é True, porque a filtragem acontece ao desenhar a região.
  (2) **O add-on Storyboard & Animatic passa a viajar dentro do Nuclear** (`c02b748fd26`), em
  `scripts/addons_core/nuclear_storyboard` (v0.15.0, 77 arquivos no zip). Sem isso a metade (1)
  não serve para ninguém: a aba existiria vazia em toda estação onde o add-on não tivesse sido
  instalado à mão. `make_release.py --para-o-nuclear <repo>` sincroniza as duas cópias pela mesma
  lista de arquivos do zip. ⚠️ A cópia empacotada **ganha do symlink de desenvolvimento** —
  num Nuclear buildado, editar o repo do add-on e não ver efeito nenhum é o resultado esperado.
  O add-on peneira sozinho (`boardpanel.tab_available()` pergunta ao enum do RNA, não à versão
  do Nuclear): em build sem a aba, a grade volta para a sidebar em vez de sumir.
  ⚠️ Compilada na worktree isolada `nuclear-rel-177` (build dir `build_nuclear_rel177`) porque
  havia sessão paralela viva na máquina — mesma receita da 1.7.7.

- **Nuclear 1.7.7 (Beta) — `NUCLEAR_BUILD = 20` — PUBLICADO (2026-08-10).** PATCH a partir da
  branch `Nuclear` (HEAD `b702f68c0686`, pushado ANTES do build). **Três frentes, sendo a
  primeira o motivo da release.**
  (1) **A atualização passa a "grudar" na máquina do artista** (`a14a43a56ff`,
  `nuclear_update.py`). Sintoma relatado de uma máquina fora da LAN: baixava os 357 MB,
  aplicava, reiniciava no build novo — e a abertura seguinte voltava ao binário velho, então
  baixava tudo de novo. Seis downloads completos num único dia, todo dia. O apply sempre
  funcionou; quem estava errado era o **atalho**: o pin do KDE apontava para um binário fora do
  `current` (o flat deixado como fallback pela migração, ou um `.desktop` órfão de antes do
  rename), e o `_reconcile_desktop` da b16 só sabia consertar o `Nuclear.desktop`. Agora
  `_refresh_desktop` varre **todos** os `.desktop` (`~/.local/share/applications` + base) e
  reescreve `Exec=`/`TryExec=` que apontem para dentro da base por fora do `current`; e
  `_ground_flat_binary` aposenta o binário flat (`<base>/nuclear|blender` →
  `*.pre-versioned.bak`) deixando no lugar um shim `#!/bin/sh` para `<base>/current/nuclear` —
  idempotente, marcado por `_SHIM_MARKER`, nunca apaga nada. Roda no `register()` (startup) e no
  `_run_apply`. ⚠️ Vale a lacuna estrutural de sempre: **quem aplica uma release é o updater da
  ANTERIOR**, então este conserto só age depois que a máquina receber a b20 uma vez — o que ela
  já faz sozinha, todo dia, por causa do próprio loop.
  (2) **Trava (cadeado) de coleção e objeto no Outliner** (`005da2d6d44`), o equivalente ao lock
  do Harmony: enquanto se anima um personagem, o resto da cena para de responder ao cursor. A
  trava **implica** "disable selection" em vez de reimplementá-la — `COLLECTION_LOCKED`/
  `OB_LOCKED` chegam à Base como `BASE_LOCKED` e o layer sync limpa `BASE_SELECTABLE`, então
  picking, box select, Select All, Outliner e canais de animação recusam a peça travada pela
  maquinaria que já existe, e o clique **atravessa** a peça travada até a de trás (o Pick Peg
  não precisou de mudança nenhuma). Ao contrário da visibilidade do upstream, que acumula
  permissivamente, a trava é **restritiva**: objeto linkado numa coleção travada e noutra livre
  continua travado. O que a seleção não cobre foi barrado explicitamente — troca de modo
  (`ED_operator_object_active_editable_ex`), desenho em GP (`active_grease_pencil_poll`, que
  pega a peça já em paint mode quando foi travada) e o converter de transform do PegRig, que lê
  o objeto **ativo** e não a seleção (travar deseleciona, mas não desativa).
  (3) **Pivôs do PegRig ficam onde o rigger colocou** (`4b6412f5793`), quatro causas medidas em
  `carolina_pegs_atualizada.blend` (84 pegs, 41 com desenho): o setter gravava o alvo cru, mas o
  centro de rotação é `parent_world @ (pivot + translation)`, então o pivô nascia deslocado de
  exatamente `|t|` (14 de 14 pegs arrastados); `Pivot to Drawing` mirava a **bbox avaliada**, ou
  seja, a célula que estivesse no playhead (alvo variando até 4,82 u entre frames em 34 de 41
  peças), e passou a usar a união de todas as células (dependência de frame: 1 de 41); o graph
  sync re-ancorava a cada tree update — inclusive o do **undo** —, e reescrever a inverse matrix
  de um desenho bindado cancela a pose que a peg segurava (peça posada em (0.4, 0, 0.3) caía
  para a origem); e o auto-rig herdava a mesma dependência de frame na detecção de junta.
  **Build e verificação:** compilado numa `git worktree` isolada (`nuclear-rel-177` +
  `build_nuclear_rel177`, preset `nuclear_2d`, `-j2`/`-j3`) porque outra sessão editava o source
  do repo principal ao vivo — o primeiro build foi **descartado** por ter incorporado código não
  commitado (aba Storyboard, `36b3ba53bfa`, que fica para a b21). Carimbo do binário
  `b702f68c0686` == HEAD == `origin/Nuclear`, splash/Sobre em **Nuclear 1.7.7**; smoke 2D
  ALL PASS; poda 1169 → 859 MB; zip de **354.871.380 bytes**, sha256
  `690ff6880eda95a26c35ebd2e544661e66d1b0596b476314292e91673045489d`; verify-zip (updater +
  2615 arquivos `scipy`, sem peso morto 3D) e check-manifest OK; regra nº5 conferida à mão
  (`Nuclear/nuclear` **e** `Nuclear/blender`). Publicado em duas fases (`.new` → sha256 conferido
  no servidor → os dois `mv` no mesmo `ssh`). Backup da 1.7.6: `nuclear.zip.bak-pre-1.7.7`; o
  `bak-pre-1.7.5` foi removido pela política de dois. `ping.php`/`instalarNuclear.sh` não
  tocados. ⚠️ O `version.json.sig` órfão continua desatualizado, sem chave e sem dono.
  ⚠️ A `scipy` **não vem** do `ninja install` — foi copiada do `bin/` do build anterior antes de
  empacotar, como manda a regra nº4.

- **Nuclear 1.7.6 (Beta) — `NUCLEAR_BUILD = 19` — PUBLICADO (2026-08-06), superado pela 1.7.7.** PATCH a partir da
  branch `Nuclear` (HEAD `34cff92658f`), 100% Python de startup. **Duas frentes, ambas de
  "o que a tela mostra não é o que o arquivo tem".**
  (1) **O realce da peg acompanha a viewport e a célula exposta** (`de9a03d3045`,
  `nuclear_peg_graph.py`): a silhueta verde é cacheada por peça e a chave era cega a duas coisas
  que o artista faz o tempo todo. A chave de view lia a translação da matriz na última **linha**
  (`vm[3][0..2]`) — mas `mathutils` indexa `m[linha][coluna]` e a translação mora na **coluna 3**,
  então aqueles três termos são o `(0,0,0)` constante de uma matriz afim; zoom nem entrava na
  chave. Só orbitar invalidava, e num viewport 2D ninguém orbita: **pan e zoom deixavam o realce
  congelado** nos pixels anteriores. A chave passou a ser a `perspective_matrix` inteira — a mesma
  matriz que `_project` usa, então cobre rotação+pan+zoom por construção. E **nada despejava a
  peça cuja CÉLULA muda**: a Cell Library instancia outro drawing no MESMO keyframe do MESMO
  frame, com a peça parada, então frame/matriz/view batiam e o cache servia a célula anterior até
  mudar de frame ou mexer na peça; `_drop_geometry_caches()` agora despeja por
  `is_updated_geometry` no `depsgraph_update_post`, **antes** do guard de `_SYNCING`, do skip de
  playback e do debounce (os três engoliriam o evento), casando nome do objeto **e** do data-block.
  ⚠️ Peça **com modifier** pula os dois caches, o que fazia o defeito parecer intermitente — quem
  congelava era mão/boca/olho, justamente o perfil que usa Cell Library. Regressão headless de 13
  checagens; o flood fill do matte que volta a rodar no pan custa 0,16 ms/redraw.
  (2) **Personagem tombado no repouso: `Fit Curve to Drawing` endireita de verdade**
  (`a36c20774f4`, `nuclear_deform_curve.py`), a partir de `~/relatorios/deform-curve-torso-torto.md`.
  Rig com Deform Curve no torso saía pendendo em preview, thumb e take: o desenho é reto, a curva
  inclina, e o modifier **reconstrói** o desenho sobre a curva (`strength=1`). Eram **quatro
  defeitos empilhados, cada um escondendo o seguinte**: (a) a forma da curva é animada no
  **DATA-block**, não no objeto — por isso o diagnóstico inicial apurou "0 F-Curves" (eram 27
  canais com 1 key cada); (b) escrever `bp.co` sem tocar a F-Curve é **no-op silencioso** (a
  avaliação replaya a key por cima) e o operador ainda reportava `FINISHED` — agora cada canal
  anda pelo mesmo delta do ponto, preservando animação por cima; (c) o `_bind` devolve a curva
  animada ao **rest carimbado** antes de bindar, o que logo após um fit **desfazia o conserto** —
  o fit passou a restampar o rest e a bindar contra a forma que assentou; (d) `kp.co_ui` já
  arrasta as tangentes, e somá-las de novo movia o handle **2×**, entortando a Bézier e piorando
  a cada passe (0,08 → 0,15 → 0,28 → 0,45). Junto: **`Check Deform Curves` ganhou a métrica
  objetiva** (avalia a peça com e sem o modifier, acusa desvio > 0,05 u) — ⚠️ medida na curva
  **como avaliada**, não no rest, senão o defeito some (2,7e-08 numa peça visivelmente torta) —
  e voltou a varrer o **arquivo**: ele inspecionava só a peça SELECIONADA e, como o `.blend`
  guarda a seleção, respondia "no piece carries a Curve modifier" em rig cheio delas (a ATENA
  reportava zero). Medido, desvio antes → depois de um fit: Quetzalcoatl `tronco` 0,476 →
  **0,000**, tezca `tronco` 0,179 → 0,000, dinossauro `rabo` 0,374 → 0,000, `Stroke.018` 0,122 →
  0,000, `canela.e` 0,045 → 0,000; idempotente em 4 passes; **controle**: ATENA e as 5 peças já
  ajustadas do dinossauro seguem em 0,000. ⚠️ **Nenhuma mudança de código endireita arquivo já
  salvo** — cada rig precisa ser refitado e salvo, e os takes remontados; o Check aponta quais.
  ✅ **A string compilada voltou a bater:** este release **recompilou** (o que a 1.7.5 não fez),
  então splash/Sobre/crash report dizem **1.7.6** e o `build hash` é `34cff92658f6` == HEAD ==
  `origin/Nuclear` (pushado ANTES do build, como manda a pegadinha do `@{u}`). Compilado em
  `build_nuclear_2d` (preset `nuclear_2d.cmake`, ninja **-j2** com duas GUIs do usuário abertas).
  Smoke 2D ALL PASS no binário e de novo no staging; poda 1175 → 865 MB; zip de
  **357.290.441 bytes**, sha256
  `8b7a5d8d0b8579d02e99da1da0f86009695b7525f9a25bfe7bdb544cbb8952e9`; verify-zip (updater + 2615
  arquivos `scipy`, sem peso morto 3D) + check-manifest OK. Publicado em duas fases. Backup da
  1.7.5/b18: `nuclear.zip.bak-pre-1.7.6`. `ping.php`/`instalarNuclear.sh` não tocados.
  ⚠️ O `version.json.sig` órfão (sistema "Marketplace" fora do repo, ver 1.7.5) **continua
  desatualizado** — segue sem chave e sem dono documentado.

- **Nuclear 1.7.5 (Beta) — `NUCLEAR_BUILD = 18` — PUBLICADO (2026-08-05), superado pela 1.7.6.** PATCH a partir da
  branch `Nuclear` (HEAD `7c4cc78072a`, 9 commits sobre a 1.7.4/b17, já pushados antes deste
  release). **Cinco frentes:** (1) **Converter Armature em Pegs** (feature nova,
  `nuclear_rig_auto.py`): personagem legado rigado com armature vira PegRig casando por nome;
  validado do zero — 66 pegs (34 juntas + 32 desenho), 32/32 peças presas, rótulos em
  português. (2) **Deform Curve — bind não congela mais o desenho** (`3e02e18`, `abeb1eb`): o
  bind passa a guardar a curva de REPOUSO e medir contra o desenho vivo, então um desenho
  bindado continua editável; bindar uma curva já animada usa o rest carimbado em vez da pose do
  frame corrente. Validado: desvio 0,000000 ao reavaliar, salvar+reabrir e ir/voltar no tempo.
  (3) **Deform Curve — a peg dirigida copia a TANGENTE, não a corda** (`b6d4987`, fix
  documentado). (4) **Seleção de Grease Pencil bate com o que é desenhado**
  (`abeb1eb`/`0c6ba93`/`d4ffd27`): planos de profundidade na ordem do render, tolerância
  apertada, atalho de matte local; camadas com mask de Auto-Patch voltaram a ser clicáveis; o
  corte de mask por **stencil foi REMOVIDO** (nunca funcionou — reduzia área clicável em vez de
  recortar). (5) **Peg verde vs. objeto azul** (`7c4cc78`, feature/UX): dá pra distinguir a peg
  do objeto selecionado, e a forma da peg passou a ser o desenho avaliado (com masks) em vez de
  um retângulo. ⚠️ **Não comparar com números de acerto de clique da 1.7.4** — o b17 não tem a
  propriedade `location` em `object.pegrig_pick`, então o harness novo (medição por diferença de
  render) nem roda nele; os números atuais (métrica nova, não comparável) são Atena 94,2% ·
  Carolina 87,2% · dinossauro 80,0% · Lala 66,4%. Também não afirmado: ganho "182ms→1,4ms" do
  overlay (não medido nesta rodada, precisa de GUI). **Rebuild feito por outra leva de trabalho
  ANTES deste release** (commit `7c4cc78072a`, `ninja install`, smoke 2D 15/15 ALL PASS) — este
  agente só bumpou versão/build e publicou; não recompilou. ⚠️ **Consequência aceita:** o binário
  empacotado tem `NUCLEAR_VERSION_STRING` compilado como **"Nuclear 1.7.4"** e `build hash
  7c4cc78072af` (commit anterior ao bump), enquanto o manifesto/`nuclear_version.json` dizem
  corretamente **1.7.5 / build 18** — só cosmético (Sobre/splash/crash report mostram "1.7.4"),
  **não afeta o auto-update** (o cliente compara pelo `nuclear_version.json` ao lado do binário,
  não pela string compilada). Decisão: **não rebuildar** para não disparar `ninja` com a RAM
  praticamente sem swap livre (0,03 GB de 7,9 GB de swap livres no momento do publish) sem
  confirmação do usuário — realinhar a string compilada fica para o próximo release que
  recompilar (nenhuma ação extra necessária, resolve sozinho). Compilado em `build_nuclear_2d`
  (preset `nuclear_2d.cmake`). Staging: `cp -al bin Nuclear` → poda 1175→865 MB → stamp → smoke
  2D re-rodado no staging (15/15 ALL PASS) → zip. Zip de **357.281.180 bytes** (~341 MB).
  verify-zip (updater + 2615 arquivos `scipy`, sem peso morto 3D) + check-manifest OK. Publicado
  em duas fases (`nuclear.zip.new`+`version.json.new` → sha conferido no servidor → os dois `mv`
  no mesmo comando); sha256 do zip live == manifesto live == resposta pública ==
  `4fc289877606e6a3bf46007826ccd09f1131cdc00fbf396e90dc283625e73c67`, `content-length` público
  confere. Backup da 1.7.4/b17: `nuclear.zip.bak-pre-1.7.5`; o backup mais antigo
  (`nuclear.zip.bak-pre-1.7.3`) foi podado para manter a política de guardar só os 2 mais
  recentes. `ping.php`/`instalarNuclear.sh` não tocados.
  ⚠️ **Achado no servidor, fora do escopo deste release:** `estacao/` agora tem um sistema
  **"Marketplace"** não documentado aqui e ausente do repo (`marketplace.json` + `.sig`,
  `marketplace/<id>/…`, catálogo de itens tipo "palette") e um `version.json.sig` (ed25519,
  `key_id: nuclear-release-2026-07`) assinando o manifesto — nada disso existe em
  `scripts/startup/nuclear_update.py` nem em qualquer branch deste repo (`grep` vazio), então o
  cliente de auto-update atual **não verifica** essa assinatura; o publish desta release deixou
  o `version.json.sig` **desatualizado** (assinado para o `version.json` da 1.7.4). Não mexi
  nele — sem a chave privada e sem documentação de quem/como mantém esse sistema. Se for um
  mecanismo ativo (outro processo/sessão), precisa de re-assinatura manual; o dono do servidor
  deveria registrar esse sistema em algum lugar (aqui ou em doc próprio) para o próximo release
  saber lidar com ele.

- **Nuclear 1.7.4 (Beta) — `NUCLEAR_BUILD = 17` — PUBLICADO (2026-07-31), superado pela 1.7.5.** PATCH a partir da
  branch `Nuclear`, juntando duas frentes que rodaram em paralelo na mesma branch. **Destaque —
  duas perdas de desenho no Grease Pencil**, ambas herdadas de comportamento upstream e ambas
  candidatas a mandar para o upstream. (1) **O `I` no Dope Sheet apagava o elenco inteiro**
  (`action_edit.cc`): `insert_action_keys` derivava `grease_pencil_hold_previous` do flag
  **"Additive Drawing"** (`GP_TOOL_FLAG_RETAIN_LAST`), que vem **off de fábrica**; com ele off,
  `insert_grease_pencil_key` cai no ramo "insert a blank frame" e o `I` insere keyframe **vazio**
  em cada canal que toca, apagando o desenho dali em diante — e com `type='ALL'` (o default do
  menu) isso é todo canal visível de todo objeto listado. Medido no rig de referência: 670→798
  keyframes em 54 peças e **43 peças visíveis → 0**. Agora inserir keyframe **segura o desenho
  exposto** (comportamento Toon Boom); o branco continua entrando quando não há o que segurar (sem
  frame ativo, ou end frame), e o flag mantém a outra função dele (semear um frame recém-desenhado
  com os traços anteriores). O caminho legado de anotações (`ANIMTYPE_GPLAYER`) não foi tocado.
  (2) **O Interpolate esvaziava camadas sem par** (`grease_pencil_interpolate.cc`): o `layer_mask`
  guardava **toda** camada, inclusive as sem intervalo interpolável, então o `init` inseria nelas
  um BREAKDOWN **vazio** e o `update` sobrescrevia com nada o que houvesse no frame — e como só o
  *Cancel* restaura, confirmar deixava a camada em branco dali em diante. O mask passa a ser
  reduzido às camadas com mapeamento (a mesma garantia que o `interpolate_sequence` já tinha).
  Junto: o `invoke` chamava só os status indicators, e o modal só preenche os keyframes no
  primeiro `MOUSEMOVE` — invocar pelo menu e confirmar de imediato esvaziava **todos** os alvos;
  passa a chamar o `update`. Prova A/B no mesmo arquivo, frame 4, peça `boca`: o binário b16 cria
  4 breakdowns vazios (`dente-line`, `dentes`, `fundo`, `lingua`), o binário novo cria **0**.
  **Segundo bloco — a deform curve virou animável de verdade.** O gizmo keyava só o ponto
  arrastado, mas tangente `AUTO` é recalculada a partir dos vizinhos: sem key neles a curva
  carregava as tangentes da pose e **o desenho não voltava ao repouso**. `keyframe_whole_curve()`
  keya a curva inteira; resíduo de ida-e-volta ao frame de repouso no dinossauro: `torso.004`
  0.1954→0.0000, `braco.e` 0.0980→0.0000, `braco.d` 0.0821→0.0000 (as outras 5 já estavam em 0).
  E as keys **não apareciam em lugar nenhum**: `animdata_filter_dopesheet_ob` (`anim_filter.cc`)
  passa a listar a animação das curvas do modifier `GREASE_PENCIL_CURVE` **sob o objeto do
  desenho** — quem se seleciona é a peça, mas a Action mora no data-block da curva. Como o Dope
  Sheet do workspace 2D abre em modo **Grease Pencil**, que lista só camadas, o arquivo que
  carrega PegRig agora abre em modo **Dope Sheet** (`scripts/startup/nuclear_timeline_mode.py`,
  handler `load_post`; nada é gravado no arquivo, e storyboard sem rig fica no modo GP). Ensinar o
  modo GP a listar F-Curves foi **rejeitado**: o próprio upstream avisa no código que exigiria
  mexer em quase todo operador que testa `ANIMCONT_GPENCIL` (seleção, delete, snap, copy/paste), e
  o canal apareceria desenhado recusando ser editado — pior que hoje. **Terceiro bloco —
  Entremeio.** O registro de gerados guardava só a identidade `[peg, canal, frame]`, então quando o
  artista repunha um in-between (promovendo-o a pose-chave real) a geração seguinte o reconhecia
  como "meu" e **apagava a pose do artista** — o oposto do P1 do PRD. O registro passa a guardar os
  valores escritos, e `clear_generated`/`clear_generated_entries` comparam o valor atual da F-Curve
  (epsilon 1e-5) antes de apagar; se divergiu, o frame só sai do registro e o keyframe fica.
  Junto, os dois guarda-corpos pós-escrita (drift em âncora e exposição GP) **revertem** a escrita
  e cancelam com erro, em vez de só avisar — antes falhavam abertos. Sincronizado do repo-fonte
  `entremeio` em `2245e15`, 50 testes passam. Vão junto o painel `Rig ▸ Deform Curve`
  (`c52c8f31128`, 885 linhas) e os fixes de Entremeio de 28/07 (clamp anti-overshoot, drift medido
  antes/depois, `anchors_span` ignorando biblioteca de poses e Cell Library, rig alvo = o que a
  cena usa). **Fora do escopo por decisão do usuário:** o Armature→PegRig nativo
  (`nuclear_rig_auto.py`, +374 linhas) segue na working tree, e o addon `nuclear_storyboard` (repo
  separado, hoje só um symlink de dev com 682 linhas não commitadas) entra numa release futura
  quando o desenvolvimento fechar — o app template `Storyboarding` já viajava no pacote e continua
  indo. ⚠️ **Pegadinha do carimbo:** o `buildinfo.cmake` do upstream usa `git rev-parse @{u}`, o
  **upstream tracking branch** — não o HEAD local. O primeiro pacote saiu carimbado
  `0a5197b4a15a` (o que estava no `origin/Nuclear`), sem cobrir os 4 commits locais; **pushe antes
  de buildar** ou o hash do splash/relatório de crash aponta para a release errada. Refeito:
  commit de release → push → `ninja install` (regenera buildinfo e re-linka, 6 passos) →
  re-empacotar, e o carimbo virou `b9877095b4d0` == HEAD == `origin/Nuclear`. **Manutenção do
  servidor:** os `nuclear.zip.bak*` foram podados de 18 para 2 (ficaram `bak-pre-1.7.4` = b16 e
  `bak-pre-1.7.3` = b15), liberando ~9 GB — o disco saiu de **89% → 88%**, fechando a pendência
  que se arrastava desde a b14. Compilado em `build_nuclear_2d` (container `blender`, preset
  `nuclear_2d.cmake`, ninja **-j2** por causa da RAM disputada com duas GUIs abertas do usuário).
  Smoke 2D ALL PASS; staging podado 1175 MB → 865 MB; zip de **340 MB** (357.250.470 bytes);
  verify-zip (updater + 2615 arquivos de `scipy`, sem peso morto 3D) + check-manifest OK.
  Publicado em duas fases (`nuclear.zip.new` + `version.json.new` → sha conferido no servidor →
  **os dois `mv` no mesmo comando**, para nunca existir instante com manifesto e zip descasados);
  sha256 do zip live == manifesto live == resposta pública ==
  `86a0413710e257405f4d4553e3c6f9a328a4292db61eee3ec5d53c00922346ac`, e o `content-length` público
  confere. Backup da 1.7.3/b16: `nuclear.zip.bak-pre-1.7.4`. `ping.php`/`instalarNuclear.sh` não
  tocados.

- **Nuclear 1.7.3 (Beta) — `NUCLEAR_BUILD = 16` — PUBLICADO (2026-07-28), superado pela 1.7.4.** PATCH que fecha a
  lacuna estrutural exposta pela 1.7.2: **o updater que aplica uma release é o da versão
  ANTERIOR**, então toda mudança em como o `.desktop` é escrito chega uma release atrasada. Na
  prática: a b15 trocou o template do lançador para `2D_Animation`, mas quem aplicou a b15 foi o
  updater da b14, que reescreveu o `Exec` com `--app-template Nuclear` — as máquinas continuaram
  abrindo no template `Nuclear` (UI enxuta: o template substitui `VIEW3D_HT_tool_header.draw`
  pelo dele e os controles de pincel somem, o que o usuário leu como "informações faltando").
  Conserto: `nuclear_update.py` ganha `_reconcile_desktop()`, agendado no `register()` (timer de
  1 s, pulado em background mode), que roda o mesmo `_refresh_desktop` **no startup** — o build
  que está rodando conserta o próprio lançador na primeira abertura, sem depender de outro
  update. O `_refresh_desktop` virou **idempotente** (só grava quando a linha muda), então o
  estado estável é duas leituras e nenhuma escrita. Testado isolado em HOME falso, 3 casos:
  lançador com template antigo é corrigido, segunda passada não reescreve (mtime igual),
  `.desktop` de outro app não é tocado. Compilado em `build_nuclear_2d` (preset 2D, ninja -j2),
  smoke 2D ALL PASS, staging podado 1174 MB → 865 MB, zip **340 MB** (357.029.468 bytes),
  verify-zip + check-manifest OK. Publicado em duas fases; zip live == manifesto live ==
  resposta pública == `e09ca80fcb0ac8807a4b113144ae62b3d9d8f33ef6609211b7aea1a9d846287d`.
  Backup da 1.7.2/b15: `nuclear.zip.bak-pre-1.7.3`. `ping.php`/`instalarNuclear.sh` não tocados.

- **Nuclear 1.7.2 (Beta) — `NUCLEAR_BUILD = 15` — PUBLICADO (2026-07-28), superado pela 1.7.3.** PATCH a partir da
  branch `Nuclear` (commit `e70b800de51`). **A causa PRINCIPAL da perda de preferências, que a
  b14 não pegou.** O usuário reabriu a queixa "fecho e abro e perdi tudo" depois da 1.7.1: o
  guard de mtime da b14 só cobria duas instâncias brigando pelo arquivo, que era a metade menor.
  O verdadeiro culpado é o **app template**: o lançador abre com `--app-template`, e
  `wm_homefile_read_ex` carrega as preferências *do template*; como nenhum dos três templates do
  Nuclear tem `userpref.blend` próprio, o upstream cai em `BKE_blendfile_userdef_from_defaults()`
  e passa isso a `BKE_blender_userdef_app_template_data_set`, que faz **`VALUE_SWAP` de `addons`,
  `user_keymaps`, `user_keyconfig_prefs`, `themes`, `uistyles`, `uifonts` e `keyconfigstr`**. Ou
  seja: **toda abertura pelo lançador trocava addons/atalhos/tema pelos de fábrica**, e o save
  automático da saída (`U.runtime.is_dirty`) tornava permanente. Conserto: removido o fallback
  para defaults quando o template não traz preferências próprias (`wm_files.cc`) — sem prefs
  próprias, o template não tem o que restaurar. Reproduzido antes/depois (addon + item de keymap
  sobrevivem com template, na troca de template e sem template; keyconfig segue "Nuclear").
  **Segunda mudança, a pedido do usuário: o lançador passa a iniciar no template
  `2D_Animation`**, não no `Nuclear` — trocado nos quatro lugares que escrevem o `.desktop`
  (`release/freedesktop/Nuclear.desktop`, `instalarNuclear.sh`, `instalarNuclear-wizard.sh` e
  `nuclear_update.py`, este com a constante nova `_APP_TEMPLATE`). ⚠️ Consequência aceita: o
  `__init__.py` do template `Nuclear` não roda mais, então a UI customizada (topbar próprio, abas
  Properties/Reference/Library/Color/Peg Graph) sai de cena; o template segue no pacote e volta
  trocando a constante. Como o `_refresh_desktop` reescreve o `Exec` a cada apply, as máquinas
  pegam a troca no update que PARTIR da b15. Compilado em `build_nuclear_2d` (container
  `blender`, preset `nuclear_2d.cmake`, ninja -j2); o `bin/` **já tinha** o `scipy` desta vez.
  Smoke 2D ALL PASS. Staging podado (1174 MB → 865 MB), zip de **340 MB** (357.021.973 bytes).
  verify-zip + check-manifest OK. Publicado em duas fases (`nuclear.zip.new` → sha conferido no
  servidor → `mv`); sha256 do zip live == manifesto live == resposta pública ==
  `d3d34575f9247a97b131fdd4d9ebfd1ca099e83b558012a601a4127dae9e9bc6`. Backup da 1.7.1/b14 no
  servidor: `nuclear.zip.bak-pre-1.7.2`. ⚠️ Os `nuclear.zip.bak*` seguem crescendo com o disco a
  **89%** — a poda continua pendente de autorização. `ping.php`/`instalarNuclear.sh` não tocados.

- **Nuclear 1.7.1 (Beta) — `NUCLEAR_BUILD = 14` — PUBLICADO (2026-07-27), superado pela 1.7.2.** PATCH a partir da
  branch `Nuclear`: quatro correções, três delas de **perda de dados/trabalho**, todas achadas
  investigando a estação de animação `bazzite-2` (192.168.0.29) e o take
  `DPE_EP06_C12T67` (Carolina). **(1) As pegs do rig não desaparecem mais no save**
  (`bec553b0122`): o `followpeg_id_looper` reportava o PegRig com `is_reference = false`, sem
  contar usuário — quatro objetos seguindo o rig e `users = 1`; quando o último usuário contado
  saía, o rig ia a zero e era descartado no save com as 80 pegs dentro. Torna obsoleto o
  workaround `use_fake_user = True`. **(2) Preferências não são mais sobrescritas por uma janela
  antiga** (`09b76ec32f3`): as prefs são gravadas inteiras a partir do estado em memória, então
  uma instância aberta há horas desfazia addons/atalhos configurados noutra ao fechar. Agora o
  mtime do `userpref.blend` é rastreado e o save **automático** (saída) pula quando o disco está
  mais novo; "Save Preferences" explícito segue forçando. **(3) Fim do crash no Outliner**
  (`5650284a200`): `tree_element_id_type_to_index()` repassava o `-1` de
  `BKE_idtype_idcode_to_index()` e o chamador indexava `MergedIconRow[-1]`, corrompendo o array
  vizinho → deref de nulo em `outliner_draw_iconrow_doit` (SIGSEGV real, coredump na .29 após
  1h23 de trabalho). Junto: `NO_KEY_NEEDED` do auto-key deixou de virar WARNING "Could not insert
  key" (inundava o log e parecia keyframe perdido) e o `bezt[-1]` do `insert_vert_fcurve`.
  **(4) Pacote 221 MB menor**: a b13 foi empacotada à mão e pulou a poda; agora o `verify-zip`
  **reprova** pacote com peso morto (`e19bb623119`), e o zip voltou a **340 MB** (357.337.194
  bytes) contra os 578 MB da b13. Também: o updater passou a **criar** o `Nuclear.desktop` quando
  não existe (máquinas que nunca receberam o rebrand manual do lançador seguiam abrindo pelo shim
  `blender`, com "blender" no menu/journal) — como toda melhoria do apply, só age a partir do
  build que a contém, então vale do update que PARTIR da b14.
  ⚠️ **Pegadinha achada neste release:** o `bin/` do `build_nuclear_2d` **não tem as deps Python**
  (`scipy` etc.) — o `ninja install` não as instala, elas foram postas por fora um dia. O
  `verify-zip` pegou (regra de ouro nº4) e o `scipy` (+ `scipy.libs` + dist-info, 142 MB) foi
  copiado do pacote publicado para o `bin/` e para o staging; agora o `bin/` os tem, mas
  **confira sempre**. Nota: `pyclipper`/`triangle`/`skimage` já não existiam nem no pacote da b13
  — o status quo é só `scipy`, não foi alterado aqui.
  Compilado em `build_nuclear_2d` (container `blender`, preset `nuclear_2d.cmake`, ninja -j2).
  Smoke 2D ALL PASS; os quatro fixes revalidados no binário de release; take real aberto na GUI
  com o Outliner exercitado. verify-zip + check-manifest OK. Publicado com upload em duas fases
  (`nuclear.zip.new` → sha conferido no servidor → `mv`), sha256 do zip live == manifesto live ==
  resposta pública == `1481548d02db95a9e7520438033febdd0afc0dc06a27c91217814217355cbdaa`.
  Backup da 1.7.0/b13 no servidor: `nuclear.zip.bak-pre-1.7.1`. ⚠️ Os backups `nuclear.zip.bak*`
  já somam **9,5 GB** com o disco do servidor a **89%** — vale podar os antigos.
  `ping.php`/`instalarNuclear.sh` não tocados.

- **Nuclear 1.7.0 (Beta) — `NUCLEAR_BUILD = 13` — PUBLICADO (2026-07-27).** MINOR a partir
  da branch `Nuclear`. **Destaque 1 — grade de thumbnails na tela de abertura:** a splash
  screen agora mostra os projetos recentes como uma grade de miniaturas (Krita-style), com a
  imagem embedded no `.blend`/`.nuc` — o artista reconhece o take pelo desenho, não pelo nome
  de arquivo. O thumbnail é lido do cache do sistema (THB_LARGE) ou do header do próprio
  arquivo, letterboxed pra quadrado, com cache LRU de 100 entradas validado por mtime. Quatro
  arquivos tocados: `wm.py` (grid layout 8×4), `UI_interface_c.hh` (parâmetro `columns`),
  `interface_template_recent_files.cc` (+~230 linhas, leitura+cache+render), `rna_ui_api.cc`
  (exposição Python). **Destaque 2 — Entremeio com auto-detecção de faixa:** o addon de
  in-betweening agora detecta automaticamente onde começa e termina a animação real (ignora
  frames negativos/biblioteca de poses e Cell Library ≥100000). Painel ganhou campos
  Início/Fim + botão "Auto-detectar" + hint visual. Ver `rig_bridge.detect_animation_range()`.
  **Limpeza de dirs legados** (pendente desde b12) pega carona neste release: o updater que
  APLICA a b13 é o da versão que está rodando, então máquinas em ≤b12 só ganham a limpeza
  de `.cache/blender`/`.config/blender` no update que PARTIR de b13. Compilado nesta máquina
  em `build_nuclear_2d` (container `blender`, preset `nuclear_2d.cmake`, ninja 3 jobs, ccache
  quente ~1min). Smoke 2D ALL PASS. Empacotado com deps Python (scipy 2615 arquivos).
  verify-zip + check-manifest OK. Publicado: sha256 do zip live no servidor == manifesto ==
  `760cf54b0384ff4e85613dd05580e5ff8bad141dcc87ed4115100f0cdaf884dd` (578.335.394 bytes).
  Backup da 1.6.0/b12 no servidor: `nuclear.zip.bak-pre-1.7.0`.
  `ping.php`/`instalarNuclear.sh` não tocados.

- **PENDENTE (commitado, NÃO publicado) — auto-limpeza dos dirs legados `blender` no
  updater (2026-07-08).** `nuclear_update.py`: `_cleanup_legacy_dirs()` roda no apply logo
  após `_migrate_legacy_config`, (1) **apaga** `~/.cache/blender` (regenerável; o build novo
  já usa `~/.cache/Nuclear`) e (2) **renomeia** `~/.config/blender` → `.pre-nuclear.bak`
  (nunca apaga config — reversível; guardado p/ não clobberar backup nem tocar no dir
  Nuclear vivo; só age se `.config/Nuclear` já existe, p/ não órfãr settings não-migrados).
  Testado isolado em HOME falso (3 cenários: pós-migração, idempotente 2x, Nuclear-ausente).
  Novo helper `_cache_roots()` espelha `caches_root` do `appdir.cc`. ⚠️ **Como toda melhoria
  do apply, só age a partir do build que a contém:** máquinas em ≤b12 só ganham a limpeza no
  update que PARTIR de b13+ (o updater que aplica é o da versão que está rodando). **Agora
  PUBLICADO como parte da 1.7.0/b13.**

- **Nuclear 1.6.0 (Beta) — `NUCLEAR_BUILD = 12` — PUBLICADO (2026-07-08).** Empacota o
  **rebrand completo** (rename `blender`→`nuclear` do executável e de TODOS os artefatos:
  auxiliares, `Nuclear.desktop`, ícones `nuclear*.svg`, man `nuclear.1`, keyconfig
  "Nuclear" com migração de prefs, metainfo/readme, strings de `--help`/splash/Help, temas
  `Nuclear_Dark/Light`) **mais o Auto Rig da 1.5.1** (a branch puxou aqueles commits, então
  1.6.0 é superset). **Shim de compat `blender`** no zip (regra de ouro nº5 — o updater das
  máquinas em build ≤11 procura um arquivo `blender`). **⚠️ Colisão de build resolvida:** o
  servidor tinha uma **1.5.1/b11** publicada por sessão PARALELA (2026-07-08 18:07, auto-rig,
  390MB, sha `80cf187a…`, notes "auto rig: novas peças implementadas") que este doc não
  registrava; por isso o bump foi **MINOR → 1.6.0 / build 12** (não reusar o b11 já gasto —
  regra de ouro nº1). Backup da 1.5.1 no servidor: `nuclear.zip.bak-pre-1.6.0`.
  **Otimização:** pacote podado com `nuclear_prune_package.sh` (−310MB: 34 libs 3D mortas
  USD/OSL/OpenVDB/Embree/HIP-RT + 5 ferramentas de build) → zip de **340MB** (356.983.335
  bytes, sha256 `3c1a1d0e561c12c8f038aba35e0efc51ddc07b66b9b923574be2ad9eb73a71c5`).
  **Testado antes de publicar (bateria no pacote JÁ PODADO):** smoke 2D ALL PASS + GUI
  (janela/splash/Help desenham, zero "Blender") + render GP pesado (28.800 pts × 6 frames,
  ~0,19s/frame estável) + shim + keyconfig/migração. **Pegadinha achada e corrigida:** o
  `ninja install` deixou presets órfãos do rename (`Blender.py`/`Blender_27x.py`,
  `Blender_Dark/Light.xml`) que iriam duplicados pro zip — removidos do build antes de
  empacotar (ver [[nuclear-bin-stale-files-ship-in-release]]; renomear preset exige limpar
  os antigos do `bin/`). Compilado em `build_nuclear_2d` (container `blender`), verify-zip +
  check-manifest OK. `ping.php`/`instalarNuclear.sh` não tocados.

- **Refresh do zip 1.5.0/b10 — fix cosmético do banner do updater (2026-07-06, mesmo
  dia).** Bug: `_draw_statusbar` montava `"Nuclear %s disponível" % _latest_label()`, mas
  `_latest_label()` já retorna o `version_string` completo (que já começa com "Nuclear") →
  renderizava "Nuclear Nuclear 1.5.0 (Beta) disponível" na status bar. Fix em
  `scripts/startup/nuclear_update.py` (commit `9c2e3217f62`, branch `Nuclear`): removido o
  prefixo redundante, agora só `"%s disponível" % _latest_label()`. **NÃO bumpou** `NUCLEAR_BUILD`
  (fix cosmético, não vale forçar re-download de quem já está no b10) — segue **1.5.0 / build
  10**. Re-injeção cirúrgica de 1 arquivo no zip já publicado, sem rebuild: backup do zip anterior
  como `nuclear.zip.bak-pre-1.5.0-updaterfix` no servidor, removido o `.pyc` obsoleto do
  `__pycache__` do zip (`zip -d`, pra não deixar bytecode velho ao lado da fonte corrigida) e
  injetado o `nuclear_update.py` corrigido via `zip -g` no caminho interno
  `Nuclear/5.0/scripts/startup/nuclear_update.py`. `verify-zip` OK (updater + scipy). Manifesto
  regerado com **mesmo build/version/notes**, só `sha256`/`size` mudaram: novo sha256
  `22c5eb30e4d35058f6cb6977972db781caa373a14abaec71017b2f3aee65cf25`, 646.600.712 bytes (era
  `8494b0a702652dd179faac27c90c51e3d3dbad63c1a3fc314374252c111335f1`, 646.626.577 bytes).
  Conferido: sha256/size do zip live no servidor == manifesto live == resposta pública de
  `https://rapaduraatomica.com.br/estacao/version.json` e `content-length` do
  `estacao/nuclear.zip`. `ping.php` / `instalarNuclear.sh` não tocados.

- **Nuclear 1.5.0 (Beta) — `NUCLEAR_BUILD = 10` — PUBLICADO (2026-07-06).** Minor a partir da
  branch `Nuclear` (bump/build já feitos e testados no commit `8bbcfde3b5b`, este agente só
  empacotou/publicou). **Destaque 1 — kit de pintura Grease Pencil:** nova aba "Paint" no
  Properties (`scripts/startup/nuclear_paint_toolkit.py`) com color picker estilo Krita (roda de
  matiz + triângulo saturação/valor), pincéis Smudge e Blur/Dissolve, Lasso Fill, balde e cores
  recentes. **Destaque 2 — rebrand da pasta de config:** `.config/blender` → `.config/Nuclear`
  (idem cache), com **migração automática** dos settings existentes embutida no updater
  (`nuclear_update.py::_migrate_legacy_config`, roda no apply) e no instalador — ninguém perde
  tema/keymaps/addons no auto-update. Compilado **nesta máquina** em
  `~/Documentos/GitHub/build_nuclear_full` (container distrobox `blender`, `ninja install` exit
  0, binário 236 MB, `--version` confirma "Nuclear 1.5.0 (Beta)"). Empacotado/verificado por este
  fluxo: `cp -al bin Nuclear` (staging leftover da 1.4.4 removido antes) → sem relíquias
  `versions`/`current` no `bin` (nada a limpar desta vez) → `stamp` → `zip -r` → `verify-zip`
  (updater + 2615 arquivos `site-packages/scipy`) OK → `manifest` → `check-manifest` OK. Backup do
  zip 1.4.4/b9 no servidor: `nuclear.zip.bak-pre-1.5.0` (sha256 conferido == `630cab0f11…` antes
  do overwrite). Publish confirmado: sha256 do zip live no servidor == manifesto live ==
  `8494b0a702652dd179faac27c90c51e3d3dbad63c1a3fc314374252c111335f1` (646.626.577 bytes).
  `ping.php` / `instalarNuclear.sh` não tocados.

- **Nuclear 1.4.4 (Beta) — `NUCLEAR_BUILD = 9` — PUBLICADO (2026-07-01), superado pela 1.5.0.** Patch a partir da branch
  `Nuclear`. Delta 100% Python sobre a 1.4.3/b8: **relatório automático de falha** (cliente de startup
  `scripts/startup/nuclear_crash_report.py`, dead-man's switch, POST HTTPS pro `crash.php` reusando o
  token público de ping — sem segredo novo no build), **addon SVG ↔ Grease Pencil**
  (`scripts/addons_core/svg_to_gp/`, importa/exporta traços) e **fix da Cell Library** (trata cada
  objeto como parte distinta na biblioteca cross-file). Compilado **nesta máquina** (checkout
  `Nuclear-git/Nuclear`, dir `Nuclear/build`) — ⚠️ o container `blender` estava corrompido (falha de
  `devpts` no init, exit 32) e foi removido; o toolchain foi **reconstruído num container `blenderdev`
  fresco** (`gcc 16.1.1`, `cmake 4.3.0`, `ninja-build 1.13.2` via dnf), build incremental de 761 passos
  com gcc 16 sem erros. Empacotado/verificado via fluxo manual (`stamp` + `zip`, staging sem
  `versions`/`current`). verify-zip (updater + scipy) + check-manifest OK; publish confirmado no
  servidor (sha256 do zip live == manifesto). Backup do zip 1.4.3/b8 no servidor:
  `nuclear.zip.bak-pre-1.4.4`. **Server-side pendente (NÃO vai no zip, deploy manual bloqueado):**
  deploy do `crash.php`/`admin.php` + rotação da senha de admin vazada. `ping.php` /
  `instalarNuclear.sh` não tocados.

- **Nuclear 1.4.3 (Beta) — `NUCLEAR_BUILD = 8` — PUBLICADO (2026-06-29), superado pela 1.4.4.** Patch a partir da branch
  `integration/1.4.3-audit`. Unifica a auditoria de crash/freeze + reset operators na mainline 1.4.x
  e leva **duas rodadas de auditoria de performance** (PegRig avaliado O(1) via nó de depsgraph
  `PEGRIG_SOLVE`; freeze após ~1000 frames; throttle/defer de handlers). **Destaque desta release —
  squash & stretch corrigido:** o squash agora deforma a partir do **pivot da peg** (mesmo ponto fixo
  da rotação/escala), axis-aligned ao X/Z local, com a compensação de área (X) **desligada por
  padrão** (`squash_volume = 0`) — fim do "desliza na diagonal/em X" da peça posada. Também: **gizmo
  de pontos no viewport pro envelope/Contour** (`nuclear_contour_gizmo.py`, espelha o do Curve:
  dot por controller, click/shift-click/drag, Reset Selected honra) e **operadores de Reset**
  (envelope/contour/curve). Compilado nesta máquina em `build_nuclear_full` (container `blender`,
  `ninja -j2`), empacotado/verificado/publicado via fluxo manual (`--no-bump`, staging sem
  `bin/versions`+`current`). verify-zip + check-manifest OK. Backup do zip 1.4.2/b7 no servidor:
  `nuclear.zip.bak-pre-1.4.3`. `ping.php` / `instalarNuclear.sh` não tocados.

- **Nuclear 1.4.2 (Beta) — `NUCLEAR_BUILD = 7` — PUBLICADO (2026-06-26), superado pela 1.4.3.** Nova minor a partir da
  branch `Nuclear` (HEAD `7a4381e`). **Destaque — Auto-Rig** (novo addon de startup
  `scripts/startup/nuclear_rig_auto.py`): monta um PegRig completo a partir das peças GP
  desenhadas — **Auto-Build Skeleton** (casa tronco/espinha/membros por nome, sufixo de lado
  `.e`/`.d`, pivôs de junta sempre geométricos), **Link Selected to Active** (liga face/acessórios
  em lote ao pai ativo), padrão de **duas pegs** por peça (junta estrutural + peg de desenho
  `(ctrl)`), e **Peg Graph agrupado** por região com botão **Auto Layout**. 100% Python sobre a API
  de PegRig (sem C), validado headless vs rig de referência; convenção de nomes em
  `RigAutoFeature.md`. Também na release: **formato `.nuc`** como extensão padrão de arquivos novos
  (Fase 1 — `.blend` legado segue 100% abrível, byte-idêntico; mexe em `blendfile.cc`/`wm_files.cc`
  + MIME `application/x-nuclear`, daí o rebuild) e **persistência do layout do Peg Graph**
  (ID-property JSON no rig, sobrevive a Sync/frames e ao export). Compilado nesta máquina em
  `Nuclear/build` (container `blender`, `ninja && ninja install`), empacotado/verificado/publicado
  via `nuclear_release.sh --no-bump`. verify-zip + check-manifest OK. Versão cosmética setada direto
  em **1.4.2** (pula 1.4.0/1.4.1, a pedido); `NUCLEAR_BUILD` 6→7. Backup do zip 1.3.2/b6 no
  servidor: `nuclear.zip.bak-pre-1.4.2`. **Server-side (separado, NÃO vai no zip):** telemetria com
  apelido/região por máquina + painel admin (`app.py`/`ping.php`/templates) — `ping.php` segue
  deploy manual.

- **Nuclear 1.3.2 (Beta) — `NUCLEAR_BUILD = 6` — PUBLICADO (2026-06-23), superado pela 1.4.2.**
  Release de robustez do auto-updater: injeção do script corrigido (commit `d63ac650`) no zip do
  build 5, sem recompilação. Fixes incluídos: log em disco (`nuclear_update.log`), checagem de
  espaço livre antes do download (`_check_free_space`), traceback capturado em caso de falha no
  apply. Bump: PATCH 1.3.1→1.3.2, `NUCLEAR_BUILD` 5→6. verify-zip OK (updater + scipy presentes),
  check-manifest OK. **Foi deployado** (estava live no servidor até 2026-06-26, quando a 1.4.2 o
  substituiu). `ping.php` / `instalarNuclear.sh` não tocados.

- **Nuclear 1.3.1 (Beta) — `NUCLEAR_BUILD = 5` — PUBLICADO (2026-06-23).** Release a partir da
  branch `Nuclear` (HEAD `ee2a8c7`). Empacota a junção Auto-Patch + Envelope **mais** o Contour
  evoluído (stroke de layer como cage; modo **Guide Line**/MLS; **Spine Controllers** = rig Bézier
  ao longo da linha com handles em Object Mode; cage nasce escondida + toggle **Show/Hide
  Controllers**), Cell Library / Drawing Substitution, nova Timeline, melhorias nos Pegs e a
  identidade visual Nuclear. Compilado **nesta máquina** em `Nuclear/build` via container distrobox
  **`blender`** (`ninja && ninja install`), e empacotado/verificado/publicado por
  `tools/nuclear_release.sh --no-bump --build-dir Nuclear/build`. verify-zip + check-manifest OK.
  **⚠️ Achado:** o servidor já tinha uma **1.3.0 / build 4** live (de 2026-06-19, conteúdo anterior
  ao merge, notes "Squashs e Cutter", sha256 `e7a211c5…`) que este doc **não registrava**. Por isso
  o bump foi **PATCH → 1.3.1 / build 5** (não reusar o build 4 já gasto — regra de ouro nº1; senão
  máquinas na b4 de 19/jun não enxergariam o update). Backup do zip 1.3.0/b4 no servidor:
  `nuclear.zip.bak-pre-1.3.0`. `ping.php` / `instalarNuclear.sh` seguem manuais (não tocados).

- **Junção Auto-Patch + Envelope na mainline `Nuclear` (2026-06-23) — INCLUÍDO NO BUILD 6.**
  As duas features GP refinadas (Auto-Patch engine-based de `feat/gp-masks` + Envelope/Contour
  modifier de `integration/gp-contour-1.1`) foram juntadas na branch `integration/autopatch-envelope`
  (criada a partir de `Nuclear`) por merge sequencial B→A, e o resultado trazido para a branch
  **`Nuclear`**. Coexistem agora 3 sistemas: **Cutter** (`MOD_grease_pencil_mask.cc`, eType 88),
  **Auto-Patch** (engine) e **Contour/Envelope** (`MOD_grease_pencil_contour.cc`, **eType 88→89**
  — realocado para não colidir com o Cutter). Botão do Auto-Patch renomeado p/ "Auto-Patch" (sem
  "Toon Boom"). Build limpo (ninja RC 0) + smoke test headless: os 3 registram. (Já estava no zip
  b5; o build 6 herda esse conteúdo via repackage sem rebuild.) Ver ADR
  `docs/decisions/2026-06-23-merge-autopatch-envelope-nuclear.md`.

- **Consolidação 1.0 → 1.1 + modifier Contour/masks GP (2026-06-16) — BUMP LOCAL, NÃO
  PUBLICADO.** O trabalho GP novo (modifier `GreasePencilContour` eType 88 — deformer
  envelope MVC estilo Toon Boom — + masks nativas de GP) vivia só na linha 1.0
  (`feat/native-auto-patch`, working tree). Foi commitado lá (`90ac371`) e portado para a
  linha 1.1 via cherry-pick limpo na branch **`integration/gp-contour-1.1`** (base
  `origin/auto/integration`). Build validado no `blenderdev` (`ninja install` ok; modifier
  registra e instancia em GP). Header bumpado para **1.2.0 / `NUCLEAR_BUILD = 3`** (MINOR,
  recurso novo). **Pendente (externo/manual):** empacotar o `nuclear.zip` novo, regerar o
  `version.json` (regra de ouro nº2), atualizar o espelho do manifesto, fast-forward de
  `origin/auto/integration` + push, e deploy. O espelho `version.json` segue apontando o
  zip publicado da b2 (build 2) até existir zip novo.

- **Envelope Bézier (modifier Contour evoluído) — operador nativo + Bind + controles em
  Object Mode (2026-06-22) — NÃO PUBLICADO.** Na `integration/gp-contour-1.1`: cage = curva
  Bézier (não só mesh) `25e74b1`; operador `OBJECT_OT_greasepencil_envelope_setup` (traça a
  silhueta convex-hull → Bézier cíclica → bind) + `OBJECT_OT_greasepencil_contour_bind`
  `0f19a1d`; controles empty+hook em Object Mode `cba41e7`; handles de Bézier completos
  (âncora + 2 tangentes) `125c961`; Collection/in-front/locks/6-pts `93385c3`; visual estilo
  Bézier nativa (cor via `ob->color`, tamanho, bevel) `7c2cdb3`. **Todas as seams (do modifier
  Contour original + envelope + overlay) JÁ registradas no `NUCLEAR_DIVERGENCE.md`.**

- **Conserto flat + fallback home + permissão de execução (2026-06-12) — PUBLICADO.**
  `scripts/startup/nuclear_update.py`: (a) flat install se auto-atualiza no lugar; (b)
  fallback abre a HOME do repo; (c) `_extract_zip`/`_ensure_executable` preservam o bit `+x`
  na extração — antes o `zipfile.extractall` zerava o modo e o binário saía sem `+x` (não
  abria). Re-injetado no zip publicado via `zip -g` e manifesto regerado a cada etapa.
  Backups no servidor: `nuclear.zip.bak-pre-flatfix`, `nuclear.zip.bak-pre-permfix`.

- **Versão em produção:** Nuclear 1.7.6 (Beta) — `NUCLEAR_BUILD = 19` (2026-08-06, deploy
  confirmado: sha256 do zip no servidor confere com o manifesto live e com a resposta pública, e
  o `content-length` público bate). Máquinas em qualquer build ≤ 18 enxergam como update.
  Histórico: 1.1.0/b2 (2026-06-11) → 1.3.0/b4 (2026-06-19, não
  registrado à época) → 1.3.1/b5 (2026-06-23) → 1.3.2/b6 (2026-06-23) → 1.4.2/b7 (2026-06-26) →
  1.4.3/b8 (2026-06-29) → 1.4.4/b9 (2026-07-01) → 1.6.0/b12 (2026-07-08) → 1.7.0/b13 (2026-07-27) →
  1.7.1/b14 (2026-07-27) → 1.7.2/b15 (2026-07-28) → 1.7.3/b16 (2026-07-28) →
  1.7.4/b17 (2026-07-31) → 1.7.5/b18 (2026-08-05) → **1.7.6/b19 (2026-08-06)**.
- **nuclear.zip (b19, em produção):** 357.290.441 bytes, sha256
  `8b7a5d8d0b8579d02e99da1da0f86009695b7525f9a25bfe7bdb544cbb8952e9` (2026-08-06). Auto-contido
  por construção (updater + deps Python do fork no `bin`); verify-zip + check-manifest OK antes de
  cada publish. **Backups no servidor: só os 2 mais recentes** — `nuclear.zip.bak-pre-1.7.6` (zip
  1.7.5/b18) e `nuclear.zip.bak-pre-1.7.5` (zip 1.7.4/b17). `nuclear.zip.bak-pre-1.7.4` foi podado
  neste release para manter a política de guardar dois, que mantém rollback de duas versões.
  Apagar o `.bak` mais antigo faz parte da rotina de publish — não deixe voltar a acumular.
- **Build dir:** `~/Documentos/GitHub/build_nuclear_2d` nesta máquina (out-of-source, preset
  `nuclear_2d.cmake`; container distrobox **`blender`** — ou `blenderdev` com toolchain
  reconstruído via dnf se o `blender` corromper, ver entrada 1.4.4/b9). `nice ninja -j2` (o
  `nuclear_release.sh` usa `-j3`; com GUIs do usuário abertas confira `free -m` antes e prefira
  `-j2`, para um OOM não matar as janelas dele). ⚠️ **O default de `--build-dir` do
  `nuclear_release.sh` está errado** — ele resolve para `~/Documentos/build_nuclear_2d` (dois
  `dirname` a partir do repo), então **passe `--build-dir` sempre**. Empacotamento manual, se for
  fazer à mão: `cp -al bin Nuclear` → **rm `Nuclear/versions`+`Nuclear/current`** (relíquias de
  auto-update ~5GB) → stamp → `zip -r` (deps já no `bin`). O `nuclear_release.sh` **já faz** essa
  poda sozinho desde a b14 (`rm -rf "$STAGE_DIR/versions" "$STAGE_DIR/current"`, mais o
  `nuclear_prune_package.sh`) — a nota antiga que dizia o contrário estava desatualizada.
- ⚠️ **Pushe os commits ANTES de buildar o release.** O `buildinfo.cmake` do upstream carimba o
  binário com `git rev-parse @{u}` (o upstream tracking branch), **não** com o HEAD local: com
  commits só locais, o `build hash` do splash e do relatório de crash aponta para a release
  anterior. Fluxo certo: commit de release → `git push` → `ninja install` (regenera o buildinfo e
  re-linka, ~6 passos) → empacotar. Custou um re-empacotamento na 1.7.4.
- **Publique em duas fases:** suba `nuclear.zip.new` **e** `version.json.new`, confira o sha256 do
  zip no servidor, e só então faça **os dois `mv` no mesmo comando `ssh`** — assim nunca existe um
  instante com manifesto e zip descasados (subir o manifesto antes faria o updater baixar o zip
  velho e falhar no checksum; subir só o zip faria o inverso).
- **Instalador versionado:** publicado em `instalarNuclear-versionado.sh` (o `.sh` antigo
  segue sendo o flat).
- **Telas:** diálogos fixos (`invoke_props_dialog`); primeira checagem 3 s após abrir;
  re-checagem a cada 6 h enquanto aberto.
- **Pendente de aprovação manual (deploy de código):** trocar o `instalarNuclear.sh`
  canônico pelo versionado; deploy do `ping.php` com eco do manifesto (opcional).
