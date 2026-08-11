"""Canvas do take em Grease Pencil.

Um take = um objeto GP (`SB_<código>`) com três papéis de camada:

    BG          fundo, **sempre em escala de cinza** (RN02)
    PERSONAGENS uma camada por personagem, com a cor hex do lineart (RF-D04)
    PROPS       objetos de cena

O papel de uma camada é o GRUPO em que ela está: camadas do GP v3 não aceitam
custom properties, e o grupo tem a vantagem de ser visível para o artista e de
sobreviver a renomear a camada. O vínculo com o personagem vem do material da
camada, cuja cor é o hex declarado — ou seja, a mesma chave que o PRD define.

Os DESENHOS do take são os keyframes do GP — a arte é a verdade, o JSON é só
índice. `sync_drawings_from_gp` reconcilia os dois numa direção só: GP → modelo,
preservando as exposições manuais já ajustadas.
"""

from __future__ import annotations

import math
from typing import List, Optional

import bpy

from .core import normalize_hex
from .core.model import Drawing

#: Mapa camada -> id do personagem, guardado no OBJETO (que aceita ID props).
#: É atalho de leitura: a verdade continua sendo a cor do material da camada.
CHARACTER_MAP_KEY = "nsb_layer_characters"
TAKE_KEY = "nsb_take"

ROLE_BG = "bg"
ROLE_CHARACTER = "character"
ROLE_PROPS = "props"

GROUP_BG = "BG"
GROUP_CHARACTERS = "PERSONAGENS"
GROUP_PROPS = "PROPS"

#: Modo de desenho do GP v3 (o antigo `PAINT_GPENCIL` não existe mais).
DRAW_MODE = "PAINT_GREASE_PENCIL"
DRAW_MODE_RETRY = 0.1
DRAW_MODE_TRIES = 10

#: Nomes das camadas de papel único. Propositalmente diferentes dos grupos:
#: grupo e camada compartilham namespace, e o nome repetido viraria "BG.001".
LAYER_BG = "Fundo"
LAYER_PROPS = "Objetos"

#: Grupo de camadas -> papel.
ROLE_BY_GROUP = {
    GROUP_BG: ROLE_BG,
    GROUP_CHARACTERS: ROLE_CHARACTER,
    GROUP_PROPS: ROLE_PROPS,
}

#: Largura do quadro em unidades de cena. A câmera é ortográfica e enquadra
#: exatamente esta largura, então o canvas é 1:1 com o pixel do render.
FRAME_WIDTH = 10.0

#: Espaçamento padrão entre desenhos novos, em frames.
DRAWING_STEP = 12

#: Onde estacionar um keyframe enquanto os outros se movem, para nenhum destino
#: esbarrar em quem ainda não saiu do lugar.
PARKING = 1_000_000


def gp_data():
    """`bpy.data.grease_pencils` mudou de nome entre builds do fork."""
    return getattr(bpy.data, "grease_pencils_v3", None) or bpy.data.grease_pencils


