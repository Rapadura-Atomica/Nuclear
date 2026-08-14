"""Operadores: tudo que altera o projeto passa por aqui.

Contrato de cada operador: mexe no `ProjectStore`, grava em disco quando faz
sentido, e chama `sync.sync_all` no fim para a UI refletir o novo estado.
"""

from __future__ import annotations

from pathlib import Path

import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty,
                       FloatVectorProperty, IntProperty, StringProperty)
from bpy.types import Operator

from . import state, sync, takefile
from .translations import _, apply_context
from .core import Character, ProjectStore, Prop, StorageError, normalize_hex
from .core.rules import blocks_export
from .core.wave_info import AudioError


def _report_error(op, exc) -> set:
    op.report({"ERROR"}, str(exc))
    return {"CANCELLED"}


def _scene(context):
    return getattr(context, "scene", None)


def _editor_preference(context) -> str:
    """Caminho do editor de áudio configurado nas preferências do add-on.

    Vem vazio quando o add-on roda a partir do repositório sem estar instalado
    como extensão — aí `find_audio_editor` se vira com o PATH.
    """
    from .props import get_prefs
    prefs = get_prefs(context)
    return getattr(prefs, "audio_editor", "") if prefs else ""


class NSB_OT_new_project(Operator):
    bl_idname = "nsb.new_project"
    bl_label = "New project"
    bl_description = "Creates the project folder with project.json and library.json"
    bl_options = {"REGISTER"}

    def execute(self, context):
        st = context.window_manager.nsb
        root = bpy.path.abspath(st.project_dir).strip()
        if not root:
            self.report({"ERROR"}, _("choose the project folder"))
            return {"CANCELLED"}
        try:
            store = ProjectStore.create(Path(root), st.project_name or "New Project")
        except StorageError as exc:
            return _report_error(self, exc)
        # Sem `ensure_structure` aqui de propósito: este operador é o caminho de
        # SCRIPT, em que quem chama declara a estrutura que quer. Quem abre pela
        # tela passa por `nsb.open_folder`, e lá o board nasce inteiro.
        state.set_store(store)
        sync.sync_all(context)
        self.report({"INFO"}, _("project created at") + f" {root}")
        return {"FINISHED"}


class NSB_OT_open_project(Operator):
    bl_idname = "nsb.open_project"
    bl_label = "Open project"
    bl_description = "Loads project.json from the given folder"
    bl_options = {"REGISTER"}

    def execute(self, context):
        st = context.window_manager.nsb
        root = bpy.path.abspath(st.project_dir).strip()
        try:
            store = ProjectStore.load(Path(root))
        except StorageError as exc:
            return _report_error(self, exc)
        state.set_store(store)
        sync.sync_all(context)
        self.report({"INFO"}, _("project opened") + f": {store.project.name}")
        return {"FINISHED"}


def episode_dir(context):
    """Pasta do episódio em que se está trabalhando, ou "".

    Com um board aberto ela é a pasta ACIMA dele (as cenas são vizinhas); sem
    board, é a que o animador abriu e ainda não virou cena nenhuma.
    """
    store = state.get_store()
    if store is not None:
        return str(Path(store.paths.root).parent)
    return (context.window_manager.nsb.episode_dir or "").strip()


def save_open_take(destino) -> None:
    """Grava o take que está na tela antes de a sessão trocar de board.

    Sem isto, sair de uma cena com desenho aberto deixaria o traço só na
    memória — e o board seguinte carrega por cima.
    """
    anterior = state.get_store()
    if anterior is None or Path(anterior.paths.root) == Path(destino):
        return
    aberto = takefile.current_take_of_file(anterior)
    if aberto is not None:
        takefile.save_take(anterior, aberto)
    else:
        anterior.save()


def open_or_create_board(context, alvo):
    """Abre o board da pasta (ou começa um) e o deixa na tela. (store, existia?)

    É o miolo compartilhado por "abrir pasta", "nova cena" e o menu de cenas:
    os três significam a mesma coisa — entrar naquela pasta para trabalhar.
    """
    from . import autoswitch
    from .core import context_from_path, ensure_structure
    from .core.storage import PROJECT_FILE
    from .props import remember_board

    alvo = Path(alvo)
    existente = (alvo / PROJECT_FILE).is_file()
    deduzido = context_from_path(alvo)
    if existente:
        store = ProjectStore.load(alvo)
    else:
        store = ProjectStore.create(alvo, deduzido.project_name,
                                    project_code=deduzido.project_code,
                                    library_path=_shared_library(alvo))
    store.ensure_dirs()
    mudou = ensure_structure(store)

    # Board NOVO numa pasta em que já se desenhou: os `.nuc` que estão lá viram
    # takes do board. Sem isto a grade abria vazia com o trabalho inteiro no
    # disco, invisível. Só na criação — em board que já existe, um arquivo sem
    # take é um take REMOVIDO de propósito, e ressuscitá-lo a cada abertura
    # desfaria a decisão do animador.
    if not existente:
        cena = _first_scene(store)
        if cena is not None and store.adopt_take_files(cena):
            mudou = True

    if mudou:
        store.save()

    state.set_store(store)
    context.window_manager.nsb.episode_dir = str(alvo.parent)
    remember_board(context, store.paths.root, store.project.name)
    sync.sync_all(context)

    # A cena escolhida tem de aparecer na TELA, não só na lista: o take anterior
    # continua aberto no canvas e é de outro board. Quem abre é o mesmo timer da
    # lista de takes — trocar de arquivo aqui dentro seria no meio do fechamento
    # do navegador de pastas.
    autoswitch.request_open(context)
    return store, existente


def _first_scene(store):
    """Cena em que o board novo põe os takes, ou None se não houver nenhuma."""
    for episode in store.project.episodes:
        if episode.scenes:
            return episode.scenes[0]
    return None


