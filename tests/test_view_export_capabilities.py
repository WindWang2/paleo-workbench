"""T-VIZ-03: per-tab view export capabilities and engine routing."""

from __future__ import annotations

from pathlib import Path

from paleo_workbench.resources.export_service import (
    export_widget_snapshot,
    list_view_export_labels,
    view_export_capabilities,
)


class _WellLike:
    def paint_all(self, painter):  # pragma: no cover - duck type
        pass


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
