#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Instalador guiado (wizard) do Nuclear para Linux.
#
# Este script e uma CAMADA DE EXPERIENCIA por cima da mesma logica de instalacao
# versionada do instalarNuclear.sh (layout ~/Nuclear/versions/<ver>-b<build>/ +
# symlink atomico "current", compativel com o auto-update embutido). A logica de
# download/checksum/layout/desktop e a mesma ja validada; o que muda e a conducao:
#
#   - UI GUI-first com degradacao graciosa: kdialog (KDE/Bazzite) -> zenity (GNOME)
#     -> whiptail/dialog (TUI) -> texto puro lendo de /dev/tty. GUI e imune ao
#     problema do "curl | bash" que rouba o stdin; o ramo de texto le de /dev/tty.
#   - Pre-checagem: ferramentas, espaco em disco (a partir de manifest.size), $HOME
#     gravavel, deteccao de SO.
#   - Barra de progresso real no download (determinada por manifest.size).
#   - Passo de consentimento de telemetria de presenca (opt-out honesto via a env
#     var NUCLEAR_TELEMETRY_OFF=1 no Exec do .desktop).
#   - Oferecer abrir o Nuclear ao final.
#
# Uso:
#   instalarNuclear-wizard.sh [--yes] [--dir CAMINHO] [--no-telemetry] [--help]
#     --yes           nao-interativo: aceita padroes (usado quando nao ha GUI/tty).
#     --dir CAMINHO   diretorio base (padrao: ~/Nuclear).
#     --no-telemetry  ja instala com a telemetria de presenca desligada.
#     --help          mostra este resumo.

set -u

# --- constantes --------------------------------------------------------------

# URLs podem ser sobrescritas por env var (para testes/staging), a exemplo do que
# a telemetria ja faz. Em producao ficam nos padroes abaixo.
MANIFEST_URL="${NUCLEAR_MANIFEST_URL:-https://rapaduraatomica.com.br/estacao/version.json}"
ADDONS_DOWNLOAD_URL="${NUCLEAR_ADDONS_URL:-https://rapaduraatomica.com.br/estacao/addons.zip}"
INSTALLER_VERSION="2.0-wizard"
APP_TITLE="Instalador do Nuclear"

# Fator de folga de disco: zip (download temporario) + arvore extraida (~3.5x o zip)
# + margem. Usado so na pre-checagem; nao precisa ser exato.
SPACE_FACTOR_NUM=5     # multiplica manifest.size por 5/1 ...
SPACE_MARGIN_BYTES=$((300 * 1024 * 1024))  # ... e soma 300 MiB de margem.

# --- opcoes de linha de comando ----------------------------------------------

BASE_DIR="$HOME/Nuclear"
DIR_SET=0        # 1 = usuario passou --dir; pula o seletor grafico de pasta.
ASSUME_YES=0
TELEMETRY_OFF=0

usage() {
    sed -n '5,27p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
    case "$1" in
        --yes|-y)        ASSUME_YES=1 ;;
        --no-telemetry)  TELEMETRY_OFF=1 ;;
        --dir)           shift; [ $# -gt 0 ] || { echo "[ERRO] --dir requer um caminho"; exit 2; }; BASE_DIR="$1"; DIR_SET=1 ;;
        --dir=*)         BASE_DIR="${1#--dir=}"; DIR_SET=1 ;;
        -h|--help)       usage; exit 0 ;;
        *)               echo "[ERRO] opcao desconhecida: $1"; usage; exit 2 ;;
    esac
    shift
done

# Staging de download removido na saida (sucesso ou fatal). Uma unica trap EXIT
# evita o vazamento que uma trap RETURN por-funcao causaria sob "set -u".
_tmp_root=""
_cleanup() { [ -n "$_tmp_root" ] && rm -rf "$_tmp_root" 2>/dev/null; }
trap _cleanup EXIT

# =============================================================================
# Camada de UI: detecta o backend mais rico disponivel e expoe primitivas
# uniformes (ui_info / ui_error / ui_confirm / ui_input / ui_download).
# =============================================================================

UI=""          # kdialog | zenity | tui | text
TUI_BIN=""     # whiptail | dialog (quando UI=tui)
QDBUS_BIN=""   # qdbus para a barra do kdialog (quando existir)

_has() { command -v "$1" >/dev/null 2>&1; }

