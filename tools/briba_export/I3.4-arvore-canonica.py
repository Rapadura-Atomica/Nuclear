"""
I3.4 — árvore canônica de um arquivo do Nuclear, nos níveis 1 e 2 de fidelidade.

Descreve o que **precisa sobreviver** à conversão para `.brb`:

  nível 1 (traço)     geometria de pontos, pressão, espessura, cor
  nível 2 (estrutura) camadas, grupos, nomes, ordem de desenho, exposição por quadro

Não descreve rig nem animação — isso é nível 3/4, e as entidades correspondentes
(`Piece`, `Rig`, `Performance`) ainda estão marcadas como pendentes na
especificação do formato. Medir agora o que ainda vai mudar só produziria
divergência falsa.

A saída é **canônica**: mesma entrada dá exatamente os mesmos bytes. Ordem
estável, floats arredondados, nada de ponteiro de memória ou id de sessão. É o
que permite comparar duas execuções, ou uma execução contra o `.brb` que saiu
dela, sem ruído.

Uso:
    nuclear -b ARQUIVO.blend -P I3.4-arvore-canonica.py -- saida.json
"""
import bpy
import json
import sys
import hashlib

SCHEMA = 1
CASAS = 5           # arredondamento de float: abaixo disso é ruído de precisão
MAX_PONTOS = 4      # amostra de pontos gravada por traço (o resto vira resumo)
LIMIAR_FORA_DA_LINHA = 1000   # quadro além disso é biblioteca de células, não exposição


def r(v):
    """Arredonda para a precisão que a comparação considera significativa."""
    try:
        return round(float(v), CASAS)
    except (TypeError, ValueError):
        return None


def rvec(v):
    try:
        return [r(x) for x in v]
    except TypeError:
        return None


def cor_do_material(ob, indice):
    """(stroke_rgba, fill_rgba) do material naquele slot, ou (None, None).

    A cor de um traço pode vir do MATERIAL ou de vertex color por ponto, e as
    duas coexistem no mesmo arquivo. Ler só uma perde pintura de um jeito que
    não aparece em contagem nenhuma — por isso as duas são gravadas em campos
    separados, nunca fundidas.
    """
    try:
        slots = ob.material_slots
        if indice < 0 or indice >= len(slots):
            return None, None
        mat = slots[indice].material
        gp = getattr(mat, "grease_pencil", None)
        if gp is None:
            return None, None
        traco = rvec(gp.color) if getattr(gp, "show_stroke", True) else None
        fill = rvec(gp.fill_color) if getattr(gp, "show_fill", False) else None
        return traco, fill
    except (AttributeError, IndexError, ReferenceError):
        return None, None


def pontos_do_traco(st):
    """Resumo geométrico + amostra. O traço inteiro viraria um JSON gigante.

    O que a comparação precisa é: quantos pontos, onde começa, onde termina,
    que caixa ocupa, e a assinatura do conjunto. Isso pega deslocamento,
    reamostragem e perda de ponto — que são os modos de falha reais de um
    exportador de geometria.
    """
    pts = list(getattr(st, "points", []))
    n = len(pts)
    if n == 0:
        return {"n": 0}

    pos, pres, rad = [], [], []
    for p in pts:
        try:
            pos.append(tuple(p.position))
        except AttributeError:
            pos.append((0.0, 0.0, 0.0))
        pres.append(float(getattr(p, "pressure", 1.0) or 0.0))
        rad.append(float(getattr(p, "radius", 0.0) or 0.0))

    xs = [p[0] for p in pos]; ys = [p[1] for p in pos]; zs = [p[2] for p in pos]
    # assinatura: pega reordenação e alteração de ponto que a bbox não pegaria
    h = hashlib.sha1()
    for p, pr in zip(pos, pres):
        h.update(f"{p[0]:.5f},{p[1]:.5f},{p[2]:.5f},{pr:.4f};".encode())

    return {
        "n": n,
        "bbox": [[r(min(xs)), r(min(ys)), r(min(zs))],
                 [r(max(xs)), r(max(ys)), r(max(zs))]],
        "inicio": rvec(pos[0]),
        "fim": rvec(pos[-1]),
        "pressao": {"min": r(min(pres)), "max": r(max(pres)),
                    "media": r(sum(pres) / n)},
        "raio": {"min": r(min(rad)), "max": r(max(rad)), "media": r(sum(rad) / n)},
        "amostra": [rvec(p) for p in pos[:MAX_PONTOS]],
        "assinatura": h.hexdigest()[:16],
    }


