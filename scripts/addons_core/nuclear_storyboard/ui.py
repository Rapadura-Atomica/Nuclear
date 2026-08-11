"""Interface do add-on na sidebar (N) da 3D View, aba "Storyboard".

Um painel só, na ordem em que o board artist trabalha: escolher o take →
desenhar → encaixar o áudio → exportar. Tudo que é ajuste fino, diagnóstico ou
cadastro vive no painel "More options", fechado por padrão — quem está
desenhando não deveria precisar abrir nunca.

Regras de linguagem desta tela: nada de sigla de regra (RN02), nada de nome de
subsistema do Blender (VSE, keyframe, exposure) e nenhum rótulo que só caiba
truncado nos 280px da sidebar — botão largo vira coluna, botão pequeno vira
ícone com tooltip.

As strings estão em inglês porque é a partir do inglês que o Blender traduz; o
português vive em `translations.py`. Texto montado em tempo de execução passa
por `_()`.
"""

from __future__ import annotations

import bpy
from bpy.types import Panel, UIList

from . import state, sync
from .core import take_duration
from .core.rules import MIN_DRAWINGS
from .translations import _, apply_context

CATEGORY = "Storyboard"


class NSB_UL_characters(UIList):
    """Nome, rig e a COR — clicável, que abre o seletor do Nuclear.

    O hexadecimal saiu da lista: ele é como o pipeline guarda a cor, não como
    uma pessoa a escolhe. Quem precisar do código exato o encontra dentro do
    próprio seletor, no campo Hex.
    """

    def draw_item(self, context, layout, data, item, icon, active_data, active_prop, index=0, flt_flag=0):
        row = layout.row(align=True)
        amostra = row.row()
        amostra.scale_x = 0.35
        amostra.prop(item, "color", text="")
        row.label(text=item.name, icon="OUTLINER_OB_ARMATURE" if item.linked else "ERROR")


#: Como cada estado da pendência aparece na lista de props. A chave é o status
#: que o sistema de aprovação usa; "WAITING" é local (referência anexada, pedido
#: ainda não aberto). O que o artista precisa saber é só: pedi? andou? chegou?
REQUEST_LOOK = {
    "WAITING": ("to send", "TIME"),
    "DRAFT": ("asked", "CHECKMARK"),
    "PENDING_PRODUCER": ("with the producer", "CHECKMARK"),
    "PRODUCER_APPROVED": ("with the producer", "CHECKMARK"),
    "PENDING_CLIENT": ("with the client", "CHECKMARK"),
    "IN_REVIEW": ("with the client", "CHECKMARK"),
    "CLIENT_CHANGES": ("changes asked", "ERROR"),
    "CHANGES_REQUESTED": ("changes asked", "ERROR"),
    "APPROVED": ("art ready", "SOLO_ON"),
    "REJECTED": ("turned down", "ERROR"),
    "MISSING": ("no longer there", "ERROR"),
}


class NSB_UL_props(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_prop, index=0, flt_flag=0):
        row = layout.row(align=True)
        row.label(text=item.name, icon="IMAGE_DATA" if item.has_art else "MESH_DATA")
        direita = row.row(align=True)
        direita.alignment = "RIGHT"
        if item.resolved:
            direita.label(text=_("final art in"), icon="SOLO_ON")
        elif item.request_status:
            rotulo, icone = REQUEST_LOOK.get(item.request_status,
                                             (item.request_status, "TIME"))
            direita.label(text=_(rotulo), icon=icone)
        elif item.temporary:
            direita.label(text=_("temporary"), icon="TIME")


class _Base:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY


# ---------------------------------------------------------------------------
# As cenas vizinhas
#
# Uma cena é uma PASTA (`.../EP13/1 - Thumbs/CENA01`), então as cenas do
# episódio são as pastas ao lado. Trocar de cena é entrar na pasta do lado — e
# isso passou a acontecer dentro do add-on, sem o navegador de arquivos.
#
# Ler o disco a cada redesenho de painel sairia caro (a pasta costuma estar no
# Dropbox): a lista é relida a cada poucos segundos. Cena criada agora aparece
# no redesenho seguinte, porque quem a cria pede a lista fresca.
# ---------------------------------------------------------------------------

