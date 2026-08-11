"""O take escrito por cima da câmera.

Trabalhando com trinta planos, saber em qual deles se está não pode depender de
olhar a sidebar — que fica fechada quando o artista quer tela. O código do take
vai no canto superior esquerdo DO QUADRO (não da janela): é onde o burning do
animatic também escreve, então o que se vê desenhando é o que vai aparecer no
vídeo.

Não entra no render: overlay é para quem desenha. O que vai para o vídeo é o
burning, que tem tela própria.

**Os desenhos como quadrados na timeline foram REMOVIDOS** (2026-08-10, decisão
do usuário): o keyframe volta a ser desenhado pelo Nuclear, do jeito nativo. O
add-on pintava blocos por cima da faixa de keyframes para ler exposição como no
Harmony; a decisão é que a forma do keyframe é assunto da timeline do Nuclear,
não de um overlay do storyboard. O código está no histórico (`git log`
`overlay.py`) se um dia voltar a fazer falta.
"""

from __future__ import annotations

import blf
import bpy

from . import state

#: Handles dos desenhos registrados (para tirá-los no unregister).
_HANDLES = []

# --- rótulo do take --------------------------------------------------------

#: Distância entre o canto do quadro e o texto, em pixels de tela.
LABEL_MARGIN = 14
LABEL_SIZE = 22
SUBLABEL_SIZE = 13
LABEL_COLOR = (0.08, 0.08, 0.09, 0.95)
SUBLABEL_COLOR = (0.25, 0.25, 0.28, 0.9)

#: Erros já contados, para uma falha de overlay não virar mil linhas no console.
_REPORTED = set()


def safe_draw(função):
    """Overlay que quebra não pode encher o console nem parar a tela.

    Um `draw_handler` roda a cada redesenho: uma exceção ali vira um traceback
    por quadro, e o artista perde o console (onde os avisos do add-on aparecem).
    O primeiro erro de cada tipo é impresso; os iguais depois dele, não.
    """
    def _envelope():
        try:
            função()
        except Exception as exc:  # noqa: BLE001 — overlay não derruba a sessão
            chave = (função.__name__, type(exc).__name__, str(exc))
            if chave not in _REPORTED:
                _REPORTED.add(chave)
                print(f"[storyboard] overlay {função.__name__}: {exc}")
    _envelope.__name__ = função.__name__
    return _envelope


def _ui_scale() -> float:
    return bpy.context.preferences.system.ui_scale or 1.0


def _current_take():
    from . import takefile

    store = state.get_store()
    if store is None:
        return None, None
    return store, takefile.current_take_of_file(store)


def enabled(context) -> bool:
    st = getattr(context.window_manager, "nsb", None)
    return bool(st and st.show_take_overlay)


# ---------------------------------------------------------------------------
# O código do take, no canto superior esquerdo do quadro
# ---------------------------------------------------------------------------

#: Espaço que o rótulo ocupa; serve para ele nunca ser empurrado para fora.
LABEL_BOX = (140, 60)

#: Altura do que o Nuclear já escreve no alto da vista ("Camera Ortográfica",
#: nome do objeto). Só entra quando o rótulo é empurrado para o canto da
#: janela — no lugar de sempre, dentro do quadro, não há com o que esbarrar.
VIEW_TEXT_CLEARANCE = 34


def safe_bounds(context):
    """(x mínimo, y máximo) livres na região, em pixels dela.

    A barra de ferramentas e o cabeçalho são regiões SOBREPOSTAS: elas cobrem a
    região de desenho em vez de encolhê-la. Escrever no canto cru da região põe
    metade do rótulo atrás da barra — foi o que a captura mostrou.
    """
    janela = context.region
    area = getattr(context, "area", None)
    esquerda, topo = 0.0, float(janela.height)
    if area is None:
        return esquerda, topo

    for outra in area.regions:
        if outra.type == "WINDOW" or outra.width <= 1 or outra.height <= 1:
            continue
        x0, y0 = outra.x - janela.x, outra.y - janela.y
        x1, y1 = x0 + outra.width, y0 + outra.height
        if x1 <= 0 or x0 >= janela.width or y1 <= 0 or y0 >= janela.height:
            continue  # não chega a cobrir a região de desenho
        if outra.type == "TOOLS" and x0 <= 0:
            esquerda = max(esquerda, float(x1))
        elif outra.type in {"HEADER", "TOOL_HEADER", "ASSET_SHELF_HEADER"} \
                and y1 >= janela.height:
            topo = min(topo, float(y0))
    return esquerda, topo


