"""Export active multi-track presentation to SVG/PDF (#221).

Stage 1 / #277 (T5): engine-backend export route for single_well, routed
through export_dispatch with ``backend="engine"`` (T1 SVG + T2 PDF
bindings). The Qt paint path remains the default.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from well_log_workstation.engine_bridge import (  # noqa: E402
    engine_available,
    reset_engine_capability_cache,
)
from well_log_workstation.export_dispatch import (  # noqa: E402
    ENGINE_PDF_NONSEARCHABLE_DISCLOSURE,
    engine_pdf_needs_disclosure,
    export_plot,
    prefer_engine_for_single_well,
)
from well_log_workstation.export_plot import (  # noqa: E402
    ExportError,
    export_presentation_pdf,
    export_presentation_svg,
)
from well_log_workstation.shell import WellLogWorkstationWindow  # noqa: E402
from well_log_workstation.workspace import create_workspace  # noqa: E402
from well_log_workstation.plot_document import load_plot_document  # noqa: E402


def _write_las(path: Path, well: str = "EXP-1") -> Path:
    path.write_text(
        f"""~VERSION INFORMATION
VERS. 2.0
WRAP. NO
~WELL INFORMATION
STRT.M 1000.0
STOP.M 1004.0
STEP.M 1.0
NULL. -999.25
WELL. {well}
~CURVE INFORMATION
DEPT.M
GR.GAPI
RT.OHMM
RHOB.G/C3
~ASCII
1000 20 2 2.2
1001 30 5 2.3
1002 40 10 2.4
1003 50 20 2.5
1004 60 50 2.6
""",
        encoding="utf-8",
    )
    return path


def test_export_svg_and_pdf_nonempty(qtbot, tmp_path: Path) -> None:
    ws = create_workspace(tmp_path / "ws", name="Export")
    las = _write_las(tmp_path / "e.las")
    win = WellLogWorkstationWindow()
    qtbot.addWidget(win)
    win.set_workspace(ws)
    well_id = win.import_las_path(las)
    win.create_single_well_plot_document(well_id, "std-gr-rt-den")
    assert win.active_presentation is not None
    assert win.active_presentation.track_count >= 2

    svg_path = tmp_path / "out" / "plot.svg"
    pdf_path = tmp_path / "out" / "plot.pdf"
    out_svg = win.export_active_plot_svg(svg_path)
    out_pdf = win.export_active_plot_pdf(pdf_path)

    assert out_svg.is_file()
    assert out_svg.stat().st_size >= 50
    text = out_svg.read_text(encoding="utf-8", errors="replace")
    assert "svg" in text.lower() or out_svg.stat().st_size > 200

    assert out_pdf.is_file()
    assert out_pdf.stat().st_size >= 50
    # PDF magic
    assert out_pdf.read_bytes()[:4] == b"%PDF"


def test_export_without_presentation_raises(qtbot, tmp_path: Path) -> None:
    win = WellLogWorkstationWindow()
    qtbot.addWidget(win)
    with pytest.raises(ExportError):
        win.export_active_plot_svg(tmp_path / "x.svg")
    with pytest.raises(ExportError):
        win.export_active_plot_pdf(tmp_path / "x.pdf")


def test_export_presentation_api_direct(qtbot, tmp_path: Path) -> None:
    ws = create_workspace(tmp_path / "ws2")
    las = _write_las(tmp_path / "d.las", well="DIR")
    win = WellLogWorkstationWindow()
    qtbot.addWidget(win)
    win.set_workspace(ws)
    well_id = win.import_las_path(las)
    pres = win.apply_template_to_well(well_id, "std-gr-rt-den")
    svg = export_presentation_svg(pres, tmp_path / "direct.svg")
    pdf = export_presentation_pdf(pres, tmp_path / "direct.pdf")
    assert svg.stat().st_size >= 50
    assert pdf.stat().st_size >= 50


# --- Stage 1 / #277 (T5): engine-backend export route ---------------------


def _engine_setup(qtbot, tmp_path: Path, monkeypatch):
    """Shared setup: a workstation with an engine surface + submitted scene.

    Returns ``(win, plot_doc, document_id)``. Skips when the engine is
    unavailable.
    """
    monkeypatch.delenv("WLWS_DISABLE_ENGINE", raising=False)
    monkeypatch.delenv("WLWS_FORCE_HOST_CANVAS", raising=False)
    reset_engine_capability_cache()
    if not engine_available():
        pytest.skip("WellLogEngine unavailable")
    ws = create_workspace(tmp_path / "eng")
    las = _write_las(tmp_path / "g.las", well="ENG-EXP")
    win = WellLogWorkstationWindow()
    qtbot.addWidget(win)
    win.set_workspace(ws)
    win.set_prefer_engine_canvas(True)
    well_id = win.import_las_path(las)
    win.create_single_well_plot_document(well_id, "std-gr-rt-den")
    pres = win.active_presentation
    assert pres is not None and pres.track_count >= 1
    win.open_engine_preview()  # submits the presentation to WellLogView
    plot_doc = load_plot_document(ws, win.active_plot_id)
    doc_id = pres.well_document_id
    return win, plot_doc, doc_id


def test_prefer_engine_for_single_well_default() -> None:
    """T11: single_well SVG/PDF prefer engine when available."""
    assert prefer_engine_for_single_well("svg", engine_available=True) == "engine"
    assert prefer_engine_for_single_well("pdf", engine_available=True) == "engine"
    assert prefer_engine_for_single_well("png", engine_available=True) == "qt"
    assert prefer_engine_for_single_well("svg", engine_available=False) == "qt"
    assert (
        prefer_engine_for_single_well(
            "pdf", engine_available=True, force_backend="qt"
        )
        == "qt"
    )
    assert engine_pdf_needs_disclosure("engine", "pdf") is True
    assert engine_pdf_needs_disclosure("engine", "svg") is False
    assert "不可搜索" in ENGINE_PDF_NONSEARCHABLE_DISCLOSURE


def test_shell_default_export_uses_engine_when_available(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    """export_active_plot_* defaults to engine for single_well (T11)."""
    win, _plot_doc, _doc_id = _engine_setup(qtbot, tmp_path, monkeypatch)
    svg = win.export_active_plot_svg(tmp_path / "def.svg")
    pdf = win.export_active_plot_pdf(tmp_path / "def.pdf")
    assert svg.is_file() and svg.stat().st_size >= 50
    assert pdf.is_file() and pdf.read_bytes()[:5] == b"%PDF-"


def test_engine_route_svg_nonempty(qtbot, tmp_path: Path, monkeypatch) -> None:
    """engine backend produces a valid SVG file via export_dispatch."""
    win, plot_doc, doc_id = _engine_setup(qtbot, tmp_path, monkeypatch)
    out = export_plot(
        plot_doc,
        "svg",
        backend="engine",
        view=win._engine_view,
        document_id=doc_id,
        path=str(tmp_path / "engine.svg"),
    )
    assert out.is_file()
    assert out.stat().st_size >= 50
    text = out.read_text(encoding="utf-8", errors="replace").lstrip()
    assert text.startswith("<?xml") or text.startswith("<svg")


def test_engine_route_pdf_nonempty(qtbot, tmp_path: Path, monkeypatch) -> None:
    """engine backend produces a valid PDF file via export_dispatch."""
    win, plot_doc, doc_id = _engine_setup(qtbot, tmp_path, monkeypatch)
    out = export_plot(
        plot_doc,
        "pdf",
        backend="engine",
        view=win._engine_view,
        document_id=doc_id,
        path=str(tmp_path / "engine.pdf"),
    )
    assert out.is_file()
    assert out.stat().st_size >= 50
    assert out.read_bytes()[:5] == b"%PDF-"


def test_engine_route_missing_view_raises(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    """engine backend without view/document_id surfaces a host ExportError."""
    monkeypatch.delenv("WLWS_DISABLE_ENGINE", raising=False)
    reset_engine_capability_cache()
    if not engine_available():
        pytest.skip("WellLogEngine unavailable")
    ws = create_workspace(tmp_path / "eng2")
    las = _write_las(tmp_path / "g2.las")
    win = WellLogWorkstationWindow()
    qtbot.addWidget(win)
    win.set_workspace(ws)
    well_id = win.import_las_path(las)
    win.create_single_well_plot_document(well_id, "std-gr-rt-den")
    plot_doc = load_plot_document(ws, win.active_plot_id)
    with pytest.raises(ExportError):
        export_plot(
            plot_doc,
            "svg",
            backend="engine",
            path=str(tmp_path / "nope.svg"),
        )


def test_engine_route_png_falls_back_to_qt(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    """PNG is not covered by the engine route; falls back to Qt paint."""
    monkeypatch.delenv("WLWS_DISABLE_ENGINE", raising=False)
    reset_engine_capability_cache()
    ws = create_workspace(tmp_path / "eng3")
    las = _write_las(tmp_path / "g3.las")
    win = WellLogWorkstationWindow()
    qtbot.addWidget(win)
    win.set_workspace(ws)
    well_id = win.import_las_path(las)
    win.create_single_well_plot_document(well_id, "std-gr-rt-den")
    plot_doc = load_plot_document(ws, win.active_plot_id)
    # backend=engine + fmt=png must not raise UnsupportedFormatError; it
    # routes through Qt paint (engine route only covers svg/pdf).
    out = export_plot(
        plot_doc,
        "png",
        backend="engine",
        paint_fn=win._paint_active_plot,
        path=str(tmp_path / "fallback.png"),
    )
    assert out.is_file() and out.stat().st_size >= 50


# --- Stage 1 / #278 (T6): engine-vs-engine parity + PDF disclosure --------


def test_engine_svg_pdf_parity_same_document(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    """Engine SVG and PDF of the same presentation agree on document identity.

    Both are routed through the host dispatch (T5) from the same prepared
    scene. The SVG carries data-document-id / data-document-revision
    metadata; the PDF is a pure-vector content stream from the same scene.
    This is the secondary parity seam (not pixel-level — no golden baseline).
    """
    win, plot_doc, doc_id = _engine_setup(qtbot, tmp_path, monkeypatch)
    svg_out = export_plot(
        plot_doc, "svg", backend="engine",
        view=win._engine_view, document_id=doc_id,
        path=str(tmp_path / "parity.svg"),
    )
    pdf_out = export_plot(
        plot_doc, "pdf", backend="engine",
        view=win._engine_view, document_id=doc_id,
        path=str(tmp_path / "parity.pdf"),
    )
    assert svg_out.is_file() and svg_out.stat().st_size >= 50
    assert pdf_out.is_file() and pdf_out.stat().st_size >= 50

    # Both come from the same prepared scene → SVG must carry the document
    # id we submitted, and the PDF must be a valid PDF from the same view.
    svg_text = svg_out.read_text(encoding="utf-8", errors="replace")
    assert f'data-document-id="{doc_id}"' in svg_text, (
        "SVG must embed the submitted document id for parity traceability"
    )
    assert pdf_out.read_bytes()[:5] == b"%PDF-"

    # The SVG physical dimensions are deterministic for a given scene; both
    # backends consume the same PreparedScene so the dimensions are fixed.
    assert 'width="' in svg_text and 'height="' in svg_text


def test_engine_pdf_disclosure_contract() -> None:
    """The engine PDF backend surfaces a non-searchable-text disclosure (T6)."""
    # engine PDF requires disclosure (ADR 0047 regression vs Qt QPdfWriter).
    assert engine_pdf_needs_disclosure("engine", "pdf") is True
    # engine SVG, Qt paint, and PNG-fallback do not.
    assert engine_pdf_needs_disclosure("engine", "svg") is False
    assert engine_pdf_needs_disclosure("qt", "pdf") is False
    assert engine_pdf_needs_disclosure("qt", "png") is False
    # The disclosure text is present and non-empty (host UI shows it).
    assert isinstance(ENGINE_PDF_NONSEARCHABLE_DISCLOSURE, str)
    assert len(ENGINE_PDF_NONSEARCHABLE_DISCLOSURE) > 0
