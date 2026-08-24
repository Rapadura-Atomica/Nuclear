#!/usr/bin/env bash
# I3.4 — autoteste do arnês de comparação.
#
# Um arnês que nunca ficou verde pode ter um defeito que o faz reprovar sempre,
# e aí ele reprovaria também o exportador certo. Um que nunca ficou vermelho
# pode estar aprovando qualquer coisa. Este roteiro exercita os dois lados,
# usando um `.brb` de fixture montado a partir da própria árvore:
#
#   caminho verde     .brb que casa com a árvore  -> tem de PASSAR
#   caminho vermelho  .brb estragado de propósito -> tem de REPROVAR
#
# Não testa o exportador do I3.1 (que não existe). Testa o teste.
#
# Uso: ./I3.4-autoteste.sh
set -uo pipefail

RAIZ="$(cd "$(dirname "$0")" && pwd)"
TMP="${TMPDIR:-/tmp}/i34-autoteste"
ARVORES="$RAIZ/I3.4-arvores"
rm -rf "$TMP"; mkdir -p "$TMP"

falhas=0; testes=0

verde() {
  local nome="$1" arv="$2"
  testes=$((testes+1))
  python3 "$RAIZ/I3.4-fixture-brb-falso.py" "$arv" "$TMP/$nome.brb" >/dev/null 2>&1
  python3 "$RAIZ/I3.4-ler-brb.py" "$TMP/$nome.brb" "$TMP/$nome.json" >/dev/null 2>&1
  if python3 "$RAIZ/I3.4-comparar.py" "$arv" "$TMP/$nome.json" >"$TMP/$nome.out" 2>&1; then
    printf '  verde   %-28s PASSOU\n' "$nome"
  else
    printf '  verde   %-28s FALHOU — devia passar\n' "$nome"
    sed -n '1,4p' "$TMP/$nome.out" | sed 's/^/            /'
    falhas=$((falhas+1))
  fi
}

vermelho() {
  local nome="$1" arv="$2" defeito="$3"
  testes=$((testes+1))
  python3 "$RAIZ/I3.4-fixture-brb-falso.py" "$arv" "$TMP/$nome-$defeito.brb" \
          --degradar "$defeito" >/dev/null 2>&1
  python3 "$RAIZ/I3.4-ler-brb.py" "$TMP/$nome-$defeito.brb" \
          "$TMP/$nome-$defeito.json" >/dev/null 2>&1
  if python3 "$RAIZ/I3.4-comparar.py" "$arv" "$TMP/$nome-$defeito.json" \
       >"$TMP/$nome-$defeito.out" 2>&1; then
    printf '  vermelho %-27s NÃO PEGOU o defeito `%s`\n' "$nome" "$defeito"
    falhas=$((falhas+1))
  elif ! grep -q 'REPROVOU' "$TMP/$nome-$defeito.out"; then
    # Saída não-zero não basta: um traceback também sai não-zero, e aí o teste
    # ficaria verde porque TUDO quebrou. O que conta é o comparador ter emitido
    # o veredito de reprovação.
    printf '  vermelho %-27s QUEBROU em vez de reprovar `%s`\n' "$nome" "$defeito"
    sed -n '1,4p' "$TMP/$nome-$defeito.out" | sed 's/^/            /'
    falhas=$((falhas+1))
  else
    local motivo
    motivo=$(sed -n '2p' "$TMP/$nome-$defeito.out" | tr -s ' ' | cut -c1-64)
    printf '  vermelho %-27s pegou `%s` →%s\n' "$nome" "$defeito" "$motivo"
  fi
}

# Árvore que não existe não pode virar teste pulado em silêncio: o roteiro é
# rodado tanto do repositório (árvores anonimizadas `ref-*`) quanto da estação
# (árvores do acervo, com outro nome), e um nome errado deixaria metade do
# caminho vermelho sem rodar sem dizer nada.
exige() {
  if [ ! -f "$1" ]; then
    printf '  AUSENTE %s — o caminho vermelho não pôde rodar\n' "${1:-(sem árvore)}"
    testes=$((testes+1)); falhas=$((falhas+1))
    return 1
  fi
}

