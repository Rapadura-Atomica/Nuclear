"""Ponte de rig — leitura do PegRig do Nuclear para PlanIR (SPEC Fase 0, §4).

Marco A implementa SÓ a leitura (`read_rig`). `write_keys`/`measure_fidelity`
entram no Marco B. Tudo via `bpy` padrão; paths confirmados na branch `Nuclear`:

    bpy.data.pegrigs[name]                 -> datablock PegRig (ID animável)
    rig.pegs[i].name / .parent_index       -> hierarquia (Peg Graph)
    rig.animation_data.action.fcurves      -> FCurves, data_path 'pegs["x"].rotation'

Canais lidos = ALL_CHANNELS (transform + squash, contínuos e discretos). Não lê
`world_mat`/`matrix_world` (runtime-only) nem `parent_index`/`squash_rest_len`
(não-animáveis).
"""

from __future__ import annotations

import json
import re
from typing import Optional

from .ir import (
    ALL_CHANNELS,
    CONTINUOUS_CHANNELS,
    GeneratedKeys,
    Keyframe,
    PegRef,
    PegTrack,
    PlanIR,
)

# data_path de uma FCurve de peg, ex.: pegs["arm_L"].rotation
_DATA_PATH_RE = re.compile(r'pegs\["(?P<name>.*?)"\]\.(?P<chan>\w+)$')


def parse_peg_data_path(data_path: str) -> Optional[tuple[str, str]]:
    """('peg_name', 'canal') a partir de um data_path; None se não for de peg."""
    m = _DATA_PATH_RE.match(data_path)
    if not m:
        return None
    return m.group("name"), m.group("chan")


def followers_of(rig) -> list[str]:
    """Nomes dos objetos da cena presos a este rig por constraint FOLLOW_PEG.

    É o que separa o rig VIVO do rig órfão: um take pode ter cópias do PegRig
    (`carolina_heroi` e `carolina_heroi.001`) e só uma delas mover os desenhos.
    Gerar no órfão insere keyframes que não movem nada — parece que o Entremeio
    "não fez nada".
    """
    import bpy

    out = []
    for ob in bpy.data.objects:
        for con in ob.constraints:
            if con.type == "FOLLOW_PEG" and getattr(con, "rig", None) == rig:
                out.append(ob.name)
                break
    return out


def pick_default_rig():
    """O PegRig que a cena realmente usa (mais objetos presos), ou None.

    Empate ou nenhum seguidor: cai no primeiro da lista, como antes.
    """
    import bpy

    if not len(bpy.data.pegrigs):
        return None
    melhor, n_melhor = None, -1
    for rig in bpy.data.pegrigs:
        n = len(followers_of(rig))
        if n > n_melhor:
            melhor, n_melhor = rig, n
    return melhor or bpy.data.pegrigs[0]


def check_compatibility(rig) -> tuple[bool, list[str]]:
    """Valida que a RNA/estrutura do PegRig é a esperada (RF-8.6).

    Falha ALTO com mensagem clara se um rebase do Nuclear mudar a API, em vez de
    quebrar silenciosamente no meio da geração. Retorna (ok, [problemas]).
    """
    issues: list[str] = []
    if not hasattr(rig, "pegs"):
        issues.append("PegRig sem coleção 'pegs' — API do fork mudou?")
        return (False, issues)
    if len(rig.pegs) == 0:
        issues.append("PegRig sem pegs.")
        return (False, issues)

    peg = rig.pegs[0]
    for chan in CONTINUOUS_CHANNELS:
        if not hasattr(peg, chan):
            issues.append(f"peg sem canal '{chan}' (esperado animável).")
    if not hasattr(peg, "parent_index"):
        issues.append("peg sem 'parent_index' (hierarquia).")

    # o acesso a FCurves (slotted actions) tem que funcionar
    adt = getattr(rig, "animation_data", None)
    if adt is not None and adt.action is not None:
        try:
            list(_iter_fcurves(adt))
        except Exception as e:  # noqa: BLE001 — queremos qualquer falha de API
            issues.append(f"acesso a FCurves falhou (slotted actions?): {e!r}")

    return (len(issues) == 0, issues)


