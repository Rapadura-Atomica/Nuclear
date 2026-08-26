#!/usr/bin/env python3
"""
I3.7 — transcodifica um `.brb` deste lado para o formato que o aplicativo REALMENTE lê.

Existe por causa de um achado de 25/08: a especificação e a implementação do Briba
descrevem formatos diferentes. O exportador deste lado seguiu a especificação, como
manda a separação de lados — e o aplicativo recusa o resultado, porque procura outro
campo, outra estrutura e outra passada de bytes. O mapa completo das diferenças está
em `I3-Formato-Real-do-brb.md`.

Isto **não substitui** o exportador. É a ponte que permite finalmente responder a
pergunta que o bloco 3 nunca pôde responder: *o aplicativo abre o nosso acervo?* Sem
ela, cada tentativa custava um palpite sobre o container.

O que ele traduz:

  manifesto        `magic`/`schema_version` -> `format: "brb"` e camelCase
  documento        árvore de camadas -> projeto achatado, coleções por id
  desenho          quadro embutido na camada -> entidade própria + `exposures`
  traço            vetor de cor -> objeto {r,g,b,a}; `pointsKey` por traço
  pontos           4 f32 (16 B) -> 6 f32 (24 B): x, y, pressão, tiltX, tiltY, t

O que ele NÃO tem como traduzir, e declara:

  `closed`         área preenchida não é campo de traço no modelo real; vira contorno
  grupos           o modelo real é achatado por `rootLayers`; os grupos somem
  máscaras         já não existiam nos níveis 1 e 2

Uso:
  ./I3.7-transcodificar.py entrada.brb saida.brb
  ./I3.7-transcodificar.py entrada.brb saida.brb --pinceis DE.brb
"""

import argparse
import importlib.util
import json
import struct
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
BYTES_NOSSOS = 16      # x, y, pressão, tempo
BYTES_DELES = 24       # x, y, pressão, tiltX, tiltY, t
LADO_CANVAS = (1920, 1080)


def carregar(nome, mod):
    spec = importlib.util.spec_from_file_location(mod, str(RAIZ / nome))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


L = carregar("I3.4-ler-brb.py", "ler_brb_para_transcodificar")


# --------------------------------------------------------------------------- #

def pinceis_padrao(caminho_modelo):
    """As definições de pincel vêm de um arquivo escrito pelo próprio aplicativo.

    Inventar pincel aqui seria repetir o erro que trouxe este roteiro: supor a forma
    de uma estrutura do outro lado. Se houver um `.brb` de referência, os pincéis
    dele viajam inteiros; senão, sai um mínimo declarado.
    """
    if caminho_modelo and Path(caminho_modelo).exists():
        with zipfile.ZipFile(caminho_modelo) as z:
            doc = L.cbor_para_python(z.read("document.cbor"))
        pin = doc.get("brushes")
        if isinstance(pin, dict) and pin:
            return pin, sorted(pin)[0]
    return ({"brush_ink": {"id": "brush_ink", "kind": "ink-brush", "name": "Nanquim",
                           "width": 12, "erases": False}}, "brush_ink")


def enc_cbor(v):
    """Codificador CBOR — o mesmo subconjunto do resto das ferramentas."""
    if v is None:
        return b"\xf6"
    if v is True:
        return b"\xf5"
    if v is False:
        return b"\xf4"
    if isinstance(v, int) and not isinstance(v, bool):
        maior, n = (0, v) if v >= 0 else (1, -1 - v)
        if n < 24:
            return bytes([(maior << 5) | n])
        if n < 256:
            return bytes([(maior << 5) | 24, n])
        if n < 65536:
            return bytes([(maior << 5) | 25]) + struct.pack(">H", n)
        if n < 2**32:
            return bytes([(maior << 5) | 26]) + struct.pack(">I", n)
        return bytes([(maior << 5) | 27]) + struct.pack(">Q", n)
    if isinstance(v, float):
        return b"\xfb" + struct.pack(">d", v)
    if isinstance(v, str):
        b = v.encode("utf-8")
        return _pref(0x60, 0x78, len(b)) + b
    if isinstance(v, (list, tuple)):
        return _pref(0x80, 0x98, len(v)) + b"".join(enc_cbor(x) for x in v)
    if isinstance(v, dict):
        # Chave de mapa vai em ORDEM CANÔNICA, pelos bytes da chave codificada.
        # Não é preciosismo: o leitor do outro lado recusa com "recurso que este app
        # ainda não lê: chaves de mapa fora da ordem canônica", e diz o deslocamento
        # exato. Para texto curto o primeiro byte já carrega o comprimento, então a
        # ordem sai por tamanho e depois alfabética — que é exatamente a ordem em que
        # o arquivo escrito pelo próprio aplicativo aparece (`id, fps, name, rigs,
        # audio, width, assets, …`).
        itens = sorted(((enc_cbor(k), x) for k, x in v.items()), key=lambda kv: kv[0])
        return _pref(0xA0, 0xB8, len(v)) + b"".join(k + enc_cbor(x) for k, x in itens)
    raise TypeError(f"não sei codificar {type(v)}")


