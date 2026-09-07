"""Scalar factor styling (v7 §5): ScalarStyleSpec + classification.

The spec describes HOW a scalar factor surface is styled (ramp, mode,
classification, ranges, reverse, opacity, nodata transparency, unit and
colorbar labels).  Classification runs host-side on numpy (deterministic);
the RENDERER XML itself is produced by QGIS through the bridge
(:func:`encode_scalar_renderer_xml`) so the wire format is always authored
by QGIS's own serializer — never hand-rolled XML that could drift from the
vendored QGIS version.  Without the bridge there is no honest scalar QGIS
path; callers must then use the RGBA mirror and disclose the degradation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

__all__ = [
    "ScalarStyleSpec",
    "classify_breaks",
    "equal_interval_breaks",
    "natural_breaks",
    "quantile_breaks",
    "ramp_items_for_spec",
    "scalar_style_pipeline_ready",
]

_MODES = ("continuous", "classified")
_CLASSIFICATIONS = ("equal_interval", "quantile", "natural_breaks", "explicit")


@dataclass(frozen=True)
class ScalarStyleSpec:
    """Declarative styling for one scalar factor surface.

    ``mode``: continuous ramp vs classified (step) ramp.
    ``classification``: how class breaks are derived (``explicit`` uses
    ``explicit_breaks``; others derive from data via :func:`classify_breaks`).
    ``manual_range`` overrides data min/max for the ramp span.
    ``nodata_transparent``: NaN cells render transparent (default).
    """

    ramp_name: str = "viridis"
    mode: str = "continuous"
    classification: str = "equal_interval"
    n_classes: int = 5
    explicit_breaks: tuple[float, ...] | None = None
    manual_range: tuple[float, float] | None = None
    reverse: bool = False
    opacity: float = 1.0
    nodata_transparent: bool = True
    unit_label: str = ""
    colorbar_title: str = ""
    colorbar_decimals: int = 2

    def __post_init__(self) -> None:
        if self.mode not in _MODES:
            raise ValueError(f"mode must be one of {_MODES}, got {self.mode!r}")
        if self.classification not in _CLASSIFICATIONS:
            raise ValueError(
                f"classification must be one of {_CLASSIFICATIONS}, got "
                f"{self.classification!r}")
        if self.n_classes < 2:
            raise ValueError("n_classes must be >= 2")
        if not 0.0 <= float(self.opacity) <= 1.0:
            raise ValueError("opacity must be within [0, 1]")
        if self.manual_range is not None:
            lo, hi = (float(v) for v in self.manual_range)
            if not hi > lo:
                raise ValueError("manual_range needs hi > lo")
        if self.classification == "explicit" and not self.explicit_breaks:
            raise ValueError("explicit classification requires explicit_breaks")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "ramp_name": self.ramp_name,
            "mode": self.mode,
            "classification": self.classification,
            "n_classes": self.n_classes,
            "reverse": self.reverse,
            "opacity": self.opacity,
            "nodata_transparent": self.nodata_transparent,
            "unit_label": self.unit_label,
            "colorbar_title": self.colorbar_title,
            "colorbar_decimals": self.colorbar_decimals,
        }
        if self.explicit_breaks is not None:
            data["explicit_breaks"] = [float(v) for v in self.explicit_breaks]
        if self.manual_range is not None:
            data["manual_range"] = [float(v) for v in self.manual_range]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScalarStyleSpec":
        explicit = data.get("explicit_breaks")
        manual = data.get("manual_range")
        return cls(
            ramp_name=str(data.get("ramp_name", "viridis")),
            mode=str(data.get("mode", "continuous")),
            classification=str(data.get("classification", "equal_interval")),
            n_classes=int(data.get("n_classes", 5)),
            explicit_breaks=tuple(float(v) for v in explicit) if explicit else None,
            manual_range=tuple(float(v) for v in manual) if manual else None,
            reverse=bool(data.get("reverse", False)),
            opacity=float(data.get("opacity", 1.0)),
            nodata_transparent=bool(data.get("nodata_transparent", True)),
            unit_label=str(data.get("unit_label", "")),
            colorbar_title=str(data.get("colorbar_title", "")),
            colorbar_decimals=int(data.get("colorbar_decimals", 2)),
        )


# ---------------------------------------------------------------------------
# Classification (deterministic, numpy)


def _format_labels(breaks: Sequence[float], decimals: int) -> list[str]:
    return [f"{float(v):.{decimals}f}" for v in breaks]


def equal_interval_breaks(vmin: float, vmax: float, *, n: int = 5,
                          decimals: int = 2):
    breaks = list(np.linspace(float(vmin), float(vmax), int(n) + 1))
    return breaks, _format_labels(breaks, decimals)


def quantile_breaks(values: np.ndarray, *, n: int = 5, decimals: int = 2):
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        raise ValueError("quantile classification needs at least one finite value")
    quantiles = np.linspace(0.0, 1.0, int(n) + 1)
    breaks = list(np.quantile(finite, quantiles))
    # Enforce strict monotonicity (flat distributions collapse quantiles).
    for index in range(1, len(breaks)):
        if breaks[index] <= breaks[index - 1]:
            breaks[index] = breaks[index - 1]
    return breaks, _format_labels(breaks, decimals)


def natural_breaks(values: np.ndarray, *, n: int = 5, sample: int = 1000,
                   seed: int = 0, decimals: int = 2):
    """Jenks natural breaks on (sampled) finite values — Fisher-Jenks via
    numpy with a deterministic sample draw."""
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        raise ValueError("natural breaks need at least one finite value")
    if finite.size > int(sample):
        generator = np.random.default_rng(seed)
        finite = generator.choice(finite, size=int(sample), replace=False)
    data = np.sort(finite)
    k = int(n)
    if data.size <= k:
        breaks = list(data) + [data[-1]]
        return breaks, _format_labels(breaks, decimals)

    # Classic O(n·k) dynamic-programming Jenks (1-D k-means equivalent).
    count = data.size
    matrix = np.zeros((k + 1, count + 1), dtype=np.float64)
    pivot = np.zeros((k + 1, count + 1), dtype=np.int64)
    matrix[1, 1:] = np.inf
    for classes in range(2, k + 1):
        for end in range(classes, count + 1):
            best = np.inf
            best_split = classes - 1
            prefix_sum = 0.0
            prefix_sqsum = 0.0
            # Iterate splits from the tail keeps the inner loop tight.
            for split in range(classes - 1, end):
                seg = data[split:end]
                s = seg.sum()
                sq = (seg * seg).sum()
                variance = sq - (s * s) / seg.size
                candidate = matrix[classes - 1, split] + variance
                if candidate < best:
                    best = candidate
                    best_split = split
            matrix[classes, end] = best
            pivot[classes, end] = best_split
    # Reconstruct class boundaries from the pivot table.
    boundaries = [0] * (k + 1)
    boundaries[k] = count
    end = count
    for classes in range(k, 1, -1):
        end = pivot[classes, end]
        boundaries[classes - 1] = end
    breaks = [float(data[boundaries[i] - 1]) if boundaries[i] > 0 else float(data[0])
              for i in range(k)]
    breaks.append(float(data[-1]))
    breaks = sorted(set(breaks))
    return breaks, _format_labels(breaks, decimals)


def classify_breaks(spec: ScalarStyleSpec, *, values: np.ndarray,
                    vmin: float, vmax: float, n: int | None = None):
    """Derive (breaks, labels) per the spec; manual_range overrides span."""
    classes = int(n or spec.n_classes)
    if spec.manual_range is not None:
        vmin, vmax = (float(v) for v in spec.manual_range)
    if spec.classification == "explicit":
        breaks = [float(v) for v in (spec.explicit_breaks or ())]
        if len(breaks) < 2:
            raise ValueError("explicit_breaks needs at least two values")
        return breaks, _format_labels(breaks, spec.colorbar_decimals)
    if spec.classification == "equal_interval":
        return equal_interval_breaks(vmin, vmax, n=classes,
                                     decimals=spec.colorbar_decimals)
    if spec.classification == "quantile":
        return quantile_breaks(values, n=classes,
                               decimals=spec.colorbar_decimals)
    if spec.classification == "natural_breaks":
        return natural_breaks(values, n=classes,
                              decimals=spec.colorbar_decimals)
    raise ValueError(f"unknown classification {spec.classification!r}")


# ---------------------------------------------------------------------------
# Ramp items (value → color) for the shader


def ramp_items_for_spec(spec: ScalarStyleSpec, ramp, span: tuple[float, float],
                        *, mode: str,
                        breaks: Sequence[float] | None = None) -> list[dict]:
    """Shader items: ``{"value", "color", "label"}``.

    continuous: stops across the span; classified: one item per class break
    (step ramp).  ``ramp`` is a :class:`mapping.color_ramps.ColorRamp`.
    """
    from paleo_workbench.mapping.color_ramps import _hex_to_rgb

    def _rgb(hex_color: str) -> tuple[int, int, int]:
        r, g, b, _alpha = _hex_to_rgb(hex_color)
        return int(r), int(g), int(b)

    vmin, vmax = float(span[0]), float(span[1])
    if vmax <= vmin:
        raise ValueError("ramp span needs vmax > vmin")
    decimals = spec.colorbar_decimals
    if mode == "classified":
        if not breaks or len(breaks) < 2:
            raise ValueError("classified ramp items need breaks")
        positions = [(float(b) - vmin) / (vmax - vmin) for b in breaks]
        positions[0], positions[-1] = 0.0, 1.0
        items = []
        for position, value in zip(positions, breaks):
            items.append({
                "value": float(value),
                "color": _rgb(ramp.evaluate(position)),
                "label": f"{float(value):.{decimals}f}",
            })
        if spec.reverse:
            # values stay ascending; the color assignment flips end-for-end
            colors = [item["color"] for item in items]
            items = [dict(item, color=color)
                     for item, color in zip(items, reversed(colors))]
        return items
    stops = 17  # smooth continuous ramp with bounded item count
    items = []
    for index in range(stops):
        position = index / (stops - 1)
        color = ramp.evaluate(1.0 - position if spec.reverse else position)
        value = vmin + position * (vmax - vmin)
        items.append({
            "value": value,
            "color": _rgb(color),
            "label": f"{value:.{decimals}f}",
        })
    return items


# ---------------------------------------------------------------------------
# Bridge encode (renderer XML authored by QGIS itself)


def scalar_style_pipeline_ready() -> dict[str, Any]:
    """Probe for the FULL scalar QGIS styling path (bridge + gdal)."""
    from paleo_workbench.mapping.qgis_style import qgis_bridge_available

    from paleo_workbench.mapping.scalar_data_mirror import (
        scalar_data_mirror_ready,
    )

    gdal_status = scalar_data_mirror_ready()
    bridge = qgis_bridge_available()
    reasons = []
    if not bridge:
        reasons.append("qgis_render_bridge not built")
    if not gdal_status["gdal"]:
        reasons.append(str(gdal_status["reason"]))
    return {
        "bridge": bridge,
        "gdal": gdal_status["gdal"],
        "ready": bridge and gdal_status["gdal"],
        "reason": "; ".join(reasons),
    }


def encode_scalar_renderer_xml(spec: ScalarStyleSpec, *,
                               stats: dict[str, Any],
                               crs: str | None = None) -> str:
    """Build the QGIS raster renderer XML via the vendored bridge.

    ``stats`` carries the grid's finite statistics (``min``/``max`` plus the
    raw ``values`` for data-driven classification).  Raises
    ``RuntimeError`` when the bridge is unavailable — there is deliberately
    NO hand-rolled XML fallback (a drifted XML would render wrong maps).
    """
    status = scalar_style_pipeline_ready()
    if not status["bridge"]:
        raise RuntimeError(
            "scalar renderer XML requires the qgis_render_bridge "
            f"({status['reason']}); use the RGBA mirror and disclose the "
            "degradation instead")
    import json as _json

    import qgis_render_bridge as native

    values = np.asarray(stats.get("values", ()), dtype=float)
    finite = values[np.isfinite(values)] if values.size else values
    vmin = float(stats.get("min") if stats.get("min") is not None else (
        finite.min() if finite.size else 0.0))
    vmax = float(stats.get("max") if stats.get("max") is not None else (
        finite.max() if finite.size else 1.0))
    if vmax <= vmin:
        vmax = vmin + 1.0  # degenerate span; renderer still needs hi > lo
    breaks, labels = classify_breaks(spec, values=finite, vmin=vmin, vmax=vmax)

    from paleo_workbench.mapping.color_ramps import get_color_ramp

    ramp = get_color_ramp(spec.ramp_name)
    items = ramp_items_for_spec(spec, ramp, (vmin, vmax),
                                mode="classified" if spec.mode == "classified"
                                else "continuous", breaks=breaks)
    payload = {
        "ramp_name": spec.ramp_name,
        "mode": spec.mode,
        "items": items,
        "min": vmin,
        "max": vmax,
        "opacity": float(spec.opacity),
        "nodata_transparent": bool(spec.nodata_transparent),
        "unit_label": spec.unit_label,
        "colorbar_title": spec.colorbar_title,
        "crs": crs or "",
        "labels": labels,
    }
    return native.build_scalar_renderer_xml(_json.dumps(payload))
