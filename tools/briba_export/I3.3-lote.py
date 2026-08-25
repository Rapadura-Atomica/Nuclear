#!/usr/bin/env python3
"""
I3.3 — modo lote: converte o acervo inteiro numa noite, sem ninguém olhando.

O que o lote pede, literalmente: *converter o acervo inteiro em uma noite, sem
intervenção, com registro de erro por arquivo*. As três coisas puxam requisito:

  sem intervenção     nenhum arquivo pode parar a fila. Nuclear que cai, arquivo
                      que não abre, `.blend` corrompido, exportação que trava —
                      tudo vira linha no registro e a fila anda. O único jeito de
                      travar a noite é o processo do Nuclear pendurar, e por isso
                      cada arquivo tem prazo (`--prazo`, 10 min por padrão).
  em uma noite        um Nuclear por vez. Cada instância come RAM e o acervo tem
                      `.blend` de rig grande; dois em paralelo numa estação de
                      16 GB derrubam a noite inteira por falta de memória. O
                      padrão é serial, e `--paralelo` existe mas avisa.
  registro por erro   `lote-registro.jsonl`, uma linha por arquivo, gravada na
                      hora — não no fim. Se a estação reiniciar às 4h da manhã,
                      o que já rodou está no disco e `--continuar` retoma.

Uso:

  # o acervo inteiro, verificando cada conversão
  ./I3.3-lote.py --lista I3.4-referencias.txt --saida ~/lote-brb --verificar

  # uma pasta (varre `.blend` e `.nuc`, recursivo)
  ./I3.3-lote.py --dir ~/acervo/Projeto --saida ~/lote-brb

  # retomar a noite que caiu
  ./I3.3-lote.py --lista lista.txt --saida ~/lote-brb --continuar

Sai 0 quando todo arquivo converteu **e** (com `--verificar`) nenhum reprovou.
"""

import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent

EXPORTADOR  = os.environ.get("EXPORTADOR_BRB", str(RAIZ / "I3.1-exportar-brb.py"))
ARVORE      = str(RAIZ / "I3.4-arvore-canonica.py")
LER_BRB     = str(RAIZ / "I3.4-ler-brb.py")
COMPARAR    = str(RAIZ / "I3.4-comparar.py")
FIDELIDADE  = str(RAIZ / "I3.2-relatorio-fidelidade.py")
MINIATURA   = str(RAIZ / "I3.6-miniatura-brb.py")
NUCLEAR     = os.environ.get("NUCLEAR_BIN", str(Path.home() / "Nuclear/current/nuclear"))

# O catálogo da Montagem já se queimou com isto: filtrar só `*.blend` deixa de
# fora todo rig `.nuc`, que é a metade convertida do acervo.
EXTENSOES = (".blend", ".nuc")

# Cópia de conflito do Dropbox não é acervo — é decisão humana pendente (I0.2).
# O Dropbox marca conflito em três formatos no mesmo acervo, dependendo da
# língua do cliente que gravou.
TERMOS_PULAR = ("conflicted copy", "cópia em conflito", "conflitos entre maiúsculas")
RE_PULAR = re.compile(r"(\.blend\d+$)|(/\.Trash)|(/\.local/share/Trash/)", re.I)

parar = False


def _sinal(_s, _f):
    """Ctrl+C não mata a noite no meio: fecha o arquivo atual e grava tudo."""
    global parar
    parar = True
    print("\n[I3.3] pedido de parada recebido — terminando o arquivo atual e "
          "fechando o registro. `--continuar` retoma daqui.", flush=True)


# --------------------------------------------------------------------------- #

def descobrir(args):
    alvos = []
    for l in args.lista or []:
        for linha in Path(l).read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha and not linha.startswith("#"):
                alvos.append(Path(linha))
    for d in args.dir or []:
        for ext in EXTENSOES:
            alvos.extend(sorted(Path(d).rglob(f"*{ext}")))
    alvos.extend(Path(a) for a in args.arquivo or [])

    vistos, saida, pulados = set(), [], []
    for a in alvos:
        s = str(a)
        chave = str(a.resolve()) if a.exists() else s
        if chave in vistos:
            continue
        vistos.add(chave)
        low = s.lower()
        if RE_PULAR.search(s) or any(t in low for t in TERMOS_PULAR):
            pulados.append(s)
            continue
        if a.suffix.lower() not in EXTENSOES:
            pulados.append(s)
            continue
        saida.append(a)
    return saida, pulados


