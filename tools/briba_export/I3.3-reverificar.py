#!/usr/bin/env python3
"""
I3.3 — reverifica um lote já convertido, **sem o Nuclear**.

Converter o acervo custa uma noite de estação, e a maior parte dessa noite é o
Nuclear abrindo `.blend`. Mas só a primeira etapa da verificação precisa dele:
extrair a árvore do arquivo de origem. As outras três — reler o `.brb`, comparar
e escrever o relatório — são Python puro, e o lote **já guardou** a árvore do
Nuclear em `arvores/<base>.json`.

Então toda vez que o leitor, o comparador ou o relatório mudam, dá para cobrar a
mudança contra o acervo inteiro em minutos, em vez de repetir a noite. Sem isso
a tentação é medir o conserto em cinco arquivos de referência e presumir o resto
— e o acervo é justamente onde mora o caso que ninguém imaginou.

O que ele NÃO faz: reconverter. Se o exportador mudou, a árvore do `.brb` muda e
aí a noite é inevitável. Este roteiro serve para mudança na régua, não na peça.

Uso:

  ./I3.3-reverificar.py ~/lote-brb-acervo-v4
  ./I3.3-reverificar.py ~/lote-brb-acervo-v4 --so 20      # amostra, para olhar
  ./I3.3-reverificar.py ~/lote-brb-acervo-v4 --diff       # só o que mudou

Sai 0 quando nenhum arquivo piorou de veredito em relação ao registro do lote.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
LER_BRB = str(RAIZ / "I3.4-ler-brb.py")
COMPARAR = str(RAIZ / "I3.4-comparar.py")
FIDELIDADE = str(RAIZ / "I3.2-relatorio-fidelidade.py")

# Do melhor para o pior, a mesma ordem do I3.2. Serve para dizer se um arquivo
# MELHOROU ou PIOROU, que é a única pergunta que importa numa reverificação.
ORDEM = ["CONVERTIDO LIMPO", "CONVERTIDO COM PERDA DECLARADA",
         "PRECISA DE OLHO HUMANO", "REPROVADO — PERDA CALADA",
         "REPROVADO — FALHA DE CONVERSÃO"]


def rank(v):
    try:
        return ORDEM.index(v)
    except ValueError:
        return len(ORDEM)


def rodar(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode


def uma(base, dirs):
    brb = dirs["brb"] / f"{base}.brb"
    arv_nuc = dirs["arvores"] / f"{base}.json"
    arv_brb = dirs["arvores"] / f"{base}.brb.json"
    cmp_json = dirs["comparacoes"] / f"{base}.json"

    if not brb.exists():
        return None, "o `.brb` não está mais na pasta"
    if not arv_nuc.exists():
        # Sem a árvore do Nuclear não há com o que comparar, e inventar uma
        # comparação vazia devolveria um verde que não significa nada.
        return None, "sem árvore do Nuclear — precisa da rodada com o Nuclear"

    if rodar([sys.executable, LER_BRB, str(brb), str(arv_brb)]) != 0:
        return "REPROVADO — FALHA DE CONVERSÃO", "o `.brb` saiu ilegível na releitura"

    rodar([sys.executable, COMPARAR, str(arv_nuc), str(arv_brb), str(cmp_json)])

    cmd = [sys.executable, FIDELIDADE, "arquivo", "--brb", str(brb),
           "--base", base, "--saida-dir", str(dirs["fidelidade"]),
           "--arvore-nuclear", str(arv_nuc), "--arvore-brb", str(arv_brb)]
    if cmp_json.exists():
        cmd += ["--comparacao", str(cmp_json)]
    rodar(cmd)

    fid = dirs["fidelidade"] / f"{base}-fidelidade.json"
    if not fid.exists():
        return None, "o relatório não foi escrito"
    try:
        return json.loads(fid.read_text(encoding="utf-8")).get("veredito"), None
    except (json.JSONDecodeError, OSError) as e:
        return None, f"relatório ilegível — {type(e).__name__}"


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("saida", help="a pasta de saída de uma rodada do I3.3")
    ap.add_argument("--so", type=int, help="reverifica só os N primeiros")
    ap.add_argument("--diff", action="store_true",
                    help="lista só os arquivos cujo veredito mudou")
    args = ap.parse_args()

    raiz = Path(args.saida)
    dirs = {n: raiz / n for n in
            ("brb", "arvores", "comparacoes", "fidelidade", "logs")}
    registro = raiz / "lote-registro.jsonl"
    if not registro.exists():
        sys.exit(f"[I3.3r] {registro} não existe — isto não é saída de lote")

    antes = {}
    for linha in registro.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if r.get("base"):
            antes[r["base"]] = r.get("veredito")

    bases = sorted(antes)
    if args.so:
        bases = bases[:args.so]

    mudou, piorou, melhorou, sem_verificar = [], [], [], []
    for i, base in enumerate(bases, 1):
        v, motivo = uma(base, dirs)
        v0 = antes.get(base)
        if v is None:
            sem_verificar.append((base, motivo))
            print(f"[{i}/{len(bases)}] {base}: não reverificado — {motivo}")
            continue
        if v != v0:
            mudou.append((base, v0, v))
            (piorou if rank(v) > rank(v0) else melhorou).append(base)
            print(f"[{i}/{len(bases)}] {base}: {v0} -> {v}")
        elif not args.diff:
            print(f"[{i}/{len(bases)}] {base}: {v}")

    print(f"\n[I3.3r] {len(bases)} arquivo(s): {len(mudou)} mudaram de veredito "
          f"({len(melhorou)} melhoraram, {len(piorou)} pioraram), "
          f"{len(sem_verificar)} não deu para reverificar.")
    if piorou:
        print("       pioraram: " + ", ".join(piorou[:20])
              + (" …" if len(piorou) > 20 else ""))
    # Não reverificar não é o mesmo que reprovar: um arquivo sem árvore do
    # Nuclear é lacuna de cobertura, e some em silêncio se não for dito.
    if sem_verificar:
        print(f"       sem cobertura: {len(sem_verificar)} — "
              "estes continuam valendo o que o lote disse")
    return 1 if piorou else 0


if __name__ == "__main__":
    sys.exit(main())
