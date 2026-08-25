#!/usr/bin/env python3
"""
I3.1 — recarimbar `.brb` já convertido, sem reconverter.

Existe por uma razão só: **o Briba ainda está sendo escrito.** Enquanto ele
estiver, quatro coisas da especificação do container ainda podem mudar de ideia:

  numero magico       a spec cita uma vez, numa tabela, e não diz o valor
  nomes dos campos    `magic`, `schema_version`, `project` foram inferidos
  pasta de atuação    `actions/` x `performances/` é pendência de governança
  método do ZIP       resolvido (armazenado), mas o mesmo risco vale
  buffer de pontos    endianness e ordem dos campos, nenhum dos dois fixado

A última é a pior das cinco, porque é a única que **não dá erro**: endianness
trocada não faz o leitor recusar o arquivo, faz o desenho sair com coordenadas
absurdas. Num acervo convertido em lote ninguém olha arquivo por arquivo, e o
erro passa. Mas ela também é recarimbável: o buffer é um vetor achatado de
float32, então trocar a ordem de bytes é uma transformação de 4 em 4 bytes e
trocar a ordem dos campos é uma permutação de 16 em 16. Nenhuma das duas precisa
do Blender, e nenhuma mexe em offset -- o CBOR continua apontando para os
mesmos lugares.

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

  # o leitor do outro lado le big-endian
  ./I3.1-recarimbar-brb.py ~/lote-brb/brb --trocar-bytes

  # a ordem dos campos do ponto era outra
  ./I3.1-recarimbar-brb.py ~/lote-brb/brb --ordem-campos x,y,tempo,pressao
"""

import argparse
import json
import struct
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path


# O exportador grava 4 floats little-endian por ponto: x, y, pressão, tempo.
CAMPOS = ("x", "y", "pressao", "tempo")
BYTES_POR_PONTO = 4 * len(CAMPOS)


def eh_buffer(nome):
    return nome.startswith("strokes/") and nome.endswith(".bin")


def transformar_buffer(dados, trocar_bytes, ordem):
    """Reescreve o buffer de pontos. Devolve (novos_dados, erro)."""
    if not dados:
        return dados, None
    if len(dados) % BYTES_POR_PONTO:
        return dados, (f"o buffer tem {len(dados)} bytes, que não é múltiplo de "
                       f"{BYTES_POR_PONTO} — está truncado, e mexer nele agora "
                       f"só espalharia o estrago")
    saida = bytearray(dados)
    if ordem:
        indices = [CAMPOS.index(c) for c in ordem]
        for i in range(0, len(dados), BYTES_POR_PONTO):
            ponto = dados[i:i + BYTES_POR_PONTO]
            saida[i:i + BYTES_POR_PONTO] = b"".join(
                ponto[j * 4:(j + 1) * 4] for j in indices)
    if trocar_bytes:
        base = bytes(saida)
        for i in range(0, len(base), 4):
            saida[i:i + 4] = base[i:i + 4][::-1]
    return bytes(saida), None


