#!/usr/bin/env python3
"""
I3.6 — põe uma miniatura de verdade dentro de um `.brb` já convertido.

O container manda `thumbnail.png` ("miniatura do projeto"). O exportador vinha
gravando ali **8 bytes** — só a assinatura PNG, sem cabeçalho, sem pixel, sem
marca de fim. Nenhum decodificador do mundo abre isso: o outro lado não vê uma
imagem vazia, vê um arquivo corrompido, e a falha aparece no leitor dele, não
aqui.

Por que ninguém pegou: o leitor do I3.4 só confere que a entrada **existe**
(`thumbnail.png ausente`), e a comparação de árvore não olha para dentro do PNG.
É perda calada da mesma família das outras — passa em tudo que a gente mede.

Este roteiro é **pós-passe**, o mesmo precedente da recarimbagem: não abre o
`.blend`, não chama o Nuclear, não reconverte nada. Lê o próprio `.brb`,
redesenha o conteúdo com o mesmo código da verificação visual (I3.5) e regrava o
container com a miniatura no lugar. Todas as outras entradas saem **byte a byte
iguais** — e ele confere isso antes de trocar o arquivo.

Uso:

  ./I3.6-miniatura-brb.py arquivo.brb                # no lugar, com backup
  ./I3.6-miniatura-brb.py pasta/ --lote              # o acervo convertido
  ./I3.6-miniatura-brb.py arquivo.brb --ver          # só diz o que tem hoje
  ./I3.6-miniatura-brb.py arquivo.brb --lado 256     # outro tamanho

Sai 0 quando todo arquivo pedido ficou com miniatura válida.
"""

import argparse
import hashlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
LADO_PADRAO = 512
SUPERAMOSTRA = 4          # desenha grande e reduz: é o antisserrilhado do PIL
FUNDO = (255, 255, 255)   # branco, como o SVG da verificação visual


def carregar(nome_arquivo, nome_modulo):
    """Nome de arquivo com ponto não é importável; entra por caminho."""
    spec = importlib.util.spec_from_file_location(
        nome_modulo, str(RAIZ / nome_arquivo))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def pil():
    try:
        from PIL import Image, ImageDraw
        return Image, ImageDraw
    except ImportError:
        sys.exit("[I3.6] este roteiro precisa do Pillow (`pip install Pillow`).\n"
                 "       Ele roda FORA do Nuclear de propósito — é pós-passe.")


def cor_para_rgb(hexa):
    h = (hexa or "#000000").lstrip("#")
    if len(h) != 6:
        return (0, 0, 0)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def desenhar(tracos, lado):
    """Rasteriza os traços já coletados pelo I3.5 num PNG quadrado.

    Quadrado de propósito: miniatura de catálogo entra em grade, e personagem
    em pé numa caixa larga vira uma tira. A arte fica centrada, na proporção
    original, com o resto de fundo.
    """
    Image, ImageDraw = pil()
    xs = [x for t in tracos for x, _ in t["pontos"]]
    ys = [y for t in tracos for _, y in t["pontos"]]
    if not xs:
        return None

    grande = lado * SUPERAMOSTRA
    margem = grande // 32
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    lx, ly = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    esc = (grande - 2 * margem) / max(lx, ly)
    # centraliza o que sobra no eixo menor
    dx = (grande - lx * esc) / 2
    dy = (grande - ly * esc) / 2

    def px(x, y):
        # Y do Nuclear cresce para cima, Y da imagem cresce para baixo — sem a
        # inversão o personagem sai de cabeça para baixo, que é fácil de
        # confundir com defeito de conversão.
        return (dx + (x - x0) * esc, dy + (y1 - y) * esc)

    img = Image.new("RGB", (grande, grande), FUNDO)
    d = ImageDraw.Draw(img, "RGBA")
    for t in tracos:
        pts = [px(x, y) for x, y in t["pontos"]]
        if len(pts) < 2:
            continue
        alfa = max(0, min(255, int(round(t["alfa"] * 255))))
        if alfa == 0:
            continue
        rgba = cor_para_rgb(t["cor"]) + (alfa,)
        if t["fechado"] and len(pts) >= 3:
            # `closed` é área preenchida (T2.6), não traço cíclico — a mesma
            # regra que fez 79% das áreas chapadas voltarem a existir.
            d.polygon(pts, fill=rgba)
        else:
            e = t["espessura"]
            larg = 2 if not e else max(2, min(int(round(e * esc * 2)), grande // 8))
            d.line(pts, fill=rgba, width=larg, joint="curve")

    return img.resize((lado, lado), Image.LANCZOS)


def png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def diagnostico(dados):
    """O que dá para dizer sobre o PNG que está lá dentro hoje."""
    if not dados:
        return "vazio (0 bytes)"
    if not dados.startswith(b"\x89PNG\r\n\x1a\n"):
        return f"não é PNG ({len(dados)} bytes)"
    if len(dados) <= 8:
        return "só a assinatura PNG, sem imagem (8 bytes) — nenhum leitor abre"
    try:
        Image, _ = pil()
        with Image.open(io.BytesIO(dados)) as im:
            im.verify()
        with Image.open(io.BytesIO(dados)) as im:
            return f"PNG válido, {im.width}x{im.height}, {len(dados)} bytes"
    except Exception as e:                                   # noqa: BLE001
        return f"PNG que não decodifica — {type(e).__name__}: {e}"


def regravar(caminho, novo_png, backup=True):
    """Troca só `thumbnail.png`, preservando ordem, método e o resto dos bytes.

    ZIP_STORED não é capricho: o leitor do outro lado recusou entrada
    comprimida com todas as letras ("este leitor só aceita armazenamento
    direto"). Regravar com o padrão do zipfile quebraria o arquivo inteiro para
    trocar uma imagem.
    """
    caminho = Path(caminho)
    with zipfile.ZipFile(caminho) as z:
        entradas = [(i, z.read(i.filename)) for i in z.infolist()]
    antes = {n: hashlib.sha256(d).hexdigest() for (i, d) in entradas
             for n in [i.filename] if n != "thumbnail.png"}

    tinha = any(i.filename == "thumbnail.png" for i, _ in entradas)
    tmp = tempfile.NamedTemporaryFile(delete=False, dir=str(caminho.parent),
                                      suffix=".brb.tmp")
    tmp.close()
    try:
        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_STORED) as z:
            for info, dados in entradas:
                if info.filename == "thumbnail.png":
                    dados = novo_png
                novo = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                novo.compress_type = zipfile.ZIP_STORED
                novo.external_attr = info.external_attr
                z.writestr(novo, dados)
            if not tinha:
                z.writestr("thumbnail.png", novo_png)

        # O compromisso desta ferramenta é "só a miniatura muda". Conferir, e
        # não prometer: o arquivo de origem já foi conferido uma vez e não vai
        # ser conferido de novo.
        with zipfile.ZipFile(tmp.name) as z:
            depois = {i.filename: hashlib.sha256(z.read(i.filename)).hexdigest()
                      for i in z.infolist() if i.filename != "thumbnail.png"}
            metodos = {i.compress_type for i in z.infolist()}
        if depois != antes:
            raise RuntimeError("a regravação mudou entrada que não era a miniatura")
        if metodos - {zipfile.ZIP_STORED}:
            raise RuntimeError("saiu entrada comprimida; o leitor recusa")

        if backup:
            shutil.copy2(caminho, caminho.with_suffix(".brb.antes-da-miniatura"))
        os.replace(tmp.name, caminho)
    finally:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)


