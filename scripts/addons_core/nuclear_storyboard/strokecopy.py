"""Copiar e colar desenho de um take para o outro, sem inventar material novo.

O copiar/colar nativo do Grease Pencil casa os materiais por `session_uid` — um
número de execução, dado ao datablock quando ele entra na memória. Dentro do
mesmo arquivo isso funciona. Entre dois takes, não: trocar de take é abrir outro
arquivo, e ao recarregar o mesmo material ganha outro uid (medido: o `SB_LN_x`
saiu de 167 para 256 só de reabrir). O casamento falha, o Blender cai no ramo
"esse material sumiu, faço um novo" e cada colagem deixa mais um material sem
nome nem cor na lista do objeto. É o "não criar novos" e o "a lista de materiais
duplicando a cada take" que o artista relatou.

Aqui o casamento é por NOME, que é o que atravessa arquivo — e é a mesma chave
que a biblioteca já usa (`SB_LN_<personagem>`). A ordem de resolução, ao colar:

    slot que o take já tem  ->  material do arquivo  ->  criar, com os ajustes
                                                          anotados na cópia

Só o último passo cria alguma coisa, e mesmo ele cria a cor CERTA, porque a
cópia leva os ajustes do material junto.

A área de transferência é uma variável de módulo com dados puros (números e
strings). Ela precisa sobreviver ao `open_mainfile` que acontece entre copiar e
colar — qualquer referência a datablock viraria ponteiro morto ali.

Colar é POR CAMADA: a camada de origem é recriada no destino com o papel dela
(BG, personagens, objetos). Amontoar tudo na camada ativa desmontaria a
separação que o board inteiro depende — e é ela que diz de quem é cada traço.
"""

from __future__ import annotations

import bpy
from bpy.types import Operator

from . import gp, workspace
from .translations import _, apply_context

#: O desenho copiado. `None` = nada foi copiado nesta sessão do Nuclear.
_BUFFER = None

#: Como cada tipo de atributo é lido em bloco: (campo do `foreach_get`, quantos
#: números por elemento). Ler ponto a ponto pela API custava meio segundo para
#: colar um plano bem trabalhado (20 mil pontos, medido); em bloco é o mesmo
#: dado com uma chamada por atributo.
FOREACH = {
    "FLOAT": ("value", 1),
    "INT": ("value", 1),
    "INT8": ("value", 1),
    "INT32_2D": ("value", 2),
    "BOOLEAN": ("value", 1),
    "FLOAT2": ("vector", 2),
    "FLOAT_VECTOR": ("vector", 3),
    "FLOAT_COLOR": ("color", 4),
    "BYTE_COLOR": ("color", 4),
    "QUATERNION": ("value", 4),
}

#: O material NÃO viaja como número: o índice do slot é do objeto de origem, e é
#: justamente o que não vale no take de destino. Ele sai como NOME.
MATERIAL_ATTR = "material_index"

#: Atributos que o destino recria sozinho e que não devem ser sobrescritos.
SKIP_ATTRS = {".selection"}


def _read_attribute(attr):
    """Todos os valores de um atributo, achatados. (valores, campo, largura)."""
    campo, largura = FOREACH.get(attr.data_type, (None, 0))
    if campo is None:
        return None, "", 0
    valores = [0.0] * (len(attr.data) * largura)
    attr.data.foreach_get(campo, valores)
    return valores, campo, largura


def effective_frame(layer, number: int):
    """O keyframe que está NA TELA neste frame (contando o hold), ou None."""
    candidatos = [f for f in layer.frames if f.frame_number <= number]
    if not candidatos:
        return None
    return max(candidatos, key=lambda f: f.frame_number)


def _material_name(ob, index: int) -> str:
    if 0 <= index < len(ob.data.materials):
        material = ob.data.materials[index]
        if material is not None:
            return material.name
    return ""


# ---------------------------------------------------------------------------
# Copiar
# ---------------------------------------------------------------------------

def copy_drawing(ob, frame_number: int, only_selected: bool = True) -> dict:
    """Anota o quadro atual do objeto GP. Devolve o que foi copiado.

    Com traço selecionado, copia a seleção — é o gesto de edição de sempre. Sem
    seleção nenhuma, copia o QUADRO INTEIRO: levar o desenho de um plano para o
    seguinte é o motivo de existir deste módulo, e obrigar a selecionar tudo
    antes seria um passo a mais em toda vez.

    O que viaja são os ATRIBUTOS do desenho, lidos em bloco: assim a cópia leva
    junto tudo que existir no traço (espessura, opacidade, giro, cor de vértice
    e o que um build futuro acrescentar) sem uma lista de campos escrita à mão,
    que envelheceria calada.
    """
    camadas = []
    materiais = {}
    total = 0

    for layer in ob.data.layers:
        if layer.hide:
            continue
        frame = effective_frame(layer, frame_number)
        if frame is None:
            continue
        dados = _dump_layer(ob, frame.drawing, only_selected)
        if dados is None:
            continue
        dados["name"] = layer.name
        dados["group"] = layer.parent_group.name if layer.parent_group else ""
        camadas.append(dados)
        total += len(dados["sizes"])
        for nome in dados["materials"]:
            if nome and nome not in materiais:
                materiais[nome] = _material_settings(nome)

    return {"layers": camadas, "materials": materiais, "strokes": total}


