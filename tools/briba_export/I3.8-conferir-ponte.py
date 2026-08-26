#!/usr/bin/env python3
"""
I3.8 — a arte sobreviveu à ponte? Compara o desenho dos dois lados, arquivo por arquivo.

A ponte do I3.7 já é conferida por estrutura: contagem de camadas, ordem canônica das
chaves, `pointCount` batendo com o tamanho do arquivo de pontos. Isso não basta, e este
bloco já provou três vezes por quê — o `closed` lido errado, a cor em espaço errado e a
miniatura de oito bytes passaram todos por conferência de número contra número.

Aqui a pergunta é outra: **o desenho que sai é o mesmo que entrou?**

Como, sem depender de render nem do aplicativo: os pontos dos dois lados viram uma nuvem,
cada nuvem é normalizada pela própria caixa e rasterizada numa grade de ocupação, e as duas
grades se comparam por interseção sobre união. Isso pega o que só o olho pegaria —
escala trocada, Y invertido, camada perdida, traço fora de lugar — sem exigir que os dois
lados usem as mesmas unidades, que é justamente o que a ponte muda de propósito.

O que ele NÃO cobra: cor, espessura e preenchimento. Cor e espessura não mudam de forma na
travessia; o preenchimento some por limitação declarada do formato alvo, e cobrar aqui
faria o arnês reprovar o acervo inteiro por uma decisão que já está registrada.

Uso:
  ./I3.8-conferir-ponte.py ORIGEM_DIR PONTE_DIR
  ./I3.8-conferir-ponte.py ORIGEM_DIR PONTE_DIR --limiar 0.90 --provas SAIDA_DIR
"""

import argparse
import importlib.util
import math
import struct
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
GRADE = 96          # lado da grade de ocupação
# Coordenada absurda não é arte: é geometria corrompida na origem. Comparar sem
# filtrar mede a corrupção, não o desenho — a caixa de um lado explode, a grade
# colapsa numa célula e a semelhança vai a zero mesmo com a travessia perfeita.
# O conferidor tinha o mesmo ponto cego que a ponte tinha.
COORD_ABSURDA = 1e6
LIMIAR = 0.90       # abaixo disto, o desenho mudou o bastante para olhar


def carregar(nome, mod):
    spec = importlib.util.spec_from_file_location(mod, str(RAIZ / nome))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


L = carregar("I3.4-ler-brb.py", "ler_brb_para_conferir")


# --------------------------------------------------------------------------- #

def sensata(p):
    return (math.isfinite(p[0]) and math.isfinite(p[1])
            and abs(p[0]) <= COORD_ABSURDA and abs(p[1]) <= COORD_ABSURDA)


def segmentos_nossos(caminho):
    """Segmentos de reta do `.brb` deste lado (4 floats por ponto)."""
    with zipfile.ZipFile(caminho) as z:
        nomes = z.namelist()
        doc = L.cbor_para_python(z.read("document.cbor"))
        buf = b"".join(z.read(n) for n in sorted(nomes)
                       if n.startswith("strokes/") and n.endswith(".bin"))
    segs = []
    for c in (L.campo(doc, "layers", "camadas", padrao=[]) or []):
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
                fim = int(off) + int(n) * 16
                if int(off) < 0 or fim > len(buf):
                    continue
                pts = [struct.unpack_from("<ffff", buf, int(off) + i * 16)[:2]
                       for i in range(int(n))]
                pts = [p for p in pts if sensata(p)]
                if pts:
                    segs.append(pts)
    return segs


def segmentos_da_ponte(caminho):
    """Segmentos do `.brb` no formato do aplicativo (6 floats por ponto)."""
    with zipfile.ZipFile(caminho) as z:
        doc = L.cbor_para_python(z.read("document.cbor"))
        segs = []
        for lid in (doc.get("rootLayers") or []):
            lay = (doc.get("layers") or {}).get(lid)
            if not lay:
                continue
            for exp in (lay.get("exposures") or []):
                des = (doc.get("drawings") or {}).get(exp.get("drawingId"))
                if not des:
                    continue
                for t in (des.get("strokes") or []):
                    b = z.read(t["pointsKey"])
                    n = int(t["pointCount"])
                    if len(b) < n * 24:
                        continue
                    pts = [struct.unpack_from("<ffffff", b, i * 24)[:2]
                           for i in range(n)]
                    segs.append(pts)
    return segs


