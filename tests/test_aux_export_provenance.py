"""Regression tests for review finding #5 — auxiliary export writers must
register catalog provenance.

Each UI page's best-effort ``_register_*_export`` helper must produce an
OUTPUT DataVersion (with lineage when sources are known) when a catalog is
active, and must no-op harmlessly when none is (no project open). This pins
the "no untracked export" contract without instantiating full widgets.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog import (
    CoreCatalogAdapter,
    DataCatalogService,
    DataStage,
    reset_catalog,
    set_catalog,
)
from paleo_workbench.project.models import ProjectDocument


def _make_project_path(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


@pytest.fixture()
def project(tmp_path: Path) -> ProjectDocument:
    return ProjectDocument.new("demo")


@pytest.fixture()
def catalog(tmp_path: Path):
    service = DataCatalogService.open(_make_project_path(tmp_path))
    adapter = CoreCatalogAdapter(service)
    set_catalog(adapter)
    yield adapter
    # Reset the runtime BEFORE closing: a leaked adapter over a closed service
    # would poison get_catalog() for test modules that run after this one.
    reset_catalog()
    service.close()


def _write_export(tmp_path: Path, name: str) -> Path:
    out = tmp_path / "exports" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"exported")
    return out


# ------------------------------------------------------------------ stratigraphy


def test_stratigraphy_register_export_registers_output(qtbot, catalog, project, tmp_path):
    from paleo_workbench.ui.pages.stratigraphy_correlation_page import (
        StratigraphyCorrelationPage,
    )

    page = StratigraphyCorrelationPage()
    page.set_project(project)
    page._loaded_resource_ids = []

    out = _write_export(tmp_path, "well_tops.csv")
    page._register_export(str(out), fmt="csv", label="分层顶 CSV")

    versions = [v for v in catalog.list_versions() if v.stage == DataStage.OUTPUT]
    assert len(versions) == 1
    # The OUTPUT version is managed: its payload is a copy inside outputs/,
    # not the original export file (which stays untouched).
    assert versions[0].format == "csv"
    assert out.read_bytes() == b"exported"
    service = catalog._service if hasattr(catalog, "_service") else None
    payload_path = Path(versions[0].path)
    assert payload_path.is_file()
    assert payload_path.read_bytes() == b"exported"


def test_stratigraphy_register_export_links_source_resources(qtbot, catalog, project, tmp_path):
    from paleo_workbench.ui.pages.stratigraphy_correlation_page import (
        StratigraphyCorrelationPage,
    )

    src = tmp_path / "incoming" / "w1.las"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"LAS")
    raw = catalog.register_input(
        name="w1.las",
        path=str(src),
        checksum=None,
        kind="well_log",
        format="las",
        legacy_resource_id="res_w1",
    )

    page = StratigraphyCorrelationPage()
    page.set_project(project)
    page._loaded_resource_ids = ["res_w1"]

    out = _write_export(tmp_path, "section.png")
    page._register_export(str(out), fmt="png", label="连井剖面")

    run = next(r for r in catalog.list_runs() if r.operation == "export")
    assert raw.version_id in run.input_version_ids


def test_stratigraphy_register_export_no_catalog_noop(qtbot, project, tmp_path):
    """No catalog backend active (no project open) → registration no-ops."""
    from paleo_workbench.ui.pages.stratigraphy_correlation_page import (
        StratigraphyCorrelationPage,
    )

    page = StratigraphyCorrelationPage()
    page.set_project(project)
    out = _write_export(tmp_path, "x.csv")
    # No catalog set → helper returns without raising.
    page._register_export(str(out), fmt="csv", label="x")


# ------------------------------------------------------------------ joint snapshot


def test_joint_snapshot_register_registers_output(qtbot, catalog, project, tmp_path):
    from paleo_workbench.ui.pages.well_seismic_joint_page import WellSeismicJointPage

    page = WellSeismicJointPage(project=project)
    out = _write_export(tmp_path, "joint.png")
    page._register_snapshot_export(str(out))

    versions = [v for v in catalog.list_versions() if v.stage == DataStage.OUTPUT]
    assert len(versions) == 1
    assert versions[0].format == "png"


def test_joint_snapshot_register_no_catalog_noop(qtbot, project, tmp_path):
    from paleo_workbench.ui.pages.well_seismic_joint_page import WellSeismicJointPage

    page = WellSeismicJointPage(project=project)
    out = _write_export(tmp_path, "joint.png")
    page._register_snapshot_export(str(out))  # no-op, no catalog


# ------------------------------------------------------------------ 3D mesh export


def test_3d_mesh_register_registers_output(qtbot, catalog, project, tmp_path):
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )

    page = GeologicalModeling3DPage()
    page.set_project(project)
    page.combo_export_type.setCurrentIndex(0)  # FLAC3D
    out = _write_export(tmp_path, "model.f3grid")
    page._register_mesh_export(str(out))

    versions = [v for v in catalog.list_versions() if v.stage == DataStage.OUTPUT]
    assert len(versions) == 1
    assert versions[0].format == "f3grid"


def test_3d_mesh_register_abaqus_format(qtbot, catalog, project, tmp_path):
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )

    page = GeologicalModeling3DPage()
    page.set_project(project)
    page.combo_export_type.setCurrentIndex(1)  # Abaqus
    out = _write_export(tmp_path, "model.inp")
    page._register_mesh_export(str(out))

    versions = [v for v in catalog.list_versions() if v.stage == DataStage.OUTPUT]
    assert len(versions) == 1
    assert versions[0].format == "inp"
