"""Ponte com o sistema de aprovação de assets, do lado do Blender.

O trabalho de rede está em `core/approval.py` (puro). Aqui ficam só os
operadores: entrar, ligar o board a um projeto, abrir a pendência do prop
provisório e conferir o que já voltou aprovado.

Regra que vale para todos: **nada de rede sem o artista pedir**. Nenhum handler,
timer ou `draw()` consulta o servidor — desenhar num board não pode travar
porque a internet caiu. Quem fala com a rede é sempre um clique.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator

from . import state, sync
from .core import approval
from .core.approval import ApprovalError
from .core.naming import suggest_project_code
from .props import get_prefs
from .translations import _, apply_context

#: Sessão viva deste processo. Fica em memória (o token vai para as prefs, que
#: são da máquina); some ao fechar o Nuclear, como qualquer login.
SESSION = None

#: Resultado da última conferida, para a UI mostrar sem consultar de novo.
LAST_CHECK = ""

#: Cache dos itens de menu (o Blender não segura as strings devolvidas por um
#: callback de `items` — ver a mesma armadilha em `props.py`).
_ITEMS_CACHE = {}
_EMPTY = [("", "—", "")]


# ---------------------------------------------------------------------------
# Sessão
# ---------------------------------------------------------------------------

def base_url(context) -> str:
    prefs = get_prefs(context)
    return (getattr(prefs, "approval_url", "") or approval.DEFAULT_BASE_URL).strip()


def session(context, required: bool = True):
    """Sessão pronta para uso, reaproveitando o token guardado nas prefs."""
    global SESSION
    if SESSION is not None:
        return SESSION
    prefs = get_prefs(context)
    token = getattr(prefs, "approval_token", "") if prefs else ""
    if token:
        SESSION = approval.Session(base_url=base_url(context), token=token,
                                   user_name=getattr(prefs, "approval_user", ""),
                                   role=getattr(prefs, "approval_role", ""))
        return SESSION
    if required:
        raise ApprovalError("entre no aprovação primeiro")
    return None


def forget_session(context) -> None:
    global SESSION
    SESSION = None
    prefs = get_prefs(context)
    if prefs:
        prefs.approval_token = ""


class _ApprovalOperator(Operator):
    """Base: transforma falha de rede em mensagem, nunca em traceback."""

    bl_options = {"REGISTER"}

    def run(self, context):
        raise NotImplementedError

    def execute(self, context):
        try:
            return self.run(context)
        except ApprovalError as exc:
            # Token vencido: derruba a sessão para o próximo clique pedir senha.
            if "entre de novo" in str(exc) or "entre no aprovação" in str(exc):
                forget_session(context)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class NSB_OT_approval_login(_ApprovalOperator):
    """Entra com o mesmo usuário e senha da intranet."""

    bl_idname = "nsb.approval_login"
    bl_label = "Sign in to approvals"
    bl_description = ("Signs in with the same user and password as the intranet, "
                      "so the board can open pending items there")

    username: StringProperty(name="User", default="")
    password: StringProperty(name="Password", default="", subtype="PASSWORD")

    def invoke(self, context, event):
        prefs = get_prefs(context)
        if prefs and not self.username:
            self.username = prefs.approval_user
        return context.window_manager.invoke_props_dialog(self)

    def run(self, context):
        global SESSION
        nova = approval.login(self.username, self.password,
                              base_url=base_url(context))
        SESSION = nova
        prefs = get_prefs(context)
        if prefs:
            # A SENHA não é guardada em lugar nenhum — só o token que a API
            # devolveu, do mesmo jeito que o app do celular faz.
            prefs.approval_user = self.username
            prefs.approval_token = nova.token
            prefs.approval_role = nova.role
        self.password = ""
        self.report({"INFO"}, _("signed in as") + f" {nova.user_name or self.username}")
        return {"FINISHED"}


class NSB_OT_approval_logout(Operator):
    bl_idname = "nsb.approval_logout"
    bl_label = "Sign out"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        forget_session(context)
        self.report({"INFO"}, _("signed out"))
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Ligar o board a um projeto
# ---------------------------------------------------------------------------

#: Projetos lidos do servidor no último clique. Vive no MÓDULO, não na classe do
#: operador: o Blender recria a classe ao registrar e um atributo pendurado nela
#: some (o callback de `items` levantava AttributeError e o menu ficava vazio).
_FETCHED = []


def _project_items(self, context):
    _ITEMS_CACHE["projects"] = [(p["id"], p["name"], "") for p in _FETCHED] or list(_EMPTY)
    return _ITEMS_CACHE["projects"]


class NSB_OT_pick_approval_project(_ApprovalOperator):
    """Liga este board a um projeto do aprovação e acerta o nome dos arquivos.

    Duas coisas de uma vez porque são a mesma decisão: é o projeto que diz para
    onde vão as pendências e qual sigla abre o nome de cada arquivo entregue.
    """

    bl_idname = "nsb.pick_approval_project"
    bl_label = "Link to a project"
    bl_description = ("Lists the projects from the approval system and links this "
                      "board to one of them")

    project: EnumProperty(name="Project", items=_project_items)
    #: Escape para script/teste: o menu só tem itens depois de o diálogo ter
    #: consultado o servidor, e passar um id direto não caberia nele.
    project_id: StringProperty(default="", options={"HIDDEN"})
    code: StringProperty(
        name="Project code", default="",
        description=("Short code that opens every delivered file name "
                     "(DPE_EP03_C02T05); empty uses the board name"))

    @classmethod
    def poll(cls, context):
        return state.has_project()

    def invoke(self, context, event):
        global _FETCHED
        try:
            _FETCHED = approval.list_projects(session(context))
        except ApprovalError as exc:
            if "entre de novo" in str(exc):
                forget_session(context)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if not _FETCHED:
            self.report({"ERROR"}, _("no project available in the approval system"))
            return {"CANCELLED"}

        store = state.require_store()
        atual = store.project.settings.approval_project_id
        if atual and any(p["id"] == atual for p in _FETCHED):
            self.project = atual
        self.code = store.project.settings.project_code
        return context.window_manager.invoke_props_dialog(self, width=380)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "project")
        layout.prop(self, "code")
        nome = next((p["name"] for p in _FETCHED if p["id"] == self.project), "")
        if not self.code and nome:
            layout.label(text=_("suggestion") + f": {suggest_project_code(nome)}",
                         icon="INFO")

    def run(self, context):
        global _FETCHED
        store = state.require_store()
        if not _FETCHED:
            # Chamado direto (sem passar pelo diálogo), como em teste ou script.
            _FETCHED = approval.list_projects(session(context))
        alvo = self.project_id or self.project
        escolhido = next((p for p in _FETCHED if p["id"] == alvo), None)
        if escolhido is None:
            self.report({"ERROR"}, _("pick a project"))
            return {"CANCELLED"}

        ajustes = store.project.settings
        ajustes.approval_project_id = escolhido["id"]
        ajustes.approval_project_name = escolhido["name"]
        ajustes.project_code = (self.code or suggest_project_code(escolhido["name"])).strip()

        # O asset exige um cliente; o padrão é o primeiro contato do projeto. Sem
        # nenhum, a pendência vai falhar depois com uma mensagem que explica.
        clientes = approval.list_clients(session(context), escolhido["id"])
        if clientes:
            ajustes.approval_client_id = clientes[0]["id"]
            ajustes.approval_client_name = clientes[0]["name"]
        else:
            ajustes.approval_client_id = ajustes.approval_client_name = ""

        # Categoria: se a produção já criou uma para props/referências, as
        # pendências entram lá em vez de ficarem soltas no projeto.
        ajustes.approval_folder_id = ajustes.approval_folder_name = ""
        for pasta in approval.list_folders(session(context), escolhido["id"]):
            if any(p in pasta["name"].lower() for p in ("prop", "refer", "asset")):
                ajustes.approval_folder_id = pasta["id"]
                ajustes.approval_folder_name = pasta["name"]
                break

        store.save()
        sync.sync_all(context)
        self.report({"INFO"}, _("board linked to") + f" {escolhido['name']}")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Pendências
# ---------------------------------------------------------------------------

def _extensao(pendencia) -> str:
    """Extensão da arte baixada.

    Vem do CAMINHO da URL ou do tipo declarado — nunca do nome do asset: um
    nome como "Prop: cenário v1.2" daria a extensão ".2" e o arquivo entraria no
    board sem ser imagem nenhuma.
    """
    import mimetypes
    import urllib.parse

    caminho = urllib.parse.urlparse(pendencia.download_url).path
    sufixo = Path(caminho).suffix.lower()
    if sufixo and len(sufixo) <= 5:
        return sufixo
    tipo = (pendencia.extra or {}).get("fileType") or ""
    return mimetypes.guess_extension(tipo.split(";")[0].strip()) or ".png"


def selected_prop(context):
    store = state.get_store()
    if store is None:
        return None
    st = context.window_manager.nsb
    if 0 <= st.prop_index < len(store.library.props):
        return store.library.props[st.prop_index]
    return None


def pending_props(store):
    """Props provisórios com referência anexada e pendência ainda não aberta."""
    return [p for p in store.library.props
            if p.temporary and p.reference and not p.request_id]


def open_request(context, store, prop) -> str:
    """Abre a pendência de um prop. Devolve o id do asset criado.

    O texto leva o take de origem: quem for criar o prop precisa saber onde ele
    aparece, e essa informação só existe aqui.
    """
    onde = [f"{ep.code or ep.name}/{sc.code or sc.name}/{tk.code or tk.name}"
            for ep, sc, tk in store.project.iter_takes() if prop.id in tk.prop_ids]
    descricao = _("Temporary prop created in the storyboard; needs the final art.")
    if onde:
        descricao += " " + _("Appears in") + ": " + ", ".join(onde[:8])
    if prop.notes:
        descricao += f" — {prop.notes}"

    ajustes = store.project.settings
    pendencia = approval.create_request(
        session(context),
        name=f"Prop: {prop.name}",
        project_id=ajustes.approval_project_id,
        client_id=ajustes.approval_client_id,
        folder_id=ajustes.approval_folder_id,
        reference=store.paths.abs(prop.reference),
        description=descricao)
    prop.request_id = pendencia.asset_id
    prop.request_status = pendencia.status
    prop.request_checked_at = datetime.now().isoformat(timespec="seconds")
    return pendencia.asset_id


class NSB_OT_prop_reference(Operator):
    """Anexa (ou troca) a imagem de referência do prop selecionado."""

    bl_idname = "nsb.prop_reference"
    bl_label = "Attach reference image"
    bl_description = ("Attaches the reference image of the temporary prop — it is "
                      "what goes to the approval system as the request")

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.png;*.jpg;*.jpeg;*.webp",
                                options={"HIDDEN"})
    request: BoolProperty(
        name="Open the request now", default=True,
        description="Opens the pending item in the approval system right away")

    @classmethod
    def poll(cls, context):
        return selected_prop(context) is not None

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        import shutil

        store = state.require_store()
        prop = selected_prop(context)
        origem = Path(bpy.path.abspath(self.filepath)).expanduser()
        if not origem.is_file():
            self.report({"ERROR"}, _("reference image not found"))
            return {"CANCELLED"}

        # A referência é copiada para dentro do board, como o áudio: o projeto
        # tem que continuar inteiro quando a pasta viaja de máquina.
        destino = store.prop_reference_destination(prop.name, origem.suffix)
        shutil.copy2(origem, destino)
        prop.reference = store.paths.rel(destino)
        store.save()

        aviso = ""
        if self.request and prop.temporary and not prop.request_id:
            try:
                open_request(context, store, prop)
                store.save()
            except ApprovalError as exc:
                # Sem rede/login a referência FICA anexada e o pedido espera: a
                # fila local é o que faz isto funcionar sem internet.
                aviso = str(exc)

        sync.sync_all(context)
        if aviso:
            self.report({"WARNING"}, _("reference attached; request pending")
                        + f": {aviso}")
        else:
            self.report({"INFO"}, _("reference attached"))
        return {"FINISHED"}


class NSB_OT_send_requests(_ApprovalOperator):
    """Abre no aprovação todas as pendências que ainda não foram enviadas."""

    bl_idname = "nsb.send_requests"
    bl_label = "Send pending requests"
    bl_description = ("Opens, in the approval system, one pending item per "
                      "temporary prop that has a reference image")

    @classmethod
    def poll(cls, context):
        store = state.get_store()
        return store is not None and bool(pending_props(store))

    def run(self, context):
        store = state.require_store()
        # Sem sessão, falha uma vez com a mensagem certa em vez de repetir o
        # mesmo erro uma vez por prop da fila.
        session(context)
        fila = pending_props(store)
        enviados, falhas = 0, []
        for prop in fila:
            try:
                open_request(context, store, prop)
                enviados += 1
            except ApprovalError as exc:
                falhas.append(f"{prop.name}: {exc}")
        store.save()
        sync.sync_all(context)

        if enviados:
            self.report({"INFO"}, f"{enviados} " + _("request(s) opened"))
        if falhas:
            self.report({"WARNING"}, falhas[0])
            for extra in falhas[1:]:
                print(f"[storyboard] {extra}")
        return {"FINISHED"} if enviados or not falhas else {"CANCELLED"}


class NSB_OT_check_requests(_ApprovalOperator):
    """A volta: lê o estado das pendências e traz a arte aprovada.

    Quando a arte definitiva é aprovada, ela é baixada para dentro do board,
    entra na biblioteca como prop final e o provisório passa a apontar para ele
    (`replaced_by`) — que é o caminho que o resto do add-on já segue.
    """

    bl_idname = "nsb.check_requests"
    bl_label = "Check requests"
    bl_description = ("Reads how the requests are doing in the approval system and "
                      "brings in the art that has been approved")

    @classmethod
    def poll(cls, context):
        store = state.get_store()
        return store is not None and any(p.request_id for p in store.library.props)

    def run(self, context):
        global LAST_CHECK

        store = state.require_store()
        com_pedido = [p for p in store.library.props if p.request_id]
        estados = approval.pending_state(
            session(context), [p.request_id for p in com_pedido],
            project_id=store.project.settings.approval_project_id)

        agora = datetime.now().isoformat(timespec="seconds")
        mudou, resolvidos, sumidos = 0, 0, 0
        for prop in com_pedido:
            pendencia = estados.get(prop.request_id)
            if pendencia is None:
                # Apagada do outro lado: manter o vínculo esconderia do artista
                # que ninguém mais está vendo esse pedido.
                prop.request_status = "MISSING"
                prop.request_checked_at = agora
                sumidos += 1
                continue
            if pendencia.status != prop.request_status:
                mudou += 1
            prop.request_status = pendencia.status
            prop.request_checked_at = agora

            if pendencia.is_done and not prop.replaced_by:
                final = self._trazer_arte(store, prop, pendencia)
                if final is not None:
                    prop.replaced_by = final.id
                    resolvidos += 1

        store.save()
        sync.sync_all(context)

        partes = [f"{len(com_pedido)} " + _("request(s) checked")]
        if resolvidos:
            partes.append(f"{resolvidos} " + _("resolved"))
        if sumidos:
            partes.append(f"{sumidos} " + _("no longer there"))
        LAST_CHECK = ", ".join(partes)
        self.report({"INFO"} if not sumidos else {"WARNING"}, LAST_CHECK)
        return {"FINISHED"}

    def _trazer_arte(self, store, prop, pendencia):
        """Baixa a arte aprovada e cadastra o prop definitivo."""
        from .core.model import Prop

        if not pendencia.download_url:
            return None
        destino = store.prop_art_destination(f"{prop.name}_final")
        sufixo = _extensao(pendencia)
        if sufixo and sufixo != destino.suffix:
            destino = destino.with_suffix(sufixo)
        try:
            approval.download_file(pendencia.download_url, destino)
        except ApprovalError as exc:
            print(f"[storyboard] não deu para baixar {prop.name}: {exc}")
            return None
        final = Prop(name=prop.name, temporary=False,
                     file=store.paths.rel(destino),
                     notes=_("Approved art brought from the approval system"))
        store.library.props.append(final)
        return final


CLASSES = (NSB_OT_approval_login, NSB_OT_approval_logout,
           NSB_OT_pick_approval_project,
           NSB_OT_prop_reference, NSB_OT_send_requests, NSB_OT_check_requests)


def register():
    apply_context(CLASSES)
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