def _resolve_pegrig(source):
    """Aceita um PegRig, um nome (str), ou um objeto que referencie um PegRig.

    Retorna o datablock PegRig ou levanta ValueError com mensagem clara (RF-1.4:
    sinalizar, nunca 'preencher por conta própria').
    """
    import bpy

    if source is None:
        raise ValueError("Nenhum rig informado.")
    if isinstance(source, str):
        rig = bpy.data.pegrigs.get(source)
        if rig is None:
            disponiveis = ", ".join(r.name for r in bpy.data.pegrigs) or "(nenhum)"
            raise ValueError(f"PegRig '{source}' não encontrado. Disponíveis: {disponiveis}")
        return rig
    if source.__class__.__name__ == "PegRig":
        return source
    for attr in ("pegrig", "peg_rig", "data"):
        cand = getattr(source, attr, None)
        if cand is not None and cand.__class__.__name__ == "PegRig":
            return cand
    raise ValueError(f"Não consegui resolver um PegRig a partir de {source!r}.")


def _iter_fcurves(adt):
    """Itera as FCurves de um AnimData, robusto a slotted actions (Blender 4.4+/5.0).

    No Blender 5.0 `action.fcurves` não existe: as curvas vivem em
    `action.layers[].strips[].channelbag(slot).fcurves`, por slot de animação.
    Faz fallback para actions legadas (`action.fcurves`) de arquivos antigos.
    """
    if adt is None or adt.action is None:
        return
    action = adt.action

    # Action legada (pré-4.4): FCurves diretas.
    if hasattr(action, "fcurves"):
        yield from action.fcurves
        return

    # Action com slots (4.4+/5.0): FCurves nos channelbags do slot deste AnimData.
    slot = getattr(adt, "action_slot", None)
    for layer in action.layers:
        for strip in layer.strips:
            if getattr(strip, "type", None) != "KEYFRAME":
                continue
            cbag = strip.channelbag(slot) if slot is not None else None
            if cbag is not None:
                yield from cbag.fcurves
            else:
                # sem slot resolvido: varre todos os channelbags do strip
                for bag in getattr(strip, "channelbags", []):
                    yield from bag.fcurves


def _peg_channel_fcurves(adt, peg_names: set[str]):
    """Agrupa as FCurves por (peg, canal) -> {array_index: fcurve}."""
    out: dict[tuple[str, str], dict[int, object]] = {}
    for fcu in _iter_fcurves(adt):
        parsed = parse_peg_data_path(fcu.data_path)
        if parsed is None:
            continue
        peg_name, chan = parsed
        if peg_name not in peg_names or chan not in ALL_CHANNELS:
            continue
        out.setdefault((peg_name, chan), {})[fcu.array_index] = fcu
    return out


def _build_track_anchors(peg_obj, channel_fcurves: dict[tuple[str, str], dict[int, object]]):
    """Monta as âncoras de uma peg como SNAPSHOTS FIÉIS da pose.

    Para cada canal, os frames-âncora são a união dos frames keyados de seus
    componentes. Em cada frame, cada componente é amostrado por `fcu.evaluate`
    (não 0-fill!) — componentes sem fcurve usam o valor estático da peg, que é
    exatamente o que a avaliação retornaria. Isso garante drift = 0 na fidelidade
    mesmo quando os eixos de um canal são keyados em frames diferentes.
    """
    frame_values: dict[int, dict[str, tuple[float, ...]]] = {}
    for (peg_name, chan), idx_map in channel_fcurves.items():
        if peg_name != peg_obj.name:
            continue
        arity = ALL_CHANNELS[chan]
        static = getattr(peg_obj, chan)
        static = (float(static),) if arity == 1 else tuple(float(c) for c in static)

        frames = sorted({int(round(kp.co[0]))
                         for fcu in idx_map.values() for kp in fcu.keyframe_points})
        for frame in frames:
            comps = tuple(float(idx_map[i].evaluate(frame)) if i in idx_map else static[i]
                          for i in range(arity))
            frame_values.setdefault(frame, {})[chan] = comps

    return [Keyframe(frame=f, values=frame_values[f]) for f in sorted(frame_values)]


