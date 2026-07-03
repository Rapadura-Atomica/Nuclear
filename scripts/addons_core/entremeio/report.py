"""Relatório auditável (RF-6.5 / RF-9.4) — o que torna P1/P2 rastreáveis.

Registra CADA geração como artefato versionável: rig, trecho, engine + parâmetros,
seed, versão do modelo, contagens, drift nas âncoras, aderência por canal e
preservação da exposição. Salva JSON (máquina) + resumo .txt (humano) — para
versionamento, revisão e auditoria (nada sai do estúdio).

`build_report` é puro (sem bpy) — o operador passa o que já calculou. `write_report`
grava os dois arquivos.
"""

from __future__ import annotations

import json
import os

REPORT_SCHEMA = "entremeio-report/1"


def build_report(*, rig_name, plan, generated, engine, seed,
                 fidelity_report, drift_max, drift_offenders,
                 exposure_ok, keyframes_inserted, timing_ms, timestamp):
    """Monta o dict do relatório a partir do que o operador já tem em mãos."""
    anchor_frames = sorted({k.frame for t in plan.tracks for k in t.anchors})
    pegs_animated = [t.name for t in plan.tracks if t.anchors]

    return {
        "schema": REPORT_SCHEMA,
        "timestamp": timestamp,
        "rig": rig_name,
        "frame_range": [plan.frame_start, plan.frame_end],
        "engine": engine,              # {"mode","model_version","params"}
        "seed": seed,
        "counts": {
            "anchor_frames": len(anchor_frames),
            "pegs_animated": len(pegs_animated),
            "in_betweens": generated.frame_count(),
            "keyframes_inserted": keyframes_inserted,
        },
        "fidelity": {
            "ok": bool(fidelity_report.ok),
            "drift_max": round(float(drift_max), 9),
            "drift_offenders": [
                {"peg": p, "frame": f, "channel": c, "drift": round(float(d), 6)}
                for (p, f, c, d) in drift_offenders
            ],
            "exposure_preserved": bool(exposure_ok),
            "violations": [
                {"rule": v.rule, "peg": v.peg, "frame": v.frame,
                 "channel": v.channel, "detail": v.detail}
                for v in fidelity_report.violations
            ],
            "adherence_vs_linear": fidelity_report.adherence,
        },
        "timing_ms": timing_ms,
    }


def summarize(report) -> str:
    """Resumo humano (uma tela) do relatório."""
    c, fid = report["counts"], report["fidelity"]
    lines = [
        f"Entremeio — relatório  ({report['timestamp']})",
        f"  rig: {report['rig']}   trecho: {report['frame_range'][0]}-{report['frame_range'][1]}",
        f"  engine: {report['engine'].get('mode')} "
        f"(modelo {report['engine'].get('model_version', '-')})  seed: {report['seed']}",
        f"  params: {report['engine'].get('params', {})}",
        f"  âncoras: {c['anchor_frames']}   pegs: {c['pegs_animated']}   "
        f"in-betweens: {c['in_betweens']}  ({c['keyframes_inserted']} componentes)",
        f"  FIDELIDADE: {'OK' if fid['ok'] else 'REJEITADO'}   "
        f"drift âncoras (máx): {fid['drift_max']:.2g}   "
        f"exposição preservada: {'sim' if fid['exposure_preserved'] else 'NÃO'}",
    ]
    if fid["violations"]:
        lines.append(f"  VIOLAÇÕES: {len(fid['violations'])} — 1ª: {fid['violations'][0]['rule']}")
    if fid["drift_offenders"]:
        lines.append(f"  DRIFT em {len(fid['drift_offenders'])} âncora(s) — revisar")
    worst = max((m.get("max", 0.0) for m in fid["adherence_vs_linear"].values()), default=0.0)
    lines.append(f"  desvio máx vs. linear: {worst:.4g}")
    lines.append(f"  tempos(ms): {report['timing_ms']}")
    return "\n".join(lines)


def write_report(report, dir_path, stem="entremeio_report"):
    """Grava JSON + .txt no diretório. Retorna (json_path, txt_path)."""
    os.makedirs(dir_path, exist_ok=True)
    safe_ts = str(report["timestamp"]).replace(":", "").replace(" ", "_")
    base = os.path.join(dir_path, f"{stem}_{report['rig']}_{safe_ts}")
    json_path, txt_path = base + ".json", base + ".txt"
    with open(json_path, "w") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    with open(txt_path, "w") as fh:
        fh.write(summarize(report) + "\n")
    return json_path, txt_path
