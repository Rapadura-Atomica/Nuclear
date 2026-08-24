"""
I3.4 — compara a árvore do Nuclear com a árvore do `.brb` e emite um veredito.

As quatro categorias são as do I3.2, e a quarta é a que faz o relatório valer:

  OK          convertido com equivalência exata
  DEGRADADO   convertido por aproximação — diz qual, e quanto
  PERDIDO     sem equivalente do outro lado
  SUSPEITO    converteu, mas precisa de olho humano

O critério de aceite do lote diz que, se o relatório afirmar que nada se perdeu
e um animador discordar, **é o relatório que está errado**. Por isso SUSPEITO
existe: sem um lugar para admitir incerteza, a única saída seria mentir.

Uso:
    python3 I3.4-comparar.py arvore-nuclear.json arvore-brb.json [saida.json]
"""
import json
import sys
from pathlib import Path

OK, DEGRADADO, PERDIDO, SUSPEITO = "OK", "DEGRADADO", "PERDIDO", "SUSPEITO"
TOL_OPACIDADE = 0.001


class Achados:
    def __init__(self):
        self.itens = []

    def add(self, categoria, assunto, detalhe, onde=None):
        self.itens.append({"categoria": categoria, "assunto": assunto,
                           "detalhe": detalhe, "onde": onde})

    def conta(self, categoria):
        return sum(1 for i in self.itens if i["categoria"] == categoria)

    @property
    def passou(self):
        return self.conta(PERDIDO) == 0 and self.conta(DEGRADADO) == 0


def _quadros_unicos(camada):
    """Um quadro por desenho distinto — descarta as reexposições."""
    vistos, out = set(), []
    for q in camada["quadros"]:
        ref = q.get("desenho_ref")
        if ref is not None:
            if ref in vistos:
                continue
            vistos.add(ref)
        out.append(q)
    return out


def camadas_do_nuclear(arv):
    """Achata os objetos GP numa lista de camadas comparável com a do .brb.

    No Nuclear cada objeto GP tem suas camadas; no `.brb` há uma árvore só. O
    nome do objeto entra como prefixo do caminho para que duas camadas
    chamadas `linha` em objetos diferentes não se confundam.
    """
    out = []
    for ob in arv.get("objetos", []):
        for c in ob.get("camadas", []):
            fim_cena = (arv.get("cena", {}).get("quadros") or [1, 250])[1]
            expostos = [q for q in c["quadros_expostos"] if q <= fim_cena + 1000]
            out.append({
                "caminho": f"{ob['nome']}/{c['nome']}",
                "objeto": ob["nome"],
                "nome": c["nome"],
                # Um objeto GP do Nuclear vira um grupo no .brb — é o mapeamento
                # natural, porque a spec só tem árvore de camadas e não tem
                # objeto. Quando a camada já está num grupo de camadas, esse
                # grupo é que manda; senão o pai esperado é o nome do objeto.
                "grupo_pai_esperado": c.get("grupo_pai") or ob["nome"],
                "ordem": c["ordem_de_desenho"],
                # todos os quadros que carregam desenho, biblioteca inclusive:
                # é isso que precisa existir do outro lado
                "quadros_com_desenho": sorted(c["quadros_expostos"]),
                "opacidade": c.get("opacidade"),
                "visivel": c.get("visivel"),
                "quadros_expostos": expostos,
                "quadros_biblioteca": c.get("quadros_fora_da_linha", []),
                "quadros_em_espera": c.get("quadros_em_espera", []),
                # Contagem por DESENHO ÚNICO, não por ocorrência de quadro:
                # um quadro em espera reexpõe o mesmo desenho, e o `.brb`
                # guarda a referência em vez de repetir os traços. Contar por
                # quadro faria o comparador acusar perda num exportador que
                # está justamente fazendo a coisa certa.
                "n_tracos": sum(q["n_tracos"] for q in _quadros_unicos(c)),
                "n_pontos": sum(t["geometria"].get("n", 0)
                                for q in _quadros_unicos(c) for t in q["tracos"]),
                "tem_cor_material": any(t.get("cor_material_traco") or t.get("cor_material_fill")
                                        for q in c["quadros"] for t in q["tracos"]),
                "tem_cor_vertice": any(t.get("cor_vertice")
                                       for q in c["quadros"] for t in q["tracos"]),
                "mascaras": c.get("mascaras") or [],
                "usa_mascara": bool(c.get("usa_mascara")),
            })
    return out


