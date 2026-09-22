"""CONV-27 — cartography_native (pybind facade) parity tests.

Skipped entirely when the optional ``pwb_cartography`` extension is not
built (same discipline as the CONV-20 bind smoke test): the pure-Python
surface stays authoritative when the extension is absent. When present,
every facade entry point must match its Python oracle implementation
exactly — the C++ kernels are frozen against the same oracles, so parity
here is the product wiring proof.
"""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.mapping import cartography_native

pytestmark = pytest.mark.skipif(
    not cartography_native.HAS_CPP,
    reason="pwb_cartography extension not built (optional CONV-27 bind)",
)


def test_has_cpp_and_ramp_parity():
    from paleo_workbench.mapping.color_ramps import (
        get_color_ramp,
        list_color_ramps,
    )

    assert cartography_native.list_color_ramps() == list_color_ramps()
    ramp = get_color_ramp("plasma")
    for t in (0.0, 0.3, 0.5, 0.7, 1.0, 2.0, -1.0):
        assert cartography_native.evaluate_ramp("plasma", t) == ramp.evaluate(t)


def test_symbol_parity():
    from paleo_workbench.mapping.geological_symbols import (
        library_to_dict,
        validate_binding,
    )

    assert cartography_native.symbol_library_document() == library_to_dict()
    assert cartography_native.validate_binding(
        "fault_v2", "paleo_shoreline", "line"
    ) == validate_binding("fault_v2", "paleo_shoreline", "line")


def test_classification_parity():
    from paleo_workbench.mapping.scalar_style import (
        equal_interval_breaks,
        quantile_breaks,
    )

    assert cartography_native.classify_equal_interval(
        -40.0, -10.0, 3, 3
    ) == equal_interval_breaks(-40.0, -10.0, n=3, decimals=3)
    values = [1.5, 2.2, 3.7, 8.1, 9.9, 10.0, 4.4, 6.6, 5.5, 7.7, 0.2, 3.3]
    cpp_breaks, cpp_labels = cartography_native.classify_quantile(values, 4, 2)
    py_breaks, py_labels = quantile_breaks(
        np.asarray(values, dtype=float), n=4, decimals=2
    )
    assert cpp_breaks == py_breaks
    assert cpp_labels == py_labels


def test_flatten_qgis_style_parity():
    from paleo_workbench.mapping.map_render_backend import (
        _flatten_qgis_style,
    )
    from paleo_workbench.mapping.map_styles import TextStyle, VectorStyle

    style = VectorStyle(
        fill="#101010",
        stroke="#eeeeee",
        labels=TextStyle(field="name", size=12.0, halo_width=2.0),
    )
    payload = style.to_dict()
    payload["qgis_style"] = {
        "schema_version": 1,
        "renderer_xml": "<renderer-v2/>",
        "labeling_xml": "",
        "name": "",
        "tags": [],
        "revision": 1,
    }
    assert cartography_native.flatten_qgis_style(payload) == (
        _flatten_qgis_style(payload)
    )


def test_template_parity():
    from paleo_workbench.mapping.geological_pipeline.templates import (
        create_geological_factor_map_template,
    )
    from paleo_workbench.mapping.layers import MapDocument

    map_doc = MapDocument(id="map_p", title="T1")
    map_doc.extent = (110.0, 35.0, 125.0, 45.0)
    py_doc = create_geological_factor_map_template(
        map_doc, factor_name="porosity", unit="%"
    ).to_dict()
    request = {
        "template_name": "factor_map",
        "map": {
            "id": "map_p",
            "title": "T1",
            # The composer stub freezes len(map_doc.layers).
            "layer_count": len(map_doc.layers),
            "extent": [110.0, 35.0, 125.0, 45.0],
        },
        "factor_name": "porosity",
        "unit": "%",
    }
    assert cartography_native.instantiate_template(request) == py_doc


def test_registry_errors_propagate():
    with pytest.raises(KeyError):
        cartography_native.binding_record("ghost_symbol")
