"""Ponte entre a exposição de cada desenho (metadado) e os keyframes do GP.

    keyframes -> modelo   `absorb_manual_timing`, no salvar: o que o artista
                          arrastou na dopesheet PASSA A SER o timing do take
    modelo -> keyframes   `apply_exposures`, para espalhar os desenhos de novo
                          na duração que veio do áudio

A direção keyframes→modelo era um botão ("ler o timing dos desenhos") e virou
automática: arrastar um keyframe é a maneira mais direta de dizer "este desenho
dura mais", e pedir confirmação por botão só criava um jeito de perder o
trabalho. A volta continua explícita, porque desfaz o que o artista fez.

Nada disso toca no desenho em si: mudar exposição é mudar quando o mesmo
keyframe aparece, e entre eles continua havendo só hold (RN05, RF-T02).
"""

from __future__ import annotations

from typing import List

from . import gp
from .core import take_duration
from .core.timing import distribute_exposures, seconds_to_frames

#: Deslocamento usado para estacionar keyframes fora do caminho enquanto
#: reposicionamos: mover um a um colidiria com os que ainda não saíram do lugar.
PARKING = 1_000_000


def read_exposures(take, ob, fps: int) -> int:
    """Grava a exposição dos desenhos que saíram da divisão automática.

    O último desenho fica com o que sobra até o fim do take; se ele acabar
    passando do fim (o artista puxou o keyframe para longe), ganha ao menos um
    frame.

    Só vira tempo fixo o desenho cujo span DIVERGE do que a divisão automática
    daria. Gravar todos — como era antes — congelava o take inteiro por causa de
    um único keyframe arrastado: os outros desenhos paravam de acompanhar o
    áudio, e um diálogo mais longo depois já não os redistribuía.
    """
    frames = gp.drawing_frames(ob)
    if not frames:
        return 0

    gp.sync_drawings_from_gp(take, ob)
    auto = distribute_exposures(take, fps)
    total = seconds_to_frames(take_duration(take), fps)
    end = max(total + 1, frames[-1] + 1)

    boundaries = frames + [end]
    changed = 0
    for i, drawing in enumerate(take.drawings):
        span = max(1, boundaries[i + 1] - boundaries[i])
        if i < len(auto) and span == auto[i]:
            continue
        drawing.exposure = span / float(fps)
        changed += 1
    return changed


def planned_frames(take, fps: int) -> List[int]:
    """Onde cada desenho deveria começar, dadas as exposições do modelo."""
    spans = distribute_exposures(take, fps)
    positions, cursor = [], 1
    for span in spans:
        positions.append(cursor)
        cursor += span
    return positions


def apply_exposures(take, ob, fps: int) -> int:
    """Move os keyframes para as posições que o timing do modelo pede.

    Devolve quantos keyframes mudaram de lugar.
    """
    current = gp.drawing_frames(ob)
    target = planned_frames(take, fps)
    if not current or len(current) != len(target) or current == target:
        return 0

    layers = [l for l in ob.data.layers if l.frames]
    moved = 0

    # Primeiro todo mundo sai do caminho, depois cada um pousa no lugar novo —
    # assim nenhum destino esbarra num keyframe que ainda não se moveu.
    for layer in layers:
        for number in sorted({f.frame_number for f in layer.frames}, reverse=True):
            if number in current:
                layer.frames.move(number, number + PARKING)

    for layer in layers:
        for old, new in zip(current, target):
            if gp.frame_at(layer, old + PARKING) is not None:
                layer.frames.move(old + PARKING, new)
                if old != new:
                    moved += 1

    # Reescrever o frame na ordem, sem passar por `sync_drawings_from_gp`: ele
    # casa desenho com keyframe pelo NÚMERO do frame, e eles acabaram de mudar
    # de lugar — cada desenho viraria um registro novo, perdendo id, nome, tempo
    # ajustado à mão e o PNG já renderizado. A ordem, essa, não muda.
    for drawing, number in zip(take.drawings, target):
        drawing.frame = number
    return moved


def absorb_manual_timing(take, ob, fps: int, reference: List[int] = None) -> int:
    """Guarda o timing dos keyframes quando ele saiu da divisão automática.

    Chamada ao salvar o take. Se os keyframes estão exatamente onde a divisão
    automática os colocaria, não há nada de manual a guardar — e gravar mesmo
    assim congelaria o take: um áudio mais longo depois já não redistribuiria
    os desenhos.

    `reference` é onde a divisão automática os punha ANTES de o áudio ser lido
    de volta na mesma passada. Sem isso, cortar um clipe na timeline congelava o
    take inteiro: a duração encolhia, os keyframes continuavam no lugar de
    antes, e a comparação com a divisão nova os acusava de arrastados.
    """
    frames = gp.drawing_frames(ob)
    if not frames or frames == planned_frames(take, fps):
        return 0
    if reference is not None and frames == reference:
        return 0
    return read_exposures(take, ob, fps)


def clear_exposures(take) -> int:
    """Volta todos os desenhos para a divisão automática da duração."""
    count = sum(1 for d in take.drawings if d.exposure is not None)
    for drawing in take.drawings:
        drawing.exposure = None
    return count