SCENES_TTL = 5.0
_SCAN_CACHE = {}


def _scan(chave, produzir, fresco: bool = False):
    import time

    agora = time.monotonic()
    quando, valor = _SCAN_CACHE.get(chave, (0.0, None))
    if fresco or valor is None or agora - quando > SCENES_TTL:
        valor = produzir()
        _SCAN_CACHE[chave] = (agora, valor)
    return valor


def scene_neighbours(store, fresco: bool = False):
    """Cenas do episódio, vistas de dentro de um board (as pastas vizinhas)."""
    from .core import scene_folders

    raiz = str(store.paths.root)
    return _scan(("vizinhas", raiz), lambda: scene_folders(raiz), fresco)


def episode_scene_list(pasta, fresco: bool = False):
    """Cenas dentro da pasta do episódio, vistas de fora (nenhum board aberto)."""
    from .core import episode_scenes

    return _scan(("episodio", str(pasta)), lambda: episode_scenes(pasta), fresco)


def _scene_icon(pasta, atual=None) -> str:
    if atual is not None and pasta == atual:
        return "CHECKMARK"
    # Pasta de cena ainda sem board: entrar nela começa um.
    return "SEQUENCE" if (pasta / "project.json").is_file() else "ADD"


# ---------------------------------------------------------------------------
# O painel do artista
# ---------------------------------------------------------------------------

