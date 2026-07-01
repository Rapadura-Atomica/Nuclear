#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Rapadura Atômica
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Deploy assistido do relatório de falha (crash report) do Nuclear.
#
# Por que um script para VOCÊ rodar, e não o Claude: o deploy toca o host de
# PRODUÇÃO (araga286). O harness do Claude bloqueia escrever código em produção
# sem um prompt interativo, então as ações no servidor saem da SUA mão.
#
# Uso:
#   bash tools/nuclear_telemetry/deploy_crash.sh
#
# Pré-requisitos: o alias SSH `araga286` configurado, e estar na raiz do fork
# (a pasta com tools/ e scripts/). Cada fase pede confirmação; pode pular as que
# não quiser. NÃO faz rebuild sozinho — a Frente B chama o nuclear_release.sh.

set -uo pipefail

SSH_HOST="araga286"
# Caminho ABSOLUTO no servidor (o home é /home1/araga286; scp novo não expande $HOME
# nem ~, então nada de variáveis aqui). É onde já vive o ping.php.
REMOTE="/home1/araga286/public_html/addon/rapaduraatomica/nuclear/nuclear-api"
TOKEN="6a50f72f178f5c02b526418301fea046"
BASE_URL="https://rapaduraatomica.com.br/nuclear/nuclear-api"

# Multiplexação SSH: abre UMA conexão-mestra e reusa em todos os comandos, então
# você digita a senha uma única vez.
CTL="$HOME/.ssh/cm-nuclear-%h-%p-%r"
SSHOPTS=(-o ControlMaster=auto -o "ControlPath=$CTL" -o ControlPersist=180)
sshx()  { ssh "${SSHOPTS[@]}" "$SSH_HOST" "$@"; }
scpx()  { scp "${SSHOPTS[@]}" "$@"; }

here="$(cd "$(dirname "$0")/../.." && pwd)"   # raiz do fork
cd "$here" || { echo "não achei a raiz do fork"; exit 1; }