def camera_corner(context):
    """(x, y) do canto superior esquerdo do QUADRO, em pixels da região.

    Sem câmera na tela (o artista girou a vista), devolve o canto da própria
    região: o rótulo continua onde o olho já o procura.

    O canto é preso à região no fim. Com o quadro maior que a janela — zoom
    dado, que é o normal de quem está desenhando um detalhe — o canto de cima
    fica ACIMA da tela, e o rótulo simplesmente não apareceria.
    """
    from bpy_extras.view3d_utils import location_3d_to_region_2d

    region = context.region
    rv3d = getattr(context, "region_data", None)
    x, y = LABEL_MARGIN, region.height - LABEL_MARGIN

    scene = context.scene
    cam = scene.camera if scene else None
    if (rv3d is not None and rv3d.view_perspective == "CAMERA"
            and cam is not None and cam.type == "CAMERA"):
        pontos = []
        for vertice in cam.data.view_frame(scene=scene):
            na_tela = location_3d_to_region_2d(region, rv3d, cam.matrix_world @ vertice)
            if na_tela is not None:
                pontos.append(na_tela)
        if len(pontos) >= 4:
            x = min(p.x for p in pontos) + LABEL_MARGIN
            y = max(p.y for p in pontos) - LABEL_MARGIN

    largura, altura = LABEL_BOX
    escala = _ui_scale()
    livre_x, livre_y = safe_bounds(context)
    # Empurrado para o alto da janela, o rótulo cairia em cima do que o Nuclear
    # já escreve ali ("Camera Ortográfica", nome do objeto): desce duas linhas.
    teto = livre_y - LABEL_MARGIN
    if y > teto:
        teto -= VIEW_TEXT_CLEARANCE * escala
    x = min(max(x, livre_x + LABEL_MARGIN),
            max(livre_x + LABEL_MARGIN, region.width - largura * escala))
    y = min(max(y, altura * escala), teto)
    return x, y


def _context_line(store, take) -> str:
    achado = store.project.find_take(take.id)
    if achado is None:
        return ""
    episode, scene_obj, _tk = achado
    partes = [episode.code or episode.name, scene_obj.code or scene_obj.name]
    return " · ".join(p for p in partes if p)


def draw_take_label():
    context = bpy.context
    if not enabled(context) or context.space_data.type != "VIEW_3D":
        return
    store, take = _current_take()
    if take is None:
        return

    escala = _ui_scale()
    x, topo = camera_corner(context)
    fonte = 0
    blf.enable(fonte, blf.SHADOW)
    # A sombra é o que faz o rótulo continuar legível sobre o traço preto do
    # desenho — o board é arte escura sobre branco, e texto escuro sumiria.
    blf.shadow(fonte, 3, 1.0, 1.0, 1.0, 0.9)
    blf.shadow_offset(fonte, 0, 0)

    tamanho = LABEL_SIZE * escala
    blf.size(fonte, tamanho)
    blf.color(fonte, *LABEL_COLOR)
    blf.position(fonte, x, topo - tamanho, 0)
    blf.draw(fonte, take.code or take.name)

    linha = _context_line(store, take)
    if linha:
        menor = SUBLABEL_SIZE * escala
        blf.size(fonte, menor)
        blf.color(fonte, *SUBLABEL_COLOR)
        blf.position(fonte, x, topo - tamanho - menor - 4 * escala, 0)
        blf.draw(fonte, linha)
    blf.disable(fonte, blf.SHADOW)


# ---------------------------------------------------------------------------

def register():
    if bpy.app.background:
        return  # sem janela não há o que desenhar
    espaço = bpy.types.SpaceView3D
    _HANDLES.append((espaço, espaço.draw_handler_add(
        safe_draw(draw_take_label), (), "WINDOW", "POST_PIXEL")))


def unregister():
    while _HANDLES:
        space, handle = _HANDLES.pop()
        space.draw_handler_remove(handle, "WINDOW")