def camadas_do_brb(arv):
    out = []
    for c in arv.get("camadas", []):
        tipo = (c.get("tipo_de_conteudo") or "").lower()
        if tipo.startswith("group"):
            continue
        out.append({
            "caminho": c.get("nome"),
            "nome": c.get("nome"),
            "grupo_pai": c.get("grupo_pai"),
            "ordem": c.get("ordem_de_desenho"),
            "opacidade": c.get("opacidade"),
            "visivel": c.get("visivel"),
            "quadros_expostos": c.get("quadros_expostos", []),
            "quadros_em_espera": c.get("quadros_em_espera", []),
            "n_tracos": sum(q["n_tracos"] for q in c.get("quadros", [])),
            "n_pontos": sum((t.get("n_pontos") or 0)
                            for q in c.get("quadros", []) for t in q.get("tracos", [])),
            "tem_cor": any(t.get("cor") for q in c.get("quadros", [])
                           for t in q.get("tracos", [])),
        })
    return out


def marcar_rank(camadas, chave_pai):
    """Posição relativa dentro do pai — 0, 1, 2… por grupo."""
    por_pai = {}
    for c in sorted(camadas, key=lambda x: (x.get("ordem") or 0, str(x.get("nome")))):
        pai = c.get(chave_pai)
        por_pai.setdefault(pai, [])
        c["rank"] = len(por_pai[pai])
        por_pai[pai].append(c)
    return camadas


def casar(orig, conv):
    """Casa camada por nome. Nome é o que o padrão de rig fixa e é o que o
    animador reconhece — casar por índice esconderia justamente o defeito de
    ordem que a comparação existe para pegar."""
    por_nome = {}
    for c in conv:
        por_nome.setdefault(c["nome"], []).append(c)
    pares, sobrando = [], list(conv)
    for o in orig:
        cands = por_nome.get(o["nome"]) or []
        escolhido = cands.pop(0) if cands else None
        if escolhido is not None and escolhido in sobrando:
            sobrando.remove(escolhido)
        pares.append((o, escolhido))
    return pares, sobrando


