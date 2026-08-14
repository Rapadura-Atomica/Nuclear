"""A bancada do artista atravessa a troca de take — e a troca de cena.

Um take é um arquivo, e arquivo do Blender carrega a bancada junto: o pincel com
o tamanho e a suavização que a pessoa ajustou, os materiais que ela criou, a
tela em que ela trabalha. Trocar de take devolvia tudo ao estado gravado no
arquivo seguinte — o artista reajustava o pincel a cada plano.

O que já estava resolvido é a TELA: o `.nuc` do take é aberto com `load_ui=False`
(`takefile.open_take`), então o layout é o do artista, não o do arquivo. Falta o
resto, que é o que este módulo faz: ANOTAR a bancada ao sair de um take e
REMONTAR ao abrir o seguinte.

**Onde cada metade mora, e por quê.** A bancada tem duas coisas de donos
diferentes:

    o PINCEL   é da pessoa   -> um JSON na config do Nuclear (a máquina)
    o MATERIAL é do trabalho -> ao lado da biblioteca, que é do episódio

Isto foi aprendido do jeito difícil. A bancada inteira morava no board, e cada
CENA é um board: o artista escolhia a caneta e a cor na CENA01, ia para a CENA02
e recebia de volta o lápis verde de fábrica — "ele sempre volta para a cor verde
padrão". É o mesmo defeito que a biblioteca já teve (cada cena nascia com o
elenco vazio) e a mesma correção: o que não é da cena não pode ser gravado na
pasta dela.

Em arquivo próprio e não no `project.json` porque isto é bancada, não conteúdo —
o índice do board não deve mudar de checksum porque alguém engrossou o traço.

Como a bancada é lida: não há lista de campos escrita à mão. Percorremos as
propriedades RNA graváveis de tipo simples (número, booleano, enum, cor) e
guardamos o que estiver lá. Uma lista fixa envelheceria calada — a cada build do
Nuclear que renomeasse um ajuste, ele deixaria de acompanhar o artista sem
ninguém perceber.
"""

from __future__ import annotations

import json
from pathlib import Path

import bpy

BENCH_FILE = "workspace.json"

#: Tipos de propriedade que sabemos gravar em JSON e devolver.
SIMPLE_TYPES = {"BOOLEAN", "INT", "FLOAT", "ENUM", "STRING"}

#: Identidade e contabilidade do datablock — nada disso é ajuste de bancada, e
#: escrever por cima trocaria um pincel por outro (ou mexeria no dono do dado).
SKIP_PROPS = {
    "name", "name_full", "tag", "use_fake_user", "use_extra_user",
    "is_runtime_data", "is_library_indirect", "original", "users",
    "asset_data", "library", "library_weak_reference", "override_library",
    "preview", "session_uid",
}

#: Materiais que o take já monta sozinho — a biblioteca manda neles (a cor do
#: personagem é a chave que aponta para o rig), então a bancada não os carrega.
MANAGED_PREFIXES = ("SB_LN_", "SB_PROP_")
MANAGED_NAMES = {"SB_BG", "SB_PROPS"}


# ---------------------------------------------------------------------------
# Ler e escrever uma struct RNA qualquer
# ---------------------------------------------------------------------------

def dump_struct(struct) -> dict:
    """Ajustes graváveis de tipo simples de uma struct RNA."""
    if struct is None:
        return {}
    out = {}
    for prop in struct.bl_rna.properties:
        if prop.is_readonly or prop.identifier in SKIP_PROPS:
            continue
        if prop.type not in SIMPLE_TYPES:
            continue
        try:
            valor = getattr(struct, prop.identifier)
        except AttributeError:
            continue
        if getattr(prop, "is_array", False):
            valor = list(valor)
        elif prop.type == "ENUM" and getattr(prop, "is_enum_flag", False):
            valor = sorted(valor)
        out[prop.identifier] = valor
    return out


def apply_struct(struct, data: dict) -> int:
    """Devolve os ajustes à struct. Devolve quantos entraram.

    Cada campo entra sozinho, no seu try: um ajuste que sumiu do build (ou um
    enum que não aceita mais aquele valor) não pode levar junto os outros
    quarenta que ainda servem.
    """
    if struct is None or not data:
        return 0
    aplicados = 0
    for chave, valor in data.items():
        try:
            atual = getattr(struct, chave)
        except AttributeError:
            continue
        try:
            if hasattr(atual, "__len__") and not isinstance(atual, str):
                if len(atual) != len(valor):
                    continue
                for i, item in enumerate(valor):
                    atual[i] = item
            else:
                if atual == valor:
                    continue
                setattr(struct, chave, valor)
            aplicados += 1
        except (TypeError, ValueError, AttributeError):
            continue
    return aplicados


