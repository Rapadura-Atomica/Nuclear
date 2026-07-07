#!/bin/bash
# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Instalador do Nuclear (layout versionado, compativel com o auto-update).
#
# Em vez de extrair direto em ~/Nuclear/5.0, este instalador monta o mesmo layout
# que o atualizador embutido (scripts/startup/nuclear_update.py) usa:
#
#   ~/Nuclear/
#     versions/<versao>-b<build>/   <- pasta portatil completa do Nuclear
#     current -> versions/<...>      <- symlink atomico; o .desktop lanca ESTE
#
# Assim, quando o Nuclear avisar de uma atualizacao e o usuario clicar em instalar,
# a troca e so um flip de symlink e o lancador continua valendo. Tudo mora no $HOME,
# entao funciona em SO imutavel (Bazzite/Fedora Atomic) sem mexer em /usr.
#
# O instalador le os metadados de estacao/version.json, entao ele e o instalador e o
# atualizador compartilham a mesma fonte de verdade de versao/checksum.

set -u

BASE_DIR="$HOME/Nuclear"
VERSIONS_DIR="$BASE_DIR/versions"
CURRENT_LINK="$BASE_DIR/current"
MANIFEST_URL="https://rapaduraatomica.com.br/estacao/version.json"
ADDONS_DOWNLOAD_URL="https://rapaduraatomica.com.br/estacao/addons.zip"
DESKTOP_FILE="$HOME/.local/share/applications/Nuclear.desktop"

# same_origin URL_A URL_B -> exit 0 se compartilham esquema+host+porta.
# Pina downloads a origem do manifesto confiavel (python3 ja e dependencia).
same_origin() {
    python3 -c 'import sys,urllib.parse as u
a=u.urlsplit(sys.argv[1]); b=u.urlsplit(sys.argv[2])
sys.exit(0 if (a.scheme and a.hostname and a.scheme.lower()==b.scheme.lower() and a.hostname.lower()==b.hostname.lower() and (a.port or 0)==(b.port or 0)) else 1)' "$1" "$2"
}

echo "[INFO] Instalacao do Nuclear (layout versionado)"
echo "========================================"

# --- 1. ler o manifesto ------------------------------------------------------

echo "[1/5] Lendo manifesto: $MANIFEST_URL"
MANIFEST="$(curl -fsSL -A 'Nuclear-Installer/1.0' "$MANIFEST_URL")" || {
    echo "[ERRO] Nao foi possivel baixar o manifesto"; exit 1; }

# Extrai campos do JSON sem depender de jq (usa python3, que o sistema tem).
# Campos de addons sao opcionais (so presentes se a release os publicou).
read -r BUILD VERSION URL SHA256 ADDONS_URL_M ADDONS_SHA256 <<EOF
$(printf '%s' "$MANIFEST" | python3 -c 'import sys,json; m=json.load(sys.stdin); print(m["build"], m["version"], m["url"], m.get("sha256",""), m.get("addons_url",""), m.get("addons_sha256",""))')
EOF

# Seguranca (fail-closed): o zip TEM que vir da MESMA origem (esquema+host+porta)
# do manifesto, e o manifesto TEM que trazer sha256. Senao, um manifesto adulterado
# poderia apontar o download para outro host / http:// ou pular a verificacao de
# integridade - e o binario baixado roda no proximo boot.
if [ -z "$SHA256" ]; then
    echo "[ERRO] Manifesto sem sha256 - instalacao recusada por seguranca"; exit 1
fi
if ! same_origin "$URL" "$MANIFEST_URL"; then
    echo "[ERRO] URL de download recusada por seguranca (origem difere do manifesto): $URL"; exit 1
fi

VERSION_DIRNAME="${VERSION}-b${BUILD}"
INSTALL_DIR="$VERSIONS_DIR/$VERSION_DIRNAME"
echo "       versao $VERSION (build $BUILD) -> $INSTALL_DIR"

if [ -d "$INSTALL_DIR" ]; then
    echo "[AVISO] Esta versao ja esta instalada em $INSTALL_DIR"
    read -p "Reinstalar? (s/n): " -n 1 -r; echo
    [[ $REPLY =~ ^[Ss]$ ]] && rm -rf "$INSTALL_DIR" || { echo "[INFO] Mantendo o que ja existe."; }
fi

# --- 2. baixar + verificar ---------------------------------------------------

mkdir -p "$VERSIONS_DIR"
if [ ! -d "$INSTALL_DIR" ]; then
    echo "[2/5] Baixando Nuclear: $URL"
    TMP="$(mktemp -d "$VERSIONS_DIR/.install-XXXXXX")" || { echo "[ERRO] mktemp"; exit 1; }
    trap 'rm -rf "$TMP"' EXIT
    wget --show-progress -q -O "$TMP/nuclear.zip" "$URL" || { echo "[ERRO] Falha no download"; exit 1; }

    echo "       verificando checksum..."
    GOT="$(sha256sum "$TMP/nuclear.zip" | awk '{print $1}')"
    if [ "$GOT" != "$SHA256" ]; then
        echo "[ERRO] Checksum nao confere (download corrompido)"; exit 1
    fi

    echo "       extraindo..."
    unzip -q "$TMP/nuclear.zip" -d "$TMP/x" || { echo "[ERRO] Falha ao extrair"; exit 1; }

    # Acha a pasta que contem o binario 'blender' dentro do zip.
    SRC="$(dirname "$(find "$TMP/x" -name blender -type f | head -n1)")"
    [ -z "$SRC" ] && { echo "[ERRO] binario 'blender' nao encontrado no pacote"; exit 1; }

    mv "$SRC" "$INSTALL_DIR" || { echo "[ERRO] Falha ao instalar"; exit 1; }

    # Carimba a versao instalada (o auto-update le isto para saber o build atual).
    printf '%s' "$MANIFEST" > "$INSTALL_DIR/nuclear_version.json"
    rm -rf "$TMP"; trap - EXIT
    echo "[OK] Nuclear $VERSION (build $BUILD) instalado"
