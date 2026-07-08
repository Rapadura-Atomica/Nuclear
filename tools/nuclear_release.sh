#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Self-serve Nuclear release: chains the flow documented in
# tools/nuclear_claude/CLAUDE.md (sec. 5) and .claude/agents/nuclear-release.md so a
# programmer can run a release without going through the Claude agent.
#
#   tools/nuclear_release.sh patch --build --notes "correcao X"
#   tools/nuclear_release.sh minor --dry-run            # preview only, nothing runs
#   tools/nuclear_release.sh --no-bump --notes "..."     # version already bumped by hand
#
# What it does, in order: bump version -> optional rebuild (only with --build; configures
# with the nuclear_2d preset + ccache/mold) -> 2D smoke gate on the binary (always) ->
# package the portable zip (prunes dead 3D libs + build tools; --no-prune to skip) ->
# verify golden rules #3/#4 -> generate + check the manifest -> publish zip+manifest
# together to estacao/ (asks to confirm) -> reminds you to update CLAUDE.md -> offers
# to commit.
#
# Official releases build with build_files/cmake/config/nuclear_2d.cmake (2026-07-07
# decision, see docs/decisions/2026-07-07-modelo-comercial-hibrido.md): 3D subsystems
# compiled out (-21% binary), ccache + mold on. The smoke gate
# (tools/smoke_nuclear2d.py) aborts the release if the binary still carries 3D or lost
# a 2D-pipeline capability. Use --no-smoke only to package a deliberate full build.
#
# What it deliberately never touches: ping.php / instalarNuclear.sh (overwriting
# production CODE is out of scope here, same restriction as the Claude agent -- those
# deploys stay manual/approved separately).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RELEASE_PY="$SCRIPT_DIR/nuclear_release.py"
TELEMETRY_MIRROR="$REPO_ROOT/tools/nuclear_telemetry/server/version.json"

KIND=""
DO_BUMP=true
DO_BUILD=false
DO_SMOKE=true
DO_PRUNE=true
DRY_RUN=false
ASSUME_YES=false
BUILD_DIR="$(dirname "$(dirname "$REPO_ROOT")")/build_nuclear_2d"
CONTAINER="blender"
PRESET="$REPO_ROOT/build_files/cmake/config/nuclear_2d.cmake"
NOTES=""
REMOTE="araga286:~/public_html/addon/rapaduraatomica/estacao/"

usage() {
  sed -n '2,28p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    patch|minor|major) KIND="$1"; shift ;;
    --no-bump) DO_BUMP=false; shift ;;
    --build) DO_BUILD=true; shift ;;
    --no-smoke) DO_SMOKE=false; shift ;;
    --no-prune) DO_PRUNE=false; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    --yes|-y) ASSUME_YES=true; shift ;;
    --build-dir) BUILD_DIR="$2"; shift 2 ;;
    --container) CONTAINER="$2"; shift 2 ;;
    --notes) NOTES="$2"; shift 2 ;;
    --remote) REMOTE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "argumento desconhecido: $1" >&2; usage; exit 1 ;;
  esac
done

if $DO_BUMP && [[ -z "$KIND" ]]; then
  echo "erro: informe patch|minor|major, ou use --no-bump se a versao ja foi ajustada." >&2
  exit 1
fi

confirm() {
  local prompt="$1" reply=""
  if $ASSUME_YES; then return 0; fi
  read -r -p "$prompt [y/N] " reply || reply=""
  [[ "$reply" =~ ^[yY]([eE][sS])?$ ]]
}