class NSB_PT_storyboard(_Base, Panel):
    bl_idname = "NSB_PT_storyboard"
    bl_label = "Storyboard"

    def draw(self, context):
        from . import takefile
        layout = self.layout
        st = context.window_manager.nsb
        store = state.get_store()

        if store is None:
            self._draw_no_project(layout, st)
            return

        open_take = takefile.current_take_of_file(store)
        selected = sync.current_take(context)
        has_takes = any(True for _e, _s, _t in store.project.iter_takes())

        self._draw_header(layout, store, st, has_takes)
        self._draw_navigation(context, layout, st, store, selected, open_take)
        if open_take is not None:
            self._draw_take(context, layout, store, open_take)
        # Entregar tem painel próprio, logo abaixo: aqui é o lugar de desenhar.

    # -- pedaços -----------------------------------------------------------
    def _draw_no_project(self, layout, st):
        """Primeira tela: uma pasta e os boards de ontem. Nada a preencher.

        Antes eram dois campos de texto e dois botões ("abrir" e "criar"), e o
        artista tinha de saber de antemão se aquela pasta já era um board. É a
        mesma pergunta nos dois casos — escolher a pasta —, então virou um botão
        só: tem board ali, abre; não tem, começa um.

        Com um EPISÓDIO aberto (a pasta que guarda as cenas), a tela é outra: as
        cenas que existem ali e o botão de criar a próxima.
        """
        from pathlib import Path

        from .props import recent_boards

        pasta_do_ep = (st.episode_dir or "").strip()
        if pasta_do_ep and Path(pasta_do_ep).is_dir():
            self._draw_episode(layout, Path(pasta_do_ep))
            return

        col = layout.column(align=True)
        col.scale_y = 1.5
        col.operator("nsb.open_folder", icon="FILE_FOLDER")

        # O caminho da cena costuma chegar copiado do Dropbox na web; abrir por
        # ele poupa reencontrar a mesma pasta nível por nível.
        linha = layout.row(align=True)
        linha.prop(st, "folder_link", text="", icon="URL")
        atalho = linha.row(align=True)
        atalho.operator_context = "EXEC_DEFAULT"
        atalho.enabled = bool(st.folder_link.strip())
        atalho.operator("nsb.open_folder", text="", icon="PLAY").path = st.folder_link

        recentes = recent_boards()
        if not recentes:
            return
        layout.label(text=_("Lately") + ":")
        col = layout.column(align=True)
        # EXEC_DEFAULT: o caminho já está escolhido, o navegador de pastas só
        # perguntaria de novo o que a linha clicada acabou de responder.
        col.operator_context = "EXEC_DEFAULT"
        for entry in recentes:
            row = col.row(align=True)
            op = row.operator("nsb.open_folder", text=entry.get("name") or entry["path"],
                              icon="SEQUENCE")
            op.path = entry["path"]
            op = row.operator("nsb.forget_board", text="", icon="X")
            op.path = entry["path"]

    def _draw_episode(self, layout, pasta):
        """O episódio aberto: as cenas que existem na pasta e a próxima.

        É por aqui que o animador entra — ele abre `.../EP13/1 - Thumbs`, vê o
        que já existe e cria a cena que vai desenhar. O add-on fica sabendo do
        projeto, do episódio e das cenas de uma vez só, porque as três coisas
        estão no caminho.
        """
        cabeçalho = layout.row(align=True)
        cabeçalho.label(text=pasta.name, icon="SEQUENCE")
        cabeçalho.operator("nsb.close_episode", icon="X", text="")
        layout.label(text=str(pasta.parent.name) + " · " + pasta.name, icon="FILE_FOLDER")

        cenas = episode_scene_list(pasta)
        if cenas:
            col = layout.column(align=True)
            col.operator_context = "EXEC_DEFAULT"
            for cena in cenas:
                op = col.operator("nsb.open_folder", text=cena.name,
                                  icon=_scene_icon(cena))
                op.path = str(cena)
        else:
            layout.label(text=_("no scene in this folder yet"), icon="INFO")

        col = layout.column(align=True)
        col.scale_y = 1.5
        col.operator("nsb.new_scene_folder", icon="ADD")

    def _draw_header(self, layout, store, st, has_takes):
        row = layout.row(align=True)
        row.label(text=store.project.name, icon="SEQUENCE")
        # O lápis ao lado do nome, e não escondido na entrega: o nome saiu da
        # pasta na criação do board e é aqui que o animador o vê errado — ele
        # vai escrito no burning de todo quadro.
        row.operator("nsb.rename_project", icon="GREASEPENCIL", text="")
        # A pasta é a resposta para "onde isto está indo parar?" — o add-on
        # criou `takes/` sozinho lá dentro e é ele quem sabe o caminho.
        row.operator("nsb.open_board_folder", icon="FILE_FOLDER", text="")
        row.operator("nsb.save_project", icon="FILE_TICK", text="")
        row.operator("nsb.close_project", icon="X", text="")
        if st.error_count and has_takes:
            row = layout.row()
            row.alert = True
            plural = _("thing to fix") if st.error_count == 1 else _("things to fix")
            row.label(text=f"{st.error_count} {plural}", icon="ERROR")

    def _draw_navigation(self, context, layout, st, store, selected, open_take):
        """Onde o board está e os takes. Episódio e cena não se escolhem.

        Os dois vieram da pasta que o artista abriu (`.../EP06/CENA03`), então
        aqui eles são INFORMAÇÃO — uma linha escrita, com o lápis ao lado para
        corrigir o que o caminho não soube dizer. Os menus só voltam no board
        que tem mais de um episódio ou mais de uma cena, que é o board antigo:
        ali eles ainda escolhem alguma coisa.
        """
        if not st.episodes:
            col = layout.column(align=True)
            col.scale_y = 1.3
            col.operator("nsb.add_episode", icon="ADD")
            return

        if self._one_scene_board(store):
            self._draw_context_line(layout, st, store)
            self._draw_scenes(layout, store)
        else:
            row = layout.row(align=True)
            row.prop(st, "episode_menu", text="")
            if not st.scenes:
                row.operator("nsb.add_episode", icon="ADD", text="")
                col = layout.column(align=True)
                col.scale_y = 1.3
                col.operator("nsb.add_scene", icon="ADD")
                return
            row.prop(st, "scene_menu", text="")
            row.operator("nsb.add_episode", icon="ADD", text="")
            row.operator("nsb.add_scene", icon="SEQ_STRIP_DUPLICATE", text="")
            # O código digitado errado no começo do board seguia para o nome de
            # todos os arquivos entregues; o lápis é a saída.
            row.operator("nsb.rename_structure", icon="GREASEPENCIL", text="")

        if not st.scenes:
            col = layout.column(align=True)
            col.scale_y = 1.3
            col.operator("nsb.add_scene", icon="ADD")
            return

        self._draw_takes(context, layout, st, store, open_take)

        if selected is None:
            return

        # Clicar no take já entra nele, então este botão não faz parte do
        # caminho normal: ele só aparece na única situação em que a seleção não
        # passou por um clique — board recém-aberto, com um take apontado e
        # nenhum canvas na tela.
        if open_take is None or open_take.id != selected.id:
            col = layout.column(align=True)
            col.scale_y = 1.5
            col.operator("nsb.open_take", icon="GREASEPENCIL",
                         text=_("Draw") + f" {selected.code}")

    def _draw_takes(self, context, layout, st, store, open_take):
        """Os takes da cena — SÓ onde o board não tem coluna própria.

        A grade saiu daqui: ela agora é a aba `Storyboard` do Properties, que
        ocupa a área inteira de um editor em vez de disputar os 280px da
        sidebar com o resto da bancada (`boardpanel`). O que fica nesta tela é
        o trabalho — cena, biblioteca, entrega e ajustes.

        No Nuclear sem a aba (build anterior, ou Blender de fábrica) a grade
        continua aqui: atualizar o add-on antes do Nuclear não pode deixar o
        artista sem board nenhum.
        """
        from . import boardpanel

        if boardpanel.tab_available():
            self._draw_board_hint(context, layout, store)
            return

        cena = sync.current_scene(context)
        takes = list(cena.takes) if cena is not None else []
        boardpanel.draw_take_column(layout, context, store, st, takes, open_take)

    def _draw_board_hint(self, context, layout, store):
        """Quantos planos a cena tem, e onde eles são vistos.

        Sem esta linha, a bancada de um board cheio fica igual à de um board
        vazio — e quem nunca abriu a aba não descobre que ela existe.
        """
        cena = sync.current_scene(context)
        takes = list(cena.takes) if cena is not None else []
        linha = layout.row(align=True)
        linha.label(text=f"{len(takes)} " + _("takes in the Storyboard tab"),
                    icon="SEQUENCE")
        linha.operator("nsb.add_take", icon="ADD", text="")

    @staticmethod
    def _one_scene_board(store) -> bool:
        """O board é de uma cena só — o caso normal desde que a pasta manda."""
        episodios = store.project.episodes
        return len(episodios) == 1 and len(episodios[0].scenes) <= 1

    def _draw_context_line(self, layout, st, store):
        """`EP06 · CENA03`, com o lápis. É o que a pasta disse, escrito de volta."""
        episodio = st.episodes[st.episode_index] if st.episodes else None
        cena = st.scenes[st.scene_index] if st.scenes else None
        partes = [item.code or item.name for item in (episodio, cena) if item is not None]
        texto = " · ".join(p for p in partes if p) or "—"

        row = layout.row(align=True)
        row.label(text=texto, icon="SEQUENCE")
        row.operator("nsb.rename_structure", icon="GREASEPENCIL", text="")

    def _draw_scenes(self, layout, store):
        """As cenas do episódio, ESCRITAS — uma seção, não um botão de menu.

        As cenas do episódio são as pastas vizinhas à do board, e trocar de cena
        é entrar na pasta do lado. Isso era um menu: um botão que só dizia o nome
        da cena aberta e escondia as outras atrás de um clique. Agora a seção é
        como a do take — a lista está na tela, e o artista vê de uma vez quantas
        cenas o episódio tem, em quais já se desenhou (`SEQUENCE`), qual é a
        aberta (`CHECKMARK`) e qual pasta ainda vai virar board (`ADD`).

        Criar a próxima cena mora aqui pelo mesmo motivo: é parte de transitar
        pelo episódio, e no menu antigo ela sumia quando havia uma cena só.
        """
        from pathlib import Path

        atual = Path(store.paths.root)
        vizinhas = scene_neighbours(store)

        box = layout.box()
        row = box.row(align=True)
        row.label(text=_("Scenes in this episode"), icon="SEQUENCE")
        row.operator("nsb.new_scene_folder", icon="ADD", text="")

        col = box.column(align=True)
        # EXEC_DEFAULT: a pasta clicada já é a resposta; o navegador de pastas
        # perguntaria de novo.
        col.operator_context = "EXEC_DEFAULT"
        for pasta in vizinhas:
            op = col.operator("nsb.open_folder", text=pasta.name,
                              icon=_scene_icon(pasta, atual))
            op.path = str(pasta)

    def _draw_take(self, context, layout, store, take):
        from . import gp

        ob = gp.find_take_object(take)

        box = layout.box()
        row = box.row(align=True)
        row.label(text=take.code, icon="GREASEPENCIL")
        row.label(text=f"{take_duration(take):.1f}s")
        row.operator("nsb.save_take", icon="FILE_TICK", text="")

        # ── desenhos ──
        row = box.row(align=True)
        row.label(text=_("Drawings"))
        row.operator("nsb.add_drawing", icon="ADD", text="")
        row.operator("nsb.remove_drawing", icon="REMOVE", text="")

        if ob is not None:
            frames = gp.drawing_frames(ob)
            grid = box.grid_flow(columns=5, align=True)
            for i, number in enumerate(frames, start=1):
                op = grid.operator("nsb.goto_drawing", text=f"{i}",
                                   depress=(number == context.scene.frame_current))
                op.frame = number

        if len(take.drawings) < MIN_DRAWINGS:
            row = box.row()
            row.alert = True
            row.label(text=_("no drawing yet"), icon="INFO")

        # Onde o take termina é decisão do artista, não de uma regra: ele anda
        # até o quadro do corte e manda partir.
        col = box.column(align=True)
        col.enabled = context.scene.frame_current > 1
        col.operator("nsb.split_take", icon="MOD_EDGESPLIT")

        # ── áudio ──
        row = box.row(align=True)
        row.label(text=_("Audio"))
        row.operator("nsb.import_audio", icon="ADD", text="")

        if not take.audios:
            box.label(text=_("no dialogue yet"), icon="INFO")
        self._draw_audio_clips(box, take)

        # Arte de outro take dentro deste arquivo aparece na cena e no render:
        # é raro, mas quando acontece o artista precisa ver na hora.
        foreign = gp.foreign_take_objects(take)
        if foreign:
            row = box.row()
            row.alert = True
            row.label(text=_("there is art from another take here"), icon="ERROR")
            box.operator("nsb.clean_foreign", icon="TRASH")

    def _draw_audio_clips(self, box, take):
        from . import audioedit

        watched = audioedit.watched_ids()
        for i, audio in enumerate(take.audios):
            row = box.row(align=True)
            # Clipe aberto no editor externo ganha o ícone de vigia: é a única
            # pista de que o Nuclear vai recarregar sozinho quando ele salvar.
            row.label(text=audio.name,
                      icon="RADIOBUT_ON" if audio.id in watched else "SOUND")
            row.label(text=f"{audio.start:.1f}→{audio.end:.1f}s")
            op = row.operator("nsb.edit_audio_external", icon="FILE_SOUND", text="")
            op.index = i
            op = row.operator("nsb.reload_audio", icon="FILE_REFRESH", text="")
            op.index = i
            op = row.operator("nsb.set_audio_start", icon="TRACKING", text="")
            op.index = i
            op = row.operator("nsb.remove_audio", icon="X", text="")
            op.index = i

        if audioedit.LAST_MESSAGE:
            box.label(text=_("reloaded from the editor") + f": {audioedit.LAST_MESSAGE}",
                      icon="CHECKMARK")