def rodar(cmd, prazo, log):
    """Roda e devolve (codigo, segundos). Nunca levanta por causa do filho."""
    t0 = time.monotonic()
    with open(log, "ab") as f:
        f.write(f"\n$ {' '.join(shlex.quote(c) for c in cmd)}\n".encode())
        f.flush()
        try:
            p = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT,
                               timeout=prazo, check=False)
            return p.returncode, time.monotonic() - t0
        except subprocess.TimeoutExpired:
            f.write(f"\n[I3.3] PRAZO ESTOURADO ({prazo}s)\n".encode())
            return "prazo", time.monotonic() - t0
        except OSError as e:
            f.write(f"\n[I3.3] não deu para executar: {e}\n".encode())
            return "erro-de-execucao", time.monotonic() - t0


def cauda(log, n=12):
    """Últimas linhas úteis do log — é o que vai no registro para triagem."""
    try:
        linhas = Path(log).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    uteis = [l for l in linhas if l.strip() and not l.startswith("$ ")]
    return uteis[-n:]


def base_de(caminho, usadas):
    """Nome curto único. Dois `personagem.blend` em pastas diferentes existem."""
    b = re.sub(r"[^\w.\-]+", "_", caminho.stem)
    if b not in usadas:
        usadas.add(b)
        return b
    pai = re.sub(r"[^\w\-]+", "_", caminho.parent.name)
    n, cand = 2, f"{pai}__{b}"
    while cand in usadas:
        cand = f"{pai}__{b}__{n}"
        n += 1
    usadas.add(cand)
    return cand


# --------------------------------------------------------------------------- #

def decidir(veredito, cod_cmp, cod_fid):
    """Situação do arquivo no lote. Devolve (situacao, motivo).

    Quem dá o veredito é o I3.2, não o código de saída do comparador.

    As duas camadas usam régua diferente de propósito: o comparador reprova
    qualquer perda observada, e o I3.2 sabe distinguir perda DECLARADA — que é
    limitação conhecida dos níveis 1 e 2 — de perda CALADA, que é o defeito.
    Enquanto esta decisão saía do código de saída, um arquivo com perda
    declarada aparecia como `REPROVOU` no resumo do lote e `PRECISA DE OLHO
    HUMANO` no relatório dele. Um relatório que se contradiz não serve para
    decidir nada, que é justamente o que o I3.2 existe para evitar.

    O sinal do comparador não some — fica em `comparador_reprovou`, para quem
    estiver depurando o arnês em vez de triando a conversão.
    """
    if veredito is None:
        # Sem relatório não há veredito, e aí o código de saída é tudo que há.
        if cod_fid != 0:
            return "REPROVOU", "o relatório de fidelidade não foi gerado"
        if cod_cmp != 0:
            return "REPROVOU", "a comparação reprovou"
        return "PASSOU", None
    if str(veredito).startswith("REPROVADO"):
        return "REPROVOU", veredito
    return "PASSOU", None


