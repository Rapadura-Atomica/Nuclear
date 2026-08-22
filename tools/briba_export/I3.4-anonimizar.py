"""
I3.4 — anonimiza uma árvore de referência para versionar em repo público.

O repositório do Nuclear é público. As árvores servem de fixture para o
autoteste do comparador, e para isso o que importa é a **estrutura** — quantas
camadas, quais quadros em espera, quais máscaras, a biblioteca de poses. Nada
disso depende do nome do personagem nem do lugar onde o arquivo mora.

Então some daqui: caminho de arquivo, nome de objeto, nome de camada, nome de
máscara. Fica tudo o resto, bit a bit.

O mapeamento é **determinístico** (mesmo nome, mesmo pseudônimo, sempre) e
consistente dentro do arquivo: se uma camada é mascarada por outra, os
pseudônimos preservam esse vínculo — senão o teste de máscara perderia o
sentido.

Uso:
    python3 I3.4-anonimizar.py entrada.json saida.json
"""
import hashlib
import json
import sys
from pathlib import Path


class Pseudonimos:
    """Nome real -> pseudônimo estável, por espécie."""

    def __init__(self):
        self.mapa = {}
        self.contagem = {}

    def de(self, especie, nome):
        if nome is None:
            return None
        chave = (especie, nome)
        if chave not in self.mapa:
            n = self.contagem.get(especie, 0) + 1
            self.contagem[especie] = n
            self.mapa[chave] = f"{especie}-{n:03d}"
        return self.mapa[chave]


def anonimizar(arv):
    p = Pseudonimos()

    # o nome do arquivo vira um rótulo derivado do hash: continua distinguindo
    # uma referência da outra sem dizer de onde veio
    origem = arv.get("arquivo", "")
    rotulo = "ref-" + hashlib.sha1(origem.encode()).hexdigest()[:8]
    arv["arquivo"] = f"<anonimizado>/{rotulo}.blend"

    for ob in arv.get("objetos", []):
        ob["nome"] = p.de("objeto", ob["nome"])
        for c in ob.get("camadas", []):
            c["nome"] = p.de("camada", c["nome"])
            if c.get("grupo_pai"):
                c["grupo_pai"] = p.de("grupo", c["grupo_pai"])
            # o vínculo de máscara precisa continuar apontando para a MESMA
            # camada depois da troca, senão o teste de máscara vira ruído
            c["mascaras"] = [p.de("camada", m) for m in (c.get("mascaras") or [])]
        for g in ob.get("grupos", []):
            g["nome"] = p.de("grupo", g["nome"])
            if g.get("pai"):
                g["pai"] = p.de("grupo", g["pai"])

    if "cena" in arv:
        arv["cena"]["nome"] = "Scene"
    return arv


def main():
    if len(sys.argv) < 3:
        print(__doc__.strip())
        return 2
    arv = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    saida = anonimizar(arv)
    Path(sys.argv[2]).write_text(
        json.dumps(saida, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    r = saida["resumo"]
    print(f"[anon] {Path(sys.argv[1]).name} -> {Path(sys.argv[2]).name}: "
          f"{r['n_objetos_gp']} objetos, {r['n_camadas']} camadas, {r['n_tracos']} traços")
    return 0


if __name__ == "__main__":
    sys.exit(main())
