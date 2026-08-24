#!/usr/bin/env python3
"""
I3.2 — relatório de fidelidade por arquivo convertido.

Responde três perguntas, nesta ordem, para quem **não** escreveu o conversor:

    o que veio          o que atravessou inteiro, com número
    o que se perdeu     o que não tem equivalente do outro lado, e por quê
    o que conferir      o que atravessou mas mudou de aparência

E uma quarta, que é o critério de aceite do lote:

    perda calada        o que o arquivo perdeu SEM avisar no relatório dele

O relatório cruza duas fontes independentes:

  DECLARADO   `relatorio-de-fidelidade.json`, gravado dentro do próprio `.brb`
              pelo exportador (I3.1). É o que o conversor **sabe** que degradou.
  OBSERVADO   a comparação do I3.4 entre a árvore do Nuclear e a árvore lida de
              volta do `.brb`. É o que de fato **está** diferente.

Divergência observada sem declaração correspondente é o defeito que este
relatório existe para pegar: o lote diz, com todas as letras, que um relatório
que afirma não ter perdido nada e é desmentido pelo animador é o relatório que
está errado — e é ele que precisa ser corrigido primeiro.

Uso:

  # um arquivo
  I3.2-relatorio-fidelidade.py arquivo \\
      --brb saida/brb/personagem.brb \\
      --arvore-nuclear saida/arvores/personagem.json \\
      --arvore-brb saida/arvores/personagem.brb.json \\
      --comparacao saida/relatorios/personagem.json \\
      --saida-dir saida/fidelidade

  # índice de tudo que já foi convertido
  I3.2-relatorio-fidelidade.py consolidar saida/fidelidade

Só `--brb` é obrigatório no modo `arquivo`. Sem a comparação o relatório sai
assinalado como **sem verificação independente** — ele passa a repetir o que o
conversor disse de si mesmo, e isso vale menos.
"""

import argparse
import json
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

SCHEMA = 1

# Veredito, do melhor para o pior. A ordem é usada para escolher o veredito
# final: vale sempre o pior que apareceu.
LIMPO      = "CONVERTIDO LIMPO"
DECLARADA  = "CONVERTIDO COM PERDA DECLARADA"
CONFERIR   = "PRECISA DE OLHO HUMANO"
CALADA     = "REPROVADO — PERDA CALADA"
FALHA      = "REPROVADO — FALHA DE CONVERSÃO"
ORDEM = [LIMPO, DECLARADA, CONFERIR, CALADA, FALHA]

# --------------------------------------------------------------------------- #
# Vocabulário: o que o exportador consegue declarar, e o que ele não consegue.
# --------------------------------------------------------------------------- #

# assunto observado (comparador) -> assuntos que o exportador usaria para o
# mesmo fato. Se o comparador achou algo aqui e o exportador não falou nada
# naquele lugar, a perda foi CALADA.
DECLARAVEL = {
    "cor":                    {"cor"},
    "pontos":                 {"profundidade", "pontos"},
    "opacidade":              {"opacidade"},
    "grupo":                  {"grupo"},
    "máscara calada":         {"máscara"},
    "máscara não preservada": {"máscara"},
    "modo de mistura":        {"modo de mistura"},
    "quadros em espera":      {"quadros em espera", "exposição"},
}

# assunto observado que NÃO é perda de fidelidade e sim defeito: o dado tinha
# equivalente no formato e mesmo assim não chegou lá.
ESTRUTURAL = {
    "estrutura", "camada", "traços", "exposição", "biblioteca de poses",
    "container", "camada a mais",
}

# O que muda a APARÊNCIA e por isso vai para a lista do animador, mesmo quando
# foi declarado direitinho. Declarar não desfaz o efeito na tela.
OLHO_HUMANO = {
    "máscara", "máscara calada", "máscara não preservada",
    "modo de mistura", "cor", "profundidade", "opacidade",
}

