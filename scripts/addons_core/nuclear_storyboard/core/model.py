"""Modelo de dominio do Storyboard & Animatic.

Python puro (stdlib), sem `bpy`: roda no Python embarcado do Nuclear (3.11) e
tambem no host, o que permite testar todo o modelo headless.

Hierarquia: Project -> Episode -> Scene -> Take -> (Drawing | Audio).
A biblioteca de assets (personagens/props) e do PROJETO e vive num arquivo
proprio, porque o PRD a quer compartilhada entre episodios.
"""

from __future__ import annotations

import re
import typing
import uuid
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1

#: Duracao de um take sem nenhum audio (furo do PRD: RF-A03 so define o caso com audio).
DEFAULT_SILENT_TAKE = 2.0

#: Cauda somada ao fim do ultimo audio. O PRD (RF-A03) pede 0,5s; ZERADA a
#: pedido do usuario em 2026-07-31 — a cena termina no ultimo frame do audio e o
#: corte para o take seguinte e seco. Fica como constante para o dia em que o
#: ritmo pedir a folga de volta.
AUDIO_TAIL = 0.0

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

#: Rotulos do burning (RF-14), na ordem projeto/episodio/cena/take.
BURN_LABELS = {
    "pt": ("Projeto", "Ep", "Cena", "Take"),
    "en": ("Project", "Ep", "Scene", "Take"),
}


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def normalize_hex(value: str) -> str:
    """Normaliza `#aabbcc` / `aabbcc` / `#ABC` para `#AABBCC`. Erra se invalido."""
    v = value.strip()
    if not v.startswith("#"):
        v = "#" + v
    if len(v) == 4:  # forma curta #abc
        v = "#" + "".join(c * 2 for c in v[1:])
    if not HEX_RE.match(v):
        raise ValueError(f"cor hex invalida: {value!r}")
    return v.upper()


def rgb_from_hex(value: str):
    """`#AABBCC` -> (r, g, b) em 0..1, NA MESMA escala do hex (sRGB).

    E o par de `hex_from_rgb`: serve ao seletor de cor da interface, que guarda
    o valor em espaco de tela (`COLOR_GAMMA`) — exatamente o numero que o hex
    representa. Converter para linear e trabalho do material, nao daqui.
    """
    h = normalize_hex(value)
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (1, 3, 5))


def hex_from_rgb(rgb) -> str:
    """(r, g, b) em 0..1 (sRGB) -> `#AABBCC`.

    Arredonda para o inteiro mais proximo: `hex -> rgb -> hex` tem que devolver
    o mesmo hex, senao a cor do personagem escorregaria um pouco a cada vez que
    o artista abrisse o seletor, e ela e a CHAVE que aponta para o rig.
    """
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02X}" for c in rgb[:3])


# --------------------------------------------------------------------------
# Serializacao generica de dataclasses
# --------------------------------------------------------------------------

