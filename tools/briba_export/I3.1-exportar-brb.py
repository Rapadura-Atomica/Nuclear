"""
I3.1 — exporta a cena do Nuclear para `.brb`, níveis 1 e 2 de fidelidade.

  nível 1 (traço)     geometria de pontos, pressão, espessura, cor
  nível 2 (estrutura) camadas, grupos, nomes, ordem de desenho, exposição por quadro

Escrito **a partir da especificação** (`brb-format.md`, validada em 20/08/2026),
nunca a partir do código do Briba. A especificação atravessa a fronteira entre os
dois lados; código, nunca — I0.1, regra 4.

Não exporta peça, rig nem atuação: são níveis 3 e 4, e as entidades
correspondentes continuam marcadas como pendentes de T17.1 na própria spec.
Escrevê-las agora seria construir sobre alvo que ainda vai mudar.

Uso:
    nuclear -b ARQUIVO.blend -P I3.1-exportar-brb.py -- saida.brb
"""
import bpy
import json
import os
import struct
import sys
import zipfile
from pathlib import Path

VERSAO_ESQUEMA = 1

# O número mágico é a única coisa que decide se o Briba aceita ou recusa o
# arquivo antes de olhar qualquer conteúdo — e a spec o cita **uma vez**, numa
# tabela, sem dizer o valor. O Briba ainda está sendo escrito, então também não
# dá para tirar o valor de um arquivo que ele mesmo salvou.
#
# Por isso o valor NÃO é constante de código: vem de `BRB_MAGIC`, e o padrão
# abaixo é declaradamente um chute. O dia em que o lado do Briba fixar o valor,
# nada aqui muda — e o acervo já convertido também não precisa reconverter:
# `I3.1-recarimbar-brb.py` troca o carimbo no lugar, em segundos por arquivo.
NUMERO_MAGICO = os.environ.get("BRB_MAGIC", "BRB\x00")
MAGICO_CONFIRMADO = "BRB_MAGIC" in os.environ

# Limiar de profundidade: o `.brb` é 2D e o Grease Pencil é 3D. Traço mais
# fundo que isto perde informação de verdade na projeção, e o relatório de
# fidelidade precisa dizer. Abaixo disso é ruído de plano de desenho.
LIMIAR_PROFUNDIDADE = 1e-4

# Pincéis que a spec fixa (T2.5). O GP não guarda "qual pincel desenhou isto",
# então a escolha é uma aproximação — registrada como tal no relatório.
PINCEL_PADRAO = "InkPen"

# O container é ZIP, mas **sem compressão**: o leitor do Briba 0.0.1 recusa
# entrada comprimida ("entrada comprimida (método 8); este leitor só aceita
# armazenamento direto"). A spec não diz nada sobre método de compressão — é
# lacuna dela, e enquanto não fechar, gravar armazenado é o que abre dos dois
# lados. Descoberto abrindo um `.brb` exportado no app de verdade, em 21/08.
COMPRESSAO = zipfile.ZIP_STORED


# --------------------------------------------------------------------------- #
# CBOR — codificador mínimo (RFC 8949), o mesmo subconjunto do leitor do I3.4
# --------------------------------------------------------------------------- #

def enc(v):
    if v is None:
        return b"\xf6"
    if v is True:
        return b"\xf5"
    if v is False:
        return b"\xf4"
    if isinstance(v, int):
        maior, n = (0, v) if v >= 0 else (1, -1 - v)
        return _cabeca(maior, n)
    if isinstance(v, float):
        return b"\xfb" + struct.pack(">d", v)
    if isinstance(v, str):
        b = v.encode("utf-8")
        return _cabeca(3, len(b)) + b
    if isinstance(v, bytes):
        return _cabeca(2, len(v)) + v
    if isinstance(v, (list, tuple)):
        return _cabeca(4, len(v)) + b"".join(enc(x) for x in v)
    if isinstance(v, dict):
        return _cabeca(5, len(v)) + b"".join(enc(k) + enc(x) for k, x in v.items())
    raise TypeError(f"não sei codificar {type(v)}")


def _cabeca(maior, n):
    base = maior << 5
    if n < 24:
        return bytes([base | n])
    if n < 256:
        return bytes([base | 24, n])
    if n < 65536:
        return bytes([base | 25]) + struct.pack(">H", n)
    if n < 2 ** 32:
        return bytes([base | 26]) + struct.pack(">I", n)
    return bytes([base | 27]) + struct.pack(">Q", n)


