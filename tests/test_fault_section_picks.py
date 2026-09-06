"""L6 — seismic fault picks inside the (single) fault interpretation authority.

FaultTrace now carries the seismic side (section picks with TWT + optional
per-pick confidence) alongside the map-plane polyline, related to the map
fault through ``map_fault_id`` — one authority, two views (decision D5).
These tests pin the closed loop: draft → artifact → fingerprint → catalog
DERIVED version + run parameters → project ref → reopen.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.catalog import reset_catalog, set_catalog
from paleo_workbench.catalog.adapter import CoreCatalogAdapter
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.workflow.correlation_artifact import (
    scientific_fingerprint_fault,
    write_fault_artifact,
)
from paleo_workbench.workflow.fault_lifecycle import (
    new_fault_draft,
    save_fault_draft,
    restore_fault_draft_from_project,
)
from paleo_workbench.workflow.stratigraphy_models import (
    FaultInterpretationPayload,
    FaultSectionPick,
    FaultTrace,
)


@pytest.fixture()
def catalog_project(tmp_path: Path):
    project_file = tmp_path / "proj" / "demo.paleo.json"
    project_file.parent.mkdir(parents=True)
    project_file.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_file)
    set_catalog(CoreCatalogAdapter(service))
    try:
        yield service, ProjectDocument.new("Fault Project"), project_file
    finally:
        service.close()
        reset_catalog()


def _seismic_trace() -> FaultTrace:
    return FaultTrace(
        name="F1",
        polyline=[[100.0, 200.0], [400.0, 200.0]],
        vertical_domain="time",
        map_fault_id="fault_entity_7",
        section_picks=[
            FaultSectionPick(
                section_kind="inline",
                section_index=2300,
                offset=1450.0,
                twt_ms=1234.5,
                confidence=0.85,
            ),
            FaultSectionPick(
                section_kind="inline",
                section_index=2300,
                offset=1460.0,
                twt_ms=1260.0,
            ),
            FaultSectionPick(
                section_kind="crossline",
                section_index=1450,
                offset=2300.0,
                twt_ms=1230.0,
            ),
        ],
    )


class TestSectionPicksModel:
    def test_picks_roundtrip_through_artifact(self, tmp_path):
        payload = FaultInterpretationPayload(
            interpretation_id="fault_1", traces=[_seismic_trace()]
        )
        path = write_fault_artifact(payload, tmp_path, "fault_1_v1")
        from paleo_workbench.workflow.correlation_artifact import read_fault_artifact

        loaded, _ = read_fault_artifact(path)
        trace = loaded.traces[0]
        assert trace.map_fault_id == "fault_entity_7"
        assert trace.vertical_domain == "time"
        picks = trace.section_picks
        assert len(picks) == 3
        assert picks[0].section_kind == "inline"
        assert picks[0].section_index == 2300
        assert picks[0].twt_ms == pytest.approx(1234.5)
        assert picks[0].confidence == pytest.approx(0.85)
        assert picks[1].confidence is None  # unassessed stays None, never 0

    def test_fingerprint_covers_picks_and_map_link(self):
        base = FaultInterpretationPayload(
            interpretation_id="fault_1", traces=[_seismic_trace()]
        )
        fp_base = scientific_fingerprint_fault(base)

        changed_pick = base.model_copy(deep=True)
        changed_pick.traces[0].section_picks[0].twt_ms = 1300.0
        assert scientific_fingerprint_fault(changed_pick) != fp_base

        changed_link = base.model_copy(deep=True)
        changed_link.traces[0].map_fault_id = None
        assert scientific_fingerprint_fault(changed_link) != fp_base

        changed_confidence = base.model_copy(deep=True)
        changed_confidence.traces[0].section_picks[0].confidence = 0.4
        assert scientific_fingerprint_fault(changed_confidence) != fp_base

    def test_invalid_section_kind_refused(self):
        with pytest.raises(ValueError):
            FaultSectionPick(
                section_kind="arbitrary", section_index=1, offset=1.0, twt_ms=1.0
            )


class TestSeismicFaultLifecycle:
    def test_save_registers_version_with_pick_provenance(self, catalog_project):
        service, doc, project_path = catalog_project
        draft = new_fault_draft(traces=[_seismic_trace()], crs="EPSG:32650")

        ref, status = save_fault_draft(draft, doc, project_path)

        assert status == "ok"
        assert ref is not None and ref.current_version_id
        run = next(
            r
            for r in service.document.runs
            if r.id == _run_id_for_output(service, ref.current_version_id)
        )
        params = run.parameters
        assert params["pick_count"] == 3
        assert params["seismic_trace_count"] == 1
        assert params["map_linked_trace_count"] == 1
        assert params["vertical_domains"] == ["time"]
        assert params["crs"] == "EPSG:32650"

    def test_reopen_restores_picks_and_relation(self, catalog_project):
        service, doc, project_path = catalog_project
        draft = new_fault_draft(traces=[_seismic_trace()])
        save_fault_draft(draft, doc, project_path)

        reopened = restore_fault_draft_from_project(doc, project_path)

        assert reopened is not None
        trace = reopened.payload.traces[0]
        assert trace.map_fault_id == "fault_entity_7"
        assert [p.twt_ms for p in trace.section_picks] == pytest.approx(
            [1234.5, 1260.0, 1230.0]
        )
        assert reopened.dirty is False

    def test_noop_when_only_display_changes(self, catalog_project):
        service, doc, project_path = catalog_project
        draft = new_fault_draft(traces=[_seismic_trace()])
        save_fault_draft(draft, doc, project_path)

        draft.display = {"color": "#ff0000", "width": 2.5}  # display-only
        ref, status = save_fault_draft(draft, doc, project_path)

        assert status == "noop_unchanged"

    def test_new_version_when_pick_changes(self, catalog_project):
        service, doc, project_path = catalog_project
        draft = new_fault_draft(traces=[_seismic_trace()])
        _, _ = save_fault_draft(draft, doc, project_path)
        first_version = doc.fault_interpretations[0].current_version_id

        draft.payload.traces[0].section_picks.append(
            FaultSectionPick(
                section_kind="inline", section_index=2300, offset=1470.0, twt_ms=1290.0
            )
        )
        draft.dirty = True
        ref, status = save_fault_draft(draft, doc, project_path)

        assert status == "ok"
        assert ref.current_version_id != first_version
        assert ref.parent_version_id == first_version  # immutable chain

    def test_map_plane_trace_still_saves_unchanged(self, catalog_project):
        """Pre-existing map-only faults keep working (no picks required)."""
        service, doc, project_path = catalog_project
        trace = FaultTrace(name="map-only", polyline=[[0.0, 0.0], [1.0, 1.0]])
        draft = new_fault_draft(traces=[trace])

        ref, status = save_fault_draft(draft, doc, project_path)

        assert status == "ok"
        run = next(
            r
            for r in service.document.runs
            if r.id == _run_id_for_output(service, ref.current_version_id)
        )
        assert run.parameters["pick_count"] == 0
        assert run.parameters["vertical_domains"] == []


def _run_id_for_output(service: DataCatalogService, version_id: str) -> str:
    for run in service.document.runs:
        if version_id in (run.output_version_ids or ()):
            return run.id
    raise AssertionError(f"no run outputs version {version_id}")