class ForaDaOrdem(Exception):
    pass


def conferir_ordem_canonica(d):
    """Percorre o CBOR emitido e cobra ordem canônica de chave de mapa.

    O leitor do outro lado recusa com *"chaves de mapa fora da ordem canônica em X
    (em document.cbor+N)"*, e nada na especificação pede isso. Um codificador que
    ordena e um arnês que confere são coisas diferentes: o primeiro pode ter um
    caminho que escapa da ordenação, e aí o arquivo sai do lote errado e ninguém
    percebe até alguém abrir. Conferir o que FOI escrito custa microssegundos.
    """
    i = 0

    def tam(info):
        nonlocal i
        if info < 24:
            return info
        if info == 24:
            v = d[i]; i += 1; return v
        if info == 25:
            v = struct.unpack_from(">H", d, i)[0]; i += 2; return v
        if info == 26:
            v = struct.unpack_from(">I", d, i)[0]; i += 4; return v
        if info == 27:
            v = struct.unpack_from(">Q", d, i)[0]; i += 8; return v
        raise ForaDaOrdem(f"tamanho não suportado {info} em +{i}")

    def item():
        nonlocal i
        b = d[i]; i += 1
        maior, info = b >> 5, b & 0x1F
        if maior in (0, 1):
            tam(info)
        elif maior in (2, 3):
            # `i += tam(info)` seria um bug sutil: Python lê `i` ANTES de chamar
            # `tam()`, e `tam()` avança `i` ao ler o byte de comprimento — o avanço
            # se perderia. Só aparece em texto de 24 bytes ou mais, que é onde o
            # comprimento deixa de caber no cabeçalho. Custou 72 falsos positivos
            # num lote de 381: exatamente os arquivos de nome longo.
            n = tam(info)
            i += n
        elif maior == 4:
            for _ in range(tam(info)):
                item()
        elif maior == 5:
            n = tam(info)
            ant = None
            for _ in range(n):
                k0 = i
                item()
                chave = d[k0:i]
                if ant is not None and chave < ant:
                    nome = d[k0 + 1:i].decode("utf-8", "replace")
                    raise ForaDaOrdem(f"chave {nome!r} fora da ordem canônica "
                                      f"(document.cbor+{k0})")
                ant = chave
                item()
        elif maior == 6:
            tam(info); item()
        elif maior == 7:
            if info == 25: i += 2
            elif info == 26: i += 4
            elif info == 27: i += 8
            elif info >= 24: i += 1
        else:
            raise ForaDaOrdem(f"tipo {maior}")
    item()


def _pref(curto, um_byte, n):
    if n < 24:
        return bytes([curto | n])
    if n < 256:
        return bytes([um_byte, n])
    return bytes([um_byte + 1]) + struct.pack(">H", n)


def ler_nosso(caminho):
    """Devolve (documento, buffer de pontos) do `.brb` deste lado."""
    with zipfile.ZipFile(caminho) as z:
        nomes = z.namelist()
        doc = L.cbor_para_python(z.read("document.cbor"))
        buf = b"".join(z.read(n) for n in sorted(nomes)
                       if n.startswith("strokes/") and n.endswith(".bin"))
    return doc, buf


