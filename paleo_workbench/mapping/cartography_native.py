"""Optional C++ cartography facade over the CONV-27 registries.

The pybind11 module ``pwb_cartography`` (built from
``libs/cartography/cartography_bind/``, see
``paleo_workbench/mapping/CPP_EXTENSION.md``) wraps the Qt-free cartography
library frozen against the Python oracles (color ramps, geological symbols,
style libraries, template factories, scalar classification). This module is
the only seam that dispatches to it:

* ``HAS_CPP`` is True only when ``import pwb_cartography`` succeeds.
* Every entry point mirrors the production Python surface
  (``mapping.color_ramps`` / ``mapping.geological_symbols`` /
  ``mapping.geological_pipeline.templates`` / ``mapping.scalar_style`` /
  ``mapping.map_render_backend._flatten_qgis_style``); when the extension is
  absent the caller falls back to those modules, so behavior is identical
  with and without the extension.
* The C++ kernels are the product path for the C++ runtime; this facade
  exists so the Python legacy surface can be accelerated without changing
  any contract. Registry errors propagate with the exact frozen messages
  (KeyError texts from ``symbol_by_id`` / template lookup).

Import this module directly; existing product modules are untouched. Example::

    from paleo_workbench.mapping import cartography_native
    if cartography_native.HAS_CPP:
        doc = cartography_native.symbol_library_document()
"""
from __future__ import annotations

import math

try:
    import pwb_cartography as _cartography
except ImportError:  # extension not built / not on sys.path
    _cartography = None

HAS_CPP = _cartography is not None

__all__ = [
    "HAS_CPP",
    "binding_record",
    "classify_equal_interval",
    "classify_quantile",
    "color_ramp_document",
    "evaluate_ramp",
    "evaluate_ramp_value",
    "flatten_qgis_style",
    "instantiate_template",
    "list_color_ramps",
    "list_symbols",
    "list_templates",
    "symbol_library_document",
    "validate_binding",
]


def list_color_ramps() -> list[str]:
    """Registry names in insertion order (get_color_ramp fallback rules)."""
    if HAS_CPP:
        return list(_cartography.list_color_ramps())
    from paleo_workbench.mapping.color_ramps import list_color_ramps as _py

    return _py()


def color_ramp_document(name: str) -> dict:
    """The ramp document; unknown names resolve to viridis (parity)."""
    if HAS_CPP:
        return dict(_cartography.color_ramp_document(name))
    from paleo_workbench.mapping.color_ramps import get_color_ramp

    return get_color_ramp(name).to_dict()


def evaluate_ramp(name: str, t: float) -> str:
    """Sample the ramp at t (non-finite -> nodata color)."""
    if HAS_CPP:
        return _cartography.evaluate_ramp(name, float(t))
    from paleo_workbench.mapping.color_ramps import get_color_ramp

    return get_color_ramp(name).evaluate(t)


def evaluate_ramp_value(name: str, value: float, vmin: float,
                        vmax: float) -> str:
    """Sample the ramp by data value and bounds."""
    if HAS_CPP:
        return _cartography.evaluate_ramp_value(name, float(value),
                                                float(vmin), float(vmax))
    from paleo_workbench.mapping.color_ramps import get_color_ramp

    return get_color_ramp(name).evaluate_value(value, vmin, vmax)


def list_symbols() -> list[str]:
    """The V2 geological symbol ids in registry order."""
    if HAS_CPP:
        return list(_cartography.list_symbols())
    from paleo_workbench.mapping.geological_symbols import GEOLOGICAL_SYMBOLS

    return list(GEOLOGICAL_SYMBOLS)


def symbol_library_document() -> dict:
    """``{"schema_version": 2, "symbols": [...]}`` in registry order."""
    if HAS_CPP:
        return dict(_cartography.symbol_library_document())
    from paleo_workbench.mapping.geological_symbols import library_to_dict

    return library_to_dict()


