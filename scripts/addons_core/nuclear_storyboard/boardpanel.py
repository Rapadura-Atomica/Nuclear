"""A coluna de planos: o board numa aba própria do Properties do Nuclear.

O board e a bancada eram a mesma tela. Escolher o plano, desenhar, encaixar o
áudio, cadastrar personagem e exportar disputavam a mesma faixa de 280px da
sidebar — e a grade de miniaturas, que é o que o artista olha o dia inteiro,
ficava espremida entre um campo de texto e um botão de exportar.

Aqui ela sai de lá. O Nuclear ganhou a aba `storyboard` no Properties (o mesmo
caminho do Paint tab: `BCONTEXT_STORYBOARD`), e uma aba do Properties ocupa a
ÁREA INTEIRA de um editor — o artista encosta uma coluna estreita na lateral e
lê a cena de cima para baixo, como no Storyboard Pro. A bancada fica com o que
é trabalho: episódio e cena, biblioteca, entrega e ajustes.

Um plano por linha, e não uma grade: a sequência é lida em ordem, e duas
colunas obrigam a varrer em ziguezague. A miniatura à esquerda, a legenda à
direita — código, duração e o alerta de quem não passa na validação.

Build velho do Nuclear (ou Blender de fábrica) não tem a aba: o painel
simplesmente não aparece, e é por isso que a sidebar mantém a grade quando
`tab_available()` é falso. Sem essa peneira, atualizar o add-on antes do
Nuclear deixaria o artista sem board nenhum.
"""

from __future__ import annotations

import bpy
from bpy.types import Panel

from . import state, sync
from .translations import _

#: Nome da aba no Properties, do lado C++ (`buttons_main_region_context_string`).
CONTEXT = "storyboard"

#: Altura da miniatura no card. Maior que a da sidebar: aqui a largura é do
#: editor, e quem escolheu esta coluna quer ver o desenho.
THUMB_SCALE = 6.0

#: Quanto da largura fica com a miniatura. O resto é a legenda — que precisa de
#: espaço para "T011B" e "12,5s" sem truncar em coluna estreita.
THUMB_SPLIT = 0.55

_TAB = None


def tab_available() -> bool:
    """Este Nuclear tem a aba `Storyboard` no Properties?

    Lido uma vez: o enum é do build, não muda em execução. `enum_items_static`
    porque o `context` do Properties é filtrado em tempo real pelo que existe na
    cena — a lista viva pode não trazer a aba mesmo onde ela existe.
    """
    global _TAB
    if _TAB is None:
        try:
            prop = bpy.types.SpaceProperties.bl_rna.properties["context"]
            itens = getattr(prop, "enum_items_static", None) or prop.enum_items
            _TAB = any(item.identifier == "STORYBOARD" for item in itens)
        except (KeyError, AttributeError):
            _TAB = False
    return _TAB


class NSB_PT_board(Panel):
    """Os planos da cena, um por linha — clicar entra no take."""

    bl_idname = "NSB_PT_board"
    bl_label = "Board"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = CONTEXT
    # Sem cabeçalho: a aba já diz o que é, e a seta de recolher só tiraria a
    # única coisa que esta coluna mostra.
    bl_options = {"HIDE_HEADER"}

    def draw(self, context):
        from . import takefile

        layout = self.layout
        store = state.get_store()
        if store is None:
            self._draw_no_board(layout, context)
            return

        cena = sync.current_scene(context)
        takes = list(cena.takes) if cena is not None else []
        open_take = takefile.current_take_of_file(store)
        st = context.window_manager.nsb

        self._draw_title(layout, st)
        draw_take_column(layout, context, store, st, takes, open_take)

    def _draw_title(self, layout, st):
        """`EP13 · CENA01` — de que cena é esta coluna.

        A bancada mostra a mesma linha, mas ela pode estar fechada ou noutra
        aba: uma coluna de planos sem dizer de que cena são é uma armadilha em
        episódio com dez cenas parecidas.
        """
        episodio = st.episodes[st.episode_index] if st.episodes else None
        cena = st.scenes[st.scene_index] if st.scenes else None
        partes = [item.code or item.name for item in (episodio, cena) if item is not None]
        texto = " · ".join(p for p in partes if p)
        if texto:
            layout.label(text=texto, icon="SEQUENCE")

    def _draw_no_board(self, layout, context):
        """Sem board aberto, a coluna manda para onde se abre um."""
        col = layout.column(align=True)
        col.scale_y = 1.5
        col.operator("nsb.open_folder", icon="FILE_FOLDER")
        layout.label(text=_("or open a board in the Storyboard tab of the sidebar"),
                     icon="INFO")