# ---------------------------------------------------------------------------
# Tudo que o artista não precisa ver para desenhar
# ---------------------------------------------------------------------------

class NSB_PT_more(_Base, Panel):
    """Seis botões, no máximo. Tudo aqui é coisa que se faz de vez em quando.

    O que existia antes e sumiu daqui não virou opção escondida — deixou de
    existir: montar e ler a timeline de áudio acontece ao abrir e ao salvar o
    take, o timing arrastado na dopesheet é guardado no salvar, e a trava do
    pincel cinza fica sempre ligada (é regra do projeto, não preferência).
    Render e validação também saíram: exportar já renderiza o que falta e já
    trava quando há erro, e o contador de erros vive no painel de cima.
    """

    bl_idname = "NSB_PT_more"
    bl_parent_id = "NSB_PT_storyboard"
    bl_label = "More options"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return state.has_project()

    def draw(self, context):
        from . import gp, takefile
        layout = self.layout
        store = state.require_store()
        take = takefile.current_take_of_file(store)
        ob = gp.find_take_object(take) if take is not None else None

        # A camada de personagem e o envio de prop saíram daqui: os dois agem
        # sobre o item SELECIONADO na biblioteca, e agora acontecem lá — o
        # personagem no clique, o prop no "Novo prop", que já usa o desenho.
        col = layout.column(align=True)
        if take is not None:
            col.operator("nsb.apply_exposures", icon="MOD_TIME")
            col.operator("nsb.set_take_duration", icon="TIME")

        # O que se desenha por cima da tela é preferência de quem está olhando.
        layout.prop(context.window_manager.nsb, "show_take_overlay")

        # Só aparece quando há o que consertar: com a trava ligada o normal é
        # nunca haver.
        if ob is not None:
            problems = gp.bg_violations(ob)
            if problems:
                row = layout.row()
                row.alert = True
                row.label(text=f"{len(problems)} " + _("colour(s) in the background"),
                          icon="ERROR")
                layout.operator("nsb.fix_bg_grayscale", icon="MODIFIER")


