"""Operadores de export: disparam o worker headless e acompanham o progresso.

O trabalho pesado (render de cada take, FFmpeg, `.kdenlive`) roda num processo
Nuclear separado — ver `export_worker.py`. Aqui só cuidamos de disparar, ler o
progresso e recarregar o projeto quando termina, porque o worker atualiza os
PNGs no `project.json`.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from queue import Empty, Queue

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator

from . import state, sync, takefile
from .translations import _, apply_context
from .core import ProjectStore, scope_basename
from .core.exporter import have_ffmpeg

WORKER = Path(__file__).with_name("export_worker.py")


def nuclear_binary() -> str:
    """Executável do Nuclear em execução — o worker roda na mesma versão."""
    return bpy.app.binary_path or sys.executable


def _pump(pipe, queue: Queue) -> None:
    for line in iter(pipe.readline, ""):
        queue.put(line.rstrip("\n"))
    pipe.close()
    queue.put(None)


class _WorkerOperator(Operator):
    """Base dos operadores que rodam o worker e acompanham por timer."""

    bl_options = {"REGISTER"}

    _process = None
    _queue = None
    _timer = None
    _thread = None
    _last = ""
    _failure = ""
    #: Thread do envio ao aprovação (None enquanto não há envio em curso).
    _sending = None
    _upload_error = ""

    def worker_args(self, context):
        raise NotImplementedError

    @classmethod
    def poll(cls, context):
        return state.has_project()

    def execute(self, context):
        store = state.require_store()

        # O worker lê o disco: o que estiver só na memória precisa ir para lá.
        take = takefile.current_take_of_file(store)
        if take is not None:
            takefile.save_take(store, take)
        else:
            store.save()

        command = [nuclear_binary(), "--background", "--factory-startup",
                   "--python", str(WORKER), "--"] + self.worker_args(context)
        try:
            self._process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1)
        except OSError as exc:
            self.report({"ERROR"}, _("could not start the worker") + f": {exc}")
            return {"CANCELLED"}

        self._queue = Queue()
        self._thread = threading.Thread(target=_pump,
                                        args=(self._process.stdout, self._queue),
                                        daemon=True)
        self._thread.start()

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.3, window=context.window)
        wm.modal_handler_add(self)
        self.report({"INFO"}, _("export running…"))
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type != "TIMER":
            return {"PASS_THROUGH"}

        if self._sending is not None:
            return self._watch_upload(context)

        finished = False
        while True:
            try:
                line = self._queue.get_nowait()
            except Empty:
                break
            if line is None:
                finished = True
                break
            if line.startswith("PROGRESS "):
                parts = line.split(" ", 3)
                self._last = parts[3] if len(parts) > 3 else ""
                context.workspace.status_text_set(
                    f"Storyboard: {self._last} ({parts[1]}/{parts[2]})")
            elif line.startswith("FAILED "):
                self._failure = line[len("FAILED "):]
            else:
                print(f"[export] {line}")

        if not finished:
            return {"RUNNING_MODAL"}
        return self._finish(context)

    def _finish(self, context):
        code = self._process.wait() if self._process else 1

        store = state.get_store()
        if store is not None:
            # O worker gravou os PNGs no project.json: recarrega para a UI ver.
            state.set_store(ProjectStore.load(store.paths.root))
            sync.sync_all(context)

        if code != 0 or self._failure:
            self._cleanup(context)
            self.report({"ERROR"}, self._failure or _("the worker failed") + f" ({code})")
            return {"CANCELLED"}

        # Subir o vídeo é a segunda metade da entrega e pode levar minutos: vai
        # numa thread, com o modal ainda de pé. Fazer o upload aqui dentro
        # deixaria o Nuclear congelado, sem dizer por quê.
        if self.start_upload(context):
            context.workspace.status_text_set(_("Storyboard: sending to approvals…"))
            return {"RUNNING_MODAL"}

        self._cleanup(context)
        self.on_success(context)
        self.report({"INFO"}, self.success_message())
        return {"FINISHED"}

    def _watch_upload(self, context):
        if self._sending.is_alive():
            return {"RUNNING_MODAL"}
        self._sending = None
        self._cleanup(context)
        if self._upload_error:
            self.report({"WARNING"}, self._upload_error)
            return {"FINISHED"}
        self.on_success(context)
        self.report({"INFO"}, self.success_message())
        return {"FINISHED"}

    def start_upload(self, context) -> bool:
        """Gancho: devolve True se pôs uma thread de envio de pé."""
        return False

    def on_success(self, context) -> None:
        """Gancho para o que só faz sentido quando o worker terminou bem."""

    def success_message(self) -> str:
        return _("export finished")

    def _cleanup(self, context) -> None:
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        context.workspace.status_text_set(None)

    def cancel(self, context):
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
        self._cleanup(context)


class NSB_OT_render_take(_WorkerOperator):
    bl_idname = "nsb.render_take"
    bl_label = "Render take drawings"
    bl_description = "Renders the selected take PNGs in a separate process"

    force: BoolProperty(name="Re-render existing", default=False)

    @classmethod
    def poll(cls, context):
        return sync.current_take(context) is not None

    def worker_args(self, context):
        store = state.require_store()
        take = sync.current_take(context)
        args = ["--project", str(store.paths.root), "--takes", take.id]
        if self.force:
            args.append("--force")
        return args

    def success_message(self) -> str:
        return _("drawings rendered")


class NSB_OT_make_thumbs(_WorkerOperator):
    """Desenha as miniaturas que faltam no board, num Nuclear separado.

    O caminho normal é outro: a miniatura sai sozinha quando o take é salvo.
    Este botão existe para o board que veio de antes das miniaturas (ou de outra
    máquina), em que gerar exige abrir um `.nuc` por take — coisa que não pode
    acontecer na sessão de quem está desenhando.
    """

    bl_idname = "nsb.make_thumbs"
    bl_label = "Draw the board"
    bl_description = ("Renders the missing thumbnails of this scene in a separate "
                      "process")

    force: BoolProperty(name="Redo the ones already there", default=False)

    @classmethod
    def poll(cls, context):
        return sync.current_scene(context) is not None

    def worker_args(self, context):
        from . import thumbs

        store = state.require_store()
        cena = sync.current_scene(context)
        alvos = cena.takes if self.force else thumbs.missing(store, cena.takes)
        args = ["--project", str(store.paths.root), "--thumbs",
                "--takes", ",".join(tk.id for tk in alvos)]
        if self.force:
            args.append("--force")
        return args

    def on_success(self, context) -> None:
        from . import thumbs
        # Os ícones já carregados são os de antes: sem esquecer, o board
        # continuaria mostrando os quadros vazios que acabaram de ser gerados.
        thumbs.forget()

    def success_message(self) -> str:
        return _("board drawn")


def _take_example_name(store, takes) -> str:
    """Nome do primeiro arquivo do recorte — o diálogo mostra antes de gerar.

    Ver o nome pronto é o que deixa o animador perceber na hora que a sigla do
    projeto está errada, em vez de descobrir com 20 MP4s já na pasta.
    """
    from .core.naming import take_basename_by_id

    if not takes:
        return ""
    return f"{take_basename_by_id(store.project, takes[0].id) or takes[0].code}.mp4"


def scope_takes(context, scope: str):
    """Takes do recorte pedido e o nome do arquivo que ele gera (RF-13).

    Devolve `(takes, nome)`, com o nome já no padrão do estúdio
    (`DPE_EP03_C02`). Recorte vazio (nenhuma cena selecionada, por exemplo)
    devolve lista vazia, e quem chamou reclama.
    """
    store = state.require_store()
    project = store.project
    if scope == "EPISODE_DIR":
        # As cenas são pastas IRMÃS, cada uma com o board dela: contar os planos
        # delas aqui significaria ler todos os `project.json` vizinhos a cada
        # redesenho de painel — e a pasta costuma estar no Dropbox. Quem varre é
        # o worker, uma vez, quando a entrega começa.
        ep = project.episodes[0] if project.episodes else None
        return [], scope_basename(project, ep)
    if scope == "PROJECT":
        return ([tk for _e, _s, tk in project.iter_takes()],
                scope_basename(project))
    if scope == "EPISODE":
        ep = sync.current_episode(context)
        if ep is None:
            return [], ""
        return ([tk for sc in ep.scenes for tk in sc.takes],
                scope_basename(project, ep))
    if scope == "SCENE":
        ep, sc = sync.current_episode(context), sync.current_scene(context)
        if sc is None:
            return [], ""
        return list(sc.takes), scope_basename(project, ep, sc)
    ep, sc = sync.current_episode(context), sync.current_scene(context)
    take = sync.current_take(context)
    if take is None:
        return [], ""
    return [take], scope_basename(project, ep, sc, take)


class NSB_OT_export_animatic(_WorkerOperator):
    bl_idname = "nsb.export_animatic"
    bl_label = "Export animatic"
    bl_description = ("Renders what is missing and builds the MP4 with burn-in and "
                      "the .kdenlive project, in a separate process")

    scope: EnumProperty(
        name="Scope",
        items=[
            ("EPISODE_DIR", "Whole episode (every scene folder)",
             "Every scene of the episode folder, each one a board, joined into "
             "a single video"),
            ("PROJECT", "Whole project", "Every take, in document order"),
            ("EPISODE", "Selected episode", "Every take of the selected episode"),
            ("SCENE", "Selected scene", "Every take of the selected scene (RF-13)"),
            ("TAKE", "Selected take", "Only the selected take"),
        ],
        default="PROJECT")
    force: BoolProperty(name="Re-render everything", default=False)
    video: BoolProperty(name="MP4 video", default=True)
    kdenlive: BoolProperty(name=".kdenlive project", default=True)
    per_take: BoolProperty(
        name="One MP4 per plan", default=True,
        description=("Also writes one MP4 per take, named PROJECT_EP00_C00T00 — "
                     "this is what the animation team receives"))
    play: BoolProperty(name="Play when finished", default=False,
                       description="Opens the exported video in the system player")
    fmt: EnumProperty(
        name="Format",
        items=[("MP4", "MP4 (review)", "Plays anywhere and is what the approval "
                                       "system takes"),
               ("DNXHR", "DNxHR (editing)", "Cuts frame by frame in DaVinci "
                                            "without converting first")],
        default="MP4")
    upload: BoolProperty(
        name="Send to approvals", default=False,
        description=("Uploads the animatic to the approval system as soon as it "
                     "is built"))
    folder: StringProperty(
        name="Save to", subtype="DIR_PATH", default="",
        description=("Folder the animatic goes to — point it at the production "
                     "folder to deliver straight from here; empty keeps it "
                     "inside the project"))
    takes_folder: StringProperty(
        name="Takes go to", subtype="DIR_PATH", default="",
        description=("Folder the individual takes go to; empty keeps them in "
                     "exports/takes inside the project"))

    _video_path = ""
    _folder = None
    _takes_folder = None
    #: Pendência criada no aprovação quando o envio deu certo.
    _delivered = None

    def invoke(self, context, event):
        # As pastas escolhidas da última vez vêm preenchidas: entregar é
        # trabalho repetido, e digitar o caminho do Dropbox toda vez é onde se
        # erra.
        store = state.get_store()
        if store is not None:
            if not self.folder:
                self.folder = store.project.settings.export_dir
            if not self.takes_folder:
                self.takes_folder = store.project.settings.takes_export_dir
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        """Duas entregas, dois caminhos — cada uma na sua caixa.

        O diálogo automático embaralharia as duas listas de opções; separadas,
        dá para marcar "um arquivo por take" sem se perguntar em qual pasta ele
        vai cair.
        """
        layout = self.layout
        layout.prop(self, "scope")

        box = layout.box()
        box.label(text=_("Animatic (takes joined)"), icon="SEQUENCE")
        linha = box.row(align=True)
        linha.prop(self, "video", toggle=True)
        linha.prop(self, "kdenlive", toggle=True)
        if self.video or self.kdenlive:
            box.prop(self, "folder")

        box = layout.box()
        box.label(text=_("One file per take"), icon="RENDER_RESULT")
        box.prop(self, "per_take", text=_("Also export take by take"))
        if self.per_take:
            box.prop(self, "takes_folder")
            store = state.get_store()
            if store is not None:
                takes, _nome = scope_takes(context, self.scope)
                exemplo = _take_example_name(store, takes)
                if exemplo:
                    box.label(text=f"{len(takes)} " + _("file(s), like") + f" {exemplo}",
                              icon="FILE_MOVIE")

        linha = layout.row(align=True)
        linha.prop(self, "force", toggle=True)
        linha.prop(self, "play", toggle=True)

    def execute(self, context):
        quer_video = self.video or self.per_take
        if quer_video and not have_ffmpeg():
            self.report({"ERROR"}, _("ffmpeg not found in PATH"))
            return {"CANCELLED"}
        if not (self.video or self.kdenlive or self.per_take):
            self.report({"ERROR"}, _("nothing to export: pick at least one file"))
            return {"CANCELLED"}
        if self.scope != "EPISODE_DIR" and not scope_takes(context, self.scope)[0]:
            self.report({"ERROR"}, _("nothing selected to export"))
            return {"CANCELLED"}

        store = state.require_store()
        if self.upload:
            recusa = self._why_cannot_send(context, store)
            if recusa:
                self.report({"ERROR"}, recusa)
                return {"CANCELLED"}
        try:
            self._folder = self._resolve_folder(store, self.folder, "export_dir",
                                                store.paths.exports)
            self._takes_folder = self._resolve_folder(
                store, self.takes_folder, "takes_export_dir",
                store.paths.exports / "takes") if self.per_take else None
        except OSError as exc:
            self.report({"ERROR"}, _("cannot write to this folder") + f": {exc}")
            return {"CANCELLED"}
        return super().execute(context)

    @staticmethod
    def cannot_send(context, store, fmt: str = "MP4", video: bool = True) -> str:
        """Por que este board não consegue entregar no aprovação, ou "".

        Estático porque o PAINEL pergunta a mesma coisa antes de desenhar o
        botão: o artista tem de ver o impedimento antes de clicar, não depois de
        esperar o render inteiro.
        """
        from .props import get_prefs

        if not video:
            return _("to send, the animatic itself has to be built")
        if fmt != "MP4":
            return _("approvals only take MP4 — deliver in MP4 and keep the "
                     "other format for editing")
        prefs = get_prefs(context)
        if not getattr(prefs, "approval_token", ""):
            return _("sign in to approvals first")
        ajustes = store.project.settings
        if not ajustes.approval_project_id:
            return _("this board is not linked to a project yet")
        if not ajustes.approval_client_id:
            return _("no client contact in this project")
        return ""

    def _why_cannot_send(self, context, store) -> str:
        return self.cannot_send(context, store, self.fmt, self.video)

    def _resolve_folder(self, store, escolhida: str, setting: str, padrao: Path) -> Path:
        """Pasta de destino, criada se preciso. Vazio = a pasta padrão dela."""
        escolhida = (escolhida or "").strip()
        if not escolhida:
            destino = padrao
        else:
            # `//` e `~` chegam do seletor de pasta do Blender.
            destino = Path(bpy.path.abspath(escolhida)).expanduser().resolve()
        destino.mkdir(parents=True, exist_ok=True)
        gravavel = destino / ".nsb_write_test"
        gravavel.touch()
        gravavel.unlink()

        # Só grava no projeto o que o artista escolheu de propósito.
        guardado = str(destino) if escolhida else ""
        if getattr(store.project.settings, setting) != guardado:
            setattr(store.project.settings, setting, guardado)
            store.save()
        return destino

    def worker_args(self, context):
        from .core.exporter import output_format

        store = state.require_store()
        takes, name = scope_takes(context, self.scope)
        name = name or "animatic"
        destino = self._folder or store.paths.exports
        formato = output_format(self.fmt)

        if self.scope == "EPISODE_DIR":
            # Uma pasta acima do board estão as cenas irmãs — é ela que o worker
            # varre, exportando cada board e emendando tudo num vídeo só.
            args = ["--episode", str(Path(store.paths.root).parent),
                    "--format", formato.key]
        else:
            args = ["--project", str(store.paths.root), "--format", formato.key]
            if self.scope != "PROJECT":
                args += ["--takes", ",".join(tk.id for tk in takes)]
        if self.force:
            args.append("--force")
        if self.video:
            self._video_path = str(destino / f"{name}{formato.suffix}")
            args += ["--video", self._video_path]
        if self.kdenlive:
            args += ["--kdenlive", str(destino / f"{name}.kdenlive")]
        if self.per_take and self._takes_folder is not None:
            args += ["--per-take-dir", str(self._takes_folder)]
        return args

    # -- entrega no sistema de aprovação -----------------------------------
    def start_upload(self, context) -> bool:
        """Sobe o vídeo recém-montado, numa thread. Devolve se começou."""
        from .core.approval import ApprovalError, deliver_video
        from .ops_approval import session

        if not (self.upload and self._video_path):
            return False
        video = Path(self._video_path)
        if not video.is_file():
            self._upload_error = _("the video was not built; nothing was sent")
            return False

        store = state.require_store()
        ajustes = store.project.settings
        takes, nome = scope_takes(context, self.scope)
        descricao = _("Animatic exported from the storyboard") + \
            f" — {len(takes)} " + _("plan(s)")
        try:
            # A sessão é lida AQUI, na thread principal: `context` e as
            # preferências do add-on não são de mexer fora dela.
            sessao = session(context)
        except ApprovalError as exc:
            self._upload_error = str(exc)
            return False

        self._upload_error = ""
        self._delivered = None

        def _enviar():
            try:
                self._delivered = deliver_video(
                    sessao, name=nome or store.project.name,
                    project_id=ajustes.approval_project_id,
                    client_id=ajustes.approval_client_id,
                    folder_id=ajustes.approval_folder_id,
                    video=video, description=descricao)
            except ApprovalError as exc:
                self._upload_error = _("delivered to the folder, but not sent") \
                    + f": {exc}"
            except OSError as exc:
                self._upload_error = _("delivered to the folder, but not sent") \
                    + f": {exc}"

        self._sending = threading.Thread(target=_enviar, daemon=True)
        self._sending.start()
        return True

    def on_success(self, context) -> None:
        if self.play and self._video_path and Path(self._video_path).is_file():
            bpy.ops.wm.path_open(filepath=self._video_path)

    def success_message(self) -> str:
        partes = []
        if (self.video or self.kdenlive) and self._folder is not None:
            partes.append(_("animatic exported to") + f" {self._folder}")
        if self.per_take and self._takes_folder is not None:
            partes.append(_("takes exported to") + f" {self._takes_folder}")
        if self.upload and self._delivered is not None:
            partes.append(_("sent to approvals") + f": {self._delivered.name}")
        if partes:
            return "; ".join(partes)
        store = state.get_store()
        return (_("animatic exported to") + f" {store.paths.exports}") if store else _("animatic exported")


class NSB_OT_watch_scene(Operator):
    """RF-13: assistir a cena inteira, takes emendados na ordem."""

    bl_idname = "nsb.watch_scene"
    bl_label = "Watch scene"
    bl_description = ("Builds the animatic of the selected scene only and opens it "
                      "in the player")

    @classmethod
    def poll(cls, context):
        return state.has_project() and sync.current_scene(context) is not None

    def execute(self, context):
        # Sem `.kdenlive`: isto é prévia, não entrega. O worker reaproveita os
        # PNGs já renderizados, então rever a cena depois de um ajuste de
        # timing custa só a montagem do vídeo.
        # O export segue modal no operador chamado; aqui já terminamos.
        # `per_take=False` explícito: o operador guarda o que foi marcado da
        # última vez, e rever a cena não é hora de gerar 20 arquivos.
        bpy.ops.nsb.export_animatic("EXEC_DEFAULT", scope="SCENE",
                                    video=True, kdenlive=False, per_take=False,
                                    play=True)
        return {"FINISHED"}


class NSB_OT_open_exports(Operator):
    bl_idname = "nsb.open_exports"
    bl_label = "Open exports folder"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return state.has_project()

    def execute(self, context):
        store = state.require_store()
        # A pasta que interessa é para onde o animatic foi de verdade.
        escolhida = store.project.settings.export_dir
        destino = Path(escolhida) if escolhida else store.paths.exports
        destino.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.path_open(filepath=str(destino))
        return {"FINISHED"}


CLASSES = (NSB_OT_render_take, NSB_OT_make_thumbs, NSB_OT_export_animatic,
           NSB_OT_watch_scene, NSB_OT_open_exports)


def register():
    apply_context(CLASSES)
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
