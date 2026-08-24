#!/usr/bin/env python3
"""
I3.5 — desenha um `.brb` como SVG, usando só o que está dentro do arquivo.

Serve para uma pergunta que nenhum relatório responde e nenhuma comparação de
árvore alcança: **a arte atravessou?**

Todo o resto da verificação compara número com número — camadas, traços, pontos,
cores. Isso pega perda de estrutura, mas passa batido por erro que só o olho vê:
coordenada trocada, cor errada, ordem de desenho invertida, peça achatada. E o
teste que pegaria isso — abrir no Briba — não existe enquanto o aplicativo estiver
sendo escrito.

Este roteiro fecha parte dessa lacuna. Ele **não abre o `.blend`** e não usa o
Nuclear: lê o container, decodifica o CBOR, tira os pontos do buffer binário e
desenha. Se sair um personagem reconhecível, os dados chegaram do outro lado.
Se sair borrão preto, não chegaram — e o relatório que disse que estava tudo bem
é que está errado.

O que ele NÃO prova: que o Briba aceita o arquivo. Isso continua dependendo do
Briba existir. Ele prova o conteúdo, não o container.

Uso:

  ./I3.5-desenhar-brb.py arquivo.brb saida.svg
  ./I3.5-desenhar-brb.py arquivo.brb saida.svg --quadro 24
  ./I3.5-desenhar-brb.py pasta/ pasta-svg/          # em lote
"""

import argparse
import importlib.util
import json
import struct
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
BYTES_POR_PONTO = 16


