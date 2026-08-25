"""
I3.4 — fixture de teste: gera um `.brb` que CASA com uma árvore canônica.

Existe por um motivo só: provar que o comparador consegue **passar**. Um arnês
de teste que nunca ficou verde pode ter um defeito que o faz reprovar sempre, e
aí ele não vale nada — reprovaria o exportador certo do mesmo jeito.

Isto **não é o exportador do I3.1**. O exportador de verdade lê a cena do
Nuclear; este aqui lê o JSON que o `I3.4-arvore-canonica.py` produziu e devolve
o `.brb` correspondente. É fixture, e serve só para o teste do teste.

Uso:
    python3 I3.4-fixture-brb-falso.py arvore.json saida.brb [--degradar CAMPO]

`--degradar` estraga um aspecto de propósito, para conferir que o comparador
pega. Valores: tracos, ordem, cor, espera.
"""
import json
import struct
import sys
import zipfile
from pathlib import Path


# --------------------------------------------------------------------------- #
# codificador CBOR mínimo — espelho do decodificador do I3.4-ler-brb.py
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
        if n < 24:
            return bytes([(maior << 5) | n])
        if n < 256:
            return bytes([(maior << 5) | 24, n])
        if n < 65536:
            return bytes([(maior << 5) | 25]) + struct.pack(">H", n)
        return bytes([(maior << 5) | 26]) + struct.pack(">I", n)
    if isinstance(v, float):
        return b"\xfb" + struct.pack(">d", v)
    if isinstance(v, str):
        b = v.encode("utf-8")
        return _prefixo(0x60, 0x78, len(b)) + b
    if isinstance(v, (list, tuple)):
        return _prefixo(0x80, 0x98, len(v)) + b"".join(enc(x) for x in v)
    if isinstance(v, dict):
        return _prefixo(0xA0, 0xB8, len(v)) + b"".join(enc(k) + enc(x) for k, x in v.items())
    raise TypeError(f"não sei codificar {type(v)}")


def _prefixo(base_curto, base_1byte, n):
    if n < 24:
        return bytes([base_curto | n])
    if n < 256:
        return bytes([base_1byte, n])
    return bytes([base_1byte + 1]) + struct.pack(">H", n)


# --------------------------------------------------------------------------- #

def montar(arvore, degradar=None):
    """Traduz a árvore do Nuclear para a forma que o `.brb` guarda."""
    fim_cena = (arvore.get("cena", {}).get("quadros") or [1, 250])[1]
    camadas, offset, buffers = [], 0, []

    for ob in arvore.get("objetos", []):
        gid = f"grp-{ob['nome']}"
        camadas.append({
            "id": gid, "name": ob["nome"], "parent": None,
            "order": len(camadas), "visible": True, "locked": False,
            "opacity": 1.0, "blend_mode": "Normal", "content": {"Group": None},
        })

        for c in ob["camadas"]:
            quadros = []
            vistos = {}
            for q in c["quadros"]:
                # a biblioteca de poses fora da linha do tempo entra como
                # quadro normal: ela É desenho, só não está exposta na régua
                ref = q.get("desenho_ref")
                if ref is not None and ref in vistos and degradar != "espera":
                    quadros.append({"index": q["quadro"],
                                    "content": {"Held": {"reference": vistos[ref]}}})
                    continue
                if ref is not None:
                    vistos[ref] = q["quadro"]

                tracos = []
                for t in q["tracos"]:
                    n = t["geometria"].get("n", 0)
                    cor = t.get("cor_material_traco") or t.get("cor_material_fill") or [0, 0, 0, 1]
                    if degradar == "cor":
                        cor = None
                    tracos.append({
                        "brush": "InkPen",
                        "color": cor,
                        "closed": bool(t.get("ciclico")),
                        "smoothing": 0.0,
                        "points": {"offset": offset, "size": n},
                    })
                    # 16 bytes por ponto, os mesmos 4 floats que o exportador
                    # grava (x, y, pressão, tempo). Aqui ficaram 12 por um bom
                    # tempo, e passava: o comparador tira a contagem de pontos
                    # do `size` no CBOR, não do tamanho do buffer. Mas quem lê o
                    # buffer por fora — o relatório de fidelidade, que divide os
                    # bytes por 16 justamente para pegar buffer truncado — veria
                    # este fixture como um arquivo com um quarto dos pontos
                    # faltando. Fixture que não tem o tamanho do formato real
                    # não serve para exercitar a verificação que mede por fora.
                    buffers.append(b"\x00" * max(n * 16, 1))
                    offset += n * 16
                if degradar == "tracos" and tracos:
                    tracos = tracos[:-1]
                quadros.append({"index": q["quadro"], "content": {"Drawn": tracos}})

            ordem = len(camadas)
            if degradar == "ordem":
                ordem = 999 - ordem
            camadas.append({
                "id": f"lay-{ob['nome']}-{c['nome']}",
                "name": c["nome"], "parent": gid, "order": ordem,
                "visible": bool(c.get("visivel", True)),
                "locked": bool(c.get("travada", False)),
                "opacity": float(c.get("opacidade") or 1.0),
                "blend_mode": "Normal",
                "content": {"Drawing": quadros},
            })

    return {
        "frame_start": (arvore.get("cena", {}).get("quadros") or [1, 250])[0],
        "frame_end": fim_cena,
        "frame_rate": arvore.get("cena", {}).get("fps", 24),
        "resolution": arvore.get("cena", {}).get("resolucao", [1920, 1080]),
        "layers": camadas,
    }, buffers


