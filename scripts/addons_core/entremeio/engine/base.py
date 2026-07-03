"""Interface do engine de geração (SPEC Fase 0, §6.1).

Contrato ESTÁVEL: não muda entre a Fase 0 (baseline local determinístico) e a
Fase 1 (motor de IA via IPC). O resto do add-on só conhece esta interface — é o
que permite trocar o órgão (baseline <-> IA) sem reescrever produto.
"""

from __future__ import annotations

from typing import Protocol

from ..ir import GeneratedKeys, PlanIR


class InbetweenEngine(Protocol):
    def generate(self, plan: PlanIR) -> GeneratedKeys:
        """Recebe um PlanIR (âncoras rígidas) e devolve SÓ os in-betweens novos.

        Invariantes que o guarda-corpos cobra depois (P1/P2):
        - nunca emitir key num frame de âncora;
        - nunca emitir canal/peg ausente no plano;
        - nunca emitir canal discreto (preservado, não interpolado).
        """
        ...