def cor_de_vertice(desenho, st_idx, n_pontos):
    """Vertex color por ponto, se existir. Devolve None se o arquivo não usa.

    Em GP v3 a cor de vértice vive em atributo do desenho, não no traço. Como
    o nome e a forma do atributo variam entre versões, tenta e desiste em
    silêncio — mas o campo fica no JSON como `null`, que é diferente de ausente:
    diz que foi procurado e não havia.
    """
    try:
        attrs = getattr(desenho, "attributes", None)
        if not attrs:
            return None
        for nome in ("vertex_color", "vertex_colors", ".vertex_color"):
            a = attrs.get(nome)
            if a is None:
                continue
            dados = getattr(a, "data", [])
            if not len(dados):
                continue
            vals = [rvec(getattr(d, "color", getattr(d, "vector", None)) or ()) for d in dados[:8]]
            return {"atributo": nome, "n": len(dados), "amostra": [v for v in vals if v]}
    except (AttributeError, TypeError, KeyError, ReferenceError):
        pass
    return None


def camadas_do_objeto(ob):
    dados = getattr(ob, "data", None)
    if dados is None or not hasattr(dados, "layers"):
        return None

    # Identidade de desenho: dois quadros apontando para o MESMO desenho é
    # quadro em espera (held), não desenho novo. Sem isso o exportador pode
    # duplicar a exposição e o relatório diria que está tudo certo.
    #
    # `data.drawings` não existe em toda versão do GP v3 — nesta build não
    # existe. O ponteiro do próprio desenho existe sempre, então o mapa é
    # montado na ordem em que os desenhos aparecem. O índice é local ao
    # objeto e estável para a mesma entrada, que é o que a comparação pede.
    id_desenho = {}

    def ref_do_desenho(desenho):
        try:
            ptr = desenho.as_pointer()
        except (AttributeError, TypeError):
            return None
        if ptr not in id_desenho:
            id_desenho[ptr] = len(id_desenho)
        return id_desenho[ptr]

    camadas = []
    for ordem, lay in enumerate(dados.layers):
        quadros = []
        for fr in sorted(lay.frames, key=lambda f: f.frame_number):
            desenho = getattr(fr, "drawing", None)
            ref = ref_do_desenho(desenho) if desenho is not None else None

            tracos = []
            if desenho is not None:
                for i, st in enumerate(getattr(desenho, "strokes", [])):
                    mat_idx = int(getattr(st, "material_index", 0) or 0)
                    traco_rgba, fill_rgba = cor_do_material(ob, mat_idx)
                    g = pontos_do_traco(st)
                    tracos.append({
                        "i": i,
                        "material_slot": mat_idx,
                        "cor_material_traco": traco_rgba,
                        "cor_material_fill": fill_rgba,
                        "cor_vertice": cor_de_vertice(desenho, i, g.get("n", 0)),
                        "ciclico": bool(getattr(st, "cyclic", False)),
                        "geometria": g,
                    })

            quadros.append({
                "quadro": int(fr.frame_number),
                "tipo": str(getattr(fr, "keyframe_type", "KEYFRAME")),
                "desenho_ref": ref,
                "n_tracos": len(tracos),
                "tracos": tracos,
            })

        # quadro em espera: reaparece um desenho que já foi exposto antes
        vistos, em_espera = set(), []
        for q in quadros:
            if q["desenho_ref"] is None:
                continue
            if q["desenho_ref"] in vistos:
                em_espera.append(q["quadro"])
            vistos.add(q["desenho_ref"])

        # Quadro muito além do fim da cena não é exposição: é biblioteca de
        # poses estacionada fora da linha do tempo (convenção do estúdio — as
        # poses ficam em 100001, 100002… para não aparecerem na régua e serem
        # chamadas por troca de desenho).
        #
        # A QUANTIDADE é pequena: são as poses da peça, quase sempre 2 a 5, e
        # dezenas só em biblioteca de boca ou mão. O que é grande é o NÚMERO do
        # quadro, e é daí que vem o risco: um exportador que percorre de
        # frame_start a frame_end perde a biblioteca inteira, e um que tome o
        # maior frame_number como duração gera uma linha de cem mil quadros.
        # Por isso essas poses são marcadas à parte da exposição de verdade.
        fim_cena = bpy.context.scene.frame_end
        fora_da_linha = [q["quadro"] for q in quadros if q["quadro"] > fim_cena + LIMIAR_FORA_DA_LINHA]

        camadas.append({
            "ordem_de_desenho": ordem,
            "nome": lay.name,
            "quadros_fora_da_linha": fora_da_linha,
            "grupo_pai": getattr(getattr(lay, "parent_group", None), "name", None),
            "visivel": bool(getattr(lay, "hide", False) is False),
            "travada": bool(getattr(lay, "lock", False)),
            "opacidade": r(getattr(lay, "opacity", 1.0)),
            "modo_de_mistura": str(getattr(lay, "blend_mode", "REGULAR")),
            "usa_mascara": bool(getattr(lay, "use_masks", False)),
            "mascaras": sorted(m.name for m in getattr(lay, "mask_layers", [])),
            "n_quadros": len(quadros),
            "quadros_expostos": [q["quadro"] for q in quadros],
            "quadros_em_espera": em_espera,
            "quadros": quadros,
        })

    grupos = []
    try:
        for g in dados.layer_groups:
            grupos.append({
                "nome": g.name,
                "pai": getattr(getattr(g, "parent_group", None), "name", None),
            })
    except AttributeError:
        pass

    return {"n_camadas": len(camadas), "grupos": sorted(grupos, key=lambda x: x["nome"]),
            "camadas": camadas}


