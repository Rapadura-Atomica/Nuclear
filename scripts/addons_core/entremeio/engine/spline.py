"""Engine spline determinístico (Hermite / Catmull-Rom) — resolve a limitação C0.

O baseline (ease pairwise) desacelera até PARAR em cada âncora — bom p/ 2 poses,
mas "engasga" quando o movimento deveria FLUIR por breakdowns (3+ poses). Este
engine interpola com Hermite cúbico dando continuidade C1:

- tangente ZERO na primeira e na última âncora  -> ease-in/out do movimento como um todo;
- tangente Catmull-Rom (diferença centrada) no interior -> velocidade contínua, flui pelas poses.

Degeneração elegante: com só 2 âncoras (sem interior), ambas as tangentes são 0
e o Hermite vira exatamente um smoothstep (ease-in-out) — mesmo resultado do baseline.
Passa EXATO por todas as âncoras (drift 0 preservado). Determinístico (sem RNG).

Implementa a interface InbetweenEngine (mesma fronteira onde a IA pluga depois).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..ir import CONTINUOUS_CHANNELS, GeneratedKeys, Keyframe, PlanIR
from .baseline import _channel_anchor_points

# amplitude máxima do lag de overlap (mantém a reparametrização monotônica)
_OVERLAP_MAX = 0.28


@dataclass(frozen=True)
class SplineParams:
    # 0 = Catmull-Rom cheio (flui bastante); 1 = tangentes nulas (vira linear/ease pairwise).
    tension: float = 0.0
    # 0 = sem drag; >0 = overlap/follow-through: pegs mais fundas na hierarquia "arrastam".
    overlap: float = 0.0
    # densidade: 1 = keyframe em todo frame; 2 = a cada 2 frames ("nos dois")...
    step: int = 1


def _depths(tracks) -> list[int]:
    """Profundidade de cada peg na hierarquia (root=0), via parent_index nos tracks."""
    n = len(tracks)
    depth = [-1] * n
    def resolve(i, guard=0):
        if depth[i] >= 0:
            return depth[i]
        p = tracks[i].peg.parent
        depth[i] = 0 if (p < 0 or p >= n or guard > n) else resolve(p, guard + 1) + 1
        return depth[i]
    for i in range(n):
        resolve(i)
    return depth


def _lag_warp(s: float, amp: float) -> float:
    """Reparametriza s∈[0,1] atrasando o meio (bump sin que zera nas pontas).

    s_eff < s no interior -> a peg fica "para trás" e depois recupera. amp limitado
    p/ manter monotônico e s_eff(0)=0, s_eff(1)=1 (âncoras intactas)."""
    return s - amp * math.sin(math.pi * s)


def _hermite(p0: float, p1: float, m0: float, m1: float, s: float) -> float:
    """Hermite cúbico em s∈[0,1]. m0/m1 já escalados p/ o segmento. Passa por p0,p1."""
    s2 = s * s
    s3 = s2 * s
    h00 = 2 * s3 - 3 * s2 + 1
    h10 = s3 - 2 * s2 + s
    h01 = -2 * s3 + 3 * s2
    h11 = s3 - s2
    return h00 * p0 + h10 * m0 + h01 * p1 + h11 * m1


def _tangents(frames: list[int], values: list[float], tension: float) -> list[float]:
    """dv/dframe em cada âncora: 0 nas pontas, Catmull-Rom (centrado) no interior."""
    n = len(frames)
    m = [0.0] * n
    scale = 1.0 - tension
    for i in range(1, n - 1):
        df = frames[i + 1] - frames[i - 1]
        if df != 0:
            m[i] = scale * (values[i + 1] - values[i - 1]) / df
    return m


class SplineEngine:
    """Engine Hermite/Catmull-Rom (implementa InbetweenEngine)."""

    def __init__(self, params: SplineParams | None = None):
        self.params = params or SplineParams()

    def generate(self, plan: PlanIR) -> GeneratedKeys:
        per_peg: dict[str, list[Keyframe]] = {}

        # lag de overlap por profundidade (normalizado pela peg mais funda)
        depths = _depths(plan.tracks)
        max_depth = max(depths) if depths else 0
        overlap = max(0.0, min(1.0, self.params.overlap))

        for idx, track in enumerate(plan.tracks):
            lag_amp = 0.0
            if overlap > 0.0 and max_depth > 0:
                lag_amp = overlap * _OVERLAP_MAX * (depths[idx] / max_depth)
            frame_values: dict[int, dict[str, tuple[float, ...]]] = {}

            for channel in CONTINUOUS_CHANNELS:
                pts = _channel_anchor_points(track, channel)
                if len(pts) < 2:
                    continue
                frames = [f for f, _ in pts]
                vecs = [v for _, v in pts]
                arity = len(vecs[0])

                # tangente por componente, em cada âncora
                comp_tangents = [
                    _tangents(frames, [v[c] for v in vecs], self.params.tension)
                    for c in range(arity)
                ]

                for i in range(len(frames) - 1):
                    f0, f1 = frames[i], frames[i + 1]
                    h = f1 - f0
                    if h <= 1:
                        continue  # sem buraco entre âncoras adjacentes
                    step = max(1, self.params.step)
                    for frame in range(f0 + step, f1, step):
                        s = (frame - f0) / h
                        if lag_amp:
                            s = _lag_warp(s, lag_amp)   # overlap: filhas arrastam
                        comps = tuple(
                            _hermite(vecs[i][c], vecs[i + 1][c],
                                     comp_tangents[c][i] * h, comp_tangents[c][i + 1] * h, s)
                            for c in range(arity)
                        )
                        frame_values.setdefault(frame, {})[channel] = comps

            if frame_values:
                per_peg[track.name] = [Keyframe(frame=f, values=frame_values[f])
                                       for f in sorted(frame_values)]

        return GeneratedKeys(per_peg=per_peg)