_in_gui_session() {
    [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]
}

_is_kde() {
    case "${XDG_CURRENT_DESKTOP:-}${DESKTOP_SESSION:-}" in
        *KDE*|*kde*|*plasma*|*Plasma*) return 0 ;;
        *) return 1 ;;
    esac
}

detect_ui() {
    # Forcar um backend (kdialog|zenity|tui|text) via env var, util para suporte
    # e testes headless.
    case "${NUCLEAR_INSTALLER_UI:-}" in
        kdialog|zenity|text) UI="${NUCLEAR_INSTALLER_UI}"; return ;;
        tui) UI="tui"; { _has whiptail && TUI_BIN="whiptail"; } || TUI_BIN="dialog"; return ;;
    esac
    if _in_gui_session; then
        if _is_kde && _has kdialog; then UI="kdialog"; return; fi
        if _has zenity; then UI="zenity"; return; fi
        if _has kdialog; then UI="kdialog"; return; fi
    fi
    if _has whiptail; then UI="tui"; TUI_BIN="whiptail"; return; fi
    if _has dialog;   then UI="tui"; TUI_BIN="dialog";   return; fi
    UI="text"
}

detect_qdbus() {
    local c
    for c in qdbus6 qdbus qdbus-qt6 qdbus-qt5; do
        if _has "$c"; then QDBUS_BIN="$c"; return; fi
    done
    QDBUS_BIN=""
}

# Le uma linha do usuario no ramo de texto, sempre do terminal real (/dev/tty),
# nao do stdin (que pode ser o proprio script sob "curl | bash").
_read_tty() {
    # $1 = variavel de destino, $2 = prompt
    if [ -r /dev/tty ]; then
        printf '%s' "$2" > /dev/tty
        IFS= read -r "$1" < /dev/tty
    else
        # Sem terminal: nao da pra perguntar. Sinaliza para o chamador usar o padrao.
        return 1
    fi
}

ui_info() {   # titulo, mensagem
    case "$UI" in
        kdialog) kdialog --title "$1" --msgbox "$2" ;;
        zenity)  zenity --info --title="$1" --width=420 --text="$2" ;;
        tui)     "$TUI_BIN" --title "$1" --msgbox "$2" 15 70 ;;
        text)    printf '\n== %s ==\n%s\n' "$1" "$2" >&2 ;;
    esac
}

ui_error() {  # titulo, mensagem
    case "$UI" in
        kdialog) kdialog --title "$1" --error "$2" ;;
        zenity)  zenity --error --title="$1" --width=420 --text="$2" ;;
        tui)     "$TUI_BIN" --title "$1" --msgbox "ERRO: $2" 15 70 ;;
        text)    printf '\n[ERRO] %s\n%s\n' "$1" "$2" >&2 ;;
    esac
}

# Retorna 0 = sim, 1 = nao. Sob --yes, ou sem tty no ramo de texto, assume "sim".
ui_confirm() {  # titulo, mensagem
    if [ "$ASSUME_YES" = "1" ]; then return 0; fi
    case "$UI" in
        kdialog) kdialog --title "$1" --yesno "$2" ;;
        zenity)  zenity --question --title="$1" --width=420 --text="$2" ;;
        tui)     "$TUI_BIN" --title "$1" --yesno "$2" 15 70 ;;
        text)
            local _r
            if _read_tty _r "$2 [S/n]: "; then
                case "$_r" in ''|[Ss]*) return 0 ;; *) return 1 ;; esac
            else
                return 0  # sem tty: aceita o padrao (sim)
            fi
            ;;
    esac
}

# Ecoa o valor digitado (ou o padrao). $1 titulo, $2 mensagem, $3 padrao.
ui_input() {
    if [ "$ASSUME_YES" = "1" ]; then printf '%s' "$3"; return 0; fi
    local out
    case "$UI" in
        kdialog) out=$(kdialog --title "$1" --inputbox "$2" "$3") || out="$3" ;;
        zenity)  out=$(zenity --entry --title="$1" --width=420 --text="$2" --entry-text="$3") || out="$3" ;;
        tui)     out=$("$TUI_BIN" --title "$1" --inputbox "$2" 12 70 "$3" 3>&1 1>&2 2>&3) || out="$3" ;;
        text)
            local _r
            if _read_tty _r "$2 [$3]: "; then
                out="${_r:-$3}"
            else
                out="$3"
            fi
            ;;
    esac
    [ -n "$out" ] || out="$3"
    printf '%s' "$out"
}