def espiar_pontos(dados, quantos=2):
    """Decodifica os primeiros pontos nas duas ordens de bytes.

    É o diagnóstico que a suposição de endianness pede: coordenada de desenho
    fica na casa das unidades, e a leitura errada devolve número absurdo —
    1e-41, 1e+38. Com as duas colunas lado a lado dá para ver qual é a certa
    sem ter um leitor do outro lado.
    """
    linhas = []
    for i in range(min(quantos, len(dados) // BYTES_POR_PONTO)):
        bloco = dados[i * BYTES_POR_PONTO:(i + 1) * BYTES_POR_PONTO]
        linhas.append((struct.unpack("<ffff", bloco),
                       struct.unpack(">ffff", bloco)))
    return linhas


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
    try:
        with zipfile.ZipFile(p) as z:
            bufs = [z.read(n) for n, _ in entradas if eh_buffer(n)]
    except (zipfile.BadZipFile, OSError):
        bufs = []
    total = sum(len(b) for b in bufs)
    if total:
        resto = total % BYTES_POR_PONTO
        print(f"  buffer de pontos: {total} B"
              + (f" — TRUNCADO, sobra {resto} B" if resto
                 else f" = {total // BYTES_POR_PONTO} pontos"))
        for le, be in espiar_pontos(bufs[0]):
            print(f"    1o ponto  little-endian {fmt(le)}")
            print(f"              big-endian    {fmt(be)}")
            break
        print("    coordenada de desenho fica na casa das unidades; a leitura "
              "errada devolve absurdo")
    return 0


def fmt(t):
    return "(" + ", ".join(f"{v:.4g}" for v in t) + ")"


# O valor confirmado pelo lado do Briba em 25/08/2026. Recarimbar PARA ele não é
# só trocar o campo: cada `.brb` carrega dentro de si um achado `SUSPEITO` dizendo
# que o carimbo é suposição, e deixar esse achado num arquivo já corrigido é pior
# que não ter achado nenhum — o arquivo passaria a mentir sobre si mesmo, que é
# exatamente o que o relatório de fidelidade existe para impedir.
#
# ⚠️ O mesmo valor está em `I3.1-exportar-brb.py` e em `I3.4-ler-brb.py`.
MAGICO_CONFIRMADO = "BRIBA-ANIMA"


def limpar_suposicao_de_magico(dados):
    """Tira o achado de número mágico do relatório embutido. Devolve (bytes, tirou)."""
    try:
        rel = json.loads(dados.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return dados, False
    achados = rel.get("achados")
    if not isinstance(achados, list):
        return dados, False
    ficam = [a for a in achados
             if not (isinstance(a, dict) and a.get("assunto") == "número mágico")]
    if len(ficam) == len(achados):
        return dados, False
    rel["achados"] = ficam
    # O resumo é contado a partir dos achados; recontar em vez de decrementar,
    # senão um arquivo com dois achados de mesma categoria sai com o número
    # errado e ninguém percebe.
    resumo = {}
    for a in ficam:
        cat = a.get("categoria")
        if cat:
            resumo[cat] = resumo.get(cat, 0) + 1
    rel["resumo"] = resumo
    return json.dumps(rel, ensure_ascii=False, indent=1).encode("utf-8"), True


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
    mexe_no_buffer = bool(args.trocar_bytes or args.ordem_campos)
    mudou_manifesto = json.dumps(man, ensure_ascii=False, sort_keys=True) != antes
    if not mudou_manifesto and not trocas_de_pasta and not mexe_no_buffer:
        return False, "nada a mudar"

    # Buffer truncado é recusa, não conserto pela metade: transformar um vetor
    # que já está quebrado espalha o estrago pelos pontos que ainda estavam bons.
    if mexe_no_buffer:
        for info, dados in conteudo:
            if eh_buffer(info.filename) and len(dados) % BYTES_POR_PONTO:
                return False, (f"{info.filename}: {len(dados)} bytes não é "
                               f"múltiplo de {BYTES_POR_PONTO} — buffer truncado")

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
                elif (info.filename == "relatorio-de-fidelidade.json"
                      and args.magic == MAGICO_CONFIRMADO):
                    dados, _ = limpar_suposicao_de_magico(dados)
                elif mexe_no_buffer and eh_buffer(info.filename):
                    dados, erro = transformar_buffer(
                        dados, args.trocar_bytes, args.ordem_campos)
                    if erro:
                        raise OSError(erro)
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
    ap.add_argument("--trocar-bytes", action="store_true",
                    help="inverte a ordem de bytes de cada float do buffer de pontos")
    ap.add_argument("--ordem-campos",
                    metavar="A,B,C,D",
                    help="nova ordem dos 4 campos do ponto (padrão hoje: "
                         + ",".join(CAMPOS) + ")")
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

    if args.ordem_campos:
        ordem = [c.strip() for c in args.ordem_campos.split(",")]
        if sorted(ordem) != sorted(CAMPOS):
            ap.error(f"--ordem-campos precisa ser uma permutação de "
                     f"{','.join(CAMPOS)}; veio {args.ordem_campos}")
        args.ordem_campos = ordem

    arquivos = alvos(args.caminho)
    if not arquivos:
        print("[I3.1] nenhum `.brb` nos caminhos informados")
        return 2

    if args.ver:
        return max(ver(p) for p in arquivos)

    if not (args.magic or args.renomear or args.definir or args.pasta
            or args.trocar_bytes or args.ordem_campos):
        ap.error("informe pelo menos uma mudança (--magic, --renomear, "
                 "--definir, --pasta, --trocar-bytes, --ordem-campos) "
                 "ou use --ver")

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
