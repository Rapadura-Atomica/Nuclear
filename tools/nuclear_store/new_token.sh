#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Gera um token de cliente e o adiciona ao tokens.json do servidor (via ssh).
#
#   tools/nuclear_store/new_token.sh "Estudio X" meu-addon.zip outro.zip
#   tools/nuclear_store/new_token.sh "Estudio X" '*'                # tudo
#   NUCLEAR_STORE_EXPIRES=2027-01-01 tools/nuclear_store/new_token.sh "Estudio X" '*'
#
# Imprime o token UMA vez (entregue ao cliente por canal seguro). O tokens.json
# vive fora da web (paid/ tem .htaccess deny) e nunca e commitado no repo.
set -euo pipefail

HOST="${NUCLEAR_STORE_HOST:-araga286}"
REMOTE_JSON="~/public_html/addon/rapaduraatomica/estacao/paid/tokens.json"
CLIENT="${1:?uso: new_token.sh \"Nome do Cliente\" addon1.zip [addon2.zip ...] | '*'}"
shift
[ $# -ge 1 ] || { echo "erro: informe ao menos um addon (ou '*')" >&2; exit 1; }

TOKEN="$(head -c 32 /dev/urandom | sha256sum | cut -c1-48)"

if [ "$1" = "*" ]; then ADDONS='"*"'
else
  ADDONS="$(printf '%s\n' "$@" | python3 -c 'import json,sys; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))')"
fi
EXPIRES_KV=""
[ -n "${NUCLEAR_STORE_EXPIRES:-}" ] && EXPIRES_KV=", \"expires\": \"$NUCLEAR_STORE_EXPIRES\""

# shellcheck disable=SC2029
ssh "$HOST" "python3 - <<PYEOF
import json, os
p = os.path.expanduser('$REMOTE_JSON')
os.makedirs(os.path.dirname(p), exist_ok=True)
data = {}
if os.path.exists(p):
    with open(p) as f:
        data = json.load(f)
data['$TOKEN'] = json.loads('{\"client\": \"$CLIENT\", \"addons\": $ADDONS$EXPIRES_KV}')
tmp = p + '.tmp'
with open(tmp, 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
os.replace(tmp, p)
print('tokens no arquivo:', len(data))
PYEOF"

echo
echo "== token gerado para: $CLIENT =="
echo "$TOKEN"
echo
echo "teste:  curl -H 'X-Nuclear-Token: $TOKEN' -A 'Nuclear-Store/1.0' \\"
echo "          https://rapaduraatomica.com.br/estacao/paid.php"