def _shared_library(root) -> str:
    """Caminho (relativo à pasta nova) da biblioteca que já existe por perto.

    Cada cena é um board, e os personagens são do EPISÓDIO: sem isto, entrar na
    CENA02 daria uma biblioteca vazia, e a cor de cada personagem — que é a
    chave que aponta para o rig — seria recadastrada cena a cena, escorregando.
    Relativo com `..` para o episódio inteiro continuar valendo depois de mudar
    de máquina ou de pasta.
    """
    import os

    from .core import find_shared_library

    achada = find_shared_library(root)
    if achada is None:
        return ""
    return os.path.relpath(achada, root)


class NSB_OT_open_folder(Operator):
    """Uma pasta, um board — sem perguntar episódio nem cena.

    O animador escolhe a pasta em que quer fazer os takes e acabou: se já houver
    um board ali, ele abre; se não houver, nasce um, com o episódio e a cena
    lidos do próprio caminho (`.../DPE/EP06/CENA03`). Era o passo que fazia
    começar um board custar cinco decisões antes do primeiro traço — e as duas
    perguntas do meio já estavam respondidas na pasta escolhida.
    """

    bl_idname = "nsb.open_folder"
    bl_label = "Open takes folder"
    bl_description = ("Opens the board in this folder, or starts one there — the "
                      "episode and the scene come from the path")

    directory: StringProperty(subtype="DIR_PATH", options={"SKIP_SAVE"})
    filter_folder: BoolProperty(default=True, options={"HIDDEN", "SKIP_SAVE"})
    #: Caminho já conhecido (lista de recentes, testes): pula o navegador.
    path: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        if self.path:
            return self.execute(context)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        from .core import ROLE_EPISODE, folder_role, path_from_link
        from .props import remember_board

        escolhido = (self.path or self.directory or "").strip()
        if not escolhido:
            self.report({"ERROR"}, _("choose the folder where the takes go"))
            return {"CANCELLED"}

        # O caminho da cena costuma chegar copiado do Dropbox na web.
        do_link = path_from_link(escolhido)
        if do_link is not None:
            if not do_link.is_dir():
                self.report({"ERROR"}, _("this folder is not synced on this machine")
                                       + f": {do_link}")
                return {"CANCELLED"}
            alvo = do_link
        elif "://" in escolhido:
            self.report({"ERROR"}, _("this link does not say where the folder is"))
            return {"CANCELLED"}
        else:
            alvo = Path(bpy.path.abspath(escolhido)).expanduser()
        # Clicar no próprio `project.json` no navegador é o engano natural.
        if alvo.is_file():
            alvo = alvo.parent

        # Sair de um board com desenho na tela é sair do take: ele é gravado
        # aqui, senão o traço da cena anterior ficaria só na memória.
        save_open_take(alvo)

        # A pasta do EPISÓDIO (`.../EP13/1 - Thumbs`) não é um board: ela guarda
        # as cenas. Entrar por ela é o caminho normal do animador — ele escolhe
        # o episódio e depois a cena, que pode nem existir ainda.
        if folder_role(alvo) == ROLE_EPISODE:
            st = context.window_manager.nsb
            st.episode_dir = str(alvo)
            state.set_store(None)
            remember_board(context, alvo, alvo.name, kind="episode")
            sync.sync_all(context)
            self.report({"INFO"}, _("episode opened") + f": {alvo.name}")
            return {"FINISHED"}

        try:
            store, existente = open_or_create_board(context, alvo)
        except StorageError as exc:
            return _report_error(self, exc)

        rotulo = _("board opened") if existente else _("board started at")
        self.report({"INFO"}, f"{rotulo}: {alvo}")
        return {"FINISHED"}


class NSB_OT_new_scene_folder(Operator):
    """Cria a pasta de uma cena dentro do episódio e entra nela.

    O animador digita só o NÚMERO: o nome da pasta sai no padrão que o episódio
    já usa (`CENA07`), porque é a nomenclatura que o montador do episódio lê
    para ordenar os planos — e duas convenções na mesma pasta quebram isso.
    """

    bl_idname = "nsb.new_scene_folder"
    bl_label = "New scene"
    bl_description = "Creates the scene folder inside the episode and opens it"

    number: IntProperty(name="Scene", default=1, min=1, max=999)

    @classmethod
    def poll(cls, context):
        return bool(episode_dir(context))

    def invoke(self, context, event):
        from .core import next_scene_number

        self.number = next_scene_number(episode_dir(context))
        return context.window_manager.invoke_props_dialog(self, width=260)

    def draw(self, context):
        from .core import scene_folder_name

        layout = self.layout
        layout.prop(self, "number")
        # O nome da pasta, antes de ela existir: é ele que a produção vai ver no
        # Dropbox, e o que o nome dos arquivos entregues vai carregar.
        layout.label(text=_("Folder") + ": "
                          + scene_folder_name(episode_dir(context), self.number),
                     icon="FILE_FOLDER")

    def execute(self, context):
        from .core import scene_folder_name

        pasta_do_ep = episode_dir(context)
        if not pasta_do_ep:
            self.report({"ERROR"}, _("open the episode folder first"))
            return {"CANCELLED"}

        alvo = Path(pasta_do_ep) / scene_folder_name(pasta_do_ep, self.number)
        já_existia = alvo.is_dir()
        try:
            alvo.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return _report_error(self, exc)

        save_open_take(alvo)
        try:
            store, existente = open_or_create_board(context, alvo)
        except StorageError as exc:
            return _report_error(self, exc)

        if existente:
            self.report({"WARNING"}, _("this scene already existed") + f": {alvo.name}")
        elif já_existia:
            self.report({"INFO"}, _("board started in the folder that was there")
                                  + f": {alvo.name}")
        else:
            self.report({"INFO"}, _("scene created") + f": {alvo.name}")
        return {"FINISHED"}