def main():
    if len(sys.argv) < 3:
        print(__doc__.strip())
        return 2
    degradar = None
    if "--degradar" in sys.argv:
        degradar = sys.argv[sys.argv.index("--degradar") + 1]

    arvore = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    destino = Path(sys.argv[2])
    doc, buffers = montar(arvore, degradar)

    # sem compressão: o leitor do Briba recusa entrada deflatada
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_STORED) as z:
        z.writestr("manifest.json", json.dumps({
            "magic": "BRB\x00", "schema_version": 1,
            "project": {"name": Path(arvore.get("arquivo", "sem-nome")).stem},
        }))
        z.writestr("document.cbor", enc(doc))
        for i, b in enumerate(buffers):
            z.writestr(f"strokes/{i:05d}.bin", b)
        z.writestr("thumbnail.png", b"\x89PNG\r\n\x1a\n")
        # Um exportador correto declara o que perdeu. O fixture representa um
        # exportador correto, então declara também — senão o comparador o
        # reprovaria por perda calada, que é justamente a checagem certa.
        achados = [
            {"categoria": "DEGRADADO", "assunto": "máscara",
             "detalhe": f"a camada é mascarada por {c['mascaras']}; o .brb nos "
                        f"níveis 1 e 2 não tem máscara de camada",
             "onde": f"{ob['nome']}/{c['nome']}"}
            for ob in arvore.get("objetos", [])
            for c in ob.get("camadas", [])
            if c.get("usa_mascara") and c.get("mascaras")
        ]
        # Exportador correto também PRESERVA o vínculo de máscara, não só
        # declara a perda — é o que torna a conversão reversível.
        mascaras = [
            {"camada": f"lay:{ob['nome']}:{c['nome']}",
             "objeto": ob["nome"], "nome_da_camada": c["nome"],
             "mascarada_por": [{"camada": m, "objeto": ob["nome"],
                                "invertida": False, "auto_patch": False}
                               for m in c["mascaras"]]}
            for ob in arvore.get("objetos", [])
            for c in ob.get("camadas", [])
            if c.get("usa_mascara") and c.get("mascaras")
        ]
        if mascaras:
            z.writestr("mascaras.json", json.dumps(
                {"schema": 1, "n_camadas_mascaradas": len(mascaras),
                 "mascaras": mascaras}, ensure_ascii=False))

        from collections import Counter
        z.writestr("relatorio-de-fidelidade.json", json.dumps(
            {"schema": 1,
             "resumo": dict(Counter(i["categoria"] for i in achados)),
             "achados": achados}, ensure_ascii=False, indent=1))

    n_tracos = sum(len(q["content"].get("Drawn", []))
                   for c in doc["layers"] if "Drawing" in c["content"]
                   for q in c["content"]["Drawing"] if "Drawn" in q["content"])
    marca = f" [DEGRADADO: {degradar}]" if degradar else ""
    print(f"[fixture] {destino.name}: {len(doc['layers'])} camadas, "
          f"{n_tracos} traços{marca}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
