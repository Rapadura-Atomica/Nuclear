"""Leitura de metadados de WAV pela stdlib (`wave`), sem dependencia externa.

O PRD limita a entrada a WAV PCM 16/24 bits, entao o modulo `wave` da stdlib
cobre o caso inteiro.
"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import NamedTuple


class WavInfo(NamedTuple):
    duration: float
    sample_rate: int
    channels: int
    bit_depth: int


class AudioError(Exception):
    pass


def wav_info(path) -> WavInfo:
    path = Path(path)
    try:
        with wave.open(str(path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if rate <= 0:
                raise AudioError(f"sample rate invalido em {path.name}")
            return WavInfo(
                duration=frames / float(rate),
                sample_rate=rate,
                channels=wf.getnchannels(),
                bit_depth=wf.getsampwidth() * 8,
            )
    except wave.Error as exc:
        raise AudioError(f"WAV invalido ou corrompido: {path.name} ({exc})")
    except FileNotFoundError:
        raise AudioError(f"audio nao encontrado: {path}")


def wav_duration(path) -> float:
    return wav_info(path).duration