def _dump_layer(ob, drawing, only_selected: bool):
    """Os traços deste desenho, atributo por atributo. None se não há o que levar."""
    offsets = [o.value for o in drawing.curve_offsets]
    total_curvas = max(0, len(offsets) - 1)
    if not total_curvas:
        return None

    escolhidas = [i for i in range(total_curvas)
                  if not only_selected or drawing.strokes[i].select]
    if not escolhidas:
        return None

    sizes = [offsets[i + 1] - offsets[i] for i in escolhidas]
    materiais = [_material_name(ob, drawing.strokes[i].material_index)
                 for i in escolhidas]

    curva, ponto, tipos = {}, {}, {}
    for attr in drawing.attributes:
        if attr.name in SKIP_ATTRS or attr.name == MATERIAL_ATTR:
            continue
        valores, campo, largura = _read_attribute(attr)
        if valores is None:
            continue
        tipos[attr.name] = (attr.data_type, attr.domain, largura)
        if attr.domain == "CURVE":
            curva[attr.name] = [v for i in escolhidas
                                for v in valores[i * largura:(i + 1) * largura]]
        elif attr.domain == "POINT":
            ponto[attr.name] = [v for i in escolhidas
                                for v in valores[offsets[i] * largura:
                                                 offsets[i + 1] * largura]]

    return {"sizes": sizes, "materials": materiais, "curve": curva,
            "point": ponto, "types": tipos}


def _material_settings(nome: str) -> dict:
    """Ajustes do material, para recriá-lo igual se ele não existir no destino."""
    material = bpy.data.materials.get(nome)
    if material is None or material.grease_pencil is None:
        return {}
    return workspace.dump_struct(material.grease_pencil)


def has_selection(ob, frame_number: int) -> bool:
    for layer in ob.data.layers:
        frame = effective_frame(layer, frame_number)
        if frame is None:
            continue
        if any(getattr(s, "select", False) for s in frame.drawing.strokes):
            return True
    return False


# ---------------------------------------------------------------------------
# Colar
# ---------------------------------------------------------------------------

def resolve_material(ob, nome: str, ajustes: dict) -> int:
    """Índice do slot deste material no objeto, criando o mínimo possível.

    É o coração do módulo. Um take aberto já tem os materiais da biblioteca (a
    paleta do episódio entra em todo take), então o caso comum termina na
    primeira linha — sem criar nada.
    """
    if not nome:
        return 0
    for i, slot in enumerate(ob.data.materials):
        if slot is not None and slot.name == nome:
            return i

    material = bpy.data.materials.get(nome)
    if material is None:
        material = bpy.data.materials.new(nome)
    if material.grease_pencil is None:
        bpy.data.materials.create_gpencil_data(material)
    if ajustes:
        workspace.apply_struct(material.grease_pencil, ajustes)
    ob.data.materials.append(material)
    return len(ob.data.materials) - 1


def _target_layer(ob, nome: str, grupo: str):
    """A camada de destino: a de mesmo nome, ou uma nova no mesmo papel.

    Procurar pelo nome é o que faz o desenho colado cair na camada do mesmo
    personagem em vez de virar uma camada nova a cada colagem — o irmão, no
    mundo das camadas, do material duplicado.
    """
    existente = ob.data.layers.get(nome)
    if existente is not None:
        return existente

    layer = ob.data.layers.new(nome)
    gp.flatten_layer(layer)
    if grupo:
        grupo_real = gp._ensure_group(ob.data, grupo)
        ob.data.layers.move_to_layer_group(layer, grupo_real)
    return layer


def paste_drawing(ob, frame_number: int, dados: dict) -> int:
    """Cola o quadro anotado no frame atual. Devolve quantos traços entraram."""
    colados = 0
    ajustes = dados.get("materials") or {}
    for camada in dados.get("layers") or []:
        layer = _target_layer(ob, camada.get("name", ""), camada.get("group", ""))
        frame = gp.frame_at(layer, frame_number)
        if frame is None:
            # Sem keyframe aqui a colagem não teria onde pousar. Criar um não
            # inventa desenho no take: `drawing_frames` conta NÚMEROS de frame,
            # e este quadro já é um deles.
            frame = layer.frames.new(frame_number)

        drawing = frame.drawing
        sizes = camada.get("sizes") or []
        if not sizes:
            continue
        primeira = len(drawing.strokes)
        primeiro_ponto = sum(len(s.points) for s in drawing.strokes)
        drawing.add_strokes(sizes)

        _apply_attributes(drawing, camada, primeira, primeiro_ponto)

        # O material é o único que não vem copiado como número: o índice do slot
        # é do objeto de ORIGEM. Resolvido pelo nome, um por traço.
        for i, nome in enumerate(camada.get("materials") or []):
            drawing.strokes[primeira + i].material_index = resolve_material(
                ob, nome, ajustes.get(nome, {}))

        colados += len(sizes)
        drawing.tag_positions_changed()
    return colados


