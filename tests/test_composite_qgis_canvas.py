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


def test_shim_mupp_non_square_aspect_consistent(qtbot):
    """F3 回归: 非正方形画布下 map_units_per_pixel 与 fitted extent/width 一致。"""
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim

    shim = QgisCanvasShim()
    qtbot.addWidget(shim)
    shim.resize(800, 400)
    shim.show()
    qtbot.waitExposed(shim)
    qtbot.wait(300)
    shim.set_extent((0.0, 0.0, 10.0, 10.0))
    qtbot.wait(300)
    w = max(1, shim.canvas.width())
    h = max(1, shim.canvas.height())
    extent = tuple(shim.stack.canvas_extent(shim.canvas_address))
    dx = extent[2] - extent[0]
    dy = extent[3] - extent[1]
    mupp = shim.map_units_per_pixel
    expected = max(dx / w, dy / h)
    assert mupp == pytest.approx(expected, rel=1e-6)
    assert (mupp * w == pytest.approx(dx, rel=1e-3) or mupp * h == pytest.approx(dy, rel=1e-3))


def test_shim_extent_single_emission(qtbot):
    """F4 回归: 一次程序化 set_extent 只触发一次 extent_changed。"""
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim

    shim = QgisCanvasShim()
    qtbot.addWidget(shim)
    shim.resize(600, 400)
    shim.show()
    qtbot.waitExposed(shim)
    qtbot.wait(500)
    seen: list[tuple] = []
    shim.extent_changed.connect(lambda e: seen.append(tuple(e)))
    shim.set_extent((0.0, 0.0, 20.0, 20.0))
    qtbot.wait(400)
    assert len(seen) == 1, f"expected 1 emission, got {len(seen)}: {seen}"
    seen.clear()
    current = shim.view_extent
    shim.set_extent(current)
    qtbot.wait(200)
    assert len(seen) == 0, f"duplicate fitted should not emit, got {seen}"
    seen.clear()
    shim.set_extent((5.0, 5.0, 25.0, 25.0))
    qtbot.wait(300)
    assert len(seen) == 1


def test_shim_tool_operation_emits_on_user_extent(qtbot):
    """F2 回归: 用户 pan/zoom（非程序化 extent）触发 tool_operation(False)，程序化不触发。"""
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim

    shim = QgisCanvasShim()
    qtbot.addWidget(shim)
    shim.resize(600, 400)
    shim.show()
    qtbot.waitExposed(shim)
    qtbot.wait(500)
    ops: list[bool] = []
    shim.tool_operation.connect(lambda b: ops.append(bool(b)))
    shim.set_extent((0.0, 0.0, 20.0, 20.0))
    qtbot.wait(300)
    assert ops == [], f"programmatic should not emit tool_operation, got {ops}"
    shim._on_stack_extent(5.0, 5.0, 25.0, 25.0)
    assert ops == [False]