def read_rig(source, *, seed: int = 0, style_preset: Optional[str] = None) -> PlanIR:
    """Lê um PegRig real e devolve um PlanIR (SPEC §4.1).

    `source`: nome do PegRig, o datablock, ou objeto que o referencie.
    As âncoras são os keyframes JÁ existentes nas pegs (RF-2.4, caminho primário).
    """
    import bpy

    rig = _resolve_pegrig(source)

    peg_refs = [PegRef(name=p.name, parent=int(p.parent_index)) for p in rig.pegs]
    peg_names = {pr.name for pr in peg_refs}

    adt = getattr(rig, "animation_data", None)
    channel_fcurves = _peg_channel_fcurves(adt, peg_names)

    scene = bpy.context.scene

    # holds discretos (Drawing Substitution / Xsheet) por peg — SPEC §5, RF-4.6.
    # Restringe à janela do animatic; a Cell Library (frames >= 100000) fica de fora.
    from . import discrete
    holds = discrete.detect_discrete_holds(
        rig, frame_range=(int(scene.frame_start), int(scene.frame_end)))

    pegs_by_name = {p.name: p for p in rig.pegs}
    tracks: list[PegTrack] = []
    for pr in peg_refs:
        anchors = _build_track_anchors(pegs_by_name[pr.name], channel_fcurves)
        tracks.append(PegTrack(peg=pr, anchors=anchors,
                               discrete_holds=holds.get(pr.name, [])))

    return PlanIR(
        fps=float(scene.render.fps / scene.render.fps_base),
        frame_start=int(scene.frame_start),
        frame_end=int(scene.frame_end),
        tracks=tracks,
        seed=seed,
        style_preset=style_preset,
    )


# --- Escrita (SPEC §4.2) ---------------------------------------------------

def _set_peg_channel(peg, channel: str, comps: tuple[float, ...]) -> None:
    """Escreve o valor estático no canal da peg (escalar ou vetor)."""
    if CONTINUOUS_CHANNELS.get(channel) == 1:
        setattr(peg, channel, comps[0])
    else:
        setattr(peg, channel, comps)


def _clear_inbetween_keys(rig, adt, peg_channels: dict[str, set[str]], f0: int, f1: int) -> int:
    """Remove keys ESTRITAMENTE entre f0 e f1 nos canais dados (regeneração, RF-7.3).

    Usa `keyframe_delete` por (frame, índice): remover keyframe_points por
    referência num laço invalida as demais referências ("Keyframe not in F-Curve").
    Aqui coletamos (data_path, índice, frame) primeiro e só então deletamos.
    """
    targets: list[tuple[str, int, int]] = []
    for fcu in _iter_fcurves(adt):
        parsed = parse_peg_data_path(fcu.data_path)
        if parsed is None:
            continue
        peg_name, chan = parsed
        if chan not in peg_channels.get(peg_name, set()):
            continue
        for kp in fcu.keyframe_points:
            fr = int(round(kp.co[0]))
            if f0 < fr < f1:
                targets.append((fcu.data_path, fcu.array_index, fr))

    removed = 0
    for data_path, index, fr in targets:
        try:
            if rig.keyframe_delete(data_path=data_path, index=index, frame=fr):
                removed += 1
        except RuntimeError:
            pass
    return removed


def write_keys(rig, generated: GeneratedKeys, *, replace_range=None) -> int:
    """Escreve os in-betweens como keyframes nativos editáveis (RF-7.1, RF-8.2).

    Não-destrutivo: só toca frames entre âncoras. Se `replace_range=(f0,f1)`,
    limpa os in-betweens daquele vão antes de reescrever (regeneração parcial).
    Retorna o número de keyframes inseridos.
    """
    import bpy

    adt = getattr(rig, "animation_data", None)

    if replace_range is not None:
        f0, f1 = replace_range
        peg_channels = {peg: {c for k in keys for c in k.values}
                        for peg, keys in generated.per_peg.items()}
        _clear_inbetween_keys(rig, adt, peg_channels, f0, f1)

    pegs_by_name = {p.name: p for p in rig.pegs}
    inserted = 0
    for peg_name, keys in generated.per_peg.items():
        peg = pegs_by_name.get(peg_name)
        if peg is None:
            continue
        for k in keys:
            for channel, comps in k.values.items():
                _set_peg_channel(peg, channel, comps)
                if rig.keyframe_insert(data_path=f'pegs["{peg_name}"].{channel}', frame=k.frame):
                    inserted += CONTINUOUS_CHANNELS.get(channel, len(comps))

    # reavalia o frame atual para refrescar a pose exibida (as FCurves passam a mandar)
    scene = bpy.context.scene
    scene.frame_set(scene.frame_current)
    return inserted


# --- Geração gerenciada: regenerar limpa o que o Entremeio criou antes (RF-7.3) ---

_GEN_PROP = "_entremeio_generated"   # ID-property no PegRig: lista [peg, chan, frame, valores]

# tolerância pra decidir se uma key "gerada" ainda tem o valor que o Entremeio
# escreveu, ou se o artista reposou em cima dela (promoveu a pose-chave real)
_VALUE_EPSILON = 1e-5