# A partir de um LOCAL escolhido (a pasta-pai), deriva o diretorio base do Nuclear:
# a instalacao fica sempre contida numa subpasta "Nuclear/" (evita espalhar
# versions/current solto na Home). Se o proprio local ja se chama "Nuclear", usa
# como esta em vez de duplicar.
_base_from_parent() {
    local p="${1%/}"
    case "$(basename "$p")" in
        Nuclear) printf '%s' "$p" ;;
        *)       printf '%s/Nuclear' "$p" ;;
    esac
}

# Escolha visual da pasta. Abre o seletor de diretorios NATIVO (no Plasma/GNOME
# ja vai pelo Portal do XDG), comecando em Inicio (Home). Ecoa o diretorio base
# final. Em TUI/texto (sem seletor grafico) cai para um campo de caminho.
ui_pickdir() {  # titulo, mensagem, pasta-pai-padrao (ex.: $HOME)
    local title="$1" msg="$2" defp="${3%/}" sel=""
    if [ "$ASSUME_YES" = "1" ]; then printf '%s' "$(_base_from_parent "$defp")"; return; fi
    case "$UI" in
        kdialog) sel=$(kdialog --title "$title" --getexistingdirectory "$defp" 2>/dev/null) ;;
        zenity)  sel=$(zenity --file-selection --directory --title="$title" --filename="$defp/" 2>/dev/null) ;;
        *)       # Sem seletor grafico: pede o caminho completo por texto.
                 printf '%s' "$(ui_input "$title" "$msg" "$(_base_from_parent "$defp")")"; return ;;
    esac
    [ -n "$sel" ] || sel="$defp"   # cancelou -> mantem o padrao (Inicio).
    printf '%s' "$(_base_from_parent "$sel")"
}

# --- download com barra de progresso -----------------------------------------

# Baixa $1 para $2 usando wget ou curl (o que existir). Roda em foreground.
_downloader() {
    if _has wget; then wget -q -O "$2" "$1"
    elif _has curl; then curl -fsSL -o "$2" "$1"
    else return 127; fi
}

# GET simples para stdout (usado no manifesto).
_http_get() {
    if _has curl; then curl -fsSL -A "Nuclear-Installer/$INSTALLER_VERSION" "$1"
    elif _has wget; then wget -q -O - "$1"
    else return 127; fi
}

# Gera porcentagens 0..100 em stdout enquanto o download roda, medindo o tamanho
# do arquivo de saida contra o total conhecido (manifest.size). Escreve o codigo
# de saida do downloader em $4 (arquivo).
_progress_gen() {  # url, out, total, rcfile
    local url="$1" out="$2" total="$3" rcfile="$4"
    ( _downloader "$url" "$out"; echo $? > "$rcfile" ) &
    local dpid=$! cur pct=0
    while kill -0 "$dpid" 2>/dev/null; do
        cur=$(stat -c%s "$out" 2>/dev/null || echo 0)
        if [ "$total" -gt 0 ]; then
            pct=$(( cur * 100 / total ))
            [ "$pct" -gt 99 ] && pct=99
        fi
        printf '%s\n' "$pct"
        sleep 0.3
    done
    wait "$dpid" 2>/dev/null
    printf '100\n'
}

