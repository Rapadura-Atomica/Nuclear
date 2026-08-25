#!/usr/bin/env python3
"""
Autoteste do I3.6 (miniatura do `.brb`).

A miniatura entrou por causa de uma perda calada: o exportador gravava 8 bytes
em `thumbnail.png` e **tudo passava** — o leitor só conferia se a entrada
existia, e comparação de árvore não olha para dentro de um PNG. Um arnês que só
cobrasse "gerou um PNG" repetiria o mesmo erro num degrau acima.

Então aqui se cobra o pixel, não o arquivo:

  verde     miniatura decodifica, no tamanho pedido
            a arte aparece no lugar certo (Y invertido, não de cabeça pra baixo)
            a cor sai em sRGB, não o número linear cru
            todas as outras entradas ficam byte a byte iguais
            nada sai comprimido — o leitor do outro lado recusa
  vermelho  8 bytes / ausente / PNG que não decodifica -> trocado
            arquivo sem traço nenhum -> NÃO regrava, e diz que não gerou

Não precisa do Nuclear nem do acervo: Python puro, roda no CI.

Uso: ./I3.6-autoteste.py
"""

import hashlib
import importlib.util
import io
import json
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
I36 = RAIZ / "I3.6-miniatura-brb.py"

falhas = []
testes = 0


def carregar(nome_arquivo, nome_modulo):
    spec = importlib.util.spec_from_file_location(
        nome_modulo, str(RAIZ / nome_arquivo))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ENC = carregar("I3.4-fixture-brb-falso.py", "fixture_falso").enc


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

def quadrado(x0, y0, lado, cor):
    """Um traço fechado — que no `.brb` quer dizer região preenchida."""
    return ([(x0, y0), (x0 + lado, y0), (x0 + lado, y0 + lado), (x0, y0 + lado)],
            cor, True)


def documento(tracos):
    """Monta o CBOR e o buffer de pontos de um `.brb` de um quadro só."""
    buf, offset, saida = bytearray(), 0, []
    for pontos, cor, fechado in tracos:
        for x, y in pontos:
            buf += struct.pack("<ffff", x, y, 1.0, 0.0)
        saida.append({"brush": "InkPen", "color": list(cor), "closed": fechado,
                      "smoothing": 0.0,
                      "points": {"offset": offset, "size": len(pontos)}})
        offset += len(pontos) * 16
    doc = {
        "frame_start": 1, "frame_end": 250, "frame_rate": 24,
        "resolution": [1920, 1080],
        "layers": [
            {"id": "grp", "name": "corpo", "parent": None, "order": 0,
             "visible": True, "locked": False, "opacity": 1.0,
             "blend_mode": "Normal", "content": {"Group": None}},
            {"id": "lay", "name": "arte", "parent": "grp", "order": 1,
             "visible": True, "locked": False, "opacity": 1.0,
             "blend_mode": "Normal",
             "content": {"Drawing": [{"index": 1, "content": {"Drawn": saida}}]}},
        ],
    }
    return ENC(doc), bytes(buf)


def escrever_brb(destino, tracos, thumb=b"\x89PNG\r\n\x1a\n", extras=True):
    doc, buf = documento(tracos)
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_STORED) as z:
        z.writestr("manifest.json", json.dumps({"magic": "BRB\x00",
                                                "schema_version": 1}))
        z.writestr("document.cbor", doc)
        z.writestr("strokes/0000.bin", buf)
        if thumb is not None:
            z.writestr("thumbnail.png", thumb)
        if extras:
            z.writestr("performances/.vazio", b"")
            z.writestr("relatorio-de-fidelidade.json",
                       json.dumps({"schema": 1, "achados": []}))
    return destino


def entradas(p):
    with zipfile.ZipFile(p) as z:
        return {i.filename: (hashlib.sha256(z.read(i.filename)).hexdigest(),
                             i.compress_type) for i in z.infolist()}, \
               [i.filename for i in z.infolist()]