# Frases prontas: o motivo técnico traduzido para quem vai olhar o desenho.
PORQUE = {
    "máscara":
        "os níveis 1 e 2 do `.brb` não têm campo de máscara de camada. O vínculo "
        "foi guardado inteiro em `mascaras.json` dentro do arquivo — nada foi "
        "destruído — mas a camada vai aparecer **sem o recorte** até os níveis "
        "3 e 4 existirem.",
    "modo de mistura":
        "a especificação começa só com `Normal` (T2.7). A camada mantém o "
        "desenho e a cor, e perde o modo de mistura.",
    "profundidade":
        "o traço tinha extensão fora do plano de desenho e o `.brb` é 2D. "
        "Foi achatado na projeção; em desenho de produção isso costuma ser "
        "imperceptível, mas em peça girada no espaço muda a silhueta.",
    "cor":
        "o `.brb` guarda uma cor por traço. Quando o material tem cor de linha "
        "E de preenchimento, ou quando há cor por vértice, a fusão é inevitável.",
    "biblioteca de poses":
        "as poses moram em quadros 100001+ e não são animação — são acervo de "
        "desenho. Perdê-las é perder variante de boca, mão e olho.",
}

CONFERENCIA = {
    "máscara":
        "abra a camada no Briba e confira se o desenho aparece **inteiro** onde "
        "antes era recortado.",
    "modo de mistura":
        "confira se a camada ficou opaca demais ou clara demais em relação ao "
        "que está embaixo.",
    "cor":
        "confira a cor da linha e do preenchimento; a fusão pode ter escolhido "
        "a errada das duas.",
    "profundidade":
        "confira a silhueta da peça — ela foi achatada no plano.",
    "opacidade":
        "confira a transparência da camada.",
}


# --------------------------------------------------------------------------- #
# Leitura das fontes
# --------------------------------------------------------------------------- #

def ler_json(caminho):
    if not caminho:
        return None
    p = Path(caminho)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def declarado_do_brb(caminho_brb):
    """Tira o relatório do exportador de dentro do `.brb`.

    Nunca levanta: um `.brb` ilegível é um achado do relatório, não um traço
    de pilha. O modo lote (I3.3) depende disso para não parar a noite inteira
    num arquivo torto.
    """
    p = Path(caminho_brb)
    if not p.exists():
        return None, [f"o arquivo `{p.name}` não existe"]
    avisos = []
    try:
        with zipfile.ZipFile(p) as z:
            nomes = set(z.namelist())
            comprimidos = [i.filename for i in z.infolist()
                           if i.compress_type != zipfile.ZIP_STORED]
            if comprimidos:
                avisos.append(
                    f"{len(comprimidos)} entrada(s) do ZIP estão comprimidas; o "
                    f"leitor do Briba recusa método diferente de armazenado")
            if "relatorio-de-fidelidade.json" not in nomes:
                avisos.append("o `.brb` não traz relatório de fidelidade — "
                              "não dá para saber o que o conversor sabia")
                return None, avisos
            bruto = z.read("relatorio-de-fidelidade.json").decode("utf-8")
        return json.loads(bruto), avisos
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError,
            UnicodeDecodeError, OSError) as e:
        return None, [f"não deu para ler o `.brb`: {type(e).__name__}: {e}"]


BYTES_POR_PONTO = 16  # 4 floats little-endian: x, y, pressão, tempo


