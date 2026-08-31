"""Regression — opening a project with time-depth calibration entries crashed.

``ViewCoordinationController._time_depth_assets`` hands the controller paths
exactly as the project model stores them: ``ResourceItem.path`` is a plain
``str`` (deserialized straight from the project JSON) and the catalog asset
resolver also returns ``str``. The registration site formatted
``f"td-table:{path.name}"`` on that value → ``AttributeError: 'str' object
has no attribute 'name'`` (view_coordination.py:123), which escaped
``bind_project`` during ``AppShell`` construction and killed the whole
project open. The controller now normalizes to ``Path`` at the use site;
these tests pin that str-pathed projects (legacy resources AND WorkArea
entity-asset links) bind cleanly and still register real calibrations.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.project.domain import EntityAssetLink, WellEntity
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.view_coordination import ViewCoordinationController
from paleo_workbench.viz.coordinate_hub import CoordinateTransformHub
from paleo_workbench.viz.selection_context import SelectionContext

# SMI TD dat rows: TIME TVDSS TVD MD (parse_td_table reads cols 0 and 3).
TD_ROWS = "0.0 0.0 0.0 0.0\n1000.0 950.0 950.0 1000.0\n2000.0 1900.0 1900.0 2000.0\n"


@pytest.fixture()
def td_table(tmp_path):
    path = tmp_path / "W1_checkshot.dat"
    path.write_text(TD_ROWS, encoding="utf-8")
    return path


@pytest.fixture()
def controller() -> ViewCoordinationController:
    return ViewCoordinationController(SelectionContext(), CoordinateTransformHub())


def _legacy_td_project(td_path: str) -> ProjectDocument:
    doc = ProjectDocument.new("TD Project")
    doc.resources = [
        ResourceItem(
            name="W-1", path=td_path, type="time_depth", format="dat"
        )
    ]
    return doc


def test_legacy_resource_str_path_registers_calibration(controller, td_table):
    """The exact crash shape: ResourceItem.path is a str (project JSON)."""
    project = _legacy_td_project(str(td_table))

    controller.bind_project(project)  # used to AttributeError on path.name

    calibration = controller.coordinate_hub.time_depth_calibration("W-1")
    assert calibration is not None, (
        "a parseable time_depth resource must register a real calibration"
    )
    assert calibration.provenance == f"td-table:{td_table.name}"
    assert calibration.pairs == ((0.0, 0.0), (1000.0, 1000.0), (2000.0, 2000.0))


def test_entity_asset_link_str_path_registers_calibration(
    controller, td_table, monkeypatch
):
    """WorkArea EntityAssetLinks resolve through the catalog, whose resolver
    returns str paths — the same .name crash from the other entry."""
    from paleo_workbench.ui import view_coordination as vc_module

    well = WellEntity(name="W-LINK")
    doc = ProjectDocument.new("TD Project")
    doc.wells = [well]
    doc.entity_asset_links = [
        EntityAssetLink(
            entity_id=well.id, asset_id="asset-td-1", role="time_depth"
        )
    ]
    monkeypatch.setattr(
        vc_module.ViewCoordinationController,
        "_resolve_asset_path",
        staticmethod(lambda project, asset_id: str(td_table)),
    )

    controller.bind_project(doc)  # used to AttributeError on path.name

    calibration = controller.coordinate_hub.time_depth_calibration("W-LINK")
    assert calibration is not None
    assert calibration.provenance == f"td-table:{td_table.name}"


def test_path_typed_asset_still_registers(controller, td_table, monkeypatch):
    """Tolerance contract: a boundary that already hands over Path objects
    keeps working (the normalization must not regress to str-only)."""
    from paleo_workbench.ui import view_coordination as vc_module

    monkeypatch.setattr(
        vc_module.ViewCoordinationController,
        "_time_depth_assets",
        staticmethod(lambda project: (("W-1", td_table),)),
    )

    controller.bind_project(ProjectDocument.new("TD Project"))

    calibration = controller.coordinate_hub.time_depth_calibration("W-1")
    assert calibration is not None
    assert calibration.provenance == f"td-table:{td_table.name}"


def test_unparseable_str_table_is_skipped_without_crash(controller, tmp_path):
    """A str path whose table cannot parse is skipped (debug log), never
    raised — bind_project must survive it."""
    bogus = tmp_path / "bogus.dat"
    bogus.write_text("not a td table\n", encoding="utf-8")
    project = _legacy_td_project(str(bogus))

    controller.bind_project(project)

    assert controller.coordinate_hub.time_depth_calibration("W-1") is None


def test_offscreen_open_project_with_td_table_entries(tmp_path, qtbot, monkeypatch):
    """End-to-end smoke of the reported crash: GUI ``open_project_path`` on a
    SAVED project whose time-depth resource paths deserialize as str."""
    from paleo_workbench.app import PaleoWorkbenchWindow
    from paleo_workbench.project.manager import ProjectManager

    td_file = tmp_path / "W1_checkshot.dat"
    td_file.write_text(TD_ROWS, encoding="utf-8")
    project_file = tmp_path / "TD工区.paleo.json"
    assert ProjectManager(project_file).save(_legacy_td_project(str(td_file)))

    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    # A degraded catalog raises a modal; a smoke test must never block.
    monkeypatch.setattr(window, "_show_project_error", lambda title, message: None)

    assert window.open_project_path(project_file) is True

    hub = window.app_shell.view_coordination.coordinate_hub
    calibration = hub.time_depth_calibration("W-1")
    assert calibration is not None, (
        "opening a project with td-table entries must register its calibration"
    )
    assert calibration.provenance == f"td-table:{td_file.name}"