def draw_take_column(layout, context, store, st, takes, open_take):
    """A coluna de planos + os botões que mexem nela.

    Vive fora do painel porque a sidebar cai aqui também, no Nuclear que ainda
    não tem a aba.
    """
    from . import thumbs

    if takes:
        col = layout.column(align=True)
        for item, take in zip(st.takes, takes):
            _draw_card(col, store, thumbs, item, take, open_take)
    else:
        layout.label(text=_("Create a take to start"), icon="INFO")

    row = layout.row(align=True)
    row.operator("nsb.add_take", icon="ADD")
    row.operator("nsb.remove_take", icon="REMOVE", text="")
    row.operator("nsb.move_take", icon="TRIA_UP", text="").offset = -1
    row.operator("nsb.move_take", icon="TRIA_DOWN", text="").offset = 1

    _draw_copy_row(layout)

    faltando = thumbs.missing(store, takes)
    if faltando:
        # Take feito antes das miniaturas (ou em outra máquina, ou adotado do
        # disco) não tem PNG nenhum: gerar exige abrir cada `.nuc`, e isso vai
        # para um Nuclear separado para não atropelar o que está na tela.
        layout.row().operator("nsb.make_thumbs", icon="FILE_REFRESH",
                              text=f"{_('Draw the board')} ({len(faltando)})")


def _draw_copy_row(layout):
    """Duplicar aqui, ou levar o plano para outra cena.

    Qual plano está copiado é dito numa LINHA, e não no botão: entre copiar e
    colar passa uma troca de board, e "Colar" sozinho seria um clique no escuro
    depois de dez minutos desenhando noutra cena. No botão, esse texto viraria
    "Colar T0…" numa coluna estreita — que é pior do que não dizer nada.
    A linha só existe quando há algo copiado.
    """
    from . import ops_takecopy

    copiado = ops_takecopy.clipboard_label()
    if copiado:
        layout.label(text=f"{_('Copied')}: {copiado}", icon="PASTEDOWN")

    row = layout.row(align=True)
    row.operator("nsb.duplicate_take", icon="DUPLICATE")
    row.operator("nsb.copy_take", icon="COPYDOWN", text="")
    row.operator("nsb.paste_take", icon="PASTEDOWN", text="")


#: Altura do campo do código e do botão de abrir, dentro do card. Somadas, dão
#: a altura da miniatura — senão o card cresce e a coluna fica serrilhada.
CODE_SCALE = 1.6
OPEN_SCALE = 3.4


def _draw_card(col, store, thumbs, item, take, open_take):
    """Um plano: miniatura à esquerda; código (editável) e duração à direita."""
    card = col.box()
    linha = card.split(factor=THUMB_SPLIT, align=True)

    ícone = thumbs.icon_id(store, take)
    if ícone:
        linha.template_icon(icon_value=ícone, scale=THUMB_SCALE)
    else:
        # O espaço da miniatura fica lá mesmo vazio: sem ele, take desenhado e
        # take em branco dariam duas alturas de card e a coluna ficaria serrilhada.
        vazio = linha.column(align=True)
        vazio.scale_y = THUMB_SCALE - 1.0
        vazio.label(text="", icon="IMAGE_DATA")

    legenda = linha.column(align=True)
    # Take que não passa na validação aparece em alerta — era a única coisa que
    # a lista de texto dizia e a miniatura não diria.
    legenda.alert = not item.ok

    # O código fica num campo: renomear um plano era coisa de abrir o diálogo da
    # estrutura inteira, e é aqui que o artista está olhando quando percebe que
    # o nome está errado.
    campo = legenda.row(align=True)
    campo.scale_y = CODE_SCALE
    campo.prop(item, "code", text="")

    # O botão de abrir fica com o resto da altura: o clique tem de pegar a faixa
    # inteira ao lado da miniatura — mirar numa tira fina é o que torna uma
    # lista cansativa.
    abrir = legenda.column(align=True)
    abrir.scale_y = OPEN_SCALE
    op = abrir.operator("nsb.goto_take", depress=open_take is take,
                        text=f"{item.duration:.1f}s")
    op.uid = take.id


CLASSES = (NSB_PT_board,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
