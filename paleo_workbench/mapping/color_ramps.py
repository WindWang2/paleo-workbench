"""Color ramps and palettes for continuous geological property mapping and GIS layers."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class ColorStop:
    """One stop in a continuous color ramp."""
    position: float  # [0.0, 1.0]
    color: str       # Hex string '#RRGGBB' or '#RRGGBBAA'


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int, int]:
    s = hex_str.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s) + "FF"
    elif len(s) == 6:
        s = s + "FF"
    elif len(s) != 8:
        return (128, 128, 128, 255)
    try:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
        a = int(s[6:8], 16)
        return (r, g, b, a)
    except ValueError:
        return (128, 128, 128, 255)


def _rgb_to_hex(r: int, g: int, b: int, a: int = 255) -> str:
    r = max(0, min(255, int(r)))
    g = max(0, min(255, int(g)))
    b = max(0, min(255, int(b)))
    a = max(0, min(255, int(a)))
    if a == 255:
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"#{r:02x}{g:02x}{b:02x}{a:02x}"


@dataclass(frozen=True, slots=True)
class ColorRamp:
    """Continuous or discrete color ramp for grid, raster, and graduated mapping."""
    name: str
    stops: tuple[ColorStop, ...]
    nodata_color: str = "#00000000"  # transparent by default

    def __post_init__(self) -> None:
        if not self.stops:
            object.__setattr__(self, "stops", (ColorStop(0.0, "#000000"), ColorStop(1.0, "#ffffff")))

    def evaluate(self, t: float) -> str:
        """Sample the color ramp at normalised parameter t ∈ [0.0, 1.0]."""
        if not math.isfinite(t):
            return self.nodata_color
        t = max(0.0, min(1.0, float(t)))
        if len(self.stops) == 1:
            return self.stops[0].color

        # Find surrounding stops
        if t <= self.stops[0].position:
            return self.stops[0].color
        if t >= self.stops[-1].position:
            return self.stops[-1].color

        for i in range(len(self.stops) - 1):
            s0 = self.stops[i]
            s1 = self.stops[i + 1]
            if s0.position <= t <= s1.position:
                span = s1.position - s0.position
                factor = (t - s0.position) / span if span > 1e-12 else 0.0
                r0, g0, b0, a0 = _hex_to_rgb(s0.color)
                r1, g1, b1, a1 = _hex_to_rgb(s1.color)
                r = r0 + (r1 - r0) * factor
                g = g0 + (g1 - g0) * factor
                b = b0 + (b1 - b0) * factor
                a = a0 + (a1 - a0) * factor
                return _rgb_to_hex(int(round(r)), int(round(g)), int(round(b)), int(round(a)))

        return self.stops[-1].color

    def evaluate_value(self, value: float, vmin: float, vmax: float) -> str:
        """Sample the color ramp given real value and data bounds."""
        if not math.isfinite(value) or not math.isfinite(vmin) or not math.isfinite(vmax):
            return self.nodata_color
        if math.isclose(vmin, vmax):
            return self.evaluate(0.5)
        t = (value - vmin) / (vmax - vmin)
        return self.evaluate(t)

    def sample_table(self, count: int = 256) -> list[tuple[int, int, int, int]]:
        """Return an RGBA lookup table (N x 4 ints in [0, 255]) for fast raster mapping."""
        count = max(2, int(count))
        table = []
        for i in range(count):
            t = i / (count - 1)
            hex_c = self.evaluate(t)
            table.append(_hex_to_rgb(hex_c))
        return table

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "stops": [{"position": s.position, "color": s.color} for s in self.stops],
            "nodata_color": self.nodata_color,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "ColorRamp":
        if not isinstance(data, Mapping):
            return get_color_ramp("viridis")
        name = str(data.get("name") or "custom")
        raw_stops = data.get("stops") or ()
        stops = []
        for item in raw_stops:
            if isinstance(item, Mapping):
                stops.append(ColorStop(float(item.get("position", 0.0)), str(item.get("color", "#000000"))))
        nodata = str(data.get("nodata_color") or "#00000000")
        return cls(name=name, stops=tuple(stops), nodata_color=nodata)


# Standard geological & scientific color ramps
_BUILTIN_RAMPS: dict[str, ColorRamp] = {
    "viridis": ColorRamp(
        name="viridis",
        stops=(
            ColorStop(0.0, "#440154"),
            ColorStop(0.25, "#3b528b"),
            ColorStop(0.5, "#21918c"),
            ColorStop(0.75, "#5ec962"),
            ColorStop(1.0, "#fde725"),
        ),
    ),
    "plasma": ColorRamp(
        name="plasma",
        stops=(
            ColorStop(0.0, "#0d0887"),
            ColorStop(0.25, "#6a00a8"),
            ColorStop(0.5, "#b12a90"),
            ColorStop(0.75, "#e16462"),
            ColorStop(1.0, "#fca636"),
        ),
    ),
    "magma": ColorRamp(
        name="magma",
        stops=(
            ColorStop(0.0, "#000004"),
            ColorStop(0.25, "#51127c"),
            ColorStop(0.5, "#b73779"),
            ColorStop(0.75, "#fc8961"),
            ColorStop(1.0, "#fcfdbf"),
        ),
    ),
    "coolwarm": ColorRamp(
        name="coolwarm",
        stops=(
            ColorStop(0.0, "#3b4cc0"),
            ColorStop(0.5, "#dddddd"),
            ColorStop(1.0, "#b40426"),
        ),
    ),
    "jet": ColorRamp(
        name="jet",
        stops=(
            ColorStop(0.0, "#00007f"),
            ColorStop(0.25, "#007fff"),
            ColorStop(0.5, "#7fff7f"),
            ColorStop(0.75, "#ff7f00"),
            ColorStop(1.0, "#7f0000"),
        ),
    ),
    # Geological Factor Ramps
    "porosity": ColorRamp(
        name="porosity",
        stops=(
            ColorStop(0.0, "#2c7bb6"),   # Low porosity (tight) -> Blue
            ColorStop(0.25, "#abd9e9"),  # Poor
            ColorStop(0.5, "#ffffbf"),   # Moderate -> Yellow
            ColorStop(0.75, "#fdae61"),  # Good -> Orange
            ColorStop(1.0, "#d7191c"),   # High porosity (sweet spot) -> Red
        ),
    ),
    "permeability": ColorRamp(
        name="permeability",
        stops=(
            ColorStop(0.0, "#313695"),   # Low perm
            ColorStop(0.25, "#74add1"),
            ColorStop(0.5, "#e0f3f8"),
            ColorStop(0.75, "#fee090"),
            ColorStop(1.0, "#d73027"),   # High perm
        ),
    ),
    "thickness": ColorRamp(
        name="thickness",
        stops=(
            ColorStop(0.0, "#f7fcf5"),   # Thin / Zero thickness
            ColorStop(0.25, "#c7e9c0"),  # Moderate
            ColorStop(0.5, "#74c476"),
            ColorStop(0.75, "#31a354"),
            ColorStop(1.0, "#006d2c"),   # Thick / Depocenter -> Dark Green
        ),
    ),
    "sand_thickness": ColorRamp(
        name="sand_thickness",
        stops=(
            ColorStop(0.0, "#f7fbff"),   # No sand -> Light
            ColorStop(0.25, "#fed976"),  # Thin sand
            ColorStop(0.5, "#feb24c"),   # Moderate
            ColorStop(0.75, "#fd8d3c"),  # Thick sand
            ColorStop(1.0, "#b10026"),   # Channel core / thickest -> Crimson
        ),
    ),
    "toc": ColorRamp(
        name="toc",
        stops=(
            ColorStop(0.0, "#f7f7f7"),   # Poor organic content
            ColorStop(0.33, "#cccccc"),  # Fair
            ColorStop(0.66, "#969696"),  # Good
            ColorStop(1.0, "#252525"),   # Excellent source rock -> Dark carbonaceous
        ),
    ),
    "water_depth": ColorRamp(
        name="water_depth",
        stops=(
            ColorStop(0.0, "#ffffcc"),   # Coastal / Exposed land
            ColorStop(0.25, "#a1dab4"),  # Shallow lake / marine
            ColorStop(0.5, "#41b6c4"),   # Semi-deep
            ColorStop(0.75, "#2c7fb8"),  # Deep lake
            ColorStop(1.0, "#253494"),   # Bathyal / Deep abyssal
        ),
    ),
}


def get_color_ramp(name: str) -> ColorRamp:
    """Resolve a color ramp by name, defaulting to viridis if unknown."""
    return _BUILTIN_RAMPS.get(str(name).lower(), _BUILTIN_RAMPS["viridis"])


def register_color_ramp(ramp: ColorRamp) -> None:
    """Register a custom or specialized color ramp."""
    _BUILTIN_RAMPS[ramp.name.lower()] = ramp


def list_color_ramps() -> list[str]:
    """Return available color ramp names."""
    return list(_BUILTIN_RAMPS.keys())