run() {
  if $DRY_RUN; then
    printf '[dry-run]'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

version_json() { python3 "$RELEASE_PY" version; }
version_string() { version_json | python3 -c 'import json,sys; print(json.load(sys.stdin)["version_string"])'; }

echo "== Nuclear release =="
echo "repo:       $REPO_ROOT"
echo "build dir:  $BUILD_DIR"
$DRY_RUN && echo "modo:       DRY-RUN (nenhum comando real e executado)"
echo

BEFORE="$(version_string)"

# 1. Bump -----------------------------------------------------------------
if $DO_BUMP; then
  run python3 "$RELEASE_PY" bump "$KIND"
else
  echo "-- bump pulado (--no-bump)"
fi
AFTER="$(version_string)"
echo ">> versao: $BEFORE -> $AFTER"
echo

# 2. Rebuild (only with --build, never silently) ---------------------------
# Configures with the nuclear_2d preset (idempotent when the dir is already
# preset-configured; on a full-featured dir it correctly converts it to the 2D
# feature set). /usr/bin/cmake|ninja on purpose: the PATH cmake can be a broken
# pip shim (2026-07-07 gotcha).
if $DO_BUILD; then
  if confirm "Build via distrobox '$CONTAINER' agora (ccache quente ~1min; frio ~30min)?"; then
    run distrobox enter "$CONTAINER" -- env BUILD_DIR="$BUILD_DIR" REPO_ROOT="$REPO_ROOT" PRESET="$PRESET" bash -lc '
      /usr/bin/cmake -S "$REPO_ROOT" -B "$BUILD_DIR" -G Ninja -DCMAKE_BUILD_TYPE=Release -C "$PRESET" &&
      nice /usr/bin/ninja -C "$BUILD_DIR" -j3 && nice /usr/bin/ninja -C "$BUILD_DIR" install'
  else
    echo "build cancelado pelo usuario. Abortando -- nada foi publicado." >&2
    exit 1
  fi
else
  echo "-- rebuild pulado (use --build para compilar via distrobox antes de empacotar)"
fi
echo

# 2.5. 2D smoke gate (always, even without --build: gates whatever binary is
# about to be packaged; fails if 3D came back or a 2D capability was lost) ----
if $DO_SMOKE; then
  # Binario renomeado blender -> nuclear no rebrand; aceita os dois nomes.
  SMOKE_BIN="$BUILD_DIR/bin/nuclear"
  [[ -x "$SMOKE_BIN" ]] || SMOKE_BIN="$BUILD_DIR/bin/blender"
  if [[ ! -x "$SMOKE_BIN" ]] && ! $DRY_RUN; then
    echo "erro: binario nao encontrado em $BUILD_DIR/bin/nuclear (rode com --build ou ajuste --build-dir)." >&2
    exit 1
  fi
  run "$SMOKE_BIN" -b --factory-startup --python "$REPO_ROOT/tools/smoke_nuclear2d.py"
  echo ">> smoke 2D: ALL PASS"
else
  echo "-- smoke gate pulado (--no-smoke): empacotando build sem verificacao 2D"
fi
echo

# 3. Package ----------------------------------------------------------------
STAGE_DIR="$BUILD_DIR/Nuclear"
ZIP_PATH="$BUILD_DIR/nuclear.zip"
MANIFEST_PATH="$BUILD_DIR/version.json"

run rm -rf "$STAGE_DIR"
run cp -al "$BUILD_DIR/bin" "$STAGE_DIR"
# Prune dead 3D dependency libs (features OFF in the preset) + build tools from
# the staging copy before zipping. Hardlink-safe: only the staging links are
# dropped, $BUILD_DIR/bin stays whole. Skip with --no-prune. Validated to keep
# the 2D pipeline pixel-identical (2026-07-07). Also strip the auto-update
# relics if a previous run left them in bin/ (the packaging note's manual step).
run rm -rf "$STAGE_DIR/versions" "$STAGE_DIR/current"
if $DO_PRUNE; then
  run bash "$SCRIPT_DIR/nuclear_prune_package.sh" "$STAGE_DIR"
else
  echo "-- poda de peso morto pulada (--no-prune)"
fi
run python3 "$RELEASE_PY" stamp "$STAGE_DIR"
run rm -f "$ZIP_PATH"
if $DRY_RUN; then
  printf '[dry-run] (cd %q && zip -qr %q %q)\n' "$BUILD_DIR" "$(basename "$ZIP_PATH")" "$(basename "$STAGE_DIR")"
else
  ( cd "$BUILD_DIR" && zip -qr "$(basename "$ZIP_PATH")" "$(basename "$STAGE_DIR")" )
fi
echo ">> empacotado: $ZIP_PATH"
echo

# 4. Verify golden rules #3/#4 -----------------------------------------------
run python3 "$RELEASE_PY" verify-zip --zip "$ZIP_PATH"
echo

# 5. Manifest + checksum verification ---------------------------------------
if [[ -z "$NOTES" ]] && ! $ASSUME_YES; then
  read -r -p "Notas de release (texto curto do que mudou): " NOTES || NOTES=""
fi
run python3 "$RELEASE_PY" manifest --zip "$ZIP_PATH" --notes "$NOTES" -o "$MANIFEST_PATH"
run python3 "$RELEASE_PY" check-manifest --zip "$ZIP_PATH" --manifest "$MANIFEST_PATH"
echo

# 6. Publish (zip + manifest together, never one without the other) --------
if confirm "Publicar nuclear.zip + version.json em $REMOTE via scp?"; then
  run scp "$ZIP_PATH" "$MANIFEST_PATH" "$REMOTE"
  run cp "$MANIFEST_PATH" "$TELEMETRY_MIRROR"
  PUBLISHED=true
else
  echo "-- publicacao pulada. Quando estiver pronto: scp '$ZIP_PATH' '$MANIFEST_PATH' '$REMOTE'"
  PUBLISHED=false
fi
echo

# 7. CLAUDE.md reminder (never auto-edited -- the "o que mudou" prose stays human) ---
cat <<EOF
== Lembrete: cole isto na secao "Estado atual" de tools/nuclear_claude/CLAUDE.md ==

- **Versao publicada:** $AFTER (era $BEFORE).
- **Data:** $(date +%Y-%m-%d)
- **nuclear.zip:** $([[ -f "$ZIP_PATH" ]] && stat -c '%s bytes' "$ZIP_PATH" 2>/dev/null || echo "(dry-run, nao gerado)")
- **Notas:** ${NOTES:-"(preencher)"}
EOF
echo

# 8. Commit (no Co-Authored-By -- a human is running this, not the agent) ---
if confirm "Comitar as mudancas (header de versao + espelho do manifesto) agora?"; then
  run git -C "$REPO_ROOT" add \
    "$REPO_ROOT/source/blender/blenkernel/BKE_blender_version.h" \
    "$TELEMETRY_MIRROR"
  read -r -p "Mensagem do commit: " COMMIT_MSG || COMMIT_MSG="release: $AFTER"
  run git -C "$REPO_ROOT" commit -m "$COMMIT_MSG"
else
  echo "-- commit pulado. Lembre de commitar o header e o espelho do manifesto."
fi
echo

echo "== Resumo =="
echo "versao:      $BEFORE -> $AFTER"
echo "zip:         $ZIP_PATH"
echo "manifesto:   $MANIFEST_PATH"
echo "publicado:   ${PUBLISHED:-false} (em $REMOTE)"
echo "pendente:    atualizar tools/nuclear_claude/CLAUDE.md a mao (bloco acima); ping.php / instalarNuclear.sh NAO sao tocados por este script."