def main():
    destino = sys.argv[-1]
    cena = bpy.context.scene

    objetos = []
    for ob in sorted(bpy.data.objects, key=lambda o: o.name):
        if ob.type not in ("GREASEPENCIL", "GPENCIL"):
            continue
        est = camadas_do_objeto(ob)
        if est is None:
            continue
        objetos.append({
            "nome": ob.name,
            "oculto": bool(ob.hide_render),
            "matriz_mundo": [r(v) for linha in ob.matrix_world for v in linha],
            **est,
        })

    total_tracos = sum(q["n_tracos"] for o in objetos for c in o["camadas"] for q in c["quadros"])
    total_pontos = sum(t["geometria"].get("n", 0)
                       for o in objetos for c in o["camadas"]
                       for q in c["quadros"] for t in q["tracos"])

    saida = {
        "schema": SCHEMA,
        "arquivo": bpy.data.filepath,
        "versao_nuclear": bpy.app.version_string,
        "versao_do_arquivo": ".".join(str(x) for x in bpy.data.version),
        "cena": {
            "nome": cena.name,
            "quadros": [cena.frame_start, cena.frame_end],
            "fps": cena.render.fps,
            "resolucao": [cena.render.resolution_x, cena.render.resolution_y],
        },
        "resumo": {
            "n_objetos_gp": len(objetos),
            "n_camadas": sum(o["n_camadas"] for o in objetos),
            "n_grupos": sum(len(o["grupos"]) for o in objetos),
            "n_tracos": total_tracos,
            "n_pontos": total_pontos,
            "n_quadros_em_espera": sum(len(c["quadros_em_espera"])
                                       for o in objetos for c in o["camadas"]),
            "n_quadros_fora_da_linha": sum(len(c["quadros_fora_da_linha"])
                                           for o in objetos for c in o["camadas"]),
        },
        "objetos": objetos,
    }

    with open(destino, "w", encoding="utf-8") as fh:
        json.dump(saida, fh, ensure_ascii=False, indent=1, sort_keys=True)

    res = saida["resumo"]
    print(f"[I3.4] {bpy.path.basename(bpy.data.filepath)}: "
          f"{res['n_objetos_gp']} objetos, {res['n_camadas']} camadas, "
          f"{res['n_tracos']} traços, {res['n_pontos']} pontos, "
          f"{res['n_quadros_em_espera']} em espera, "
          f"{res['n_quadros_fora_da_linha']} fora da linha -> {destino}")


if __name__ == "__main__":
    main()
