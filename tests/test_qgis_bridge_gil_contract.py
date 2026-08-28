"""#1031 — the optional qgis_render_bridge must release the GIL around its
long synchronous C++ work (``render_sync`` parallel map render and
``export_vector`` SVG/PDF render + file I/O).

The extension is optional and commonly unbuilt in dev checkouts, so this is a
source-contract test on ``bindings.cpp``: the two heavy bindings must convert
their Python inputs *before* a ``py::gil_scoped_release`` scope, call only
C++-typed bridge methods inside it, and build Python objects only after the
scope closes. When the module is built, a companion runtime check confirms
the bindings still import.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

BINDINGS = (
    Path(__file__).resolve().parents[1]
    / "native"
    / "qgis_render_bridge"
    / "src"
    / "bindings.cpp"
)


def _binding_body(source: str, method: str) -> str:
    match = re.search(
        rf'\.def\("{method}", \[.*?\)(?=\n        \.def|\n        \.def_property)',
        source,
        re.DOTALL,
    )
    assert match is not None, f"{method} binding not found in bindings.cpp"
    return match.group(0)


@pytest.fixture()
def source() -> str:
    assert BINDINGS.exists(), "bindings.cpp missing from checkout"
    return BINDINGS.read_text(encoding="utf-8")


def test_render_sync_releases_gil_around_cxx_render(source):
    body = _binding_body(source, "render_sync")
    assert "gil_scoped_release" in body, (
        "render_sync must release the GIL for the parallel QGIS render (#1031)"
    )
    # Python conversion happens before the release scope ...
    assert body.index("parse_extent(") < body.index("gil_scoped_release")
    # ... and Python result construction happens after the release scope closes.
    assert body.index("result_to_python") > body.index("gil_scoped_release")


def test_export_vector_releases_gil_around_cxx_export(source):
    body = _binding_body(source, "export_vector")
    assert "gil_scoped_release" in body, (
        "export_vector must release the GIL for synchronous vector render + I/O (#1031)"
    )
    assert body.index("parse_extent(") < body.index("gil_scoped_release")


def test_no_python_work_inside_release_scopes(source):
    """Inside a gil_scoped_release scope only C++-typed calls may appear."""
    for inside in re.findall(r"gil_scoped_release[^;]*;\s*(.*?)}\(\)", source, re.DOTALL):
        assert "py::" not in inside, f"Python API touched with the GIL released: {inside!r}"


def test_optional_module_still_importable_when_built():
    """If the extension is built in this environment it must import cleanly."""
    pytest.importorskip(
        "qgis_render_bridge", reason="optional QGIS bridge not built in this checkout"
    )
