"""M1 Task 6: 综合编修文档区由 QgsMapCanvas 承载（shim 契约）。

需要 ``qgis_render_bridge`` 的用例带 ``@pytest.mark.qgis``（packaging #437：
主 CI 门不构建桥，标记用例自跳过；``PALEO_REQUIRE_QGIS=1`` 的 QGIS 腿上
fail-closed，见 tests/qgis_support.py 与 conftest 的统一门禁）。
"""
import pytest

pytest.importorskip("PySide6")


@pytest.mark.qgis
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
    overlay = getattr(doc.canvas, "_overlay", None)
    assert overlay is not None
    from paleo_workbench.ui.qgis_stack.widgets import canvas_viewport

    viewport = canvas_viewport(doc.canvas.canvas) or doc.canvas
    assert overlay.parent() is viewport
    # 比例尺是边角小控件，不得盖住地图中心。
    center = viewport.rect().center()
    assert not overlay.geometry().contains(center)
    north = getattr(doc.canvas, "_chrome_north", None)
    assert north is not None and north.isVisible()


@pytest.mark.qgis
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
    # M2T2 审查修复回归：_mirrored_layers 保持 M1 语义（QGIS layer id），
    # doc id 另存 _mirrored_doc_ids。
    assert doc.canvas._mirrored_doc_ids == ["w1"]
    assert len(doc.canvas._mirrored_layers) == 1
    assert doc.canvas._mirrored_layers[0] != "w1"


@pytest.mark.qgis
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


@pytest.mark.qgis
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


@pytest.mark.qgis
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


def test_shim_bridge_missing_raises_actionable_error(monkeypatch):
    """F1/F2 审查修复回归: 桥缺失时报 RuntimeError 且提示可执行修复命令（offscreen-safe）。"""
    import sys

    import paleo_workbench.ui.qgis_stack.canvas_shim as shim_mod

    monkeypatch.setitem(sys.modules, "qgis_render_bridge", None)
    monkeypatch.setitem(sys.modules, "qgis_render_bridge.mapstack", None)

    with pytest.raises(RuntimeError) as excinfo:
        shim_mod._load_mapstack()
    msg = str(excinfo.value)
    assert "PALEO_WITH_QGIS_RENDERER" in msg
    assert "native/qgis_render_bridge" in msg
    assert isinstance(excinfo.value.__cause__, ImportError)


def test_mirror_failures_collected_not_swallowed():
    """#1164: per-layer and tail failures land in diagnostics; survivors stay."""
    from types import SimpleNamespace

    from paleo_workbench.ui.qgis_stack.mirror import mirror_snapshot_to_stack

    def _layer(lid):
        return SimpleNamespace(
            id=lid, name=lid, crs="EPSG:4326", visible=True, opacity=1.0,
            layer_type="vector", metadata={}, style={},
            features=[{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
                "properties": {},
            }],
        )

    class FakeStack:
        def upsert_mirror_layer(self, doc_id, *args, **kwargs):
            if doc_id == "bad":
                raise RuntimeError("boom-crs")
            return "qgis-" + doc_id

        def remove_mirror_layers_except(self, seen):
            raise RuntimeError("tail-boom")

        def set_mirror_layer_order(self, seen):
            pass

        def refresh_canvas(self, addr):
            pass

    snap = SimpleNamespace(
        project_crs="EPSG:4326", layers=[_layer("ok"), _layer("bad")],
    )
    diags: list = []
    qgis_ids, seen, failures = mirror_snapshot_to_stack(
        FakeStack(), 0, snap, diags
    )
    assert seen == ["ok"]
    assert qgis_ids == ["qgis-ok"]
    assert ("bad", "boom-crs") in diags
    assert ("<tail>", "tail-boom") in diags
    assert failures, "failures stay surfaced on the return path too"


def test_mirror_ledger_self_heals_when_bridge_layer_deleted():
    """镜像对象在桥上被删后，台账不得把「缺数据」冻结成 no-op。

    场景：源层发布过（台账有条目）→ 桥侧对象被删（clear_project_layers /
    mock 链外删除）→ 下次发布 token 全匹配，若无存在性校验会 no-op，
    图层永久隐身；副本（新 id 无台账）却正常。存在性探针失败必须作废
    条目、走完整 upsert 重建镜像。
    """
    from types import SimpleNamespace

    from paleo_workbench.mapping import qgis_mirror
    from paleo_workbench.mapping.qgis_mirror import mirror_snapshot_to_stack

    def _layer(lid):
        return SimpleNamespace(
            id=lid, name=lid, crs="EPSG:4326", visible=True, opacity=1.0,
            layer_type="vector", metadata={}, style={}, data_revision=1,
            features=[{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
                "properties": {},
            }],
        )

    class FakeStack:
        def __init__(self):
            self.deleted = set()
            self.upserts = []

        def upsert_mirror_layer(self, doc_id, *args, **kwargs):
            self.upserts.append(doc_id)
            self.deleted.discard(doc_id)
            return "qgis-" + doc_id

        def mirror_features_json(self, doc_id, limit=0):
            # 与真桥一致：缺失层返回 exists:false（不抛异常）。
            import json as _json
            return _json.dumps({"exists": doc_id not in self.deleted})

        def mirror_provider_facts(self, doc_id):
            # 真桥自省面：缺失/失效层都如实上报（不存在返回 None 等价体）。
            if doc_id in self.deleted:
                return {"exists": False, "is_valid": False}
            return {"exists": True, "is_valid": True}

        def remove_mirror_layers_except(self, seen):
            pass

        def set_mirror_layer_order(self, seen):
            pass

        def refresh_canvas(self, addr):
            pass

    stack = FakeStack()
    snap = SimpleNamespace(project_crs="EPSG:4326", layers=[_layer("src")])
    diags: list = []

    # 第一次发布：建台账。
    mirror_snapshot_to_stack(stack, 0, snap, diags)
    assert stack.upserts == ["src"]

    # 模拟桥侧对象被删（ledger 不知情）。
    stack.deleted.add("src")
    stack.upserts.clear()

    # 第二次发布：存在性探针必须让条目失效并重建。
    mirror_snapshot_to_stack(stack, 0, snap, diags)
    assert stack.upserts == ["src"], \
        "deleted mirror layer must be re-upserted, not frozen as no-op"