def binding_record(symbol_id: str) -> dict:
    """The style<->science traceability record for a symbol."""
    if HAS_CPP:
        return dict(_cartography.binding_record(symbol_id))
    from paleo_workbench.mapping.geological_symbols import (
        binding_record as _py,
    )

    return _py(symbol_id)


def validate_binding(symbol_id: str, role: str,
                     geometry_kind: str) -> tuple[bool, str]:
    """Role/geometry compatibility check (frozen reason strings)."""
    if HAS_CPP:
        ok, reason = _cartography.validate_binding(symbol_id, role,
                                                   geometry_kind)
        return bool(ok), reason
    from paleo_workbench.mapping.geological_symbols import (
        validate_binding as _py,
    )

    return _py(symbol_id, role, geometry_kind)


def list_templates() -> list[dict]:
    """The five standard map template catalog entries."""
    if HAS_CPP:
        return [dict(row) for row in _cartography.list_templates()]
    from paleo_workbench.mapping.geological_pipeline.templates import (
        create_geological_factor_map_template as _factor,
    )

    # No Python catalog exists (the C++ library owns the five-factory
    # vocabulary); the factor factory is the only Python-parity entry.
    return [{"name": "factor_map", "title": "地质因子图",
             "description": "Python-parity factor map composition"}]


def instantiate_template(request: dict) -> dict:
    """Build a composition document from a template request dict.

    Request keys: template_name, map {id, title, layer_count, extent},
    title, factor_name, unit, paper_size, orientation. The C++ library owns
    all five factories; the Python fallback covers only the parity one.
    """
    if HAS_CPP:
        return dict(_cartography.instantiate_template(request))
    from paleo_workbench.mapping.geological_pipeline.templates import (
        create_geological_factor_map_template,
    )
    from paleo_workbench.mapping.layers import MapDocument

    if request.get("template_name", "factor_map") != "factor_map":
        raise KeyError(
            f"unknown template {request.get('template_name')!r}; "
            "Python fallback only covers 'factor_map'"
        )
    map_doc = MapDocument(
        id=str(request.get("map", {}).get("id", "")),
        title=str(request.get("map", {}).get("title", "")),
    )
    extent = request.get("map", {}).get("extent", (0.0, 0.0, 1.0, 1.0))
    map_doc.extent = tuple(float(v) for v in extent)
    composition = create_geological_factor_map_template(
        map_doc,
        title=request.get("title") or None,
        factor_name=str(request.get("factor_name", "")),
        unit=str(request.get("unit", "")),
        paper_size=str(request.get("paper_size", "A4")),
        orientation=str(request.get("orientation", "landscape")),
    )
    return composition.to_dict()


def classify_equal_interval(vmin: float, vmax: float, n: int = 5,
                            decimals: int = 2) -> tuple[list, list]:
    """np.linspace breaks + fixed-decimal labels."""
    if HAS_CPP:
        breaks, labels = _cartography.classify_equal_interval(
            float(vmin), float(vmax), int(n), int(decimals))
        return list(breaks), list(labels)
    from paleo_workbench.mapping.scalar_style import equal_interval_breaks

    return equal_interval_breaks(vmin, vmax, n=n, decimals=decimals)


def classify_quantile(values: list, n: int = 5,
                      decimals: int = 2) -> tuple[list, list]:
    """np.quantile breaks over the finite values (monotonicity enforced)."""
    finite = [float(v) for v in values if isinstance(v, (int, float))
              and not isinstance(v, bool) and math.isfinite(float(v))]
    if HAS_CPP:
        breaks, labels = _cartography.classify_quantile(finite, int(n),
                                                        int(decimals))
        return list(breaks), list(labels)
    import numpy as np

    from paleo_workbench.mapping.scalar_style import quantile_breaks

    return quantile_breaks(np.asarray(finite, dtype=float), n=n,
                           decimals=decimals)


def flatten_qgis_style(style: dict) -> dict:
    """Promote the authoritative qgis_style payload + unit conversions."""
    if HAS_CPP:
        return dict(_cartography.flatten_qgis_style(style))
    from paleo_workbench.mapping.map_render_backend import (
        _flatten_qgis_style as _py,
    )

    return _py(style)
