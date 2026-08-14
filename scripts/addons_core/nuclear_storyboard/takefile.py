"""Abrir e salvar o `.nuc` de cada take.

Um arquivo por take: 200 takes num arquivo só ficaria intragável, e assim o
export pode paralelizar depois. O `.nuc` guarda no `Scene` de onde ele veio
(`nsb_project_dir`, `nsb_take_id`), então abrir o arquivo solto — por duplo
clique, fora do add-on — reencontra o projeto sozinho.
"""

from __future__ import annotations

from pathlib import Path

import bpy
from bpy.app.handlers import persistent

from . import audiotl, gp, state, sync, thumbs, workspace
from .core import ProjectStore, StorageError

PROJECT_DIR_KEY = "nsb_project_dir"
TAKE_ID_KEY = "nsb_take_id"

#: Quantos desenhos o índice tinha a mais que o arquivo na última abertura — o
#: operador avisa, porque significa trabalho que nunca chegou a ser gravado.
LAST_DROPPED_DRAWINGS = 0


def stamp_scene(scene, store, take) -> None:
    scene[PROJECT_DIR_KEY] = str(store.paths.root)
    scene[TAKE_ID_KEY] = take.id


def project_root_of_file(filepath) -> Path:
    """Board a que o `.nuc` ABERTO pertence pelo lugar em que está no disco.

    O carimbo de dentro do arquivo diz de onde ele veio, não onde ele está: um
    board copiado, renomeado ou movido carrega o carimbo antigo e faria o
    add-on gravar no board de origem, calado. Quando o arquivo está dentro de
    uma pasta com `project.json`, é essa que manda; o carimbo continua valendo
    para o `.nuc` solto, longe de qualquer projeto (que é para o que ele existe).
    """
    if not filepath:
        return None
    here = Path(filepath).parent
    for folder in [here, *here.parents][:4]:
        if (folder / "project.json").is_file():
            return folder
    return None


def is_on_screen(scene, take) -> bool:
    """A cena aberta é o arquivo deste take?

    Os operadores da sidebar mexem no take SELECIONADO na lista, que nem sempre
    é o que está aberto no canvas — sem esta pergunta, importar um áudio num
    take vizinho remontaria a timeline do take que o artista está desenhando.
    """
    return (scene is not None and take is not None
            and scene.get(TAKE_ID_KEY) == take.id)


def capture_from_scene(scene, store, take) -> bool:
    """Lê de volta o que o artista mexeu na tela: arte, clipes e timing.

    É o miolo do salvar, sem gravar arquivo. Quem vai mudar a duração do take
    precisa fazer isto ANTES: remontar a cena a partir do modelo sem ler o que
    está na tela joga fora o clipe que ele acabou de arrastar.
    """
    from . import timingtools

    if not is_on_screen(scene, take):
        return False
    fps = store.project.settings.fps
    ob = gp.find_take_object(take)
    reference = None
    if ob is not None:
        gp.sync_drawings_from_gp(take, ob)
        # Onde a divisão automática põe os desenhos com a duração de AGORA —
        # antes de ler os clipes de volta, que é o que muda a duração.
        reference = timingtools.planned_frames(take, fps)
    audiotl.sync_from_vse(scene, take, fps)
    if ob is not None:
        timingtools.absorb_manual_timing(take, ob, fps, reference)
    return True


def refresh_take_view(scene, store, take, capture: bool = True) -> bool:
    """Põe a cena em dia com o modelo depois de mexer no take.

    Quando a duração muda — áudio importado, recarregado, apagado, ajuste
    manual — três coisas na tela ficam para trás: os clipes do VSE, o fim da
    cena e a posição dos desenhos. Antes só `open_take` fazia isso, então
    importar um diálogo de 10s num take de 2s deixava o som passando do fim da
    cena, e os desenhos empilhados no primeiro segundo enquanto o animatic
    exportado já os espalhava — a tela mostrando uma coisa e o MP4 outra.

    `capture=False` para quem já leu a tela (ou acabou de abrir o arquivo).
    """
    from . import timingtools

    if not is_on_screen(scene, take):
        return False
    if capture:
        capture_from_scene(scene, store, take)

    fps = store.project.settings.fps
    audiotl.sync_to_vse(scene, store, take)
    audiotl.apply_take_range(scene, take, fps)
    ob = gp.find_take_object(take)
    if ob is not None:
        timingtools.apply_exposures(take, ob, fps)
    return True