# ---------------------------------------------------------------------------
# A bancada
# ---------------------------------------------------------------------------

def _gp_paint(context):
    settings = getattr(context, "tool_settings", None)
    return getattr(settings, "gpencil_paint", None) if settings else None


#: Campos que identificam um pincel do catálogo de assets. No Blender 5.0 quem
#: está ativo não é um datablock que se possa atribuir — `gpencil_paint.brush` é
#: SÓ LEITURA — e sim um asset apontado por esta referência fraca.
ASSET_REF_FIELDS = ("asset_library_type", "asset_library_identifier",
                    "relative_asset_identifier")


def brush_asset(paint) -> dict:
    """Qual pincel do catálogo está ativo, num dicionário gravável em JSON."""
    ref = getattr(paint, "brush_asset_reference", None)
    if ref is None:
        return {}
    return {campo: getattr(ref, campo, "") for campo in ASSET_REF_FIELDS}


def _paint_area():
    """Uma área 3D para emprestar ao operador de pincel, ou None.

    O timer roda sem área nenhuma no contexto, e `brush.asset_activate` é um
    operador de modo de pintura: chamado de lá, ele recusa por poll e o pincel
    do artista nunca volta. Emprestar a viewport é o que faz a chamada valer.
    """
    for window in getattr(bpy.context.window_manager, "windows", ()):
        tela = getattr(window, "screen", None)
        if tela is None:
            continue
        for area in tela.areas:
            if area.type != "VIEW_3D":
                continue
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            if region is not None:
                return {"window": window, "area": area, "region": region}
    return None


def activate_brush_asset(paint, ref: dict) -> bool:
    """Volta a ativar o pincel que o artista estava usando. Devolve se trocou.

    O nome do pincel ativo estava sendo ANOTADO e nunca devolvido: `restore` só
    aplicava ajustes aos pincéis existentes, e qual deles ficava na mão do
    artista continuava vindo do arquivo que abriu. Como cada take é um arquivo,
    escolher o pincel de tinta num plano e cair no lápis no plano seguinte era o
    comportamento normal do add-on.

    Trocar exige o operador (a propriedade é somente leitura), e o operador
    exige contexto de pintura — daí a segunda tentativa com a viewport
    emprestada, que é a que funciona quando a chamada vem do timer.
    """
    if not ref or bpy.app.background:
        return False
    if brush_asset(paint) == ref:
        return False  # já é este: não custar um operador por troca de take

    argumentos = {
        "asset_library_type": ref.get("asset_library_type", "ESSENTIALS"),
        "asset_library_identifier": ref.get("asset_library_identifier", ""),
        "relative_asset_identifier": ref.get("relative_asset_identifier", ""),
    }
    try:
        bpy.ops.brush.asset_activate(**argumentos)
        return True
    except (RuntimeError, TypeError):
        pass

    área = _paint_area()
    if área is None:
        return False
    try:
        with bpy.context.temp_override(**área):
            bpy.ops.brush.asset_activate(**argumentos)
    except (RuntimeError, TypeError):
        # Pincel que saiu do catálogo, ou modo de pintura ainda não de pé.
        return False
    return True


def is_managed(name: str) -> bool:
    return name in MANAGED_NAMES or name.startswith(MANAGED_PREFIXES)


def capture(context, ob=None) -> dict:
    """Anota a bancada como ela está agora.

    Os pincéis são gravados por NOME, todos os que existem na sessão — não só o
    ativo. Quem afina o lápis e a borracha quer os dois afinados no take
    seguinte, e o pincel ativo do arquivo que abrir pode ser qualquer um deles.
    """
    paint = _gp_paint(context)
    brushes = {}
    for brush in bpy.data.brushes:
        if getattr(brush, "gpencil_settings", None) is None:
            continue
        brushes[brush.name] = {
            "brush": dump_struct(brush),
            "gpencil": dump_struct(brush.gpencil_settings),
        }

    dados = {
        "paint": dump_struct(paint),
        "active_brush": getattr(getattr(paint, "brush", None), "name", ""),
        "brush_asset": brush_asset(paint),
        "brushes": brushes,
        "materials": [],
        "active_material": "",
    }

    if ob is not None and getattr(ob, "data", None) is not None:
        for material in ob.data.materials:
            if material is None or material.grease_pencil is None:
                continue
            if is_managed(material.name):
                continue
            dados["materials"].append({
                "name": material.name,
                "gpencil": dump_struct(material.grease_pencil),
            })
        índice = ob.active_material_index
        if 0 <= índice < len(ob.data.materials):
            ativo = ob.data.materials[índice]
            dados["active_material"] = ativo.name if ativo else ""
    return dados