def ocupacao(segs, lado=GRADE, inverter_y=False):
    """Normaliza pela caixa e marca as células por onde a linha passa.

    Normalizar pela própria caixa é o que torna a comparação possível: os dois lados
    vivem em unidades diferentes de propósito (cena do Nuclear × pixels do canvas), e
    o que se quer saber é se o DESENHO é o mesmo, não se os números são.
    """
    pts = [p for s in segs for p in s]
    if len(pts) < 2:
        return set()
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    lx, ly = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    esc = (lado - 1) / max(lx, ly)
    dx = (lado - 1 - lx * esc) / 2
    dy = (lado - 1 - ly * esc) / 2

    def cel(p):
        cx = dx + (p[0] - x0) * esc
        cy = dy + ((y1 - p[1]) if inverter_y else (p[1] - y0)) * esc
        return int(cx), int(cy)

    grade = set()
    for s in segs:
        ant = None
        for p in s:
            atual = cel(p)
            if ant is not None:
                # Bresenham simples: sem rasterizar o segmento, traço longo vira
                # dois pontos soltos e a comparação mente para mais.
                (ax, ay), (bx, by) = ant, atual
                passos = max(abs(bx - ax), abs(by - ay), 1)
                for i in range(passos + 1):
                    grade.add((ax + (bx - ax) * i // passos,
                               ay + (by - ay) * i // passos))
            else:
                grade.add(atual)
            ant = atual
    return grade


def iou(a, b):
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("origem", help="pasta dos `.brb` deste lado")
    ap.add_argument("ponte", help="pasta dos `.brb` transcodificados")
    ap.add_argument("--limiar", type=float, default=LIMIAR)
    ap.add_argument("--provas", help="pasta para gravar as comparações que reprovaram")
    a = ap.parse_args()

    origem, ponte = Path(a.origem), Path(a.ponte)
    arquivos = sorted(ponte.glob("*.brb"))
    if not arquivos:
        sys.exit(f"[I3.8] nenhum `.brb` em {ponte}")

    notas, ruins, vazios, faltando = [], [], [], []
    for p in arquivos:
        o = origem / p.name
        if not o.exists():
            faltando.append(p.name)
            continue
        try:
            a_segs, b_segs = segmentos_nossos(o), segmentos_da_ponte(p)
        except (zipfile.BadZipFile, OSError, KeyError, ValueError,
                struct.error) as e:
            ruins.append((p.name, 0.0, f"{type(e).__name__}: {e}"))
            continue
        if not a_segs and not b_segs:
            vazios.append(p.name)
            continue
        # A ponte inverte o Y de propósito (o canvas cresce para baixo); comparar
        # sem desfazer isso reprovaria 100% do acervo por uma decisão correta.
        nota = iou(ocupacao(a_segs), ocupacao(b_segs, inverter_y=True))
        notas.append((p.name, nota, len(a_segs), len(b_segs)))
        if nota < a.limiar:
            ruins.append((p.name, nota, f"{len(a_segs)} traços -> {len(b_segs)}"))

    if notas:
        vals = sorted(n for _, n, _, _ in notas)
        media = sum(vals) / len(vals)
        mediana = vals[len(vals) // 2]
        print(f"[I3.8] {len(notas)} arquivo(s) comparados")
        print(f"       semelhança do desenho: mediana {mediana:.3f} · "
              f"média {media:.3f} · pior {vals[0]:.3f}")
        faixas = [(0.99, "quase idêntico"), (0.95, "muito próximo"),
                  (a.limiar, "próximo")]
        resto = len(vals)
        for corte, rotulo in faixas:
            n = sum(1 for v in vals if v >= corte)
            print(f"       >= {corte:.2f} ({rotulo}): {n}")
            resto = len(vals) - n
        print(f"       abaixo de {a.limiar:.2f}: {resto}")
    if vazios:
        print(f"       {len(vazios)} sem traço nos dois lados (não é perda)")
    if faltando:
        print(f"       {len(faltando)} sem par na origem")
    if ruins:
        print(f"\n[I3.8] {len(ruins)} para olhar:")
        for n, v, d in sorted(ruins, key=lambda x: x[1])[:15]:
            print(f"       {v:.3f}  {n}  ({d})")
    else:
        print("\n[I3.8] nenhum arquivo abaixo do limiar — o desenho atravessou.")
    return 1 if ruins else 0


if __name__ == "__main__":
    sys.exit(main())
