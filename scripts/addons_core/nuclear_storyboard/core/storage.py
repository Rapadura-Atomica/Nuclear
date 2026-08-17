"""Persistencia do projeto em disco — JSON estruturado.

Layout da pasta do projeto:

    <projeto>/
      project.json      hierarquia episodio/cena/take + settings + burning
      library.json      personagens (hex -> rig) e props; compartilhada
      takes/            um .nuc por take
      audio/            wavs importados
      drawings/         PNGs achatados dos desenhos (cache para o export)
      props/            arte dos props mandados para a biblioteca (RF-09)
      exports/          mp4 + .kdenlive gerados

Escrita atomica (tmp + os.replace): uma queda no meio do save nao deixa o
project.json pela metade.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .model import (SCHEMA_VERSION, Library, Project, Prop, Scene, Episode,
                    Take, from_dict, to_dict)

PROJECT_FILE = "project.json"
LIBRARY_FILE = "library.json"
SUBDIRS = ("takes", "audio", "drawings", "props", "exports")

#: Sufixos da metade nova de um take partido: T003 -> T003B, T003C…
ASCII_UPPER = "BCDEFGHIJKLMNOPQRSTUVWXYZ"

#: Sufixo que `_free_take_file` põe para dois takes de mesmo código não caírem
#: no mesmo arquivo (`T011_2.nuc`). Não faz parte do código do take.
TAKE_FILE_SUFFIX_RE = re.compile(r"^(.+?)_(\d+)$")


def _code_from_take_file(stem: str):
    """Código do take a partir do nome do `.nuc`: (base, veio_com_sufixo?)."""
    achado = TAKE_FILE_SUFFIX_RE.match(stem)
    return (achado.group(1), True) if achado else (stem, False)


class StorageError(Exception):
    pass


def _signature(path: Path):
    """Como o arquivo esta agora: (data em ns, tamanho). None se nao existe."""
    try:
        info = path.stat()
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size)


def _keep_aside(path: Path):
    """Guarda uma copia do arquivo antes de sobrescreve-lo. Devolve o caminho.

    O nome diz o que aconteceu e quando, em portugues, porque quem vai encontrar
    isso na pasta e o artista — e ele ja convive com o
    "conflicted copy" do Dropbox, que e a mesma historia contada em ingles.
    """
    import time

    if not path.is_file():
        return None
    quando = time.strftime("%Y-%m-%d %Hh%M")
    destino = _unique_path(path.with_name(f"{path.stem} (mudou por fora {quando}){path.suffix}"))
    try:
        shutil.copy2(path, destino)
    except OSError:
        return None
    return destino


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _read_json(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise StorageError(f"arquivo nao encontrado: {path}")
    except json.JSONDecodeError as exc:
        raise StorageError(f"JSON invalido em {path}: {exc}")


def _check_schema(payload: dict, path: Path) -> None:
    version = payload.get("schema_version", 0)
    if version > SCHEMA_VERSION:
        raise StorageError(
            f"{path.name} foi gravado por uma versao mais nova do add-on "
            f"(schema {version} > {SCHEMA_VERSION}). Atualize o Nuclear."
        )


@dataclass
class ProjectPaths:
    root: Path

    @property
    def project_json(self) -> Path:
        return self.root / PROJECT_FILE

    @property
    def library_json(self) -> Path:
        return self.root / LIBRARY_FILE

    @property
    def takes(self) -> Path:
        return self.root / "takes"

    @property
    def audio(self) -> Path:
        return self.root / "audio"

    @property
    def drawings(self) -> Path:
        return self.root / "drawings"

    @property
    def props(self) -> Path:
        return self.root / "props"

    @property
    def exports(self) -> Path:
        return self.root / "exports"

    def abs(self, relative: str) -> Path:
        """Caminho absoluto de uma referencia guardada no JSON.

        Referencias sao relativas a raiz do projeto justamente para a pasta
        inteira poder ser movida ou sincronizada sem quebrar nada. Caminho
        absoluto passa direto (ex.: rig fora do projeto).
        """
        p = Path(relative)
        return p if p.is_absolute() else self.root / p

    def rel(self, path) -> str:
        """Inverso de `abs`: relativiza se estiver dentro do projeto."""
        p = Path(path).resolve()
        try:
            return str(p.relative_to(self.root.resolve()))
        except ValueError:
            return str(p)


def library_file(paths: "ProjectPaths", project: Project) -> Path:
    """Arquivo da biblioteca deste board: o local, ou o compartilhado.

    `settings.library_path` aponta para o `library.json` de outra pasta quando
    as cenas de um episodio dividem a mesma biblioteca — que e o caso normal,
    porque cada cena e um board proprio e os personagens sao do episodio.
    """
    declarado = getattr(project.settings, "library_path", "") or ""
    return paths.abs(declarado) if declarado else paths.library_json


class ProjectStore:
    """Le e grava um projeto na pasta. Mantem project e library juntos."""

    def __init__(self, root, project: Project, library: Library):
        self.paths = ProjectPaths(Path(root))
        self.project = project
        self.library = library
        #: Como cada JSON estava no disco quando este store o leu. E o que
        #: permite perceber que ALGUEM MAIS escreveu nele desde entao — no
        #: estudio o board vive no Dropbox e duas maquinas abrem o mesmo
        #: episodio (em 2026-08-17 isso desfez a correcao de nome de cinco
        #: boards e trouxe de volta 42 arquivos apagados).
        self._seen = {}
        self._remember_files()
        #: Arquivos que este store sobrescreveu depois de terem mudado por
        #: fora, e onde ficou a copia do que estava la. A UI conta ao artista.
        self.overwritten = []
        #: Caminho da biblioteca COMPARTILHADA que o projeto declara e que nao
        #: foi encontrada. None quando esta tudo no lugar (ou quando a
        #: biblioteca e a do proprio board, que nasce junto com ele).
        self.library_missing = None

    # ---- ciclo de vida -------------------------------------------------
    @classmethod
    def create(cls, root, name: str, **settings) -> "ProjectStore":
        root = Path(root)
        if (root / PROJECT_FILE).exists():
            raise StorageError(f"ja existe um projeto em {root}")
        project = Project(name=name)
        for key, value in settings.items():
            if hasattr(project.settings, key):
                setattr(project.settings, key, value)
            else:
                raise StorageError(f"setting desconhecido: {key}")
        store = cls(root, project, Library())
        store.ensure_dirs()
        # Board novo apontado para uma biblioteca que JÁ EXISTE (as cenas de um
        # episódio dividem a mesma): ele lê antes de gravar, senão o primeiro
        # save apagaria o elenco inteiro do episódio com uma biblioteca vazia.
        arquivo = store.library_file
        if arquivo.is_file():
            payload = _read_json(arquivo)
            _check_schema(payload, arquivo)
            store.library = from_dict(Library, payload)
        store.save()
        return store

    @classmethod
    def load(cls, root) -> "ProjectStore":
        root = Path(root)
        paths = ProjectPaths(root)
        payload = _read_json(paths.project_json)
        _check_schema(payload, paths.project_json)
        project = from_dict(Project, payload)

        # A biblioteca pode morar fora do board (uma por episódio, dividida
        # entre as cenas) — quem diz onde é o próprio projeto.
        arquivo = library_file(paths, project)
        # Biblioteca COMPARTILHADA que nao esta no lugar (o `library.json` do
        # episodio ainda nao sincronizou, ou o caminho relativo deixou de valer)
        # nao pode virar uma biblioteca vazia calada: cada personagem e cada
        # prop citado pelos takes passa a "nao estar na biblioteca", e o board
        # inteiro parece quebrado sem que nada explique o motivo.
        faltando = project.settings.library_path and not arquivo.exists()
        if arquivo.exists():
            lib_payload = _read_json(arquivo)
            _check_schema(lib_payload, arquivo)
            library = from_dict(Library, lib_payload)
        else:
            library = Library()
        store = cls(root, project, library)
        store.library_missing = arquivo if faltando else None
        return store

    @property
    def library_file(self) -> Path:
        """Arquivo em que a biblioteca deste board é lida e gravada."""
        return library_file(self.paths, self.project)

    def ensure_dirs(self) -> None:
        for sub in SUBDIRS:
            (self.paths.root / sub).mkdir(parents=True, exist_ok=True)

    def _files_to_watch(self):
        return (self.paths.project_json, self.library_file)

    def _remember_files(self) -> None:
        """Anota como cada JSON esta no disco AGORA."""
        for arquivo in self._files_to_watch():
            self._seen[str(arquivo)] = _signature(arquivo)

    def changed_outside(self):
        """Arquivos do board que mudaram no disco desde que este store os leu.

        Board no Dropbox aberto em duas maquinas nao e caso raro no estudio: a
        outra grava, o cliente sincroniza, e o arquivo debaixo de nos deixa de
        ser o que tinhamos lido. Quem descobre isso tarde perde trabalho.
        """
        mudados = []
        for arquivo in self._files_to_watch():
            visto = self._seen.get(str(arquivo))
            if visto is not None and _signature(arquivo) != visto:
                mudados.append(arquivo)
        return mudados

    def save(self) -> None:
        """Grava o board. Nunca APAGA o que outro escreveu enquanto isso.

        Quando o arquivo mudou por fora desde a leitura, o que estava la e
        guardado ao lado antes de ser sobrescrito (`.mudou-por-fora-<hora>`) e
        o caminho vai para `overwritten`, que a tela mostra. Recusar a gravacao
        seria pior: o trabalho que o artista tem na tela e o que se perderia.
        """
        self.project.schema_version = SCHEMA_VERSION
        self.library.schema_version = SCHEMA_VERSION
        for arquivo in self.changed_outside():
            copia = _keep_aside(arquivo)
            if copia is not None:
                self.overwritten.append(copia)
        _write_json(self.paths.project_json, to_dict(self.project))
        _write_json(self.library_file, to_dict(self.library))
        self._remember_files()

    # ---- estrutura -----------------------------------------------------
    def add_episode(self, code: str, name: str = "") -> Episode:
        ep = Episode(code=code, name=name or code)
        self.project.episodes.append(ep)
        return ep

    def add_scene(self, episode: Episode, code: str, name: str = "") -> Scene:
        sc = Scene(code=code, name=name or code)
        episode.scenes.append(sc)
        return sc

    def add_take(self, scene: Scene, code: str, name: str = "",
                 after: Take = None) -> Take:
        """Cria um take na cena; `after` o coloca logo depois daquele.

        Partir um take gera a segunda metade, que precisa entrar EM SEGUIDA —
        no fim da lista ela sairia do lugar na ordem de leitura do animatic.
        """
        tk = Take(code=code, name=name or code)
        tk.file = self._free_take_file(code)
        if after is not None and after in scene.takes:
            scene.takes.insert(scene.takes.index(after) + 1, tk)
        else:
            scene.takes.append(tk)
        return tk

    def free_take_code(self, scene: Scene) -> str:
        """Proximo codigo livre da cena: T001, T002…

        Conta a partir de quantos takes existem e so anda enquanto o codigo
        estiver tomado — apagar o ultimo e criar outro devolve o mesmo codigo,
        em vez de deixar um buraco na numeracao do board.

        E o codigo de um take A MAIS, seja ele criado do zero ou duplicado: numa
        cena de cinco planos, duplicar o segundo da o SEXTO. Numerar pela origem
        (`T002B`) era outra leitura possivel, e o animador pediu esta.
        """
        usados = {tk.code for tk in scene.takes}
        i = len(scene.takes) + 1
        while f"T{i:03d}" in usados:
            i += 1
        return f"T{i:03d}"

    def next_take_code(self, scene: Scene, base: str) -> str:
        """Código livre para a metade nova: T003 -> T003B, T003C…

        Letra em vez de número novo porque o take partido continua sendo aquele
        plano: numerar por cima empurraria o resto da cena, e o board artist lê
        "3B" como a continuação de "3" sem precisar de explicação.
        """
        raiz = base.rstrip(ASCII_UPPER) or base
        usados = {tk.code for tk in scene.takes}
        for letra in ASCII_UPPER:
            tentativa = f"{raiz}{letra}"
            if tentativa not in usados:
                return tentativa
        i = 2
        while f"{raiz}_{i}" in usados:
            i += 1
        return f"{raiz}_{i}"

    def adopt_take_files(self, scene: Scene) -> list:
        """Põe na cena os `.nuc` da pasta `takes/` que nenhum take reivindica.

        Board que nasce numa pasta onde o animador JÁ desenhou abria com a grade
        vazia — quinze takes no disco, invisíveis, com toda a cara de trabalho
        perdido. Acontece quando o índice se perde, quando os desenhos chegam de
        outra máquina pelo Dropbox, ou quando uma versão anterior do add-on
        gravou o `project.json` em outro lugar.

        Adotar é só APONTAR para o arquivo que está lá: nada é criado, movido
        nem sobrescrito. O código sai do nome do arquivo, que é o que o animador
        vê no disco; o sufixo de desambiguação (`T011_2.nuc`) vira a letra do
        take partido (`T011B`), porque é o mesmo plano continuando.

        Devolve os takes adotados, na ordem em que entraram.
        """
        tomados = {tk.file for _, _, tk in self.project.iter_takes() if tk.file}
        adotados = []
        for arquivo in sorted(self.paths.takes.glob("*.nuc"),
                              key=lambda p: p.name.lower()):
            relativo = str(Path("takes") / arquivo.name)
            if relativo in tomados:
                continue
            base, sufixado = _code_from_take_file(arquivo.stem)
            usados = {tk.code for tk in scene.takes}
            código = self.next_take_code(scene, base) if sufixado or base in usados else base
            take = Take(code=código, name=código)
            take.file = relativo
            scene.takes.append(take)
            adotados.append(take)
        return adotados

    def _take_slug(self, code: str) -> str:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in code)
        return safe or "take"

    def _free_take_file(self, code: str) -> str:
        """Caminho do `.nuc` que ainda não pertence a nenhum take.

        O código sozinho não serve de nome de arquivo: `T001` na cena 1 e `T001`
        na cena 2 são takes DIFERENTES e cairiam no mesmo `.nuc`, cada um
        abrindo e sobrescrevendo a arte do outro. Desambiguamos com sufixo
        (`T001_2.nuc`), conferindo tanto o índice quanto o disco — um take
        removido do índice deixa o arquivo lá, e ele não pode ser reaproveitado
        por engano.
        """
        taken = {tk.file for _, _, tk in self.project.iter_takes() if tk.file}
        slug = self._take_slug(code)
        i = 1
        while True:
            candidate = str(Path("takes") / (f"{slug}.nuc" if i == 1 else f"{slug}_{i}.nuc"))
            if candidate not in taken and not (self.paths.root / candidate).exists():
                return candidate
            i += 1

    def prop_reference_destination(self, prop_name: str, suffix: str) -> Path:
        """Caminho livre para a imagem de REFERENCIA de um prop.

        O nome sai do prop, nao do arquivo escolhido: uma pasta `props/` cheia de
        `ref_IMG_20260804.png` nao diz nada, e um arquivo que ja se chamava
        "ref_lampiao.png" virava "ref_ref_lampiao.png".
        """
        self.paths.props.mkdir(parents=True, exist_ok=True)
        slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in prop_name)
        slug = slug.strip("_") or "prop"
        if not suffix.startswith("."):
            suffix = f".{suffix}" if suffix else ".png"
        return _unique_path(self.paths.props / f"ref_{slug}{suffix}")

    def prop_art_destination(self, name: str) -> Path:
        """Caminho livre para a arte de um prop mandado do canvas (RF-09).

        Nome homonimo nao sobrescreve: dois props chamados "Copo" viram
        `Copo.png` e `Copo_1.png`, porque a arte e a identidade deles.
        """
        self.paths.props.mkdir(parents=True, exist_ok=True)
        slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in name) or "prop"
        return _unique_path(self.paths.props / f"{slug}.png")

    def remove_prop(self, prop: Prop) -> dict:
        """Tira o prop da biblioteca, dos takes e do disco. NAO grava.

        Apagar so o cadastro deixaria os takes apontando para um id que nao
        existe mais — que e o erro RF-B01, o unico problema de prop que TRAVA o
        export. Por isso a limpeza e uma coisa so.

        As imagens dele saem junto (decisao do usuario, 2026-08-17), menos as
        que outro prop ainda usa: dois cadastros podem apontar para o mesmo
        arquivo, e apagar ali levaria a arte de quem ficou.

        Devolve o que aconteceu, para quem chamou poder contar ao artista:
        `takes` (de quantos ele saiu), `files` (imagens apagadas), `kept`
        (imagens que ficaram porque outro prop usa) e `request` (id da pendencia
        aberta no aprovacao, que continua la — daqui nao se cancela nada).
        """
        try:
            self.library.props.remove(prop)
        except ValueError:
            return {"takes": 0, "files": [], "kept": [], "request": ""}

        takes = 0
        for _ep, _sc, take in self.project.iter_takes():
            if prop.id in take.prop_ids:
                take.prop_ids.remove(prop.id)
                takes += 1

        # Quem tinha sido substituido por ele volta a ser o que e: sem isto o
        # provisorio aponta para um id morto e `resolve_prop` devolve None.
        for outro in self.library.props:
            if outro.replaced_by == prop.id:
                outro.replaced_by = None

        em_uso = {rel for outro in self.library.props
                  for rel in (outro.file, outro.reference) if rel}
        apagados, mantidos = [], []
        for rel in dict.fromkeys(r for r in (prop.file, prop.reference) if r):
            if rel in em_uso:
                mantidos.append(rel)
                continue
            caminho = self.paths.abs(rel)
            try:
                caminho.unlink()
                apagados.append(rel)
            except OSError:
                pass  # arquivo ja sumiu ou e de fora do projeto: o cadastro sai igual
        return {"takes": takes, "files": apagados, "kept": mantidos,
                "request": prop.request_id or ""}

    # ---- midia ---------------------------------------------------------
    def import_audio(self, source, take: Take, start: float = 0.0, duration: Optional[float] = None):
        """Copia o .wav para dentro do projeto e devolve o clipe criado.

        A copia e proposital: o projeto tem que ser autocontido, do mesmo jeito
        que o build de take do Painel — arquivo fora da pasta some quando o
        projeto viaja.
        """
        from .wave_info import wav_duration  # import tardio: so quem importa audio paga
        from .model import Audio

        src = Path(source)
        if not src.is_file():
            raise StorageError(f"audio nao encontrado: {src}")
        self.paths.audio.mkdir(parents=True, exist_ok=True)
        dest = self.paths.audio / src.name
        if dest.resolve() != src.resolve():
            dest = _unique_path(dest)
            shutil.copy2(src, dest)
        if duration is None:
            duration = wav_duration(dest)
        clip = Audio(name=src.stem, file=self.paths.rel(dest), start=start, duration=duration)
        take.audios.append(clip)
        return clip


def _unique_path(path: Path) -> Path:
    """Evita sobrescrever homonimo: `dialogo.wav` -> `dialogo_1.wav`."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    i = 1
    while True:
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1
