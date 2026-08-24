#!/usr/bin/env python3
"""
Autoteste do I3.2 (relatório de fidelidade) e da parte pura do I3.3 (lote).

Um relatório de fidelidade que só sabe dizer "passou" é pior que relatório
nenhum: ele dá confiança sem base. Este roteiro monta arquivos de propósito
quebrados e cobra o veredito certo de cada um.

  verde     conversão limpa, perda declarada          -> não reprova
  vermelho  perda que o conversor não declarou        -> REPROVA (perda calada)
            dado que tinha equivalente e não chegou   -> REPROVA (falha)
            `.brb` comprimido / buffer truncado       -> REPROVA (o Briba recusa)

Não precisa do Nuclear nem do acervo: roda em Python puro, no CI.

Uso: ./I3.2-autoteste.py
"""

import json
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
I32 = RAIZ / "I3.2-relatorio-fidelidade.py"
ALERTA = "⚠️"

falhas = []
testes = 0


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

def escrever_brb(destino, achados_declarados, n_pontos=4, comprimir=False,
                 truncar=False, sem_relatorio=False):
    modo = zipfile.ZIP_DEFLATED if comprimir else zipfile.ZIP_STORED
    buf = b"".join(struct.pack("<ffff", i, i, 1.0, 0.0) for i in range(n_pontos))
    if truncar:
        buf = buf[:-7]
    with zipfile.ZipFile(destino, "w", modo) as z:
        z.writestr("manifest.json", json.dumps({"magic": "BRB ",
                                                "schema_version": 1}))
        z.writestr("document.cbor", b"\xa0")
        z.writestr("strokes/0000.bin", buf)
        if not sem_relatorio:
            z.writestr("relatorio-de-fidelidade.json", json.dumps(
                {"schema": 1, "achados": achados_declarados}, ensure_ascii=False))
    return destino


def arvore(n_camadas=2, n_tracos=10, n_pontos=4, n_grupos=0, avisos=None):
    return {"schema": 1, "arquivo": "/acervo/fake.blend", "versao_nuclear": "5.0.0",
            "resumo": {"n_camadas": n_camadas, "n_tracos": n_tracos,
                       "n_pontos": n_pontos, "n_grupos": n_grupos},
            "avisos": avisos or []}


def comparacao(achados, veredito="PASSOU"):
    return {"schema": 1, "arquivo_nuclear": "/acervo/fake.blend",
            "veredito": veredito, "achados": achados,
            "comparado": {"camadas_nuclear": 2, "camadas_brb": 2,
                          "tracos_nuclear": 10, "tracos_brb": 10},
            "nao_verificado": ["níveis 3 e 4"]}


def achado(cat, assunto, onde, detalhe="detalhe"):
    return {"categoria": cat, "assunto": assunto, "onde": onde, "detalhe": detalhe}


# --------------------------------------------------------------------------- #