#: O pincel não existe no instante em que o take abre — ele nasce quando o
#: Nuclear entra em modo de desenho e ativa o pincel do catálogo de assets, o
#: que acontece um tique depois. Por isso a bancada espera por ele, e não o
#: contrário: sem esta espera o "tamanho do traço continua o mesmo" só valia por
#: acaso, quando o modo de desenho tinha entrado a tempo.
BRUSH_RETRY = 0.15
BRUSH_TRIES = 20

#: Bancada esperando o pincel aparecer (uma por vez: é sempre a última).
_PENDING = {}


def apply_brushes(data: dict) -> int:
    """Devolve os ajustes a cada pincel que já exista nesta sessão.

    Pincel ausente é pulado de propósito: criar um datablock homônimo aqui daria
    um pincel de mentira ao lado do de verdade.
    """
    total = 0
    for nome, guardado in (data.get("brushes") or {}).items():
        brush = bpy.data.brushes.get(nome)
        if brush is None:
            continue
        total += apply_struct(brush, guardado.get("brush"))
        total += apply_struct(brush.gpencil_settings, guardado.get("gpencil"))
    return total


def brushes_present(data: dict) -> bool:
    """Algum dos pincéis anotados já existe na sessão?"""
    return any(bpy.data.brushes.get(nome) is not None
               for nome in (data.get("brushes") or {}))


def _brush_tick():
    """Uma exceção aqui faria o Blender DESREGISTRAR o timer, e a bancada
    pararia de acompanhar o artista em silêncio — daí o `try` em volta de tudo.
    """
    try:
        return _brush_tick_inner()
    except Exception as exc:  # noqa: BLE001 — o timer não pode morrer
        print(f"[storyboard] bancada: {exc}")
        _PENDING.clear()
        return None


def _brush_tick_inner():
    dados, faltam = _PENDING.get("data"), _PENDING.get("tries", 0)
    if not dados or faltam <= 0:
        _PENDING.clear()
        return None
    _PENDING["tries"] = faltam - 1
    if not brushes_present(dados):
        return BRUSH_RETRY

    # Os ajustes primeiro, e uma vez só: eles dependem apenas de os pincéis
    # existirem. Deixá-los atrás da troca de pincel — que pode nunca acontecer,
    # se o pincel saiu do catálogo — devolveria o artista a um traço de fábrica
    # por causa de um detalhe que nada tem a ver com a espessura.
    if not _PENDING.get("applied"):
        apply_brushes(dados)
        _PENDING["applied"] = True

    # Devolver o pincel ATIVO depende de o modo de pintura estar de pé, o que
    # acontece depois: enquanto o operador recusar, tentamos de novo dentro do
    # mesmo orçamento de tentativas.
    paint = _gp_paint(bpy.context)
    ref = dados.get("brush_asset") or {}
    if ref and paint is not None and brush_asset(paint) != ref:
        if not activate_brush_asset(paint, ref):
            return BRUSH_RETRY
        # Trocar de pincel traz OUTRO datablock para a mão: os ajustes anotados
        # precisam ser postos nele também.
        apply_brushes(dados)

    _PENDING.clear()
    return None


def restore_brushes_soon(data: dict) -> bool:
    """Espera o pincel aparecer para devolver os ajustes a ele.

    Em background não há loop de eventos (nem modo de pintura): o que dava para
    fazer já foi feito na hora.
    """
    data = data or {}
    if bpy.app.background or not (data.get("brushes") or data.get("brush_asset")):
        return False
    _PENDING.update({"data": data, "tries": BRUSH_TRIES})
    # `persistent`: entre abrir o take e o pincel aparecer passa justamente um
    # carregamento de arquivo, que descarta os timers comuns.
    if not bpy.app.timers.is_registered(_brush_tick):
        bpy.app.timers.register(_brush_tick, first_interval=BRUSH_RETRY,
                                persistent=True)
    return True