class NSB_PT_library(_Base, Panel):
    """Cadastro de personagens e props — trabalho de produção, não de desenho.

    Painel próprio (e fechado) porque é outra tarefa, feita uma vez por
    episódio: quem está desenhando não abre isto.
    """

    bl_idname = "NSB_PT_library"
    bl_parent_id = "NSB_PT_storyboard"
    bl_label = "Library"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return state.has_project()

    def draw(self, context):
        from . import ops_approval

        layout = self.layout
        st = context.window_manager.nsb
        store = state.require_store()

        # Cada cena é um board, mas o elenco é do EPISÓDIO: quando a biblioteca
        # mora fora desta pasta, quem cadastra aqui cadastra para todas as
        # cenas — e isso precisa estar escrito, senão parece que o personagem
        # some ao trocar de cena.
        if store.project.settings.library_path:
            layout.label(text=_("Shared with the other scenes"), icon="LINKED")

        # Clicar no personagem JÁ é "vou desenhar este agora" — a camada dele
        # fica ativa e o pincel na cor dele. Não há botão para confirmar a
        # escolha que o clique já fez; ao lado da lista fica só o cadastro.
        layout.label(text=_("Characters (colour -> rig)"))
        row = layout.row()
        row.template_list("NSB_UL_characters", "", st, "characters", st, "character_index", rows=3)
        side = row.column(align=True)
        side.operator("nsb.add_character", icon="ADD", text="")
        side.operator("nsb.remove_character", icon="REMOVE", text="")
        side.operator("nsb.link_character_rig", icon="LINKED", text="")

        layout.label(text=_("Props"))
        row = layout.row()
        row.template_list("NSB_UL_props", "", st, "props", st, "prop_index", rows=3)
        side = row.column(align=True)
        side.operator("nsb.add_prop", icon="ADD", text="")
        side.operator("nsb.prop_reference", icon="IMAGE_REFERENCE", text="")
        side.operator("nsb.replace_prop", icon="FILE_REFRESH", text="")
        layout.operator("nsb.place_prop", icon="IMPORT")

        self._draw_requests(layout, store, ops_approval)

    def _draw_requests(self, layout, store, ops_approval):
        """Pendências: só o que precisa de ação, nunca um "está tudo certo".

        A fila local (referência anexada, pedido não aberto) aparece porque é a
        única pista de que algo ficou por enviar — sem rede, o pedido espera.
        """
        na_fila = len(ops_approval.pending_props(store))
        com_pedido = [p for p in store.library.props if p.request_id]

        col = layout.column(align=True)
        if na_fila:
            linha = col.row()
            linha.alert = True
            linha.label(text=f"{na_fila} " + _("prop(s) still to request"), icon="TIME")
            col.operator("nsb.send_requests", icon="EXPORT")
        if com_pedido:
            col.operator("nsb.check_requests", icon="FILE_REFRESH")
        if ops_approval.LAST_CHECK:
            col.label(text=ops_approval.LAST_CHECK, icon="INFO")


