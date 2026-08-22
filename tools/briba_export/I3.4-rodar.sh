#!/usr/bin/env bash
# I3.4 — laço de verificação do exportador `.brb`.
#
# Para cada arquivo de referência:
#   1. extrai a árvore canônica do lado do Nuclear
#   2. exporta para `.brb`          (I3.1 — ainda não existe)
#   3. lê o `.brb` de volta
#   4. compara as duas árvores e emite veredito
#
# Enquanto o I3.1 não existir, o passo 2 falha e o roteiro reprova. **Isso é o
# comportamento correto**: o teste nasce vermelho, e é ele que diz quando o
# exportador passou a funcionar — em vez de alguém decidir isso no olho.
#
# Uso:  ./I3.4-rodar.sh [dir-de-saida]
# Sai 0 se todas as referências passarem, 1 se qualquer uma reprovar.
set -uo pipefail

RAIZ="$(cd "$(dirname "$0")" && pwd)"
SAIDA="${1:-$RAIZ/I3.4-resultado}"
NUCLEAR="${NUCLEAR_BIN:-$HOME/Nuclear/current/nuclear}"
LISTA="$RAIZ/I3.4-referencias.txt"
EXPORTADOR="${EXPORTADOR_BRB:-$RAIZ/I3.1-exportar-brb.py}"

mkdir -p "$SAIDA/arvores" "$SAIDA/brb" "$SAIDA/relatorios"
LOG="$SAIDA/_execucao.log"; : > "$LOG"

total=0; passou=0; reprovou=0; sem_exportador=0

while IFS= read -r arq; do
  [ -n "$arq" ] || continue
  total=$((total+1))
  base="$(basename "${arq%.*}")"
  echo "── $base" | tee -a "$LOG"

  # 1. árvore do lado do Nuclear
  if ! timeout 600 "$NUCLEAR" -b "$arq" -P "$RAIZ/I3.4-arvore-canonica.py" \
        -- "$SAIDA/arvores/$base.json" >>"$LOG" 2>&1; then
    echo "   ERRO ao extrair a árvore (o Nuclear caiu ou o arquivo não abriu)" | tee -a "$LOG"
    reprovou=$((reprovou+1)); continue
  fi

  # 2. exportar — o passo que ainda não existe
  if [ ! -f "$EXPORTADOR" ]; then
    echo "   PENDENTE: exportador não encontrado em $EXPORTADOR (I3.1 não implementado)" | tee -a "$LOG"
    sem_exportador=$((sem_exportador+1)); continue
  fi
  if ! timeout 600 "$NUCLEAR" -b "$arq" -P "$EXPORTADOR" \
        -- "$SAIDA/brb/$base.brb" >>"$LOG" 2>&1; then
    echo "   ERRO na exportação" | tee -a "$LOG"
    reprovou=$((reprovou+1)); continue
  fi

  # 3. ler o .brb de volta
  if ! python3 "$RAIZ/I3.4-ler-brb.py" "$SAIDA/brb/$base.brb" \
        "$SAIDA/arvores/$base.brb.json" >>"$LOG" 2>&1; then
    echo "   ERRO ao reabrir o .brb — o arquivo saiu ilegível" | tee -a "$LOG"
    reprovou=$((reprovou+1)); continue
  fi

  # 4. comparar
  if python3 "$RAIZ/I3.4-comparar.py" "$SAIDA/arvores/$base.json" \
       "$SAIDA/arvores/$base.brb.json" "$SAIDA/relatorios/$base.json" | tee -a "$LOG"; then
    passou=$((passou+1))
  else
    reprovou=$((reprovou+1))
  fi
done < "$LISTA"

echo
printf 'FIM %d referências: %d passaram, %d reprovaram, %d sem exportador\n' \
  "$total" "$passou" "$reprovou" "$sem_exportador" | tee -a "$LOG"

# sem exportador ainda não é sucesso — é trabalho não feito
[ "$reprovou" -eq 0 ] && [ "$sem_exportador" -eq 0 ]
