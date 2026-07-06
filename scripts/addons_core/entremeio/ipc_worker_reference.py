#!/usr/bin/env python3
"""Worker de referência da fronteira IPC do Entremeio (SPEC §7).

Roda em PROCESSO SEPARADO (subprocess). Lê um pedido JSON em stdin, reconstrói o
`PlanIR`, gera in-betweens com o engine determinístico (baseline/spline) e devolve
`GeneratedKeys` JSON em stdout. É um STAND-IN do motor de IA — o processo real de
PyTorch usará EXATAMENTE o mesmo protocolo stdin/stdout, então trocar o cérebro não
mexe no add-on.

Protocolo (entremeio-ipc/1):
  entrada:  {"protocol","addon_dir","plan","engine","params","seed"}
  saída ok: {"protocol","ok":true,"generated","model_version","seed"}
  saída erro: {"protocol","ok":false,"error"}   (erros vão NO protocolo, rc=0)

Importa ir/engine do add-on de forma bpy-free (pacote sintético), então roda em
qualquer Python 3.10+ — inclusive o venv isolado do motor de IA.
"""

import json
import os
import sys
import types

PROTOCOL = "entremeio-ipc/1"


def _load_engine_modules(addon_dir):
    """Importa ir + engines do add-on sem tocar em bpy (pacote sintético)."""
    import importlib

    pkg = types.ModuleType("ent_worker")
    pkg.__path__ = [addon_dir]
    sys.modules["ent_worker"] = pkg
    epkg = types.ModuleType("ent_worker.engine")
    epkg.__path__ = [os.path.join(addon_dir, "engine")]
    sys.modules["ent_worker.engine"] = epkg

    ir = importlib.import_module("ent_worker.ir")
    baseline = importlib.import_module("ent_worker.engine.baseline")
    spline = importlib.import_module("ent_worker.engine.spline")
    return ir, baseline, spline


def _run(request):
    ir, baseline, spline = _load_engine_modules(request["addon_dir"])
    plan = ir.PlanIR.from_dict(request["plan"])
    p = request.get("params", {})
    engine_name = request.get("engine", "spline")

    step = int(p.get("step", 1))
    if engine_name == "baseline":
        engine = baseline.BaselineEngine(baseline.BaselineParams(
            ease=p.get("ease", 0.6), overshoot=p.get("overshoot", 0.0), step=step))
    else:
        engine = spline.SplineEngine(spline.SplineParams(
            tension=p.get("tension", 0.0), overlap=p.get("overlap", 0.0), step=step))

    generated = engine.generate(plan)
    return {
        "protocol": PROTOCOL,
        "ok": True,
        "generated": generated.to_dict(),
        "model_version": f"reference-{engine_name}-0.1",
        "seed": request.get("seed", plan.seed),
    }


def main():
    try:
        request = json.loads(sys.stdin.read())
        if request.get("protocol") != PROTOCOL:
            raise ValueError(f"protocolo inesperado: {request.get('protocol')!r}")
        response = _run(request)
    except Exception as e:  # noqa: BLE001 — erro reportado NO protocolo, nunca via crash
        response = {"protocol": PROTOCOL, "ok": False, "error": f"{type(e).__name__}: {e}"}
    sys.stdout.write(json.dumps(response))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