def converter(arq, base, dirs, args):
    """Um arquivo do começo ao fim. Devolve o registro dele."""
    log = dirs["logs"] / f"{base}.log"
    log.write_bytes(b"")
    reg = {"arquivo": str(arq), "base": base, "etapas": {}}
    try:
        reg["bytes_entrada"] = arq.stat().st_size
    except OSError:
        reg["bytes_entrada"] = None

    brb = dirs["brb"] / f"{base}.brb"

    # 1. exportar — a única etapa obrigatória
    cod, seg = rodar([NUCLEAR, "-b", str(arq), "-P", EXPORTADOR, "--", str(brb)],
                     args.prazo, log)
    reg["etapas"]["exportar"] = {"codigo": cod, "segundos": round(seg, 1)}
    if cod != 0 or not brb.exists():
        reg["situacao"] = "FALHOU"
        reg["motivo"] = ("prazo estourado" if cod == "prazo" else
                         "o Nuclear saiu com erro" if cod != 0 else
                         "o Nuclear saiu bem mas não gravou o `.brb`")
        reg["log"] = str(log)
        reg["ultimas_linhas"] = cauda(log)
        return reg
    reg["bytes_brb"] = brb.stat().st_size

    # 1.5. miniatura do container. O exportador roda DENTRO do Nuclear, onde não
    #      há Pillow, então a miniatura entra aqui, fora dele, como pós-passe.
    #      Roda mesmo sem `--verificar`: um container incompleto é incompleto do
    #      mesmo jeito, e sem esta etapa o defeito aparece no leitor do outro
    #      lado, não aqui.
    if not args.sem_miniatura:
        cod_min, seg = rodar([sys.executable, MINIATURA, str(brb),
                              "--sem-backup"], args.prazo, log)
        reg["etapas"]["miniatura"] = {"codigo": cod_min, "segundos": round(seg, 1)}

    if not args.verificar:
        reg["situacao"] = "CONVERTIDO"
        reg["motivo"] = "sem verificação independente (rode com --verificar)"
        return reg

    # 2. árvore canônica do lado do Nuclear
    arv_nuc = dirs["arvores"] / f"{base}.json"
    cod, seg = rodar([NUCLEAR, "-b", str(arq), "-P", ARVORE, "--", str(arv_nuc)],
                     args.prazo, log)
    reg["etapas"]["arvore"] = {"codigo": cod, "segundos": round(seg, 1)}

    # 3. reler o `.brb`
    arv_brb = dirs["arvores"] / f"{base}.brb.json"
    cod_ler, seg = rodar([sys.executable, LER_BRB, str(brb), str(arv_brb)],
                         args.prazo, log)
    reg["etapas"]["reler"] = {"codigo": cod_ler, "segundos": round(seg, 1)}
    if cod_ler != 0:
        reg["situacao"] = "CONVERTIDO SEM VERIFICAR"
        reg["motivo"] = "o `.brb` saiu ilegível na releitura"
        reg["log"] = str(log)
        reg["ultimas_linhas"] = cauda(log)
        return reg

    # 4. comparar — o veredito de conversão
    cmp_json = dirs["comparacoes"] / f"{base}.json"
    cod_cmp, seg = rodar([sys.executable, COMPARAR, str(arv_nuc), str(arv_brb),
                          str(cmp_json)], args.prazo, log)
    reg["etapas"]["comparar"] = {"codigo": cod_cmp, "segundos": round(seg, 1)}

    # 5. relatório de fidelidade (I3.2) — roda mesmo se a comparação reprovou;
    #    é justamente aí que ele tem mais o que dizer.
    cmd = [sys.executable, FIDELIDADE, "arquivo", "--brb", str(brb),
           "--base", base, "--saida-dir", str(dirs["fidelidade"])]
    if arv_nuc.exists():
        cmd += ["--arvore-nuclear", str(arv_nuc)]
    if arv_brb.exists():
        cmd += ["--arvore-brb", str(arv_brb)]
    if cmp_json.exists():
        cmd += ["--comparacao", str(cmp_json)]
    cod_fid, seg = rodar(cmd, args.prazo, log)
    reg["etapas"]["fidelidade"] = {"codigo": cod_fid, "segundos": round(seg, 1)}

    fid = dirs["fidelidade"] / f"{base}-fidelidade.json"
    if fid.exists():
        try:
            d = json.loads(fid.read_text(encoding="utf-8"))
            reg["veredito"] = d.get("veredito")
            reg["contagem"] = d.get("contagem")
        except (json.JSONDecodeError, OSError):
            pass

    # Quem dá o veredito é o I3.2, não o código de saída do comparador.
    #
    # As duas camadas usam régua diferente de propósito: o comparador reprova
    # qualquer perda observada, e o I3.2 sabe distinguir perda DECLARADA (que é
    # limitação conhecida do nível 1/2) de perda CALADA (que é o defeito). Antes
    # desta função ler o veredito, um arquivo com perda declarada saía marcado
    # `REPROVOU` no resumo do lote e `PRECISA DE OLHO HUMANO` no relatório dele
    # — e um relatório que se contradiz não serve para decidir nada, que é
    # justamente o que o I3.2 existe para evitar.
    #
    # O sinal do comparador não some: fica no registro, para quem estiver
    # depurando o arnês em vez de triando a conversão.
    reg["comparador_reprovou"] = cod_cmp != 0
    situacao, motivo = decidir(reg.get("veredito"), cod_cmp, cod_fid)
    reg["situacao"] = situacao
    if motivo:
        reg["motivo"] = motivo

    if reg["situacao"] == "REPROVOU":
        reg["log"] = str(log)
        reg["ultimas_linhas"] = cauda(log)
    return reg


# --------------------------------------------------------------------------- #

