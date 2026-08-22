"""
I3.4 — leitor de `.brb` que devolve a mesma árvore canônica do lado do Nuclear.

Escrito **a partir da especificação** (`brb-format.md`, validada em 20/08/2026),
nunca a partir do código do Briba. A especificação atravessa a fronteira entre os
dois lados; código, nunca — I0.1, regra 4. Este arquivo é a prova de que dá para
ler o formato sabendo só o que a spec diz.

Roda em Python puro, sem dependência externa: não há `cbor2` nem no sistema nem
no Python do Nuclear, então o decodificador CBOR necessário vem embutido abaixo.

Uso:
    python3 I3.4-ler-brb.py arquivo.brb saida.json
"""
import json
import struct
import sys
import zipfile
from pathlib import Path

SCHEMA = 1


# --------------------------------------------------------------------------- #
# CBOR — só o subconjunto que a spec usa (RFC 8949)
# --------------------------------------------------------------------------- #

class ErroCBOR(Exception):
    pass


class LeitorCBOR:
    """Decodificador mínimo. Cobre inteiro, bytes, texto, lista, mapa,
    booleano, nulo e float — que é tudo que `document.cbor` precisa."""

    def __init__(self, dados: bytes):
        self.d = dados
        self.i = 0

    def _byte(self):
        if self.i >= len(self.d):
            raise ErroCBOR("fim inesperado dos dados")
        b = self.d[self.i]
        self.i += 1
        return b

    def _bytes(self, n):
        if self.i + n > len(self.d):
            raise ErroCBOR(f"esperava {n} bytes, faltou")
        v = self.d[self.i:self.i + n]
        self.i += n
        return v

    def _tamanho(self, info):
        if info < 24:
            return info
        if info == 24:
            return self._byte()
        if info == 25:
            return struct.unpack(">H", self._bytes(2))[0]
        if info == 26:
            return struct.unpack(">I", self._bytes(4))[0]
        if info == 27:
            return struct.unpack(">Q", self._bytes(8))[0]
        if info == 31:
            return None          # tamanho indefinido
        raise ErroCBOR(f"tamanho não suportado: {info}")

    def ler(self):
        b = self._byte()
        maior, info = b >> 5, b & 0x1F

        if maior == 0:                                   # inteiro positivo
            return self._tamanho(info)
        if maior == 1:                                   # inteiro negativo
            return -1 - self._tamanho(info)
        if maior == 2:                                   # bytes
            n = self._tamanho(info)
            return self._bytes(n) if n is not None else self._indefinido_bytes()
        if maior == 3:                                   # texto
            n = self._tamanho(info)
            cru = self._bytes(n) if n is not None else self._indefinido_bytes()
            return cru.decode("utf-8", "replace")
        if maior == 4:                                   # lista
            n = self._tamanho(info)
            if n is None:
                out = []
                while not self._quebra():
                    out.append(self.ler())
                return out
            return [self.ler() for _ in range(n)]
        if maior == 5:                                   # mapa
            n = self._tamanho(info)
            out = {}
            if n is None:
                while not self._quebra():
                    k = self.ler(); out[self._chave(k)] = self.ler()
                return out
            for _ in range(n):
                k = self.ler(); out[self._chave(k)] = self.ler()
            return out
        if maior == 6:                                   # tag — ignora e segue
            self._tamanho(info)
            return self.ler()
        if maior == 7:                                   # simples e float
            if info == 20: return False
            if info == 21: return True
            if info == 22: return None
            if info == 23: return None                   # indefinido
            if info == 25: return self._float16()
            if info == 26: return struct.unpack(">f", self._bytes(4))[0]
            if info == 27: return struct.unpack(">d", self._bytes(8))[0]
            if info == 31: raise ErroCBOR("quebra fora de contexto")
            return self._tamanho(info)
        raise ErroCBOR(f"tipo maior desconhecido: {maior}")

    def _chave(self, k):
        return k if isinstance(k, (str, int)) else str(k)

    def _quebra(self):
        if self.i < len(self.d) and self.d[self.i] == 0xFF:
            self.i += 1
            return True
        return False

    def _indefinido_bytes(self):
        partes = []
        while not self._quebra():
            partes.append(self.ler())
        return b"".join(partes)

    def _float16(self):
        (bits,) = struct.unpack(">H", self._bytes(2))
        sinal = (bits >> 15) & 1
        exp = (bits >> 10) & 0x1F
        frac = bits & 0x3FF
        if exp == 0:
            v = frac * 2 ** -24
        elif exp == 31:
            v = float("inf") if frac == 0 else float("nan")
        else:
            v = (1 + frac / 1024) * 2 ** (exp - 15)
        return -v if sinal else v


def cbor_para_python(dados: bytes):
    return LeitorCBOR(dados).ler()


# --------------------------------------------------------------------------- #
# leitura do container
# --------------------------------------------------------------------------- #

