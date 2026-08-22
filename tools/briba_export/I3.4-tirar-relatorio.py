"""Remove o relatório de fidelidade de um .brb — fixture de 'perda calada'.

Serve ao autoteste: prova que o comparador reprova quando o exportador perde
alguma coisa e não declara. Só isso.

Uso: python3 I3.4-tirar-relatorio.py origem.brb destino.brb
"""
import sys
import zipfile

origem, destino = sys.argv[1], sys.argv[2]
zi = zipfile.ZipFile(origem)
with zipfile.ZipFile(destino, "w", zipfile.ZIP_STORED) as zo:
    for n in zi.namelist():
        if n != "relatorio-de-fidelidade.json":
            zo.writestr(n, zi.read(n))
