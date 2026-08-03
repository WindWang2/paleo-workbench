"""Correlation horizon links (#229)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from well_log_workstation.correlation_links import (  # noqa: E402
    HorizonLink,
    match_tops_by_name,
    links_to_engine_overlays,
)
from well_log_workstation.plot_document import (  # noqa: E402
    load_plot_document,
    save_plot_document,
)
from well_log_workstation.shell import WellLogWorkstationWindow  # noqa: E402
from well_log_workstation.tops_model import FormationTop, save_tops_for_well  # noqa: E402
from well_log_workstation.workspace import create_workspace  # noqa: E402


def _write_las(path: Path, well: str) -> Path:
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
~ASCII
1000 10 1
1001 20 2
1002 30 3
1003 40 4
1004 50 5
""",
        encoding="utf-8",
    )
    return path


def test_match_tops_by_name_adjacent() -> None:
    tops = {
        "w1": [
            FormationTop(name="T1", depth=1001.0, id="00000000-0000-0000-0000-000000000001"),
            FormationTop(name="T2", depth=1003.0, id="00000000-0000-0000-0000-000000000002"),
        ],
        "w2": [
            FormationTop(name="T1", depth=1001.5, id="00000000-0000-0000-0000-000000000003"),
            FormationTop(name="T3", depth=1002.0, id="00000000-0000-0000-0000-000000000004"),
        ],
        "w3": [
            FormationTop(name="T1", depth=1001.2, id="00000000-0000-0000-0000-000000000005"),
        ],
    }
    links = match_tops_by_name(["w1", "w2", "w3"], tops)
    # T1 on w1-w2 and w2-w3; T2 only on w1; T3 only on w2
    names = sorted(lk.name for lk in links)
    assert names.count("T1") == 2
    assert "T2" not in names
    assert links[0].left_well_id in ("w1", "w2")


def test_links_to_engine_overlays() -> None:
    links = [
        HorizonLink(
            id="00000000-0000-0000-0000-0000000000aa",
            left_well_id="w1",
            right_well_id="w2",
            name="T1",
            left_depth=1001.0,
            right_depth=1001.5,
            left_marker_id="00000000-0000-0000-0000-000000000001",
            right_marker_id="00000000-0000-0000-0000-000000000002",
        )
    ]
    ov = links_to_engine_overlays(
        links, well_document_ids={"w1": "00000000-0000-0000-0000-0000000000d1",
                                  "w2": "00000000-0000-0000-0000-0000000000d2"}
    )
    assert len(ov) == 1
    assert ov[0]["kind"] == "horizon_line"
    assert "left_marker_id" in ov[0]


def test_shell_auto_links_persist(qtbot, tmp_path: Path) -> None:
    ws = create_workspace(tmp_path / "lnk")
    win = WellLogWorkstationWindow()
    qtbot.addWidget(win)
    win.set_workspace(ws)
    id1 = win.import_las_path(_write_las(tmp_path / "a.las", "A"))
    id2 = win.import_las_path(_write_las(tmp_path / "b.las", "B"))
    # Shared top names
    save_tops_for_well(
        ws,
        id1,
        [
            FormationTop(
                name="HorizonA",
                depth=1001.0,
                id="00000000-0000-0000-0000-0000000000a1",
            )
        ],
    )
    save_tops_for_well(
        ws,
        id2,
        [
            FormationTop(
                name="HorizonA",
                depth=1002.0,
                id="00000000-0000-0000-0000-0000000000a2",
            )
        ],
    )
    plot = win.create_correlation_plot_document([id1, id2], "std-gr-rt-den")
    # Auto-match on show (or explicit)
    links = win.auto_link_correlation_tops()
    assert len(links) >= 1
    assert any(lk.name == "HorizonA" for lk in links)
    assert len(win.correlation_canvas.links()) >= 1

    again = load_plot_document(ws, plot.id)
    assert len(again.links) >= 1
    assert again.links[0].name == "HorizonA"


def test_clear_and_remove_links(qtbot, tmp_path: Path) -> None:
    ws = create_workspace(tmp_path / "clr")
    win = WellLogWorkstationWindow()
    qtbot.addWidget(win)
    win.set_workspace(ws)
    id1 = win.import_las_path(_write_las(tmp_path / "a.las", "A"))
    id2 = win.import_las_path(_write_las(tmp_path / "b.las", "B"))
    save_tops_for_well(
        ws,
        id1,
        [
            FormationTop(
                name="H1",
                depth=1001.0,
                id="00000000-0000-0000-0000-0000000000c1",
            ),
            FormationTop(
                name="H2",
                depth=1003.0,
                id="00000000-0000-0000-0000-0000000000c2",
            ),
        ],
    )
    save_tops_for_well(
        ws,
        id2,
        [
            FormationTop(
                name="H1",
                depth=1001.5,
                id="00000000-0000-0000-0000-0000000000c3",
            ),
            FormationTop(
                name="H2",
                depth=1003.5,
                id="00000000-0000-0000-0000-0000000000c4",
            ),
        ],
    )
    plot = win.create_correlation_plot_document([id1, id2], "std-gr-rt-den")
    links = win.auto_link_correlation_tops()
    assert len(links) >= 2
    assert win.links_list.count() >= 2

    # Remove one
    victim = links[0].id
    assert win.remove_correlation_link(victim) is True
    assert all(lk.id != victim for lk in win.correlation_canvas.links())
    reloaded = load_plot_document(ws, plot.id)
    assert all(lk.id != victim for lk in reloaded.links)

    win.clear_correlation_links()
    assert win.correlation_canvas.links() == []
    assert "无连线" in win.links_list.item(0).text()
    empty = load_plot_document(ws, plot.id)
    assert empty.links == []


def test_payload_includes_overlays(qtbot, tmp_path: Path) -> None:
    from well_log_workstation.engine_bridge import presentations_to_multi_well_payload

    ws = create_workspace(tmp_path / "ov")
    win = WellLogWorkstationWindow()
    qtbot.addWidget(win)
    win.set_workspace(ws)
    id1 = win.import_las_path(_write_las(tmp_path / "a.las", "A"))
    id2 = win.import_las_path(_write_las(tmp_path / "b.las", "B"))
    save_tops_for_well(
        ws,
        id1,
        [FormationTop(name="T", depth=1001.0, id="00000000-0000-0000-0000-0000000000b1")],
    )
    save_tops_for_well(
        ws,
        id2,
        [FormationTop(name="T", depth=1002.0, id="00000000-0000-0000-0000-0000000000b2")],
    )
    win.create_correlation_plot_document([id1, id2], "std-gr-rt-den")
    win.auto_link_correlation_tops()
    payload = presentations_to_multi_well_payload(
        win.correlation_canvas.columns(),
        tops_per_well=win.correlation_canvas.tops_per_column(),
        links=win.correlation_canvas.links(),
    )
    assert "overlays" in payload
    assert payload["overlays"][0]["kind"] == "horizon_line"
