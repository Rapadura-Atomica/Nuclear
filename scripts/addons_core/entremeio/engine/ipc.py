"""Cliente IPC — fronteira para o motor de IA em processo separado (SPEC §7, RF-8.4).

O motor de IA roda num venv PRÓPRIO (PyTorch/CUDA), isolado do Python embarcado do
host (P4). A comunicação é LOCAL — aqui via subprocess (stdin/stdout), sem rede.
O add-on manda `PlanIR` serializado e recebe `GeneratedKeys`; o guarda-corpos roda
na volta ANTES de escrever (feito no operador, independente do engine).

`IPCEngine` implementa a MESMA interface `InbetweenEngine` do baseline/spline — o
motor de IA é órgão trocável: troca-se o worker, o resto do add-on não muda. O
worker de referência (`ipc_worker_reference.py`) roda o baseline determinístico e
prova a fronteira; depois é substituído por um worker PyTorch com o mesmo protocolo.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass

from ..ir import GeneratedKeys, PlanIR

PROTOCOL = "entremeio-ipc/1"


class IPCError(RuntimeError):
    """Falha na fronteira IPC — o operador captura e NÃO escreve nada."""


@dataclass(frozen=True)
class IPCParams:
    engine: str = "spline"          # qual engine o worker roda (referência)
    tension: float = 0.0
    overlap: float = 0.0
    style: float = 0.6              # "sotaque" do estúdio/IP p/ o motor de IA (RF-5.2)
    step: int = 1                   # densidade: 1 = todo frame; 2 = a cada 2 frames...
    timeout: float = 120.0          # segundos até desistir do worker


class IPCEngine:
    """Fala com um motor externo por subprocess. `worker_cmd` = [python, script, ...]."""

    def __init__(self, worker_cmd: list[str], addon_dir: str, params: IPCParams | None = None):
        self.worker_cmd = list(worker_cmd)
        self.addon_dir = addon_dir
        self.params = params or IPCParams()

    def generate(self, plan: PlanIR) -> GeneratedKeys:
        request = {
            "protocol": PROTOCOL,
            "addon_dir": self.addon_dir,          # p/ o worker importar ir/engine (bpy-free)
            "plan": plan.to_dict(),
            "engine": self.params.engine,
            "params": {"tension": self.params.tension, "overlap": self.params.overlap,
                       "style": self.params.style, "step": self.params.step},
            "seed": plan.seed,
        }
        payload = json.dumps(request).encode("utf-8")

        try:
            proc = subprocess.run(self.worker_cmd, input=payload,
                                  capture_output=True, timeout=self.params.timeout)
        except subprocess.TimeoutExpired as e:
            raise IPCError(f"motor de IA excedeu o tempo ({self.params.timeout}s)") from e
        except OSError as e:
            raise IPCError(f"não consegui iniciar o worker {self.worker_cmd!r}: {e}") from e

        if proc.returncode != 0:
            raise IPCError(f"worker falhou (rc={proc.returncode}): "
                           f"{proc.stderr.decode('utf-8', 'replace')[:500]}")
        try:
            response = json.loads(proc.stdout.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise IPCError(f"resposta ilegível do worker: {e}") from e

        if response.get("protocol") != PROTOCOL:
            raise IPCError(f"protocolo incompatível: {response.get('protocol')!r}")
        if not response.get("ok"):
            raise IPCError(f"worker rejeitou: {response.get('error')}")

        gen = GeneratedKeys.from_dict(response["generated"])
        # metadados para o relatório auditável (RF-6.5): model_version + seed viajam de volta
        self.last_model_version = response.get("model_version", "?")
        self.last_seed = response.get("seed", plan.seed)
        return gen


def reference_worker_path(addon_dir: str) -> str:
    return os.path.join(addon_dir, "ipc_worker_reference.py")


def make_reference_engine(addon_dir: str, python_exe: str | None = None,
                          params: IPCParams | None = None) -> IPCEngine:
    """Constrói um IPCEngine apontando para o worker de referência (baseline em subprocess).

    `python_exe` default = o Python atual; para o motor de IA real, aponte o Python do venv.
    """
    cmd = [python_exe or sys.executable, reference_worker_path(addon_dir)]
    return IPCEngine(cmd, addon_dir, params)