def to_linear(hex_color: str):
    """Hex sRGB -> RGBA linear, que é o espaço em que o Blender guarda cor."""
    hex_color = normalize_hex(hex_color)
    out = []
    for i in (1, 3, 5):
        c = int(hex_color[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return (*out, 1.0)


def luminance(rgb) -> float:
    r, g, b = rgb[:3]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# ---------------------------------------------------------------------------
# Cena do take
# ---------------------------------------------------------------------------

def ensure_world(scene) -> None:
    """Fundo branco no render.

    Sem isto o world nasce preto e o board sai como uma tela preta — o BG do
    storyboard é desenhado em cinza sobre branco, não sobre vazio.
    """
    world = scene.world
    if world is None:
        world = bpy.data.worlds.get("SB_World") or bpy.data.worlds.new("SB_World")
        scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs[0].default_value = (1.0, 1.0, 1.0, 1.0)
        background.inputs[1].default_value = 1.0


def flatten_layer(layer) -> None:
    """Desliga a iluminação da camada: board é arte plana.

    Camada GP criada por código vem com `use_lights` ligado, e numa cena sem
    lâmpada isso renderiza preto — o traço some.
    """
    if hasattr(layer, "use_lights"):
        layer.use_lights = False


def neutralize_color_management(scene) -> None:
    """Sem view transform: o PNG sai com as cores exatamente como desenhadas.

    Com AgX (o padrão) o branco vira cinza claro e a cor hex do lineart chega
    distorcida ao arquivo — justamente a cor que o pipeline usa como chave.
    """
    view = scene.view_settings
    try:
        view.view_transform = "Standard"
    except TypeError:  # build sem 'Standard' — improvável, mas não vale travar
        pass
    view.look = "None"
    view.exposure = 0.0
    view.gamma = 1.0


def setup_scene(scene, project) -> None:
    """Aplica resolução e fps do projeto e garante a câmera do board."""
    s = project.settings
    ensure_world(scene)
    neutralize_color_management(scene)
    scene.render.resolution_x = s.width
    scene.render.resolution_y = s.height
    scene.render.resolution_percentage = 100
    scene.render.fps = s.fps
    scene.render.film_transparent = False

    cam = scene.camera
    if cam is None or cam.type != "CAMERA":
        cam = bpy.data.objects.get("SB_Camera")
        if cam is None:
            cam_data = bpy.data.cameras.new("SB_Camera")
            cam = bpy.data.objects.new("SB_Camera", cam_data)
            scene.collection.objects.link(cam)
        scene.camera = cam

    cam.data.type = "ORTHO"
    cam.data.ortho_scale = FRAME_WIDTH
    # Vista frontal: a câmera olha no sentido +Y, com o desenho no plano XZ.
    cam.location = (0.0, -10.0, 0.0)
    cam.rotation_euler = (math.pi / 2, 0.0, 0.0)


def _material(name: str, color, is_fill: bool = False):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    if mat.grease_pencil is None:
        bpy.data.materials.create_gpencil_data(mat)
    gpm = mat.grease_pencil
    gpm.show_stroke = True
    gpm.color = color
    gpm.show_fill = is_fill
    if is_fill:
        gpm.fill_color = color
    return mat


def _ensure_material(data, name: str, color, is_fill: bool = False) -> int:
    """Garante o material no slot do objeto e devolve o índice."""
    mat = _material(name, color, is_fill)
    for i, slot in enumerate(data.materials):
        if slot is not None and slot.name == mat.name:
            return i
    data.materials.append(mat)
    return len(data.materials) - 1


#: Papel do grupo -> nome REAL dele neste datablock, quando o nome pedido já
#: estava tomado. Vai no datablock porque camada GP não aceita custom property.
GROUPS_KEY = "nsb_groups"


def _group_registry(data) -> dict:
    stored = data.get(GROUPS_KEY)
    if stored is None:
        return {}
    return stored.to_dict() if hasattr(stored, "to_dict") else dict(stored)


def _ensure_group(data, name: str):
    """Grupo do papel, aceitando que o nome real tenha ganhado sufixo.

    Grupo e camada dividem namespace. Numa arte vinda de outro fluxo — onde uma
    CAMADA chamada "BG" é comum — o grupo nasce como "BG.001", e procurar por
    "BG" na abertura seguinte criava "BG.002", depois "BG.003"... um grupo novo
    e uma camada "Fundo.NNN" a cada vez que o take era aberto. Guardamos o nome
    que de fato saiu.
    """
    registry = _group_registry(data)
    group = data.layer_groups.get(registry.get(name, ""))
    if group is None:
        group = data.layer_groups.get(name)
    if group is None:
        group = data.layer_groups.new(name)
    if group.name != name:
        registry[name] = group.name
        data[GROUPS_KEY] = registry
    return group


def layers_in_group(data, group):
    return [l for l in data.layers if l.parent_group == group]


def _layer_has_any_art(layer) -> bool:
    return any(len(f.drawing.strokes) > 0 for f in layer.frames)


def _drop_duplicate_groups(data) -> int:
    """Limpa os grupos de papel que sobraram de aberturas anteriores.

    Rastro do bug do namespace: cada abertura criava "BG.002", "BG.003"… com uma
    camada de papel vazia dentro. Só sai o que está VAZIO e tem nome de papel com
    sufixo numérico — grupo do artista e qualquer coisa com desenho ficam.
    """
    guardados = set(_group_registry(data).values())
    removidos = 0
    for group in list(data.layer_groups):
        base, _, sufixo = group.name.rpartition(".")
        if (base not in (GROUP_BG, GROUP_CHARACTERS, GROUP_PROPS)
                or not sufixo.isdigit() or group.name in guardados):
            continue
        camadas = layers_in_group(data, group)
        if any(_layer_has_any_art(layer) for layer in camadas):
            continue
        for layer in camadas:
            data.layers.remove(layer)
        data.layer_groups.remove(group)
        removidos += 1
    return removidos


def _ensure_layer(data, name: str, group_name: str, unique_in_group: bool = True):
    """Cria a camada dentro do grupo do papel dela (o grupo É o papel).

    A busca é pelo GRUPO, nunca pelo nome: grupo e camada dividem o mesmo
    namespace no GP v3, então uma camada chamada "BG" ao lado de um grupo "BG"
    vira "BG.001" — e procurar por nome criaria uma camada nova a cada abertura
    do take. Os papéis de camada única (BG, PROPS) reaproveitam a que existir.
    """
    group = _ensure_group(data, group_name)
    if unique_in_group:
        existing = layers_in_group(data, group)
        if existing:
            return existing[0]
    else:
        for layer in layers_in_group(data, group):
            if layer.name == name:
                return layer

    layer = data.layers.new(name)
    data.layers.move_to_layer_group(layer, group)
    flatten_layer(layer)
    return layer


def find_take_object(take, adopt: bool = False):
    """Acha o objeto GP do take no arquivo aberto, pelo id gravado nele.

    `adopt` atende ao take que veio do DISCO sem índice: o `.nuc` carrega o id
    de quem o gravou, e o take recriado nasceu com outro — o desenho está ali,
    inteiro, e mesmo assim o arquivo "não tem canvas". Havendo um ÚNICO objeto
    GP no arquivo, ele é o desenho daquele take, e casar os dois é o que impede
    o add-on de criar um objeto vazio por cima e chamar o traço do artista de
    "objeto de outro take" — com o botão de descartar do lado.

    Dois ou mais objetos é o resto de takes que dividiram o mesmo arquivo: qual
    deles é o certo ninguém sabe, e adivinhar apagaria o outro. Aí não se adota.
    """
    for ob in bpy.data.objects:
        if ob.type in {"GREASEPENCIL", "GPENCIL"} and ob.get(TAKE_KEY) == take.id:
            return ob
    if not adopt:
        return None

    desenhos = [ob for ob in bpy.data.objects if ob.type in {"GREASEPENCIL", "GPENCIL"}]
    if len(desenhos) != 1:
        return None
    ob = desenhos[0]
    ob[TAKE_KEY] = take.id
    return ob


def foreign_take_objects(take):
    """Objetos GP do arquivo aberto que pertencem a OUTRO take.

    Cada `.nuc` é de um take só. Um objeto marcado com outro id ali dentro é
    resto de dois takes que dividiram o mesmo arquivo (bug do índice, já
    corrigido em `storage._free_take_file`) — e continua aparecendo na cena,
    desenhado por cima do take certo.
    """
    return [ob for ob in bpy.data.objects
            if ob.type in {"GREASEPENCIL", "GPENCIL"}
            and ob.get(TAKE_KEY) not in (None, take.id)]


def has_art(ob) -> bool:
    """Se o objeto tem algum traço — o que decide se dá para descartá-lo."""
    for layer in ob.data.layers:
        for frame in layer.frames:
            if len(frame.drawing.strokes) > 0:
                return True
    return False


def ensure_take_object(scene, project, take, library=None):
    """Cria (ou acha) o objeto GP do take, já com BG, PROPS e a câmera prontos.

    Com a `library` em mãos, as cores dos personagens cadastrados entram como
    material aqui — em TODO take, tenha ele camada de personagem ou não. Cada
    take é um arquivo próprio, então antes as cores só existiam onde alguém
    tinha criado a camada: o artista abria o take seguinte e a paleta do
    episódio não estava mais lá.
    """
    setup_scene(scene, project)

    ob = find_take_object(take, adopt=True)
    if ob is None:
        name = f"SB_{take.code or take.name or take.id}"
        data = gp_data().new(name)
        ob = bpy.data.objects.new(name, data)
        scene.collection.objects.link(ob)
        ob[TAKE_KEY] = take.id

    data = ob.data
    _drop_duplicate_groups(data)
    for name in (GROUP_BG, GROUP_CHARACTERS, GROUP_PROPS):
        _ensure_group(data, name)

    _ensure_material(data, "SB_BG", (0.5, 0.5, 0.5, 1.0), is_fill=True)
    _ensure_material(data, "SB_PROPS", (0.05, 0.05, 0.05, 1.0))

    _ensure_layer(data, LAYER_BG, GROUP_BG)
    _ensure_layer(data, LAYER_PROPS, GROUP_PROPS)
    ensure_library_materials(ob, library)

    # Vale também para camadas criadas à mão pelo artista.
    for layer in data.layers:
        flatten_layer(layer)
    return ob


def character_material_name(character) -> str:
    return f"SB_LN_{character.name}"


def ensure_library_materials(ob, library) -> int:
    """Põe (e atualiza) no take um material por personagem da biblioteca.

    Chamada ao abrir o take e sempre que a cor de alguém muda, então o material
    de cada personagem é a cor declarada AGORA — não a de quando a camada foi
    criada. Devolve quantos materiais a biblioteca cobre.

    Materiais anexados ao datablock têm dono e sobrevivem ao salvar; é isso que
    faz a paleta continuar no `.nuc` depois de fechado.
    """
    if library is None:
        return 0
    total = 0
    for character in library.characters:
        try:
            color = to_linear(character.hex_color)
        except ValueError:
            continue  # hex torto no JSON: a validação reclama, aqui só pulamos
        _ensure_material(ob.data, character_material_name(character), color)
        total += 1
    return total


def use_character_material(ob, character) -> int:
    """Deixa a cor deste personagem pronta para desenhar. Devolve o slot.

    É o "puxar da biblioteca": garante o material no take e o torna o slot ativo
    do objeto — o pincel passa a sair na cor do personagem sem o artista ter de
    caçar o material na aba de propriedades.
    """
    index = _ensure_material(ob.data, character_material_name(character),
                             to_linear(character.hex_color))
    ob.active_material_index = index  # o slot ativo é do OBJETO, não do datablock
    return index


def active_gp_brush(context):
    """Pincel de desenho ativo, ou None (fora do modo de pintura, headless…)."""
    settings = getattr(context, "tool_settings", None)
    paint = getattr(settings, "gpencil_paint", None) if settings else None
    return getattr(paint, "brush", None) if paint else None


def aim_brush_at_material(context, hex_color: str) -> bool:
    """Faz o pincel obedecer ao MATERIAL — e o deixa na cor certa.

    Trocar o material ativo não bastava, e isso não dava nenhum sinal na tela: o
    pincel do Nuclear vem com cor de vértice em cima (`vertex_color_factor` 1),
    e cor de vértice VENCE a do material. O artista escolhia o personagem e
    continuava desenhando no verde do pincel.

    Zeramos o fator (a cor passa a vir do material, que é onde o pipeline lê a
    cor do personagem) e ainda assim pintamos o pincel da mesma cor: é o que o
    artista vê no cabeçalho da ferramenta, e o que sai se ele reativar a cor de
    vértice na mão.
    """
    from .core import rgb_from_hex

    brush = active_gp_brush(context)
    if brush is None:
        return False
    cor = rgb_from_hex(hex_color)
    if hasattr(brush, "color"):
        brush.color = cor
    settings = getattr(brush, "gpencil_settings", None)
    if settings is not None and hasattr(settings, "vertex_color_factor"):
        settings.vertex_color_factor = 0.0
    return True


def draw_as_character(context, ob, character):
    """Tudo que "vou desenhar este personagem agora" significa.

    Um clique no nome dele na biblioteca: a camada de lineart dele fica ativa
    (criada na hora se ainda não existir), o material dele vira o slot ativo e o
    pincel passa a sair na cor declarada.
    """
    layer = ensure_character_layer(ob, character)
    aim_brush_at_material(context, character.hex_color)
    return layer


def _enter_draw_mode(ob) -> bool:
    if ob.mode == DRAW_MODE:
        return True
    try:
        bpy.ops.object.mode_set(mode=DRAW_MODE)
    except RuntimeError:
        return False
    return ob.mode == DRAW_MODE


def make_ready_to_draw(ob) -> bool:
    """Deixa o objeto do take ativo, selecionado e em modo de desenho.

    Sem isso o artista clica em "Open take" e cai em Object Mode sem nada
    selecionado — teria que achar o objeto e trocar de modo na mão.

    Devolve se o modo entrou NA HORA. Logo depois de `wm.open_mainfile` o
    contexto ainda recusa a troca de modo (mas aceita um tick depois), então
    nesse caso fica um timer de tiro único terminando o serviço. Em background
    não existe modo de pintura e o timer nem roda — a seleção, que é o que os
    testes headless conseguem cobrar, já foi feita.
    """
    view_layer = bpy.context.view_layer
    if view_layer is None:
        return False

    for other in view_layer.objects:
        other.select_set(False)
    ob.select_set(True)
    view_layer.objects.active = ob

    if bpy.app.background:
        return False
    if _enter_draw_mode(ob):
        return True

    name = ob.name
    tries = [0]

    def _retry_draw_mode():
        tries[0] += 1
        again = bpy.data.objects.get(name)
        # O arquivo pode ter trocado de novo entre o registro e o disparo.
        if again is None or again is not bpy.context.view_layer.objects.active:
            return None
        if _enter_draw_mode(again):
            return None
        # Poucas tentativas e desiste: melhor o artista trocar o modo na mão do
        # que um timer teimando para sempre.
        return DRAW_MODE_RETRY if tries[0] < DRAW_MODE_TRIES else None

    bpy.app.timers.register(_retry_draw_mode, first_interval=0.0)
    return False


def ensure_character_layer(ob, character):
    """Camada de lineart de um personagem, com a cor hex dele no material.

    A cor é METADADO declarado: vem do cadastro na biblioteca, nunca de leitura
    de pixel. O material recebe o mesmo hex para o artista ver na tela a cor que
    o pipeline vai usar como chave.
    """
    data = ob.data
    color = to_linear(character.hex_color)
    use_character_material(ob, character)

    layer = _ensure_layer(data, f"LN_{character.name}", GROUP_CHARACTERS,
                          unique_in_group=False)
    layer.channel_color = color[:3]

    mapping = dict(ob.get(CHARACTER_MAP_KEY, {}))
    mapping[layer.name] = character.id
    ob[CHARACTER_MAP_KEY] = mapping

    data.layers.active = layer
    return layer


def layer_role(layer) -> str:
    """Papel da camada = grupo em que ela está. Camada solta não tem papel."""
    group = layer.parent_group
    if group is None:
        return ""
    return ROLE_BY_GROUP.get(group.name, "")


def character_layers(ob):
    return [l for l in ob.data.layers if layer_role(l) == ROLE_CHARACTER]


def character_of_layer(ob, layer, library):
    """Personagem de uma camada de lineart.

    Casa primeiro pelo mapa gravado no objeto e, se o artista renomeou a
    camada, cai na cor do material — que é a chave definida pelo PRD.
    """
    mapping = ob.get(CHARACTER_MAP_KEY, {})
    char_id = mapping.get(layer.name)
    if char_id:
        found = next((c for c in library.characters if c.id == char_id), None)
        if found is not None:
            return found

    for material in ob.data.materials:
        if material is None or material.grease_pencil is None:
            continue
        if material.name != f"SB_LN_{layer.name[3:]}":
            continue
        for character in library.characters:
            if all(abs(a - b) < 1e-3
                   for a, b in zip(material.grease_pencil.color[:3],
                                   to_linear(character.hex_color)[:3])):
                return character
    return None


# ---------------------------------------------------------------------------
# Desenhos (keyframes)
# ---------------------------------------------------------------------------

def content_layers(ob):
    """Camadas que definem quando o quadro MUDA.

    O BG é fundo estático: um keyframe nele não conta como desenho novo do
    take. Se o objeto só tiver BG, aí ele mesmo vira o conteúdo.
    """
    layers = [l for l in ob.data.layers if layer_role(l) != ROLE_BG]
    return layers or list(ob.data.layers)


def frame_at(layer, number: int):
    """Keyframe EXATAMENTE neste frame, ou None.

    Não dá para usar `layer.frames.get(n)` (a coleção é chaveada por string) nem
    `get_frame_at` (devolve o keyframe em hold, que pode ser bem anterior).
    """
    for frame in layer.frames:
        if frame.frame_number == number:
            return frame
    return None


def drawing_frames(ob) -> List[int]:
    """Números de frame em que existe desenho, em ordem, sem repetição."""
    numbers = set()
    for layer in content_layers(ob):
        for frame in layer.frames:
            numbers.add(frame.frame_number)
    return sorted(numbers)


def next_drawing_frame(ob) -> int:
    frames = drawing_frames(ob)
    return (frames[-1] + DRAWING_STEP) if frames else 1


def add_drawing_keyframe(ob, frame_number: Optional[int] = None) -> int:
    """Cria um keyframe vazio nas camadas de conteúdo — um desenho novo.

    Nada de inbetween: o quadro anterior fica exposto em hold até este (RN05).
    """
    if frame_number is None:
        frame_number = next_drawing_frame(ob)
    for layer in content_layers(ob):
        if frame_at(layer, frame_number) is None:
            layer.frames.new(frame_number)
    return frame_number


def remove_drawing_keyframe(ob, frame_number: int) -> None:
    """Apaga o desenho deste frame em todas as camadas.

    `frames.remove` quer o NÚMERO do frame, não o objeto keyframe — passar o
    objeto levanta TypeError e o operador inteiro morre.
    """
    for layer in list(ob.data.layers):
        frame = frame_at(layer, frame_number)
        if frame is not None:
            layer.frames.remove(frame.frame_number)


def slice_drawings(ob, start: int, end: int) -> int:
    """Deixa só o trecho [start, end] da arte, rebaseado para o frame 1.

    O desenho que estava em HOLD quando o trecho começa vem junto, como primeiro
    keyframe — senão o pedaço abriria em branco até o próximo desenho.
    """
    mantidos = 0
    for layer in list(ob.data.layers):
        números = sorted(f.frame_number for f in layer.frames)
        dentro = [n for n in números if start <= n <= end]
        anteriores = [n for n in números if n < start]
        hold = anteriores[-1] if anteriores and start not in dentro else None

        destino = {}
        if hold is not None:
            destino[hold] = 1
        for n in dentro:
            destino[n] = n - start + 1

        for n in números:
            if n not in destino:
                layer.frames.remove(n)
        # Estacionar antes de pousar: o destino de um pode ser a origem de outro.
        for n in sorted(destino, reverse=True):
            layer.frames.move(n, n + PARKING)
        for n in sorted(destino):
            layer.frames.move(n + PARKING, destino[n])
        mantidos += len(destino)
    return mantidos


def action_fcurves(obj):
    """As curvas do objeto, com ou sem action em slots (Blender 5.0)."""
    ad = obj.animation_data
    if not ad or not ad.action:
        return []
    action = ad.action
    if hasattr(action, "fcurves"):
        return list(action.fcurves)
    return [fc for layer in getattr(action, "layers", [])
            for strip in getattr(layer, "strips", [])
            for bag in getattr(strip, "channelbags", [])
            for fc in bag.fcurves]


def rebase_animation(scene, start: int) -> int:
    """Leva a animação da cena junto com a arte para o frame 1.

    Material vindo de fora costuma ter a CÂMERA animada — o artista desenha os
    planos em pontos diferentes do canvas e ela passeia entre eles. Rebasear só
    os desenhos filmaria o trecho da pose errada: quadro vazio, desenho fora de
    campo.
    """
    deslocamento = start - 1
    if deslocamento <= 0:
        return 0
    mexidas = 0
    for obj in scene.objects:
        for fc in action_fcurves(obj):
            for key in fc.keyframe_points:
                key.co_ui[0] -= deslocamento   # co_ui arrasta os handles junto
            fc.update()
            mexidas += 1
    return mexidas


def sync_drawings_from_gp(take, ob) -> int:
    """Reescreve `take.drawings` a partir dos keyframes do GP.

    Preserva a exposição manual de cada desenho que já existia (casada pelo
    número do frame), porque timing é metadado e não pode ser perdido quando o
    artista mexe na arte (RF-T02).
    """
    previous = {d.frame: d for d in take.drawings}
    drawings = []
    for i, number in enumerate(drawing_frames(ob), start=1):
        old = previous.get(number)
        if old is not None:
            old.name = old.name or f"D{i:03d}"
            drawings.append(old)
        else:
            drawings.append(Drawing(name=f"D{i:03d}", frame=number))
    take.drawings = drawings
    return len(drawings)


# ---------------------------------------------------------------------------
# RF-09 — mandar um desenho para a biblioteca como prop
# ---------------------------------------------------------------------------

def props_layers(ob):
    return [l for l in ob.data.layers if layer_role(l) == ROLE_PROPS]


def layer_has_art(layer, frame_number: int) -> bool:
    """Existe traço nesta camada no frame (contando o hold do keyframe anterior)?"""
    candidates = [f for f in layer.frames if f.frame_number <= frame_number]
    if not candidates:
        return False
    frame = max(candidates, key=lambda f: f.frame_number)
    return len(frame.drawing.strokes) > 0


def prop_reference_source(ob, frame_number: int):
    """De onde tirar a arte de um prop novo, sem pedir nada ao artista.

    Ele já está desenhando — a imagem do objeto existe na tela, e obrigá-lo a
    produzir um PNG à parte era o que tornava cadastrar prop um trabalho. Em
    ordem de precisão: a camada em que ele está desenhando, o grupo de objetos
    inteiro, e por fim o quadro do plano (que mostra o prop no contexto, e é
    referência legítima para quem vai criar a arte).

    Devolve `(modo, camadas)` com modo em ACTIVE / PROPS / FRAME / NONE.
    """
    ativa = ob.data.layers.active
    if (ativa is not None and layer_role(ativa) == ROLE_PROPS
            and layer_has_art(ativa, frame_number)):
        return "ACTIVE", [ativa]

    do_grupo = [l for l in props_layers(ob) if layer_has_art(l, frame_number)]
    if do_grupo:
        return "PROPS", do_grupo

    com_arte = [l for l in ob.data.layers if layer_has_art(l, frame_number)]
    if com_arte:
        return "FRAME", list(ob.data.layers)
    return "NONE", []


def render_frame_png(scene, ob, destination) -> "Path":
    """O quadro inteiro do plano neste frame, com fundo — não recortado."""
    return render_layers_png(scene, ob, list(ob.data.layers), destination,
                             transparent=False)


def render_layers_png(scene, ob, layers, destination, transparent: bool = True) -> "Path":
    """Renderiza só estas camadas para um PNG (por padrão, com fundo transparente).

    É o mesmo pipeline do render dos desenhos (EEVEE, câmera do board), então o
    PNG sai do tamanho do quadro e com o prop na posição em que foi desenhado —
    quem reutilizar o prop reaproveita também o enquadramento.

    Tudo que é mexido (visibilidade, alpha, formato) volta ao lugar no fim.
    """
    from pathlib import Path

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    wanted = {l.name for l in layers}

    render = scene.render
    images = render.image_settings
    saved = {
        "filepath": render.filepath,
        "format": images.file_format,
        "color_mode": images.color_mode,
        "transparent": render.film_transparent,
        "hidden": {l.name: l.hide for l in ob.data.layers},
        "objects": {o.name: o.hide_render for o in scene.objects},
    }
    try:
        for other in scene.objects:
            if other.type == "CAMERA":
                continue
            other.hide_render = other is not ob
        for layer in ob.data.layers:
            layer.hide = layer.name not in wanted

        images.file_format = "PNG"
        images.color_mode = "RGBA" if transparent else "RGB"
        render.film_transparent = transparent
        render.filepath = str(destination.with_suffix(""))
        bpy.ops.render.render(write_still=True)
    finally:
        render.filepath = saved["filepath"]
        images.file_format = saved["format"]
        images.color_mode = saved["color_mode"]
        render.film_transparent = saved["transparent"]
        for layer in ob.data.layers:
            if layer.name in saved["hidden"]:
                layer.hide = saved["hidden"][layer.name]
        for other in scene.objects:
            if other.name in saved["objects"]:
                other.hide_render = saved["objects"][other.name]

    if not destination.is_file():
        raise RuntimeError(f"o render não gerou {destination.name}")
    return destination


# ---------------------------------------------------------------------------
# Props da biblioteca de volta ao canvas
#
# O caminho de ida já existia (o desenho vira PNG na pasta `props/`); faltava o
# de volta. O prop entra como um plano com a arte, e não como Empty de imagem:
# Empty aparece na viewport e SOME no render — o prop desapareceria justamente
# no animatic. O plano é objeto normal do arquivo, então fica gravado no `.nuc`
# do take e volta sozinho na próxima abertura.
# ---------------------------------------------------------------------------

#: Id do prop da biblioteca que este objeto representa.
PROP_KEY = "nsb_prop"

#: Quanto o plano do prop fica ATRÁS do desenho (a câmera olha no sentido +Y).
#: Sem folga, plano e traço disputam o mesmo plano e o quadro pisca.
PROP_DEPTH = 0.1

#: Largura do prop quando a arte não tem a proporção do quadro (foto, print):
#: uma fração do quadro, para o artista arrastar até o lugar.
PROP_LOOSE_WIDTH = FRAME_WIDTH / 3.0


def find_prop_object(prop):
    for ob in bpy.data.objects:
        if ob.get(PROP_KEY) == prop.id:
            return ob
    return None


def prop_objects():
    """Todos os props da biblioteca colocados neste arquivo."""
    return [ob for ob in bpy.data.objects if ob.get(PROP_KEY)]


def _prop_material(name: str, image):
    """Material chapado com a arte do prop: emissão pura, recortada pelo alpha.

    Emission em vez de Principled porque o board é arte plana — com o view
    transform já neutralizado, o pixel do PNG chega ao render igual ao que o
    artista desenhou. O alpha entra como mistura com um shader transparente, que
    é o que o EEVEE recorta de verdade.
    """
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new("ShaderNodeOutputMaterial")
    mix = nodes.new("ShaderNodeMixShader")
    emit = nodes.new("ShaderNodeEmission")
    clear = nodes.new("ShaderNodeBsdfTransparent")
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = image
    tex.extension = "CLIP"

    for node, (x, y) in ((tex, (-500, 0)), (emit, (-200, -100)),
                         (clear, (-200, 120)), (mix, (0, 0)), (out, (200, 0))):
        node.location = (x, y)

    links.new(tex.outputs["Color"], emit.inputs["Color"])
    links.new(tex.outputs["Alpha"], mix.inputs["Fac"])
    links.new(clear.outputs["BSDF"], mix.inputs[1])
    links.new(emit.outputs["Emission"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])

    # O nome mudou no EEVEE Next (4.2+); o fork pode trazer os dois.
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"
    if hasattr(mat, "blend_method"):
        mat.blend_method = "BLEND"
    return mat


def _prop_plane_size(scene, image):
    """Tamanho do plano em unidades de cena, a partir da arte.

    Arte com a proporção do quadro veio do próprio board (RF-09 renderiza o
    quadro inteiro): ela volta do tamanho do quadro e o prop reaparece
    exatamente onde foi desenhado. Qualquer outra proporção é referência solta —
    entra menor, no meio, para ser posicionada.
    """
    width, height = (image.size[0], image.size[1]) if image.size else (0, 0)
    frame_ratio = scene.render.resolution_x / max(1, scene.render.resolution_y)
    if not width or not height:
        return FRAME_WIDTH, FRAME_WIDTH / frame_ratio
    ratio = width / height
    if abs(ratio - frame_ratio) < 0.01:
        return FRAME_WIDTH, FRAME_WIDTH / frame_ratio
    return PROP_LOOSE_WIDTH, PROP_LOOSE_WIDTH / ratio


def _image_plane_mesh(name: str, width: float, height: float):
    """Quadrilátero no plano XZ (o plano em que o board é desenhado), com UV."""
    mesh = bpy.data.meshes.new(name)
    hw, hh = width / 2.0, height / 2.0
    mesh.from_pydata([(-hw, 0.0, -hh), (hw, 0.0, -hh), (hw, 0.0, hh), (-hw, 0.0, hh)],
                     [], [(0, 1, 2, 3)])
    mesh.update()
    uvs = mesh.uv_layers.new(name="UVMap")
    for loop, coord in zip(range(4), ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))):
        uvs.data[loop].uv = coord
    return mesh