def restore(context, ob=None, data: dict = None) -> int:
    """Remonta a bancada no take que acabou de abrir. Devolve quantos ajustes."""
    if not data:
        return 0
    total = 0

    paint = _gp_paint(context)
    total += apply_struct(paint, data.get("paint"))
    if paint is not None and activate_brush_asset(paint, data.get("brush_asset")):
        total += 1
    total += apply_brushes(data)

    if ob is None or getattr(ob, "data", None) is None:
        return total

    for guardado in data.get("materials") or []:
        nome = guardado.get("name") or ""
        if not nome or is_managed(nome):
            continue
        total += _ensure_material(ob, nome, guardado.get("gpencil"))

    ativo = data.get("active_material") or ""
    if ativo:
        for i, material in enumerate(ob.data.materials):
            if material is not None and material.name == ativo:
                ob.active_material_index = i
                break
    return total


def _ensure_material(ob, name: str, gpencil: dict) -> int:
    """Garante o material do artista neste take, com os ajustes dele."""
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
    if material.grease_pencil is None:
        bpy.data.materials.create_gpencil_data(material)
    aplicados = apply_struct(material.grease_pencil, gpencil)
    if all(slot is None or slot.name != material.name for slot in ob.data.materials):
        ob.data.materials.append(material)
    return aplicados


# ---------------------------------------------------------------------------
# Disco
# ---------------------------------------------------------------------------

#: Chaves da bancada que são da PESSOA e vão para a config da máquina. O resto
#: (materiais) é do trabalho e fica junto da biblioteca.
BRUSH_KEYS = ("paint", "active_brush", "brush_asset", "brushes")


def bench_path(store) -> Path:
    """Onde ficam os materiais do artista: ao lado da biblioteca do episódio.

    As cenas de um episódio dividem o mesmo `library.json`, e um material que o
    artista criou é do mesmo tipo de coisa que um personagem cadastrado — some
    da CENA02 pelo mesmo motivo que o elenco sumia. Board com biblioteca própria
    continua com a bancada na pasta dele, que é o caso de sempre.
    """
    try:
        return Path(store.library_file).parent / BENCH_FILE
    except (AttributeError, TypeError):
        return Path(store.paths.root) / BENCH_FILE


def brushes_path() -> Path:
    """Onde ficam os pincéis: na config do Nuclear, e não em board nenhum.

    O pincel é da PESSOA — o mesmo em qualquer cena, episódio ou projeto. Num
    JSON nosso (e não em `AddonPreferences`) porque preferência só vai ao disco
    quando o Blender resolve gravá-la, e o app template do Nuclear já as devolveu
    para a fábrica mais de uma vez.
    """
    pasta = bpy.utils.user_resource("CONFIG", path="nuclear_storyboard", create=True)
    return Path(pasta) / BENCH_FILE


def _write(path: Path, data: dict) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    except (OSError, TypeError, ValueError):
        return False
    return True


def _read(path: Path) -> dict:
    try:
        dados = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def save(store, data: dict) -> bool:
    """Grava a bancada: os pincéis na máquina, os materiais no episódio.

    Falha de escrita não derruba o salvar do take.
    """
    pincéis = {chave: data[chave] for chave in BRUSH_KEYS if chave in data}
    materiais = {chave: valor for chave, valor in data.items()
                 if chave not in BRUSH_KEYS}
    ok = _write(brushes_path(), pincéis) if pincéis else True
    return _write(bench_path(store), materiais) and ok


def load(store) -> dict:
    """A bancada inteira, juntando as duas metades.

    O `workspace.json` de um board gravado ANTES desta separação tem tudo
    dentro: ele continua sendo lido, e o que estiver na config vence — senão o
    artista perderia o pincel na primeira vez que abrisse o board novo.
    """
    dados = _read(bench_path(store))
    if not dados:
        # Board anterior à bancada ao lado da biblioteca: o arquivo pode estar
        # na pasta dele mesmo.
        dados = _read(Path(store.paths.root) / BENCH_FILE)
    dados.update(_read(brushes_path()))
    return dados


def capture_to_disk(context, store, ob=None) -> dict:
    dados = capture(context, ob)
    save(store, dados)
    return dados


def brush_asset_matches(context, data: dict) -> bool:
    """O pincel ativo já é o que a bancada anotou?"""
    ref = (data or {}).get("brush_asset") or {}
    if not ref:
        return True
    paint = _gp_paint(context)
    return paint is not None and brush_asset(paint) == ref


def restore_from_disk(context, store, ob=None) -> int:
    dados = load(store)
    total = restore(context, ob, dados)
    # A espera vale para os dois lados da bancada: os ajustes, que precisam do
    # datablock do pincel, e QUAL pincel está ativo, que precisa do modo de
    # pintura — e ele só entra um tique depois de o arquivo abrir.
    if not brushes_present(dados) or not brush_asset_matches(context, dados):
        restore_brushes_soon(dados)
    return total