# Baixa com feedback visual, escolhendo o melhor renderizador de barra disponivel
# (independente do backend de dialogos). Retorna o codigo de saida do download.
ui_download() {  # url, out, total, titulo
    local url="$1" out="$2" total="$3" title="$4"
    local rcfile; rcfile="$(mktemp)"
    echo 1 > "$rcfile"

    if [ "$UI" = "kdialog" ] && [ -n "$QDBUS_BIN" ]; then
        local ref
        ref=$(kdialog --title "$title" --progressbar "Baixando o Nuclear..." 100) || ref=""
        if [ -n "$ref" ]; then
            _progress_gen "$url" "$out" "$total" "$rcfile" | while IFS= read -r pct; do
                "$QDBUS_BIN" $ref value "$pct" >/dev/null 2>&1 || \
                "$QDBUS_BIN" $ref Set "" value "$pct" >/dev/null 2>&1 || true
            done
            "$QDBUS_BIN" $ref close >/dev/null 2>&1 || true
        else
            _progress_gen "$url" "$out" "$total" "$rcfile" >/dev/null
        fi
    elif _has zenity && { [ "$UI" = "zenity" ] || [ "$UI" = "kdialog" ]; }; then
        _progress_gen "$url" "$out" "$total" "$rcfile" | \
            zenity --progress --title="$title" --text="Baixando o Nuclear..." \
                   --width=420 --auto-close --no-cancel 2>/dev/null || true
    elif [ "$UI" = "tui" ]; then
        _progress_gen "$url" "$out" "$total" "$rcfile" | \
            "$TUI_BIN" --title "$title" --gauge "Baixando o Nuclear..." 8 64 0
    else
        # Barra em texto. Sob "curl | bash" so o stdin e o pipe; stderr ainda e o
        # terminal, entao o progresso vai para stderr (fd 2).
        local bar n
        _progress_gen "$url" "$out" "$total" "$rcfile" | while IFS= read -r pct; do
            n=$(( pct / 2 )); bar=""
            [ "$n" -gt 0 ] && bar=$(printf '#%.0s' $(seq 1 "$n"))
            printf '\r  [%-50s] %3d%%' "$bar" "$pct" >&2
        done
        printf '\n' >&2
    fi

    local rc; rc=$(cat "$rcfile" 2>/dev/null || echo 1); rm -f "$rcfile"
    return "${rc:-1}"
}

# =============================================================================
# Logica de instalacao (mesma do instalador versionado, encapsulada em funcoes).
# =============================================================================

# Preenchidos por read_manifest():
MANIFEST=""; M_BUILD=""; M_VERSION=""; M_URL=""; M_SHA256=""; M_SIZE=0

fatal() { ui_error "$APP_TITLE" "$1"; exit 1; }

preflight() {
    # Ferramentas essenciais.
    local missing=""
    _has python3 || missing="$missing python3"
    _has unzip   || missing="$missing unzip"
    _has sha256sum || missing="$missing sha256sum"
    if ! _has wget && ! _has curl; then missing="$missing wget/curl"; fi
    if [ -n "$missing" ]; then
        fatal "Faltam ferramentas necessarias:$missing

Instale-as pelo gerenciador de pacotes da sua distribuicao e rode o instalador de novo."
    fi
    # $HOME/base gravavel.
    local probe="$BASE_DIR"
    while [ ! -d "$probe" ] && [ "$probe" != "/" ]; do probe="$(dirname "$probe")"; done
    if [ ! -w "$probe" ]; then
        fatal "Sem permissao de escrita em: $probe

O Nuclear se instala inteiramente no seu diretorio pessoal, sem precisar de root."
    fi
}

check_space() {
    # Espaco livre no ponto de instalacao vs. estimativa a partir de manifest.size.
    local needed avail probe
    needed=$(( M_SIZE * SPACE_FACTOR_NUM + SPACE_MARGIN_BYTES ))
    probe="$BASE_DIR"
    while [ ! -d "$probe" ] && [ "$probe" != "/" ]; do probe="$(dirname "$probe")"; done
    avail=$(df -Pk "$probe" 2>/dev/null | awk 'NR==2 {print $4 * 1024}')
    [ -n "$avail" ] || return 0  # se nao der pra medir, nao bloqueia
    if [ "$avail" -lt "$needed" ]; then
        local need_gb avail_gb
        need_gb=$(awk "BEGIN{printf \"%.1f\", $needed/1073741824}")
        avail_gb=$(awk "BEGIN{printf \"%.1f\", $avail/1073741824}")
        ui_confirm "$APP_TITLE" "Espaco em disco pode ser insuficiente.

Necessario (estimado): ${need_gb} GiB
Disponivel em ${probe}: ${avail_gb} GiB

Deseja continuar mesmo assim?" || fatal "Instalacao cancelada por falta de espaco."
    fi
}

read_manifest() {
    MANIFEST="$(_http_get "$MANIFEST_URL")" || fatal "Nao foi possivel baixar o manifesto de versao.

Verifique sua conexao com a internet e tente de novo."
    # Extrai campos sem depender de jq (python3 ja foi checado no preflight).
    local parsed
    parsed="$(printf '%s' "$MANIFEST" | python3 -c \
        'import sys,json; m=json.load(sys.stdin); print(m["build"], m["version"], m["url"], m.get("sha256",""), m.get("size","0"))' 2>/dev/null)" \
        || fatal "O manifesto de versao esta corrompido ou em formato inesperado."
    read -r M_BUILD M_VERSION M_URL M_SHA256 M_SIZE <<EOF
$parsed
EOF
    case "$M_SIZE" in ''|*[!0-9]*) M_SIZE=0 ;; esac
}

