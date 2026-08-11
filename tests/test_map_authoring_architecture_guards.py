"""Static guardrails for the unified 2-D GIS authoring path.

These checks deliberately parse source without importing Qt, GDAL, or the optional
native QGIS bridge.  They defend the architectural boundary rather than rendering
appearance: host state remains authoritative and QGIS stays behind a narrow C++ seam.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HOST = ROOT / "paleo_workbench"


def _tree(relative: str) -> ast.AST:
    path = HOST / relative
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(tree: ast.AST) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_primary_mapping_page_uses_the_renderer_neutral_unified_canvas() -> None:
    imports = _imports(_tree("ui/pages/mapping_page.py"))
    assert "paleo_workbench.ui.unified_map_canvas" in imports
    assert "paleo_workbench.ui.native_map_canvas" not in imports
    assert not any(name.startswith("matplotlib") for name in imports)


def test_host_never_imports_qgis_python_or_pyqt_gui_objects() -> None:
    violations = []
    for path in HOST.rglob("*.py"):
        if "__pycache__" in path.parts or "_vendored" in path.parts:
            continue
        for module in _imports(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            if module == "qgis" or module.startswith("qgis.") or module == "PyQt6" or module.startswith("PyQt6."):
                violations.append(f"{path.relative_to(HOST)}: {module}")
    assert not violations, "native bridge boundary was bypassed:\n  " + "\n  ".join(violations)


def test_render_backends_cannot_trigger_scientific_interpolation() -> None:
    forbidden = ("factor_interpolation", "constrained_idw_adapter", "interpolate_")
    for relative in (
        "mapping/map_render_backend.py",
        "mapping/scalar_raster_mirror.py",
        "ui/unified_map_canvas.py",
    ):
        source = (HOST / relative).read_text(encoding="utf-8")
        assert not any(value in source for value in forbidden), relative


def test_vector_edit_authority_is_qt_item_free() -> None:
    for relative in ("mapping/vector_layer.py", "mapping/map_authoring.py", "mapping/map_tools.py"):
        imports = _imports(_tree(relative))
        assert not any("QGraphics" in module or module.startswith("PySide6.QtWidgets") for module in imports), relative


def test_mapping_page_has_no_direct_feature_painter() -> None:
    source = (HOST / "ui/pages/mapping_page.py").read_text(encoding="utf-8")
    assert "QPainter" not in source
    assert "render_sync(" not in source