def load_prop_image(path):
    """Carrega a arte do prop, preferindo caminho relativo ao arquivo do take.

    Relativo porque o board inteiro viaja entre máquinas (e para o Dropbox do
    estúdio): com caminho absoluto, o prop some na máquina do vizinho.
    """
    image = bpy.data.images.load(str(path), check_existing=True)
    if bpy.data.filepath:
        try:
            image.filepath = bpy.path.relpath(str(path))
        except ValueError:
            pass  # arquivo em outro volume: fica o absoluto mesmo
    return image


def place_prop(scene, prop, art_path):
    """Traz a arte de um prop da biblioteca para o take, ou atualiza a que já está.

    Devolve (objeto, novo?). Chamar de novo com o mesmo prop não duplica nada:
    o objeto é achado pelo id do prop e só tem a arte trocada — é assim que
    "substituir pela versão final" chega ao take que já usava o provisório.
    """
    image = load_prop_image(art_path)
    existing = find_prop_object(prop)
    width, height = _prop_plane_size(scene, image)
    material = _prop_material(f"SB_PROP_{prop.name}", image)

    if existing is not None:
        existing.data.materials.clear()
        existing.data.materials.append(material)
        # A arte final de um prop pode ter outra proporção que a provisória; sem
        # reajustar o plano, ela chegaria esticada ao take que já a usava.
        if len(getattr(existing.data, "vertices", ())) == 4:
            hw, hh = width / 2.0, height / 2.0
            for vertex, coord in zip(existing.data.vertices,
                                     ((-hw, 0.0, -hh), (hw, 0.0, -hh),
                                      (hw, 0.0, hh), (-hw, 0.0, hh))):
                vertex.co = coord
        if existing.name not in scene.objects:
            scene.collection.objects.link(existing)
        return existing, False

    name = f"SB_PROP_{prop.name}"
    mesh = _image_plane_mesh(name, width, height)
    mesh.materials.append(material)
    ob = bpy.data.objects.new(name, mesh)
    ob[PROP_KEY] = prop.id
    # Atrás do desenho: o prop é o objeto de cena, o traço do artista manda.
    ob.location = (0.0, PROP_DEPTH, 0.0)
    scene.collection.objects.link(ob)
    return ob, True