def ler_brb(caminho):
    """Devolve (manifesto, documento, avisos). Nunca levanta por falta de
    arquivo opcional — o que falta vira aviso, porque o relatório de fidelidade
    precisa distinguir 'não veio' de 'quebrou'."""
    avisos = []
    with zipfile.ZipFile(caminho) as z:
        nomes = set(z.namelist())

        # O Python lê ZIP comprimido e armazenado igual, então esta checagem
        # não é firula: o leitor do Briba 0.0.1 **recusa** entrada comprimida
        # ("método 8; este leitor só aceita armazenamento direto"). Sem
        # verificar aqui, o arnês aprovaria um `.brb` que o app não abre — foi
        # exatamente o que aconteceu em 21/08.
        comprimidas = [i.filename for i in z.infolist()
                       if i.compress_type != zipfile.ZIP_STORED]
        if comprimidas:
            avisos.append(
                f"{len(comprimidas)} entradas comprimidas (ex.: {comprimidas[0]}) — "
                f"o leitor do Briba só aceita armazenamento direto e vai recusar "
                f"o arquivo")

        if "manifest.json" not in nomes:
            raise ValueError("manifest.json ausente — não é um .brb válido")
        manifesto = json.loads(z.read("manifest.json").decode("utf-8"))

        if "document.cbor" not in nomes:
            raise ValueError("document.cbor ausente — não é um .brb válido")
        documento = cbor_para_python(z.read("document.cbor"))

        buffers = sorted(n for n in nomes if n.startswith("strokes/"))
        if not buffers:
            avisos.append("nenhum buffer em strokes/ — geometria de traço pode não ter sido exportada")

        # A spec marca o rename actions/ -> performances/ como pendência de
        # governança. Aceitar os dois enquanto o Anexo A não fecha evita que o
        # comparador reprove um exportador correto por causa do nome da pasta.
        atuacoes = [n for n in nomes if n.startswith(("performances/", "actions/"))]
        if any(n.startswith("actions/") for n in atuacoes):
            avisos.append("usa a pasta antiga actions/ — a spec pede performances/")

        if "thumbnail.png" not in nomes:
            avisos.append("thumbnail.png ausente")

        # O exportador grava o que decidiu perder. O comparador precisa disso:
        # perda declarada é limitação conhecida do nível 1/2; perda calada é
        # defeito. Sem ler este arquivo, o arnês aprovaria as duas igual.
        graf_mascaras = None
        if "mascaras.json" in nomes:
            try:
                graf_mascaras = json.loads(z.read("mascaras.json").decode("utf-8"))
            except (ValueError, KeyError):
                avisos.append("mascaras.json ilegível")

        fidelidade = None
        if "relatorio-de-fidelidade.json" in nomes:
            try:
                fidelidade = json.loads(z.read("relatorio-de-fidelidade.json").decode("utf-8"))
            except (ValueError, KeyError):
                avisos.append("relatorio-de-fidelidade.json ilegível")
        else:
            avisos.append("o .brb não traz relatório de fidelidade — "
                          "não dá para saber o que o exportador sabe ter perdido")

        return manifesto, documento, avisos, fidelidade, graf_mascaras, {
            "buffers_de_traco": len(buffers),
            "assets": len([n for n in nomes if n.startswith("assets/")]),
            "atuacoes": len(atuacoes),
            "audio": len([n for n in nomes if n.startswith("audio/")]),
        }


# --------------------------------------------------------------------------- #
# tradução para a forma canônica
# --------------------------------------------------------------------------- #

def campo(d, *nomes, padrao=None):
    """Busca tolerante: a spec usa identificadores em inglês, mas um exportador
    em desenvolvimento pode ainda estar em outro nome. Tentar variantes evita
    reprovar por detalhe de grafia — a divergência de verdade aparece nos
    números, não no nome do campo."""
    if not isinstance(d, dict):
        return padrao
    for n in nomes:
        if n in d:
            return d[n]
    return padrao


def conteudo_tipo(v):
    """`content` é enum. Em CBOR pode vir como mapa de uma chave, como par
    [tag, valor], ou como string quando não há carga."""
    if isinstance(v, dict) and len(v) == 1:
        return next(iter(v))
    if isinstance(v, (list, tuple)) and v:
        return str(v[0])
    if isinstance(v, str):
        return v
    return None


def conteudo_carga(v):
    if isinstance(v, dict) and len(v) == 1:
        return next(iter(v.values()))
    if isinstance(v, (list, tuple)) and len(v) > 1:
        return v[1]
    return None