def pontos_de(buf, off, n):
    fim = off + n * BYTES_NOSSOS
    if off < 0 or fim > len(buf):
        return []
    return [struct.unpack_from("<ffff", buf, off + i * BYTES_NOSSOS)
            for i in range(n)]


def cor_objeto(cor):
    """Vetor [r,g,b,a] -> objeto {r,g,b,a}. Sem tocar no espaço de cor: essa
    lacuna continua aberta, e converter aqui seria escondê-la."""
    if not cor:
        return {"r": 0.0, "g": 0.0, "b": 0.0, "a": 1.0}
    c = list(cor) + [1.0] * (4 - len(cor))
    return {"r": float(c[0]), "g": float(c[1]), "b": float(c[2]), "a": float(c[3])}


def escala_para_canvas(todos, largura, altura, margem=0.08):
    """O desenho do Nuclear vive em unidades de cena, na casa das unidades; o canvas
    do aplicativo é de 1920x1080 em pixels. Sem reescalar, o personagem inteiro cabe
    num pixel — e o teste visual não diria nada.

    Devolve uma função de projeção, e ela é a ÚNICA transformação geométrica: nada de
    reamostrar, nada de mexer em ordem de ponto.
    """
    xs = [p[0] for p in todos]
    ys = [p[1] for p in todos]
    if not xs:
        return (lambda x, y: (x, y)), 1.0
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    lx, ly = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    esc = min(largura * (1 - 2 * margem) / lx, altura * (1 - 2 * margem) / ly)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

    def proj(x, y):
        # Y do Nuclear cresce para cima; o do canvas, para baixo.
        return (largura / 2 + (x - cx) * esc, altura / 2 - (y - cy) * esc)
    return proj, esc


# --------------------------------------------------------------------------- #

