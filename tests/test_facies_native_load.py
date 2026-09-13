"""加载工程后，领域 fill_patterns 必须落到原生画布，不被信封 singleSymbol 盖掉。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.qgis_support import QGIS_MARKER, require_mapstack

PROJECT = Path(
    "/home/kevin/projects/paleo_project/data/project_area/project_area.paleo.json"
)

pytestmark = pytest.mark.skipif(
    not PROJECT.is_file(), reason="project_area fixture missing")


@pytest.mark.qgis
def test_loaded_facies_layer_keeps_svgfill_on_native_canvas(qapp, tmp_path):
    """信封是 singleSymbol 时，加载后原生渲染器仍应是带 SVGFill 的分类。"""
    require_mapstack()
    payload = json.loads(PROJECT.read_text(encoding="utf-8"))
    xml = str(payload.get("map_qgis_project_xml") or "")
    assert "singleSymbol" in xml
    assert "SVGFill" not in xml
    dest = tmp_path / "project_area.paleo.json"
    dest.write_text(PROJECT.read_text(encoding="utf-8"), encoding="utf-8")

    from paleo_workbench.project.manager import ProjectManager
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    project = ProjectManager(str(dest)).load()
    document = CompositeDocument(project)
    assert document.uses_native_stack
    layer = next(iter(document.edit_controller._layers.values()))
    assert layer.style.get("fill_patterns")
    info = document.canvas.stack.mirror_style_json(layer.id)
    renderer_xml = str(info.get("renderer_xml") or "")
    assert "categorizedSymbol" in renderer_xml, renderer_xml[:400]
    assert "SVGFill" in renderer_xml, renderer_xml[:400]