def _apply_attributes(drawing, camada, primeira_curva: int, primeiro_ponto: int):
    """Escreve os atributos copiados nas curvas recém-criadas.

    Uma leitura e uma escrita por atributo, em bloco: o desenho já está no
    destino, o que falta é preencher as faixas novas sem tocar no que já estava
    desenhado ali.
    """
    tipos = camada.get("types") or {}
    for domínio, guardado in (("CURVE", camada.get("curve") or {}),
                              ("POINT", camada.get("point") or {})):
        for nome, valores in guardado.items():
            tipo = tipos.get(nome)
            if not tipo:
                continue
            data_type, dom, largura = tipo
            if dom != domínio or not largura:
                continue
            attr = drawing.attributes.get(nome)
            if attr is None:
                try:
                    attr = drawing.attributes.new(nome, data_type, domínio)
                except (RuntimeError, TypeError):
                    continue  # atributo que este build não sabe criar
            campo, _largura = FOREACH.get(attr.data_type, ("", 0))
            if not campo:
                continue
            atual = [0.0] * (len(attr.data) * largura)
            attr.data.foreach_get(campo, atual)
            início = (primeira_curva if domínio == "CURVE" else primeiro_ponto) * largura
            fim = início + len(valores)
            if fim > len(atual):
                continue  # tamanho inesperado: melhor não escrever fora da faixa
            atual[início:fim] = valores
            attr.data.foreach_set(campo, atual)


# ---------------------------------------------------------------------------
# Operadores
# ---------------------------------------------------------------------------

def _gp_object(context):
    ob = context.object
    if ob is not None and ob.type in {"GREASEPENCIL", "GPENCIL"}:
        return ob
    return None


class NSB_OT_copy_drawing(Operator):
    """Copia o desenho deste quadro (ou só o que está selecionado)"""

    bl_idname = "nsb.copy_drawing"
    bl_label = "Copy drawing"
    bl_options = {"REGISTER", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        return _gp_object(context) is not None

    def execute(self, context):
        global _BUFFER

        ob = _gp_object(context)
        frame = context.scene.frame_current
        dados = copy_drawing(ob, frame, only_selected=has_selection(ob, frame))
        if not dados["strokes"]:
            self.report({"WARNING"}, _("nothing to copy in this frame"))
            return {"CANCELLED"}
        _BUFFER = dados
        self.report({"INFO"}, _("drawing copied") + f": {dados['strokes']}")
        return {"FINISHED"}


class NSB_OT_paste_drawing(Operator):
    """Cola o desenho copiado neste quadro, reaproveitando os materiais do take"""

    bl_idname = "nsb.paste_drawing"
    bl_label = "Paste drawing"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _gp_object(context) is not None and _BUFFER is not None

    def execute(self, context):
        ob = _gp_object(context)
        antes = len(ob.data.materials)
        colados = paste_drawing(ob, context.scene.frame_current, _BUFFER)
        novos = len(ob.data.materials) - antes
        if novos:
            # Material que este take não tinha entra com o nome e a cor de
            # origem — o que NÃO acontece deve ser um "Material.001" cinza.
            self.report({"INFO"}, _("drawing pasted") + f": {colados} "
                        + f"(+{novos} " + _("materials") + ")")
        else:
            self.report({"INFO"}, _("drawing pasted") + f": {colados}")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Atalhos
#
# Ctrl+C/Ctrl+V no Grease Pencil é o gesto que o artista já tem no dedo, e o
# pedido é justamente que ELE deixe de criar material novo. O keymap do add-on
# vence o padrão, então o nativo continua lá embaixo, intacto, para o dia em que
# estes operadores forem desativados.
# ---------------------------------------------------------------------------

KEYMAPS = ("Grease Pencil Edit Mode", "Grease Pencil Paint Mode")
_KEYS = []


def _register_keymaps():
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:  # headless: não há configuração de teclado
        return
    for nome in KEYMAPS:
        km = kc.keymaps.new(name=nome, space_type="EMPTY")
        for idname, tecla in (("nsb.copy_drawing", "C"), ("nsb.paste_drawing", "V")):
            kmi = km.keymap_items.new(idname, tecla, "PRESS", ctrl=True)
            _KEYS.append((km, kmi))


def _unregister_keymaps():
    for km, kmi in _KEYS:
        try:
            km.keymap_items.remove(kmi)
        except (RuntimeError, ReferenceError):
            pass
    _KEYS.clear()


CLASSES = (NSB_OT_copy_drawing, NSB_OT_paste_drawing)


def register():
    apply_context(CLASSES)
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    _register_keymaps()


def unregister():
    _unregister_keymaps()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