echo "── caminho verde: o .brb casa com a árvore"
for a in "$ARVORES"/*.json; do
  verde "$(basename "${a%.json}")" "$a"
done

echo
echo "── caminho vermelho: defeito injetado de propósito"
# cada defeito precisa de um arquivo que tenha o recurso correspondente:
# `espera` só existe onde há quadro em espera, e só a ref-04 tem.
SIMPLES="$ARVORES/ref-03-pegrig-linha-fill-pt.json"
RICA="$ARVORES/ref-04-pegrig-completo.json"

# Rodando da estação as árvores são as do acervo, com outro nome. Cai na mais
# simples e na mais rica que existirem, em vez de pular o caminho vermelho.
if [ ! -f "$SIMPLES" ] || [ ! -f "$RICA" ]; then
  menor=""; maior=""
  for a in "$ARVORES"/*.json; do
    [ -f "$a" ] || continue
    if [ -z "$menor" ] || [ "$a" -ot "$menor" ] 2>/dev/null; then :; fi
    if [ -z "$menor" ] || [ "$(stat -c%s "$a")" -lt "$(stat -c%s "$menor")" ]; then menor="$a"; fi
    if [ -z "$maior" ] || [ "$(stat -c%s "$a")" -gt "$(stat -c%s "$maior")" ]; then maior="$a"; fi
  done
  [ -f "$SIMPLES" ] || SIMPLES="$menor"
  [ -f "$RICA" ] || RICA="$maior"
  printf '  (árvores de referência não encontradas pelo nome; usando %s e %s)\n' \
         "$(basename "${SIMPLES:-nenhuma}")" "$(basename "${RICA:-nenhuma}")"
fi

if exige "$SIMPLES"; then
  vermelho simples "$SIMPLES" tracos
  vermelho simples "$SIMPLES" cor
  vermelho simples "$SIMPLES" ordem
fi
if exige "$RICA"; then
  vermelho rica "$RICA" espera
  vermelho rica "$RICA" tracos
fi

echo
echo "-- perda calada: o .brb perde algo e NAO declara"
# Mascara de camada nao sobrevive aos niveis 1 e 2 — a perda e inevitavel e,
# declarada, passa. O que nao pode passar e a perda CALADA. Este caso remove o
# relatorio de fidelidade de um .brb correto e cobra que o comparador reprove.
# O caso da perda calada nasce do FIXTURE, não do exportador real: assim o
# autoteste roda no CI, onde não há Nuclear nem acervo. O fixture escreve
# mascaras.json e o relatório; tirar o relatório produz exatamente o arquivo
# que perde sem declarar.
arv_mascara="$RICA"
if exige "$arv_mascara"; then
  testes=$((testes+1))
  python3 "$RAIZ/I3.4-fixture-brb-falso.py" "$arv_mascara" "$TMP/base-mudo.brb" >/dev/null 2>&1
  python3 "$RAIZ/I3.4-tirar-relatorio.py" "$TMP/base-mudo.brb" "$TMP/mudo.brb" >/dev/null 2>&1
  python3 - "$TMP/mudo.brb" "$TMP/mudo2.brb" << 'TIRA' >/dev/null 2>&1
import sys, zipfile
zi = zipfile.ZipFile(sys.argv[1])
with zipfile.ZipFile(sys.argv[2], "w", zipfile.ZIP_STORED) as zo:
    for n in zi.namelist():
        if n != "mascaras.json":
            zo.writestr(n, zi.read(n))
TIRA
  python3 "$RAIZ/I3.4-ler-brb.py" "$TMP/mudo2.brb" "$TMP/mudo.json" >/dev/null 2>&1
  if python3 "$RAIZ/I3.4-comparar.py" "$arv_mascara" "$TMP/mudo.json" >"$TMP/mudo.out" 2>&1; then
    printf '  vermelho %-27s NAO PEGOU a perda calada de mascara\n' "caro"
    falhas=$((falhas+1))
  else
    printf '  vermelho %-27s pegou perda calada de mascara\n' "caro"
  fi
fi

echo
if [ "$falhas" -eq 0 ]; then
  echo "OK — $testes testes, nenhuma falha. O arnês passa quando deve e reprova quando deve."
else
  echo "FALHOU — $falhas de $testes testes. O arnês não é confiável enquanto isto não fechar."
fi
exit $((falhas > 0))