def open_take(store, project_take, episode, scene_obj) -> Path:
    """Abre o `.nuc` do take; cria do zero se ainda não existe.

    Devolve o caminho do arquivo. Depois desta chamada o contexto do Blender
    foi trocado — quem chamou deve encerrar o operador em seguida.
    """
    path = store.paths.abs(project_take.file)
    path.parent.mkdir(parents=True, exist_ok=True)

    # `load_ui=False`: a tela é do ARTISTA, não do arquivo. Cada `.nuc` guarda o
    # layout de quando foi salvo, então trocar de take reconstruía a janela
    # inteira — a sidebar piscava, os painéis abertos fechavam e o editor de
    # tempo voltava ao que era. Trocar de take tem que parecer virar a página.
    if path.is_file():
        bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
    else:
        bpy.ops.wm.read_homefile(use_empty=True, load_ui=False)

    scene = bpy.context.scene
    # De quem o ARQUIVO diz ser. Um `.nuc` duplicado (ou adotado do disco) traz
    # o carimbo de quem o gravou, e não o do take que está sendo aberto.
    carimbo = scene.get(TAKE_ID_KEY)
    ob = gp.ensure_take_object(scene, store.project, project_take, store.library)
    stamp_scene(scene, store, project_take)
    # O `load_post` roda DENTRO do `open_mainfile` acima e pode ter atrelado a
    # sessão a outro board (carimbo antigo num arquivo copiado). Quem manda é o
    # projeto de onde o artista pediu para abrir o take.
    state.set_store(store)

    # O take abre pronto para desenhar: objeto ativo e em modo de desenho.
    gp.make_ready_to_draw(ob)

    # …e com a bancada do take anterior: pincel do jeito que ele estava e os
    # materiais que o artista criou. Sem isto, cada `.nuc` devolvia os ajustes
    # gravados NELE, e trocar de plano significava reafinar o pincel.
    workspace.restore_from_disk(bpy.context, store, ob)

    # Quantos desenhos existem é o ARQUIVO quem diz. "Novo desenho" grava o
    # índice na hora, mas a arte só vai para o `.nuc` no salvar: fechar a janela
    # sem salvar deixava o índice com desenhos que não existem — e aí o
    # alinhamento desistia (contagens diferentes) e o animatic exportaria
    # quadros vazios.
    global LAST_DROPPED_DRAWINGS
    LAST_DROPPED_DRAWINGS = max(0, len(project_take.drawings) - len(gp.drawing_frames(ob)))
    gp.sync_drawings_from_gp(project_take, ob)

    # A timeline do take vem montada: áudios com waveform, range de playback na
    # duração certa e os desenhos onde o animatic vai colocá-los — o que o
    # arquivo tem de keyframe é arte, o timing quem manda é o índice.
    refresh_take_view(scene, store, project_take, capture=False)

    # Grava quando o arquivo ainda não existe (take novo) e também quando ele
    # pertencia a OUTRO take: um `.nuc` duplicado abre carimbado com o id do
    # original, e enquanto esse carimbo estiver no disco, abri-lo por fora
    # atrela a sessão ao take de origem — desenhar aqui gravaria lá.
    if not path.is_file() or carimbo != project_take.id:
        bpy.ops.wm.save_as_mainfile(filepath=str(path))

    # Carregar um arquivo recria o WindowManager, e com ele os índices da UI
    # voltam ao primeiro take. Quando o `.nuc` já existe o `load_post` reaponta
    # sozinho pelo carimbo; num take NOVO o arquivo é criado do zero e não há
    # carga nenhuma depois do carimbo — a sidebar ficava mostrando outro take, e
    # o áudio importado logo em seguida ia parar nele.
    _select_take_in_ui(bpy.context, store, project_take.id)
    sync.sync_all(bpy.context)
    return path


