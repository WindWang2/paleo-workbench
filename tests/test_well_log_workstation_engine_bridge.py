"""Optional WellLogEngine bridge (#224 / #225)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from well_log_workstation.engine_bridge import (  # noqa: E402
    EngineUnavailable,
    create_well_log_view,
    engine_available,
    presentation_to_multi_track_payload,
    presentations_to_multi_well_payload,
    primary_curve_from_presentation,
    probe_engine,
    reset_engine_capability_cache,
)
from well_log_workstation.shell import WellLogWorkstationWindow  # noqa: E402
from well_log_workstation.tops_model import FormationTop  # noqa: E402
from well_log_workstation.workspace import create_workspace  # noqa: E402


def _write_las(path: Path, well: str = "ENG-1") -> Path:
    path.write_text(
        f"""~VERSION INFORMATION
VERS. 2.0
WRAP. NO
~WELL INFORMATION
STRT.M 1000.0
STOP.M 1003.0
STEP.M 1.0
NULL. -999.25
WELL. {well}
~CURVE INFORMATION
DEPT.M
GR.GAPI
RT.OHMM
~ASCII
1000 10 1
1001 20 2
1002 30 3
1003 40 4
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture(autouse=True)
def _reset_probe() -> None:
    reset_engine_capability_cache()
    yield
    reset_engine_capability_cache()


def test_probe_respects_disable_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WLWS_DISABLE_ENGINE", "1")
    reset_engine_capability_cache()
    cap = probe_engine()
    assert cap.available is False
    assert "WLWS_DISABLE_ENGINE" in cap.detail
    assert engine_available() is False


def test_create_view_raises_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WLWS_DISABLE_ENGINE", "1")
    reset_engine_capability_cache()
    with pytest.raises(EngineUnavailable):
        create_well_log_view()


def test_shell_default_is_host_multitrack(qtbot, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WLWS_DISABLE_ENGINE", "1")
    reset_engine_capability_cache()
    ws = create_workspace(tmp_path / "ws")
    las = _write_las(tmp_path / "e.las")
    win = WellLogWorkstationWindow()
    qtbot.addWidget(win)
    win.set_workspace(ws)
    well_id = win.import_las_path(las)
    win.apply_template_to_well(well_id, "std-gr-rt-den")
    assert win.multi_track_canvas.track_count() >= 2
    with pytest.raises(EngineUnavailable):
        win.open_engine_preview()
    assert win.active_presentation is not None


def test_primary_curve_from_presentation(qtbot, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WLWS_DISABLE_ENGINE", "1")
    reset_engine_capability_cache()
    ws = create_workspace(tmp_path / "ws2")
    las = _write_las(tmp_path / "p.las")
    win = WellLogWorkstationWindow()
    qtbot.addWidget(win)
    win.set_workspace(ws)
    well_id = win.import_las_path(las)
    pres = win.apply_template_to_well(well_id, "std-gr-rt-den")
    primary = primary_curve_from_presentation(pres)
    assert primary is not None
    depth, values, mnemonic, unit = primary
    assert depth.size == values.size
    assert depth.size >= 2
    assert mnemonic


def test_multi_track_payload_from_presentation(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("WLWS_DISABLE_ENGINE", "1")
    reset_engine_capability_cache()
    ws = create_workspace(tmp_path / "payload")
    las = _write_las(tmp_path / "p2.las")
    win = WellLogWorkstationWindow()
    qtbot.addWidget(win)
    win.set_workspace(ws)
    well_id = win.import_las_path(las)
    pres = win.apply_template_to_well(well_id, "std-gr-rt-den")
    tops = [
        FormationTop(
            name="T1",
            depth=1001.0,
            id="00000000-0000-0000-0000-000000000001",
        )
    ]
    payload = presentation_to_multi_track_payload(pres, tops=tops)
    assert "document_id" in payload
    assert len(payload["curves"]) >= 1
    assert len(payload["tracks"]) >= 1
    assert payload["tracks"][0]["layers"]
    assert payload["markers"][0]["label"] == "T1"
    n = payload["depth"].size
    for c in payload["curves"]:
        assert c["values"].size == n


def test_multi_well_payload_two_wells(qtbot, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WLWS_DISABLE_ENGINE", "1")
    reset_engine_capability_cache()
    ws = create_workspace(tmp_path / "mw")
    win = WellLogWorkstationWindow()
    qtbot.addWidget(win)
    win.set_workspace(ws)
    id1 = win.import_las_path(_write_las(tmp_path / "a.las", "A"))
    id2 = win.import_las_path(_write_las(tmp_path / "b.las", "B"))
    p1 = win.apply_template_to_well(id1, "std-gr-rt-den")
    p2 = win.apply_template_to_well(id2, "std-gr-rt-den")
    payload = presentations_to_multi_well_payload(
        [p1, p2], shared_depth=(1000.0, 1003.0)
    )
    assert len(payload["wells"]) == 2
    assert payload["shared_top"] == 1000.0
    assert payload["shared_bottom"] == 1003.0
    assert all("depth" in w and "values" in w for w in payload["wells"])


def test_submit_multi_track_when_engine_present(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("WLWS_DISABLE_ENGINE", raising=False)
    reset_engine_capability_cache()
    if not engine_available():
        pytest.skip(probe_engine().detail)
    ws = create_workspace(tmp_path / "eng")
    las = _write_las(tmp_path / "g.las")
    win = WellLogWorkstationWindow()
    qtbot.addWidget(win)
    win.set_workspace(ws)
    well_id = win.import_las_path(las)
    win.apply_template_to_well(well_id, "std-gr-rt-den")
    report = win.open_engine_preview()
    assert isinstance(report, dict)
    assert report.get("render_prepared") is True or "depth" in report
    if "track_count" in report:
        assert int(report["track_count"]) >= 1


def test_submit_multi_well_when_engine_present(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("WLWS_DISABLE_ENGINE", raising=False)
    reset_engine_capability_cache()
    if not engine_available():
        pytest.skip(probe_engine().detail)
    view = create_well_log_view()
    if not hasattr(view, "submit_multi_well_section"):
        pytest.skip("submit_multi_well_section not in this welllog build")
    ws = create_workspace(tmp_path / "eng2")
    win = WellLogWorkstationWindow()
    qtbot.addWidget(win)
    win.set_workspace(ws)
    id1 = win.import_las_path(_write_las(tmp_path / "w1.las", "W1"))
    id2 = win.import_las_path(_write_las(tmp_path / "w2.las", "W2"))
    win.create_correlation_plot_document([id1, id2], "std-gr-rt-den")
    report = win.open_engine_correlation_preview()
    assert report.get("render_prepared") is True
    assert int(report.get("well_count", 0)) == 2