def remove_prop(prop) -> bool:
    """Tira do take o prop colocado. A arte continua na biblioteca."""
    ob = find_prop_object(prop)
    if ob is None:
        return False
    bpy.data.objects.remove(ob, do_unlink=True)
    return True


# ---------------------------------------------------------------------------
# RN02 — BG em escala de cinza
# ---------------------------------------------------------------------------

def desaturate(rgb):
    lum = luminance(rgb)
    return (lum, lum, lum)


def enforce_bg_grayscale(ob) -> int:
    """Converte para cinza tudo que a camada de BG usa. Devolve quantos ajustes.

    Age em dois lugares: as cores de vértice dos traços já desenhados e os
    materiais usados por eles — é onde a cor pode escapar de RN02.
    """
    fixed = 0
    bg_layers = [l for l in ob.data.layers if layer_role(l) == ROLE_BG]
    used_materials = set()

    for layer in bg_layers:
        for frame in layer.frames:
            drawing = frame.drawing
            for stroke in drawing.strokes:
                used_materials.add(stroke.material_index)
                for point in stroke.points:
                    color = point.vertex_color
                    if max(color[:3]) - min(color[:3]) > 1e-4:
                        gray = desaturate(color)
                        point.vertex_color = (*gray, color[3])
                        fixed += 1
            drawing.tag_positions_changed()

    for index in used_materials:
        if 0 <= index < len(ob.data.materials):
            mat = ob.data.materials[index]
            if mat is None or mat.grease_pencil is None:
                continue
            gpm = mat.grease_pencil
            for attr in ("color", "fill_color"):
                color = getattr(gpm, attr)
                if max(color[:3]) - min(color[:3]) > 1e-4:
                    gray = desaturate(color)
                    setattr(gpm, attr, (*gray, color[3]))
                    fixed += 1
    return fixed