def _load_record(rig) -> list:
    raw = rig.get(_GEN_PROP)
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return []


def record_generated(rig, generated: GeneratedKeys, *, merge: bool = False) -> None:
    """Registra o que o Entremeio gerou (com o VALOR escrito), para limpar na regeneração.

    Guardar o valor é o que permite distinguir "ainda é o in-between que eu
    gerei" de "o artista reposou este frame e virou uma pose-chave real" — sem
    isso, limpar/regenerar apagaria a pose nova do artista (ver
    `_value_matches_record`).

    merge=True acrescenta ao registro existente (refino cirúrgico: outras pegs
    permanecem registradas). merge=False substitui tudo.
    """
    new = [[peg, chan, k.frame, list(k.values[chan])]
           for peg, keys in generated.per_peg.items()
           for k in keys for chan in k.values]
    rec = (_load_record(rig) + new) if merge else new
    rig[_GEN_PROP] = json.dumps(rec)


def _read_key_values(adt, peg_name: str, chan: str, frame: int) -> Optional[tuple]:
    """Valor atual (por componente) da key de `peg_name.chan` no frame dado.

    None se não houver nenhum keyframe ali (já foi removido por outra via).
    """
    data_path = f'pegs["{peg_name}"].{chan}'
    by_index: dict[int, float] = {}
    for fcu in _iter_fcurves(adt):
        if fcu.data_path != data_path:
            continue
        for kp in fcu.keyframe_points:
            if int(round(kp.co[0])) == frame:
                by_index[fcu.array_index] = kp.co[1]
    if not by_index:
        return None
    arity = CONTINUOUS_CHANNELS.get(chan, 1)
    return tuple(by_index.get(i) for i in range(arity))


def _value_matches_record(adt, peg: str, chan: str, frame: int, recorded_values) -> bool:
    """True se a key ainda tem o valor que o Entremeio escreveu (seguro apagar).

    `recorded_values is None` = registro no formato antigo (sem valor, de antes
    desta correção) — mantém o comportamento anterior por compatibilidade.
    Se a key já sumiu (None), também é seguro (nada a apagar). Se o valor
    mudou, é o artista tendo reposado ali: NÃO é mais "gerado", é pose-chave.
    """
    if recorded_values is None:
        return True
    current = _read_key_values(adt, peg, chan, frame)
    if current is None:
        return True
    if len(current) != len(recorded_values):
        return False
    return all(c is not None and abs(c - r) <= _VALUE_EPSILON
               for c, r in zip(current, recorded_values))


def regenerable_in_range(rig, frame_range, pegs=None) -> dict[str, set[str]]:
    """peg -> canais com >=2 frames-âncora DENTRO do trecho (inclusivo).

    Âncora = keyframe que NÃO está no registro do que o Entremeio gerou. É o que
    uma geração por janela consegue REFAZER: limpar além disso abriria buraco —
    apagaria in-betweens de um vão cujas âncoras estão fora da janela, sem ter
    par de âncoras para regenerá-los.
    """
    f0, f1 = frame_range
    generated = {(e[0], e[1], e[2]) for e in _load_record(rig)}
    frames_por: dict[tuple[str, str], set[int]] = {}
    for fcu in _iter_fcurves(getattr(rig, "animation_data", None)):
        parsed = parse_peg_data_path(fcu.data_path)
        if parsed is None:
            continue
        peg, chan = parsed
        if (pegs is not None and peg not in pegs) or chan not in ALL_CHANNELS:
            continue
        for kp in fcu.keyframe_points:
            fr = int(round(kp.co[0]))
            if f0 <= fr <= f1 and (peg, chan, fr) not in generated:
                frames_por.setdefault((peg, chan), set()).add(fr)
    out: dict[str, set[str]] = {}
    for (peg, chan), frames in frames_por.items():
        if len(frames) >= 2:
            out.setdefault(peg, set()).add(chan)
    return out