def uma(caminho, lado, backup, so_ver, quadro=None, tambem_png=None):
    caminho = Path(caminho)
    with zipfile.ZipFile(caminho) as z:
        atual = z.read("thumbnail.png") if "thumbnail.png" in z.namelist() else b""
    antes = diagnostico(atual)
    if so_ver:
        print(f"[I3.6] {caminho.name}: {antes}")
        # Pelo diagnóstico, não pelo tamanho: PNG truncado com a assinatura
        # certa passa fácil de 8 bytes e não abre em lugar nenhum.
        return antes.startswith("PNG válido")

    D = carregar("I3.5-desenhar-brb.py", "desenhar_brb")
    tracos, avisos = D.coletar(caminho, quadro)
    img = desenhar(tracos, lado)
    if img is None:
        print(f"[I3.6] {caminho.name}: sem traço desenhável — miniatura não gerada "
              f"(estava: {antes})")
        for a in avisos:
            print(f"       aviso: {a}")
        return False

    dados = png_bytes(img)
    regravar(caminho, dados, backup=backup)
    if tambem_png:
        Path(tambem_png).parent.mkdir(parents=True, exist_ok=True)
        Path(tambem_png).write_bytes(dados)
    print(f"[I3.6] {caminho.name}: {antes} -> {diagnostico(dados)} "
          f"({len(tracos)} traços)")
    return True


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("alvo", help="um `.brb` ou uma pasta (com --lote)")
    ap.add_argument("--lote", action="store_true",
                    help="varre a pasta atrás de `.brb`, recursivo")
    ap.add_argument("--lado", type=int, default=LADO_PADRAO,
                    help=f"lado da miniatura em pixels (padrão {LADO_PADRAO})")
    ap.add_argument("--quadro", type=int,
                    help="qual quadro desenhar (padrão: o primeiro de cada camada)")
    ap.add_argument("--ver", action="store_true",
                    help="só diz o que tem hoje, não escreve nada")
    ap.add_argument("--sem-backup", action="store_true",
                    help="não deixa `.brb.antes-da-miniatura` ao lado")
    ap.add_argument("--png-em", help="salva também os PNGs soltos nesta pasta")
    args = ap.parse_args()

    alvo = Path(args.alvo)
    if not args.lote:
        ok = uma(alvo, args.lado, not args.sem_backup, args.ver, args.quadro,
                 Path(args.png_em) / f"{alvo.stem}.png" if args.png_em else None)
        return 0 if ok else 1

    arquivos = sorted(alvo.rglob("*.brb"))
    if not arquivos:
        print(f"[I3.6] nenhum `.brb` em {alvo}")
        return 2
    bons = ruins = 0
    for a in arquivos:
        try:
            ok = uma(a, args.lado, not args.sem_backup, args.ver, args.quadro,
                     Path(args.png_em) / f"{a.stem}.png" if args.png_em else None)
        except (zipfile.BadZipFile, OSError, ValueError, KeyError,
                RuntimeError) as e:
            print(f"[I3.6] {a.name}: não deu — {type(e).__name__}: {e}")
            ok = False
        bons, ruins = bons + bool(ok), ruins + (not ok)
    print(f"[I3.6] {bons} com miniatura, {ruins} sem.")
    return 0 if not ruins else 1


if __name__ == "__main__":
    sys.exit(main())
