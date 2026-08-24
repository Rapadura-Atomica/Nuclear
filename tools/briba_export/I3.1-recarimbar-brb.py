#!/usr/bin/env python3
"""
I3.1 — recarimbar `.brb` já convertido, sem reconverter.

Existe por uma razão só: **o Briba ainda está sendo escrito.** Enquanto ele
estiver, quatro coisas da especificação do container ainda podem mudar de ideia:

  numero magico       a spec cita uma vez, numa tabela, e não diz o valor
  nomes dos campos    `magic`, `schema_version`, `project` foram inferidos
  pasta de atuação    `actions/` x `performances/` é pendência de governança
  método do ZIP       resolvido (armazenado), mas o mesmo risco vale

Se qualquer uma delas mudar depois que o acervo já rodou, reconverter o acervo
inteiro custa uma noite de estação. Trocar o carimbo custa segundos por arquivo,
e não toca em um único traço: a geometria, o CBOR e o relatório de fidelidade
saem byte a byte iguais aos que já foram conferidos.

É por isso que este roteiro NUNCA reescreve conteúdo. Ele copia as entradas
como estão e mexe só no `manifest.json` e no nome de pasta pedido.

Uso:

  # o que este arquivo diz hoje
  ./I3.1-recarimbar-brb.py --ver ~/lote-brb/brb/personagem.brb

  # o lado do Briba fixou o número mágico: carimbar o acervo inteiro
  ./I3.1-recarimbar-brb.py ~/lote-brb/brb --magic 'BRBA'

  # e se ele vier como bytes crus
  ./I3.1-recarimbar-brb.py ~/lote-brb/brb --magic-hex 42524200

  # o campo mudou de nome
  ./I3.1-recarimbar-brb.py ~/lote-brb/brb --renomear schema_version=version

  # a pasta virou actions/ mesmo
  ./I3.1-recarimbar-brb.py ~/lote-brb/brb --pasta performances/=actions/
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path


def alvos(caminhos):
    saida = []
    for c in caminhos:
        p = Path(c)
        if p.is_dir():
            saida.extend(sorted(p.rglob("*.brb")))
        elif p.suffix.lower() == ".brb":
            saida.append(p)
    return saida


def ver(p):
    try:
        with zipfile.ZipFile(p) as z:
            man = json.loads(z.read("manifest.json").decode("utf-8"))
            entradas = [(i.filename, i.compress_type) for i in z.infolist()]
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError,
            UnicodeDecodeError, OSError) as e:
        print(f"{p.name}: ILEGÍVEL — {type(e).__name__}: {e}")
        return 1
    print(f"{p.name}")
    print(f"  manifest.json: {json.dumps(man, ensure_ascii=False)}")
    comprimidas = [n for n, c in entradas if c != zipfile.ZIP_STORED]
    print(f"  {len(entradas)} entrada(s)"
          + (f", {len(comprimidas)} COMPRIMIDA(S): {comprimidas}" if comprimidas
             else ", todas armazenadas"))
    return 0


def recarimbar(p, args):
    """Reescreve só o manifesto. Devolve (mudou, motivo)."""
    try:
        with zipfile.ZipFile(p) as z:
            infos = z.infolist()
            conteudo = [(i, z.read(i.filename)) for i in infos]
            man_bruto = z.read("manifest.json").decode("utf-8")
            man = json.loads(man_bruto)
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError,
            UnicodeDecodeError, OSError) as e:
        return False, f"ilegível ({type(e).__name__})"

    antes = json.dumps(man, ensure_ascii=False, sort_keys=True)

    if args.magic is not None:
        man[args.campo_magic] = args.magic
    for velho, novo in args.renomear:
        if velho in man:
            man[novo] = man.pop(velho)
    for chave, valor in args.definir:
        man[chave] = valor

    trocas_de_pasta = list(args.pasta)
    mudou_manifesto = json.dumps(man, ensure_ascii=False, sort_keys=True) != antes
    if not mudou_manifesto and not trocas_de_pasta:
        return False, "nada a mudar"

    def novo_nome(nome):
        for velho, novo in trocas_de_pasta:
            if nome.startswith(velho):
                return novo + nome[len(velho):]
        return nome

    if args.simular:
        return True, f"simulado: {json.dumps(man, ensure_ascii=False)}"

    # Grava num temporário no MESMO diretório e troca por rename: um Ctrl+C no
    # meio não pode deixar `.brb` pela metade no lugar de um que estava bom.
    tmp = tempfile.NamedTemporaryFile(delete=False, dir=str(p.parent),
                                      prefix=".recarimbar-", suffix=".brb")
    tmp.close()
    try:
        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_STORED) as z:
            for info, dados in conteudo:
                nome = novo_nome(info.filename)
                if info.filename == "manifest.json":
                    dados = json.dumps(man, ensure_ascii=False).encode("utf-8")
                novo_info = zipfile.ZipInfo(nome, date_time=info.date_time)
                novo_info.compress_type = zipfile.ZIP_STORED
                novo_info.external_attr = info.external_attr
                z.writestr(novo_info, dados)
        if args.backup:
            shutil.copy2(p, p.with_suffix(".brb.antes"))
        os.replace(tmp.name, p)
    except OSError as e:
        Path(tmp.name).unlink(missing_ok=True)
        return False, f"não deu para gravar: {e}"
    return True, json.dumps(man, ensure_ascii=False)


def par(texto):
    if "=" not in texto:
        raise argparse.ArgumentTypeError(f"esperado `antigo=novo`, veio `{texto}`")
    return tuple(texto.split("=", 1))


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("caminho", nargs="+", help="arquivo `.brb` ou pasta (recursivo)")
    ap.add_argument("--ver", action="store_true", help="só mostra o manifesto e sai")
    ap.add_argument("--magic", help="novo número mágico, como texto")
    ap.add_argument("--magic-hex", help="novo número mágico, em hexadecimal")
    ap.add_argument("--campo-magic", default="magic",
                    help="nome do campo do número mágico (padrão: magic)")
    ap.add_argument("--renomear", type=par, action="append", default=[],
                    metavar="ANTIGO=NOVO", help="renomeia um campo do manifesto")
    ap.add_argument("--definir", type=par, action="append", default=[],
                    metavar="CAMPO=VALOR", help="define um campo do manifesto")
    ap.add_argument("--pasta", type=par, action="append", default=[],
                    metavar="ANTIGA/=NOVA/", help="renomeia uma pasta dentro do ZIP")
    ap.add_argument("--simular", action="store_true", help="mostra e não grava")
    ap.add_argument("--backup", action="store_true",
                    help="guarda o original como `.brb.antes`")
    args = ap.parse_args()

    if args.magic_hex:
        if args.magic:
            ap.error("use --magic OU --magic-hex, não os dois")
        try:
            args.magic = bytes.fromhex(args.magic_hex).decode("latin-1")
        except ValueError as e:
            ap.error(f"--magic-hex inválido: {e}")

    arquivos = alvos(args.caminho)
    if not arquivos:
        print("[I3.1] nenhum `.brb` nos caminhos informados")
        return 2

    if args.ver:
        return max(ver(p) for p in arquivos)

    if not (args.magic or args.renomear or args.definir or args.pasta):
        ap.error("informe pelo menos uma mudança (--magic, --renomear, "
                 "--definir, --pasta) ou use --ver")

    mudados = 0
    for p in arquivos:
        ok, motivo = recarimbar(p, args)
        mudados += bool(ok)
        print(f"{'MUDOU ' if ok else 'parado'} {p.name}: {motivo}")

    print(f"\n[I3.1] {mudados} de {len(arquivos)} arquivo(s) recarimbado(s)"
          + (" (simulação)" if args.simular else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