# --------------------------------------------------------------------------- #

class Relatorio:
    """Junta as decisões de conversão para o I3.2 consumir depois."""

    def __init__(self):
        self.itens = []

    def add(self, categoria, assunto, detalhe, onde=None):
        self.itens.append({"categoria": categoria, "assunto": assunto,
                           "detalhe": detalhe, "onde": onde})

    def resumo(self):
        from collections import Counter
        return dict(Counter(i["categoria"] for i in self.itens))


def cor_do_traco(ob, st, rel, onde):
    """Decide a cor única que o `.brb` guarda, e registra o que se perdeu.

    A cor pode vir do MATERIAL (cor de traço, cor de preenchimento) ou de
    VERTEX COLOR por ponto, e as duas coexistem. O `.brb` tem um campo de cor
    só, então a fusão é inevitável — o que não pode é ser silenciosa.
    """
    idx = int(getattr(st, "material_index", 0) or 0)
    traco = fill = None
    try:
        slots = ob.material_slots
        if 0 <= idx < len(slots) and slots[idx].material:
            gp = getattr(slots[idx].material, "grease_pencil", None)
            if gp is not None:
                if getattr(gp, "show_stroke", True):
                    traco = [round(float(c), 6) for c in gp.color]
                if getattr(gp, "show_fill", False):
                    fill = [round(float(c), 6) for c in gp.fill_color]
    except (AttributeError, IndexError, ReferenceError):
        pass

    if traco and fill:
        rel.add("SUSPEITO", "cor",
                "o material tem cor de traço E de preenchimento; o .brb guarda "
                "uma cor por traço — exportada a de traço", onde)
        return traco
    if traco:
        return traco
    if fill:
        return fill
    rel.add("SUSPEITO", "cor", "traço sem cor de material — exportado preto", onde)
    return [0.0, 0.0, 0.0, 1.0]


def pontos_para_buffer(st, matriz, rel, onde):
    """Projeta o traço para 2D e empacota os pontos.

    O plano de desenho do estúdio é X-Z com Y≈0, então a projeção é
    (x, z) -> (x, y). Isso foi conferido no acervo: 41 de 45 objetos do
    uma das referências são planos, e os quatro que não são perdem profundidade aqui —
    por isso a perda é medida e reportada, não presumida como zero.

    Formato: 4 floats little-endian por ponto — x, y, pressão, tempo.
    `tilt` é opcional na spec e o GP não o expõe por ponto, então fica de fora.
    """
    pts = list(getattr(st, "points", []))
    if not pts:
        return b"", 0

    dados = bytearray()
    ys = []
    for i, p in enumerate(pts):
        try:
            mundo = matriz @ p.position
        except (AttributeError, TypeError, ValueError):
            mundo = (0.0, 0.0, 0.0)
        ys.append(float(mundo[1]))
        pressao = float(getattr(p, "pressure", 1.0) or 0.0)
        # tempo relativo: o GP não guarda tempo por ponto neste formato, então
        # vai o índice normalizado — serve para replay e estabilização
        tempo = i / max(len(pts) - 1, 1)
        dados += struct.pack("<ffff", float(mundo[0]), float(mundo[2]), pressao, tempo)

    profundidade = max(ys) - min(ys)
    if profundidade > LIMIAR_PROFUNDIDADE:
        rel.add("DEGRADADO", "profundidade",
                f"traço com {profundidade:.4f} de extensão em Y foi achatado — "
                f"o .brb é 2D", onde)

    return bytes(dados), len(pts)


def perfil_de_espessura(st):
    """A spec pede uma curva serializável. O GP guarda raio por ponto, então a
    curva é a série de raios — amostrada para não inflar o CBOR."""
    pts = list(getattr(st, "points", []))
    if not pts:
        return []
    raios = [round(float(getattr(p, "radius", 0.0) or 0.0), 6) for p in pts]
    if len(raios) <= 16:
        return raios
    passo = len(raios) / 16.0
    return [raios[int(i * passo)] for i in range(16)]


