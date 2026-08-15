"""T-VIZ-03: per-tab view export capabilities and engine routing."""

from __future__ import annotations

from pathlib import Path

from paleo_workbench.resources.export_service import (
    export_widget_snapshot,
    list_view_export_labels,
    view_export_capabilities,
)


class _WellLike:
    def __init__(self, tracks=None):
        self.tracks = tracks or ["track"]

    def paint_all(self, painter):  # pragma: no cover - duck type
        pass


class _EmptyCanvas:
    def __init__(self):
        self.tracks = []

    def paint_all(self, painter):  # pragma: no cover - duck type
        pass


class _EngineWellHost:
    """Well-log host whose view_stack shows the engine surface (legacy empty)."""

    def __init__(self):
        self.widget = _EmptyCanvas()
        self.canvas = self.widget
        self.engine_host = object()
        self.view_stack = _Stack(self.engine_host)
        self.widget.export_capabilities = self.export_capabilities

    def export_capabilities(self):
        if self.view_stack.currentWidget() is self.engine_host:
            return frozenset({"PNG"})
        if self.canvas.tracks:
            return frozenset({"PNG", "SVG", "PDF"})
        return frozenset()


class _Stack:
    def __init__(self, current):
        self._current = current

    def currentWidget(self):
        return self._current


class _CrossInner:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def export_composite(self, path: str, fmt: str = "svg"):
        self.calls.append((path, fmt))
        Path(path).write_text(f"cross-{fmt}", encoding="utf-8")


class _CrossShell:
    def __init__(self):
        self.widget = _CrossInner()


class _PaleoLike:
    def __init__(self):
        self._period_name = "ZJ2"
        self._layers = []

    def load_features(self, *args, **kwargs):  # pragma: no cover
        pass


class _GrabOnly:
    def grab(self):
        raise RuntimeError("grab not used in capability checks")


def test_list_view_export_labels_catalog():
    labels = list_view_export_labels()
    assert labels == ["PNG", "SVG", "PDF"]


def test_capabilities_well_log_full_vector():
    assert view_export_capabilities(_WellLike()) == frozenset({"PNG", "SVG", "PDF"})


def test_capabilities_empty_well_log_canvas_claims_nothing():
    """#381: an empty well-log canvas must not claim vector export."""
    assert view_export_capabilities(_EmptyCanvas()) == frozenset()


def test_capabilities_engine_well_log_surface_png_only():
    """#381: engine surface owns the view -> PNG grab only, never blank vector."""
    host = _EngineWellHost()
    assert view_export_capabilities(host.widget) == frozenset({"PNG"})


def test_export_snapshot_rejects_blank_well_log_svg(tmp_path):
    """#381: exporting SVG from an empty well-log surface must fail, not succeed."""
    host = _EngineWellHost()
    out = tmp_path / "blank.svg"
    result = export_widget_snapshot(host.widget, out, "SVG", register=False)
    assert result.success is False
    assert "不支持" in result.message or "无可导出" in result.message
    assert not out.exists()

    result_png = export_widget_snapshot(_EmptyCanvas(), tmp_path / "blank.png", "PNG", register=False)
    assert result_png.success is False


def test_real_well_log_host_capabilities_follow_backend(qtbot):
    """#381: WellLogHost capabilities must follow the active backend."""
    from paleo_workbench.viz.hosts.well_log_host import WellLogHost

    host = WellLogHost()
    qtbot.addWidget(host.widget)
    # Nothing loaded, legacy surface active: nothing honest to export.
    assert view_export_capabilities(host.widget) == frozenset()
    # Engine surface owns the view (legacy canvas empty): PNG grab only.
    host.view_stack.setCurrentWidget(host.engine_host)
    assert view_export_capabilities(host.widget) == frozenset({"PNG"})
    # Back to a loaded legacy canvas: full vector set restored.
    host.view_stack.setCurrentWidget(host.scroll_area)
    host.canvas.tracks.append(object())
    assert view_export_capabilities(host.widget) == frozenset({"PNG", "SVG", "PDF"})


def test_capabilities_cross_well_unwraps_shell():
    shell = _CrossShell()
    assert view_export_capabilities(shell) == frozenset({"PNG", "SVG", "PDF"})
    assert view_export_capabilities(shell.widget) == frozenset({"PNG", "SVG", "PDF"})


def test_capabilities_paleo_map_duck_type():
    assert view_export_capabilities(_PaleoLike()) == frozenset({"PNG", "SVG", "PDF"})


def test_capabilities_generic_grab_png_only():
    assert view_export_capabilities(_GrabOnly()) == frozenset({"PNG"})


def test_export_snapshot_rejects_unsupported_format(tmp_path):
    result = export_widget_snapshot(_GrabOnly(), tmp_path / "x.svg", "SVG", register=False)
    assert result.success is False
    assert "不支持" in result.message


def test_export_snapshot_routes_cross_well_svg(tmp_path):
    shell = _CrossShell()
    out = tmp_path / "section.svg"
    result = export_widget_snapshot(shell, out, "SVG", register=False)
    assert result.success is True
    assert out.read_text(encoding="utf-8") == "cross-svg"
    assert shell.widget.calls == [(str(out), "svg")]


def test_export_snapshot_routes_cross_well_pdf(tmp_path):
    shell = _CrossShell()
    out = tmp_path / "section.pdf"
    result = export_widget_snapshot(shell, out, "PDF", register=False)
    assert result.success is True
    assert shell.widget.calls == [(str(out), "pdf")]


def test_visualization_page_gates_buttons_by_tab(qtbot):
    from paleo_workbench.ui.pages.visualization_page import VisualizationPage
    from paleo_workbench.viz.hosts import PaleoMapHost, SeismicHost, WellLogHost

    page = VisualizationPage()
    qtbot.addWidget(page)
    tabs = page.composite_panel.tabs

    well_idx = next(
        i for i in range(tabs.count()) if tabs.tabText(i) == WellLogHost.tab_title
    )
    seismic_idx = next(
        i for i in range(tabs.count()) if tabs.tabText(i) == SeismicHost.tab_title
    )
    map_idx = next(
        i for i in range(tabs.count()) if tabs.tabText(i) == PaleoMapHost.tab_title
    )

    tabs.setCurrentIndex(well_idx)
    # A freshly built well-log host has no tracks yet; #381 requires the
    # empty surface to disable vector export. Simulate a loaded legacy
    # canvas, then the full vector set must be offered again.
    page.composite_panel.well_host.canvas.tracks.append(object())
    page._sync_export_capabilities()
    assert page.trace_panel.export_svg_btn.isEnabled() is True
    assert page.trace_panel.export_pdf_btn.isEnabled() is True

    tabs.setCurrentIndex(seismic_idx)
    page._sync_export_capabilities()
    assert page.trace_panel.export_svg_btn.isEnabled() is False
    assert page.trace_panel.export_pdf_btn.isEnabled() is False
    assert page.trace_panel.export_btn.isEnabled() is True

    tabs.setCurrentIndex(map_idx)
    page._sync_export_capabilities()
    assert page.trace_panel.export_svg_btn.isEnabled() is True
    assert page.trace_panel.export_pdf_btn.isEnabled() is True
