"""Guarda-corpos de fidelidade (SPEC §8) — núcleo do produto (RF-6.x).

É o que torna P1/P2 VERIFICÁVEIS em vez de promessa. Roda sobre (PlanIR, GeneratedKeys)
ANTES de qualquer escrita e também na fronteira do IPC com o motor de IA: se qualquer
regra quebrar, REJEITA O LOTE INTEIRO (nunca escreve "por conta própria", RF-1.4/RF-6.x).

Checagens puras (sem bpy) implementadas aqui:
  (2) espaço de saída limitado: toda key gerada está numa peg existente, canal contínuo
      válido, com a aridade certa, e em frame ESTRITAMENTE entre duas âncoras desse canal.
  (3) canais discretos preservados: nenhuma key gerada em canal discreto.
  (4) sem staging novo: nenhuma peg fora do plano.
  (5) pontuação de aderência: desvio máx/médio vs. uma referência linear simples (RF-6.4).

A checagem (1) "âncoras intactas / drift = 0" exige reavaliar o rig no depsgraph e vive em
`rig_bridge.measure_fidelity` (precisa de bpy). Aqui fica o que é puro e serializável.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .ir import CONTINUOUS_CHANNELS, DISCRETE_CHANNELS, GeneratedKeys, PlanIR


@dataclass(frozen=True)
class Violation:
    peg: str
    frame: int
    channel: str
    rule: str           # id curto da regra ferida
    detail: str


@dataclass
class FidelityReport:
    ok: bool = True
    violations: list[Violation] = field(default_factory=list)
    # aderência por (peg, canal): {"max": float, "mean": float}
    adherence: dict[str, dict[str, float]] = field(default_factory=dict)
    generated_count: int = 0

    def add(self, v: Violation) -> None:
        self.violations.append(v)
        self.ok = False

    def summary(self) -> str:
        if self.ok:
            worst = max((m["max"] for m in self.adherence.values()), default=0.0)
            return f"OK — {self.generated_count} in-betweens, desvio máx vs. linear = {worst:.4g}"
        return f"REJEITADO — {len(self.violations)} violação(ões); 1ª: {self.violations[0].rule}"


def _anchor_frames_by_channel(plan: PlanIR) -> dict[str, dict[str, list[int]]]:
    """peg -> canal -> [frames de âncora ordenados] (só canais contínuos)."""
    out: dict[str, dict[str, list[int]]] = {}
    for t in plan.tracks:
        chan_frames: dict[str, list[int]] = {}
        for k in t.anchors:
            for c in k.values:
                if c in CONTINUOUS_CHANNELS:
                    chan_frames.setdefault(c, []).append(k.frame)
        for c in chan_frames:
            chan_frames[c].sort()
        out[t.peg.name] = chan_frames
    return out


def _strictly_between(frame: int, frames: list[int]) -> tuple[int, int] | None:
    """Retorna o par de âncoras (f0, f1) que cerca `frame`, ou None se não houver."""
    for f0, f1 in zip(frames, frames[1:]):
        if f0 < frame < f1:
            return (f0, f1)
    return None


def validate(plan: PlanIR, generated: GeneratedKeys) -> FidelityReport:
    """Roda o guarda-corpos. `report.ok == False` ⇒ NÃO escrever (P1/P2)."""
    report = FidelityReport(generated_count=generated.frame_count())
    anchors = _anchor_frames_by_channel(plan)
    plan_pegs = {t.peg.name for t in plan.tracks}

    for peg, keys in generated.per_peg.items():
        # (4) sem staging novo
        if peg not in plan_pegs:
            report.add(Violation(peg, -1, "*", "PEG_INEXISTENTE",
                                 f"peg '{peg}' não está no plano"))
            continue

        chan_frames = anchors.get(peg, {})
        for k in keys:
            for channel, comps in k.values.items():
                # (3) discreto nunca interpolado
                if channel in DISCRETE_CHANNELS:
                    report.add(Violation(peg, k.frame, channel, "CANAL_DISCRETO",
                                         "key gerada num canal discreto (preservar, não interpolar)"))
                    continue
                # canal contínuo válido?
                if channel not in CONTINUOUS_CHANNELS:
                    report.add(Violation(peg, k.frame, channel, "CANAL_DESCONHECIDO",
                                         f"canal '{channel}' não é animável"))
                    continue
                # aridade certa
                if len(comps) != CONTINUOUS_CHANNELS[channel]:
                    report.add(Violation(peg, k.frame, channel, "ARIDADE",
                                         f"{len(comps)} componentes, esperado {CONTINUOUS_CHANNELS[channel]}"))
                # (2) frame estritamente entre âncoras desse canal
                frames = chan_frames.get(channel)
                if not frames or len(frames) < 2:
                    report.add(Violation(peg, k.frame, channel, "SEM_ANCORA",
                                         "canal sem par de âncoras para cercar o in-between"))
                    continue
                if k.frame in frames:
                    report.add(Violation(peg, k.frame, channel, "SOBRE_ANCORA",
                                         "key gerada coincide com um frame de âncora"))
                    continue
                if _strictly_between(k.frame, frames) is None:
                    report.add(Violation(peg, k.frame, channel, "FORA_DO_VAO",
                                         "key gerada fora de qualquer vão entre âncoras"))

    if report.ok:
        _score_adherence(plan, generated, report)
    return report


def _score_adherence(plan: PlanIR, generated: GeneratedKeys, report: FidelityReport) -> None:
    """Desvio da geração vs. uma referência LINEAR simples (RF-6.4).

    Não é juízo de qualidade — é só um número auditável de "quanto o ease afastou
    do caminho reto". Útil pra sinalizar trechos e comparar engines depois.
    """
    plan_by_peg = {t.peg.name: t for t in plan.tracks}
    for peg, keys in generated.per_peg.items():
        track = plan_by_peg[peg]
        for channel in CONTINUOUS_CHANNELS:
            anchor_pts = [(k.frame, k.values[channel]) for k in track.anchors if channel in k.values]
            anchor_pts.sort()
            if len(anchor_pts) < 2:
                continue
            devs: list[float] = []
            for k in keys:
                if channel not in k.values:
                    continue
                seg = _strictly_between(k.frame, [f for f, _ in anchor_pts])
                if seg is None:
                    continue
                f0, f1 = seg
                v0 = next(v for f, v in anchor_pts if f == f0)
                v1 = next(v for f, v in anchor_pts if f == f1)
                t = (k.frame - f0) / (f1 - f0)
                for i, c in enumerate(k.values[channel]):
                    lin = v0[i] + (v1[i] - v0[i]) * t
                    devs.append(abs(c - lin))
            if devs:
                report.adherence[f"{peg}.{channel}"] = {
                    "max": max(devs), "mean": sum(devs) / len(devs),
                }
