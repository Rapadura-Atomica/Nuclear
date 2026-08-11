"""Timeline de áudio do take, em cima do VSE.

O Video Sequence Editor já desenha waveform, arrasta clipe, permite sobrepor e
toca o som junto com o playback — reimplementar isso à mão seria trabalho jogado
fora. Aqui só fazemos a ponte nos dois sentidos:

    modelo -> VSE   `sync_to_vse`, ao abrir o take
    VSE -> modelo   `sync_from_vse`, quando o artista mexeu nos clipes

Cada clipe carrega o id do áudio (`nsb_audio`) para o casamento não depender do
nome, que o artista pode trocar.
"""

from __future__ import annotations

from typing import List

import bpy

AUDIO_ID_KEY = "nsb_audio"


def _strip_collection(se):
    """`sequences` virou `strips` no 5.0.

    Cuidado com `getattr(...) or ...`: coleção vazia é falsy e derruba para o
    nome antigo, que não existe mais.
    """
    return se.strips if hasattr(se, "strips") else se.sequences


def strips_of(scene):
    se = scene.sequence_editor
    return list(_strip_collection(se)) if se is not None else []


def _collection(scene):
    se = scene.sequence_editor or scene.sequence_editor_create()
    return _strip_collection(se)


def seconds_to_frame(seconds: float, fps: int) -> int:
    """Segundo 0 do take é o frame 1 da cena."""
    return int(round(seconds * fps)) + 1


def frame_to_seconds(frame: float, fps: int) -> float:
    return max(0.0, (float(frame) - 1.0) / fps)


def _place_strip(strip, audio, fps: int) -> None:
    """Põe o clipe no lugar e no tamanho que o modelo manda.

    Duas armadilhas, as duas em cima do corte de CABEÇA (`frame_offset_start`):

    - `frame_start` é onde o clipe começaria SEM corte; quem soa no tempo certo
      é `frame_final_start`. Como `sync_from_vse` lê o final e escrevíamos no
      cru, cada ciclo abrir→salvar empurrava um clipe cortado para frente pelo
      tamanho do próprio corte, acumulando dessincronia.
    - o corte é só metadado do clipe: recriar a strip do zero traz o `.wav`
      inteiro de volta. Sem reaplicar a duração do modelo, o recorte do artista
      se perde toda vez que a timeline é remontada a partir do JSON.
    """
    offset = max(0, int(round(getattr(audio, "offset", 0.0) * fps)))
    strip.frame_start = seconds_to_frame(audio.start, fps) - offset
    if hasattr(strip, "frame_offset_start") and offset:
        strip.frame_offset_start = offset

    wanted = max(1, int(round(audio.duration * fps)))
    if audio.duration > 0 and strip.frame_final_duration != wanted:
        strip.frame_final_duration = wanted


def sync_to_vse(scene, store, take) -> int:
    """Põe cada áudio do take na timeline, com waveform ligada.

    Um clipe por canal para nunca se esconderem: sobrepor no tempo é permitido
    (RF-A02), sobrepor visualmente só atrapalha.
    """
    fps = store.project.settings.fps
    collection = _collection(scene)

    existing = {s.get(AUDIO_ID_KEY): s for s in strips_of(scene) if s.get(AUDIO_ID_KEY)}
    for audio in take.audios:
        path = store.paths.abs(audio.file)
        strip = existing.pop(audio.id, None)
        if strip is None:
            if not path.is_file():
                continue
            strip = collection.new_sound(
                name=audio.name or path.stem, filepath=str(path),
                channel=len(strips_of(scene)) + 1,
                frame_start=seconds_to_frame(audio.start, fps))
            strip[AUDIO_ID_KEY] = audio.id
        _place_strip(strip, audio, fps)
        strip.show_waveform = True

    # Clipes de áudios que sumiram do take não têm por que continuar na tela.
    for orphan in existing.values():
        collection.remove(orphan)

    return len(take.audios)


def sync_from_vse(scene, take, fps: int) -> int:
    """Lê posição e recorte dos clipes de volta para o modelo.

    Arrastar move o início; cortar a ponta encurta a duração — as duas coisas
    são metadado, o `.wav` no disco não é tocado (RF-T02).
    """
    changed = 0
    by_id = {a.id: a for a in take.audios}
    for strip in strips_of(scene):
        audio = by_id.get(strip.get(AUDIO_ID_KEY))
        if audio is None:
            continue
        start = frame_to_seconds(strip.frame_final_start, fps)
        duration = max(0.0, strip.frame_final_duration / float(fps))
        offset = max(0.0, int(getattr(strip, "frame_offset_start", 0) or 0) / float(fps))
        if (abs(audio.start - start) > 1e-6 or abs(audio.duration - duration) > 1e-6
                or abs(getattr(audio, "offset", 0.0) - offset) > 1e-6):
            audio.start, audio.duration, audio.offset = start, duration, offset
            changed += 1
    return changed


def apply_take_range(scene, take, fps: int) -> int:
    """Ajusta o range de playback da cena à duração do take."""
    from .core import take_duration
    from .core.timing import seconds_to_frames

    total = seconds_to_frames(take_duration(take), fps)
    scene.frame_start = 1
    scene.frame_end = total
    # AUDIO_SYNC: o playback casa os frames com o clock do áudio.
    # Sem isso o VSE toca frames o mais rápido que der e o áudio deriva.
    scene.sync_mode = "AUDIO_SYNC"
    return total


def orphan_strips(scene, take) -> List[str]:
    """Clipes de som na timeline que não pertencem a nenhum áudio do take."""
    known = {a.id for a in take.audios}
    return [s.name for s in strips_of(scene)
            if s.type == "SOUND" and s.get(AUDIO_ID_KEY) not in known]