def bg_violations(ob) -> List[str]:
    """Lista o que na camada de BG está fora da escala de cinza (RN02).

    Olha os dois lugares de onde a cor sai, como `enforce_bg_grayscale`: a cor
    de vértice do traço E o material com que ele foi desenhado. No GP v3 a cor
    normalmente vem do MATERIAL — checar só o vertex_color deixava passar
    justamente o caso comum, e o painel dizia "fundo limpo" com o BG vermelho.
    """
    problems = []
    used_materials = set()

    for layer in ob.data.layers:
        if layer_role(layer) != ROLE_BG:
            continue
        for frame in layer.frames:
            for stroke in frame.drawing.strokes:
                used_materials.add(stroke.material_index)
                for point in stroke.points:
                    if max(point.vertex_color[:3]) - min(point.vertex_color[:3]) > 1e-4:
                        problems.append(f"traço colorido no frame {frame.frame_number}")
                        break
                else:
                    continue
                break

    for index in sorted(used_materials):
        if not 0 <= index < len(ob.data.materials):
            continue
        mat = ob.data.materials[index]
        if mat is None or mat.grease_pencil is None:
            continue
        for attr in ("color", "fill_color"):
            color = getattr(mat.grease_pencil, attr)
            if max(color[:3]) - min(color[:3]) > 1e-4:
                problems.append(f"material colorido: {mat.name}")
                break

    return problems