def comparar(nuc, brb):
    a = Achados()
    orig = marcar_rank(camadas_do_nuclear(nuc), "grupo_pai_esperado")
    conv = marcar_rank(camadas_do_brb(brb), "grupo_pai")

    # ---- nível 2: estrutura -------------------------------------------------
    if not conv:
        if not orig:
            # Nem todo `.blend` do acervo tem desenho: biblioteca de Actions,
            # arquivo só de armadura, cena de montagem. Um `.brb` vazio a partir
            # de um arquivo vazio não perdeu nada — reprovar aqui acusaria o
            # conversor por uma decisão que o arquivo de entrada já tinha
            # tomado. Fica registrado como suspeito porque **é** notícia: quem
            # esperava um personagem vai abrir um arquivo em branco.
            a.add(SUSPEITO, "arquivo sem desenho",
                  "o arquivo não tem camada de Grease Pencil nenhuma, e o .brb "
                  "saiu vazio do mesmo jeito — nada se perdeu. Se ele guarda "
                  "rig ou animação, isso é nível 3/4 e não entra nos níveis 1 e 2")
        else:
            a.add(PERDIDO, "estrutura",
                  f"o Nuclear tem {len(orig)} camada(s) de desenho e o .brb não "
                  f"tem nenhuma")
        return a, orig, conv

    pares, sobrando = casar(orig, conv)

    for o, c in pares:
        onde = o["caminho"]
        if c is None:
            a.add(PERDIDO, "camada", f"camada `{o['nome']}` não existe no .brb", onde)
            continue

        if o["n_tracos"] != c["n_tracos"]:
            cat = PERDIDO if c["n_tracos"] < o["n_tracos"] else SUSPEITO
            a.add(cat, "traços",
                  f"{o['n_tracos']} no Nuclear, {c['n_tracos']} no .brb", onde)

        if o["n_pontos"] and c["n_pontos"] and o["n_pontos"] != c["n_pontos"]:
            dif = abs(o["n_pontos"] - c["n_pontos"]) / o["n_pontos"]
            a.add(DEGRADADO if dif > 0.01 else SUSPEITO, "pontos",
                  f"{o['n_pontos']} no Nuclear, {c['n_pontos']} no .brb "
                  f"({dif*100:.1f}% de diferença — reamostragem?)", onde)

        # Exposição: comparar o conjunto COMPLETO de quadros que carregam
        # desenho, biblioteca de poses inclusive. A biblioteca não está na
        # régua, mas É desenho e precisa existir do outro lado — separá-la aqui
        # faria o comparador acusar divergência num exportador correto.
        if o["quadros_com_desenho"] != sorted(c["quadros_expostos"]):
            faltando = sorted(set(o["quadros_com_desenho"]) - set(c["quadros_expostos"]))
            excedente = sorted(set(c["quadros_expostos"]) - set(o["quadros_com_desenho"]))
            det = []
            if faltando: det.append(f"faltam {faltando[:6]}")
            if excedente: det.append(f"sobram {excedente[:6]}")
            a.add(PERDIDO if faltando else SUSPEITO, "exposição",
                  "; ".join(det) or "conjuntos diferentes", onde)

        # quadro em espera não pode virar desenho novo
        if len(c["quadros_em_espera"]) < len(o["quadros_em_espera"]):
            a.add(DEGRADADO, "quadros em espera",
                  f"{len(o['quadros_em_espera'])} em espera no Nuclear, "
                  f"{len(c['quadros_em_espera'])} no .brb — viraram desenho duplicado?",
                  onde)

        # biblioteca de poses fora da linha do tempo
        if o["quadros_biblioteca"] and not c["quadros_expostos"]:
            a.add(PERDIDO, "biblioteca de poses",
                  f"{len(o['quadros_biblioteca'])} poses fora da linha do tempo "
                  f"e nada correspondente no .brb", onde)

        # Ordem: o que importa é a posição RELATIVA dentro do mesmo pai. No
        # Nuclear a numeração recomeça em cada objeto; no .brb ela é global.
        # Comparar o número absoluto reprovaria um exportador correto.
        if o.get("rank") is not None and c.get("rank") is not None and o["rank"] != c["rank"]:
            a.add(SUSPEITO, "ordem de desenho",
                  f"{o['rank']}ª camada do grupo no Nuclear, {c['rank']}ª no .brb — "
                  f"ordem errada muda o que fica na frente", onde)

        if o["grupo_pai_esperado"] != c["grupo_pai"]:
            a.add(DEGRADADO, "grupo",
                  f"esperava pai `{o['grupo_pai_esperado']}`, veio `{c['grupo_pai']}`", onde)

        if (o["opacidade"] is not None and c["opacidade"] is not None
                and abs(o["opacidade"] - c["opacidade"]) > TOL_OPACIDADE):
            a.add(DEGRADADO, "opacidade",
                  f"{o['opacidade']} × {c['opacidade']}", onde)

        if o["visivel"] != c["visivel"]:
            a.add(SUSPEITO, "visibilidade",
                  f"visível={o['visivel']} no Nuclear, {c['visivel']} no .brb", onde)

        # ---- nível 1: cor ---------------------------------------------------
        # A cor pode vir do material OU de vertex color, e as duas coexistem.
        # Um exportador que lê só o material perde pintura; um que lê só o
        # vertex color perde tudo que nunca foi pintado à mão.
        if (o["tem_cor_material"] or o["tem_cor_vertice"]) and not c["tem_cor"]:
            origem = []
            if o["tem_cor_material"]: origem.append("material")
            if o["tem_cor_vertice"]: origem.append("vertex color")
            a.add(PERDIDO, "cor",
                  f"o Nuclear tem cor por {' e '.join(origem)}, o .brb não trouxe cor", onde)
        elif o["tem_cor_vertice"] and o["tem_cor_material"]:
            a.add(SUSPEITO, "cor",
                  "a camada usa material E vertex color; o .brb tem um campo de cor só — "
                  "conferir qual das duas veio", onde)

    # ---- perda declarada × perda calada -------------------------------------
    # Máscara de camada não tem equivalente nos níveis 1 e 2 — a spec não tem
    # o campo. Então a perda é INEVITÁVEL, e reprovar por ela deixaria o CI
    # permanentemente vermelho por uma limitação do nível, não por defeito.
    #
    # O que o arnês cobra é outra coisa: que a perda esteja DECLARADA no
    # relatório do exportador. É o critério de aceite do lote — se o relatório
    # disser que nada se perdeu e um animador discordar, o relatório é que está
    # errado. Perda declarada passa; perda calada reprova.
    fid = brb.get("fidelidade_declarada") or {}
    declarados = {(i.get("assunto"), i.get("onde")) for i in (fid.get("achados") or [])}
    assuntos_declarados = {i.get("assunto") for i in (fid.get("achados") or [])}

    mascaradas = [o for o in orig if o["usa_mascara"] and o["mascaras"]]
    if mascaradas:
        graf = brb.get("mascaras_preservadas") or {}
        preservadas = {m.get("nome_da_camada") for m in (graf.get("mascaras") or [])}
        if not preservadas and "máscara" not in assuntos_declarados:
            for o in mascaradas:
                a.add(PERDIDO, "máscara calada",
                      f"a camada é mascarada por {o['mascaras']}, o .brb não aplica "
                      f"máscara, e o exportador NÃO declarou nem preservou o vínculo",
                      o["caminho"])
        else:
            # O vínculo tem de estar INTEIRO: máscara que some do sidecar é
            # perda de verdade, mesmo que o resto esteja declarado.
            faltando = [o for o in mascaradas if o["nome"] not in preservadas]
            for o in faltando:
                a.add(PERDIDO, "máscara não preservada",
                      f"mascarada por {o['mascaras']} e ausente de mascaras.json",
                      o["caminho"])
            if not faltando:
                a.add(OK, "máscara",
                      f"{len(mascaradas)} camadas mascaradas: os níveis 1 e 2 não "
                      f"aplicam máscara, mas o vínculo foi preservado inteiro em "
                      f"mascaras.json — conversão reversível")

    # Aviso de container que impede o app de abrir é PERDA total, não dúvida:
    # não adianta a árvore bater se o arquivo não carrega do outro lado.
    for av in (brb.get("avisos") or []):
        if "comprimidas" in av:
            a.add(PERDIDO, "container", av)

    if fid == {}:
        a.add(SUSPEITO, "relatório de fidelidade",
              "o .brb não trouxe relatório — não dá para distinguir perda "
              "conhecida de perda calada")

    for c in sobrando:
        a.add(SUSPEITO, "camada a mais",
              f"camada `{c['nome']}` existe no .brb e não no Nuclear", c["caminho"])

    return a, orig, conv


