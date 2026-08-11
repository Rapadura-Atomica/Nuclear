"""Montagem do animatic em MP4 com FFmpeg.

O vídeo é uma sequência de PNGs (um por desenho) emendados com corte seco, cada
um exposto pelo tempo que o timing manda; os áudios entram atrasados para a
posição que ocupam na timeline geral; e por cima vai o burning (RN06).

Nada é reprocessado (RF-E03): não há escala, filtro de imagem nem conversão de
espaço de cor — só composição e burning. Os PNGs já saem do render na resolução
do projeto.

Este módulo não importa `bpy`: ele monta a linha de comando e pode rodar num
worker headless. Quem executa é `run_export`.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

from .model import Project
from .timing import TakeSlice, build_timeline

FFMPEG = "ffmpeg"

#: Espaço horizontal reservado para o logo antes do texto do burning.
LOGO_TEXT_GAP = 96

#: Fonte padrão do burning. Precisa ter acentuação — o PRD exige.
#: O PRD pede monoespaçada, então essas vêm primeiro; as proporcionais ficam de
#: reserva para o sistema que não tiver nenhuma mono instalada.
FONT_CANDIDATES = (
    "/usr/share/fonts/google-noto/NotoSansMono-Regular.ttf",
    "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/liberation-mono/LiberationMono-Regular.ttf",
    "/usr/share/fonts/google-noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

#: Distância entre a linha do texto e a do timecode, em múltiplos do corpo.
TIMECODE_LINE_GAP = 1.6


# ---------------------------------------------------------------------------
# Formatos de saída
#
# O animatic tem dois destinos com exigências opostas: quem REVISA abre o
# arquivo no celular, no navegador, no sistema de aprovação — e aí manda o H.264
# baseline do PRD (§9.1). Quem EDITA joga o arquivo numa timeline do DaVinci, e
# H.264 longo-GOP arrasta a edição inteira; para esse existe o DNxHR, que corta
# quadro a quadro. Perfil LB de propósito: com HQ o disco enche depressa e a
# diferença é invisível num board de traço.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OutputFormat:
    key: str
    suffix: str
    video_args: tuple
    audio_args: tuple
    label: str
    #: Menor quadro que o codec aceita. O DNxHD recusa abaixo de 256x120 com uma
    #: mensagem de encoder que não diz nada a quem está entregando um board.
    min_width: int = 0
    min_height: int = 0

    def path_for(self, base: Path) -> Path:
        return Path(base).with_suffix(self.suffix)

    def check_size(self, width: int, height: int) -> None:
        if width < self.min_width or height < self.min_height:
            raise ExportError(
                f"{self.label} precisa de pelo menos {self.min_width}x"
                f"{self.min_height}; este board está em {width}x{height} "
                "(entregue em MP4 ou aumente a resolução do projeto)")


MP4 = OutputFormat(
    key="MP4", suffix=".mp4", label="MP4 (revisão)",
    # Baseline por exigência do PRD: roda em qualquer player, inclusive celular
    # velho. Sem CABAC nem B-frames o arquivo fica maior — para 720p de
    # rascunho, isso não pesa.
    video_args=("-c:v", "libx264", "-profile:v", "baseline", "-level", "3.1",
                "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"),
    audio_args=("-c:a", "aac", "-b:a", "192k"))

DNXHR = OutputFormat(
    key="DNXHR", suffix=".mov", label="DNxHR (edição)",
    video_args=("-c:v", "dnxhd", "-profile:v", "dnxhr_lb", "-pix_fmt", "yuv422p"),
    audio_args=("-c:a", "pcm_s16le"),
    min_width=256, min_height=120)

FORMATS = {fmt.key: fmt for fmt in (MP4, DNXHR)}


def output_format(key: str) -> OutputFormat:
    return FORMATS.get((key or "").upper(), MP4)


class ExportError(Exception):
    pass


def find_font(explicit: str = "") -> str:
    if explicit and Path(explicit).is_file():
        return explicit
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    raise ExportError("nenhuma fonte encontrada para o burning; informe uma no projeto")


def have_ffmpeg() -> bool:
    return shutil.which(FFMPEG) is not None


# ---------------------------------------------------------------------------
# Plano de export
# ---------------------------------------------------------------------------

@dataclass
class ImageEntry:
    path: Path
    frames: int


@dataclass
class AudioEntry:
    path: Path
    start: float        # segundos na timeline geral
    duration: float
    offset: float = 0.0  # de que ponto do arquivo o clipe toca


@dataclass
class BurnEntry:
    text: str
    start: float
    end: float


@dataclass
class ExportPlan:
    images: List[ImageEntry] = field(default_factory=list)
    audios: List[AudioEntry] = field(default_factory=list)
    burns: List[BurnEntry] = field(default_factory=list)
    total_frames: int = 0
    fps: int = 24
    width: int = 1280
    height: int = 720

    @property
    def duration(self) -> float:
        return self.total_frames / float(self.fps)


def build_plan(project: Project, paths, slices: Optional[Sequence[TakeSlice]] = None) -> ExportPlan:
    """Traduz o projeto para o que o FFmpeg precisa saber."""
    if slices is None:
        slices, _ = build_timeline(project)
    fps = project.settings.fps
    plan = ExportPlan(fps=fps, width=project.settings.width,
                      height=project.settings.height)

    by_id = {tk.id: (ep, sc, tk) for ep, sc, tk in project.iter_takes()}
    for item in slices:
        episode, scene, take = by_id[item.take_id]
        plan.total_frames = max(plan.total_frames, item.end_frame)

        for drawing, frames in zip(take.drawings, item.drawing_frames):
            if not drawing.png:
                raise ExportError(
                    f"take {take.code}: desenho '{drawing.name}' não tem PNG renderizado")
            image = paths.abs(drawing.png)
            if not image.is_file():
                raise ExportError(f"take {take.code}: PNG não encontrado ({drawing.png})")
            plan.images.append(ImageEntry(image, frames))

        take_start = item.start_frame / float(fps)
        for audio in take.audios:
            path = paths.abs(audio.file)
            if not path.is_file():
                raise ExportError(f"take {take.code}: áudio não encontrado ({audio.file})")
            plan.audios.append(AudioEntry(path, take_start + audio.start,
                                          audio.duration,
                                          getattr(audio, "offset", 0.0)))

        if project.burnin.enabled:
            plan.burns.append(BurnEntry(
                text=project.burn_text(episode, scene, take),
                start=take_start,
                end=item.end_frame / float(fps)))

    return plan


# ---------------------------------------------------------------------------
# Comando FFmpeg
# ---------------------------------------------------------------------------

def write_concat_list(plan: ExportPlan, destination: Path) -> Path:
    """Lista do demuxer `concat`, com a duração de cada desenho.

    O concat demuxer ignora a duração da última entrada, então ela é repetida —
    é o jeito canônico de a última imagem não ser cortada.
    """
    lines = []
    for entry in plan.images:
        lines.append(f"file '{entry.path}'")
        lines.append(f"duration {entry.frames / float(plan.fps):.6f}")
    if plan.images:
        lines.append(f"file '{plan.images[-1].path}'")
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination


def escape_drawtext(text: str) -> str:
    """Escapa o texto para o filtro drawtext (acentuação passa intacta)."""
    out = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    return out.replace("%", "\\%").replace(",", "\\,").replace("[", "\\[").replace("]", "\\]")


def build_filter(plan: ExportPlan, burnin, font: str, has_logo: bool) -> str:
    """Cadeia de filtros: burning por cima do vídeo e mixagem dos áudios."""
    margin = int(burnin.margin)
    steps = []

    # O demuxer `concat` entrega as imagens a 25 fps e quantiza cada `duration`
    # em 1/25, então os timestamps chegam tortos. Sem reamostrar aqui, o `-t`
    # corta o vídeo antes da hora e o animatic sai mais curto que o board —
    # defeito que passa despercebido porque o áudio segura a duração do
    # container. `fps` primeiro na cadeia: os drawtext seguintes usam `t`.
    steps.append(f"[0:v]fps={plan.fps}[vsrc]")
    video = "[vsrc]"

    if has_logo:
        # Logo no canto e o texto à direita dele. A largura reservada é fixa
        # porque o drawtext não enxerga as dimensões do overlay.
        steps.append(f"[1:v]format=rgba,colorchannelmixer=aa={burnin.opacity:.3f}[logo]")
        steps.append(f"{video}[logo]overlay=x={margin}:y={margin}[vlogo]")
        video = "[vlogo]"
        text_x = margin + LOGO_TEXT_GAP
    else:
        text_x = margin

    size = int(burnin.font_size)
    box = (f":box=1:boxcolor=black@{min(0.6, burnin.opacity):.3f}:boxborderw=6")

    for i, burn in enumerate(plan.burns):
        target = f"[vb{i}]"
        steps.append(
            f"{video}drawtext=fontfile='{font}'"
            f":text='{escape_drawtext(burn.text)}'"
            f":fontcolor=white@{burnin.opacity:.3f}"
            f":fontsize={size}"
            f"{box}"
            f":x={text_x}:y={margin}"
            f":enable='between(t,{burn.start:.3f},{burn.end:.3f})'{target}")
        video = target

    if getattr(burnin, "show_timecode", False):
        # Timecode do animatic inteiro, numa segunda linha: é o vídeo que corre,
        # então nada de `enable` por take. `timecode_rate` é obrigatório e os
        # `:` do valor têm de chegar escapados ao drawtext.
        steps.append(
            f"{video}drawtext=fontfile='{font}'"
            f":timecode='00\\:00\\:00\\:00':timecode_rate={plan.fps}"
            f":fontcolor=white@{burnin.opacity:.3f}"
            f":fontsize={size}"
            f"{box}"
            f":x={text_x}:y={margin + int(size * TIMECODE_LINE_GAP)}[vtc]")
        video = "[vtc]"

    steps.append(f"{video}format=yuv420p[vout]")

    audio_offset = 2 if has_logo else 1
    if plan.audios:
        labels = []
        for i, audio in enumerate(plan.audios):
            index = audio_offset + i
            delay = int(round(audio.start * 1000))
            # `atrim` antes do `adelay`: o clipe pode ser um PEDAÇO do arquivo —
            # cortado na ponta pelo artista, ou herdado de um take que foi
            # partido no meio da fala. Sem isto o MP4 tocava o wav inteiro,
            # ignorando o recorte.
            corte = f"atrim=start={audio.offset:.6f}"
            if audio.duration > 0:
                corte += f":duration={audio.duration:.6f}"
            steps.append(f"[{index}:a]{corte},asetpts=PTS-STARTPTS,"
                         f"adelay={delay}|{delay}[a{i}]")
            labels.append(f"[a{i}]")
        steps.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:"
                     f"dropout_transition=0[aout]")
    return ";".join(steps)


def build_command(plan: ExportPlan, burnin, concat_list: Path, output: Path,
                  font: str, logo: Optional[Path],
                  fmt: Optional[OutputFormat] = None) -> List[str]:
    fmt = fmt or MP4
    has_logo = logo is not None
    command = [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list)]
    if has_logo:
        command += ["-i", str(logo)]
    for audio in plan.audios:
        command += ["-i", str(audio.path)]

    command += ["-filter_complex", build_filter(plan, burnin, font, has_logo)]
    command += ["-map", "[vout]"]
    if plan.audios:
        command += ["-map", "[aout]", *fmt.audio_args]
    else:
        command += ["-an"]

    command += [
        "-r", str(plan.fps),
        *fmt.video_args,
        "-t", f"{plan.duration:.3f}",
        str(output),
    ]
    return command


def run_export(project: Project, paths, output: Path,
               slices: Optional[Sequence[TakeSlice]] = None,
               fmt: Optional[OutputFormat] = None) -> Path:
    """Monta e roda o export. Devolve o caminho do vídeo gerado.

    A extensão sai do FORMATO, não do que veio escrito: pedir DNxHR e receber um
    `.mp4` que na verdade é MOV quebraria na mão de quem vai editar.
    """
    if not have_ffmpeg():
        raise ExportError("ffmpeg não encontrado no PATH")

    fmt = fmt or MP4
    output = fmt.path_for(output)

    plan = build_plan(project, paths, slices)
    if not plan.images:
        raise ExportError("nenhum desenho renderizado para exportar")
    fmt.check_size(plan.width, plan.height)

    output.parent.mkdir(parents=True, exist_ok=True)

    logo = None
    if project.burnin.enabled and project.burnin.image:
        candidate = paths.abs(project.burnin.image)
        if candidate.is_file():
            logo = candidate

    # A lista do `concat` é andaime do FFmpeg, não entrega: escrita ao lado do
    # MP4 ela ficava para trás na pasta da produção (e, com um arquivo por take,
    # seriam dezenas de `.txt` no meio dos vídeos).
    with tempfile.TemporaryDirectory(prefix="nsb_export_") as tmp:
        concat_list = write_concat_list(plan, Path(tmp) / "concat.txt")
        command = build_command(plan, project.burnin, concat_list, output,
                                find_font(project.burnin.font), logo, fmt)
        result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-12:])
        raise ExportError(f"ffmpeg falhou:\n{tail}")
    return output