# Faz o download + verificacao + extracao + move para versions/. Ecoa (via
# variavel global) o diretorio de instalacao final.
INSTALL_DIR=""
VERSION_DIRNAME=""
do_install() {
    local versions_dir="$BASE_DIR/versions"
    VERSION_DIRNAME="${M_VERSION}-b${M_BUILD}"
    INSTALL_DIR="$versions_dir/$VERSION_DIRNAME"

    if [ -d "$INSTALL_DIR" ]; then
        if ui_confirm "$APP_TITLE" "A versao $M_VERSION (build $M_BUILD) ja esta instalada.

Reinstalar (baixar de novo)?"; then
            rm -rf "$INSTALL_DIR"
        else
            return 0  # mantem o que existe; segue para o symlink/atalho.
        fi
    fi

    mkdir -p "$versions_dir" || fatal "Nao foi possivel criar $versions_dir"
    local tmp
    tmp="$(mktemp -d "$versions_dir/.install-XXXXXX")" || fatal "Falha ao criar diretorio temporario."
    _tmp_root="$tmp"   # removido pela trap EXIT (inclusive nos caminhos de fatal).

    if ! ui_download "$M_URL" "$tmp/nuclear.zip" "$M_SIZE" "$APP_TITLE"; then
        fatal "Falha no download do Nuclear.

Verifique sua conexao e tente novamente."
    fi

    if [ -n "$M_SHA256" ]; then
        local got
        got="$(sha256sum "$tmp/nuclear.zip" | awk '{print $1}')"
        if [ "$got" != "$M_SHA256" ]; then
            fatal "O arquivo baixado esta corrompido (checksum nao confere).

Rode o instalador de novo; se persistir, avise o suporte."
        fi
    fi

    unzip -q "$tmp/nuclear.zip" -d "$tmp/x" || fatal "Falha ao extrair o pacote."

    # Acha a pasta que contem o binario 'blender' dentro do zip.
    local src
    src="$(dirname "$(find "$tmp/x" -name blender -type f | head -n1)")"
    [ -n "$src" ] && [ -d "$src" ] || fatal "Pacote invalido: binario 'blender' nao encontrado."

    mv "$src" "$INSTALL_DIR" || fatal "Falha ao mover a instalacao para $INSTALL_DIR"

    # Carimba a versao (o auto-update le isto para saber o build atual).
    printf '%s' "$MANIFEST" > "$INSTALL_DIR/nuclear_version.json"

    rm -rf "$tmp"; _tmp_root=""   # sucesso: limpa o staging agora.
}

# Troca o symlink 'current' e cria o atalho .desktop + MIME. Recebe o prefixo de
# ambiente do Exec (para o opt-out de telemetria).
finalize_desktop() {  # exec_prefix
    local exec_prefix="$1"
    local current_link="$BASE_DIR/current"
    ln -sfn "$INSTALL_DIR" "$current_link"

    local desktop_file="$HOME/.local/share/applications/Nuclear.desktop"
    mkdir -p "$(dirname "$desktop_file")"
    local icon="$current_link/blender.svg"
    [ -f "$icon" ] || icon="blender"
    cat > "$desktop_file" <<EOF
[Desktop Entry]
Name=Nuclear
GenericName=2D Animation
Exec=${exec_prefix}$current_link/blender %F
Icon=$icon
Type=Application
Categories=Graphics;2DGraphics;
MimeType=application/x-nuclear;application/x-blender;
StartupNotify=true
StartupWMClass=Nuclear
Terminal=false
EOF
    update-desktop-database "$(dirname "$desktop_file")" >/dev/null 2>&1 || true

    # Registra o tipo MIME 'application/x-nuclear' (extensao .nuc).
    local mime_pkg_dir="$HOME/.local/share/mime/packages"
    mkdir -p "$mime_pkg_dir"
    cat > "$mime_pkg_dir/nuclear.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="application/x-nuclear">
    <comment>Nuclear scene</comment>
    <glob pattern="*.nuc"/>
  </mime-type>
</mime-info>
EOF
    update-mime-database "$HOME/.local/share/mime" >/dev/null 2>&1 || true
}