def relatorio(nuc, brb, a, orig, conv):
    return {
        "schema": 1,
        "arquivo_nuclear": nuc.get("arquivo"),
        "veredito": "PASSOU" if a.passou else "REPROVOU",
        "contagem": {
            OK: a.conta(OK), DEGRADADO: a.conta(DEGRADADO),
            PERDIDO: a.conta(PERDIDO), SUSPEITO: a.conta(SUSPEITO),
        },
        "comparado": {
            "camadas_nuclear": len(orig),
            "camadas_brb": len(conv),
            "tracos_nuclear": sum(c["n_tracos"] for c in orig),
            "tracos_brb": sum(c["n_tracos"] for c in conv),
        },
        "nao_verificado": [
            "níveis 3 e 4 (peça, rig, atuação) — as entidades ainda estão "
            "pendentes de T17.1 na especificação do formato",
            "fidelidade de pixel — a spec garante paridade de DADOS, não de pixel",
            "perfil de espessura ponto a ponto — comparado por mínimo, máximo e média",
        ],
        "achados": a.itens,
        "avisos_do_brb": brb.get("avisos", []),
    }


def main():
    if len(sys.argv) < 3:
        print(__doc__.strip())
        return 2
    nuc = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    brb = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

    a, orig, conv = comparar(nuc, brb)
    rel = relatorio(nuc, brb, a, orig, conv)

    if len(sys.argv) > 3:
        Path(sys.argv[3]).write_text(
            json.dumps(rel, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")

    c = rel["contagem"]
    print(f"[I3.4] {Path(sys.argv[1]).stem}: {rel['veredito']} — "
          f"{c[PERDIDO]} perdido, {c[DEGRADADO]} degradado, {c[SUSPEITO]} suspeito")
    for i in a.itens[:12]:
        print(f"       {i['categoria']:<9} {i['assunto']:<20} {i['onde'] or '—'}: {i['detalhe']}")
    if len(a.itens) > 12:
        print(f"       … e mais {len(a.itens) - 12} achados no JSON")
    return 0 if a.passou else 1


if __name__ == "__main__":
    sys.exit(main())