else
    echo "[2/5] Pulando download (ja instalado)."
fi

# --- 3. flip do symlink 'current' --------------------------------------------

echo "[3/5] Apontando 'current' -> $VERSION_DIRNAME"
ln -sfn "$INSTALL_DIR" "$CURRENT_LINK"

# --- 4. atalho .desktop apontando para current -------------------------------

echo "[4/5] Criando atalho: $DESKTOP_FILE"
mkdir -p "$(dirname "$DESKTOP_FILE")"
ICON="$CURRENT_LINK/blender.svg"
[ -f "$ICON" ] || ICON="blender"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Name=Nuclear
GenericName=2D Animation
Exec=$CURRENT_LINK/blender --app-template Nuclear %F
Icon=$ICON
Type=Application
Categories=Graphics;2DGraphics;
MimeType=application/x-nuclear;application/x-blender;
StartupNotify=true
StartupWMClass=Nuclear
Terminal=false
EOF
update-desktop-database "$(dirname "$DESKTOP_FILE")" >/dev/null 2>&1 || true

# Registra o tipo MIME 'application/x-nuclear' (extensão .nuc) para que arquivos
# criados no Nuclear abram nele ao dar duplo-clique. Arquivos .blend legados também
# seguem associados (o .desktop acima reivindica os dois tipos).
MIME_PKG_DIR="$HOME/.local/share/mime/packages"
mkdir -p "$MIME_PKG_DIR"
cat > "$MIME_PKG_DIR/nuclear.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="application/x-nuclear">
    <comment>Nuclear scene</comment>
    <glob pattern="*.nuc"/>
  </mime-type>
</mime-info>
EOF
update-mime-database "$HOME/.local/share/mime" >/dev/null 2>&1 || true

# --- 5. addons externos ------------------------------------------------------

# Rebrand: a pasta de config passou de 'blender' para 'Nuclear'. Migra os settings
# de quem ja rodava o Nuclear para nao perder tema/keymaps/addons (idempotente:
# so copia se a pasta nova ainda nao existir).
CFG_ROOT="${XDG_CONFIG_HOME:-$HOME/.config}"
LEGACY_CFG="$CFG_ROOT/blender/$VERSION"
NUCLEAR_CFG="$CFG_ROOT/Nuclear/$VERSION"
if [ -d "$LEGACY_CFG" ] && [ ! -e "$NUCLEAR_CFG" ]; then
    mkdir -p "$CFG_ROOT/Nuclear"
    if cp -a "$LEGACY_CFG" "$NUCLEAR_CFG" 2>/dev/null; then
        echo "[OK] Config migrada: blender/$VERSION -> Nuclear/$VERSION"
    fi
fi

echo "[5/5] Instalando addons externos"
ADDONS_DIR="$NUCLEAR_CFG/scripts/addons"
mkdir -p "$ADDONS_DIR"
TMP_A="$(mktemp -d)"; trap 'rm -rf "$TMP_A"' EXIT
# URL efetiva: a do manifesto (se publicada) ou o default. Addons sao codigo, entao
# se o manifesto trouxer addons_sha256 ele e OBRIGATORIO; sem hash, cai no modo
# legado (best-effort, sem verificacao). Origem sempre pinada ao manifesto quando
# a URL vem dele. Falha aqui nunca aborta a instalacao (addons sao opcionais).
ADDONS_EFF_URL="$ADDONS_DOWNLOAD_URL"
[ -n "$ADDONS_URL_M" ] && ADDONS_EFF_URL="$ADDONS_URL_M"
if [ -n "$ADDONS_URL_M" ] && ! same_origin "$ADDONS_EFF_URL" "$MANIFEST_URL"; then
    echo "[AVISO] URL de addons recusada por seguranca (origem difere do manifesto); pulando addons"
elif ! wget --show-progress -q -O "$TMP_A/addons.zip" "$ADDONS_EFF_URL"; then
    echo "[AVISO] Nao foi possivel baixar os addons (seguindo sem eles)"
elif [ -n "$ADDONS_SHA256" ] && [ "$(sha256sum "$TMP_A/addons.zip" | awk '{print $1}')" != "$ADDONS_SHA256" ]; then
    echo "[AVISO] Checksum dos addons nao confere; NAO instalando addons (o app segue normal)"
else
    unzip -q "$TMP_A/addons.zip" -d "$TMP_A/x" && cp -r "$TMP_A/x"/* "$ADDONS_DIR/" 2>/dev/null
    echo "[OK] Addons instalados em $ADDONS_DIR"
fi
rm -rf "$TMP_A"; trap - EXIT

echo ""
echo "========================================"
echo "INSTALACAO CONCLUIDA"
echo "  Nuclear:  $INSTALL_DIR"
echo "  current:  $CURRENT_LINK -> $VERSION_DIRNAME"
echo "  atalho:   $DESKTOP_FILE"
echo "========================================"