def transcodificar(entrada, saida, modelo_pinceis, agora_ms):
    doc, buf = ler_nosso(entrada)
    camadas = L.campo(doc, "layers", "camadas", padrao=[]) or []
    largura, altura = LADO_CANVAS
    fps = int(L.campo(doc, "frame_rate", "fps", padrao=12) or 12)

    # Primeira passada: junta todos os pontos, para achar a escala de uma vez só.
    cru = []
    for c in camadas:
        cont = L.campo(c, "content", "conteudo")
        if not (L.conteudo_tipo(cont) or "").lower().startswith("drawing"):
            continue
        for fr in (L.conteudo_carga(cont) or []):
            fc = L.campo(fr, "content", "conteudo")
            if not (L.conteudo_tipo(fc) or "").lower().startswith("drawn"):
                continue
            for t in (L.conteudo_carga(fc) or []):
                pt = L.campo(t, "points", "pontos", padrao={}) or {}
                off, n = L.campo(pt, "offset"), L.campo(pt, "size", "n")
                if off is None or not n:
                    continue
                cru.extend(pontos_de(buf, int(off), int(n)))
    proj, esc = escala_para_canvas(cru, largura, altura)

    pinceis, pincel_padrao = pinceis_padrao(modelo_pinceis)
    layers, drawings, raizes, bins = {}, {}, [], {}
    n_traco = 0
    fechados = 0

    for i, c in enumerate(camadas):
        cont = L.campo(c, "content", "conteudo")
        if not (L.conteudo_tipo(cont) or "").lower().startswith("drawing"):
            continue    # grupo: o modelo real é achatado por rootLayers
        lid = f"layer_{i:04d}"
        exposicoes = []
        for fr in (L.conteudo_carga(cont) or []):
            fc = L.campo(fr, "content", "conteudo")
            quadro = int(L.campo(fr, "index", "quadro", padrao=0) or 0)
            if not (L.conteudo_tipo(fc) or "").lower().startswith("drawn"):
                continue
            did = f"draw_{len(drawings):04d}"
            tracos = []
            for t in (L.conteudo_carga(fc) or []):
                pt = L.campo(t, "points", "pontos", padrao={}) or {}
                off, n = L.campo(pt, "offset"), L.campo(pt, "size", "n")
                if off is None or not n:
                    continue
                pts = pontos_de(buf, int(off), int(n))
                if not pts:
                    continue
                if len(pts) == 1:
                    # Traço de UM ponto é um pontinho, e é marca de verdade: num
                    # personagem medido são 14 de 296, e o X máximo do desenho
                    # inteiro pertencia a um deles. Descartar encolhia a caixa e
                    # perdia a marca — calado, porque contagem de traço e de ponto
                    # continuavam quase iguais. O próprio aplicativo mostra a forma
                    # certa: o toque que ele gravou saiu com DOIS pontos idênticos,
                    # não um. Duplicar preserva a marca e é a forma que ele escreve.
                    pts = [pts[0], pts[0]]
                if bool(L.campo(t, "closed", "fechado", padrao=False)):
                    fechados += 1
                chave = f"strokes/{n_traco:06d}.bin"
                dados = bytearray()
                xs, ys = [], []
                for (x, y, pressao, tempo) in pts:
                    px, py = proj(x, y)
                    xs.append(px); ys.append(py)
                    # tiltX e tiltY não existem do lado do Nuclear: saem zero, que é
                    # o mesmo valor que o aplicativo escreve quando não há caneta.
                    dados += struct.pack("<ffffff", px, py, float(pressao),
                                         0.0, 0.0, float(tempo))
                bins[chave] = bytes(dados)
                tracos.append({
                    "id": f"stroke_{n_traco:06d}",
                    "color": cor_objeto(L.campo(t, "color", "cor")),
                    "width": 6,
                    "bounds": {"x": min(xs), "y": min(ys),
                               "w": max(xs) - min(xs), "h": max(ys) - min(ys)},
                    "erases": False,
                    "brushId": pincel_padrao,
                    "pointsKey": chave,
                    "pointCount": len(pts),
                })
                n_traco += 1
            if not tracos:
                continue
            drawings[did] = {"id": did, "strokes": tracos}
            exposicoes.append({"frame": quadro, "drawingId": did})

        if not exposicoes:
            continue
        layers[lid] = {
            "id": lid, "kind": "draw",
            "name": str(L.campo(c, "name", "nome", padrao=lid)),
            "blend": "normal",
            "opacity": float(L.campo(c, "opacity", "opacidade", padrao=1.0) or 1.0),
            "visible": bool(L.campo(c, "visible", "visivel", padrao=True)),
            "locked": bool(L.campo(c, "locked", "travada", padrao=False)),
            "parent": None, "children": [], "timing": 1,
            "rigId": None, "instanceId": None,
            "exposures": exposicoes,
        }
        raizes.append(lid)

    ultimo = max((e["frame"] for l in layers.values() for e in l["exposures"]),
                 default=0)
    documento = {
        "id": "proj_nuclear", "name": Path(entrada).stem,
        "width": largura, "height": altura, "fps": fps,
        "durationFrames": max(ultimo + 1, 1),
        "schemaVersion": 1,
        "createdAt": agora_ms, "modifiedAt": agora_ms,
        "background": {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0},
        "audio": None,
        "layers": layers, "drawings": drawings, "brushes": pinceis,
        "rigs": {}, "assets": {}, "instances": {}, "animations": {},
        "rootLayers": raizes, "markers": [],
    }
    manifesto = {
        "format": "brb", "schemaVersion": 1, "minReaderVersion": 1,
        "generator": "Nuclear (exportador do lote) via I3.7",
        "document": "document.cbor",
        "project": {"id": documento["id"], "name": documento["name"],
                    "width": largura, "height": altura, "fps": fps,
                    "durationFrames": documento["durationFrames"]},
        "counts": {"layers": len(layers), "drawings": len(drawings),
                   "strokes": n_traco},
        "createdAt": agora_ms, "modifiedAt": agora_ms,
    }

    cbor = enc_cbor(documento)
    conferir_ordem_canonica(cbor)      # se escapou da ordenação, não sai daqui

    # Carimbo de data fixo nas entradas do ZIP. Sem isto, duas passadas sobre a
    # mesma entrada dão bytes diferentes — só pela hora — e a ponte deixa de ser
    # comparável por hash. O bloco 5 precisa afirmar que a conversão do acervo é
    # reproduzível; conteúdo igual com container diferente já obriga a comparar
    # entrada por entrada, e não há razão para pagar isso.
    def entrada_fixa(nome):
        info = zipfile.ZipInfo(nome, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_STORED
        return info

    with zipfile.ZipFile(saida, "w", zipfile.ZIP_STORED) as z:
        z.writestr(entrada_fixa("manifest.json"),
                   json.dumps(manifesto, ensure_ascii=False, indent=2))
        z.writestr(entrada_fixa("document.cbor"), cbor)
        for chave, dados in sorted(bins.items()):
            z.writestr(entrada_fixa(chave), dados)

    print(f"[I3.7] {Path(entrada).name} -> {Path(saida).name}")
    print(f"       {len(layers)} camadas · {len(drawings)} desenhos · "
          f"{n_traco} traços · escala {esc:.1f}x para o canvas {largura}x{altura}")
    if fechados:
        # Perda declarada, não calada: quem lê o arquivo tem de saber. E é perda
        # TEMPORÁRIA — o preenchimento está sendo feito na versão final do outro
        # lado, e o dado de fill continua no `.brb` deste lado. Quando o formato
        # tiver fill, é retranscodificar (segundos), não reconverter (uma noite).
        print(f"       ⚠ {fechados} traço(s) de ÁREA PREENCHIDA saíram como contorno "
              f"— o formato alvo ainda não tem preenchimento")
    return {"camadas": len(layers), "desenhos": len(drawings), "tracos": n_traco,
            "fechados": fechados, "escala": esc}


def lote(pasta_entrada, pasta_saida, modelo, agora):
    """O acervo inteiro pela ponte. Python puro: não precisa do Nuclear, então
    retranscodificar o acervo custa minutos, não uma noite — e é por isso que a
    falta de preenchimento no formato alvo não obriga a decidir nada agora."""
    entrada, saida = Path(pasta_entrada), Path(pasta_saida)
    saida.mkdir(parents=True, exist_ok=True)
    arquivos = sorted(entrada.glob("*.brb"))
    if not arquivos:
        print(f"[I3.7] nenhum `.brb` em {entrada}")
        return 2

    ok = ruins = 0
    tot_tracos = tot_fechados = 0
    com_fill = []
    problemas = []
    for a in arquivos:
        try:
            r = transcodificar(a, saida / a.name, modelo, agora)
        except (ForaDaOrdem, zipfile.BadZipFile, OSError, ValueError,
                KeyError, TypeError, struct.error) as e:
            problemas.append((a.name, f"{type(e).__name__}: {e}"))
            print(f"[I3.7] {a.name}: NÃO transcodificou — {type(e).__name__}: {e}")
            ruins += 1
            continue
        ok += 1
        tot_tracos += r["tracos"]
        tot_fechados += r["fechados"]
        if r["fechados"]:
            com_fill.append((a.name, r["fechados"], r["tracos"]))

    pct = (100.0 * tot_fechados / tot_tracos) if tot_tracos else 0.0
    print(f"\n[I3.7] {ok} transcodificado(s), {ruins} não")
    print(f"       {tot_tracos} traços no total · {tot_fechados} de área preenchida "
          f"({pct:.1f}%) · {len(com_fill)} arquivo(s) dependem de preenchimento")
    # Este número é o que a direção de animação precisa para decidir: é o tanto do
    # acervo que só chega inteiro quando o formato alvo tiver fill.
    if com_fill:
        piores = sorted(com_fill, key=lambda x: -x[1])[:5]
        print("       os que mais dependem: " +
              ", ".join(f"{n} ({f}/{t})" for n, f, t in piores))
    if problemas:
        print("       falharam: " + ", ".join(n for n, _ in problemas[:10]))
    return 0 if not ruins else 1


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entrada")
    ap.add_argument("saida")
    ap.add_argument("--lote", action="store_true",
                    help="entrada e saída são PASTAS; transcodifica o acervo inteiro")
    ap.add_argument("--pinceis", help="`.brb` do aplicativo de onde copiar os pincéis")
    ap.add_argument("--agora", type=int, default=0,
                    help="carimbo de tempo em ms (padrão 0, para saída determinística)")
    a = ap.parse_args()
    if a.lote:
        return lote(a.entrada, a.saida, a.pinceis, a.agora)
    transcodificar(a.entrada, a.saida, a.pinceis, a.agora)
    return 0


if __name__ == "__main__":
    sys.exit(main())