# Addons externos (opcional; mesma logica do instalador legado).
install_addons() {
    local addons_dir="$HOME/.config/blender/$M_VERSION/scripts/addons"
    mkdir -p "$addons_dir"
    local tmp_a; tmp_a="$(mktemp -d)"
    if _downloader "$ADDONS_DOWNLOAD_URL" "$tmp_a/addons.zip"; then
        if unzip -q "$tmp_a/addons.zip" -d "$tmp_a/x" 2>/dev/null; then
            cp -r "$tmp_a/x"/* "$addons_dir/" 2>/dev/null || true
        fi
    fi
    rm -rf "$tmp_a"
}

# =============================================================================
# Fluxo do wizard
# =============================================================================

main() {
    detect_ui
    detect_qdbus

    # 1. Boas-vindas.
    ui_confirm "$APP_TITLE" "Bem-vindo ao instalador do Nuclear.

O Nuclear e um aplicativo de animacao 2D. Ele sera instalado inteiramente no seu diretorio pessoal (sem senha de administrador). Depois disso, as atualizacoes acontecem sozinhas dentro do aplicativo.

Deseja continuar?" || { ui_info "$APP_TITLE" "Instalacao cancelada."; exit 0; }

    # 2. Pre-checagem de ferramentas e permissao.
    preflight

    # 3. Local de instalacao (seletor grafico de pasta, comecando em Inicio).
    #    Pulado se o usuario ja fixou o destino com --dir.
    if [ "$ASSUME_YES" != "1" ] && [ "$DIR_SET" != "1" ]; then
        BASE_DIR="$(ui_pickdir "Onde deixar o Nuclear? (sera criada uma pasta 'Nuclear' no local escolhido)" \
                               "Onde instalar o Nuclear?" "$HOME")"
    fi

    # 4. Ler manifesto e checar espaco.
    read_manifest
    check_space

    # 5. Confirmar versao/tamanho.
    local size_mb="?"
    [ "$M_SIZE" -gt 0 ] 2>/dev/null && size_mb=$(awk "BEGIN{printf \"%.0f\", $M_SIZE/1048576}")
    ui_confirm "$APP_TITLE" "Pronto para instalar:

  Versao: Nuclear $M_VERSION (build $M_BUILD)
  Download: ${size_mb} MB
  Pasta: $BASE_DIR

Iniciar o download e a instalacao?" || { ui_info "$APP_TITLE" "Instalacao cancelada."; exit 0; }

    # 6. Consentimento de telemetria (a menos que ja tenha vindo --no-telemetry).
    if [ "$TELEMETRY_OFF" != "1" ]; then
        if ui_confirm "$APP_TITLE" "Telemetria de presenca

O Nuclear pode avisar o estudio de que esta maquina esta online (nome do computador, usuario do sistema e versao). NAO coleta dados pessoais nem conteudo dos seus arquivos, e nunca bloqueia nada.

Deseja MANTER a telemetria de presenca ligada?"; then
            TELEMETRY_OFF=0
        else
            TELEMETRY_OFF=1
        fi
    fi
    local exec_prefix=""
    [ "$TELEMETRY_OFF" = "1" ] && exec_prefix="env NUCLEAR_TELEMETRY_OFF=1 "

    # 7. Download + verificacao + extracao + layout versionado.
    do_install

    # 8. Symlink 'current' + atalho + MIME.
    finalize_desktop "$exec_prefix"

    # 9. Addons externos (best-effort).
    install_addons

    # 10. Concluir e oferecer abrir.
    local done_msg="Instalacao concluida.

  Nuclear:  $INSTALL_DIR
  Atalho:   menu de aplicativos (\"Nuclear\")
  Telemetria: $([ "$TELEMETRY_OFF" = "1" ] && echo "desligada" || echo "ligada")"

    if ui_confirm "$APP_TITLE" "$done_msg

Deseja abrir o Nuclear agora?"; then
        ( setsid "$BASE_DIR/current/blender" >/dev/null 2>&1 & ) 2>/dev/null || \
            ( "$BASE_DIR/current/blender" >/dev/null 2>&1 & )
    else
        ui_info "$APP_TITLE" "$done_msg"
    fi
}

main
