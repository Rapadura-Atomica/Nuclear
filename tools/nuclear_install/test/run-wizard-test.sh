#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Harness de TESTE VISUAL do instalador guiado (instalarNuclear-wizard.sh).
#
# Feito para ser lancado por 2 cliques a partir de um atalho .desktop (sem
# terminal): monta um pacote falso + servidor HTTP local, isola o $HOME num
# diretorio de cache descartavel e abre o wizard de verdade. Nao baixa nada da
# producao e nao toca no ~/Nuclear real. O binario "blender" do pacote e um
# dummy inofensivo (so mostra um aviso).
#
# Variaveis uteis:
#   NUCLEAR_INSTALLER_UI=kdialog|zenity|tui|text  forca o backend (padrao: auto).
#   NUCLEAR_TEST_DRYRUN=1  monta tudo, confere o manifesto e sai SEM abrir a GUI
#                          (usado na validacao automatica do proprio harness).

set -u

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
WIZARD="$SELF_DIR/../instalarNuclear-wizard.sh"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/nuclear-wizard-test"
SRV="$CACHE/srv"

# Sem terminal quando lancado pelo .desktop: erros vao para uma caixa grafica.
notify_err() {
    if command -v kdialog >/dev/null 2>&1; then kdialog --error "$1"
    elif command -v zenity >/dev/null 2>&1; then zenity --error --width=420 --text="$1"
    else echo "[ERRO] $1" >&2; fi
}

[ -f "$WIZARD" ] || { notify_err "Nao encontrei o wizard em: $WIZARD"; exit 1; }
command -v python3 >/dev/null 2>&1 || { notify_err "python3 nao encontrado."; exit 1; }
command -v zip >/dev/null 2>&1 || { notify_err "zip nao encontrado."; exit 1; }

mkdir -p "$SRV"

# --- fixtures (montadas uma vez e cacheadas) ---------------------------------
if [ ! -f "$SRV/nuclear.zip" ]; then
    root="$CACHE/pkgroot"; mkdir -p "$root/Nuclear"
    head -c 38000000 /dev/urandom > "$root/Nuclear/payload.bin"
    cat > "$root/Nuclear/blender" <<'DUMMY'
#!/bin/sh
kdialog --msgbox "Nuclear (dummy de teste) foi aberto. Nada real rodou." 2>/dev/null \
  || zenity --info --width=380 --text="Nuclear (dummy de teste). Nada real rodou." 2>/dev/null \
  || true
exit 0
DUMMY
    chmod +x "$root/Nuclear/blender"
    printf '<svg xmlns="http://www.w3.org/2000/svg"/>' > "$root/Nuclear/blender.svg"
    ( cd "$root" && zip -qr "$SRV/nuclear.zip" Nuclear ) || { notify_err "Falha ao montar o pacote de teste."; exit 1; }

    ad="$CACHE/addonsrc/svg_to_gp"; mkdir -p "$ad"; echo "x" > "$ad/__init__.py"
    ( cd "$CACHE/addonsrc" && zip -qr "$SRV/addons.zip" . )
fi

SHA="$(sha256sum "$SRV/nuclear.zip" | awk '{print $1}')"
SIZE="$(stat -c%s "$SRV/nuclear.zip")"

# Porta livre (evita conflito se rodar varias vezes).
PORT="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"

# Manifesto regenerado a cada run (a porta muda), reaproveitando o pacote cacheado.
cat > "$SRV/version.json" <<EOF
{"name":"Nuclear","build":9,"version":"1.4.4","stage":"Beta","url":"http://127.0.0.1:$PORT/nuclear.zip","sha256":"$SHA","size":$SIZE,"notes":"Build de TESTE (launcher .desktop)"}
EOF

# $HOME isolado e limpo a cada run (o seletor de pasta abre nele como Inicio).
THOME="$CACHE/home"
rm -rf "$THOME"; mkdir -p "$THOME/Documentos" "$THOME/Downloads"

# Sobe o servidor local e garante que ele morra ao sair.
python3 -m http.server "$PORT" --directory "$SRV" >/dev/null 2>&1 &
SRVPID=$!
trap 'kill "$SRVPID" 2>/dev/null' EXIT
sleep 1

export HOME="$THOME"
export NUCLEAR_MANIFEST_URL="http://127.0.0.1:$PORT/version.json"
export NUCLEAR_ADDONS_URL="http://127.0.0.1:$PORT/addons.zip"

# Modo de auto-teste: confere que o servidor serve o manifesto e sai sem GUI.
if [ "${NUCLEAR_TEST_DRYRUN:-}" = "1" ]; then
    got="$(curl -fsS "$NUCLEAR_MANIFEST_URL" 2>/dev/null | python3 -c 'import sys,json; print(json.load(sys.stdin)["build"])' 2>/dev/null)"
    if [ "$got" = "9" ]; then echo "[dry-run OK] servidor/manifesto na porta $PORT, HOME=$THOME"; exit 0
    else echo "[dry-run FALHOU] manifesto nao respondeu na porta $PORT"; exit 1; fi
fi

# Abre o wizard de verdade (backend auto-detectado: kdialog no KDE, zenity no GNOME).
bash "$WIZARD"
