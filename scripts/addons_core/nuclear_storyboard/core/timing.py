"""Timing do take e da timeline geral.

Regras do PRD:
  RF-A03  duracao do take = fim do ultimo audio + AUDIO_TAIL, com ajuste manual.
          A cauda era 0,5s e foi zerada em 2026-07-31: a cena acaba junto com a
          fala.
  RF-T02  timing e metadado; nunca toca no desenho original.
  RF-T03  entre desenhos so existe HOLD — nenhum inbetween, nenhuma transicao.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from .model import AUDIO_TAIL, DEFAULT_SILENT_TAKE, Project, Take


def take_duration(take: Take) -> float:
    """Duracao do take em segundos.

    Precedencia: ajuste manual > ultimo audio + cauda > fallback do take mudo.
    """
    if take.duration_override is not None:
        return max(0.0, float(take.duration_override))
    if take.audios:
        return max(a.end for a in take.audios) + AUDIO_TAIL
    return DEFAULT_SILENT_TAKE


def seconds_to_frames(seconds: float, fps: int) -> int:
    """Converte para frames, sempre com no minimo 1 frame."""
    return max(1, int(round(seconds * fps)))


def distribute_exposures(take: Take, fps: int) -> List[int]:
    """Reparte a duracao do take entre os desenhos, em FRAMES.

    Desenhos com `exposure` declarada ficam com o que pediram; o que sobra e
    dividido igualmente entre os demais. A soma bate exatamente com a duracao
    do take: o resto da divisao inteira e distribuido nos primeiros desenhos
    automaticos, entao nao ha frame perdido nem estourado.
    """
    n = len(take.drawings)
    if n == 0:
        return []

    total_frames = seconds_to_frames(take_duration(take), fps)
    frames: List[int] = [0] * n

    fixed_idx = [i for i, d in enumerate(take.drawings) if d.exposure is not None]
    auto_idx = [i for i, d in enumerate(take.drawings) if d.exposure is None]

    for i in fixed_idx:
        frames[i] = seconds_to_frames(take.drawings[i].exposure, fps)

    if not auto_idx:
        # Tudo manual: a soma manda, o take estica ou encolhe conforme pedido.
        return frames

    remaining = total_frames - sum(frames[i] for i in fixed_idx)
    # Cada desenho automatico precisa aparecer ao menos 1 frame, mesmo que os
    # manuais ja tenham comido a duracao inteira.
    remaining = max(remaining, len(auto_idx))

    base, extra = divmod(remaining, len(auto_idx))
    for k, i in enumerate(auto_idx):
        frames[i] = base + (1 if k < extra else 0)
    return frames


@dataclass
class TakeSlice:
    """Um take posicionado na timeline geral do animatic."""

    episode_code: str
    scene_code: str
    take_code: str
    take_id: str
    start_frame: int
    frames: int
    drawing_frames: List[int]  # exposicao de cada desenho, em frames

    @property
    def end_frame(self) -> int:
        return self.start_frame + self.frames


def build_timeline(project: Project,
                   take_ids: Optional[Iterable[str]] = None) -> Tuple[List[TakeSlice], int]:
    """Monta a timeline do animatic: takes emendados na ordem do documento.

    Corte seco entre desenhos e entre takes (RN05) — nenhum crossfade.
    Retorna (fatias, total de frames).

    `take_ids` restringe a montagem a um recorte (RF-13: assistir so uma cena ou
    um episodio). O recorte comeca no frame 0: e um animatic proprio, nao um
    pedaco do animatic do projeto.
    """
    fps = project.settings.fps
    wanted = set(take_ids) if take_ids is not None else None
    slices: List[TakeSlice] = []
    cursor = 0
    for ep, sc, tk in project.iter_takes():
        if wanted is not None and tk.id not in wanted:
            continue
        drawing_frames = distribute_exposures(tk, fps)
        frames = sum(drawing_frames) if drawing_frames else seconds_to_frames(take_duration(tk), fps)
        slices.append(TakeSlice(
            episode_code=ep.code or ep.name,
            scene_code=sc.code or sc.name,
            take_code=tk.code or tk.name,
            take_id=tk.id,
            start_frame=cursor,
            frames=frames,
            drawing_frames=drawing_frames,
        ))
        cursor += frames
    return slices, cursor
