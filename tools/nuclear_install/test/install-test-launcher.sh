#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Registra o atalho "Nuclear — Testar Wizard" no menu de aplicativos desta
# maquina (preenche o caminho absoluto do run-wizard-test.sh). Rode uma vez.

set -u
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$SELF_DIR/run-wizard-test.sh"
DEST="$HOME/.local/share/applications/nuclear-wizard-test.desktop"

mkdir -p "$(dirname "$DEST")"
cat > "$DEST" <<EOF
[Desktop Entry]
Name=Nuclear — Testar Wizard
GenericName=Teste do instalador guiado
Comment=Abre o wizard de instalacao com pacote falso e servidor local (nao toca no Nuclear real)
Exec=bash "$SCRIPT"
Icon=system-software-install
Type=Application
Categories=Development;
Terminal=false
StartupNotify=true
EOF

chmod +x "$DEST" 2>/dev/null || true
update-desktop-database "$(dirname "$DEST")" >/dev/null 2>&1 || true
echo "[OK] Atalho registrado: $DEST"
echo "     Procure por 'Nuclear — Testar Wizard' no menu de aplicativos."