def clear_generated(rig, pegs=None, frame_range=None, peg_channels=None) -> int:
    """Remove keys que o Entremeio gerou (deixa só as âncoras do artista).

    `pegs` (set de nomes) limita a limpeza a essas pegs — refino cirúrgico (RF-5.3).
    `frame_range=(f0, f1)` limita ao trecho (inclusivo) — regeneração por janela.
    `peg_channels` (peg -> set de canais) limita a esses canais — só o regenerável.
    O registro do que ficar de fora é preservado. None = sem filtro (limpa tudo).

    ⚠️ NUNCA apaga uma key cujo valor divergiu do que foi registrado — isso
    significa que o artista reposou ali e promoveu o frame a pose-chave real
    (ver `_value_matches_record`). Nesse caso só para de rastrear o frame
    (some do registro), sem tocar no keyframe.
    """
    adt = getattr(rig, "animation_data", None)
    rec = _load_record(rig)
    removed = 0
    kept = []
    for entry in rec:
        peg, chan, frame = entry[0], entry[1], entry[2]
        recorded_values = entry[3] if len(entry) > 3 else None
        fora_do_escopo = pegs is not None and peg not in pegs
        fora_do_trecho = (frame_range is not None
                          and not (frame_range[0] <= frame <= frame_range[1]))
        fora_dos_canais = (peg_channels is not None
                           and chan not in peg_channels.get(peg, ()))
        if fora_do_escopo or fora_do_trecho or fora_dos_canais:
            kept.append(entry)
            continue
        if not _value_matches_record(adt, peg, chan, frame, recorded_values):
            continue  # virou pose-chave do artista: não apaga, só para de rastrear
        data_path = f'pegs["{peg}"].{chan}'
        for i in range(CONTINUOUS_CHANNELS.get(chan, 1)):
            try:
                if rig.keyframe_delete(data_path=data_path, index=i, frame=frame):
                    removed += 1
            except RuntimeError:
                pass
    rig[_GEN_PROP] = json.dumps(kept)
    return removed


def clear_generated_entries(rig, entries) -> int:
    """Remove EXATAMENTE estas entradas [peg, canal, frame, valores] geradas (e só elas).

    Usado pelo descarte da prévia: apaga o que AQUELA geração escreveu (diff do
    registro antes/depois), sem tocar em gerações aplicadas anteriormente.

    Mesma proteção de `clear_generated`: se o valor da key divergiu do
    registrado (artista reposou por cima antes de apertar ESC), não apaga.
    """
    adt = getattr(rig, "animation_data", None)
    alvo = {(e[0], e[1], e[2]) for e in entries}
    valores_alvo = {(e[0], e[1], e[2]): (e[3] if len(e) > 3 else None) for e in entries}
    rec = _load_record(rig)
    removed = 0
    kept = []
    for entry in rec:
        peg, chan, frame = entry[0], entry[1], entry[2]
        if (peg, chan, frame) not in alvo:
            kept.append(entry)
            continue
        recorded_values = valores_alvo[(peg, chan, frame)]
        if not _value_matches_record(adt, peg, chan, frame, recorded_values):
            continue  # virou pose-chave do artista: não apaga, só para de rastrear
        data_path = f'pegs["{peg}"].{chan}'
        for i in range(CONTINUOUS_CHANNELS.get(chan, 1)):
            try:
                if rig.keyframe_delete(data_path=data_path, index=i, frame=frame):
                    removed += 1
            except RuntimeError:
                pass
    rig[_GEN_PROP] = json.dumps(kept)
    return removed


# --- Fidelidade ao vivo: âncoras intactas / drift = 0 (SPEC §4.3, RF-6.1) ---

def measure_fidelity(rig, plan: PlanIR, *, epsilon: float = 1e-5):
    """Reavalia o rig nos frames de âncora e mede o drift vs. o PlanIR.

    Drift esperado = 0 (as âncoras nunca foram tocadas). Retorna
    (max_drift, detalhes[list]). Restaura o frame atual ao final.
    """
    import bpy

    scene = bpy.context.scene
    saved_frame = scene.frame_current
    deps = bpy.context.evaluated_depsgraph_get()

    max_drift = 0.0
    offenders = []
    try:
        for track in plan.tracks:
            for k in track.anchors:
                scene.frame_set(k.frame)
                deps = bpy.context.evaluated_depsgraph_get()
                rig_eval = rig.evaluated_get(deps)
                peg_eval = rig_eval.pegs.get(track.name)
                if peg_eval is None:
                    continue
                for channel, comps in k.values.items():
                    if channel not in CONTINUOUS_CHANNELS:
                        continue
                    cur = getattr(peg_eval, channel)
                    cur = (cur,) if CONTINUOUS_CHANNELS[channel] == 1 else tuple(cur)
                    for a, b in zip(comps, cur):
                        d = abs(a - b)
                        if d > max_drift:
                            max_drift = d
                        if d > epsilon:
                            offenders.append((track.name, k.frame, channel, d))
    finally:
        scene.frame_set(saved_frame)

    return max_drift, offenders
