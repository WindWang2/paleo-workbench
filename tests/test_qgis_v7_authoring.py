"""Goal V7 native-leg tests: capability manifest, measure tool, validate/reshape.

These require the built qgis_render_bridge (PALEO_REQUIRE_QGIS=1 leg). They
pin the native side of the V7 contract: the manifest is authoritative, the
measure tool measures correctly (ellipsoidal vs planar), geometry validate
reports details, reshape reshapes.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from tests.qgis_support import QGIS_SKIP_REASON, require_qgis  # noqa: F401

pytestmark = pytest.mark.qgis


@pytest.fixture(scope="module")
def bridge():
    native = require_qgis()
    return native


class TestCapabilityManifest:
    def test_manifest_shape(self, bridge):
        manifest = bridge.capability_manifest()
        assert manifest["contract_version"] >= 2
        assert manifest["qgis_version"].startswith("4.")
        for key in ("native_tools", "geometry_ops", "dialogs", "features"):
            assert isinstance(manifest[key], list) and manifest[key], key

    def test_manifest_lists_v7_kinds(self, bridge):
        tools = set(bridge.capability_manifest()["native_tools"])
        assert {"pan", "zoomIn", "zoomOut", "addPoint", "addLine", "addPolygon",
                "vertex", "move", "select", "identify", "measure"} <= tools

    def test_manifest_geometry_ops_include_v7(self, bridge):
        ops = set(bridge.capability_manifest()["geometry_ops"])
        assert {"validate", "reshape", "make_valid", "split_by_line", "union"} <= ops

    def test_manifest_features_declare_snapping_v7(self, bridge):
        features = set(bridge.capability_manifest()["features"])
        assert {"snapping_endpoint", "snapping_intersection", "measure_ellipsoidal"} <= features

    def test_python_snapshot_derives_from_manifest(self, bridge):
        from paleo_workbench.mapping.capability_model import probe_qgis_capability

        snapshot = probe_qgis_capability()
        assert snapshot.status == "available"
        manifest = bridge.capability_manifest()
        assert snapshot.native_tools == frozenset(manifest["native_tools"])
        assert snapshot.geometry_ops == frozenset(manifest["geometry_ops"])
        assert snapshot.bridge_version == bridge.__version__
        assert snapshot.feature("snapping_endpoint").available
        assert "qgis.native_tool.measure" in snapshot.capability_flags()


class TestGeometryValidateReshape:
    def test_validate_reports_self_intersection(self, bridge):
        bowtie = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [4, 0], [0, 4], [4, 4], [0, 0]]],
        }
        errors = bridge.geometry.validate(bowtie)
        assert isinstance(errors, list) and errors
        assert all("message" in entry for entry in errors)

    def test_validate_clean_geometry(self, bridge):
        clean = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]],
        }
        assert bridge.geometry.validate(clean) == []

    def test_topology_service_uses_bridge_validation(self, bridge):
        from paleo_workbench.mapping.topology import TopologyService
        from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer

        layer = VectorLayer(id="composite:L1", name="x")
        layer.start_editing()
        layer.edit_session.add_feature(
            VectorFeature(
                "bad",
                {"type": "Polygon",
                 "coordinates": [[[0, 0], [4, 0], [0, 4], [4, 4], [0, 0]]]},
                {},
            )
        )
        issues = TopologyService().validate([layer])
        assert issues and issues[0]["feature_id"] == "bad"

    def test_reshape_polygon_boundary(self, bridge):
        target = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [10, 0], [10, 6], [0, 6], [0, 0]]],
        }
        line = {"type": "LineString", "coordinates": [[2, -1], [2, 7]]}
        reshaped = json.loads(bridge.geometry.reshape(json.dumps(target), json.dumps(line)))
        assert reshaped["type"] in {"Polygon", "MultiPolygon"}
        # The reshape line (x=2 vertical cut) replaces the left boundary:
        # the ring's left edge moves from x=0 to x=2 (QgsGeometry semantics —
        # boundary substitution, not vertex insertion).
        ring = reshaped["coordinates"][0]
        xs = sorted({round(p[0]) for p in ring})
        assert 2 in xs and 0 not in xs

    def test_reshape_nonintersecting_line_errors(self, bridge):
        target = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]],
        }
        line = {"type": "LineString", "coordinates": [[100, 100], [200, 200]]}
        with pytest.raises(Exception):
            bridge.geometry.reshape(json.dumps(target), json.dumps(line))


class TestNativeMeasureTool:
    def _stack_canvas(self, qtbot):
        from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim

        shim = QgisCanvasShim()
        qtbot.addWidget(shim)
        return shim

    def test_shim_detects_native_measure(self, qtbot, bridge):
        shim = self._stack_canvas(qtbot)
        assert shim._native_measure_supported

    def test_measure_tool_activates_and_reports(self, qtbot, bridge):
        shim = self._stack_canvas(qtbot)
        events: list[dict] = []
        shim.measure_updated.connect(lambda payload: events.append(dict(payload)))
        try:
            from paleo_workbench.mapping.map_tools import MapToolController, MeasureDistanceTool

            from PySide6.QtCore import QPoint, Qt
            from PySide6.QtTest import QTest

            controller = MapToolController()
            shim.set_map_tool_controller(controller)
            controller.set_active_tool(MeasureDistanceTool())
            # Native kind dispatched without raising is the activation proof.
            viewport = shim._canvas_viewport()
            assert viewport is not None
            center = viewport.rect().center()
            first = QPoint(int(center.x()), int(center.y()))
            second = QPoint(int(center.x()) + 50, int(center.y()))
            QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, first)
            QTest.mouseMove(viewport, second)
            QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, second)
            qtbot.wait(300)
        finally:
            shim.shutdown()
        if events:
            payload = events[-1]
            assert "total" in payload and "segments" in payload and "ellipsoidal" in payload
            assert len(payload["points"]) >= 1
        else:
            pytest.fail("native measure produced no callbacks")

    def test_native_tool_busy_covers_measure(self, qtbot, bridge):
        shim = self._stack_canvas(qtbot)
        try:
            assert not shim.native_tool_busy()
            shim.stack.set_map_tool(shim.canvas_address, "measure")
            assert not shim.native_tool_busy()  # no points yet
        finally:
            shim.shutdown()

    def test_measure_allowed_on_display_stack(self, bridge):
        stack = bridge.mapstack.QgisMapStack()
        stack.initialize(display=True)
        try:
            from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost  # noqa: F401

            addr = stack.create_canvas()
            stack.set_map_tool(addr, "measure")
            stack.destroy_canvas(addr)
        finally:
            stack.shutdown()


class TestSnappingEndpointPush:
    def test_endpoint_intersection_parse_without_error(self, qtbot, bridge):
        from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim

        shim = QgisCanvasShim()
        qtbot.addWidget(shim)
        try:
            shim.set_snapping_config(
                {
                    "enabled": True,
                    "mode": "all_layers",
                    "tolerance_px": 10.0,
                    "types": ["vertex", "endpoint"],
                    "intersection_enabled": True,
                    "layers": {},
                }
            )
        finally:
            shim.shutdown()