def rodar(tmp, nome, brb, arv_nuc=None, arv_brb=None, cmp_=None):
    d = tmp / nome
    d.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(I32), "arquivo", "--brb", str(brb),
           "--base", nome, "--saida-dir", str(d)]
    for flag, dado in (("--arvore-nuclear", arv_nuc), ("--arvore-brb", arv_brb),
                       ("--comparacao", cmp_)):
        if dado is not None:
            p = d / (flag.strip("-") + ".json")
            p.write_text(json.dumps(dado, ensure_ascii=False), encoding="utf-8")
            cmd += [flag, str(p)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    saida = json.loads((d / f"{nome}-fidelidade.json").read_text(encoding="utf-8"))
    md = (d / f"{nome}-fidelidade.md").read_text(encoding="utf-8")
    return r.returncode, saida, md


def checar(nome, condicao, detalhe=""):
    global testes
    testes += 1
    if condicao:
        print(f"  [ok]   {nome}")
    else:
        print(f"  [FALHA] {nome}  {detalhe}")
        falhas.append(nome)


# --------------------------------------------------------------------------- #

def main():
    with tempfile.TemporaryDirectory(prefix="i32-autoteste-") as t:
        tmp = Path(t)

        print("caminho verde - o relatório não pode reprovar conversão boa")

        brb = escrever_brb(tmp / "limpo.brb", [])
        cod, r, md = rodar(tmp, "limpo", brb, arvore(), arvore(), comparacao([]))
        checar("conversão sem achado nenhum sai LIMPA",
               r["veredito"] == "CONVERTIDO LIMPO" and cod == 0, r["veredito"])
        checar("o relatório diz o que VEIO, não só o que faltou",
               "## O que veio" in md and "| Traços |" in md)

        decl = [achado("DEGRADADO", "máscara", "CABECA/PELE",
                       "mascarada por IRIS")]
        brb = escrever_brb(tmp / "declarada.brb", decl)
        cod, r, md = rodar(tmp, "declarada", brb, arvore(), arvore(),
                           comparacao([achado("PERDIDO", "máscara calada",
                                              "CABECA/PELE")]))
        checar("perda que o conversor DECLAROU não vira perda calada",
               r["contagem"]["calada"] == 0 and r["contagem"]["declarada"] >= 1,
               json.dumps(r["contagem"]))
        checar("mas ela continua indo para a lista do animador",
               r["veredito"] == "PRECISA DE OLHO HUMANO", r["veredito"])
        checar("e a lista agrupa por motivo, não uma linha por camada",
               md.count("- [ ] **máscara**") == 1)

        print("\ncaminho vermelho - o que o relatório existe para pegar")

        brb = escrever_brb(tmp / "calada.brb", [])   # exportador calado
        cod, r, _ = rodar(tmp, "calada", brb, arvore(), arvore(),
                          comparacao([achado("PERDIDO", "cor", "CAPUZ/Layer")]))
        checar("perda observada e NÃO declarada reprova",
               r["veredito"] == "REPROVADO — PERDA CALADA" and cod == 1,
               f"{r['veredito']} cod={cod}")

        brb = escrever_brb(tmp / "lugar-errado.brb",
                           [achado("DEGRADADO", "cor", "OUTRA/Camada")])
        cod, r, _ = rodar(tmp, "lugar-errado", brb, arvore(), arvore(),
                          comparacao([achado("PERDIDO", "cor", "CAPUZ/Layer")]))
        checar("declaração em OUTRA camada não cobre a perda desta",
               r["veredito"] == "REPROVADO — PERDA CALADA", r["veredito"])

        brb = escrever_brb(tmp / "estrutural.brb", [])
        cod, r, _ = rodar(tmp, "estrutural", brb, arvore(), arvore(),
                          comparacao([achado("PERDIDO", "camada", "CABECA/PELE")]))
        checar("camada que sumiu é FALHA, não limitação do formato",
               r["veredito"] == "REPROVADO — FALHA DE CONVERSÃO" and cod == 1,
               r["veredito"])

        brb = escrever_brb(tmp / "comprimido.brb", [], comprimir=True)
        cod, r, _ = rodar(tmp, "comprimido", brb, arvore(), arvore(), comparacao([]))
        checar("ZIP comprimido reprova - o leitor do Briba recusa",
               r["veredito"] == "REPROVADO — FALHA DE CONVERSÃO"
               and any("comprimid" in a for a in r["avisos_do_arquivo"]),
               json.dumps(r["avisos_do_arquivo"], ensure_ascii=False))

        brb = escrever_brb(tmp / "truncado.brb", [], truncar=True)
        cod, r, _ = rodar(tmp, "truncado", brb, arvore(), arvore(), comparacao([]))
        checar("buffer de pontos truncado é pego pela contagem de bytes",
               any("truncado" in a for a in r["avisos_do_arquivo"]),
               json.dumps(r["avisos_do_arquivo"], ensure_ascii=False))

        brb = escrever_brb(tmp / "sem-rel.brb", [], sem_relatorio=True)
        cod, r, _ = rodar(tmp, "sem-rel", brb, arvore(), arvore(), comparacao([]))
        checar("`.brb` sem relatório de fidelidade é avisado, não ignorado",
               any("não traz relatório" in a for a in r["avisos_do_arquivo"]),
               json.dumps(r["avisos_do_arquivo"], ensure_ascii=False))

        brb = tmp / "nao-existe.brb"
        cod, r, _ = rodar(tmp, "sumido", brb, arvore(), None, None)
        checar("`.brb` que não existe não derruba o relatório",
               r["veredito"].startswith("REPROVADO"), r["veredito"])

        print("\nhonestidade - o relatório precisa dizer quando sabe pouco")

        brb = escrever_brb(tmp / "sem-cmp.brb", [])
        cod, r, md = rodar(tmp, "sem-cmp", brb, arvore(), arvore(), None)
        checar("sem comparação, o relatório se declara não verificado",
               r["verificacao_independente"] is False
               and "Sem verificação independente" in md)

        brb = escrever_brb(tmp / "pontos.brb", [], n_pontos=4)
        cod, r, md = rodar(tmp, "pontos", brb, arvore(n_pontos=9), arvore(),
                           comparacao([achado("PERDIDO", "pontos", "A/B")]))
        checar("ponto faltando com perda confirmada sai marcado",
               any(ALERTA in l["situacao"] for l in r["veio"]
                   if l["o_que"].startswith("Pontos")),
               json.dumps([l["situacao"] for l in r["veio"]], ensure_ascii=False))

        cod, r, md = rodar(tmp, "pontos-ok", brb, arvore(n_pontos=9), arvore(),
                           comparacao([]))
        checar("ponto faltando SEM perda confirmada é explicado, não alarmado",
               all(ALERTA not in l["situacao"] for l in r["veio"]),
               json.dumps([l["situacao"] for l in r["veio"]], ensure_ascii=False))

        print("\nconsolidado")

        pasta = tmp / "consolidar"
        pasta.mkdir()
        for nome in ("limpo", "calada"):
            origem = tmp / nome / f"{nome}-fidelidade.json"
            (pasta / origem.name).write_text(origem.read_text(encoding="utf-8"),
                                             encoding="utf-8")
        r = subprocess.run([sys.executable, str(I32), "consolidar", str(pasta)],
                           capture_output=True, text=True)
        d = json.loads((pasta / "Fidelidade-Consolidado.json").read_text(encoding="utf-8"))
        checar("um arquivo reprovado reprova o consolidado inteiro",
               r.returncode == 1 and d["pior_veredito"] == "REPROVADO — PERDA CALADA",
               f"cod={r.returncode} {d['pior_veredito']}")
        checar("o consolidado conta os motivos para o I5.2 priorizar",
               d["motivos"].get("cor") == 1, json.dumps(d["motivos"]))

        print("\nrecarimbagem - trocar o carimbo sem tocar no desenho")

        alvo = tmp / "recarimbar.brb"
        escrever_brb(alvo, [achado("DEGRADADO", "máscara", "A/B")], n_pontos=7)
        with zipfile.ZipFile(alvo) as z:
            antes = {i.filename: z.read(i.filename) for i in z.infolist()}
        r = subprocess.run([sys.executable, str(RAIZ / "I3.1-recarimbar-brb.py"),
                            str(alvo), "--magic", "BRBA",
                            "--renomear", "schema_version=version",
                            "--pasta", "strokes/=geometry/"],
                           capture_output=True, text=True)
        with zipfile.ZipFile(alvo) as z:
            depois = {i.filename: z.read(i.filename) for i in z.infolist()}
            comprimidas = [i.filename for i in z.infolist()
                           if i.compress_type != zipfile.ZIP_STORED]
            man = json.loads(depois["manifest.json"].decode("utf-8"))
        checar("o carimbo muda",
               man.get("magic") == "BRBA" and man.get("version") == 1
               and "schema_version" not in man, json.dumps(man))
        checar("a pasta é renomeada dentro do ZIP",
               "geometry/0000.bin" in depois and "strokes/0000.bin" not in depois,
               str(sorted(depois)))
        checar("mas o desenho sai byte a byte igual",
               depois.get("geometry/0000.bin") == antes.get("strokes/0000.bin")
               and depois["document.cbor"] == antes["document.cbor"]
               and depois["relatorio-de-fidelidade.json"]
                   == antes["relatorio-de-fidelidade.json"])
        checar("e o ZIP continua armazenado, que é o que o Briba aceita",
               not comprimidas, str(comprimidas))

        antes_txt = alvo.read_bytes()
        r = subprocess.run([sys.executable, str(RAIZ / "I3.1-recarimbar-brb.py"),
                            str(alvo), "--magic", "OUTRO", "--simular"],
                           capture_output=True, text=True)
        checar("--simular não grava nada", alvo.read_bytes() == antes_txt)

        torto = tmp / "torto.brb"
        torto.write_bytes(b"isto nao e um zip")
        r = subprocess.run([sys.executable, str(RAIZ / "I3.1-recarimbar-brb.py"),
                            str(torto), "--magic", "BRBA"],
                           capture_output=True, text=True)
        checar("`.brb` ilegível não é destruído pela recarimbagem",
               torto.read_bytes() == b"isto nao e um zip"
               and "ilegível" in r.stdout, r.stdout)

        print("\nI3.3 - descoberta de arquivos (a parte que roda sem o Nuclear)")

        acervo = tmp / "acervo"
        (acervo / "sub").mkdir(parents=True)
        nomes = ["ok.blend", "rig.nuc", "velho.blend1",
                 "arte (conflicted copy 2024-01-01).blend",
                 "arte (Cópia em conflito de estacao 2024-01-01).blend",
                 "texto.txt"]
        for n in nomes:
            (acervo / "sub" / n).write_bytes(b"x")
        r = subprocess.run([sys.executable, str(RAIZ / "I3.3-lote.py"),
                            "--dir", str(acervo), "--saida", str(tmp / "l"),
                            "--so-listar"], capture_output=True, text=True)
        achados = [l for l in r.stdout.splitlines() if l.strip()]
        checar("o lote acha `.blend` E `.nuc`",
               sum(a.endswith(".nuc") for a in achados) == 1
               and sum(a.endswith("ok.blend") for a in achados) == 1,
               r.stdout)
        checar("e pula backup `.blend1` e cópia de conflito do Dropbox",
               len(achados) == 2, "\n".join(achados))

    print(f"\n{testes} testes, {len(falhas)} falha(s)")
    for f in falhas:
        print(f"  FALHOU: {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
