"""PlanIR — modelo de dados canônico interno do Entremeio (SPEC Fase 0, §3).

Estrutura intermediária NEUTRA (não importa `bpy`). É o que a ponte de rig
produz, o engine consome/devolve, e o IPC serializa. Isolar aqui é o que
permite trocar o engine (baseline <-> IA) e, no futuro, o host (Nuclear <-> Moho)
sem reescrever o motor.

Modelo de canais (confirmado na branch `Nuclear`, rna_pegrig.cc):
- Contínuos (o engine INTERPOLA): translation/rotation/scale + squash_anchor/
  squash_tip/squash_volume. Aridade variável (vec3 ou escalar).
- Discretos (o engine PRESERVA, nunca interpola): use_squash (on/off) e, fora
  da RNA da peg, Drawing Substitution / exposição de camadas (Xsheet).
- Não-animáveis (ignorados): parent_index, squash_rest_len, matrix_world.

Convenções: radianos para rotation (euler XYZ); fator para scale/squash_volume;
tempo em FRAMES inteiros. Valores são sempre tuplas de float (use_squash = (0.0,)
ou (1.0,)) para um modelo uniforme.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

# nome do canal -> número de componentes (array_index 0..n-1 nas FCurves)
CONTINUOUS_CHANNELS: dict[str, int] = {
    "translation": 3,
    "rotation": 3,      # euler XYZ, radianos
    "scale": 3,
    "squash_anchor": 3,
    "squash_tip": 3,
    "squash_volume": 1,  # PROP_FACTOR 0..1
}

# discretos animáveis na peg: preservar exatamente, NUNCA interpolar (RF-4.6)
DISCRETE_CHANNELS: dict[str, int] = {
    "use_squash": 1,     # booleano (flag PEGRIGPEG_SQUASH) -> 0.0/1.0
}

ALL_CHANNELS: dict[str, int] = {**CONTINUOUS_CHANNELS, **DISCRETE_CHANNELS}

Components = tuple[float, ...]


@dataclass(frozen=True)
class PegRef:
    """Identidade e lugar de uma peg na hierarquia (Peg Graph)."""
    name: str            # chave em pegs["..."]
    parent: int          # parent_index (-1 = root)


@dataclass(frozen=True)
class Keyframe:
    """Uma pose de uma peg num frame.

    `values` mapeia canal -> componentes. Só carrega canais realmente animados
    naquele frame; canais ausentes ficam de fora (não viram 0).
    """
    frame: int
    values: dict[str, Components] = field(default_factory=dict)

    def continuous(self) -> dict[str, Components]:
        return {c: v for c, v in self.values.items() if c in CONTINUOUS_CHANNELS}

    def discrete(self) -> dict[str, Components]:
        return {c: v for c, v in self.values.items() if c in DISCRETE_CHANNELS}


@dataclass(frozen=True)
class PegTrack:
    """Tudo que o motor precisa saber sobre uma peg para gerar seu trecho."""
    peg: PegRef
    anchors: list[Keyframe] = field(default_factory=list)   # poses-chave: ÂNCORAS RÍGIDAS
    discrete_holds: list[int] = field(default_factory=list)  # frames de Drawing Substitution/exposição

    @property
    def name(self) -> str:
        return self.peg.name

    def animated_channels(self) -> set[str]:
        out: set[str] = set()
        for k in self.anchors:
            out.update(k.values.keys())
        return out


@dataclass(frozen=True)
class PlanIR:
    """Estado completo de um plano, pronto para o engine. Serializável."""
    fps: float
    frame_start: int
    frame_end: int
    tracks: list[PegTrack] = field(default_factory=list)
    seed: int = 0
    style_preset: Optional[str] = None   # placeholder p/ V1 (preset de estilo por IP)

    def track(self, peg_name: str) -> Optional[PegTrack]:
        for t in self.tracks:
            if t.peg.name == peg_name:
                return t
        return None

    def subtree_names(self, root_name: str) -> set[str]:
        """Nomes de root + todos os descendentes (para o refino cirúrgico, RF-5.3).

        `peg.parent` é índice na lista de tracks (parent_index); read_rig inclui
        TODAS as pegs, então a hierarquia fecha.
        """
        idx_of = {t.peg.name: i for i, t in enumerate(self.tracks)}
        if root_name not in idx_of:
            return set()
        root = idx_of[root_name]
        keep = {root}
        changed = True
        while changed:
            changed = False
            for i, t in enumerate(self.tracks):
                if i not in keep and t.peg.parent in keep:
                    keep.add(i); changed = True
        return {self.tracks[i].peg.name for i in keep}

    def scoped_to(self, names: set[str]) -> "PlanIR":
        """Novo PlanIR com âncoras SÓ nas pegs do escopo (o resto vira sem-âncora).

        Mantém a lista de tracks intacta (índices de parent válidos p/ overlap/depths).
        """
        tracks = [t if t.peg.name in names
                  else PegTrack(peg=t.peg, anchors=[], discrete_holds=t.discrete_holds)
                  for t in self.tracks]
        return PlanIR(self.fps, self.frame_start, self.frame_end, tracks, self.seed, self.style_preset)

    # --- serialização para o contrato de IPC (SPEC §7) ---------------------
    def to_dict(self) -> dict:
        return {
            "fps": self.fps,
            "frame_start": self.frame_start,
            "frame_end": self.frame_end,
            "seed": self.seed,
            "style_preset": self.style_preset,
            "tracks": [
                {
                    "peg": asdict(t.peg),
                    "anchors": [{"frame": k.frame, "values": {c: list(v) for c, v in k.values.items()}}
                                for k in t.anchors],
                    "discrete_holds": list(t.discrete_holds),
                }
                for t in self.tracks
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PlanIR":
        tracks = [
            PegTrack(
                peg=PegRef(**t["peg"]),
                anchors=[Keyframe(frame=k["frame"],
                                  values={c: tuple(v) for c, v in k["values"].items()})
                         for k in t["anchors"]],
                discrete_holds=list(t["discrete_holds"]),
            )
            for t in d["tracks"]
        ]
        return cls(
            fps=d["fps"],
            frame_start=d["frame_start"],
            frame_end=d["frame_end"],
            tracks=tracks,
            seed=d.get("seed", 0),
            style_preset=d.get("style_preset"),
        )


@dataclass(frozen=True)
class GeneratedKeys:
    """Saída do engine: SÓ os in-betweens novos (entre âncoras).

    Invariante crítico (P1/P2): nunca contém frames coincidentes com âncoras
    e nunca inclui pegs/canais ausentes no PlanIR. O guarda-corpos rejeita o
    lote inteiro se violar.
    """
    per_peg: dict[str, list[Keyframe]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"per_peg": {
            n: [{"frame": k.frame, "values": {c: list(v) for c, v in k.values.items()}} for k in ks]
            for n, ks in self.per_peg.items()
        }}

    @classmethod
    def from_dict(cls, d: dict) -> "GeneratedKeys":
        return cls(per_peg={
            n: [Keyframe(frame=k["frame"], values={c: tuple(v) for c, v in k["values"].items()})
                for k in ks]
            for n, ks in d["per_peg"].items()
        })

    def frame_count(self) -> int:
        return sum(len(ks) for ks in self.per_peg.values())
