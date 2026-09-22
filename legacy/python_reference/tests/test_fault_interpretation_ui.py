"""P1-B — fault interpretation UI closure: map break lines → versioned fault.

The map plane's break/fault polylines are the scientific authority; lifting
them through draft_from_constraint_layers + save_fault_draft must mint an
immutable version with lineage and a project reference, without touching
the source map document.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument
from paleo_workbench.workflow.constraints import constraints_from_map_document
from paleo_workbench.workflow.fault_lifecycle import (
    draft_from_constraint_layers,
    open_fault_draft_from_version,
    save_fault_draft,
)


def _map_with_break_lines() -> PaleoMapDocument:
    return PaleoMapDocument(
        id="map-1",
        name="测试图件",
        linked_target_horizon="H1",
        line_features=[
            {
                "id": "lf1",
                "feature_type": "line",
                "role": "break",
                "name": "F1 断层",
                "geometry": {"type": "LineString", "coordinates": [[0.0, 0.0], [10.0, 5.0], [20.0, 8.0]]},
            },
            {
                "id": "lf2",
                "feature_type": "line",
                "role": "direction",
                "name": "物源方向",
                "geometry": {"type": "LineString", "coordinates": [[1.0, 1.0], [2.0, 2.0]]},
            },
        ],
    )


def test_lift_only_break_lines():
    layers = constraints_from_map_document(_map_with_break_lines())
    draft = draft_from_constraint_layers(layers, crs="EPSG:32650")
    # direction lines are factor constraints, NOT faults
    assert len(draft.payload.traces) == 1
    assert draft.payload.traces[0].name == "F1 断层"
    assert draft.payload.crs == "EPSG:32650"


def test_save_and_reopen_roundtrip(tmp_path: Path):
    from paleo_workbench.project.models import ProjectMeta

    project = ProjectDocument(id="p1", name="测试工程", meta=ProjectMeta(name="测试工程"))
    project_path = tmp_path / "demo.paleo.json"
    project_path.write_text("{}", encoding="utf-8")

    layers = constraints_from_map_document(_map_with_break_lines())
    draft = draft_from_constraint_layers(layers, crs="EPSG:32650")
    ref, message = save_fault_draft(draft, project, project_path)
    assert ref is not None, message
    assert message == "ok"
    assert ref.current_version_id
    assert project.fault_interpretations, "project must hold the reference"

    # Identical content is a no-op, not a duplicate immutable version.
    ref2, message2 = save_fault_draft(draft, project, project_path)
    assert message2 == "noop_unchanged"
    assert ref2 is ref

    # Reopen from the stored artifact reproduces the traces.
    artifact_path = Path(ref.artifact_path)
    if not artifact_path.is_file():
        artifact_path = project_path.parent / ref.artifact_path
    reopened = open_fault_draft_from_version(artifact_path)
    assert reopened.payload.traces[0].name == "F1 断层"
    assert reopened.dirty is False


def test_lift_without_break_lines_is_empty():
    doc = PaleoMapDocument(id="map-2", name="无断层图", linked_target_horizon="H1", line_features=[])
    layers = constraints_from_map_document(doc)
    draft = draft_from_constraint_layers(layers)
    assert draft.payload.traces == []
