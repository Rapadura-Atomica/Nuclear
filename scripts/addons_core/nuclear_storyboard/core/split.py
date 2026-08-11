"""Partir um take em dois no frame em que o artista parou.

O critério de onde um take termina é do ARTISTA: ele anda até o quadro do corte
e manda partir. Aqui só se decide o que vai para cada lado — desenhos, falas e
tempo — sem tocar em arquivo nem em `bpy`, para poder ser testado no host.

Regras:
  - o corte é o PRIMEIRO frame do take novo (cortar no 1 não faz sentido);
  - o desenho que estava em hold no corte continua na tela: ele reaparece como
    primeiro desenho do take novo, sem duplicar arte (é o mesmo keyframe);
  - a fala que atravessa o corte é partida em duas, e a segunda metade toca do
    ponto certo do arquivo (`offset`) — é para isso que o campo existe;
  - a soma das durações não muda: partir um take não estica nem encolhe a cena.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

from .model import Audio, Drawing, Take
from .timing import distribute_exposures, seconds_to_frames, take_duration


class SplitError(Exception):
    """O corte pedido não parte o take em dois pedaços válidos."""


@dataclass
class SidePlan:
    """O que fica de um lado do corte."""

    frames: int
    drawings: List[Drawing] = field(default_factory=list)
    audios: List[Audio] = field(default_factory=list)


def positions(take: Take, fps: int) -> List[int]:
    """Onde cada desenho começa, em frames, segundo o timing do take."""
    spans = distribute_exposures(take, fps)
    out, cursor = [], 1
    for span in spans:
        out.append(cursor)
        cursor += span
    return out


def split_plan(take: Take, frame: int, fps: int) -> Tuple[SidePlan, SidePlan]:
    """Como o take fica partido no `frame` (1-based, primeiro frame do novo)."""
    total = seconds_to_frames(take_duration(take), fps)
    if frame <= 1 or frame > total:
        raise SplitError(
            f"o corte precisa cair entre o frame 2 e o {total}; veio {frame}")
    if not take.drawings:
        raise SplitError("take sem desenho não tem o que partir")

    inicio = positions(take, fps)
    antes = SidePlan(frames=frame - 1)
    depois = SidePlan(frames=total - frame + 1)

    # --- desenhos ---------------------------------------------------------
    for drawing, pos in zip(take.drawings, inicio):
        lado, novo_pos = ((antes, pos) if pos < frame
                          else (depois, pos - frame + 1))
        lado.drawings.append(_clone_drawing(drawing, novo_pos))

    if not depois.drawings:
        # O corte caiu depois do último desenho: o take novo mostra o que estava
        # em hold, senão abriria em branco.
        depois.drawings.append(_clone_drawing(take.drawings[-1], 1))
    elif depois.drawings[0].frame > 1:
        anterior = [d for d, p in zip(take.drawings, inicio) if p < frame]
        if anterior:
            depois.drawings.insert(0, _clone_drawing(anterior[-1], 1))

    for lado in (antes, depois):
        _reexpose(lado, fps)
        _renumber(lado)

    # --- falas ------------------------------------------------------------
    corte_s = (frame - 1) / float(fps)
    for audio in take.audios:
        if audio.start < corte_s:
            fim = min(audio.end, corte_s)
            antes.audios.append(_clone_audio(
                audio, start=audio.start, duration=fim - audio.start,
                offset=audio.offset))
        if audio.end > corte_s:
            comeco = max(audio.start, corte_s)
            depois.audios.append(_clone_audio(
                audio, start=comeco - corte_s, duration=audio.end - comeco,
                offset=audio.offset + (comeco - audio.start)))

    return antes, depois


def _clone_drawing(drawing: Drawing, frame: int) -> Drawing:
    """Cópia do desenho na posição nova. O nome é renumerado depois.

    O PNG já renderizado viaja junto: a arte é a mesma, e re-render é a parte
    cara do export.
    """
    return Drawing(name=drawing.name, frame=frame, png=drawing.png,
                   exposure=drawing.exposure)


def _renumber(side: SidePlan) -> None:
    """Cada lado conta os desenhos do primeiro: "D003" num take novo confunde."""
    for i, drawing in enumerate(side.drawings, start=1):
        drawing.name = f"D{i:03d}"


def _clone_audio(audio: Audio, start: float, duration: float,
                 offset: float) -> Audio:
    return Audio(name=audio.name, file=audio.file, start=max(0.0, start),
                 duration=max(0.0, duration), offset=max(0.0, offset))


def _reexpose(side: SidePlan, fps: int) -> None:
    """Fixa a exposição de cada desenho pelo espaço que ele ocupa no lado.

    O timing dos dois pedaços já está decidido pelo take original — deixar em
    automático faria os desenhos se redistribuírem sozinhos e o corte mudaria a
    cena, que é o oposto de partir um take.
    """
    limites = [d.frame for d in side.drawings] + [side.frames + 1]
    for i, drawing in enumerate(side.drawings):
        drawing.exposure = max(1, limites[i + 1] - limites[i]) / float(fps)