def achatar_camadas(documento):
    """Devolve as camadas em ordem de desenho, com o nome do grupo pai.

    Pela spec, `Group` não guarda filhos: eles se acham filtrando por `parent`.
    Então a árvore é reconstruída aqui, e não lida pronta.
    """
    camadas = campo(documento, "layers", "camadas", padrao=[]) or []
    por_id = {}
    for c in camadas:
        cid = campo(c, "id")
        if cid is not None:
            por_id[cid] = c

    def nome_do_pai(c):
        pai = campo(c, "parent", "pai")
        if pai is None:
            return None
        return campo(por_id.get(pai, {}), "name", "nome")

    saida = []
    for c in sorted(camadas, key=lambda x: (campo(x, "order", "ordem", padrao=0) or 0,
                                            str(campo(x, "name", "nome", padrao="")))):
        conteudo = campo(c, "content", "conteudo")
        tipo = conteudo_tipo(conteudo)
        quadros = []
        if tipo and tipo.lower().startswith("drawing"):
            for fr in (conteudo_carga(conteudo) or []):
                fc = campo(fr, "content", "conteudo")
                ftipo = conteudo_tipo(fc)
                carga = conteudo_carga(fc)
                tracos = carga if ftipo and ftipo.lower().startswith("drawn") else []
                quadros.append({
                    "quadro": campo(fr, "index", "quadro", padrao=0),
                    "em_espera": bool(ftipo and ftipo.lower().startswith("held")),
                    "referencia": campo(carga, "reference", "referencia") if isinstance(carga, dict) else None,
                    "n_tracos": len(tracos or []),
                    "tracos": [
                        {
                            "brush": campo(t, "brush", "pincel"),
                            "cor": campo(t, "color", "cor"),
                            "fechado": bool(campo(t, "closed", "fechado", padrao=False)),
                            "suavizacao": campo(t, "smoothing", "suavizacao"),
                            "n_pontos": campo(campo(t, "points", "pontos", padrao={}) or {}, "size", "n", padrao=None),
                        }
                        for t in (tracos or [])
                    ],
                })

        saida.append({
            "ordem_de_desenho": campo(c, "order", "ordem", padrao=0),
            "nome": campo(c, "name", "nome"),
            "grupo_pai": nome_do_pai(c),
            "tipo_de_conteudo": tipo,
            "visivel": bool(campo(c, "visible", "visivel", padrao=True)),
            "travada": bool(campo(c, "locked", "travada", padrao=False)),
            "opacidade": campo(c, "opacity", "opacidade", padrao=1.0),
            "modo_de_mistura": campo(c, "blend_mode", "modo_de_mistura", padrao="Normal"),
            "n_quadros": len(quadros),
            "quadros_expostos": [q["quadro"] for q in quadros],
            "quadros_em_espera": [q["quadro"] for q in quadros if q["em_espera"]],
            "quadros": quadros,
        })
    return saida


def para_canonico(manifesto, documento, avisos, fidelidade, graf_mascaras, contagens):
    camadas = achatar_camadas(documento)
    n_tracos = sum(q["n_tracos"] for c in camadas for q in c["quadros"])
    return {
        "schema": SCHEMA,
        "origem": "brb",
        "manifesto": {
            "numero_magico": campo(manifesto, "magic", "numero_magico"),
            "versao_do_esquema": campo(manifesto, "schema_version", "versao_do_esquema"),
            "projeto": campo(manifesto, "project", "projeto"),
        },
        "cena": {
            "quadros": [campo(documento, "frame_start", padrao=None),
                        campo(documento, "frame_end", "duration", padrao=None)],
            "fps": campo(documento, "frame_rate", "fps"),
            "resolucao": campo(documento, "resolution", "resolucao"),
        },
        "resumo": {
            "n_camadas": len(camadas),
            "n_grupos": sum(1 for c in camadas
                            if (c["tipo_de_conteudo"] or "").lower().startswith("group")),
            "n_tracos": n_tracos,
            "n_quadros_em_espera": sum(len(c["quadros_em_espera"]) for c in camadas),
            **contagens,
        },
        "camadas": camadas,
        "avisos": avisos,
        "fidelidade_declarada": fidelidade,
        "mascaras_preservadas": graf_mascaras,
    }


def main():
    if len(sys.argv) < 3:
        print(__doc__.strip())
        return 2
    origem, destino = Path(sys.argv[1]), Path(sys.argv[2])
    if not origem.exists():
        print(f"[I3.4] ERRO: {origem} não existe.")
        print("       Isto é esperado enquanto o exportador do I3.1 não existir —")
        print("       o comparador nasce reprovando de propósito.")
        return 3

    manifesto, documento, avisos, fidelidade, graf_mascaras, contagens = ler_brb(origem)
    canon = para_canonico(manifesto, documento, avisos, fidelidade, graf_mascaras, contagens)
    destino.write_text(json.dumps(canon, ensure_ascii=False, indent=1, sort_keys=True),
                       encoding="utf-8")
    r = canon["resumo"]
    print(f"[I3.4] {origem.name}: {r['n_camadas']} camadas, {r['n_tracos']} traços, "
          f"{r['n_quadros_em_espera']} em espera -> {destino}")
    for a in avisos:
        print(f"       aviso: {a}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
