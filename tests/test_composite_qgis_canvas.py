"""M1 Task 6: 综合编修文档区由 QgsMapCanvas 承载（shim 契约）。"""
import pytest

pytest.importorskip("PySide6")


def test_composite_document_hosts_qgis_canvas(qtbot):
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    doc = CompositeDocument(ProjectDocument.new("t"))
    qtbot.addWidget(doc)
    doc.resize(900, 600)
    doc.show()

    assert isinstance(doc.canvas, QgisCanvasShim)
    assert doc.canvas.canvas.width() > 0  # 真 QgsMapCanvas 已在布局中
    doc.canvas.backend_status_changed.emit  # 信号存在
    assert "qgis" in doc.canvas.backend_status.lower()


def test_shim_mirrors_vector_snapshot_to_project(qtbot):
    from paleo_workbench.mapping.map_render_backend import (
        MapLayerSnapshot, MapRenderSnapshot,
    )
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    doc = CompositeDocument(ProjectDocument.new("t"))
    qtbot.addWidget(doc)
    doc.canvas.set_layer_snapshot(MapRenderSnapshot(
        project_crs="EPSG:4326",
        layers=[
            MapLayerSnapshot(
                id="w1", name="井位", layer_type="vector",
                data_revision=1, style_revision=1, visible=True, opacity=1.0,
                extent=(0.0, 0.0, 10.0, 10.0), crs="EPSG:4326",
                features=({"id": "f1",
                           "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
                           "properties": {}},),
                style={"fill": "#e03131", "stroke": "#1f2937", "stroke_width": 1.0,
                       "marker": "circle", "marker_size": 6.0},
            ),
        ],
    ))
    assert doc.canvas.stack.project_layer_count() == 1
