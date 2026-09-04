"""A6 + A9 — core-flow end-to-end roundtrip.

Covers the goal's main business chain at integration scale:
create project → well data → factor grid (INTERMEDIATE) → horizon
interpretation version → MapProduct (OUTPUT) → tag → save → close →
reopen → verify identity, lineage and provenance survive; and
``describe_map_product`` answers the provenance questions from real state.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from paleo_workbench.catalog import CoreCatalogAdapter, DataCatalogService, DataStage
from paleo_workbench.catalog.lifecycle import register_persisted_factor_grids
from paleo_workbench.catalog.runtime import reset_catalog, set_catalog
from paleo_workbench.project.factor_grid_artifacts import factor_grid_result_for_task
from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import (
    FactorMapTask,
    MapProductRecord,
    ProjectDocument,
    WellTable,
    WellTableRow,
)
from paleo_workbench.workflow.map_product import (
    MapProductAssembly,
    assemble_map_product,
    describe_map_product,
)
from paleo_workbench.workflow.factor_interpolation import apply_interpolation_to_task
from paleo_workbench.workflow.well_table import (
    sample_points_from_well_table,
    value_key_for_factor_type,
)
from paleo_workbench.viz.interpretation_lifecycle import (
    open_draft_from_array,
    save_draft_as_new_version,
)

pytest.importorskip("PySide6")


def _well_table() -> WellTable:
    rows = [
        WellTableRow(name="W1", x=0.0, y=0.0, z=0.32, H_s=12.0, H_t=40.0, R_s=0.3),
        WellTableRow(name="W2", x=1.0, y=0.2, z=0.41, H_s=8.0, H_t=20.0, R_s=0.4),
        WellTableRow(name="W3", x=0.4, y=1.0, z=0.25, H_s=5.0, H_t=20.0, R_s=0.25),
    ]
    return WellTable(
        id="wtable_main",
        name="H1 砂地比井表",
        target_horizon="H1",
        factor_type="sand_ratio",
        rows=rows,
        crs="EPSG:32650",
    )


def test_core_flow_roundtrip(tmp_path: Path):
    project_path = tmp_path / "demo.paleo.json"

    # --- create project: wells + factor task through the real pipeline ----
    project = ProjectDocument.new("CoreFlow")
    well_table = _well_table()
    project.well_tables.append(well_table)
    task = FactorMapTask(
        id="factor_rs",
        name="H1 砂地比",
        target_horizon="H1",
        factor_type="sand_ratio",
        method="IDW",
        source_kind="real",
        well_table_id="wtable_main",
        parameters={
            "sample_points": sample_points_from_well_table(
                well_table,
                value_key=value_key_for_factor_type("sand_ratio"),
            )
        },
    )
    project.factor_map_tasks.append(task)

    # real interpolation: live grid + grid_metadata fingerprints
    apply_interpolation_to_task(task, method="IDW", grid_n=8, power=2.0, project=project)
    assert task.status == "complete"
    assert task.grid_metadata

    ProjectManager(project_path).save(project)

    service = DataCatalogService.open(project_path)
    adapter = CoreCatalogAdapter(service)
    set_catalog(adapter)
    staged_payload = tmp_path / "payload.json"
    try:
        # --- derive: grid registers as INTERMEDIATE with a run ------------
        versions = register_persisted_factor_grids(project)
        assert len(versions) == 1
        grid_version = versions[0]
        assert grid_version.stage is DataStage.INTERMEDIATE
        assert project.factor_map_tasks[0].grid_artifact_version_id == grid_version.version_id

        # --- interpret: horizon draft → immutable version -----------------
        baseline = np.array([[0.30, 0.33, 0.40], [0.25, 0.28, 0.34]], dtype="float32")
        draft = open_draft_from_array(baseline, horizon_key="H1", name="H1 解释")
        draft.set_picks(
            np.array([0, 0]),
            np.array([0, 1]),
            np.array([0.29, 0.32], dtype="float32"),
        )
        ref, message = save_draft_as_new_version(
            draft, project, project_path, catalog=adapter
        )
        assert ref is not None, message
        assert ref.current_version_id
        # save_draft_as_new_version appends the ref to the project itself
        assert project.horizon_interpretations[-1].id == ref.id

        # --- save again: the registered grid version must survive (torn-
        #     pairing protection #918 keeps the committed version id) -------
        ProjectManager(project_path).save(project)
        assert project.factor_map_tasks[0].grid_artifact_version_id == grid_version.version_id

        # --- assemble MapProduct (OUTPUT) ----------------------------------
        staged_payload.write_text(
            json.dumps({"product": "H1 古地理成果"}, ensure_ascii=False), encoding="utf-8"
        )
        result = assemble_map_product(
            project,
            assembly=MapProductAssembly(
                product_name="H1 古地理成果图",
                factor_task_ids=["factor_rs"],
                interpretation_refs=[str(ref.id)],
                notes="roundtrip",
            ),
            catalog=service,
            payload_path=staged_payload,
        )
        record = project.map_products[-1]
        assert record.output_version_id == result.output_version_id
        assert record.run_id == result.run_id

        # --- tag the output -------------------------------------------------
        service.add_tags(["final", "paleo"], version_id=result.output_version_id)

        # --- provenance questions answered from real state -----------------
        described = describe_map_product(record, project, catalog=service)
        assert described["product_name"] == "H1 古地理成果图"
        assert described["well_count"] == 3
        assert {w["name"] for w in described["wells"]} == {"W1", "W2", "W3"}
        factor_entry = described["factor_maps"][0]
        assert factor_entry["grid_version_id"] == grid_version.version_id
        assert factor_entry["factor_type"] == "sand_ratio"
        interp_entry = described["interpretations"][0]
        assert interp_entry["kind"] == "horizon"
        assert interp_entry["current_version_id"] == ref.current_version_id
        assert described["run"]["generator"] == "map-product-v1"
        assert grid_version.version_id in described["run"]["input_version_ids"]
        assert described["output"]["version_id"] == result.output_version_id
        assert described["output"]["stage"] == DataStage.OUTPUT.value

        # --- save → close ---------------------------------------------------
        ProjectManager(project_path).save(project)
    finally:
        reset_catalog()
        service.close()

    # --- reopen: project + catalog state must match pre-close -------------
    reopened_manager = ProjectManager(project_path)
    reopened = reopened_manager.load()
    reopened_service = DataCatalogService.open(project_path)
    reopened_adapter = CoreCatalogAdapter(reopened_service)
    set_catalog(reopened_adapter)
    try:
        # map_products section roundtrips through the project file
        assert len(reopened.map_products) == 1
        reopened_record = reopened.map_products[0]
        assert reopened_record.product_name == "H1 古地理成果图"
        assert reopened_record.output_version_id == result.output_version_id
        assert reopened_record.run_id == result.run_id
        assert reopened_record.scientific_fingerprint == result.scientific_fingerprint

        # factor task grid version identity survives
        task = reopened.factor_map_tasks[0]
        assert task.grid_artifact_version_id == grid_version.version_id
        grid_after = factor_grid_result_for_task(task, crs="EPSG:32650")
        assert grid_after.shape == (8, 8)

        # horizon interpretation version survives
        assert len(reopened.horizon_interpretations) == 1
        assert reopened.horizon_interpretations[0].current_version_id == ref.current_version_id

        # catalog lineage: output → run → inputs resolves end to end
        output_version = reopened_service.get_version(result.output_version_id)
        assert output_version.stage is DataStage.OUTPUT
        run = reopened_service.get_run(result.output_version_id and result.run_id)
        assert grid_version.version_id in list(run.input_version_ids)

        # tags survive
        assert result.output_version_id in reopened_service.find_versions_by_tag("final")
        assert result.output_version_id in reopened_service.find_versions_by_tag("paleo")

        # describe gives the same answers after reopen
        described_after = describe_map_product(
            reopened_record, reopened, catalog=reopened_service
        )
        assert described_after["well_count"] == 3
        assert described_after["output"]["version_id"] == result.output_version_id
        assert (
            described_after["interpretations"][0]["current_version_id"]
            == ref.current_version_id
        )
    finally:
        reset_catalog()
        reopened_service.close()


def test_describe_reports_missing_references_honestly(tmp_path: Path):
    """Stale ids surface as missing_* entries instead of being dropped."""
    project = ProjectDocument.new("Honest")
    record = MapProductRecord(
        product_name="ghost",
        factor_task_ids=["factor_missing"],
        interpretation_refs=["interp_missing"],
        output_version_id="ver_missing",
        run_id="run_missing",
    )
    described = describe_map_product(record, project, catalog=None)
    assert described["factor_maps"] == [
        {"task_id": "factor_missing", "status": "missing_task"}
    ]
    assert described["interpretations"] == [
        {"ref_id": "interp_missing", "status": "missing_ref"}
    ]
    # catalog unavailable → run/output report unavailable with a reason
    assert described["run"] is None
    assert described["output"] is None