def medidas_do_brb(caminho_brb):
    """Mede o `.brb` por fora, sem acreditar no que ele diz de si mesmo.

    O leitor do I3.4 não conta ponto — ele lê a árvore, e o ponto mora num
    buffer binário à parte. Contar os bytes aqui é o que pega buffer truncado,
    que é a falha silenciosa mais cara do formato: a árvore fica perfeita e o
    desenho chega pela metade.
    """
    p = Path(caminho_brb)
    if not p.exists():
        return {}
    try:
        with zipfile.ZipFile(p) as z:
            bytes_pontos = sum(i.file_size for i in z.infolist()
                               if i.filename.startswith("strokes/")
                               and i.filename.endswith(".bin"))
    except (zipfile.BadZipFile, OSError):
        return {}
    if bytes_pontos % BYTES_POR_PONTO:
        return {"bytes_de_pontos": bytes_pontos, "buffer_quebrado": True}
    return {"bytes_de_pontos": bytes_pontos,
            "n_pontos": bytes_pontos // BYTES_POR_PONTO}


# --------------------------------------------------------------------------- #
# O cruzamento
# --------------------------------------------------------------------------- #

def indexar_declarado(itens):
    """Agrupa o que o exportador declarou por lugar e por assunto."""
    por_lugar = defaultdict(set)
    for i in itens or []:
        por_lugar[i.get("onde") or "—"].add((i.get("assunto") or "").strip())
    return por_lugar


def foi_declarado(achado, por_lugar):
    """O exportador avisou desta perda, neste lugar?"""
    assunto = (achado.get("assunto") or "").strip()
    equivalentes = DECLARAVEL.get(assunto)
    if not equivalentes:
        return False
    onde = achado.get("onde") or "—"
    if por_lugar.get(onde, set()) & equivalentes:
        return True
    # O exportador registra por camada (`objeto/camada`); o comparador às vezes
    # aponta o objeto inteiro. Aceita o prefixo para não acusar perda calada
    # onde a declaração existe um nível acima.
    for lugar, assuntos in por_lugar.items():
        if (lugar.startswith(onde + "/") or onde.startswith(lugar + "/")) \
           and assuntos & equivalentes:
            return True
    return False


def classificar(comparacao, declarado):
    """Separa o observado em: declarada, calada, estrutural, conferir."""
    por_lugar = indexar_declarado((declarado or {}).get("achados"))
    baldes = {"declarada": [], "calada": [], "estrutural": [], "conferir": [],
              "suposicoes": []}

    for a in (comparacao or {}).get("achados", []):
        cat = a.get("categoria")
        assunto = (a.get("assunto") or "").strip()
        if cat == "OK":
            continue
        if cat == "SUSPEITO":
            baldes["conferir"].append(a)
            continue
        if assunto in ESTRUTURAL:
            baldes["estrutural"].append(a)
            continue
        if foi_declarado(a, por_lugar):
            baldes["declarada"].append(a)
        else:
            baldes["calada"].append(a)

    # O que o exportador declarou e o comparador não viu continua sendo perda —
    # só não é perda escondida. Entra na lista declarada para o animador saber.
    vistos = {(a.get("assunto"), a.get("onde")) for a in baldes["declarada"]}
    for d in (declarado or {}).get("achados", []):
        chave = (d.get("assunto"), d.get("onde"))
        if chave in vistos:
            continue
        item = {**d, "_fonte": "exportador"}
        # SUSPEITO do lado do exportador é SUPOSIÇÃO, não perda. O número mágico
        # do container é o caso claro: nada se perdeu, só não se sabe se o valor
        # está certo. Listar isso como perda faria todo arquivo do acervo nascer
        # com "perda declarada", e aí a categoria deixa de significar coisa
        # alguma justamente onde ela mais precisa significar.
        if d.get("categoria") == "SUSPEITO":
            # Suposição SEM lugar é do container (número mágico, nome de campo):
            # nada a conferir no desenho, e recarimbável. Suposição COM lugar é
            # escolha de conversão numa camada — essa quem confere é o animador,
            # abrindo o arquivo, e recarimbar não desfaz.
            if d.get("onde"):
                baldes["conferir"].append(item)
            else:
                baldes["suposicoes"].append(item)
            continue
        baldes["declarada"].append(item)
    return baldes


def veredito_de(baldes, avisos_brb):
    v = LIMPO
    if baldes["declarada"]:
        v = DECLARADA
    if baldes["conferir"] or any((a.get("assunto") or "") in OLHO_HUMANO
                                 for a in baldes["declarada"]):
        v = CONFERIR
    if baldes["calada"]:
        v = CALADA
    if baldes["estrutural"] or avisos_brb:
        v = FALHA
    return v


def pior(a, b):
    return a if ORDEM.index(a) >= ORDEM.index(b) else b


# --------------------------------------------------------------------------- #
# O que veio — a metade que os relatórios de migração sempre esquecem
# --------------------------------------------------------------------------- #

def o_que_veio(arv_nuc, arv_brb, comparacao, medidas):
    conferido = conferiu_geometria(comparacao)
    """Tabela lado a lado. Sem isso o relatório só sabe reclamar."""
    def resumo(a):
        return (a or {}).get("resumo", {}) or {}

    n, b = resumo(arv_nuc), dict(resumo(arv_brb))
    b.update({k: v for k, v in (medidas or {}).items() if k == "n_pontos"})
    if not n and comparacao:
        c = comparacao.get("comparado", {})
        n = {"n_camadas": c.get("camadas_nuclear"), "n_tracos": c.get("tracos_nuclear")}
        b.setdefault("n_camadas", c.get("camadas_brb"))
        b.setdefault("n_tracos", c.get("tracos_brb"))

    linhas = []
    for rotulo, chave in (("Camadas de desenho", "n_camadas"),
                          ("Grupos de camada", "n_grupos"),
                          ("Traços", "n_tracos"),
                          ("Pontos de traço", "n_pontos"),
                          ("Quadros em espera", "n_quadros_em_espera"),
                          ("Quadros fora da linha (biblioteca de poses)",
                           "n_quadros_fora_da_linha")):
        vn, vb = n.get(chave), b.get(chave)
        if vn is None and vb is None:
            continue
        linhas.append({"o_que": rotulo, "nuclear": vn, "brb": vb,
                       "situacao": situacao(vn, vb, chave, n, b, conferido)})
    return linhas


def conferiu_geometria(comparacao):
    """A comparação do I3.4 olhou traço e ponto camada a camada, e não reclamou?

    Sem essa resposta, uma contagem menor do lado do `.brb` não pode ser
    explicada — só descrita. E descrever perda sem julgar é o que faz relatório
    de migração não valer nada.
    """
    if comparacao is None:
        return None
    for a in comparacao.get("achados", []):
        if a.get("categoria") in ("PERDIDO", "DEGRADADO") and \
           (a.get("assunto") or "") in ("pontos", "traços", "exposição"):
            return False
    return True


def situacao(vn, vb, chave, n, b, conferido=None):
    if vn is None or vb is None:
        return "não medido dos dois lados"
    if vn == vb:
        return "inteiro" if vn else "não havia"

    # Objeto GP do Nuclear vira grupo de camada no `.brb`. A contagem de camadas
    # do lado de lá soma os dois, e a diferença bate exatamente com o número de
    # grupos — quando bate, não faltou nem sobrou nada: é tradução de modelo.
    grupos_novos = (b.get("n_grupos") or 0) - (n.get("n_grupos") or 0)
    if chave == "n_camadas" and vb - vn == grupos_novos and grupos_novos > 0:
        return (f"inteiro — as {grupos_novos} a mais são os objetos do Nuclear "
                f"virados grupo ({vn} de desenho + {grupos_novos})")
    if chave == "n_grupos" and vb > vn:
        return f"{vb} contra {vn} — cada objeto do Nuclear virou um grupo"
    if chave in ("n_tracos", "n_pontos") and vb < vn:
        falta = vn - vb
        if conferido is True:
            return (f"{num(falta)} a menos, e não é perda: quadro em espera "
                    f"referencia o desenho em vez de repetir. A comparação olhou "
                    f"camada a camada e não achou traço nem ponto faltando")
        if conferido is False:
            return f"⚠️ {num(falta)} a menos — a comparação achou perda de verdade aqui"
        return f"⚠️ {num(falta)} a menos — sem comparação, não dá para dizer se é perda"
    return f"{num(vb)} contra {num(vn)}"


# --------------------------------------------------------------------------- #
# Montagem
# --------------------------------------------------------------------------- #

def montar(base, caminho_brb, arv_nuc, arv_brb, comparacao):
    declarado, avisos_brb = declarado_do_brb(caminho_brb) if caminho_brb else (None, [])
    medidas = medidas_do_brb(caminho_brb) if caminho_brb else {}
    avisos_brb = list(avisos_brb or [])
    avisos_brb += list((arv_brb or {}).get("avisos", []) or [])
    if medidas.get("buffer_quebrado"):
        avisos_brb.append(
            f"o buffer de pontos tem {medidas['bytes_de_pontos']} bytes, que não é "
            f"múltiplo de {BYTES_POR_PONTO} — está truncado, e algum traço chegou "
            f"pela metade do outro lado")

    baldes = classificar(comparacao, declarado)
    v = veredito_de(baldes, avisos_brb)

    p = Path(caminho_brb) if caminho_brb else None
    mascaras = (arv_brb or {}).get("mascaras_preservadas") or {}
    if isinstance(mascaras, dict):
        n_mascaras = mascaras.get("n_camadas_mascaradas") or len(mascaras.get("mascaras", []))
    else:
        n_mascaras = len(mascaras)

    return {
        "schema": SCHEMA,
        "base": base,
        "veredito": v,
        "verificacao_independente": comparacao is not None,
        "arquivo_nuclear": (arv_nuc or {}).get("arquivo")
                           or (comparacao or {}).get("arquivo_nuclear"),
        "versao_nuclear": (arv_nuc or {}).get("versao_nuclear"),
        "versao_do_arquivo": (arv_nuc or {}).get("versao_do_arquivo"),
        "brb": {
            "caminho": str(p) if p else None,
            "bytes": p.stat().st_size if p and p.exists() else None,
        },
        "veio": o_que_veio(arv_nuc, arv_brb, comparacao, medidas),
        "medidas_do_brb": medidas,
        "perdeu_declarado": baldes["declarada"],
        "perdeu_calado": baldes["calada"],
        "falhou": baldes["estrutural"],
        "conferir": baldes["conferir"],
        "suposicoes": baldes["suposicoes"],
        "mascaras_preservadas": n_mascaras,
        "avisos_do_arquivo": avisos_brb,
        "contagem": {
            "declarada": len(baldes["declarada"]),
            "calada": len(baldes["calada"]),
            "estrutural": len(baldes["estrutural"]),
            "conferir": len(baldes["conferir"]),
            "suposicoes": len(baldes["suposicoes"]),
        },
        "nao_verificado": (comparacao or {}).get("nao_verificado", []) or [
            "nada foi verificado de forma independente — só o que o conversor "
            "disse de si mesmo",
        ],
    }


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #

SELO = {
    LIMPO:     "✅",
    DECLARADA: "🟡",
    CONFERIR:  "👁️",
    CALADA:    "❌",
    FALHA:     "❌",
}


def agrupar(achados):
    g = defaultdict(list)
    for a in achados:
        g[(a.get("assunto") or "—").strip()].append(a)
    return sorted(g.items(), key=lambda kv: (-len(kv[1]), kv[0]))


def lista_de(achados, limite=6):
    out = []
    for assunto, itens in agrupar(achados):
        onde = [i.get("onde") for i in itens if i.get("onde")]
        amostra = ", ".join(f"`{o}`" for o in onde[:3])
        if len(onde) > 3:
            amostra += f" e mais {len(onde) - 3}"
        cabeca = f"- **{assunto}** — {len(itens)}×"
        if amostra:
            cabeca += f" · {amostra}"
        out.append(cabeca)
        out.append(f"  - {itens[0].get('detalhe', '').strip()}")
        if assunto in PORQUE:
            out.append(f"  - **Por quê:** {PORQUE[assunto]}")
    return out


def num(v):
    return "—" if v is None else f"{v:,}".replace(",", ".")


def markdown(r):
    L = []
    A = L.append
    A(f"# Fidelidade da conversão — `{r['base']}`")
    A("")
    A(f"{SELO.get(r['veredito'], '•')} **{r['veredito']}**")
    A("")
    if r.get("suposicoes"):
        n = len(r["suposicoes"])
        A(f"O veredito acima é sobre **fidelidade do desenho**. Além dele, este "
          f"arquivo carrega {n} suposição{'ões' if n != 1 else ''} de container "
          f"ainda não confirmada{'s' if n != 1 else ''} — ver o fim do relatório. "
          f"{'Elas não tiram' if n != 1 else 'Ela não tira'} nem "
          f"{'alteram' if n != 1 else 'altera'} nada do desenho, mas "
          f"{'podem' if n != 1 else 'pode'} fazer o aplicativo recusar o "
          f"arquivo inteiro.")
        A("")
    if not r["verificacao_independente"]:
        A("> ⚠️ **Sem verificação independente.** Este relatório repete o que o "
          "conversor disse de si mesmo — a árvore do `.brb` não foi comparada "
          "com a do Nuclear. Vale menos que um relatório verificado, e o modo "
          "lote (I3.3) roda com `--verificar` justamente para não cair aqui.")
        A("")

    A("| | |")
    A("|---|---|")
    A(f"| Arquivo do Nuclear | `{r['arquivo_nuclear'] or '—'}` |")
    tamanho = f" · {num(r['brb']['bytes'])} bytes" if r["brb"]["bytes"] else ""
    A(f"| Arquivo `.brb` | `{r['brb']['caminho'] or '—'}`{tamanho} |")
    if r.get("versao_nuclear"):
        A(f"| Nuclear que exportou | {r['versao_nuclear']} |")
    if r.get("versao_do_arquivo"):
        A(f"| Versão que gravou o `.blend` | {r['versao_do_arquivo']} |")
    A("")

    # ---- o que veio
    A("## O que veio")
    A("")
    if r["veio"]:
        A("| O que | No Nuclear | No `.brb` | Situação |")
        A("|---|---:|---:|---|")
        for l in r["veio"]:
            A(f"| {l['o_que']} | {num(l['nuclear'])} | {num(l['brb'])} | {l['situacao']} |")
    else:
        A("_Não deu para medir — faltou a árvore de um dos lados._")
    A("")
    if r["mascaras_preservadas"]:
        plural = "s" if r["mascaras_preservadas"] != 1 else ""
        A(f"Além disso, **{r['mascaras_preservadas']} vínculo{plural} de máscara** "
          f"{'foram' if plural else 'foi'} guardado{plural} em `mascaras.json` "
          f"dentro do arquivo. Máscara não é aplicada nos níveis 1 e 2, mas o "
          f"vínculo está lá inteiro — a conversão é reversível.")
        A("")

    # ---- o que se perdeu
    A("## O que se perdeu")
    A("")
    if not r["perdeu_declarado"] and not r["perdeu_calado"] and not r["falhou"]:
        A("Nada. Toda a estrutura de camada, traço, cor e exposição atravessou.")
    else:
        if r["perdeu_declarado"]:
            A("### Perda declarada pelo conversor")
            A("")
            A("Isto é limitação conhecida do nível 1/2 do formato, não defeito do "
              "arquivo. Está escrito dentro do próprio `.brb`.")
            A("")
            L.extend(lista_de(r["perdeu_declarado"]))
            A("")
        if r["perdeu_calado"]:
            A("### ❌ Perda **calada**")
            A("")
            A("A comparação achou diferença onde o conversor não avisou nada. "
              "**Isto reprova a conversão** — não pelo tamanho da perda, mas "
              "porque ela não estava no relatório. É o critério de aceite do lote.")
            A("")
            L.extend(lista_de(r["perdeu_calado"]))
            A("")
        if r["falhou"]:
            A("### ❌ Falha de conversão")
            A("")
            A("Não é limitação do formato: o dado **tinha** equivalente do outro "
              "lado e mesmo assim não chegou lá. É defeito do exportador.")
            A("")
            L.extend(lista_de(r["falhou"]))
            A("")

    # ---- conferência humana
    A("## O que precisa de conferência humana")
    A("")
    pendencias = list(r["conferir"]) + [
        a for a in r["perdeu_declarado"] + r["perdeu_calado"]
        if (a.get("assunto") or "") in OLHO_HUMANO]
    if not pendencias:
        A("Nada. Nenhuma diferença deste arquivo muda o que se vê na tela.")
    else:
        # Uma linha por MOTIVO, não por camada. Um rig de personagem tem centenas
        # de camadas e a mesma decisão de conversão se repete em todas — cento e
        # nove linhas iguais não são uma lista de conferência, são uma parede.
        A("Uma linha por **motivo**, com as camadas atingidas. Abra o arquivo no "
          "Briba e confira cada motivo uma vez; se o primeiro estiver certo, os "
          "outros da mesma linha seguem a mesma regra de conversão.")
        A("")
        for assunto, itens in agrupar(pendencias):
            chave = (assunto or "").replace("máscara calada", "máscara") \
                                   .replace("máscara não preservada", "máscara")
            dica = CONFERENCIA.get(chave) or (itens[0].get("detalhe") or "").strip()
            lugares = []
            for i in itens:
                o = i.get("onde")
                if o and o not in lugares:
                    lugares.append(o)
            n_l, n_i = len(lugares), len(itens)
            quantos = (f"{n_l} camada" + ("s" if n_l != 1 else "")) if lugares \
                else (f"{n_i} ocorrência" + ("s" if n_i != 1 else ""))
            A(f"- [ ] **{assunto}** — {quantos}. {dica}")
            if lugares:
                mostra = ", ".join(f"`{o}`" for o in lugares[:8])
                if len(lugares) > 8:
                    mostra += f" … e mais {len(lugares) - 8}"
                A(f"  - Onde: {mostra}")
    A("")

    if r.get("suposicoes"):
        A("## Suposições que este arquivo carrega")
        A("")
        A("A especificação do formato não fixa estes pontos, e o conversor teve "
          "de escolher. **Nada se perdeu por causa deles** — mas se o valor "
          "escolhido estiver errado, o arquivo pode ser recusado na abertura. "
          "Todos são recarimbáveis com `I3.1-recarimbar-brb.py`, sem reconverter.")
        A("")
        for assunto, itens in agrupar(r["suposicoes"]):
            A(f"- **{assunto}** — {itens[0].get('detalhe', '').strip()}")
        A("")

    if r["avisos_do_arquivo"]:
        A("## Avisos do próprio arquivo")
        A("")
        for a in r["avisos_do_arquivo"]:
            A(f"- {a}")
        A("")

    A("## O que este relatório **não** verifica")
    A("")
    for n in r["nao_verificado"]:
        A(f"- {n}")
    A("")
    A("---")
    A("")
    A("_Gerado pelo I3.2. As duas fontes são independentes: o que o conversor "
      "declarou (dentro do `.brb`) e o que a comparação do I3.4 observou "
      "(árvore do Nuclear × árvore relida do `.brb`)._")
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------- #
# Consolidado
# --------------------------------------------------------------------------- #

def consolidar(pasta):
    pasta = Path(pasta)
    arquivos = sorted(pasta.glob("*-fidelidade.json"))
    relatorios = [json.loads(p.read_text(encoding="utf-8")) for p in arquivos]
    if not relatorios:
        return None, f"nenhum `*-fidelidade.json` em {pasta}"

    contagem = Counter(r["veredito"] for r in relatorios)
    pior_geral = LIMPO
    for r in relatorios:
        pior_geral = pior(pior_geral, r["veredito"])

    L = []
    A = L.append
    A("# Fidelidade da conversão — consolidado")
    A("")
    A(f"{len(relatorios)} arquivo(s) convertido(s). "
      f"Pior veredito do conjunto: {SELO.get(pior_geral,'•')} **{pior_geral}**.")
    A("")
    A("| Veredito | Arquivos |")
    A("|---|---:|")
    for v in ORDEM:
        if contagem.get(v):
            A(f"| {SELO.get(v,'•')} {v} | {contagem[v]} |")
    A("")
    A("## Por arquivo")
    A("")
    A("| Arquivo | Veredito | Declarada | Calada | Falha | Conferir | Suposições | Verificado |")
    A("|---|---|---:|---:|---:|---:|---:|:-:|")
    for r in sorted(relatorios, key=lambda r: -ORDEM.index(r["veredito"])):
        c = r["contagem"]
        A(f"| [`{r['base']}`]({r['base']}-fidelidade.md) "
          f"| {SELO.get(r['veredito'],'•')} {r['veredito']} "
          f"| {c['declarada']} | {c['calada']} | {c['estrutural']} | {c['conferir']} "
          f"| {c.get('suposicoes', 0)} "
          f"| {'sim' if r['verificacao_independente'] else '**não**'} |")
    A("")

    precisam = [r for r in relatorios if r["contagem"]["conferir"]
                or any((a.get("assunto") or "") in OLHO_HUMANO
                       for a in r["perdeu_declarado"] + r["perdeu_calado"])]
    A("## O que precisa de olho humano")
    A("")
    if not precisam:
        A("Nenhum arquivo do conjunto muda de aparência na conversão.")
    else:
        for r in precisam:
            A(f"- **`{r['base']}`** — ver "
              f"[o relatório dele]({r['base']}-fidelidade.md)")
    A("")

    motivos = Counter()
    for r in relatorios:
        for a in r["perdeu_declarado"] + r["perdeu_calado"] + r["falhou"]:
            motivos[(a.get("assunto") or "—").strip()] += 1
    if motivos:
        A("## Motivos mais frequentes")
        A("")
        A("Serve para o I5.2: o que aparece em muitos arquivos vale corrigir no "
          "exportador; o que aparece em um só vale tratar à mão.")
        A("")
        A("| Motivo | Ocorrências |")
        A("|---|---:|")
        for m, n in motivos.most_common():
            A(f"| {m} | {n} |")
        A("")

    dados = {
        "schema": SCHEMA,
        "n_arquivos": len(relatorios),
        "pior_veredito": pior_geral,
        "por_veredito": dict(contagem),
        "motivos": dict(motivos),
        "arquivos": [{"base": r["base"], "veredito": r["veredito"],
                      "contagem": r["contagem"],
                      "verificacao_independente": r["verificacao_independente"]}
                     for r in relatorios],
    }
    return ("\n".join(L) + "\n", dados), None


# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="modo", required=True)

    a1 = sub.add_parser("arquivo", help="relatório de um arquivo convertido")
    a1.add_argument("--brb", required=True)
    a1.add_argument("--arvore-nuclear")
    a1.add_argument("--arvore-brb")
    a1.add_argument("--comparacao")
    a1.add_argument("--saida-dir", default=".")
    a1.add_argument("--base", help="nome curto (padrão: nome do .brb sem extensão)")

    a2 = sub.add_parser("consolidar", help="índice de tudo que já foi convertido")
    a2.add_argument("pasta")

    args = ap.parse_args()

    if args.modo == "consolidar":
        r, erro = consolidar(args.pasta)
        if erro:
            print(f"[I3.2] {erro}")
            return 2
        md, dados = r
        pasta = Path(args.pasta)
        (pasta / "Fidelidade-Consolidado.md").write_text(md, encoding="utf-8")
        (pasta / "Fidelidade-Consolidado.json").write_text(
            json.dumps(dados, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8")
        print(f"[I3.2] consolidado: {dados['n_arquivos']} arquivo(s), "
              f"pior veredito {dados['pior_veredito']}")
        return 0 if dados["pior_veredito"] not in (CALADA, FALHA) else 1

    base = args.base or Path(args.brb).stem
    r = montar(base, args.brb,
               ler_json(args.arvore_nuclear),
               ler_json(args.arvore_brb),
               ler_json(args.comparacao))

    saida = Path(args.saida_dir)
    saida.mkdir(parents=True, exist_ok=True)
    (saida / f"{base}-fidelidade.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    (saida / f"{base}-fidelidade.md").write_text(markdown(r), encoding="utf-8")

    c = r["contagem"]
    print(f"[I3.2] {base}: {r['veredito']} — {c['declarada']} declarada, "
          f"{c['calada']} calada, {c['estrutural']} falha, {c['conferir']} conferir")
    return 0 if r["veredito"] not in (CALADA, FALHA) else 1


if __name__ == "__main__":
    sys.exit(main())
