"""Engines de geração de in-betweens. Interface estável em base.py (SPEC §6)."""

from .base import InbetweenEngine
from .baseline import BaselineEngine, BaselineParams
from .spline import SplineEngine, SplineParams

__all__ = ["InbetweenEngine", "BaselineEngine", "BaselineParams",
           "SplineEngine", "SplineParams"]
