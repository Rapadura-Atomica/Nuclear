"""Baseline determinístico da Fase 0 (SPEC §6.2).

Gera in-betweens no espaço das pegs por interpolação com ease/spacing, canal a
canal, entre âncoras consecutivas. É determinístico por `seed` (RF-4.4) e é a
RÉGUA contra a qual a aceitação do motor de IA será medida.

Princípios respeitados por construção:
- O ANIMATIC decide quantos frames: gera-se um in-between em cada frame inteiro
  ESTRITAMENTE entre duas âncoras de um canal — nunca o motor inventa contagem (RF-1.3).
- Passa exatamente pelas âncoras: os termos de ease e de overshoot zeram nos
  extremos (t=0 e t=1), então as âncoras nunca sofrem drift (P1, RF-6.1).
- Canais discretos (use_squash, cells) são IGNORADOS — preservados, nunca interpolados (RF-4.6).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from ..ir import CONTINUOUS_CHANNELS, GeneratedKeys, Keyframe, PlanIR


@dataclass(frozen=True)
class BaselineParams:
    # 0 = linear puro; 1 = smoothstep (ease-in-out) cheio. Distribui o spacing.
    ease: float = 0.6
    # amplitude de overshoot pseudo-aleatório por segmento (0 = desligado).
    # Zera nos extremos -> não fere as âncoras. Usa `seed` para ser reprodutível.
    overshoot: float = 0.0
    # densidade: 1 = keyframe em todo frame ("nos uns"); 2 = a cada 2 frames ("nos dois")...
    step: int = 1


def _ease(t: float, strength: float) -> float:
    """Reparametriza t in [0,1] preservando extremos: ease(0)=0, ease(1)=1."""
    smooth = t * t * (3.0 - 2.0 * t)            # smoothstep
    return (1.0 - strength) * t + strength * smooth


def _channel_anchor_points(track, channel: str) -> list[tuple[int, tuple[float, ...]]]:
    """(frame, valor) das âncoras que têm esse canal, ordenado por frame.

    Coerção defensiva do frame para int: âncoras vivem em frames inteiros; blinda
    contra entrada float (ex.: um motor de IA que devolva frame float via IPC).
    """
    pts = [(int(round(k.frame)), k.values[channel])
           for k in track.anchors if channel in k.values]
    pts.sort(key=lambda p: p[0])
    return pts


class BaselineEngine:
    """Engine determinístico (implementa InbetweenEngine)."""

    def __init__(self, params: BaselineParams | None = None):
        self.params = params or BaselineParams()

    def generate(self, plan: PlanIR) -> GeneratedKeys:
        per_peg: dict[str, list[Keyframe]] = {}

        for track in plan.tracks:
            # acumula valores por frame -> {canal: componentes}
            frame_values: dict[int, dict[str, tuple[float, ...]]] = {}

            for channel in CONTINUOUS_CHANNELS:           # só canais contínuos
                pts = _channel_anchor_points(track, channel)
                if len(pts) < 2:
                    continue                              # nada a interpolar
                for (f0, v0), (f1, v1) in zip(pts, pts[1:]):
                    self._fill_segment(track.name, channel, f0, v0, f1, v1,
                                       plan.seed, frame_values)

            if frame_values:
                keys = [Keyframe(frame=f, values=frame_values[f]) for f in sorted(frame_values)]
                per_peg[track.name] = keys

        return GeneratedKeys(per_peg=per_peg)

    def _fill_segment(self, peg, channel, f0, v0, f1, v1, seed, frame_values):
        span = f1 - f0
        if span <= 1:
            return                                        # frames adjacentes: sem buraco
        # RNG determinístico por (seed, peg, canal, segmento) — sem Math.random global
        rng = random.Random(f"{seed}|{peg}|{channel}|{f0}|{f1}")
        over = self.params.overshoot
        amp = [rng.uniform(-1.0, 1.0) for _ in range(len(v0))] if over else None

        step = max(1, self.params.step)
        for frame in range(f0 + step, f1, step):          # de `step` em `step`, entre as âncoras
            t = (frame - f0) / span
            e = _ease(t, self.params.ease)
            comps = []
            for i, (a, b) in enumerate(zip(v0, v1)):
                val = a + (b - a) * e
                if over:
                    # bump que zera nos extremos (sin(pi*t)); mantém âncoras intactas
                    val += over * math.sin(math.pi * t) * (b - a) * amp[i]
                comps.append(val)
            frame_values.setdefault(frame, {})[channel] = tuple(comps)
