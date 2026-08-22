"""P3 session-10 regressions: async unified-map export, Windows ctest fail-closed."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QFileDialog

from paleo_workbench.mapping.map_render_backend import (
    FallbackMapRenderBackend,
    QgisMapRenderBackend,
)
from paleo_workbench.ui.pages.mapping_page import MappingPage
from paleo_workbench.ui.pages.visualization_page import VisualizationPage
from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas
from paleo_workbench.viz.native_factor_map import MapScene
from tests.test_unified_map_canvas import _snapshot


def _install_export_spies(monkeypatch):
    """Record GUI-thread calls to the three sync export entry points."""
    gui = threading.current_thread()
    hits: list[str] = []
    worker_names: list[str] = []
    started = threading.Event()
    release = threading.Event()

    def wrap(label, orig, *, gate_render: bool):
        def _wrapped(*args, **kwargs):
            thread = threading.current_thread()
            if thread is gui:
                hits.append(label)
            else:
                worker_names.append(thread.name)
                if gate_render:
                    started.set()
                    release.wait(timeout=5)
            return orig(*args, **kwargs)

        return _wrapped

    monkeypatch.setattr(
        UnifiedMapCanvas,
        "export_png",
        wrap("export_png", UnifiedMapCanvas.export_png, gate_render=False),
    )
    monkeypatch.setattr(
        UnifiedMapCanvas,
        "render_export_image",
        wrap(
            "render_export_image",
            UnifiedMapCanvas.render_export_image,
            gate_render=False,
        ),
    )
    monkeypatch.setattr(
        FallbackMapRenderBackend,
        "render_sync",
        wrap("render_sync", FallbackMapRenderBackend.render_sync, gate_render=True),
    )
    monkeypatch.setattr(
        QgisMapRenderBackend,
        "render_sync",
        wrap("render_sync", QgisMapRenderBackend.render_sync, gate_render=True),
    )
    return hits, worker_names, started, release, gui


def test_visualization_export_slot_does_not_render_on_gui_thread(
    qtbot, tmp_path, monkeypatch
) -> None:
    """#662: visualization PNG slot must only start the worker."""
    canvas = UnifiedMapCanvas(backend=FallbackMapRenderBackend())
    qtbot.addWidget(canvas)
    canvas.set_layer_snapshot(_snapshot())
    canvas.set_extent((0.0, 0.0, 10.0, 10.0))

    page = VisualizationPage()
    qtbot.addWidget(page)
    page.composite_panel.tabs.addTab(canvas, "统一地图")
    page.composite_panel.tabs.setCurrentWidget(canvas)

    out = tmp_path / "viz.png"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(out), "PNG")
    )
    hits, worker_names, started, release, gui = _install_export_spies(monkeypatch)

    page._export_current_view("PNG")

    assert hits == []
    assert not out.is_file()
    assert page._export_job.is_running
    assert QApplication.overrideCursor() is not None
    qtbot.waitUntil(started.is_set, timeout=5_000)
    assert worker_names
    assert worker_names[0] != gui.name
    release.set()
    qtbot.waitUntil(lambda: not page._export_job.is_running, timeout=10_000)
    assert out.is_file()
    image = QImage(str(out))
    assert not image.isNull()
    assert image.width() >= 64 and image.height() >= 64
    page.shutdown_workers(2_000)


def test_mapping_export_slot_does_not_render_on_gui_thread(
    qtbot, tmp_path, monkeypatch
) -> None:
    """#662: mapping factor-map export must not call render_sync on the GUI slot."""
    page = MappingPage()
    qtbot.addWidget(page)
    page.unified_canvas.set_layer_snapshot(_snapshot())
    page.unified_canvas.set_extent((0.0, 0.0, 10.0, 10.0))
    page._native_factor_scene = MapScene()

    out = tmp_path / "map.png"
    hits, worker_names, started, release, gui = _install_export_spies(monkeypatch)

    page.export_native_factor_map(out, register=False)

    assert hits == []
    assert not out.is_file()
    assert page._export_job.is_running
    assert QApplication.overrideCursor() is not None
    qtbot.waitUntil(started.is_set, timeout=5_000)
    assert worker_names
    assert worker_names[0] != gui.name
    release.set()
    qtbot.waitUntil(lambda: not page._export_job.is_running, timeout=10_000)
    assert out.is_file()
    image = QImage(str(out))
    assert not image.isNull()
    page.shutdown_workers(2_000)


def test_windows_ctest_step_is_fail_closed() -> None:
    """#631: Windows ctest must fail the job; hang bound is the 20-min job timeout."""
    src = Path(".github/workflows/well-log-engine.yml").read_text(encoding="utf-8")
    job_head = src.split("clang-sanitizers:", 1)[0]
    assert "timeout-minutes: 20" in job_head
    start = src.index("- name: Test (Windows)")
    end = src.index("- name: Test (Unix)")
    windows = src[start:end]
    assert "continue-on-error" not in windows
    unix = src[end : src.index("clang-sanitizers:")]
    assert "continue-on-error" not in unix
    assert "--parallel 2" in unix
    assert "timeout-minutes" not in unix


def test_reference_layers_imports_cleanly_without_gdal(monkeypatch, tmp_path) -> None:
    """#851: reference_layers must not hard-fail collection when GDAL is broken.

    The module-level ``from osgeo import gdal, osr`` made this file (and every
    module importing mapping_page) un-collectable on machines where the GDAL
    wheel and system libgdal mismatch — silently dropping ~470 tests including
    the #662 export regressions above. With osgeo made un-importable the module
    must still import, and the GDAL-backed operations must fail with a clear
    ReferenceLayerError instead of an AttributeError.
    """
    import importlib
    import sys

    import paleo_workbench.mapping.reference_layers as rl

    # The re-import below replaces sys.modules AND the parent-package
    # attribute; both must be restored or later monkeypatch targets and
    # ``from ... import`` resolve to different module objects (leak seen by
    # the project well-map reference-layer tests).
    original_module = rl
    parent_package = sys.modules["paleo_workbench.mapping"]
    monkeypatch.setattr(parent_package, "reference_layers", original_module)
    monkeypatch.setitem(
        sys.modules,
        "paleo_workbench.mapping.reference_layers",
        original_module,
    )

    monkeypatch.setitem(sys.modules, "osgeo", None)
    monkeypatch.setitem(sys.modules, "osgeo.gdal", None)
    monkeypatch.setitem(sys.modules, "osgeo.osr", None)
    monkeypatch.delitem(
        sys.modules, "paleo_workbench.mapping.reference_layers", raising=False
    )

    mod = importlib.import_module("paleo_workbench.mapping.reference_layers")

    assert mod.gdal is None and mod.osr is None
    # Collection-visible surface still exists and errors are actionable.
    assert mod.ReferenceLayerService is not None
    source = tmp_path / "ref.tif"
    source.write_bytes(b"x")
    with pytest.raises(mod.ReferenceLayerError, match="GDAL"):
        mod.ReferenceLayerService().import_layer(source, "EPSG:4326")