class NSB_PT_delivery(_Base, Panel):
    """Entregar: o que, para onde, e o botão. Nada mais na tela do dia a dia.

    Antes a entrega estava partida em dois lugares — o botão de exportar no
    painel de cima, com um diálogo de oito opções, e a sigla do projeto num
    painel "Entrega" que não entregava nada. O combinado da produção (formato,
    o que acompanha, as pastas) desceu para o subpainel "Como entregar", que se
    ajusta uma vez por board; aqui fica só o ato de entregar.
    """

    bl_idname = "NSB_PT_delivery"
    bl_parent_id = "NSB_PT_storyboard"
    bl_label = "Delivery"

    @classmethod
    def poll(cls, context):
        return state.has_project()

    def draw(self, context):
        from .core import take_duration
        from .core.exporter import have_ffmpeg, output_format
        from .ops_export import NSB_OT_export_animatic, scope_takes

        layout = self.layout
        st = context.window_manager.nsb
        store = state.require_store()
        ajustes = store.project.settings

        layout.label(text=_("What goes in this delivery") + ":")
        layout.prop(st, "delivery_scope", text="")

        takes, nome = scope_takes(context, st.delivery_scope)
        formato = output_format(st.delivery_format)
        if not takes:
            layout.label(text=_("nothing selected to deliver"), icon="INFO")
            return

        # O que vai sair, escrito antes de sair: nome do arquivo, quantos planos
        # e quanto tempo. É por aqui que se percebe a sigla errada — e não com
        # vinte arquivos já na pasta da produção.
        caixa = layout.box()
        linha = caixa.row(align=True)
        linha.label(text=f"{nome}{formato.suffix}", icon="FILE_MOVIE")
        segundos = sum(take_duration(tk) for tk in takes)
        caixa.label(text=f"{len(takes)} " + _("plan(s)") + f" · {segundos:.1f}s")
        # Take a take vem ligado, e sair calado seria pior do que não sair: são
        # mais quinze arquivos na pasta da produção. Escrito com o nome de um
        # deles, que é como o animador reconhece o que vai receber.
        if st.delivery_per_take:
            from .ops_export import _take_example_name

            exemplo = _take_example_name(store, takes)
            texto = f"+ {len(takes)} " + _("one per plan")
            if exemplo:
                texto += f", " + _("like") + f" {exemplo}"
            caixa.label(text=texto, icon="RENDER_RESULT")

        para_pasta = st.delivery_target in {"FOLDER", "BOTH"}
        para_aprovacao = st.delivery_target in {"APPROVAL", "BOTH"}
        # Combo sem rótulo é adivinhação: "Uma pasta" não diz que a pergunta é
        # para ONDE a entrega vai — a pasta da produção, o sistema em que o
        # produtor revisa, ou os dois.
        layout.label(text=_("Where this delivery goes") + ":")
        layout.prop(st, "delivery_target", text="")

        # As pastas na tela principal, e não escondidas em "Como entregar": o
        # animador cola aqui o caminho da produção (o Dropbox do episódio) e é
        # a pergunta que ele responde toda vez que entrega em lugar novo.
        # Rótulo EM CIMA de cada campo: na coluna de rótulos da sidebar, "Pasta
        # dos planos" sairia truncado — e um campo de caminho sem rótulo não diz
        # qual dos dois vídeos vai cair nele.
        if para_pasta:
            col = layout.column(align=True)
            col.label(text=_("The animatic (everything joined) goes to") + ":",
                      icon="SEQUENCE")
            col.prop(st, "delivery_dir", text="")
            if not st.delivery_dir:
                col.label(text=_("empty: stays in exports, inside the board"),
                          icon="INFO")
            if st.delivery_per_take:
                col = layout.column(align=True)
                col.label(text=_("The plans, one file each, go to") + ":",
                          icon="RENDER_RESULT")
                col.prop(st, "delivery_takes_dir", text="")
                if not st.delivery_takes_dir:
                    # Sem isto, o artista aponta a pasta da produção, entrega, e
                    # os quinze arquivos por plano ficam dentro do board.
                    col.label(text=_("empty: stay in exports/takes, inside the "
                                     "board"), icon="INFO")

        impedimento = ""
        if para_aprovacao:
            impedimento = NSB_OT_export_animatic.cannot_send(
                context, store, st.delivery_format, video=True)
            if impedimento:
                linha = layout.row()
                linha.alert = True
                linha.label(text=impedimento, icon="ERROR")
            else:
                layout.label(text=_("Goes to") + f": {ajustes.approval_project_name}",
                             icon="URL")

        col = layout.column(align=True)
        col.scale_y = 1.5
        col.enabled = not impedimento and have_ffmpeg()
        # EXEC_DEFAULT: as escolhas já estão na tela, então o botão entrega — não
        # abre outro diálogo para perguntar de novo o que ele acabou de ler.
        col.operator_context = "EXEC_DEFAULT"
        op = col.operator("nsb.export_animatic", icon="EXPORT", text=_("Deliver"))
        op.scope = st.delivery_scope
        op.fmt = st.delivery_format
        op.video = True
        op.kdenlive = st.delivery_kdenlive and para_pasta
        op.per_take = st.delivery_per_take
        op.upload = para_aprovacao
        op.play = False
        op.force = False
        op.folder = st.delivery_dir
        op.takes_folder = st.delivery_takes_dir

        if not have_ffmpeg():
            linha = layout.row()
            linha.alert = True
            linha.label(text=_("ffmpeg not found in PATH"), icon="ERROR")
        if st.error_count:
            # O contador é do BOARD inteiro, e o recorte pode nem incluir o take
            # quebrado: dizer só "1 coisa para resolver" aqui faria parecer que
            # esta entrega está travada quando ela vai sair normalmente.
            linha = layout.row()
            linha.alert = True
            linha.label(text=f"{st.error_count} " + _("thing(s) to fix in the board"),
                        icon="ERROR")

        linha = layout.row(align=True)
        linha.operator("nsb.watch_scene", icon="PLAY")
        if para_pasta:
            linha.operator("nsb.open_exports", icon="FILE_FOLDER", text="")


