"""Scalar-factor QGIS publish payloads (v7 §5).

One helper shared by BOTH publish paths (offscreen ``QgisMapRenderBackend``
and the interactive ``QgisMapStack`` mirror) so a scalar grid becomes the
SAME thing on screen and in export: a single-band float32 GeoTIFF data
mirror + a QGIS-authored pseudocolor renderer XML.

Availability is honest: when the bridge or GDAL is missing (or the render
payload exposes no raw grid), :func:`build_scalar_qgis_payload` returns
``None`` and callers fall back to the RGBA mirror / skip with disclosure —
never a silently wrong render.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from paleo_workbench.mapping.scalar_data_mirror import ScalarDataMirror
from paleo_workbench.mapping.scalar_style import (
    ScalarStyleSpec,
    encode_scalar_renderer_xml,
    scalar_style_pipeline_ready,
)

__all__ = [
    "build_scalar_qgis_payload",
    "raster_source_qgis_payload",
    "scalar_spec_from_layer_style",
]

#: scene ``color_ramp`` vocabulary (native_factor_map set_scalar_style) →
#: the shared ColorRamp library names used for QGIS styling.
_SCENE_RAMP_ALIASES = {
    "default": "viridis",
    "grayscale": "gray",
    "warm_cool": "coolwarm",
    "": "viridis",
}

#: cap on values shipped for data-driven classification (quantile/Jenks run
#: host-side; a representative sample is statistically sufficient and keeps
#: the JSON payload bounded).
_CLASSIFICATION_SAMPLE = 20_000


def scalar_spec_from_layer_style(style: dict[str, Any] | None) -> ScalarStyleSpec:
    """Derive the QGIS ScalarStyleSpec from the scene's persisted scalar
    style dict.  A full ``{"scalar_style": {...}}`` block (ScalarStyleSpec
    serialization) wins; the legacy flat vocabulary (color_ramp/color_range/
    nodata) maps onto the spec's continuous mode."""
    style = style or {}
    nested = style.get("scalar_style")
    if isinstance(nested, dict) and nested:
        return ScalarStyleSpec.from_dict(nested)
    ramp = str(style.get("color_ramp") or "").strip().lower()
    kwargs: dict[str, Any] = {
        "ramp_name": _SCENE_RAMP_ALIASES.get(ramp, ramp or "viridis"),
    }
    color_range = style.get("color_range")
    if isinstance(color_range, (list, tuple)) and len(color_range) == 2:
        try:
            lo, hi = (float(color_range[0]), float(color_range[1]))
            if hi > lo:
                kwargs["manual_range"] = (lo, hi)
        except (TypeError, ValueError):
            pass
    if str(style.get("unit") or ""):
        kwargs["unit_label"] = str(style["unit"])
    return ScalarStyleSpec(**kwargs)


def _stats_from_grid(grid: np.ndarray, spec: ScalarStyleSpec) -> dict[str, Any]:
    finite = np.asarray(grid, dtype=float)
    finite = finite[np.isfinite(finite)]
    values = finite
    if finite.size > _CLASSIFICATION_SAMPLE:
        generator = np.random.default_rng(0)
        values = generator.choice(finite, size=_CLASSIFICATION_SAMPLE,
                                  replace=False)
    return {
        "min": float(finite.min()) if finite.size else None,
        "max": float(finite.max()) if finite.size else None,
        "values": values,
    }


def build_scalar_qgis_payload(layer, data_cache: ScalarDataMirror) -> dict[str, Any] | None:
    """Payload for one scalar_grid layer: {source_path, renderer_xml, spec}.

    ``None`` when the scalar QGIS path is unavailable (bridge/gdal/raw grid)
    — the caller must then use the RGBA mirror (offscreen) or skip with
    disclosure (canvas).
    """
    if layer.layer_type != "scalar_grid":
        raise TypeError("scalar payloads are for scalar_grid layers")
    status = scalar_style_pipeline_ready()
    if not status["ready"]:
        return None
    scalar = layer.renderer_payload
    grid_getter = getattr(scalar, "grid_array", None)
    if grid_getter is None:
        return None  # payload cannot expose raw values (older native build)
    try:
        grid = grid_getter()
    except (RuntimeError, ValueError):
        return None
    if grid is None or grid.ndim != 2 or grid.size == 0:
        return None
    spec = scalar_spec_from_layer_style(layer.style)
    stats = _stats_from_grid(grid, spec)
    source = data_cache.ensure(
        layer_id=str(layer.id), grid=grid,
        extent=tuple(float(v) for v in layer.extent),
        crs=layer.crs, data_revision=int(layer.data_revision),
    )
    renderer_xml = encode_scalar_renderer_xml(
        spec, stats=stats, crs=layer.crs)
    return {"source_path": source, "renderer_xml": renderer_xml, "spec": spec}


def raster_source_qgis_payload(layer) -> dict[str, Any] | None:
    """Payload for a raster_source layer: the file path mirrored natively
    (no scalar styling — reference imagery keeps its own pixels)."""
    if layer.layer_type != "raster_source":
        raise TypeError("raster payloads are for raster_source layers")
    source = str(layer.renderer_payload or "")
    if not source:
        return None
    return {"source_path": source, "renderer_xml": "", "spec": None}
