#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Gera o artefato distribuivel "Nuclear-Installer": um UNICO arquivo executavel,
# auto-contido, para maquinas onde o Nuclear ainda nao esta instalado. E o proprio
# instalarNuclear-wizard.sh com um banner de identificacao. Sem AppImage/FUSE: o
# instalador so orquestra ferramentas de sistema, entao nao ha libs a empacotar
# (e FUSE costuma faltar em Bazzite/Fedora Atomic, o alvo principal).
#
# Rode este script sempre que o wizard mudar, para atualizar dist/Nuclear-Installer.

set -eu
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$SELF_DIR/instalarNuclear-wizard.sh"
OUT="$SELF_DIR/dist/Nuclear-Installer"

mkdir -p "$SELF_DIR/dist"
{
    head -3 "$SRC"   # shebang + 2 linhas SPDX
    cat <<'BANNER'
#
# ====================================================================
# Nuclear-Installer — instalador de clique unico (auto-contido).
# Copie este ARQUIVO UNICO para qualquer Linux e execute. Nao precisa do
# repositorio, nem de FUSE, nem de instalar nada: usa so ferramentas de
# sistema (bash/python3/unzip/wget|curl) e abre um wizard grafico.
# ====================================================================
BANNER
    tail -n +4 "$SRC"
} > "$OUT"
chmod +x "$OUT"

bash -n "$OUT"
echo "[OK] $OUT ($(wc -c < "$OUT") bytes)"
