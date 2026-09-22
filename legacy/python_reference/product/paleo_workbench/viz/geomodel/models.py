"""Domain data models for the 3D geological modeling engine.

Replaces raw dict-passing with typed dataclasses for type safety,
IDE discoverability, and elimination of Primitive Obsession smell.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Layer:
    """A single lithological layer within a borehole."""
    top: float
    bottom: float
    lithology: str = "Unknown"
    color: tuple[float, float, float, float] = (0.5, 0.5, 0.5, 0.8)


@dataclass
class BoreholeRecord:
    """A borehole with its location, total depth, and layer sequence."""
    name: str
    x: float
    y: float
    total_depth: float
    layers: list[Layer] = field(default_factory=list)


@dataclass
class FaultRecord:
    """A fault plane defined by its normal vector and offset."""
    name: str
    normal: tuple[float, float, float] = (1.0, 0.0, 0.0)
    d: float = 0.0
    color: tuple[float, float, float, float] = (0.9, 0.2, 0.2, 0.65)


@dataclass
class TunnelRecord:
    """A tunnel defined by a 3D path and display color."""
    name: str
    path: list[list[float]] = field(default_factory=list)
    color: tuple[float, float, float, float] = (0.2, 0.8, 0.2, 0.9)


@dataclass
class GridSpec:
    """Numerical simulation grid specification — bundles the (nx,ny,nz,dx,dy,dz) data clump."""
    nx: int = 10
    ny: int = 10
    nz: int = 10
    dx: float = 10.0
    dy: float = 10.0
    dz: float = 10.0
