#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Registra o atalho "Instalar Nuclear" no menu de aplicativos: um item clicavel
# que abre o wizard de instalacao de PRODUCAO (instalarNuclear-wizard.sh, sem
# nenhum override de teste). Clicar = baixar e instalar o Nuclear real.
#
# Diferente do test/install-test-launcher.sh, que aponta para o harness de teste
# (servidor local + pacote falso). Rode uma vez.

set -u
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
WIZARD="$SELF_DIR/instalarNuclear-wizard.sh"
DEST="$HOME/.local/share/applications/nuclear-install.desktop"

[ -f "$WIZARD" ] || { echo "[ERRO] wizard nao encontrado: $WIZARD" >&2; exit 1; }

mkdir -p "$(dirname "$DEST")"
cat > "$DEST" <<EOF
[Desktop Entry]
Name=Instalar Nuclear
GenericName=Instalador do Nuclear
Comment=Baixa e instala a versao mais recente do Nuclear
Exec=bash "$WIZARD"
Icon=system-software-install
Type=Application
Categories=Graphics;
Terminal=false
StartupNotify=true
EOF

chmod +x "$DEST" 2>/dev/null || true
update-desktop-database "$(dirname "$DEST")" >/dev/null 2>&1 || true
echo "[OK] Atalho registrado: $DEST"
echo "     Procure por 'Instalar Nuclear' no menu de aplicativos."
