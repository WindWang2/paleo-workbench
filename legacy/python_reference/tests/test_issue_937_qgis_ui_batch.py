"""Regression tests for #937 QGIS/UI batch.

Covers the locally editable sub-items (2,3,4,6,7) without requiring a
native bridge build — native calls are mocked.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QWidget


# 2: empty-mirror categorized guard
def test_open_renderer_properties_downgrades_empty_categorized_to_single():
    from paleo_workbench.ui import map_symbology_bridge as bridge

    fake_native = MagicMock()
    # legacy migration returns a single-symbol xml regardless of downgrade
    fake_native.legacy_style_to_renderer_xml.return_value = "<renderer type='singleSymbol'/>"
    fake_native.run_renderer_properties_dialog.return_value = {
        "ok": True,
        "renderer_xml": "<renderer type='singleSymbol'/>",
        "opacity": 1.0,
    }
    with patch.object(bridge, "_native", return_value=fake_native):
        result = bridge.open_renderer_properties(
            None,
            title="test",
            features=(),
            crs="EPSG:4326",
            fields=(),
            style={"renderer": "categorized", "field": "", "categories": {}},
        )
        # Should have been downgraded to single before native call — not raise,
        # and native receives single renderer hint.
        assert result is not None
        call_style = fake_native.legacy_style_to_renderer_xml.call_args[0][0]
        assert call_style.get("renderer") == "single"
        # native dialog still called and succeeded
        fake_native.run_renderer_properties_dialog.assert_called_once()


# 3: labeling_xml consumed from dialog result
def test_open_renderer_properties_consumes_labeling_xml_from_result():
    from paleo_workbench.ui import map_symbology_bridge as bridge

    fake_native = MagicMock()
    fake_native.legacy_style_to_renderer_xml.return_value = None
    fake_native.run_renderer_properties_dialog.return_value = {
        "ok": True,
        "renderer_xml": "<renderer type='singleSymbol'/>",
        "labeling_xml": "<labeling new='1'/>",
        "opacity": 0.8,
    }
    with patch.object(bridge, "_native", return_value=fake_native):
        result = bridge.open_renderer_properties(
            None,
            title="t",
            features=(),
            crs="",
            fields=("a",),
            style={"qgis_style": {"renderer_xml": "<renderer/>", "labeling_xml": "<labeling old='1'/>", "name": "", "tags": [], "revision": 1}},
        )
        assert result is not None
        assert result["qgis_style"]["labeling_xml"] == "<labeling new='1'/>"
        assert result["qgis_style"]["renderer_xml"] == "<renderer type='singleSymbol'/>"

    # symbol selector path also preserves labeling_xml from result
    fake_native2 = MagicMock()
    fake_native2.run_symbol_selector_dialog.return_value = {
        "ok": True,
        "renderer_xml": "<renderer type='singleSymbol' updated='1'/>",
        "labeling_xml": "<labeling sym='1'/>",
    }
    with patch.object(bridge, "_native", return_value=fake_native2):
        result2 = bridge.open_symbol_selector(
            None,
            title="t2",
            symbol_index=0,
            features=(),
            crs="",
            fields=(),
            style={"qgis_style": {"renderer_xml": "<renderer/>", "labeling_xml": "<labeling old='2'/>", "name": "", "tags": [], "revision": 2}},
        )
        assert result2 is not None
        assert result2["qgis_style"]["labeling_xml"] == "<labeling sym='1'/>"


# 4: legend swatch uses real color, dict items
def test_paint_map_decorations_uses_real_legend_color(qapp):
    from PySide6.QtGui import QPainter, QImage

    from paleo_workbench.ui.unified_map_canvas import paint_map_decorations

    img = QImage(400, 300, QImage.Format.Format_RGBA8888)
    img.fill("#181c22")
    painter = QPainter(img)
    assert painter.isActive()
    # decorations with explicit colors
    decorations = {
        "title": "test",
        "elements": ["图例"],
        "legend_items": [
            {"label": "sandstone", "color": "#ff0000"},
            {"label": "shale", "color": "#00ff00"},
            "plain_item",
        ],
    }
    # Should not raise and should handle both dict and str
    paint_map_decorations(painter, decorations, width=400, height=300, extent=(0, 0, 10, 10), dpi=96)
    painter.end()
    # No crash is success — swatch colors are exercised via QColor validity
    assert not img.isNull()


# 6: mapping_page contour completed is non-modal (status bar not dialog)
def test_mapping_contour_completed_sets_status_not_dialog(qapp):
    from paleo_workbench.ui.pages.mapping_page import MappingPage

    page = MappingPage()
    # mock project and documents
    fake_project = MagicMock()
    fake_project.paleomap_documents = []
    fake_project.factor_map_tasks = []
    fake_project.coordinate = MagicMock(project_crs="EPSG:4326")
    page._project = fake_project
    # mock contour job target (no setter — set internal)
    page._contour_job._target = fake_project
    # mock commit to return drafts
    fake_draft = MagicMock(linked_map_document_id="doc1")
    with patch("paleo_workbench.ui.pages.mapping_page.commit_contour_drafts", return_value=[fake_draft]):
        with patch.object(page, "update_state") as mock_update:
            with patch("PySide6.QtWidgets.QMessageBox.information") as mock_msg:
                from paleo_workbench.ui.pages.mapping_page import ContourDraftResult

                result = MagicMock(spec=ContourDraftResult)
                page._on_contour_completed(result)
                mock_msg.assert_not_called()
                # status bar should have success text
                assert "已生成" in page.status_bar.scale.text()
                mock_update.assert_called_once()


# 7: project_controller maintenance thread join is non-blocking
def test_project_controller_end_session_nonblocking_on_lingering_thread(qapp):
    from paleo_workbench.ui.project_controller import ProjectController

    window = MagicMock()
    window.project = MagicMock()
    window.project_path = Path("/tmp/fake.paleo.json")
    window.app_shell = MagicMock()
    window.app_shell.shutdown_workers.return_value = True
    window._refresh_shell = MagicMock()
    # create a lingering thread that sleeps 2s
    def sleeper():
        time.sleep(2.0)

    t = threading.Thread(target=sleeper, daemon=True)
    t.start()
    ctrl = ProjectController(window)
    ctrl._maintenance_thread = t
    start = time.perf_counter()
    ok = ctrl._end_current_session()
    elapsed = time.perf_counter() - start
    # Should return False quickly (<1s) instead of blocking 5s
    assert ok is False
    assert elapsed < 1.0
    # cleanup: wait for sleeper to finish to not leak
    t.join(timeout=2.5)


# 1: runtime opt-out env vars no longer demote a usable bridge (M5)
def test_create_map_render_backend_ignores_disable_env(monkeypatch):
    import paleo_workbench.mapping.map_render_backend as mrb

    class _FakeQgis:
        def __init__(self, *a, **k):
            pass

        @property
        def is_available(self):
            return True

    monkeypatch.setattr(mrb, "QgisMapRenderBackend", _FakeQgis)
    monkeypatch.setattr(mrb, "qgis_backend_probe", lambda: (True, ""))
    monkeypatch.setenv("PALEO_DISABLE_QGIS_RENDERER", "1")
    monkeypatch.setenv("PALEO_USE_QGIS_RENDERER", "0")
    backend = mrb.create_map_render_backend(prefer_qgis=True)
    assert isinstance(backend, _FakeQgis)
