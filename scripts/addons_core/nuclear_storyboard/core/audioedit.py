"""RF-18 — ponte com o editor de audio externo (Audacity).

Parte pura: descobrir o executavel, detectar que o arquivo mudou no disco e
decidir o que fazer com a duracao do clipe depois da edicao. Quem lanca o
processo e remonta a timeline e `nuclear_storyboard/audioedit.py`, que importa
daqui.

O arquivo editado e o .wav que ja vive DENTRO do projeto (o import copia, ver
`ProjectStore.import_audio`): o Audacity abre e salva por cima, e o projeto
segue autocontido.
"""

from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

#: Variavel de ambiente que vence tudo — util em teste e em maquina exotica.
EDITOR_ENV = "NSB_AUDIO_EDITOR"

#: Executaveis procurados no PATH, em ordem de preferencia. Tenacity e o fork
#: livre do Audacity e fala o mesmo dialeto de linha de comando.
EDITOR_COMMANDS = ("audacity", "tenacity")

#: Flatpak: id do app e as raizes onde uma instalacao aparece. Conferimos o
#: diretorio em vez de rodar `flatpak info` para nao pagar subprocesso a cada
#: redesenho de painel.
FLATPAK_APP = "org.audacityteam.Audacity"
FLATPAK_ROOTS = ("/var/lib/flatpak/app", "~/.local/share/flatpak/app")

#: Folga para decidir se o clipe estava inteiro (em segundos).
TRIM_TOLERANCE = 1e-3


class EditorNotFound(Exception):
    pass


def _which(name: str, environ) -> Optional[str]:
    """`shutil.which` olhando o PATH do `environ` recebido, nao o do processo."""
    return shutil.which(name, path=environ.get("PATH", os.defpath))


def _flatpak_editor(environ) -> Optional[List[str]]:
    if _which("flatpak", environ) is None:
        return None
    for root in FLATPAK_ROOTS:
        if (Path(root).expanduser() / FLATPAK_APP).is_dir():
            return ["flatpak", "run", FLATPAK_APP]
    return None


def find_audio_editor(explicit: str = "", environ=None) -> List[str]:
    """Comando (ja separado em argumentos) que abre um .wav para edicao.

    Ordem: caminho configurado pelo usuario, variavel de ambiente, PATH,
    Flatpak. Sem nenhum deles levanta `EditorNotFound` com uma mensagem que diz
    o que instalar — o add-on nao instala nada por conta propria.
    """
    environ = os.environ if environ is None else environ

    for candidate in (explicit.strip(), environ.get(EDITOR_ENV, "").strip()):
        if not candidate:
            continue
        parts = shlex.split(candidate)
        if not parts:
            continue
        # Comando com argumentos ("flatpak run ...") passa inteiro; caminho ou
        # nome solto ainda precisa existir.
        if len(parts) > 1 or Path(parts[0]).is_file() or _which(parts[0], environ):
            return parts
        raise EditorNotFound(f"editor de audio nao encontrado: {candidate}")

    for name in EDITOR_COMMANDS:
        found = _which(name, environ)
        if found:
            return [found]

    flatpak = _flatpak_editor(environ)
    if flatpak:
        return flatpak

    raise EditorNotFound(
        "Audacity nao encontrado: instale-o (ou informe o caminho do editor "
        "nas preferencias do add-on)")


def file_signature(path) -> Optional[Tuple[int, int]]:
    """(mtime_ns, tamanho) do arquivo, ou None se ele nao existe.

    Tamanho junto do mtime porque um save do Audacity pode cair no mesmo
    nanossegundo do anterior em sistema de arquivo de baixa resolucao.
    """
    try:
        info = Path(path).stat()
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size)


def reconcile_duration(clip_duration: float, old_file_duration: float,
                       new_file_duration: float) -> float:
    """Duracao do clipe depois que o .wav mudou de tamanho no disco.

    Duas situacoes distintas:

    - o clipe usava o arquivo INTEIRO: acompanha o novo tamanho, para cima ou
      para baixo — foi para isso que o artista foi ao Audacity.
    - o clipe estava recortado na timeline: o recorte e decisao do artista e
      nao pode ser desfeita pela edicao; so encolhe se o arquivo agora for
      menor que ele.
    """
    if new_file_duration <= 0:
        return clip_duration
    if clip_duration >= old_file_duration - TRIM_TOLERANCE:
        return new_file_duration
    return min(clip_duration, new_file_duration)