def carregar_leitor():
    """O decodificador de CBOR vive no leitor do I3.4; nome de arquivo com
    ponto não é importável, então entra por caminho."""
    spec = importlib.util.spec_from_file_location(
        "ler_brb", str(RAIZ / "I3.4-ler-brb.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


L = carregar_leitor()


def pontos(buffer, offset, size):
    fim = offset + size * BYTES_POR_PONTO
    if offset < 0 or fim > len(buffer):
        return []
    return [struct.unpack_from("<ffff", buffer, offset + i * BYTES_POR_PONTO)
            for i in range(size)]


def para_srgb(c):
    """Linear -> sRGB.

    O Grease Pencil guarda cor de material em LINEAR, e é isso que o `.brb`
    carrega. Escrever esse número direto num SVG, que é sRGB, escurece a arte
    inteira — o casaco bege da referência saiu marrom-escuro até esta conversão
    entrar. A especificação do `.brb` diz `color: RGBA` e **não diz o espaço**;
    enquanto não disser, é a sexta lacuna da lista, e da mesma família da
    endianness: não dá erro, só sai errado.
    """
    c = max(0.0, min(1.0, float(c)))
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def rgba(cor):
    if not cor or len(cor) < 3:
        return "#000000", 1.0
    r, g, b = (max(0, min(255, int(round(para_srgb(c) * 255)))) for c in cor[:3])
    a = float(cor[3]) if len(cor) > 3 else 1.0
    return f"#{r:02x}{g:02x}{b:02x}", a


def esp_media(perfil):
    """O perfil de espessura é a série de raios amostrada. Vira largura de
    linha; sem perfil, uma largura fina que não esconde erro de posição."""
    try:
        vals = [float(v) for v in (perfil or []) if v is not None]
    except (TypeError, ValueError):
        return None
    if not vals:
        return None
    return sum(vals) / len(vals)


def coletar(caminho, quadro_pedido=None):
    """Devolve (traços, avisos). Cada traço já vem pronto para virar SVG."""
    avisos = []
    with zipfile.ZipFile(caminho) as z:
        nomes = z.namelist()
        doc = L.cbor_para_python(z.read("document.cbor")) if "document.cbor" in nomes else {}
        buffer = b"".join(z.read(n) for n in sorted(nomes)
                          if n.startswith("strokes/") and n.endswith(".bin"))

    camadas = L.campo(doc, "layers", "camadas", padrao=[]) or []
    por_id = {L.campo(c, "id"): c for c in camadas if L.campo(c, "id") is not None}

    saida = []
    for c in sorted(camadas, key=lambda x: (L.campo(x, "order", "ordem", padrao=0) or 0,
                                            str(L.campo(x, "name", "nome", padrao="")))):
        conteudo = L.campo(c, "content", "conteudo")
        if not (L.conteudo_tipo(conteudo) or "").lower().startswith("drawing"):
            continue
        if not bool(L.campo(c, "visible", "visivel", padrao=True)):
            continue
        nome = L.campo(c, "name", "nome") or "?"
        op_camada = float(L.campo(c, "opacity", "opacidade", padrao=1.0) or 1.0)

        # Um quadro por camada: o pedido, senão o primeiro que tem desenho.
        # Quadro em espera aponta para outro — aqui isso vira "sem desenho
        # próprio", porque redesenhar o referenciado exigiria resolver a cadeia
        # e o objetivo é olhar a arte, não reconstruir a exposição.
        escolhido = None
        for fr in (L.conteudo_carga(conteudo) or []):
            idx = L.campo(fr, "index", "quadro", padrao=0)
            fc = L.campo(fr, "content", "conteudo")
            tipo = (L.conteudo_tipo(fc) or "").lower()
            if not tipo.startswith("drawn"):
                continue
            if quadro_pedido is None:
                escolhido = fc
                break
            if idx == quadro_pedido:
                escolhido = fc
                break
        if escolhido is None:
            continue

        for t in (L.conteudo_carga(escolhido) or []):
            pt = L.campo(t, "points", "pontos", padrao={}) or {}
            off = L.campo(pt, "offset", padrao=None)
            size = L.campo(pt, "size", "n", padrao=None)
            if off is None or not size:
                continue
            p = pontos(buffer, int(off), int(size))
            if len(p) < 2:
                continue
            cor, alfa = rgba(L.campo(t, "color", "cor"))
            saida.append({
                "camada": nome,
                "pontos": [(x, y) for x, y, _pr, _tm in p],
                "cor": cor,
                "alfa": max(0.0, min(1.0, alfa * op_camada)),
                "fechado": bool(L.campo(t, "closed", "fechado", padrao=False)),
                "espessura": esp_media(L.campo(t, "thickness_profile",
                                               "perfil_de_espessura")),
            })

    if not saida:
        avisos.append("nenhum traço desenhável — o arquivo pode estar vazio, "
                      "ou todo o desenho pode estar em quadros em espera")
    return saida, avisos


def svg(tracos, titulo, largura=1000, margem=24):
    xs = [x for t in tracos for x, _ in t["pontos"]]
    ys = [y for t in tracos for _, y in t["pontos"]]
    if not xs:
        return ('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="120">'
                '<text x="16" y="60" font-family="sans-serif" font-size="14">'
                'sem tra&#231;o desenh&#225;vel</text></svg>')

    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    lx, ly = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    esc = (largura - 2 * margem) / lx
    altura = int(ly * esc + 2 * margem)

    # O plano do Nuclear é X-Z e o eixo Y do SVG cresce para baixo: sem a
    # inversão o personagem sai de cabeça para baixo, que é fácil de confundir
    # com defeito de conversão.
    def px(x, y):
        return (margem + (x - x0) * esc, margem + (y1 - y) * esc)

    # Espessura média do acervo em unidades de cena, convertida para pixel; a
    # linha nunca some nem vira mancha.
    def larg(t):
        e = t["espessura"]
        if not e:
            return 1.2
        return max(0.4, min(14.0, e * esc * 2))

    partes = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{largura}" '
        f'height="{altura}" viewBox="0 0 {largura} {altura}">',
        f'<title>{titulo}</title>',
        f'<rect width="100%" height="100%" fill="#ffffff"/>',
    ]
    for t in tracos:
        d = " ".join(f"{'M' if i == 0 else 'L'}{px(x, y)[0]:.2f},{px(x, y)[1]:.2f}"
                     for i, (x, y) in enumerate(t["pontos"]))
        if t["fechado"]:
            d += " Z"
            partes.append(f'<path d="{d}" fill="{t["cor"]}" '
                          f'fill-opacity="{t["alfa"]:.3f}" stroke="none"/>')
        else:
            partes.append(f'<path d="{d}" fill="none" stroke="{t["cor"]}" '
                          f'stroke-opacity="{t["alfa"]:.3f}" '
                          f'stroke-width="{larg(t):.2f}" stroke-linecap="round" '
                          f'stroke-linejoin="round"/>')
    partes.append("</svg>")
    return "\n".join(partes)


def uma(origem, destino, quadro):
    tracos, avisos = coletar(origem, quadro)
    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    Path(destino).write_text(svg(tracos, Path(origem).stem), encoding="utf-8")
    camadas = len({t["camada"] for t in tracos})
    cores = len({t["cor"] for t in tracos})
    pretos = sum(1 for t in tracos if t["cor"] == "#000000")
    print(f"[I3.5] {Path(origem).name} -> {destino}: {len(tracos)} traços, "
          f"{camadas} camadas, {cores} cores distintas"
          + (f", {pretos} traços pretos" if pretos else ""))
    for a in avisos:
        print(f"       aviso: {a}")
    return {"arquivo": str(origem), "svg": str(destino), "tracos": len(tracos),
            "camadas": camadas, "cores": cores, "pretos": pretos,
            "avisos": avisos}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("origem", help="arquivo `.brb` ou pasta com vários")
    ap.add_argument("destino", help="arquivo `.svg` ou pasta de saída")
    ap.add_argument("--quadro", type=int,
                    help="qual quadro desenhar (padrão: o primeiro de cada camada)")
    ap.add_argument("--limite", type=int, help="no modo pasta, para depois de N")
    args = ap.parse_args()

    origem = Path(args.origem)
    if origem.is_file():
        return 0 if uma(origem, args.destino, args.quadro) else 1

    arquivos = sorted(origem.rglob("*.brb"))
    if args.limite:
        arquivos = arquivos[:args.limite]
    if not arquivos:
        print(f"[I3.5] nenhum `.brb` em {origem}")
        return 2

    saida = Path(args.destino)
    saida.mkdir(parents=True, exist_ok=True)
    relatos = []
    for a in arquivos:
        try:
            relatos.append(uma(a, saida / f"{a.stem}.svg", args.quadro))
        except (zipfile.BadZipFile, OSError, ValueError, KeyError) as e:
            print(f"[I3.5] {a.name}: não deu para desenhar — {type(e).__name__}: {e}")
            relatos.append({"arquivo": str(a), "erro": str(e)})
    (saida / "_desenhos.json").write_text(
        json.dumps(relatos, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[I3.5] {len(relatos)} arquivo(s) desenhado(s) em {saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
