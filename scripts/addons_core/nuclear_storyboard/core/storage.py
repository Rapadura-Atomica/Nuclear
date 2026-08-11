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

from .model import (SCHEMA_VERSION, Library, Project, Scene, Episode, Take,
                    from_dict, to_dict)

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
        if arquivo.exists():
            lib_payload = _read_json(arquivo)
            _check_schema(lib_payload, arquivo)
            library = from_dict(Library, lib_payload)
        else:
            library = Library()
        return cls(root, project, library)

    @property
    def library_file(self) -> Path:
        """Arquivo em que a biblioteca deste board é lida e gravada."""
        return library_file(self.paths, self.project)

    def ensure_dirs(self) -> None:
        for sub in SUBDIRS:
            (self.paths.root / sub).mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        self.project.schema_version = SCHEMA_VERSION
        self.library.schema_version = SCHEMA_VERSION
        _write_json(self.paths.project_json, to_dict(self.project))
        _write_json(self.library_file, to_dict(self.library))

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
