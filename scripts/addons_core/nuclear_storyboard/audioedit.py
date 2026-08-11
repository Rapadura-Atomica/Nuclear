"""RF-18 — abrir o áudio no Audacity e recarregar sozinho quando ele salvar.

O editor externo trabalha no `.wav` que já está dentro do projeto, então não há
importação de volta: o que muda é o arquivo, e o que precisa acompanhar é a
duração do clipe e o som carregado na sessão.

O acompanhamento é por timer (`persistent=True`): o Audacity roda solto, não
avisa ninguém quando salva, e ficar perguntando o mtime de meia dúzia de
arquivos uma vez por segundo é barato. A parte que decide coisas — achar o
executável, comparar assinatura, reconciliar a duração — mora em
`core/audioedit.py` e é testada sem Blender.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Dict, Optional

import bpy

from . import audiotl, state, takefile
from .core.audioedit import (EditorNotFound, file_signature,
                             find_audio_editor, reconcile_duration)
from .core.wave_info import AudioError, wav_duration

INTERVAL = 1.0

#: Última mensagem do watcher, para o painel contar o que aconteceu — um timer
#: não tem `report()`.
LAST_MESSAGE = ""


@dataclass
class _Watch:
    take_id: str
    audio_id: str
    path: str
    signature: Optional[tuple]
    file_duration: float


#: audio_id -> _Watch
_WATCHED: Dict[str, _Watch] = {}


def _find_take_and_audio(store, watch: _Watch):
    found = store.project.find_take(watch.take_id)
    if found is None:
        return None, None
    take = found[2]
    audio = next((a for a in take.audios if a.id == watch.audio_id), None)
    return take, audio


def refresh_sound(scene, store, take, audio) -> None:
    """Faz a sessão reler o `.wav` do disco.

    Não existe operador de "reload" para um `Sound` no Blender: o datablock
    guarda o áudio decodificado e continua tocando a versão antiga mesmo depois
    de o arquivo mudar. O jeito confiável é jogar fora o clipe e o som e deixar
    o `sync_to_vse` remontar a partir do modelo — a posição e o recorte vêm do
    JSON, então nada se perde.
    """
    if scene is None:
        return
    collection = scene.sequence_editor.strips if scene.sequence_editor else None
    if collection is None:
        return

    sounds = set()
    for strip in audiotl.strips_of(scene):
        if strip.get(audiotl.AUDIO_ID_KEY) != audio.id:
            continue
        if getattr(strip, "sound", None) is not None:
            sounds.add(strip.sound)
        collection.remove(strip)

    for sound in sounds:
        if sound.users == 0:
            bpy.data.sounds.remove(sound)

    audiotl.sync_to_vse(scene, store, take)


def reload_audio(scene, store, take, audio) -> float:
    """Relê a duração do arquivo e ajusta o clipe. Devolve a nova duração."""
    path = store.paths.abs(audio.file)
    new_duration = wav_duration(path)

    # Sem vigia (recarga manual de um clipe que nunca foi ao editor) não há
    # tamanho anterior do arquivo guardado; assumir o do clipe faz o clipe
    # passar por "inteiro" e acompanhar o arquivo, que é o que se espera de um
    # botão chamado "recarregar".
    watch = _WATCHED.get(audio.id)
    old_file_duration = watch.file_duration if watch else audio.duration
    audio.duration = reconcile_duration(audio.duration, old_file_duration,
                                        new_duration)

    if watch is not None:
        watch.signature = file_signature(path)
        watch.file_duration = new_duration

    refresh_sound(scene, store, take, audio)
    # Um diálogo que ficou mais longo estica o take: sem isto o clipe novo
    # passava do fim da cena e os desenhos continuavam no tempo do áudio velho.
    # Vale para o botão e para o vigia do editor externo, que passam por aqui.
    takefile.refresh_take_view(scene, store, take, capture=False)
    return audio.duration


def launch(store, take, audio, editor: str = "") -> str:
    """Abre o `.wav` do clipe no editor externo e passa a vigiar o arquivo.

    Devolve o comando usado, para o operador conseguir dizer quem abriu.
    """
    path = store.paths.abs(audio.file)
    if not path.is_file():
        raise EditorNotFound(f"arquivo de áudio não encontrado: {audio.file}")

    command = find_audio_editor(editor)
    try:
        duration = wav_duration(path)
    except AudioError:
        duration = audio.duration

    # `start_new_session`: o editor não pode morrer junto com o Nuclear nem
    # herdar o terminal dele.
    subprocess.Popen([*command, str(path)], start_new_session=True)

    _WATCHED[audio.id] = _Watch(take_id=take.id, audio_id=audio.id,
                                path=str(path), signature=file_signature(path),
                                file_duration=duration)
    start()
    return " ".join(command)


def forget(audio_id: str = "") -> None:
    """Para de vigiar um clipe (ou todos, sem argumento)."""
    if audio_id:
        _WATCHED.pop(audio_id, None)
    else:
        _WATCHED.clear()
    if not _WATCHED:
        stop()


def watched_ids():
    return set(_WATCHED)


def _scene():
    window = getattr(bpy.context, "window", None)
    return getattr(window, "scene", None) or getattr(bpy.context, "scene", None)


def _tick():
    global LAST_MESSAGE
    store = state.get_store()
    if store is None or not _WATCHED:
        return INTERVAL

    scene = _scene()
    for watch in list(_WATCHED.values()):
        # O clipe pode ter saído do take enquanto o editor estava aberto. A
        # checagem vem ANTES da assinatura de propósito: um vigia órfão que só
        # some quando o arquivo muda mantém a UI mentindo até lá.
        take, audio = _find_take_and_audio(store, watch)
        if audio is None:
            forget(watch.audio_id)
            continue

        signature = file_signature(watch.path)
        if signature is None or signature == watch.signature:
            continue

        try:
            duration = reload_audio(scene, store, take, audio)
        except AudioError:
            # Salvamento pela metade: o arquivo ainda está sendo escrito.
            # Deixamos a assinatura antiga para tentar de novo no próximo tick.
            continue

        store.save()
        LAST_MESSAGE = f"{audio.name}: {duration:.2f}s"
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    return INTERVAL


def is_running() -> bool:
    return bpy.app.timers.is_registered(_tick)


def start() -> None:
    if not is_running():
        bpy.app.timers.register(_tick, persistent=True)


def stop() -> None:
    if is_running():
        bpy.app.timers.unregister(_tick)


def register() -> None:
    forget()


def unregister() -> None:
    forget()
