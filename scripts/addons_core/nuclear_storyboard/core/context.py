"""De onde o board sai: a PASTA em que o animador vai fazer os takes.

Declarar episódio e cena era pedir duas vezes a mesma coisa. Quando o animador
escolhe a pasta ele JÁ disse os dois: o caminho da produção é sempre
`<PROJETO>/EP00/CENA00/`, e é de lá que saem o código do episódio, o da cena, o
nome do board e a sigla que abre o nome dos arquivos entregues.

Nada aqui adivinha demais: o que o caminho não disser vira `EP01`/`SC01`, que o
lápis da interface corrige. O que importa é o board nascer inteiro sem nenhuma
pergunta — os códigos entram no burning e no nome da entrega, então errar neles
é barato de consertar e caro de esquecer.

Módulo puro (sem `bpy`): serve à interface, ao worker headless e aos testes no
host.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .naming import sanitize, suggest_project_code

#: Pasta de episódio: `EP06`, `ep_06`, `Episodio 06`.
EPISODE_RE = re.compile(r"^(?:ep|epis[oó]dio|episode)[\s_-]*\d+", re.IGNORECASE)

#: Pasta de cena: `CENA03`, `SC03`, `C03`, `Scene 03`. O `C` sozinho pede o
#: número colado para não abocanhar uma pasta chamada "Cortes".
SCENE_RE = re.compile(r"^(?:cena|scene|sc)[\s_-]*\d+|^c\d+", re.IGNORECASE)

#: Pastas de ETAPA da produção, que ficam entre o projeto e o episódio:
#: `1_PreProducao`, `2_Animatic`, `1 - Thumbs`. Elas dizem em que ponto do
#: pipeline o material está, não de quem ele é — quem dá nome ao board é a pasta
#: do PROJETO, acima delas. Sem isto, o board do Tarik se chamava "2_Animatic".
STAGE_PREFIX_RE = re.compile(r"^\d+\s*[-_.]")
STAGE_WORDS = {
    "animatic", "animatics", "thumbs", "thumbnails", "storyboard", "board",
    "preproducao", "producao", "posproducao", "pre", "pos", "arte", "layout",
    "cenas", "scenes", "episodios", "episodes", "takes",
}

DEFAULT_EPISODE = "EP01"
DEFAULT_SCENE = "SC01"


@dataclass
class FolderContext:
    """O que a pasta escolhida diz sobre o board que vai nascer nela."""

    root: Path
    episode_code: str
    scene_code: str
    project_name: str
    project_code: str
    #: Os dois códigos vieram MESMO do caminho, ou são o padrão? A interface usa
    #: isto para dizer ao animador o que ela deduziu e o que ela inventou.
    from_path: bool = False


def _code(part: str) -> str:
    return sanitize(part).upper()


def context_from_path(root) -> FolderContext:
    """Lê episódio, cena, nome e sigla do caminho da pasta escolhida.

    A busca é de dentro para fora — a cena é a pasta mais funda que se parece
    com cena, e o episódio, a pasta de episódio acima dela. O nome do board é a
    pasta que vem antes do episódio (`.../DPE/EP06/CENA03` -> "DPE"), que é onde
    a produção guarda o projeto inteiro.
    """
    root = Path(root).expanduser()
    parts = [p for p in root.parts if p not in ("/", "\\") and not p.endswith(":\\")]
    if not parts:
        return FolderContext(root, DEFAULT_EPISODE, DEFAULT_SCENE, "Board", "", False)

    i_scene = _deepest(parts, SCENE_RE)
    limite = i_scene if i_scene is not None else len(parts)
    i_episode = _deepest(parts[:limite], EPISODE_RE)

    scene_code = _code(parts[i_scene]) if i_scene is not None else DEFAULT_SCENE
    episode_code = _code(parts[i_episode]) if i_episode is not None else DEFAULT_EPISODE

    # A pasta do projeto é a primeira acima do nível mais alto reconhecido que
    # não seja etapa de pipeline; sem nível reconhecido, o board é a própria
    # pasta escolhida.
    topo = i_episode if i_episode is not None else i_scene
    if topo is None:
        project_name = parts[-1]
    else:
        i = topo - 1
        while i > 0 and is_stage_folder(parts[i]):
            i -= 1
        project_name = parts[i] if i >= 0 else parts[topo]

    return FolderContext(
        root=root,
        episode_code=episode_code,
        scene_code=scene_code,
        project_name=project_name,
        project_code=suggest_project_code(project_name),
        from_path=i_scene is not None or i_episode is not None,
    )


def _deepest(parts, pattern):
    for i in range(len(parts) - 1, -1, -1):
        if pattern.match(parts[i]):
            return i
    return None


def is_stage_folder(part: str) -> bool:
    """A pasta é etapa de pipeline (`2_Animatic`, `1 - Thumbs`) e não o projeto?

    Pasta numerada é o hábito da produção para ordenar etapas. Um projeto que se
    chame mesmo "3 Porquinhos" cai nesta peneira — e é por isso que o nome do
    board continua editável na tela.
    """
    limpo = part.strip()
    if STAGE_PREFIX_RE.match(limpo):
        return True
    plano = sanitize(limpo).lower().replace("-", "_")
    return plano.replace("_", "") in STAGE_WORDS or plano in STAGE_WORDS


# --------------------------------------------------------------------------
# As cenas vizinhas
#
# Uma cena é uma pasta, e o episódio é a pasta que as contém — trocar de cena é
# entrar na pasta do lado. O add-on não precisa de um cadastro de cenas para
# isso: basta olhar o disco, que é onde a produção já organizou tudo.
# --------------------------------------------------------------------------

def scene_folders(root):
    """Pastas de cena vizinhas à do board (incluindo ele), em ordem de nome.

    Entra na lista quem se parece com cena (`CENA02`, `SC03`) ou quem já tem um
    board dentro — a segunda regra pega a cena de nome fora do padrão, que
    existe e não pode sumir do menu por causa do nome.
    """
    root = Path(root).expanduser()
    try:
        vizinhas = [p for p in root.parent.iterdir() if p.is_dir()]
    except OSError:
        vizinhas = []

    achadas = {p for p in vizinhas if _looks_like_scene(p)}
    if root.is_dir():
        achadas.add(root)
    return sorted(achadas, key=lambda p: p.name.lower())


def _looks_like_scene(pasta) -> bool:
    """A pasta é uma cena — pelo nome, ou por já ter um board dentro?

    A peneira das PEÇAS INTERNAS do board (`takes/`, `props/`, `audio/`…) não é
    zelo: uma versão antiga do add-on deixou um `project.json` dentro da própria
    `takes/`, e a regra "tem board, logo é cena" punha a pasta de takes no menu
    de cenas do episódio, ao lado das cenas de verdade. Entrar nela abriria um
    board com os takes do episódio como se fossem os de uma cena.
    """
    from .storage import SUBDIRS

    if pasta.name.lower() in SUBDIRS:
        return False
    return bool(SCENE_RE.match(pasta.name)) or (pasta / "project.json").is_file()


#: O que a pasta escolhida é, do ponto de vista do add-on.
ROLE_BOARD = "board"      # já tem um board dentro
ROLE_SCENE = "scene"      # é (ou vai ser) a pasta de uma cena
ROLE_EPISODE = "episode"  # contém as cenas — é por aqui que o animador entra


def folder_role(root) -> str:
    """`board`, `scene` ou `episode` — o que a pasta escolhida representa.

    O animador entra pela pasta do EPISÓDIO (`.../EP13/1 - Thumbs`), que é onde
    as cenas moram; abrir uma cena direto continua valendo. Distinguir os dois
    é o que impede um board de nascer no meio do episódio, com as cenas viradas
    subpastas de um take.
    """
    root = Path(root).expanduser()
    # Pasta que GUARDA cenas é o episódio, mesmo que tenha um `project.json`
    # dentro: um board nascido ali por engano (o que o fluxo antigo fazia ao
    # escolher a pasta do episódio) não pode esconder as cenas que existem —
    # entrar no episódio mostrava 14 takes soltos e nenhuma das cenas. Quem se
    # CHAMA de cena está fora da regra: ali o board é o dono da pasta.
    if not SCENE_RE.match(root.name) and any(_looks_like_scene(p)
                                             for p in _subfolders(root)):
        return ROLE_EPISODE
    if (root / "project.json").is_file():
        return ROLE_BOARD
    return ROLE_SCENE


def _subfolders(root):
    try:
        return sorted((p for p in Path(root).iterdir() if p.is_dir()),
                      key=lambda p: p.name.lower())
    except OSError:
        return []


def episode_scenes(episode_dir):
    """Pastas de cena dentro da pasta do episódio, em ordem de nome."""
    return [p for p in _subfolders(episode_dir) if _looks_like_scene(p)]


#: Como a produção nomeia cena quando ainda não há nenhuma na pasta.
DEFAULT_SCENE_PREFIX = "CENA"
DEFAULT_SCENE_DIGITS = 2

_SCENE_NAME_RE = re.compile(r"^([A-Za-zÀ-ÿ]+)[\s_-]*(\d+)$")


def scene_folder_name(episode_dir, number: int) -> str:
    """Nome da pasta da cena `number`, no padrão que o episódio JÁ usa.

    O estúdio escreve `CENA01`, mas board antigo pode ter `SC01` e outro pode
    escrever `Cena 1`: copiar o que está lá evita duas convenções na mesma pasta
    — e é a convenção que o montador do episódio lê para ordenar.
    """
    prefixo, dígitos = DEFAULT_SCENE_PREFIX, DEFAULT_SCENE_DIGITS
    for pasta in episode_scenes(episode_dir):
        achado = _SCENE_NAME_RE.match(pasta.name.strip())
        if achado:
            prefixo, dígitos = achado.group(1), len(achado.group(2))
            break
    return f"{prefixo}{max(1, int(number)):0{dígitos}d}"


def next_scene_number(episode_dir) -> int:
    """Primeiro número de cena livre na pasta do episódio."""
    usados = set()
    for pasta in episode_scenes(episode_dir):
        achado = _SCENE_NAME_RE.match(pasta.name.strip())
        if achado:
            usados.add(int(achado.group(2)))
    número = 1
    while número in usados:
        número += 1
    return número


def find_shared_library(root, levels: int = 4):
    """`library.json` que já existe perto — nos pais ou nas cenas vizinhas.

    Cada cena é um board, e board novo nasceria com a biblioteca vazia: o
    animador teria de recadastrar os personagens do episódio a cada cena, e a
    cor de cada um (que é a chave que aponta para o rig) escorregaria entre elas.
    A biblioteca é do PROJETO desde o PRD — aqui ela só passa a ser encontrada.
    """
    from .storage import LIBRARY_FILE

    root = Path(root).expanduser()
    # Biblioteca DA PRÓPRIA pasta ganha de qualquer outra: quem já tem elenco
    # não vai buscar o de fora. Sem isto, uma cena com cinco personagens
    # cadastrados que perdeu o `project.json` renascia apontando para o
    # `library.json` vazio do episódio — o elenco todo sumia da tela, com o
    # arquivo intacto ao lado.
    if (root / LIBRARY_FILE).is_file():
        return None
    for pasta in list(root.parents)[:levels]:
        alvo = pasta / LIBRARY_FILE
        if alvo.is_file():
            return alvo
    for vizinha in scene_folders(root):
        alvo = vizinha / LIBRARY_FILE
        if vizinha != root and alvo.is_file():
            return alvo
    return None


# --------------------------------------------------------------------------
# Link do Dropbox -> pasta no disco
#
# O caminho das cenas chega copiado do Dropbox na web
# (`https://www.dropbox.com/home/Projetos/Tarik/.../CENA01`). Traduzir o link
# para a pasta local poupa o animador de reencontrar a mesma pasta no navegador
# de arquivos, nível por nível.
# --------------------------------------------------------------------------

DROPBOX_HOSTS = {"dropbox.com", "www.dropbox.com"}

#: Primeiro pedaço do caminho de um link de PASTA na web ("meus arquivos").
DROPBOX_HOME = {"home", "h"}

#: Links compartilhados: apontam para um arquivo servido pelo Dropbox, e não
#: dizem em que lugar da conta ele está — não há como achar a pasta local.
DROPBOX_SHARED = {"scl", "s", "sh", "sc"}


def dropbox_local_root():
    """Onde a pasta do Dropbox está NESTA máquina, ou None."""
    import json

    info = Path.home() / ".dropbox" / "info.json"
    try:
        dados = json.loads(info.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        dados = {}
    for conta in ("personal", "business"):
        caminho = (dados.get(conta) or {}).get("path") if isinstance(dados, dict) else None
        if caminho and Path(caminho).is_dir():
            return Path(caminho)
    padrão = Path.home() / "Dropbox"
    return padrão if padrão.is_dir() else None


def path_from_link(texto: str, root=None):
    """Pasta local de um link do Dropbox, ou None se o link não serve.

    `root` existe para o teste: sem ele, a pasta do Dropbox desta máquina.
    """
    from urllib.parse import unquote, urlparse

    if not texto or "://" not in texto:
        return None
    endereço = urlparse(texto.strip())
    if endereço.scheme not in {"http", "https"}:
        return None
    if endereço.netloc.lower() not in DROPBOX_HOSTS:
        return None

    partes = [unquote(p) for p in endereço.path.split("/") if p]
    if partes and partes[0].lower() in DROPBOX_HOME:
        partes = partes[1:]
    if not partes or partes[0].lower() in DROPBOX_SHARED:
        return None

    base = Path(root).expanduser() if root is not None else dropbox_local_root()
    return base.joinpath(*partes) if base is not None else None


def ensure_structure(store) -> bool:
    """Garante que o board tem um episódio e uma cena — deduzidos do caminho.

    Devolve se criou alguma coisa. Vale para o board novo (nasce pronto para
    receber take) e para o board antigo que ficou sem estrutura porque alguém
    parou no meio do cadastro: sem isto, o botão "Novo take" fica cinza e não há
    nada na tela explicando por quê.
    """
    project = store.project
    if project.episodes and project.episodes[0].scenes:
        return False

    ctx = context_from_path(store.paths.root)
    episode = project.episodes[0] if project.episodes else store.add_episode(ctx.episode_code)
    if not episode.scenes:
        store.add_scene(episode, ctx.scene_code)
    return True
