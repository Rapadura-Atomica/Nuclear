#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Poda o staging de empacotamento do Nuclear 2D: remove peso morto que o
# `ninja install` arrasta para `bin/` mas que o binário 2D NUNCA usa em runtime.
#
#   tools/nuclear_prune_package.sh <staging-dir>   # ex.: <build>/Nuclear
#
# O que remove, e POR QUÊ é seguro (validado 2026-07-07: binário abre, smoke
# 2D 15/15, render do take DPE pixel-idêntico à produção COM estas libs fora):
#
#   1. lib/ — bibliotecas de deps de features DESLIGADAS pelo preset nuclear_2d
#      (Cycles + seu backend de GPU-compute, OpenVDB, USD, OSL, Embree,
#      MaterialX-OSL). Como WITH_CYCLES/WITH_OPENVDB/WITH_USD estão OFF, nada no
#      binário faz dlopen/link nelas. ~291 MB.
#      ⚠️ A poda é por ALLOW-LIST DE FEATURE (as libs abaixo), NUNCA por
#      "não aparece no NEEDED" — libs como OpenColorIO/OpenEXR/OpenImageIO SÃO
#      usadas pelo pipeline 2D e não estão no NEEDED direto (carregadas por
#      outra via). Cortar por alcançabilidade quebraria a gestão de cor.
#
#   2. Ferramentas de build na raiz de bin/ (makesrna, makesdna, msgfmt,
#      glsl_preprocess, datatoc) — geradores usados só no build, nunca em
#      runtime. ~20 MB.
#
# NÃO toca em: o binário, 5.0/ (python/datafiles/scripts), locale (ver nota no
# fim), blender-thumbnailer (é runtime), nem qualquer lib de feature LIGADA.
#
# Idempotente. Só remove o que existe. Após a poda, valida que o binário do
# staging ainda sobe (`--version`), o que exercita o RUNPATH ($ORIGIN/lib).
set -euo pipefail
export LC_ALL=C

STAGING="${1:-}"
[ -n "$STAGING" ] && [ -d "$STAGING" ] || { echo "uso: $0 <staging-dir>" >&2; exit 2; }
LIBDIR="$STAGING/lib"

# Prefixos de lib de features OFF (âncora ^lib, cobre .so / .so.N / .so.N.N.N).
FEATURE_OFF_LIBS='^lib(usd|osl|oslexec|oslcomp|oslquery|oslnoise|openvdb|nanovdb|embree|hiprt|ur_loader|ur_adapter|sycl|MaterialXGenOsl|MaterialXRenderOsl|openimagedenoise|oidn)'

BUILD_TOOLS='makesrna makesdna msgfmt glsl_preprocess datatoc'

human() { du -sm "$1" 2>/dev/null | cut -f1; }

before=$(du -sm "$STAGING" | cut -f1)

# 1. libs de features OFF
n_lib=0
if [ -d "$LIBDIR" ]; then
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    rm -f "$LIBDIR/$f" && n_lib=$((n_lib + 1))
  done < <(ls "$LIBDIR" 2>/dev/null | grep -iE "$FEATURE_OFF_LIBS" || true)
fi

# 2. ferramentas de build na raiz
n_tool=0
for t in $BUILD_TOOLS; do
  if [ -e "$STAGING/$t" ]; then rm -f "$STAGING/$t" && n_tool=$((n_tool + 1)); fi
done

after=$(du -sm "$STAGING" | cut -f1)

echo "poda: ${n_lib} libs de feature-OFF + ${n_tool} ferramentas de build"
echo "staging: ${before} MB -> ${after} MB (economia: $((before - after)) MB)"

# 3. sanity: o binário do staging ainda sobe?
BIN="$STAGING/blender"
if [ -x "$BIN" ]; then
  if v="$("$BIN" --version 2>/dev/null | head -1)"; then
    echo "sanity OK: $v"
  else
    echo "ERRO: o binário do staging não sobe após a poda — abortar o release." >&2
    exit 1
  fi
fi

# Nota (NÃO automatizado — exige teste de UI/i18n): locale/ traz as traduções
# .mo de dezenas de idiomas (~66 MB). O Nuclear é English-only por ora; dá pra
# cortar tudo menos en_US/pt_BR e economizar ~60 MB, MAS o seam de branding usa
# bpy.app.translations em runtime — validar a UI antes. Fica de fora desta poda.