class NSB_OT_close_episode(Operator):
    """Larga o episódio aberto e volta à tela de escolher pasta."""

    bl_idname = "nsb.close_episode"
    bl_label = "Close episode"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        context.window_manager.nsb.episode_dir = ""
        sync.sync_all(context)
        return {"FINISHED"}


class NSB_OT_open_board_folder(Operator):
    """Abre no gerenciador de arquivos a pasta em que os takes estão sendo feitos.

    O add-on sabe o caminho (foi ele que criou a pasta `takes/` lá dentro); esta
    é a maneira de ele CONTAR o caminho ao artista, que precisa dele para mandar
    o material adiante.
    """

    bl_idname = "nsb.open_board_folder"
    bl_label = "Open board folder"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return state.has_project()

    def execute(self, context):
        store = state.require_store()
        store.ensure_dirs()
        bpy.ops.wm.path_open(filepath=str(store.paths.takes))
        return {"FINISHED"}


class NSB_OT_forget_board(Operator):
    """Tira um board da lista de recentes (o board em si fica no disco)."""

    bl_idname = "nsb.forget_board"
    bl_label = "Forget this board"
    bl_options = {"REGISTER", "INTERNAL"}

    path: StringProperty(default="", options={"HIDDEN"})

    def execute(self, context):
        import json

        from .props import _recent_path, recent_boards

        lista = [d for d in recent_boards(context) if d.get("path") != self.path]
        try:
            _recent_path().write_text(json.dumps(lista, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
        except OSError as exc:
            return _report_error(self, exc)
        return {"FINISHED"}


class NSB_OT_save_project(Operator):
    bl_idname = "nsb.save_project"
    bl_label = "Save project"
    bl_description = "Writes project.json and library.json"

    @classmethod
    def poll(cls, context):
        return state.has_project()

    def execute(self, context):
        store = state.require_store()
        try:
            store.save()
        except OSError as exc:
            return _report_error(self, exc)
        sync.sync_all(context)
        self.report({"INFO"}, _("project saved"))
        return {"FINISHED"}


class NSB_OT_close_project(Operator):
    bl_idname = "nsb.close_project"
    bl_label = "Close project"
    bl_description = "Saves and closes the current project"

    @classmethod
    def poll(cls, context):
        return state.has_project()

    def execute(self, context):
        store = state.require_store()
        store.save()
        state.set_store(None)
        sync.sync_all(context)
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Estrutura
# ---------------------------------------------------------------------------

class NSB_OT_add_episode(Operator):
    bl_idname = "nsb.add_episode"
    bl_label = "New episode"

    code: StringProperty(name="Code", default="EP01")
    name: StringProperty(name="Name", default="")

    @classmethod
    def poll(cls, context):
        return state.has_project()

    def invoke(self, context, event):
        store = state.require_store()
        self.code = f"EP{len(store.project.episodes) + 1:02d}"
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        store = state.require_store()
        store.add_episode(self.code, self.name)
        store.save()
        context.window_manager.nsb.episode_index = len(store.project.episodes) - 1
        sync.sync_all(context)
        return {"FINISHED"}


class NSB_OT_add_scene(Operator):
    bl_idname = "nsb.add_scene"
    bl_label = "New scene"

    code: StringProperty(name="Code", default="SC01")
    name: StringProperty(name="Name", default="")

    @classmethod
    def poll(cls, context):
        return sync.current_episode(context) is not None

    def invoke(self, context, event):
        ep = sync.current_episode(context)
        self.code = f"SC{len(ep.scenes) + 1:02d}"
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        store = state.require_store()
        ep = sync.current_episode(context)
        store.add_scene(ep, self.code, self.name)
        store.save()
        context.window_manager.nsb.scene_index = len(ep.scenes) - 1
        sync.sync_all(context)
        return {"FINISHED"}


class NSB_OT_add_take(Operator):
    """Cria o take seguinte da cena. Sem diálogo: o código é a ordem dele.

    Perguntar o código antes de criar era perguntar o que o próprio programa
    responderia — e o lápis conserta depois, se o board precisar de outro nome.
    """

    bl_idname = "nsb.add_take"
    bl_label = "New take"

    #: Vazio = numerar sozinho. Continua existindo para quem chama por script.
    code: StringProperty(name="Code", default="")
    name: StringProperty(name="Name", default="")

    @classmethod
    def poll(cls, context):
        return sync.current_scene(context) is not None

    def execute(self, context):
        store = state.require_store()
        sc = sync.current_scene(context)
        store.add_take(sc, self.code or store.free_take_code(sc), self.name)
        store.save()
        context.window_manager.nsb.take_index = len(sc.takes) - 1
        sync.sync_all(context)
        return {"FINISHED"}


class NSB_OT_remove_take(Operator):
    bl_idname = "nsb.remove_take"
    bl_label = "Remove take"
    bl_options = {"REGISTER", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        return sync.current_take(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        store = state.require_store()
        sc = sync.current_scene(context)
        take = sync.current_take(context)
        sc.takes.remove(take)
        store.save()
        sync.sync_all(context)
        self.report({"INFO"}, _("take removed from the index; files stay on disk")
                             + f": {take.code}")
        return {"FINISHED"}


class NSB_OT_move_take(Operator):
    """Reordena o take dentro da cena — muda a ordem no animatic."""

    bl_idname = "nsb.move_take"
    bl_label = "Move take"
    bl_options = {"REGISTER", "INTERNAL"}

    offset: IntProperty(default=-1)

    @classmethod
    def poll(cls, context):
        return sync.current_take(context) is not None

    def execute(self, context):
        store = state.require_store()
        st = context.window_manager.nsb
        sc = sync.current_scene(context)
        i = st.take_index
        j = i + self.offset
        if not (0 <= j < len(sc.takes)):
            return {"CANCELLED"}
        sc.takes[i], sc.takes[j] = sc.takes[j], sc.takes[i]
        # O take selecionado é o mesmo, só mudou de lugar na lista: seguir o
        # índice não é escolher outro take, então não abre nada.
        from .props import mirroring
        with mirroring():
            st.take_index = j
        store.save()
        sync.sync_all(context)
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Take: audio e duracao
# ---------------------------------------------------------------------------

class NSB_OT_import_audio(Operator):
    bl_idname = "nsb.import_audio"
    bl_label = "Import audio"
    bl_description = "Copies a .wav into the project and adds it to the take"

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.wav", options={"HIDDEN"})
    start: FloatProperty(name="Start (s)", default=0.0, min=0.0)

    @classmethod
    def poll(cls, context):
        return sync.current_take(context) is not None

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        store = state.require_store()
        take = sync.current_take(context)
        takefile.capture_from_scene(_scene(context), store, take)
        try:
            clip = store.import_audio(self.filepath, take, start=self.start)
        except (StorageError, AudioError) as exc:
            return _report_error(self, exc)
        # Sem isto o diálogo entrava no índice mas não aparecia na timeline, e a
        # cena continuava do tamanho de antes — o som passando do fim.
        takefile.refresh_take_view(_scene(context), store, take, capture=False)
        store.save()
        sync.sync_all(context)
        self.report({"INFO"}, _("audio imported") + f": {clip.name} ({clip.duration:.2f}s)")
        return {"FINISHED"}


class NSB_OT_remove_audio(Operator):
    bl_idname = "nsb.remove_audio"
    bl_label = "Remove audio"
    bl_options = {"REGISTER", "INTERNAL"}

    index: IntProperty(default=0)

    @classmethod
    def poll(cls, context):
        return sync.current_take(context) is not None

    def execute(self, context):
        store = state.require_store()
        take = sync.current_take(context)
        if 0 <= self.index < len(take.audios):
            takefile.capture_from_scene(_scene(context), store, take)
            take.audios.pop(self.index)
            takefile.refresh_take_view(_scene(context), store, take, capture=False)
            store.save()
            sync.sync_all(context)
        return {"FINISHED"}


class NSB_OT_set_audio_start(Operator):
    bl_idname = "nsb.set_audio_start"
    bl_label = "Place audio"

    index: IntProperty(default=0)
    start: FloatProperty(name="Start (s)", default=0.0, min=0.0)

    @classmethod
    def poll(cls, context):
        return sync.current_take(context) is not None

    def invoke(self, context, event):
        take = sync.current_take(context)
        if 0 <= self.index < len(take.audios):
            self.start = take.audios[self.index].start
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        store = state.require_store()
        take = sync.current_take(context)
        if 0 <= self.index < len(take.audios):
            takefile.capture_from_scene(_scene(context), store, take)
            take.audios[self.index].start = self.start
            takefile.refresh_take_view(_scene(context), store, take, capture=False)
            store.save()
            sync.sync_all(context)
        return {"FINISHED"}


class NSB_OT_edit_audio_external(Operator):
    """RF-18: manda o clipe para o Audacity e passa a vigiar o arquivo."""

    bl_idname = "nsb.edit_audio_external"
    bl_label = "Edit in Audacity"
    bl_description = ("Opens the clip .wav in the external audio editor; when it "
                      "is saved the take reloads by itself")

    index: IntProperty(default=0)

    @classmethod
    def poll(cls, context):
        take = sync.current_take(context)
        return take is not None and bool(take.audios)

    def execute(self, context):
        from . import audioedit
        from .core.audioedit import EditorNotFound

        store = state.require_store()
        take = sync.current_take(context)
        if not (0 <= self.index < len(take.audios)):
            return {"CANCELLED"}
        audio = take.audios[self.index]
        try:
            command = audioedit.launch(store, take, audio, _editor_preference(context))
        except (EditorNotFound, OSError) as exc:
            return _report_error(self, exc)
        self.report({"INFO"}, _("audio open in the editor") + f": {command}")
        return {"FINISHED"}


class NSB_OT_reload_audio(Operator):
    """Relê o `.wav` do disco sem esperar o vigia (RF-18)."""

    bl_idname = "nsb.reload_audio"
    bl_label = "Reload audio"
    bl_description = "Rereads the .wav from disk and updates the clip duration"

    index: IntProperty(default=0)

    @classmethod
    def poll(cls, context):
        take = sync.current_take(context)
        return take is not None and bool(take.audios)

    def execute(self, context):
        from . import audioedit

        store = state.require_store()
        take = sync.current_take(context)
        if not (0 <= self.index < len(take.audios)):
            return {"CANCELLED"}
        audio = take.audios[self.index]
        takefile.capture_from_scene(_scene(context), store, take)
        try:
            duration = audioedit.reload_audio(context.scene, store, take, audio)
        except (AudioError, OSError) as exc:
            return _report_error(self, exc)
        store.save()
        sync.sync_all(context)
        self.report({"INFO"}, f"{audio.name}: {duration:.2f}s")
        return {"FINISHED"}


class NSB_OT_set_take_duration(Operator):
    """Ajuste manual da duracao (RF-A03). Limpar volta ao cálculo pelo áudio."""

    bl_idname = "nsb.set_take_duration"
    bl_label = "Take duration"

    duration: FloatProperty(name="Duration (s)", default=2.0, min=0.041)
    clear: BoolProperty(name="Back to automatic", default=False)

    @classmethod
    def poll(cls, context):
        return sync.current_take(context) is not None

    def invoke(self, context, event):
        from .core import take_duration
        self.duration = take_duration(sync.current_take(context))
        self.clear = False
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        store = state.require_store()
        take = sync.current_take(context)
        takefile.capture_from_scene(_scene(context), store, take)
        take.duration_override = None if self.clear else self.duration
        takefile.refresh_take_view(_scene(context), store, take, capture=False)
        store.save()
        sync.sync_all(context)
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Biblioteca
# ---------------------------------------------------------------------------

class NSB_OT_add_character(Operator):
    """Cadastra um personagem: nome, cor do lineart e (depois) o rig final.

    A cor é escolhida no seletor do Nuclear, não digitada em hexadecimal —
    escolher a cor de um personagem é trabalho de olho, e o artista não tem por
    que saber que o pipeline guarda isso como `#3366CC`. O hex continua sendo o
    que vai para o `library.json`, e quem precisa dele (o design mandou a cor
    exata) digita no campo Hex de dentro do próprio seletor.
    """

    bl_idname = "nsb.add_character"
    bl_label = "New character"
    bl_description = "Registers a character with the lineart color and the final rig"

    name: StringProperty(name="Name", default="")
    color: FloatVectorProperty(
        name="Lineart color", subtype="COLOR_GAMMA", size=3, min=0.0, max=1.0,
        default=(1.0, 0.0, 0.0),
        description="Colour this character's lineart is drawn with")
    #: Continua existindo para quem chama o operador por script (testes, piloto)
    #: com a cor exata em mãos; a tela usa o seletor.
    hex_color: StringProperty(name="Hex color", default="",
                              options={"HIDDEN", "SKIP_SAVE"})
    rig_path: StringProperty(name="Rig (.nuc)", subtype="FILE_PATH", default="")

    @classmethod
    def poll(cls, context):
        return state.has_project()

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        from .core import hex_from_rgb

        layout = self.layout
        layout.prop(self, "name")
        layout.prop(self, "color")
        # O hex aparece porque é a chave que casa o desenho com o rig — mas como
        # resultado, não como campo a preencher.
        layout.label(text=_("Colour code") + f": {hex_from_rgb(self.color)}")
        layout.prop(self, "rig_path")

    def execute(self, context):
        from .core import hex_from_rgb

        store = state.require_store()
        escolhido = self.hex_color or hex_from_rgb(self.color)
        try:
            hex_color = normalize_hex(escolhido)
        except ValueError as exc:
            return _report_error(self, exc)
        if store.library.character_by_hex(hex_color) is not None:
            self.report({"ERROR"}, _("this color already belongs to another character")
                              + f": {hex_color}")
            return {"CANCELLED"}
        rig = bpy.path.abspath(self.rig_path) if self.rig_path else ""
        store.library.characters.append(Character(
            name=self.name or "Personagem", hex_color=hex_color,
            rig_path=store.paths.rel(rig) if rig else ""))
        store.save()
        sync.sync_all(context)
        return {"FINISHED"}


class NSB_OT_link_character_rig(Operator):
    """RN03: liga a cor hex ao rig final."""

    bl_idname = "nsb.link_character_rig"
    bl_label = "Link rig"

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.nuc;*.blend", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        st = context.window_manager.nsb
        return state.has_project() and 0 <= st.character_index < len(st.characters)

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        store = state.require_store()
        st = context.window_manager.nsb
        char = store.library.characters[st.character_index]
        char.rig_path = store.paths.rel(bpy.path.abspath(self.filepath))
        store.save()
        sync.sync_all(context)
        self.report({"INFO"}, _("rig linked") + f": {char.name} → {char.rig_path}")
        return {"FINISHED"}


class NSB_OT_remove_character(Operator):
    bl_idname = "nsb.remove_character"
    bl_label = "Remove character"
    bl_options = {"REGISTER", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        st = context.window_manager.nsb
        return state.has_project() and 0 <= st.character_index < len(st.characters)

    def execute(self, context):
        store = state.require_store()
        st = context.window_manager.nsb
        char = store.library.characters.pop(st.character_index)
        for _, _, take in store.project.iter_takes():
            if char.id in take.character_ids:
                take.character_ids.remove(char.id)
        store.save()
        sync.sync_all(context)
        return {"FINISHED"}


class NSB_OT_rename_project(Operator):
    """Corrige o nome do projeto e a sigla que abre o nome dos arquivos.

    Existe porque até aqui os dois só se escolhiam na CRIAÇÃO do board: o nome
    saía da pasta (`.../DPE/EP06/CENA03` -> "DPE") e, quando a pasta não dizia
    nada, ficava "New Project" para sempre — e esse nome não é enfeite, ele vai
    escrito no burning de todo quadro entregue.

    Nome e sigla andam juntos num diálogo só porque são a mesma pergunta feita
    duas vezes: como este projeto se chama para quem assiste (o burning) e como
    ele se chama para quem recebe o arquivo (`DPE_EP03_C02T05`).
    """

    bl_idname = "nsb.rename_project"
    bl_label = "Rename project"
    bl_description = ("Fixes the project name that goes in the burn-in and the "
                      "code that opens every delivered file name")

    project_name: StringProperty(
        name="Project name", default="",
        description="Goes in the burn-in of every frame delivered")
    code: StringProperty(
        name="Project code", default="",
        description=("Short code that opens every delivered file name "
                     "(DPE_EP03_C02T05); empty uses the board name"))

    @classmethod
    def poll(cls, context):
        return state.has_project()

    def invoke(self, context, event):
        from .core.naming import suggest_project_code

        store = state.require_store()
        self.project_name = store.project.name
        self.code = store.project.settings.project_code or \
            suggest_project_code(store.project.name)
        # Largo o bastante para o nome de exemplo caber inteiro: é ele que faz a
        # sigla ser conferida antes de virar vinte arquivos.
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, context):
        from .core.naming import project_code, scope_basename

        layout = self.layout
        # Rótulo em cima, campo embaixo: em linha, "Sigla do projeto" saía
        # truncado como "Sigla do pr...".
        layout.label(text=_("Project name"))
        layout.prop(self, "project_name", text="")
        layout.separator()
        layout.label(text=_("Project code"))
        layout.prop(self, "code", text="")

        store = state.get_store()
        if store is None:
            return
        # Mostra o nome pronto: é assim que o animador vê que errou a sigla
        # antes de gerar vinte arquivos com ela.
        antes = (store.project.name, store.project.settings.project_code)
        store.project.name = self.project_name
        store.project.settings.project_code = self.code
        try:
            exemplo = next(iter(store.project.iter_takes()), None)
            if exemplo is not None:
                ep, sc, tk = exemplo
                nome = scope_basename(store.project, ep, sc, tk)
            else:
                nome = project_code(store.project)
        finally:
            store.project.name, store.project.settings.project_code = antes
        layout.label(text=_("Files will be named") + ":")
        layout.label(text=f"{nome}.mp4", icon="FILE_MOVIE")

    def execute(self, context):
        from .props import remember_board

        store = state.require_store()
        nome = self.project_name.strip()
        if not nome:
            self.report({"ERROR"}, _("the project needs a name"))
            return {"CANCELLED"}

        store.project.name = nome
        store.project.settings.project_code = self.code.strip()
        store.save()
        # A lista de boards recentes guarda o nome de quando o board foi aberto;
        # sem isto o board renomeado seguiria como "New Project" no menu de
        # abrir, que é justamente onde o animador procura por ele.
        remember_board(context, store.paths.root, store.project.name)
        sync.sync_all(context)
        self.report({"INFO"}, _("names updated"))
        return {"FINISHED"}


class NSB_OT_rename_structure(Operator):
    """Corrige código e nome do episódio, da cena e do take selecionados.

    Existe porque o código não é enfeite: ele entra no burning e no nome de cada
    arquivo entregue (`DPE_EP03_C02T05`). Sem isto, um "EP3" digitado errado no
    começo do board ficava errado para sempre.

    O arquivo `.nuc` do take NÃO é renomeado junto: ele é carimbado e apontado
    pelo índice, e mexer no nome só criaria chance de perder arte. O nome do
    arquivo de entrega vem do código, não do `.nuc`.
    """

    bl_idname = "nsb.rename_structure"
    bl_label = "Rename"
    bl_description = ("Fixes the code and the name of the selected episode, scene "
                      "and take — the code is what opens each delivered file name")

    episode_code: StringProperty(name="Episode code", default="")
    episode_name: StringProperty(name="Episode name", default="")
    scene_code: StringProperty(name="Scene code", default="")
    scene_name: StringProperty(name="Scene name", default="")
    take_code: StringProperty(name="Take code", default="")
    take_name: StringProperty(name="Take name", default="")

    @classmethod
    def poll(cls, context):
        return state.has_project() and sync.current_episode(context) is not None

    def invoke(self, context, event):
        ep = sync.current_episode(context)
        sc = sync.current_scene(context)
        tk = sync.current_take(context)
        self.episode_code, self.episode_name = ep.code, ep.name
        self.scene_code = sc.code if sc else ""
        self.scene_name = sc.name if sc else ""
        self.take_code = tk.code if tk else ""
        self.take_name = tk.name if tk else ""
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        from .core.naming import scope_basename

        layout = self.layout
        ep = sync.current_episode(context)
        sc = sync.current_scene(context)
        tk = sync.current_take(context)

        # Uma caixa por nível, com rótulos curtos: "Código do episódio" não cabe
        # na coluna de rótulos do diálogo e saía como "Código do episó...".
        box = layout.box()
        box.label(text=_("Episode"), icon="SEQUENCE")
        box.prop(self, "episode_code", text=_("Code"))
        box.prop(self, "episode_name", text=_("Name"))
        if sc is not None:
            box = layout.box()
            box.label(text=_("Scene"), icon="SEQ_STRIP_DUPLICATE")
            box.prop(self, "scene_code", text=_("Code"))
            box.prop(self, "scene_name", text=_("Name"))
        if tk is not None:
            box = layout.box()
            box.label(text=_("Take"), icon="GREASEPENCIL")
            box.prop(self, "take_code", text=_("Code"))
            box.prop(self, "take_name", text=_("Name"))

        # O nome do arquivo com os códigos DESTE diálogo, antes de gravar.
        store = state.get_store()
        if store is None or tk is None:
            return
        antes = (ep.code, sc.code if sc else "", tk.code)
        ep.code = self.episode_code
        if sc is not None:
            sc.code = self.scene_code
        tk.code = self.take_code
        try:
            exemplo = scope_basename(store.project, ep, sc, tk)
        finally:
            ep.code, tk.code = antes[0], antes[2]
            if sc is not None:
                sc.code = antes[1]
        layout.label(text=_("Files will be named") + ":")
        layout.label(text=f"{exemplo}.mp4", icon="FILE_MOVIE")

    def execute(self, context):
        store = state.require_store()
        ep = sync.current_episode(context)
        sc = sync.current_scene(context)
        tk = sync.current_take(context)

        if not self.episode_code.strip():
            self.report({"ERROR"}, _("the episode needs a code"))
            return {"CANCELLED"}

        ep.code = self.episode_code.strip()
        ep.name = self.episode_name.strip() or ep.code
        if sc is not None:
            sc.code = self.scene_code.strip() or sc.code
            sc.name = self.scene_name.strip() or sc.code
        if tk is not None:
            tk.code = self.take_code.strip() or tk.code
            tk.name = self.take_name.strip() or tk.code

        store.save()
        sync.sync_all(context)
        self.report({"INFO"}, _("names updated"))
        return {"FINISHED"}


#: Como cada origem de referência se explica no diálogo. A ordem é a de
#: `gp.prop_reference_source`.
PROP_SOURCE_LABEL = {
    "ACTIVE": "the drawing on the layer you are on",
    "PROPS": "what is drawn in the objects group",
    "FRAME": "this plan's frame",
    "NONE": "nothing yet — the request waits for a picture",
}

#: Altura da prévia da imagem anexada ao prop, em alturas de ícone.
PROP_PREVIEW_SCALE = 7.0


class NSB_OT_add_prop(Operator):
    """Cadastra um prop na biblioteca do projeto.

    A referência sai do PRÓPRIO DESENHO. Antes era preciso ter uma imagem do
    objeto em mãos — foto, print, alguma coisa — e o artista de board não tem
    isso: ele tem o rabisco que acabou de fazer. Agora o rabisco é a referência,
    e quando nem isso existe vale o quadro do plano, que mostra o objeto no
    contexto. Anexar uma imagem continua possível, mas deixou de ser obrigatório.

    Prop provisório com referência vira PEDIDO: abre-se, no sistema de
    aprovação, uma pendência para alguém criar a arte de verdade. Sem rede ou
    sem login o pedido fica na fila do board e o botão "Enviar pendências"
    resolve depois — desenhar não pode depender de internet.
    """

    bl_idname = "nsb.add_prop"
    bl_label = "New prop"

    name: StringProperty(name="Name", default="")
    temporary: BoolProperty(name="Temporary", default=True,
                            description="Provisional version, still to be replaced")
    reference: StringProperty(
        name="Picture (optional)", subtype="FILE_PATH", default="",
        options={"SKIP_SAVE"},
        description=("Only if you already have one — without it the drawing "
                     "itself is used"))
    source: EnumProperty(
        name="Art", options={"HIDDEN"},
        items=[("AUTO", "Automatic", "Layer being drawn, objects group or the frame"),
               ("ACTIVE", "Active layer", "Only the layer being drawn on"),
               ("PROPS", "Objects group", "Every layer in the objects group"),
               ("FRAME", "Whole frame", "The plan as it is on screen"),
               ("NONE", "None", "Register with no art at all")],
        default="AUTO")
    request: BoolProperty(
        name="Ask the studio to create it", default=True,
        description=("Opens a pending item in the approval system, with the "
                     "reference attached"))
    notes: StringProperty(name="Notes", default="")

    @classmethod
    def poll(cls, context):
        return state.has_project()

    def invoke(self, context, event):
        # O nome da camada em que ele está desenhando costuma SER o nome do
        # objeto ("lampião"), então o campo já vem preenchido.
        modo, camadas = self._source(context)
        if not self.name and modo == "ACTIVE" and camadas:
            self.name = camadas[0].name
        return context.window_manager.invoke_props_dialog(self, width=380)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "name")
        layout.prop(self, "temporary")

        modo, _camadas = self._source(context)
        origem = self.reference and "PICTURE" or modo
        if origem == "PICTURE":
            texto = _("the picture you chose")
        else:
            texto = _(PROP_SOURCE_LABEL[modo])
        linha = layout.row()
        linha.alert = (origem == "NONE")
        linha.label(text=_("Reference") + ": " + texto,
                    icon="IMAGE_DATA" if origem != "NONE" else "INFO")
        layout.prop(self, "reference")
        self._draw_preview(layout)

        if self.temporary:
            linha = layout.row()
            linha.enabled = origem != "NONE"
            linha.prop(self, "request")
            store = state.get_store()
            ligado = store.project.settings.approval_project_name if store else ""
            if origem != "NONE" and self.request:
                if ligado:
                    layout.label(text=_("Request goes to") + f": {ligado}", icon="URL")
                else:
                    linha = layout.row()
                    linha.alert = True
                    linha.label(text=_("this board is not linked to a project yet"),
                                icon="ERROR")
        layout.prop(self, "notes")

    def _draw_preview(self, layout):
        """Mostra a imagem anexada antes de o prop virar pedido.

        O que sai daqui vai para o estúdio como versão 1 de uma pendência —
        alguém vai desenhar a partir dela. Escolher o arquivo errado (a foto do
        lado, o print da pasta) só aparecia depois de enviado, e desfazer um
        pedido custa a ida de volta a duas pessoas.
        """
        from . import thumbs

        if not self.reference:
            return
        caminho = Path(bpy.path.abspath(self.reference)).expanduser()
        if not caminho.is_file():
            linha = layout.row()
            linha.alert = True
            linha.label(text=_("reference image not found"), icon="ERROR")
            return
        # Pela PRÉVIA e não pelo `icon_id`: o id é 0 em background, e decidir
        # por ele faria o desenho tomar caminhos diferentes na tela e no teste.
        prévia = thumbs.load_image_preview(caminho)
        if prévia is not None:
            layout.template_icon(icon_value=prévia.icon_id, scale=PROP_PREVIEW_SCALE)
        else:
            # Arquivo que existe e não vira imagem: dizer isto agora é melhor do
            # que deixar o quadrado vazio passar por "ainda carregando".
            linha = layout.row()
            linha.alert = True
            linha.label(text=_("this file is not an image the program can show"),
                        icon="ERROR")

    # -- referência --------------------------------------------------------
    def _source(self, context):
        """(modo, camadas) da arte que vai virar referência deste prop.

        Camada sem traço NENHUM no frame nunca é escolhida — nem quando pedida
        pelo nome. Renderizá-la geraria um PNG vazio que só seria descoberto
        muito depois, quando outro take reusasse o prop.
        """
        from . import gp

        if self.source == "NONE":
            return "NONE", []
        store = state.get_store()
        take = takefile.current_take_of_file(store) if store else None
        ob = gp.find_take_object(take) if take is not None else None
        if ob is None:
            return "NONE", []

        frame = context.scene.frame_current
        if self.source == "AUTO":
            return gp.prop_reference_source(ob, frame)
        if self.source == "ACTIVE":
            ativa = ob.data.layers.active
            if ativa is not None and gp.layer_has_art(ativa, frame):
                return "ACTIVE", [ativa]
            return "NONE", []
        if self.source == "PROPS":
            camadas = [l for l in gp.props_layers(ob) if gp.layer_has_art(l, frame)]
            return ("PROPS", camadas) if camadas else ("NONE", [])
        com_arte = any(gp.layer_has_art(l, frame) for l in ob.data.layers)
        return ("FRAME", list(ob.data.layers)) if com_arte else ("NONE", [])

    def _art_from_drawing(self, context, prop):
        """Renderiza a arte escolhida para `props/`. Devolve (caminho, modo)."""
        from . import gp

        store = state.require_store()
        modo, camadas = self._source(context)
        if modo == "NONE":
            return "", modo

        ob = gp.find_take_object(takefile.current_take_of_file(store))
        destino = store.prop_art_destination(prop.name)
        if modo == "FRAME":
            gp.render_frame_png(context.scene, ob, destino)
        else:
            gp.render_layers_png(context.scene, ob, camadas, destino)
        return store.paths.rel(destino), modo

    def execute(self, context):
        import shutil

        store = state.require_store()
        prop = Prop(name=self.name.strip() or "Prop", temporary=self.temporary,
                    notes=self.notes)

        if self.reference:
            origem = Path(bpy.path.abspath(self.reference)).expanduser()
            if not origem.is_file():
                self.report({"ERROR"}, _("reference image not found"))
                return {"CANCELLED"}
            # Cópia para dentro do board, como o áudio: a pasta tem que
            # continuar inteira quando viaja de máquina.
            destino = store.prop_reference_destination(prop.name, origem.suffix)
            shutil.copy2(origem, destino)
            prop.reference = store.paths.rel(destino)
        else:
            try:
                desenhada, modo = self._art_from_drawing(context, prop)
            except RuntimeError as exc:  # o render falhou; o prop não se perde
                desenhada, modo = "", "NONE"
                self.report({"WARNING"}, str(exc))
            if desenhada:
                prop.reference = desenhada
                # Recorte do objeto é a arte PROVISÓRIA dele — é o que volta ao
                # canvas em outro take. O quadro inteiro, não: ali o prop está no
                # meio do plano, serve para explicar o pedido e nada mais.
                if modo in ("ACTIVE", "PROPS"):
                    prop.file = desenhada

        store.library.props.append(prop)
        # Com um take aberto, o prop nasce ligado a ele: é ali que o animador
        # percebeu que precisava do objeto, e sem esse vínculo o pedido chega em
        # quem faz arte sem dizer onde o prop aparece.
        aberto = takefile.current_take_of_file(store)
        if aberto is not None and prop.id not in aberto.prop_ids:
            aberto.prop_ids.append(prop.id)
        store.save()

        aviso = ""
        if prop.temporary and prop.reference and self.request:
            from .core.approval import ApprovalError
            from .ops_approval import open_request
            try:
                open_request(context, store, prop)
                store.save()
            except ApprovalError as exc:
                aviso = str(exc)

        sync.sync_all(context)
        if aviso:
            self.report({"WARNING"}, _("prop created; request pending") + f": {aviso}")
        elif prop.request_id:
            self.report({"INFO"}, _("request opened in the approval system"))
        else:
            self.report({"INFO"}, _("prop created") + f": {prop.name}")
        return {"FINISHED"}


class NSB_OT_replace_prop(Operator):
    """RN04: aponta o prop selecionado para a versão final; todos os takes que
    usam o provisório passam a resolver para ela."""

    bl_idname = "nsb.replace_prop"
    bl_label = "Replace with final version"

    final_index: IntProperty(name="Final prop index", default=0, min=0)

    @classmethod
    def poll(cls, context):
        st = context.window_manager.nsb
        return state.has_project() and len(st.props) >= 2

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        store = state.require_store()
        st = context.window_manager.nsb
        props = store.library.props
        if not (0 <= self.final_index < len(props)) or self.final_index == st.prop_index:
            self.report({"ERROR"}, _("pick another prop as the final version"))
            return {"CANCELLED"}
        old = props[st.prop_index]
        old.replaced_by = props[self.final_index].id
        store.save()
        sync.sync_all(context)
        self.report({"INFO"}, f"'{old.name}' → '{props[self.final_index].name}'")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Validacao
# ---------------------------------------------------------------------------

class NSB_OT_validate(Operator):
    bl_idname = "nsb.validate"
    bl_label = "Validate project"
    bl_description = "Runs the PRD rules and lists what blocks the export"

    @classmethod
    def poll(cls, context):
        return state.has_project()

    def execute(self, context):
        store = state.require_store()
        sync.sync_issues(context)
        from .core import validate_project
        issues = validate_project(store.project, store.library, store.paths)
        blocking = blocks_export(issues, store.project.settings.strict_hex_link)
        if blocking:
            self.report({"WARNING"}, f"{len(blocking)} " + _("problem(s) block the export"))
        else:
            self.report({"INFO"}, _("project ready for export"))
        return {"FINISHED"}


CLASSES = (
    NSB_OT_new_project, NSB_OT_open_project, NSB_OT_open_folder,
    NSB_OT_new_scene_folder, NSB_OT_close_episode, NSB_OT_open_board_folder,
    NSB_OT_forget_board,
    NSB_OT_save_project, NSB_OT_close_project,
    NSB_OT_add_episode, NSB_OT_add_scene, NSB_OT_add_take, NSB_OT_remove_take,
    NSB_OT_move_take,
    NSB_OT_import_audio, NSB_OT_remove_audio, NSB_OT_set_audio_start,
    NSB_OT_edit_audio_external, NSB_OT_reload_audio, NSB_OT_set_take_duration,
    NSB_OT_rename_project, NSB_OT_rename_structure,
    NSB_OT_add_character, NSB_OT_link_character_rig, NSB_OT_remove_character,
    NSB_OT_add_prop, NSB_OT_replace_prop,
    NSB_OT_validate,
)


def register():
    apply_context(CLASSES)
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
