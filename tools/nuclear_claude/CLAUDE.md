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
   distrobox `blenderdev` (o blocker de ownership do `build/` foi resolvido em 2026-06-08):
   ```sh
   distrobox enter blenderdev -- bash -lc 'cd <repo>/Nuclear/build && ninja && ninja install'
   ```
   (`ninja install` sincroniza os scripts Python/UI no `bin/5.0`). É demorado (~20min
   incremental sem ccache, mais para um full) e pode haver build concorrente em outro
   processo, então **confirme antes de disparar**. Rodar externamente continua sendo opção.
3. **Carimbar** o build: `python tools/nuclear_release.py stamp <pasta-do-build>`
   → grava `nuclear_version.json` ao lado do binário.
4. **Empacotar** o zip portátil (topo `Nuclear/<ver>/…`).
5. **Gerar o manifesto** do zip empacotado:
   ```sh
   python tools/nuclear_release.py manifest --zip <nuclear.zip> \
     --notes "o que mudou" -o version.json
   ```
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

Atualizado em 2026-07-06.

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

- **Versão em produção:** Nuclear 1.5.0 (Beta) — `NUCLEAR_BUILD = 10` (2026-07-06, deploy
  confirmado: sha256 do zip no servidor confere com o manifesto live). Máquinas em qualquer
  build ≤ 9 enxergam como update. Histórico: 1.1.0/b2 (2026-06-11) → 1.3.0/b4 (2026-06-19, não
  registrado à época) → 1.3.1/b5 (2026-06-23) → 1.3.2/b6 (2026-06-23) → 1.4.2/b7 (2026-06-26) →
  1.4.3/b8 (2026-06-29) → 1.4.4/b9 (2026-07-01) → **1.5.0/b10 (2026-07-06)**.
- **nuclear.zip (b10, em produção):** 646.600.712 bytes, sha256
  `22c5eb30e4d35058f6cb6977972db781caa373a14abaec71017b2f3aee65cf25` — **refresh do banner do
  updater (2026-07-06), mesmo build/version**; o zip inicial da 1.5.0 (646.626.577 bytes, sha256
  `8494b0a702652dd179faac27c90c51e3d3dbad63c1a3fc314374252c111335f1`) foi substituído sem bump.
  Auto-contido por construção (updater + deps Python do fork no `bin`); verify-zip + check-manifest
  OK antes de cada publish. Backups no servidor: `nuclear.zip.bak-pre-1.5.0-updaterfix` (zip
  1.5.0/b10 inicial), `nuclear.zip.bak-pre-1.5.0` (zip 1.4.4/b9 anterior),
  `nuclear.zip.bak-pre-1.4.4` (zip 1.4.3/b8), `nuclear.zip.bak-pre-1.4.3` (zip 1.4.2/b7),
  `nuclear.zip.bak-pre-1.4.2` (zip 1.3.2/b6), `nuclear.zip.bak-pre-1.3.0` (zip 1.3.0/b4).
- **Build dir:** `Nuclear/build` nesta máquina (checkout `Nuclear-git/Nuclear`), ou
  `~/Documentos/GitHub/build_nuclear_full` na máquina primária (out-of-source; container distrobox
  **`blender`** — ou `blenderdev` com toolchain reconstruído via dnf se o `blender` corromper,
  ver entrada 1.4.4/b9). `ninja -j2 nice`. Empacotamento manual: `cp -al bin Nuclear` → **rm
  `Nuclear/versions`+`Nuclear/current`** (relíquias de auto-update ~5GB) → stamp → `zip -r`
  (deps já no `bin`). ⚠️ O `nuclear_release.sh` não exclui `versions/current` sozinho.
- **Instalador versionado:** publicado em `instalarNuclear-versionado.sh` (o `.sh` antigo
  segue sendo o flat).
- **Telas:** diálogos fixos (`invoke_props_dialog`); primeira checagem 3 s após abrir;
  re-checagem a cada 6 h enquanto aberto.
- **Pendente de aprovação manual (deploy de código):** trocar o `instalarNuclear.sh`
  canônico pelo versionado; deploy do `ping.php` com eco do manifesto (opcional).