class NSB_PT_delivery_setup(_Base, Panel):
    """O combinado da produção: como o arquivo sai e como ele se chama.

    Fechado por padrão porque se ajusta uma vez por board — e é justamente o que
    entulhava o diálogo de export toda vez que alguém queria só entregar.
    """

    bl_idname = "NSB_PT_delivery_setup"
    bl_parent_id = "NSB_PT_delivery"
    bl_label = "How to deliver"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return state.has_project()

    def draw(self, context):
        from .core.naming import project_code
        from .props import get_prefs

        layout = self.layout
        st = context.window_manager.nsb
        store = state.require_store()
        ajustes = store.project.settings

        layout.prop(st, "delivery_format", text="")
        col = layout.column(align=True)
        col.prop(st, "delivery_kdenlive")
        col.prop(st, "delivery_per_take")
        # As duas pastas saíram daqui e foram para a tela de entrega: o caminho
        # é a pergunta que se responde na hora de entregar, não o combinado que
        # se ajusta uma vez por board.

        col = layout.column(align=True)
        if ajustes.project_code:
            # Só a sigla: o nome inteiro do arquivo não cabe nos 280px da
            # sidebar e sairia truncado ("Os arquivos come...E_EP03_CENA_02").
            col.label(text=_("Files start with") + ":", icon="FILE_MOVIE")
            col.label(text=project_code(store.project))
        else:
            linha = col.row()
            linha.alert = True
            linha.label(text=_("no project code yet"), icon="ERROR")
            col.label(text=_("files use the board name"))
        col.operator("nsb.rename_project", text=_("File names"),
                     icon="GREASEPENCIL")

        prefs = get_prefs(context)
        entrou = bool(getattr(prefs, "approval_token", "")) if prefs else False

        col = layout.column(align=True)
        if ajustes.approval_project_name:
            col.label(text=_("Approvals") + f": {ajustes.approval_project_name}",
                      icon="URL")
            if not ajustes.approval_client_id:
                linha = col.row()
                linha.alert = True
                linha.label(text=_("no client contact in this project"), icon="ERROR")
        if entrou:
            col.operator("nsb.pick_approval_project", icon="LINKED")
        else:
            col.operator("nsb.approval_login", icon="URL")


CLASSES = (
    NSB_UL_characters, NSB_UL_props,
    NSB_PT_storyboard, NSB_PT_more, NSB_PT_library,
    # O subpainel vem DEPOIS do pai: o Blender precisa do `bl_parent_id` já
    # registrado para pendurar o filho nele.
    NSB_PT_delivery, NSB_PT_delivery_setup,
)


def register():
    apply_context(CLASSES)
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