def exportar(destino):
    cena = bpy.context.scene
    rel = Relatorio()

    camadas = []
    buffers = bytearray()
    mascaras = []
    n_tracos = n_pontos = 0

    objetos = [o for o in sorted(bpy.data.objects, key=lambda x: x.name)
               if o.type in ("GREASEPENCIL", "GPENCIL")]

    for ob in objetos:
        dados = getattr(ob, "data", None)
        if dados is None or not hasattr(dados, "layers"):
            continue

        # O objeto GP vira um GRUPO: a spec tem árvore de camadas e não tem
        # objeto, então sem isto duas camadas `linha` de peças diferentes
        # colidiriam pelo nome.
        gid = f"obj:{ob.name}"
        camadas.append({
            "id": gid, "name": ob.name, "parent": None,
            "order": len(camadas),
            "visible": not bool(ob.hide_render), "locked": False,
            "opacity": 1.0, "blend_mode": "Normal",
            "content": {"Group": None},
        })

        matriz = ob.matrix_world
        grupos_de_camada = {}
        try:
            for g in dados.layer_groups:
                sub = f"grp:{ob.name}:{g.name}"
                grupos_de_camada[g.name] = sub
                camadas.append({
                    "id": sub, "name": g.name, "parent": gid,
                    "order": len(camadas), "visible": True, "locked": False,
                    "opacity": 1.0, "blend_mode": "Normal",
                    "content": {"Group": None},
                })
        except AttributeError:
            pass

        # identidade de desenho: quadro que reexpõe um desenho já usado vira
        # `Held`, com referência — nunca `Drawn` duplicado
        primeiro_quadro = {}

        for lay in dados.layers:
            onde = f"{ob.name}/{lay.name}"
            quadros = []

            for fr in sorted(lay.frames, key=lambda f: f.frame_number):
                desenho = getattr(fr, "drawing", None)
                if desenho is None:
                    continue
                try:
                    chave = (lay.name, desenho.as_pointer())
                except (AttributeError, TypeError):
                    chave = None

                if chave is not None and chave in primeiro_quadro:
                    quadros.append({"index": int(fr.frame_number),
                                    "content": {"Held": {"reference": primeiro_quadro[chave]}}})
                    continue
                if chave is not None:
                    primeiro_quadro[chave] = int(fr.frame_number)

                tracos = []
                for st in getattr(desenho, "strokes", []):
                    bruto, n = pontos_para_buffer(st, matriz, rel, onde)
                    if n == 0:
                        continue
                    offset = len(buffers)
                    buffers += bruto
                    tracos.append({
                        "id": f"{onde}:{fr.frame_number}:{len(tracos)}",
                        "points": {"offset": offset, "size": n},
                        "brush": PINCEL_PADRAO,
                        "thickness_profile": perfil_de_espessura(st),
                        "color": cor_do_traco(ob, st, rel, onde),
                        "smoothing": 0.0,
                        "stabilizer": None,
                        "closed": bool(getattr(st, "cyclic", False)),
                    })
                    n_tracos += 1
                    n_pontos += n

                quadros.append({"index": int(fr.frame_number),
                                "content": {"Drawn": tracos}})

            pai = grupos_de_camada.get(
                getattr(getattr(lay, "parent_group", None), "name", None), gid)
            camadas.append({
                "id": f"lay:{ob.name}:{lay.name}",
                "name": lay.name,
                "parent": pai,
                "order": len(camadas),
                "visible": not bool(getattr(lay, "hide", False)),
                "locked": bool(getattr(lay, "lock", False)),
                "opacity": round(float(getattr(lay, "opacity", 1.0)), 6),
                "blend_mode": "Normal",
                "content": {"Drawing": quadros},
            })

            if str(getattr(lay, "blend_mode", "REGULAR")) != "REGULAR":
                rel.add("DEGRADADO", "modo de mistura",
                        f"camada usa `{lay.blend_mode}`; a spec começa só com "
                        f"`Normal` (T2.7)", onde)
            # Máscara de camada não existe nos níveis 1 e 2 da spec, mas a
            # informação NÃO precisa se perder por causa disso: vai inteira
            # para `mascaras.json` dentro do próprio container. Assim a
            # conversão é reversível — quando o formato ganhar máscara, uma
            # reconversão aplica sem precisar do `.blend` original.
            #
            # Por isso é DEGRADADO (carregada, não aplicada) e não PERDIDO.
            # Cuidados que o acervo obriga: `invert` é o defeito clássico da
            # pupila, e `object` existe porque máscara pode atravessar objetos.
            mask_list = [m for m in getattr(lay, "mask_layers", []) if not getattr(m, "hide", False)]
            if getattr(lay, "use_masks", False) and mask_list:
                mascaras.append({
                    "camada": f"lay:{ob.name}:{lay.name}",
                    "objeto": ob.name,
                    "nome_da_camada": lay.name,
                    "mascarada_por": [{
                        "camada": m.name,
                        "objeto": getattr(getattr(m, "object", None), "name", ob.name),
                        "invertida": bool(getattr(m, "invert", False)),
                        "auto_patch": bool(getattr(m, "use_auto_patch", False)),
                    } for m in mask_list],
                })
                rel.add("DEGRADADO", "máscara",
                        f"mascarada por {[m.name for m in mask_list]} — os níveis 1 e 2 "
                        f"do .brb não aplicam máscara; o vínculo foi preservado em "
                        f"mascaras.json e a camada vai renderizar sem recorte", onde)

    documento = {
        "frame_start": int(cena.frame_start),
        "frame_end": int(cena.frame_end),
        "frame_rate": int(cena.render.fps),
        "resolution": [int(cena.render.resolution_x), int(cena.render.resolution_y)],
        "layers": camadas,
    }

    if not MAGICO_CONFIRMADO:
        rel.add("SUSPEITO", "número mágico",
                f"o manifesto foi carimbado com {NUMERO_MAGICO!r}, que é uma "
                f"suposição: a especificação cita o número mágico sem dar o "
                f"valor. Se o Briba recusar o arquivo dizendo que ele não é um "
                f".brb, é isto — e o conserto é `I3.1-recarimbar-brb.py`, sem "
                f"reconverter")

    manifesto = {
        "magic": NUMERO_MAGICO,
        "schema_version": VERSAO_ESQUEMA,
        "project": {
            "name": bpy.path.display_name_from_filepath(bpy.data.filepath) or "sem-nome",
            "origem": f"Nuclear {bpy.app.version_string}",
            "arquivo_de_origem": bpy.data.filepath,
        },
    }

    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destino, "w", COMPRESSAO) as z:
        z.writestr("manifest.json", json.dumps(manifesto, ensure_ascii=False))
        z.writestr("document.cbor", enc(documento))
        z.writestr("strokes/0000.bin", bytes(buffers))
        z.writestr("thumbnail.png", b"\x89PNG\r\n\x1a\n")
        # a pasta de atuações fica vazia: é nível 3/4, pendente de T17.1.
        # `performances/` é o nome da spec; o rename ainda não foi refletido
        # no Anexo A e é pergunta aberta para o lado do Briba.
        z.writestr("performances/.vazio", b"")
        if mascaras:
            z.writestr("mascaras.json", json.dumps(
                {"schema": 1,
                 "nota": "Máscara de camada não tem equivalente nos níveis 1 e 2 "
                         "do .brb. O vínculo está aqui inteiro para que a conversão "
                         "seja reversível — nenhuma informação foi destruída, ela só "
                         "não é aplicada. Ver I3.4-Referencias-e-Comparacao.md.",
                 "n_camadas_mascaradas": len(mascaras),
                 "mascaras": mascaras}, ensure_ascii=False, indent=1))
        z.writestr("relatorio-de-fidelidade.json",
                   json.dumps({"schema": 1, "resumo": rel.resumo(),
                               "achados": rel.itens}, ensure_ascii=False, indent=1))

    return {
        "camadas": len(camadas),
        "tracos": n_tracos,
        "pontos": n_pontos,
        "bytes_de_pontos": len(buffers),
        "mascaras_preservadas": len(mascaras),
        "fidelidade": rel.resumo(),
    }


def main():
    destino = sys.argv[-1]
    if not destino.endswith(".brb"):
        print("[I3.1] ERRO: informe o destino .brb após ' -- '")
        return 2
    r = exportar(destino)
    print(f"[I3.1] {bpy.path.basename(bpy.data.filepath)} -> {destino}: "
          f"{r['camadas']} camadas, {r['tracos']} traços, {r['pontos']} pontos, "
          f"{r['bytes_de_pontos']} B de geometria, "
          f"{r['mascaras_preservadas']} máscaras preservadas | fidelidade: {r['fidelidade']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
