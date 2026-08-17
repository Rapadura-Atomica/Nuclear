"""Espelha o `ProjectStore` nas PropertyGroups da UI.

Direcao unica: modelo -> UI. Quem edita o modelo sao os operadores, que chamam
`sync_all` no fim. A UI nunca escreve de volta.

Tudo aqui roda dentro de `props.mirroring()`: escrever numa PropertyGroup
dispara o `update` dela, e algumas dessas reagem ao artista (a selecao de take
abre o take, a cor grava na biblioteca). Sem a marca, espelhar o estado seria
indistinguivel de alguem clicando.
"""

from __future__ import annotations

from . import props, state
from .core import build_timeline, rgb_from_hex, take_duration, validate_project
from .core.rules import ERROR, WARNING, validate_take


def _state(context):
    return context.window_manager.nsb


def current_episode(context):
    store = state.get_store()
    if store is None:
        return None
    st = _state(context)
    if 0 <= st.episode_index < len(store.project.episodes):
        return store.project.episodes[st.episode_index]
    return None


def current_scene(context):
    ep = current_episode(context)
    if ep is None:
        return None
    st = _state(context)
    if 0 <= st.scene_index < len(ep.scenes):
        return ep.scenes[st.scene_index]
    return None


def current_take(context):
    sc = current_scene(context)
    if sc is None:
        return None
    st = _state(context)
    if 0 <= st.take_index < len(sc.takes):
        return sc.takes[st.take_index]
    return None


def sync_all(context) -> None:
    st = _state(context)
    store = state.get_store()
    with props.mirroring():
        if store is None:
            st.loaded = False
            for coll in (st.episodes, st.scenes, st.takes, st.characters,
                         st.props, st.issues):
                coll.clear()
            st.error_count = st.warning_count = st.timeline_frames = 0
            return

        st.loaded = True
        st.project_name = store.project.name
        st.project_dir = str(store.paths.root)

        st.episodes.clear()
        for ep in store.project.episodes:
            item = st.episodes.add()
            item.uid, item.code, item.name = ep.id, ep.code, ep.name
            item.scene_count = len(ep.scenes)
        st.episode_index = min(st.episode_index, max(0, len(st.episodes) - 1))

        ajustes = store.project.settings
        st.delivery_format = ajustes.delivery_format or "MP4"
        st.delivery_target = ajustes.delivery_target or "FOLDER"
        st.delivery_kdenlive = ajustes.delivery_kdenlive
        st.delivery_per_take = ajustes.delivery_per_take
        st.delivery_dir = ajustes.export_dir
        st.delivery_takes_dir = ajustes.takes_export_dir

        sync_scenes(context)
        sync_library(context)
        sync_issues(context)

        _, total = build_timeline(store.project)
        st.timeline_frames = total


def sync_scenes(context) -> None:
    st = _state(context)
    with props.mirroring():
        st.scenes.clear()
        ep = current_episode(context)
        if ep is not None:
            for sc in ep.scenes:
                item = st.scenes.add()
                item.uid, item.code, item.name = sc.id, sc.code, sc.name
                item.take_count = len(sc.takes)
        st.scene_index = min(st.scene_index, max(0, len(st.scenes) - 1))
        sync_takes(context)


def sync_takes(context) -> None:
    st = _state(context)
    store = state.get_store()
    with props.mirroring():
        st.takes.clear()
        sc = current_scene(context)
        if sc is not None and store is not None:
            for tk in sc.takes:
                item = st.takes.add()
                item.uid, item.code, item.name = tk.id, tk.code, tk.name
                item.drawing_count = len(tk.drawings)
                item.audio_count = len(tk.audios)
                item.duration = take_duration(tk)
                issues = validate_take(tk, store.library, store.paths)
                item.ok = not any(i.level == ERROR for i in issues)
        st.take_index = min(st.take_index, max(0, len(st.takes) - 1))


def _prop_image(store, prop) -> str:
    """Imagem que representa o prop na lista, em caminho absoluto.

    A ARTE vem primeiro; enquanto ela não existe vale a referência anexada, que
    é justamente o que o artista quer reconhecer de relance ("qual mesmo era o
    lampião?"). Caminho apontando para arquivo que sumiu devolve vazio: a lista
    volta ao ícone de sempre em vez de mostrar um quadrado carregando para
    sempre.
    """
    for relativo in (prop.file, prop.reference):
        if not relativo:
            continue
        caminho = store.paths.abs(relativo)
        if caminho.is_file():
            return str(caminho)
    return ""


def sync_library(context) -> None:
    st = _state(context)
    store = state.get_store()
    with props.mirroring():
        st.characters.clear()
        st.props.clear()
        if store is None:
            return
        for char in store.library.characters:
            item = st.characters.add()
            item.uid, item.name = char.id, char.name
            item.hex_color, item.rig_path = char.hex_color, char.rig_path
            try:
                item.color = rgb_from_hex(char.hex_color)
            except ValueError:
                # Hex torto vindo de um JSON editado na mao: a lista continua
                # aparecendo (branco), e a validacao e quem reclama.
                item.color = (1.0, 1.0, 1.0)
            item.linked = char.is_linked
        for prop in store.library.props:
            item = st.props.add()
            item.uid, item.name, item.temporary = prop.id, prop.name, prop.temporary
            item.has_art = bool(prop.file)
            item.has_reference = bool(prop.reference)
            item.resolved = bool(prop.replaced_by)
            item.art_path = _prop_image(store, prop)
            # "WAITING" não existe do outro lado: é o estado de quem tem
            # referência anexada e ainda não conseguiu (ou não tentou) abrir a
            # pendência.
            if prop.request_id:
                item.request_status = prop.request_status or "DRAFT"
            elif prop.temporary and prop.reference:
                item.request_status = "WAITING"
            else:
                item.request_status = ""


def sync_issues(context) -> None:
    st = _state(context)
    store = state.get_store()
    with props.mirroring():
        st.issues.clear()
        st.error_count = st.warning_count = 0
        if store is None:
            return
        for issue in validate_project(store.project, store.library, store.paths,
                                      library_missing=store.library_missing):
            item = st.issues.add()
            item.level, item.code = issue.level, issue.code
            item.message, item.where = issue.message, issue.where
            if issue.level == ERROR:
                st.error_count += 1
            elif issue.level == WARNING:
                st.warning_count += 1
