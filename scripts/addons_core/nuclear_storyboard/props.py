"""PropertyGroups que espelham o modelo para a UI do Blender desenhar listas.

Sao ESPELHO, nao verdade: `sync.py` reescreve tudo a partir do `ProjectStore`.
Guardamos o `uid` de cada item para achar o objeto real do modelo.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty,
                       FloatProperty, FloatVectorProperty, IntProperty,
                       PointerProperty, StringProperty)
from bpy.types import AddonPreferences, PropertyGroup


#: Quantos espelhamentos estao em curso. Escrever numa PropertyGroup dispara o
#: `update` dela, e o `sync.py` reescreve TODAS as listas a cada operacao — sem
#: esta trava, espelhar o estado abriria takes e regravaria cores sozinho.
_MIRRORING = 0


@contextmanager
def mirroring():
    """Marca que quem esta escrevendo nas PropertyGroups e o espelho, nao o artista."""
    global _MIRRORING
    _MIRRORING += 1
    try:
        yield
    finally:
        _MIRRORING -= 1


def is_mirroring() -> bool:
    return _MIRRORING > 0


class NSB_Preferences(AddonPreferences):
    """Ajustes da MAQUINA, nao do projeto — por isso ficam aqui e nao no JSON.

    O `.json` do projeto viaja entre computadores; o caminho do Audacity, nao.
    """

    bl_idname = __package__

    audio_editor: StringProperty(
        name="Audio editor", subtype="FILE_PATH", default="",
        description="Path to Audacity; empty finds it in PATH or Flatpak (RF-18)")

    # --- sistema de aprovacao de assets ---------------------------------
    # Endereco e credencial sao da MAQUINA: o board viaja entre computadores e
    # cada um entra com a sua conta. A SENHA nunca e guardada — so o token que a
    # API devolveu, como no aplicativo do celular.
    approval_url: StringProperty(
        name="Approvals address", default="",
        description="Address of the approval API; empty uses the studio one")
    approval_user: StringProperty(
        name="User", default="",
        description="Same user as the intranet")
    approval_token: StringProperty(name="Token", default="", options={"HIDDEN"})
    approval_role: StringProperty(name="Role", default="", options={"HIDDEN"})

    def draw(self, context):
        from .core.approval import DEFAULT_BASE_URL
        from .core.audioedit import EditorNotFound, find_audio_editor
        layout = self.layout
        layout.prop(self, "audio_editor")
        try:
            layout.label(text=" ".join(find_audio_editor(self.audio_editor)),
                         icon="CHECKMARK")
        except EditorNotFound as exc:
            row = layout.row()
            row.alert = True
            row.label(text=str(exc), icon="ERROR")

        box = layout.box()
        box.label(text="Approvals", icon="URL")
        box.prop(self, "approval_url", placeholder=DEFAULT_BASE_URL)
        row = box.row(align=True)
        if self.approval_token:
            row.label(text=f"{self.approval_user} ({self.approval_role or '—'})",
                      icon="CHECKMARK")
            row.operator("nsb.approval_logout", icon="X", text="")
        else:
            row.operator("nsb.approval_login", icon="URL")


def get_prefs(context):
    """Preferencias do add-on, ou None se ele nao esta instalado como add-on."""
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


# --------------------------------------------------------------------------
# Boards recentes
#
# Voltar ao trabalho de ontem era navegar ate a pasta de novo, todo dia.
#
# A lista mora num JSON na config do Nuclear, e nao numa AddonPreference: as
# preferencias so vao para o disco quando o Blender resolve grava-las, e o app
# template do Nuclear ja as devolveu para a fabrica mais de uma vez (memoria
# `nuclear-prefs-duas-instancias`). Um arquivo nosso e escrito na hora.
# --------------------------------------------------------------------------

#: Lista curta de proposito: o que passa disto se acha mais rapido pela pasta.
MAX_RECENT = 8

RECENT_FILE = "recent_boards.json"


def _recent_path():
    from pathlib import Path

    pasta = bpy.utils.user_resource("CONFIG", path="nuclear_storyboard", create=True)
    return Path(pasta) / RECENT_FILE


def recent_boards(context=None):
    """[{'path', 'name'}] dos ultimos boards abertos, do mais recente ao mais velho.

    Board que sumiu do disco nao aparece: a lista existe para clicar, e um
    caminho morto so daria erro depois do clique.
    """
    import json
    from pathlib import Path

    try:
        dados = json.loads(_recent_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(dados, list):
        return []
    vivos = []
    for d in dados:
        if not isinstance(d, dict) or not d.get("path"):
            continue
        pasta = Path(d["path"])
        if d.get("kind") == "episode":
            if pasta.is_dir():
                vivos.append(d)
        elif (pasta / "project.json").is_file():
            vivos.append(d)
    return vivos


def remember_board(context, root, name: str, kind: str = "board") -> None:
    """Poe a pasta no topo da lista, sem repetir e sem crescer para sempre.

    `kind` separa a pasta do EPISODIO (por onde o animador entra) do board de
    uma cena: as duas voltam na lista, com sentidos diferentes ao clicar.
    """
    import json

    caminho = str(root)
    lista = [d for d in recent_boards(context) if d.get("path") != caminho]
    lista.insert(0, {"path": caminho, "name": name, "kind": kind})
    del lista[MAX_RECENT:]
    try:
        _recent_path().write_text(json.dumps(lista, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
    except OSError:
        pass  # sem permissao de escrita na config: a lista some, o board abre igual


def _on_take_code(item, context):
    """Código digitado no card do plano -> código do take no índice.

    O código não é enfeite: é ele que abre o nome de cada arquivo entregue
    (`DPE_EP13_C01T05`) e o que o artista lê na coluna. Editar aqui era o único
    jeito de corrigi-lo sem passar pelo diálogo de renomear a estrutura inteira.

    O `.nuc` NÃO é renomeado junto — ele é carimbado e apontado pelo índice, e
    mexer no nome do arquivo só criaria chance de perder arte.
    """
    from . import state

    if is_mirroring():
        return
    store = state.get_store()
    if store is None:
        return
    achado = store.project.find_take(item.uid)
    if achado is None:
        return
    take = achado[2]
    novo = item.code.strip()
    if not novo:
        # Campo apagado: um plano sem código sairia do board e da entrega. A
        # devolução vai dentro de `mirroring` porque escrever numa property
        # dispara o update dela, mesmo com o valor que já estava lá.
        with mirroring():
            item.code = take.code
        return
    if novo == take.code:
        return
    # O nome que só repetia o código continua repetindo: ele nasce assim e
    # ninguém o editou, então deixá-lo apontando para o código antigo seria
    # guardar um rótulo que já não corresponde a nada.
    if take.name == take.code:
        take.name = novo
    take.code = novo
    _save_soon(store)


class NSB_TakeItem(PropertyGroup):
    uid: StringProperty()
    code: StringProperty(name="Take", update=_on_take_code,
                         description="Code of this plan — it names the file "
                                     "delivered for it")
    name: StringProperty(name="Name")
    drawing_count: IntProperty(name="Drawings")
    audio_count: IntProperty(name="Audio")
    duration: FloatProperty(name="Duration", subtype="TIME_ABSOLUTE")
    ok: BoolProperty(name="Valid", default=True)


class NSB_SceneItem(PropertyGroup):
    uid: StringProperty()
    code: StringProperty(name="Scene")
    name: StringProperty(name="Name")
    take_count: IntProperty()


class NSB_EpisodeItem(PropertyGroup):
    uid: StringProperty()
    code: StringProperty(name="Episode")
    name: StringProperty(name="Name")
    scene_count: IntProperty()


def _on_character_color(item, context):
    """Cor escolhida no seletor -> hex do personagem na biblioteca.

    A cor e a CHAVE que liga o lineart ao rig, entao ela continua sendo guardada
    como hex no `library.json`; o seletor e so a maneira de escolher. Gravar em
    disco fica para um instante depois (`_save_soon`): arrastar no seletor chama
    este callback a cada quadro, e um `store.save()` por quadro travaria a mao
    do artista.
    """
    from . import state
    from .core import hex_from_rgb

    if is_mirroring():
        return
    store = state.get_store()
    if store is None:
        return
    character = next((c for c in store.library.characters if c.id == item.uid), None)
    if character is None:
        return
    novo = hex_from_rgb(item.color)
    if novo == character.hex_color:
        return
    character.hex_color = novo
    item.hex_color = novo
    _repaint_open_take(store)
    _save_soon(store)


def _on_character_change(state, context):
    """Clicar no personagem na biblioteca ja e "vou desenhar este agora".

    Mesma logica da lista de takes: escolher e a ordem, nao um passo antes dela.
    Antes disto havia dois botoes ("Desenhar com esta cor" e "Camada do
    personagem") que so repetiam a escolha ja feita no clique.
    """
    from . import gp, takefile

    # Sem guarda de `background`: preparar o pincel não troca arquivo nem depende
    # de janela, então isto roda (e se testa) headless igual.
    if is_mirroring():
        return
    store = _store_or_none()
    if store is None:
        return
    if not (0 <= state.character_index < len(store.library.characters)):
        return
    character = store.library.characters[state.character_index]
    take = takefile.current_take_of_file(store)
    ob = gp.find_take_object(take) if take is not None else None
    if ob is None:
        return  # sem take na tela nao ha o que preparar; a escolha fica na lista

    gp.draw_as_character(context, ob, character)
    if character.id not in take.character_ids:
        take.character_ids.append(character.id)
        _save_soon(store)


def _store_or_none():
    from . import state
    return state.get_store()


def _repaint_open_take(store) -> None:
    """Leva a cor nova para o material do take que esta aberto, na hora.

    Sem isto o artista escolheria a cor e continuaria desenhando com a antiga
    ate reabrir o take.
    """
    from . import gp, takefile

    take = takefile.current_take_of_file(store)
    ob = gp.find_take_object(take) if take is not None else None
    if ob is not None:
        gp.ensure_library_materials(ob, store.library)


def _save_now():
    """Grava o projeto; e o tiro unico que `_save_soon` agenda."""
    from . import state

    atual = state.get_store()
    if atual is not None:
        atual.save()
    return None


def _save_soon(store) -> None:
    """Grava daqui a pouco, juntando o arrasto inteiro do seletor num save so.

    Quem responde "ja tem save a caminho?" e o Blender, nao uma variavel nossa:
    uma marca propria ficaria acesa para sempre se o timer fosse descartado no
    meio (abrir um take descarta os nao-persistentes), e a cor seguinte nunca
    mais chegaria ao disco. Pelo mesmo motivo o timer e `persistent`: entre
    escolher a cor e o disco pode passar uma troca de take.
    """
    if bpy.app.background:
        store.save()
        return
    if bpy.app.timers.is_registered(_save_now):
        return
    bpy.app.timers.register(_save_now, first_interval=0.4, persistent=True)


class NSB_CharacterItem(PropertyGroup):
    uid: StringProperty()
    name: StringProperty(name="Character")
    hex_color: StringProperty(name="Color")
    #: O mesmo valor do hex, em 0..1, para o seletor de cor do Nuclear. Fica em
    #: `COLOR_GAMMA` (espaco de tela) de proposito: e o espaco em que o hex e
    #: escrito, entao o campo "Hex" do proprio seletor mostra a chave do
    #: personagem sem nenhuma conversao pelo meio.
    color: FloatVectorProperty(
        name="Color", subtype="COLOR_GAMMA", size=3, min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0), update=_on_character_color,
        description="Lineart colour of this character — click to pick")
    rig_path: StringProperty(name="Rig", subtype="FILE_PATH")
    linked: BoolProperty(default=False)


class NSB_PropItem(PropertyGroup):
    uid: StringProperty()
    name: StringProperty(name="Prop")
    temporary: BoolProperty(name="Temporary", default=True)
    has_art: BoolProperty(name="Has art", default=False)
    #: Estado da pendencia no sistema de aprovacao — vazio quando nunca foi
    #: pedida. "WAITING" e local: tem referencia anexada e ainda nao subiu.
    request_status: StringProperty(name="Request", default="")
    has_reference: BoolProperty(name="Has reference", default=False)
    resolved: BoolProperty(name="Resolved", default=False)


class NSB_IssueItem(PropertyGroup):
    level: StringProperty()
    code: StringProperty()
    message: StringProperty()
    where: StringProperty()


def _on_episode_change(state, context):
    """Trocar de episódio reconstrói a lista de cenas (e, em cascata, a de takes)."""
    from . import sync
    sync.sync_scenes(context)


def _on_scene_change(state, context):
    from . import sync
    sync.sync_takes(context)


def _on_take_change(state, context):
    """Clicar num take na lista JA entra nele — nao ha passo de "desenhar".

    A troca em si nao acontece aqui: abrir arquivo de dentro de um callback de
    propriedade e feito com a interface no meio de um redesenho. Quem abre e um
    timer de tiro unico (`autoswitch`), no tique seguinte.
    """
    from . import autoswitch
    autoswitch.request_open(context)


# --------------------------------------------------------------------------
# Episodio e cena como MENU, nao como lista
#
# Duas `template_list` comiam metade da sidebar antes de o artista desenhar
# qualquer coisa. Como menu, cada nivel ocupa uma linha.
#
# O `items` e uma callback (a hierarquia muda em tempo de execucao), e o
# resultado PRECISA ficar guardado numa variavel viva: o Blender nao segura as
# strings devolvidas e elas viram lixo — rotulo corrompido na tela.
# --------------------------------------------------------------------------

_ITEMS_CACHE = {}

#: Item mostrado quando ainda nao existe episodio/cena. Um enum sem nenhum item
#: nao pode ser desenhado.
_EMPTY = [("0", "—", "")]


def _menu_items(key, collection):
    items = [(str(i), item.code or item.name or str(i + 1), item.name)
             for i, item in enumerate(collection)]
    _ITEMS_CACHE[key] = items or list(_EMPTY)
    return _ITEMS_CACHE[key]


def _episode_items(self, context):
    return _menu_items("episodes", self.episodes)


def _scene_items(self, context):
    return _menu_items("scenes", self.scenes)


def _clamp(value, length):
    return max(0, min(value, length - 1)) if length else 0


def _episode_get(self):
    return _clamp(self.episode_index, len(self.episodes))


def _episode_set(self, value):
    self.episode_index = value  # dispara _on_episode_change


def _scene_get(self):
    return _clamp(self.scene_index, len(self.scenes))


def _scene_set(self, value):
    self.scene_index = value


# --------------------------------------------------------------------------
# Entrega
#
# O combinado da producao (formato, para onde vai, o que acompanha) mora no
# `project.json`, nao aqui: quem entrega o Ep03 entrega sempre do mesmo jeito, e
# de qualquer computador. Estas propriedades sao a MAO na tela — escrevem no
# modelo e gravam um instante depois, como o seletor de cor.
# --------------------------------------------------------------------------

def _delivery_setting(nome):
    def _update(state, context):
        if is_mirroring():
            return
        store = _store_or_none()
        if store is None:
            return
        valor = getattr(state, f"delivery_{nome}")
        if getattr(store.project.settings, f"delivery_{nome}") == valor:
            return
        setattr(store.project.settings, f"delivery_{nome}", valor)
        _save_soon(store)
    return _update


def _delivery_folder_update(state, context):
    """As duas pastas de destino, guardadas no projeto como caminho absoluto."""
    import bpy as _bpy

    if is_mirroring():
        return
    store = _store_or_none()
    if store is None:
        return
    mudou = False
    for campo, ajuste in (("delivery_dir", "export_dir"),
                          ("delivery_takes_dir", "takes_export_dir")):
        escolhido = (getattr(state, campo) or "").strip()
        # `//` e `~` chegam do seletor de pasta do Blender.
        valor = str(Path(_bpy.path.abspath(escolhido)).expanduser()) if escolhido else ""
        if getattr(store.project.settings, ajuste) != valor:
            setattr(store.project.settings, ajuste, valor)
            mudou = True
    if mudou:
        _save_soon(store)


# --------------------------------------------------------------------------
# Duracao do take, editavel na timeline
#
# Nao e um valor guardado aqui: le e escreve DIRETO no take aberto. Espelhar a
# duracao numa propriedade da sessao criaria um segundo dono do mesmo dado —
# exatamente o que o resto do add-on evita.
# --------------------------------------------------------------------------

def _take_seconds_get(self):
    from .core import take_duration
    from .timelineui import take_on_screen

    _store, take = take_on_screen()
    return float(take_duration(take)) if take is not None else 0.0


def _take_seconds_set(self, value):
    from . import sync, takefile
    from .core import take_duration
    from .timelineui import take_on_screen

    store, take = take_on_screen()
    if take is None:
        return
    fps = store.project.settings.fps
    novo = max(1.0 / fps, float(value))
    # Meio frame de tolerancia: o campo devolve o mesmo numero que mostrou, e
    # gravar por isso congelaria o take no tempo que o audio ja daria.
    if abs(take_duration(take) - novo) < 0.5 / fps:
        return
    scene = bpy.context.scene
    takefile.capture_from_scene(scene, store, take)
    take.duration_override = novo
    takefile.refresh_take_view(scene, store, take, capture=False)
    _save_soon(store)
    sync.sync_takes(bpy.context)


class NSB_State(PropertyGroup):
    """Ancorado em `WindowManager`: some ao fechar, como o estado de sessao que e."""

    project_dir: StringProperty(
        name="Project folder", subtype="DIR_PATH",
        description="Folder holding project.json, library.json and the media")
    project_name: StringProperty(name="Project name", default="New Project")
    loaded: BoolProperty(default=False)

    #: Link da pasta no Dropbox, colado da web. O caminho da cena chega assim
    #: (`https://www.dropbox.com/home/Projetos/Tarik/.../CENA01`), e reencontrar
    #: a mesma pasta no navegador de arquivos, nível por nível, e trabalho a
    #: toa: o add-on traduz o link para a pasta local.
    folder_link: StringProperty(
        name="Dropbox link", default="",
        description="Paste the folder link from Dropbox and it opens the local folder")
    #: Pasta do episodio (`.../EP13/1 - Thumbs`), onde as cenas moram. E por ela
    #: que o animador entra: escolhe o episodio e so depois a cena, que pode nem
    #: existir ainda. Com um board aberto, ela e a pasta acima dele.
    episode_dir: StringProperty(
        name="Episode folder", subtype="DIR_PATH", default="",
        description="Folder holding this episode's scenes")

    episodes: CollectionProperty(type=NSB_EpisodeItem)
    episode_index: IntProperty(default=0, update=_on_episode_change)
    episode_menu: EnumProperty(name="Episode", items=_episode_items,
                               get=_episode_get, set=_episode_set)
    scenes: CollectionProperty(type=NSB_SceneItem)
    scene_index: IntProperty(default=0, update=_on_scene_change)
    scene_menu: EnumProperty(name="Scene", items=_scene_items,
                             get=_scene_get, set=_scene_set)
    takes: CollectionProperty(type=NSB_TakeItem)
    take_index: IntProperty(default=0, update=_on_take_change)

    characters: CollectionProperty(type=NSB_CharacterItem)
    character_index: IntProperty(default=0, update=_on_character_change)
    props: CollectionProperty(type=NSB_PropItem)
    prop_index: IntProperty(default=0)

    issues: CollectionProperty(type=NSB_IssueItem)
    error_count: IntProperty(default=0)
    warning_count: IntProperty(default=0)

    timeline_frames: IntProperty(default=0)

    #: Os dois desenhos por cima da tela: o codigo do take no quadro e os
    #: desenhos como quadrados na timeline. Ligados, porque e o que a pessoa
    #: espera ver ao abrir um board; desligaveis, porque tela e do artista.
    show_take_overlay: BoolProperty(
        name="Take on screen", default=True,
        description="Writes the take code on the camera frame and squares the "
                    "drawings on the timeline")

    #: Quanto o take dura, em segundos, do jeito que a timeline mostra. E a
    #: duracao do take ABERTO no arquivo (nao a do selecionado na lista): quem
    #: olha a timeline esta vendo o plano que esta na tela.
    take_seconds: FloatProperty(
        name="Duration", description="How long this plan lasts, in seconds",
        min=0.0, soft_max=60.0, step=10, precision=2,
        get=_take_seconds_get, set=_take_seconds_set)

    # --- entrega ---------------------------------------------------------
    #: O que entregar. Fica na SESSAO (e nao no projeto) porque muda a cada
    #: entrega — hoje a cena, amanha o episodio.
    delivery_scope: EnumProperty(
        name="What to deliver",
        items=[("TAKE", "This take", "Only the take on screen"),
               ("SCENE", "This scene", "Every take of the scene"),
               ("EPISODE", "This episode", "Every take of the episode"),
               ("PROJECT", "Whole board", "Everything, in order")],
        default="SCENE")
    delivery_format: EnumProperty(
        name="Format",
        items=[("MP4", "MP4 (review)", "Plays anywhere; it is what approvals take"),
               ("DNXHR", "DNxHR (editing)", "Goes straight into DaVinci")],
        default="MP4", update=_delivery_setting("format"))
    #: Os rótulos dizem o DESTINO por extenso: "Aprovação", sozinho, não conta
    #: que ali é onde o produtor assiste e responde.
    delivery_target: EnumProperty(
        name="Deliver to",
        items=[("FOLDER", "A folder (production, Dropbox)",
                "The files are written to a folder on this computer"),
               ("APPROVAL", "The approval system (the producer reviews there)",
                "Uploads the animatic for review, without writing to a folder"),
               ("BOTH", "The folder and the approval system", "Both at once")],
        default="FOLDER", update=_delivery_setting("target"))
    delivery_kdenlive: BoolProperty(
        name="Kdenlive project", default=True,
        description="Also writes the .kdenlive next to the video",
        update=_delivery_setting("kdenlive"))
    #: Ligado de fábrica: entregar take a take é o normal da produção — é o
    #: arquivo que a equipe de animação recebe para animar em cima. Ficava
    #: desmarcado, então quem não sabia da caixa entregava só o animatic
    #: emendado e refazia a entrega depois.
    delivery_per_take: BoolProperty(
        name="One MP4 per plan", default=True,
        description=("A video per plan (PROJECT_EP00_C00T00.mp4) besides the "
                     "animatic — it is what the animation team gets to work on"),
        update=_delivery_setting("per_take"))
    delivery_dir: StringProperty(
        name="Folder", subtype="DIR_PATH", default="",
        description="Where the animatic goes; empty keeps it inside the board",
        update=_delivery_folder_update)
    delivery_takes_dir: StringProperty(
        name="Takes folder", subtype="DIR_PATH", default="",
        description="Where the per-take files go; empty keeps them in the board",
        update=_delivery_folder_update)


CLASSES = (
    NSB_TakeItem, NSB_SceneItem, NSB_EpisodeItem, NSB_CharacterItem,
    NSB_PropItem, NSB_IssueItem, NSB_State, NSB_Preferences,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.nsb = PointerProperty(type=NSB_State)


def unregister():
    del bpy.types.WindowManager.nsb
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