def save_take(store, project_take) -> Path:
    """Grava o `.nuc` e reconcilia arte e timeline com o índice JSON.

    Salvar é o momento em que o arquivo passa a ser a verdade, então tudo que o
    artista mexeu na tela entra aqui sozinho: os desenhos, os clipes de áudio
    (arrastados ou cortados) e o timing dos keyframes. Antes cada um desses
    tinha um botão de "ler de volta" — três maneiras de perder trabalho por
    esquecer de clicar.
    """
    scene = bpy.context.scene
    capture_from_scene(scene, store, project_take)
    # A bancada é anotada no salvar, que é por onde a troca de take passa: o
    # take seguinte abre com o pincel e os materiais deste.
    workspace.capture_to_disk(bpy.context, store, gp.find_take_object(project_take))
    # Cortar um clipe muda a duração: a cena e os desenhos precisam acompanhar
    # ANTES de o arquivo ser gravado, senão o `.nuc` guarda um estado que já não
    # corresponde ao índice — e a próxima leitura acusaria os desenhos de terem
    # sido arrastados.
    refresh_take_view(scene, store, project_take, capture=False)
    store.save()

    # Recarimbar antes de gravar: a cena pode ter vindo de outro board (cópia,
    # renomeação, troca de projeto com o take aberto) e o `.nuc` sairia daqui
    # dizendo pertencer a um projeto que não é este — sequestrando a sessão de
    # quem o abrisse depois.
    stamp_scene(scene, store, project_take)

    path = store.paths.abs(project_take.file)
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(path))

    # A miniatura do board sai daqui porque é aqui que a arte está na tela:
    # gerá-la depois custaria abrir o arquivo de novo. Salvar o take é também
    # por onde a troca de take passa, então o board fica em dia sozinho.
    thumbs.render_thumb(scene, store, project_take)
    return path


def current_take_of_file(store):
    """Take a que o arquivo aberto pertence, ou None."""
    take_id = bpy.context.scene.get(TAKE_ID_KEY)
    if not take_id:
        return None
    found = store.project.find_take(take_id)
    return found[2] if found else None


def _select_take_in_ui(context, store, take_id: str) -> None:
    """Aponta os índices da UI para o take que acabou de ser aberto.

    Dentro de `mirroring`: mudar a seleção de take é o que ABRE um take, e aqui
    o take já está aberto — sem a marca, isto pediria a abertura do que acabou
    de ser aberto.
    """
    from . import props

    st = context.window_manager.nsb
    with props.mirroring():
        for ei, ep in enumerate(store.project.episodes):
            for si, sc in enumerate(ep.scenes):
                for ti, tk in enumerate(sc.takes):
                    if tk.id == take_id:
                        st.episode_index = ei
                        st.scene_index = si
                        st.take_index = ti
                        return


@persistent
def _on_load_post(_dummy):
    """Depois de abrir qualquer arquivo, reata o add-on ao projeto do take.

    As PropertyGroups do WindowManager são recriadas a cada carga, então a UI
    precisa ser reespelhada; e o `ProjectStore` em memória pode ser de outro
    projeto (ou nenhum), então recarregamos do disco quando o arquivo aponta
    para um projeto diferente.
    """
    context = bpy.context
    scene = context.scene
    root = scene.get(PROJECT_DIR_KEY) if scene else None
    take_id = scene.get(TAKE_ID_KEY) if scene else None

    # Onde o arquivo ESTÁ vale mais que o carimbo do que ele um dia foi.
    on_disk = project_root_of_file(bpy.data.filepath)
    if on_disk is not None and str(on_disk) != str(root or ""):
        root = str(on_disk)
        if scene:
            scene[PROJECT_DIR_KEY] = root

    if not root:
        sync.sync_all(context)
        return

    store = state.get_store()
    if store is None or str(store.paths.root) != str(root):
        try:
            store = ProjectStore.load(Path(root))
        except StorageError:
            # Projeto sumiu ou moveu: o .nuc ainda abre, só sem o add-on atrelado.
            state.set_store(None)
            sync.sync_all(context)
            return
        state.set_store(store)

    sync.sync_all(context)
    if take_id:
        _select_take_in_ui(context, store, take_id)
        sync.sync_all(context)


def register():
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister():
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
