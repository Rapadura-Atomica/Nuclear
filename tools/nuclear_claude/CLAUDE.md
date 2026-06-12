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

---

# Nuclear — sistema de atualização (documentação viva)

> **Este arquivo é a fonte da verdade do sistema de auto-update do Nuclear.**
> Sempre que QUALQUER peça mudar (versão, fluxo, caminho de servidor, formato do
> `version.json`, etc.), **atualize este documento na mesma leva**. O agente
> `nuclear-release` é obrigado a fazer isso ao final de cada release.

Última atualização: 2026-06-11.

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
   distrobox `blender` (o blocker de ownership do `build/` foi resolvido em 2026-06-08):
   ```sh
   distrobox enter blender -- bash -lc 'cd <repo>/Nuclear/build && ninja && ninja install'
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

**Pendência conhecida:** instalações "flat" antigas (binário solto em `~/Nuclear/blender`,
sem `current`) NÃO se auto-atualizam — caem no fallback de abrir a página. Precisam ser
reinstaladas com o instalador versionado. Ver `[[nuclear-auto-update]]` na memória do
projeto.

## 8. Troubleshooting

| Sintoma | Causa provável | Ação |
| --- | --- | --- |
| "checksum não confere" | zip trocado, manifesto com hash velho | regerar `version.json` (seção 5, atalho) |
| Nenhum aviso aparece | build instalado == build do manifesto, ou sem `nuclear_version.json` | conferir `NUCLEAR_BUILD`; testar com `NUCLEAR_UPDATE_BUILD=0` |
| "Invalid operator call" | (corrigido) operador modal chamado sem evento | já resolvido: dialogs via `invoke_props_dialog` |
| Clica e abre a página em vez de instalar | instalação flat (sem `current`) | reinstalar no layout versionado |
| Aviso some sozinho | (corrigido) era `popup_menu` | já resolvido: `invoke_props_dialog` |

## 9. Variáveis de ambiente do cliente (debug, sem rebuild)

| Var | Efeito |
| --- | --- |
| `NUCLEAR_UPDATE_URL` | troca a URL do manifesto |
| `NUCLEAR_UPDATE_OFF=1` | desliga a checagem |
| `NUCLEAR_UPDATE_BUILD=0` | finge que o build instalado é 0 (força o aviso) |

## 10. Estado atual

Atualizado em 2026-06-11.

- **Versão publicada:** Nuclear 1.1.0 (Beta) — `NUCLEAR_BUILD = 2`. **Primeiro build real
  do fluxo de release** (compilado em 2026-06-11 no `build_nuclear_full` via container
  distrobox `blenderdev`, `ninja && ninja install`). Máquinas em build 1 enxergam como
  update.
- **nuclear.zip:** 663.041.271 bytes, sha256
  `bef6a58e900f76ac9c8dba6bc8d82a937421fe3d168d88cf20d4782ea7198606`. **Auto-contido por
  construção** (não injetado): o build já trazia o updater (regra nº3); as deps Python do
  fork (regra nº4) foram adicionadas no empacotamento (`tar` do `site-packages` conhecido).
  Backup do build 1 anterior no servidor: `nuclear.zip.bak-b1-deps`.
- **Build dir:** `Documentos/GitHub/build_nuclear_full` (out-of-source, aponta pro repo).
  Empacotamento: `cp -al bin Nuclear` → stamp → injeta deps → `zip -r`.
- **Instalador versionado:** publicado em `instalarNuclear-versionado.sh` (o `.sh` antigo
  segue sendo o flat).
- **Telas:** diálogos fixos (`invoke_props_dialog`); primeira checagem 3 s após abrir;
  re-checagem a cada 6 h enquanto aberto.
- **Pendente de aprovação manual (deploy de código):** trocar o `instalarNuclear.sh`
  canônico pelo versionado; deploy do `ping.php` com eco do manifesto (opcional).