say()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32mok\033[0m %s\n' "$*"; }
warn() { printf '   \033[33m!!\033[0m %s\n' "$*"; }
ask()  { read -r -p "   $1 [s/N] " a; [ "$a" = s ] || [ "$a" = S ]; }

require() { [ -f "$1" ] || { echo "faltando: $1"; exit 1; }; }
require tools/nuclear_telemetry/server/crash.php
require scripts/startup/nuclear_crash_report.py

cleanup() { ssh "${SSHOPTS[@]}" -O exit "$SSH_HOST" 2>/dev/null; }
trap cleanup EXIT

# ---------------------------------------------------------------------------
say "0) Abrir conexão SSH (senha só desta vez) e conferir o diretório"
if ! sshx "echo CONNECTED && test -d '$REMOTE' && echo DIR_OK && ls -la '$REMOTE'/ping.php 2>/dev/null | head -1"; then
    warn "SSH falhou ou o diretório $REMOTE não existe."
    ask "Criar o diretório (mkdir -p) e continuar?" && sshx "mkdir -p '$REMOTE'" || { echo "abortado"; exit 1; }
fi

# ---------------------------------------------------------------------------
say "FRENTE A — endpoint crash.php (arquivo NOVO, não sobrescreve nada)"
if ask "Subir crash.php para $REMOTE/ ?"; then
    if scpx tools/nuclear_telemetry/server/crash.php "$SSH_HOST:$REMOTE/crash.php"; then
        ok "enviado"
    else
        warn "scp falhou — veja a mensagem acima"
    fi

    say "A.1) Lint no servidor"
    sshx "php -l '$REMOTE/crash.php'" || warn "lint reprovou — confira antes de seguir"

    say "A.2) Smoke test (espera {\"ok\":true})"
    resp=$(curl -sS -X POST "$BASE_URL/crash.php" \
        -H 'Content-Type: application/json' \
        -H "X-Nuclear-Token: $TOKEN" \
        -H 'User-Agent: Nuclear-CrashReport/1.0' \
        -d '{"machine_id":"smoke123def","studio":"Teste Deploy","description":"smoke test do deploy","version":"Nuclear 1.4.2 (Beta)","hostname":"deploy-check","crashed_at":"2026-06-30T21:00:00+00:00","blender_log":"backtrace de teste"}')
    printf '   resposta: %s\n' "$(printf '%s' "$resp" | head -c 200)"
    printf '%s' "$resp" | grep -q '"ok"[[:space:]]*:[[:space:]]*true' && ok "endpoint respondeu ok" || warn "não veio {\"ok\":true} — confira o token / caminho / erro do PHP"

    say "A.3) Confere o .txt gravado na pasta protegida"
    sshx "ls -la '$REMOTE/data/crashes/' 2>&1 | tail -5; echo '--- conteúdo ---'; cat '$REMOTE'/data/crashes/*Teste-Deploy* 2>/dev/null | head -30"

    say "A.4) A pasta NÃO pode ser servida pela web (espera 403)"
    code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/data/crashes/")
    if [ "$code" = 403 ] || [ "$code" = 401 ]; then ok "negado pela web ($code)"; else warn "ESPERAVA 403, veio $code — o .htaccess não pegou!"; fi

    say "A.5) Remove o arquivo de teste"
    sshx "rm -f '$REMOTE'/data/crashes/*Teste-Deploy*" && ok "limpo"
else
    warn "Frente A pulada"
fi

# ---------------------------------------------------------------------------
say "FRENTE S — segurança pendente (admin.php novo + ping.php endurecido)"
warn "ping.php SOBRESCREVE código em produção: backup é feito antes."
if ask "Subir admin.php + ping.php agora?"; then
    ts=$(date -u +%Y%m%d-%H%M%S)
    sshx "cd '$REMOTE' && { [ -f ping.php ] && cp -n ping.php ping.php.bak-$ts; [ -f admin.php ] && cp -n admin.php admin.php.bak-$ts; }; echo backup-ok"
    scpx tools/nuclear_telemetry/server/admin.php "$SSH_HOST:$REMOTE/admin.php" && ok "admin.php enviado"
    scpx tools/nuclear_telemetry/server/ping.php  "$SSH_HOST:$REMOTE/ping.php"  && ok "ping.php enviado"
    sshx "php -l '$REMOTE/admin.php'; php -l '$REMOTE/ping.php'" || warn "lint reprovou"
    cat <<'EOF'
   AÇÃO MANUAL OBRIGATÓRIA — defina o segredo de admin SÓ no ambiente e rotacione
   o antigo (9e3b147a… vazou no Git). Em hospedagem compartilhada, no .htaccess do
   nuclear-api/ (ou painel da HostGator):
       SetEnv NUCLEAR_ADMIN_TOKEN "uma-senha-forte-nova"
   Sem isso, /admin responde 503 (fail-closed) — de propósito.
EOF
else
    warn "Frente S pulada"
fi

# ---------------------------------------------------------------------------
say "FRENTE B — distribuir o cliente (rebuild + repackage + publish)"
warn "Isto é um RELEASE: bump de NUCLEAR_BUILD, ~20 min de build no container, e"
warn "publica nuclear.zip + version.json (afeta o auto-update de TODAS as máquinas)."
echo  "   Recomendado (feature nova = MINOR):"
echo  "     tools/nuclear_release.sh minor --build \\"
echo  "       --notes \"Relatório de falha: após fechamento inesperado, o Nuclear oferece enviar um log no próximo boot.\""
echo
if ask "Disparar o release agora?"; then
    tools/nuclear_release.sh minor --build \
      --notes "Relatório de falha: após um fechamento inesperado, o Nuclear oferece no próximo boot enviar um log de crash (estúdio + descrição). Nenhum .blend é enviado."
else
    warn "Release não disparado — rode o comando acima quando quiser."
fi

say "Fim. Endpoint no ar = clientes já podem reportar assim que receberem o build novo."
