"""Tests for CrossWellExportDialog and the rewired page export flow."""
from __future__ import annotations

from pathlib import Path

from paleo_workbench.ui.pages.cross_well_export_dialog import CrossWellExportDialog
from paleo_workbench.ui.pages.stratigraphy_correlation_page import StratigraphyCorrelationPage


def test_dialog_defaults(qtbot):
    dlg = CrossWellExportDialog()
    qtbot.addWidget(dlg)
    opts = dlg.options()
    assert opts == {"fmt": "svg", "dpi": 150, "width_px": None, "page_size": None}


def test_dialog_png_enables_dpi(qtbot):
    dlg = CrossWellExportDialog()
    qtbot.addWidget(dlg)
    idx = dlg.format_combo.findData("png")
    dlg.format_combo.setCurrentIndex(idx)
    assert dlg.dpi_combo.isEnabled()
    assert dlg.page_size_combo.isEnabled() is False
    idx_pdf = dlg.format_combo.findData("pdf")
    dlg.format_combo.setCurrentIndex(idx_pdf)
    assert dlg.dpi_combo.isEnabled()
    assert dlg.page_size_combo.isEnabled()
    idx_svg = dlg.format_combo.findData("svg")
    dlg.format_combo.setCurrentIndex(idx_svg)
    assert dlg.dpi_combo.isEnabled() is False
    assert dlg.page_size_combo.isEnabled() is False


def test_dialog_options_roundtrip(qtbot):
    dlg = CrossWellExportDialog()
    qtbot.addWidget(dlg)
    dlg.format_combo.setCurrentIndex(dlg.format_combo.findData("png"))
    dlg.dpi_combo.setCurrentIndex(dlg.dpi_combo.findData(300))
    dlg.width_spin.setValue(2000)
    assert dlg.options() == {"fmt": "png", "dpi": 300, "width_px": 2000, "page_size": None}


def test_dialog_pdf_page_size(qtbot):
    dlg = CrossWellExportDialog()
    qtbot.addWidget(dlg)
    dlg.format_combo.setCurrentIndex(dlg.format_combo.findData("pdf"))
    dlg.page_size_combo.setCurrentIndex(dlg.page_size_combo.findData("A4"))
    opts = dlg.options()
    assert opts["fmt"] == "pdf"
    assert opts["page_size"] == "A4"
    # Selecting a paper size makes explicit width meaningless
    assert opts["width_px"] is None


def test_page_export_flow(qtbot, monkeypatch, tmp_path):
    """_export_section: dialog options -> engine export_composite kwargs."""
    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)

    calls = []

    class _StubInner:
        _canvases = [object()]

        def export_composite(self, path, fmt="svg", **kwargs):
            calls.append((path, fmt, kwargs))

    page.cross_host.inner = _StubInner()

    class _StubDialog:
        def __init__(self, parent=None):
            pass

        def exec(self):
            return 1

        def options(self):
            return {"fmt": "png", "dpi": 300, "width_px": 2000, "page_size": None}

    import paleo_workbench.ui.pages.stratigraphy_correlation_page as mod

    monkeypatch.setattr(mod, "CrossWellExportDialog", _StubDialog)
    monkeypatch.setattr(
        mod.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(tmp_path / "out.png"), "PNG (*.png)")),
    )
    monkeypatch.setattr(mod.QMessageBox, "information", staticmethod(lambda *a, **k: None))

    page._export_section()
    assert len(calls) == 1
    path, fmt, kwargs = calls[0]
    assert path.endswith("out.png")
    assert fmt == "png"
    assert kwargs == {"dpi": 300, "width_px": 2000, "page_size": None}


def test_page_export_button_text(qtbot):
    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    assert "SVG" not in page.export_btn.text()