def miniatura(p):
    with zipfile.ZipFile(p) as z:
        return z.read("thumbnail.png") if "thumbnail.png" in z.namelist() else b""


def rodar(*args):
    r = subprocess.run([sys.executable, str(I36), *map(str, args)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def pixel(dados, fx, fy):
    from PIL import Image
    with Image.open(io.BytesIO(dados)) as im:
        im = im.convert("RGB")
        return im.getpixel((int(im.width * fx), int(im.height * fy)))


def checar(nome, condicao, detalhe=""):
    global testes
    testes += 1
    if condicao:
        print(f"  [ok]   {nome}")
    else:
        print(f"  [FALHA] {nome}  {detalhe}")
        falhas.append(nome)


def perto(a, b, folga=12):
    return all(abs(x - y) <= folga for x, y in zip(a, b))


# --------------------------------------------------------------------------- #

def main():
    try:
        import PIL                                              # noqa: F401
    except ImportError:
        print("[I3.6-autoteste] sem Pillow — este arnês não roda. "
              "Ele é pós-passe, fora do Nuclear.")
        return 2

    with tempfile.TemporaryDirectory(prefix="i36-autoteste-") as t:
        tmp = Path(t)

        print("o defeito que trouxe esta ferramenta")

        p = escrever_brb(tmp / "stub.brb", [quadrado(0, 0, 10, [0, 0, 0, 1])])
        cod, saida = rodar(p, "--ver")
        checar("8 bytes é diagnosticado como imagem que ninguém abre",
               "só a assinatura PNG" in saida and cod == 1, saida.strip())

        cod, saida = rodar(p, "--sem-backup")
        checar("e a passada troca por um PNG que decodifica",
               cod == 0 and "PNG válido, 512x512" in saida, saida.strip())

        cod, saida = rodar(p, "--ver")
        checar("depois disso o diagnóstico fica verde",
               cod == 0 and "PNG válido" in saida, saida.strip())

        print("\no que a passada NÃO pode estragar")

        p = escrever_brb(tmp / "intacto.brb", [quadrado(0, 0, 10, [0, 0, 0, 1])])
        antes, ordem_antes = entradas(p)
        rodar(p, "--sem-backup")
        depois, ordem_depois = entradas(p)
        outras = {k: v for k, v in depois.items() if k != "thumbnail.png"}
        checar("nenhuma outra entrada muda um byte",
               outras == {k: v for k, v in antes.items() if k != "thumbnail.png"},
               f"{sorted(outras)} vs {sorted(antes)}")
        checar("a ordem das entradas é preservada",
               ordem_antes == ordem_depois, f"{ordem_antes} -> {ordem_depois}")
        checar("nada sai comprimido — o leitor do outro lado recusa método 8",
               {m for _, m in depois.values()} == {zipfile.ZIP_STORED},
               str({m for _, m in depois.values()}))
        checar("o `.brb` continua abrindo como ZIP",
               zipfile.is_zipfile(p))

        p = escrever_brb(tmp / "ver.brb", [quadrado(0, 0, 10, [0, 0, 0, 1])])
        marca = p.read_bytes()
        rodar(p, "--ver")
        checar("`--ver` não escreve nada", p.read_bytes() == marca)

        p = escrever_brb(tmp / "backup.brb", [quadrado(0, 0, 10, [0, 0, 0, 1])])
        rodar(p)
        checar("sem `--sem-backup`, o original fica ao lado",
               p.with_suffix(".brb.antes-da-miniatura").exists())

        print("\na miniatura precisa mostrar a arte, não só existir")

        # Vermelho em cima, azul embaixo. O Y da cena cresce para cima e o da
        # imagem para baixo: sem a inversão, o personagem sai de cabeça para
        # baixo — defeito que "gerou um PNG" nunca pegaria.
        p = escrever_brb(tmp / "cores.brb", [
            quadrado(0, 60, 40, [1.0, 0.0, 0.0, 1.0]),
            quadrado(0, 0, 40, [0.0, 0.0, 1.0, 1.0]),
        ])
        rodar(p, "--sem-backup")
        png = miniatura(p)
        alto, baixo = pixel(png, 0.5, 0.2), pixel(png, 0.5, 0.8)
        checar("o que está no alto da cena aparece no alto da imagem",
               perto(alto, (255, 0, 0), 20), f"topo={alto}")
        checar("e o que está embaixo, embaixo", perto(baixo, (0, 0, 255), 20),
               f"base={baixo}")

        # Cor de material do GP é LINEAR. 0.5 linear é 188 em sRGB, não 128 —
        # escrever o número cru escurece a arte inteira sem dar erro nenhum.
        p = escrever_brb(tmp / "linear.brb",
                         [quadrado(0, 0, 40, [0.5, 0.5, 0.5, 1.0])])
        rodar(p, "--sem-backup")
        meio = pixel(miniatura(p), 0.5, 0.5)
        checar("cor sai convertida para sRGB, não o valor linear cru",
               perto(meio, (188, 188, 188), 8), f"cinza={meio} (linear cru daria 128)")

        p = escrever_brb(tmp / "lado.brb", [quadrado(0, 0, 10, [0, 0, 0, 1])])
        rodar(p, "--sem-backup", "--lado", "128")
        from PIL import Image
        with Image.open(io.BytesIO(miniatura(p))) as im:
            checar("`--lado` manda no tamanho", im.size == (128, 128), str(im.size))

        print("\nos outros estados em que o arquivo pode chegar")

        p = escrever_brb(tmp / "sem-thumb.brb",
                         [quadrado(0, 0, 10, [0, 0, 0, 1])], thumb=None)
        cod, saida = rodar(p, "--sem-backup")
        checar("`.brb` sem miniatura nenhuma ganha uma",
               cod == 0 and len(miniatura(p)) > 8, saida.strip())

        p = escrever_brb(tmp / "lixo.brb", [quadrado(0, 0, 10, [0, 0, 0, 1])],
                         thumb=b"\x89PNG\r\n\x1a\n" + b"lixo" * 20)
        cod, saida = rodar(p, "--ver")
        checar("PNG que não decodifica é reprovado, não aceito por ter assinatura",
               cod != 0 and "não decodifica" in saida, saida.strip())
        cod, _ = rodar(p, "--sem-backup")
        checar("e é trocado por um bom",
               cod == 0 and len(miniatura(p)) > 100)

        vazio = escrever_brb(tmp / "vazio.brb", [])
        marca = vazio.read_bytes()
        cod, saida = rodar(vazio, "--sem-backup")
        checar("arquivo sem traço não é regravado às escondidas",
               vazio.read_bytes() == marca, "o arquivo mudou")
        checar("e ele DIZ que não gerou, em vez de sair 0 calado",
               cod != 0 and "miniatura não gerada" in saida, saida.strip())

        print("\nmodo lote")

        d = tmp / "lote"
        d.mkdir()
        for i in range(3):
            escrever_brb(d / f"p{i}.brb", [quadrado(0, 0, 10, [0, 0, 0, 1])])
        escrever_brb(d / "vazio.brb", [])
        cod, saida = rodar(d, "--lote", "--sem-backup")
        checar("o lote conta certo os que deram e os que não deram",
               "3 com miniatura, 1 sem" in saida, saida.strip().splitlines()[-1])
        checar("e sai não-zero quando algum ficou sem", cod != 0, f"cod={cod}")

        png_em = tmp / "pngs"
        cod, _ = rodar(d, "--lote", "--sem-backup", "--png-em", png_em)
        checar("`--png-em` solta os PNGs para conferência",
               len(list(png_em.glob("*.png"))) == 3,
               str(sorted(x.name for x in png_em.glob("*.png"))))

    print(f"\n{testes} teste(s), {len(falhas)} falha(s)")
    for f in falhas:
        print(f"  - {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
