"""Clicar num take na lista entra no take.

Antes eram dois passos: escolher o take na lista e depois clicar em "Draw".
O segundo passo nao decidia nada — quem escolheu o take ja disse o que queria —,
entao ele sumiu: mudar a selecao abre o `.nuc` do take, salvando antes o que
estava aberto.

Por que um timer no meio do caminho: a selecao muda dentro do `update` de uma
propriedade, que o Blender chama enquanto desenha a interface. Trocar o arquivo
aberto ali dentro derruba as estruturas que a propria interface esta usando —
`wm.open_mainfile` so pode acontecer no tique seguinte, com a tela ja entregue.

Em background nada e agendado (nao ha loop de eventos para o timer): os testes
headless chamam `open_selected` na mao, que e a mesma coisa sem a espera.
"""

from __future__ import annotations

import bpy

from . import state, sync, takefile


def request_open(context) -> bool:
    """Pede a abertura do take selecionado. Devolve se agendou alguma coisa."""
    from . import props

    # Espelhar o modelo na interface mexe no indice o tempo todo (a lista e
    # reescrita a cada operacao); so o clique do artista abre take.
    if props.is_mirroring() or bpy.app.background:
        return False
    # Quem responde "ja tem abertura a caminho?" e o proprio Blender. Uma
    # variavel nossa era melhor no papel e pior na pratica: bastava o timer ser
    # descartado uma vez (abrir arquivo descarta os nao-persistentes) para a
    # marca ficar acesa para sempre — e a lista de takes parava de abrir take,
    # calada, ate reiniciar o programa.
    if bpy.app.timers.is_registered(_fire) or not _needs_switch(context):
        return False

    # `persistent`: entre o clique e o tique seguinte pode passar um
    # carregamento de arquivo (o proprio take anterior sendo salvo e relido), e
    # o pedido do artista nao pode morrer no meio do caminho.
    bpy.app.timers.register(_fire, first_interval=0.0, persistent=True)
    return True


def _fire():
    open_selected(bpy.context)
    return None  # tiro unico


def _needs_switch(context) -> bool:
    """Ha um take selecionado diferente do que esta aberto no canvas?"""
    store = state.get_store()
    if store is None:
        return False
    take = sync.current_take(context)
    if take is None:
        return False
    aberto = takefile.current_take_of_file(store)
    return aberto is None or aberto.id != take.id


def open_selected(context) -> bool:
    """Abre o take selecionado, se ele ja nao for o que esta na tela.

    Passa pelo operador de proposito: e ele que salva o take anterior, avisa de
    desenho nao gravado e de arte de outro take.
    """
    if not _needs_switch(context):
        return False
    try:
        bpy.ops.nsb.open_take()
    except RuntimeError as exc:
        # Um take que nao abre nao pode deixar a sessao pela metade nem calada.
        print(f"[storyboard] nao consegui abrir o take: {exc}")
        return False
    return True