def resumo(registros, dirs, args, pulados, segundos):
    L, A = [], None
    A = L.append
    por = {}
    for r in registros:
        por.setdefault(r.get("situacao", "?"), []).append(r)

    A("# Conversão em lote — resumo")
    A("")
    A(f"{len(registros)} arquivo(s) em {segundos/60:.1f} min "
      f"({'com' if args.verificar else 'sem'} verificação independente).")
    A("")
    A("| Situação | Arquivos |")
    A("|---|---:|")
    for s in ("PASSOU", "CONVERTIDO", "CONVERTIDO SEM VERIFICAR", "REPROVOU",
              "FALHOU", "PULADO"):
        if por.get(s):
            A(f"| {s} | {len(por[s])} |")
    A("")

    if por.get("FALHOU"):
        A("## Não converteu")
        A("")
        A("Estes não geraram `.brb` nenhum. É a fila do I5.2.")
        A("")
        A("| Arquivo | Motivo | Log |")
        A("|---|---|---|")
        for r in por["FALHOU"]:
            A(f"| `{Path(r['arquivo']).name}` | {r.get('motivo','—')} "
              f"| `{r.get('log','—')}` |")
        A("")
        A("<details><summary>Últimas linhas de cada um</summary>")
        A("")
        for r in por["FALHOU"]:
            A(f"**`{Path(r['arquivo']).name}`**")
            A("")
            A("```")
            for l in r.get("ultimas_linhas", []):
                A(l)
            A("```")
            A("")
        A("</details>")
        A("")

    divergentes = [r for r in registros
                   if r.get("comparador_reprovou") and r.get("situacao") == "PASSOU"]
    if divergentes:
        A("## Passou com perda declarada")
        A("")
        A("O comparador viu diferença nestes arquivos e o relatório de fidelidade "
          "aceitou: é limitação conhecida dos níveis 1 e 2, declarada dentro do "
          "próprio `.brb`. Não é defeito — mas é o que o animador confere.")
        A("")
        A("| Arquivo | Veredito |")
        A("|---|---|")
        for r in divergentes[:40]:
            A(f"| [`{r['base']}`](fidelidade/{r['base']}-fidelidade.md) "
              f"| {r.get('veredito', '—')} |")
        if len(divergentes) > 40:
            A(f"| … e mais {len(divergentes) - 40} | |")
        A("")

    if por.get("REPROVOU"):
        A("## Converteu, mas reprovou na conferência")
        A("")
        A("| Arquivo | Veredito |")
        A("|---|---|")
        for r in por["REPROVOU"]:
            A(f"| [`{r['base']}`](fidelidade/{r['base']}-fidelidade.md) "
              f"| {r.get('veredito') or r.get('motivo','—')} |")
        A("")

    lentos = sorted((r for r in registros if r.get("etapas", {}).get("exportar")),
                    key=lambda r: -r["etapas"]["exportar"]["segundos"])[:5]
    if lentos:
        A("## Os cinco mais demorados")
        A("")
        A("Serve para dimensionar a noite quando o acervo inteiro entrar.")
        A("")
        A("| Arquivo | Exportação (s) | Entrada |")
        A("|---|---:|---:|")
        for r in lentos:
            mb = (r.get("bytes_entrada") or 0) / 1e6
            A(f"| `{r['base']}` | {r['etapas']['exportar']['segundos']:.1f} "
              f"| {mb:.1f} MB |")
        A("")

    if pulados:
        A("## Pulados de propósito")
        A("")
        A(f"{len(pulados)} caminho(s): cópia de conflito do Dropbox (decisão "
          f"humana do I0.2), backup `.blend1` e lixeira.")
        A("")
        A("<details><summary>Lista</summary>")
        A("")
        for p in pulados[:200]:
            A(f"- `{p}`")
        if len(pulados) > 200:
            A(f"- … e mais {len(pulados) - 200}")
        A("")
        A("</details>")
        A("")

    A("---")
    A("")
    A(f"Registro linha a linha: `{dirs['raiz'] / 'lote-registro.jsonl'}` · "
      f"log por arquivo em `{dirs['logs']}`")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lista", action="append", help="arquivo .txt com um caminho por linha")
    ap.add_argument("--dir", action="append", help="pasta a varrer (recursivo, .blend e .nuc)")
    ap.add_argument("--arquivo", action="append", help="um caminho avulso")
    ap.add_argument("--saida", required=True)
    ap.add_argument("--verificar", action="store_true",
                    help="extrai a árvore, relê o .brb, compara e gera o I3.2")
    ap.add_argument("--continuar", action="store_true",
                    help="pula o que já converteu numa rodada anterior")
    ap.add_argument("--prazo", type=int, default=600,
                    help="segundos por etapa antes de desistir do arquivo (padrão 600)")
    ap.add_argument("--limite", type=int, help="para depois de N arquivos (ensaio)")
    ap.add_argument("--so-listar", action="store_true",
                    help="mostra o que rodaria e sai")
    ap.add_argument("--sem-miniatura", action="store_true",
                    help="não gera `thumbnail.png` (o container sai incompleto)")
    args = ap.parse_args()

    if not (args.lista or args.dir or args.arquivo):
        ap.error("informe --lista, --dir ou --arquivo")

    # Perguntar agora, não no arquivo 1 de 384. Sem Pillow a miniatura não sai,
    # e o leitor cobra miniatura válida: a noite inteira sairia com o container
    # incompleto e o arnês reprovando o acervo por uma dependência ausente. Uma
    # linha aqui evita descobrir isso de manhã.
    if not args.sem_miniatura:
        try:
            import PIL                                            # noqa: F401
        except ImportError:
            sys.exit("[I3.3] Pillow não está instalado, e sem ele o `.brb` sai "
                     "sem miniatura — o container fica incompleto e o arnês "
                     "reprova.\n"
                     "       Instale o Pillow, ou rode com --sem-miniatura se "
                     "for de propósito.")

    alvos, pulados = descobrir(args)
    if args.limite:
        alvos = alvos[:args.limite]

    if args.so_listar:
        for a in alvos:
            print(a)
        print(f"\n[I3.3] {len(alvos)} a converter, {len(pulados)} pulados", file=sys.stderr)
        return 0

    raiz = Path(args.saida)
    dirs = {"raiz": raiz}
    for nome in ("brb", "logs", "arvores", "comparacoes", "fidelidade"):
        dirs[nome] = raiz / nome
        dirs[nome].mkdir(parents=True, exist_ok=True)

    registro = raiz / "lote-registro.jsonl"
    ja_feitos = set()
    if args.continuar and registro.exists():
        for linha in registro.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if r.get("situacao") in ("PASSOU", "CONVERTIDO"):
                ja_feitos.add(r.get("arquivo"))
        print(f"[I3.3] --continuar: {len(ja_feitos)} já convertido(s), pulando")

    if not Path(NUCLEAR).exists():
        print(f"[I3.3] ERRO: Nuclear não encontrado em {NUCLEAR} "
              f"(defina NUCLEAR_BIN)")
        return 2

    signal.signal(signal.SIGINT, _sinal)
    signal.signal(signal.SIGTERM, _sinal)

    registros, usadas = [], set()
    t0 = time.monotonic()
    fila = [a for a in alvos if str(a) not in ja_feitos]
    print(f"[I3.3] {len(fila)} arquivo(s) na fila · saída em {raiz}")

    with open(registro, "a", encoding="utf-8") as jl:
        for n, arq in enumerate(fila, 1):
            if parar:
                break
            base = base_de(arq, usadas)
            decorrido = time.monotonic() - t0
            eta = f" · resta ~{(decorrido/(n-1))*(len(fila)-n+1)/60:.0f} min" if n > 1 else ""
            print(f"[{n}/{len(fila)}] {base}{eta}", flush=True)

            if not arq.exists():
                r = {"arquivo": str(arq), "base": base, "situacao": "FALHOU",
                     "motivo": "o caminho não existe"}
            else:
                r = converter(arq, base, dirs, args)
            r["quando"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            jl.write(json.dumps(r, ensure_ascii=False) + "\n")
            jl.flush()
            os.fsync(jl.fileno())
            registros.append(r)
            print(f"      {r['situacao']}"
                  + (f" — {r.get('motivo')}" if r.get("motivo") else ""), flush=True)

    for p in pulados:
        registros.append({"arquivo": p, "situacao": "PULADO"})

    if args.verificar and any(r.get("situacao") in ("PASSOU", "REPROVOU")
                              for r in registros):
        subprocess.run([sys.executable, FIDELIDADE, "consolidar",
                        str(dirs["fidelidade"])], check=False)

    segundos = time.monotonic() - t0
    (raiz / "Lote-Resumo.md").write_text(
        resumo(registros, dirs, args, pulados, segundos), encoding="utf-8")

    conta = {}
    for r in registros:
        conta[r.get("situacao")] = conta.get(r.get("situacao"), 0) + 1
    print(f"\n[I3.3] FIM em {segundos/60:.1f} min: "
          + ", ".join(f"{v} {k.lower()}" for k, v in sorted(conta.items())))
    print(f"[I3.3] resumo: {raiz / 'Lote-Resumo.md'}")

    ruim = conta.get("FALHOU", 0) + conta.get("REPROVOU", 0)
    return 1 if (ruim or parar) else 0


if __name__ == "__main__":
    sys.exit(main())
