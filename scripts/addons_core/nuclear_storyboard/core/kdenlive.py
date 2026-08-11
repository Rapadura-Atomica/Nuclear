"""Writer de projeto `.kdenlive` (RF-E02).

O `.kdenlive` é um XML do MLT: `producer` para cada mídia, `playlist` para cada
trilha e um `tractor` que junta tudo. Escrevemos uma trilha de vídeo com os
desenhos na ordem e nas durações da timeline, e uma trilha de áudio por clipe
de diálogo, com `blank` para o silêncio antes de cada um.

Fidelidade é o requisito: cortes e durações têm que bater com o MP4 exportado.
Por isso os dois consomem a mesma estrutura (`build_timeline`), e o teste
compara a soma dos frames das duas saídas.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional, Sequence

from .model import Project
from .timing import TakeSlice, build_timeline

MLT_VERSION = "7.0.0"
KDENLIVE_VERSION = "24.12.0"


def _timecode(frames: int, fps: int) -> str:
    """MLT usa `hh:mm:ss.mmm`; o out é inclusivo, por isso quem chama subtrai 1."""
    total = max(0, frames) / float(fps)
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{seconds:06.3f}"


def _prop(parent, name: str, value) -> None:
    element = ET.SubElement(parent, "property", {"name": name})
    element.text = str(value)


class _Builder:
    def __init__(self, project: Project, paths):
        self.project = project
        self.paths = paths
        self.fps = project.settings.fps
        self.root = ET.Element("mlt", {
            "LC_NUMERIC": "C",
            "version": MLT_VERSION,
            "producer": "main_bin",
            "root": str(paths.root),
        })
        self._producers = 0
        self._add_profile()

    def _add_profile(self) -> None:
        s = self.project.settings
        ET.SubElement(self.root, "profile", {
            "description": f"{s.width}x{s.height} {s.fps}fps",
            "width": str(s.width), "height": str(s.height),
            "progressive": "1",
            "sample_aspect_num": "1", "sample_aspect_den": "1",
            "display_aspect_num": str(s.width), "display_aspect_den": str(s.height),
            "frame_rate_num": str(s.fps), "frame_rate_den": "1",
            "colorspace": "709",
        })

    def _new_producer(self, resource: Path, frames: int, mlt_service: str) -> str:
        pid = f"producer{self._producers}"
        self._producers += 1
        producer = ET.SubElement(self.root, "producer", {
            "id": pid,
            "in": _timecode(0, self.fps),
            "out": _timecode(max(0, frames - 1), self.fps),
        })
        _prop(producer, "resource", str(resource))
        _prop(producer, "mlt_service", mlt_service)
        if mlt_service == "qimage":
            # Sem isso o MLT devolve a imagem por 4 segundos e ignora o `out`.
            _prop(producer, "length", frames)
            _prop(producer, "ttl", 1)
        return pid

    def image_producer(self, resource: Path, frames: int) -> str:
        return self._new_producer(resource, frames, "qimage")

    def audio_producer(self, resource: Path, frames: int) -> str:
        return self._new_producer(resource, frames, "avformat")

    def playlist(self, pid: str) -> ET.Element:
        return ET.SubElement(self.root, "playlist", {"id": pid})

    def entry(self, playlist, producer_id: str, frames: int, offset: int = 0) -> None:
        """`offset` em frames: de que ponto do arquivo este trecho toca."""
        ET.SubElement(playlist, "entry", {
            "producer": producer_id,
            "in": _timecode(offset, self.fps),
            "out": _timecode(max(offset, offset + frames - 1), self.fps),
        })

    def blank(self, playlist, frames: int) -> None:
        if frames > 0:
            ET.SubElement(playlist, "blank", {"length": _timecode(frames, self.fps)})


def build_xml(project: Project, paths, slices: Optional[Sequence[TakeSlice]] = None) -> ET.ElementTree:
    if slices is None:
        slices, _ = build_timeline(project)
    builder = _Builder(project, paths)
    fps = builder.fps
    by_id = {tk.id: tk for _, _, tk in project.iter_takes()}

    video = builder.playlist("playlist_video")
    audio_tracks: List[ET.Element] = []
    total_frames = 0

    for item in slices:
        take = by_id[item.take_id]
        total_frames = max(total_frames, item.end_frame)

        for drawing, frames in zip(take.drawings, item.drawing_frames):
            resource = paths.abs(drawing.png)
            builder.entry(video, builder.image_producer(resource, frames), frames)

        # Uma trilha por clipe: sobreposição de diálogo é permitida (RF-A02) e
        # empilhar tudo numa trilha só perderia justamente esse caso.
        for index, clip in enumerate(take.audios):
            while len(audio_tracks) <= index:
                audio_tracks.append(builder.playlist(f"playlist_audio{len(audio_tracks)}"))
            track = audio_tracks[index]

            start = item.start_frame + int(round(clip.start * fps))
            frames = max(1, int(round(clip.duration * fps)))
            offset = max(0, int(round(getattr(clip, "offset", 0.0) * fps)))
            used = _playlist_frames(track, fps)
            builder.blank(track, start - used)
            builder.entry(track,
                          builder.audio_producer(paths.abs(clip.file), offset + frames),
                          frames, offset)

    if not audio_tracks:
        audio_tracks.append(builder.playlist("playlist_audio0"))

    tractor = ET.SubElement(builder.root, "tractor", {
        "id": "tractor0",
        "in": _timecode(0, fps),
        "out": _timecode(max(0, total_frames - 1), fps),
    })
    ET.SubElement(tractor, "track", {"producer": "playlist_video"})
    for track in audio_tracks:
        ET.SubElement(tractor, "track", {"producer": track.get("id"), "hide": "video"})

    return ET.ElementTree(builder.root)


def _playlist_frames(playlist, fps: int) -> int:
    """Quantos frames a trilha já ocupa (entradas + espaços)."""
    total = 0
    for child in playlist:
        if child.tag == "blank":
            total += _frames_from_timecode(child.get("length", "00:00:00.000"), fps)
        elif child.tag == "entry":
            total += _frames_from_timecode(child.get("out", "00:00:00.000"), fps) + 1
    return total


def _frames_from_timecode(value: str, fps: int) -> int:
    hours, minutes, seconds = value.split(":")
    total = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return int(round(total * fps))


def write_kdenlive(project: Project, paths, destination: Path,
                   slices: Optional[Sequence[TakeSlice]] = None) -> Path:
    tree = build_xml(project, paths, slices)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="  ")
    tree.write(destination, encoding="utf-8", xml_declaration=True)
    return destination
