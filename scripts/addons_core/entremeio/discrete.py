"""Canais discretos — detecção e preservação (SPEC §5, RF-4.6).

Dois tipos de discreto no Nuclear:
  1. `use_squash` (bool na peg) — já tratado em ir/engine/fidelity (o engine ignora,
     o guarda-corpos rejeita key gerada nele).
  2. **Drawing Substitution / Xsheet** — no GP v3 isto são os FRAMES das camadas de
     cada objeto Grease Pencil (cada frame de camada é um desenho exposto a partir
     daquele frame). Um objeto GP segue uma peg por uma constraint `FOLLOW_PEG`
     (`constraint.peg_name` + `constraint.rig`).

Este módulo detecta esses holds por peg (para enriquecer o PlanIR e o relatório) e
oferece um snapshot/verificação de que a geração NUNCA os alterou — tornando a
preservação da exposição uma garantia auditável, não uma promessa. O motor, por
construção, só escreve FCurves de transform/squash das pegs e jamais toca desenhos;
a verificação prova isso.
"""

from __future__ import annotations


def _gp_objects():
    import bpy
    return [o for o in bpy.data.objects if o.type == "GREASEPENCIL"]


def gp_followers(rig) -> dict[str, list]:
    """peg_name -> [objetos GP que seguem essa peg via FOLLOW_PEG neste rig]."""
    peg_names = {p.name for p in rig.pegs}
    out: dict[str, list] = {}
    for o in _gp_objects():
        for c in o.constraints:
            if getattr(c, "type", None) != "FOLLOW_PEG":
                continue
            crig = getattr(c, "rig", None)
            peg = getattr(c, "peg_name", "") or ""
            # casa pelo rig explícito, ou (sem rig) pelo nome da peg existir neste rig
            if crig is not None and crig != rig:
                continue
            if peg and peg in peg_names:
                out.setdefault(peg, []).append(o)
    return out


# Range-sentinela da Cell Library do Nuclear: desenhos são armazenados como frames
# de camada em números altos (>= 100000) — é o POOL de desenhos, não exposição na
# timeline. Excluído das exposições reportadas (mas preservado no snapshot).
CELL_LIBRARY_FRAME_BASE = 100000


def object_hold_frames(gp_obj, frame_range: tuple[int, int] | None = None) -> list[int]:
    """Frames de troca de desenho (drawing substitution) de um objeto GP.

    Exclui o range da Cell Library (>= CELL_LIBRARY_FRAME_BASE). Se `frame_range`
    for dado, restringe às exposições dentro do intervalo do animatic (RF-1.2).
    """
    lo, hi = frame_range if frame_range else (None, None)
    frames: set[int] = set()
    for lyr in gp_obj.data.layers:
        for f in lyr.frames:
            fr = int(round(f.frame_number))
            if fr >= CELL_LIBRARY_FRAME_BASE:
                continue
            if lo is not None and not (lo <= fr <= hi):
                continue
            frames.add(fr)
    return sorted(frames)


def detect_discrete_holds(rig, frame_range: tuple[int, int] | None = None) -> dict[str, list[int]]:
    """peg_name -> frames de exposição (timeline) dos GP que a seguem (união por peg)."""
    out: dict[str, list[int]] = {}
    for peg, objs in gp_followers(rig).items():
        frames: set[int] = set()
        for o in objs:
            frames.update(object_hold_frames(o, frame_range))
        if frames:
            out[peg] = sorted(frames)
    return out


def snapshot_gp_exposure(rig) -> dict[str, dict[str, list[int]]]:
    """Assinatura {objeto_gp: {camada: [frames]}} das exposições que seguem o rig.

    Usada como 'antes' para provar preservação (RF-4.6) após a geração.
    """
    snap: dict[str, dict[str, list[int]]] = {}
    for objs in gp_followers(rig).values():
        for o in objs:
            if o.name in snap:
                continue
            snap[o.name] = {
                lyr.name: sorted(int(round(f.frame_number)) for f in lyr.frames)
                for lyr in o.data.layers
            }
    return snap


def verify_exposure_preserved(rig, before: dict[str, dict[str, list[int]]]):
    """Confere que nenhuma exposição de camada GP mudou. Retorna (ok, mudancas)."""
    after = snapshot_gp_exposure(rig)
    changes: list[str] = []
    for obj_name, layers in before.items():
        if obj_name not in after:
            changes.append(f"{obj_name}: objeto sumiu")
            continue
        for lyr_name, frames in layers.items():
            now = after[obj_name].get(lyr_name)
            if now != frames:
                changes.append(f"{obj_name}.{lyr_name}: {frames} -> {now}")
    return (len(changes) == 0, changes)