def to_dict(obj: Any) -> Any:
    if is_dataclass(obj):
        return {f.name: to_dict(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, list):
        return [to_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj


def from_dict(cls: type, data: Any) -> Any:
    """Reconstroi um dataclass a partir de dict, guiado pelas anotacoes.

    Campos ausentes no dict caem no default do dataclass, entao um JSON de
    schema antigo continua carregando enquanto so tiverem sido ADICIONADOS
    campos. Campos desconhecidos sao ignorados (nao explodem na cara).
    """
    if not is_dataclass(cls):
        return data
    hints = typing.get_type_hints(cls)
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        kwargs[f.name] = _coerce(hints[f.name], data[f.name])
    return cls(**kwargs)


def _coerce(hint: Any, value: Any) -> Any:
    origin = typing.get_origin(hint)
    if origin is list:
        (inner,) = typing.get_args(hint)
        return [_coerce(inner, v) for v in value]
    if origin is typing.Union:  # Optional[X]
        args = [a for a in typing.get_args(hint) if a is not type(None)]
        if value is None:
            return None
        return _coerce(args[0], value)
    if is_dataclass(hint):
        return from_dict(hint, value)
    return value


# --------------------------------------------------------------------------
# Biblioteca de assets
# --------------------------------------------------------------------------

@dataclass
class Character:
    """Personagem do board. A cor hex do lineart e a chave que aponta pro rig.

    Origem da cor: METADADO declarado (decisao de projeto), gravado no material
    do layer de lineart no Grease Pencil. Nao ha leitura de pixel.
    """

    id: str = field(default_factory=new_id)
    name: str = ""
    hex_color: str = "#FFFFFF"
    rig_path: str = ""  # caminho do .nuc rigado, relativo ao projeto ou absoluto
    notes: str = ""

    @property
    def is_linked(self) -> bool:
        return bool(self.rig_path)


@dataclass
class Prop:
    """Objeto de cena. `temporary` marca versao provisoria (RF-D05)."""

    id: str = field(default_factory=new_id)
    name: str = ""
    temporary: bool = True
    file: str = ""  # arte do prop, relativa a pasta do projeto
    replaced_by: Optional[str] = None  # id do prop final que substituiu este (RN04)
    notes: str = ""
    #: Imagem de referencia do prop provisorio (foto, print, rabisco) — o que o
    #: animador anexa para explicar o que precisa ser criado de verdade. E ela
    #: que sobe como versao 1 da pendencia no sistema de aprovacao.
    reference: str = ""  # relativo a pasta do projeto
    #: Vinculo com a pendencia aberta no sistema de aprovacao: id do asset la,
    #: o ultimo estado conhecido e quando foi conferido. Vazio = nunca pedido.
    request_id: str = ""
    request_status: str = ""
    request_checked_at: str = ""  # ISO-8601, so para a UI dizer "conferido as..."


@dataclass
class Library:
    """Biblioteca do projeto, compartilhada entre episodios (RF-B03)."""

    schema_version: int = SCHEMA_VERSION
    characters: List[Character] = field(default_factory=list)
    props: List[Prop] = field(default_factory=list)

    def character_by_hex(self, hex_color: str) -> Optional[Character]:
        target = normalize_hex(hex_color)
        for c in self.characters:
            if normalize_hex(c.hex_color) == target:
                return c
        return None

    def by_id(self, asset_id: str) -> Optional[Any]:
        for item in (*self.characters, *self.props):
            if item.id == asset_id:
                return item
        return None

    def resolve_prop(self, prop_id: str) -> Optional[Prop]:
        """Segue a cadeia de substituicao ate o prop final (RN04)."""
        seen = set()
        current = next((p for p in self.props if p.id == prop_id), None)
        while current is not None and current.replaced_by and current.id not in seen:
            seen.add(current.id)
            current = next((p for p in self.props if p.id == current.replaced_by), None)
        return current


# --------------------------------------------------------------------------
# Conteudo de um take
# --------------------------------------------------------------------------

@dataclass
class Drawing:
    """Um desenho do take.

    A arte vive no Grease Pencil do .nuc do take; aqui guardamos so o ponteiro
    (`frame`, o numero do keyframe GP) e o PNG achatado que o export consome.
    `exposure` em segundos; None = fatia automatica da duracao do take.
    """

    id: str = field(default_factory=new_id)
    name: str = ""
    frame: int = 1
    png: str = ""  # relativo a pasta do projeto
    exposure: Optional[float] = None


@dataclass
class Audio:
    """Clipe de dialogo posicionado na timeline do take (RF-A02)."""

    id: str = field(default_factory=new_id)
    name: str = ""
    file: str = ""  # relativo a pasta do projeto
    start: float = 0.0
    duration: float = 0.0
    #: De que ponto do ARQUIVO o clipe toca. Sem isto, cortar a cabeca de um
    #: clipe se perdia ao remontar a timeline a partir do JSON, e um take
    #: partido no meio de uma fala nao tinha como continuar a fala no take
    #: seguinte — so daria para recomecar o wav do zero.
    offset: float = 0.0

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass
class Take:
    id: str = field(default_factory=new_id)
    code: str = ""  # ex.: "T001" — entra no burning
    name: str = ""
    file: str = ""  # .nuc do take, relativo a pasta do projeto
    drawings: List[Drawing] = field(default_factory=list)
    audios: List[Audio] = field(default_factory=list)
    duration_override: Optional[float] = None  # ajuste manual (RF-A03)
    character_ids: List[str] = field(default_factory=list)
    prop_ids: List[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class Scene:
    id: str = field(default_factory=new_id)
    code: str = ""  # ex.: "SC02" — entra no burning
    name: str = ""
    takes: List[Take] = field(default_factory=list)


@dataclass
class Episode:
    id: str = field(default_factory=new_id)
    code: str = ""  # ex.: "EP04" — entra no burning
    name: str = ""
    scenes: List[Scene] = field(default_factory=list)


# --------------------------------------------------------------------------
# Projeto
# --------------------------------------------------------------------------

@dataclass
class BurnIn:
    """Burning do export (RF-14): texto + imagem no canto superior esquerdo.

    Os defaults saem do PRD: fonte monoespacada de 18px a 16px da borda, sobre
    caixa semitransparente. `show_timecode` liga a segunda linha, que o PRD
    marca como opcional.
    """

    enabled: bool = True
    image: str = ""  # logo; relativo a pasta do projeto
    opacity: float = 0.8
    margin: int = 16  # px
    font_size: int = 18
    position: str = "top_left"
    show_timecode: bool = False
    font: str = ""  # .ttf especifico; vazio = a monoespacada do sistema


@dataclass
class Settings:
    fps: int = 24
    width: int = 1280
    height: int = 720
    language: str = "pt"  # UI em pt/en
    #: RN03 — bloquear o export quando um personagem nao tem rig vinculado.
    #: Default 'avisa'; a decisao final e do diretor de animacao.
    strict_hex_link: bool = False
    #: Para onde o animatic sai. Vazio = a pasta `exports/` do projeto. Existe
    #: para o animador entregar direto na pasta da producao (Dropbox), sem ter
    #: de ir buscar o MP4 dentro do board depois.
    export_dir: str = ""
    #: Para onde vao os MP4s de take avulso. Caminho PROPRIO porque a entrega e
    #: outra: o animatic emendado vai para a revisao, os takes vao para quem
    #: anima. Vazio = `exports/takes/` do projeto.
    takes_export_dir: str = ""
    #: Sigla do projeto no nome dos arquivos (`DPE_EP03_C02T05`). Vazio = o nome
    #: do board sanitizado. O animador digita ou traz da lista de projetos do
    #: sistema de aprovacao.
    project_code: str = ""
    #: Onde esta o `library.json` deste board. Vazio = na propria pasta.
    #:
    #: Existe porque cada CENA e um board (a pasta manda), e a biblioteca e do
    #: PROJETO: sem apontar para a mesma, o animador recadastraria os
    #: personagens do episodio a cada cena — e a cor de cada um, que e a chave
    #: que aponta para o rig, escorregaria entre elas. O caminho e relativo a
    #: raiz (`../CENA01/library.json`) para o episodio inteiro continuar
    #: funcionando depois de mudar de maquina ou de pasta.
    library_path: str = ""
    #: Como a entrega sai: formato do video, para onde vai e o que acompanha.
    #: Fica no projeto (e nao na maquina) porque e combinado da PRODUCAO — quem
    #: entrega o Ep03 entrega sempre do mesmo jeito, de qualquer computador.
    delivery_format: str = "MP4"    # MP4 (revisao) | DNXHR (edicao)
    delivery_target: str = "FOLDER"  # FOLDER | APPROVAL | BOTH
    delivery_kdenlive: bool = True
    #: Take a take vem LIGADO: e o arquivo que a equipe de animacao recebe
    #: para animar em cima, entao e a entrega normal e nao a excecao. Board
    #: gravado antes disto mantem o que foi escolhido nele (o valor esta no
    #: JSON); so board novo, ou board de schema anterior a esta chave, nasce
    #: com take a take ligado.
    delivery_per_take: bool = True
    #: Projeto correspondente no sistema de aprovacao (uuid + nome, para a tela
    #: nao ter que consultar a rede so para mostrar em quem o board esta ligado).
    #: E nele que as pendencias de prop sao abertas.
    approval_project_id: str = ""
    approval_project_name: str = ""
    #: Cliente do projeto no aprovacao. O asset exige um; o padrao e o primeiro
    #: contato do projeto, e o animador pode trocar.
    approval_client_id: str = ""
    approval_client_name: str = ""
    #: Categoria (subpasta) onde as pendencias entram, se o produtor tiver
    #: criado uma. Vazio = "sem categoria".
    approval_folder_id: str = ""
    approval_folder_name: str = ""


@dataclass
class Project:
    schema_version: int = SCHEMA_VERSION
    id: str = field(default_factory=new_id)
    name: str = "Novo Projeto"
    settings: Settings = field(default_factory=Settings)
    burnin: BurnIn = field(default_factory=BurnIn)
    episodes: List[Episode] = field(default_factory=list)

    # ---- navegacao ----------------------------------------------------
    def iter_takes(self):
        """Gera (episode, scene, take) na ordem do documento."""
        for ep in self.episodes:
            for sc in ep.scenes:
                for tk in sc.takes:
                    yield ep, sc, tk

    def find_take(self, take_id: str):
        for ep, sc, tk in self.iter_takes():
            if tk.id == take_id:
                return ep, sc, tk
        return None

    def burn_text(self, episode: Episode, scene: Scene, take: Take) -> str:
        """Texto do burning (RF-14): `Projeto: X | Ep: Y | Cena: Z | Take: W`.

        Os rotulos seguem o idioma da UI do projeto; um nivel sem codigo nem
        nome some do texto em vez de virar rotulo vazio.
        """
        labels = BURN_LABELS.get(self.settings.language, BURN_LABELS["en"])
        values = (self.name, episode.code or episode.name,
                  scene.code or scene.name, take.code or take.name)
        return " | ".join(f"{label}: {value}"
                          for label, value in zip(labels, values) if value)
