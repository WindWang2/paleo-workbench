### Task 10: QC And Export Artifact Records

**Files:**
- Create: `paleo_workbench/workflow/qc.py`
- Create: `paleo_workbench/workflow/export.py`
- Modify: `tests/test_workflow_service.py`

**Interfaces:**
- Consumes: `ProjectDocument`, `PaleoMapDocument`, `QualityReport`, `ExportArtifact`
- Produces: `run_basic_qc(project, map_document_id) -> QualityReport`
- Produces: `record_export(project, linked_id, output_path, fmt, source_task_ids) -> ExportArtifact`

- [ ] **Step 1: Write failing QC/export tests**

Append to `tests/test_workflow_service.py`:

```python
from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.workflow.export import record_export
from paleo_workbench.workflow.qc import run_basic_qc


def test_qc_warns_when_map_has_no_polygons():
    project = ProjectDocument.new("Demo")
    doc = PaleoMapDocument(name="ZJ2 Map", linked_target_horizon="ZJ2")
    project.paleomap_documents.append(doc)

    report = run_basic_qc(project, doc.id)

    assert report.status == "warning"
    assert report.issues[0]["rule"] == "facies_polygons_present"


def test_record_export_adds_artifact():
    project = ProjectDocument.new("Demo")

    artifact = record_export(project, "map_1", "exports/map.geojson", "geojson", ["pred_1"])

    assert project.export_artifacts == [artifact]
    assert artifact.format == "geojson"
    assert artifact.source_task_ids == ["pred_1"]
```

- [ ] **Step 2: Run QC/export tests to verify they fail**

Run:

```bash
python -m pytest tests/test_workflow_service.py::test_qc_warns_when_map_has_no_polygons tests/test_workflow_service.py::test_record_export_adds_artifact -v
```

Expected: FAIL with missing modules.

- [ ] **Step 3: Implement QC service**

Create `paleo_workbench/workflow/qc.py`:

```python
from __future__ import annotations

from paleo_workbench.project.models import ProjectDocument, QualityReport


def run_basic_qc(project: ProjectDocument, map_document_id: str) -> QualityReport:
    document = next(doc for doc in project.paleomap_documents if doc.id == map_document_id)
    issues: list[dict] = []
    if not document.facies_polygons:
        issues.append(
            {
                "rule": "facies_polygons_present",
                "severity": "warning",
                "message": "古地理图尚无相带多边形",
            }
        )
    if not document.linked_target_horizon:
        issues.append(
            {
                "rule": "target_horizon_present",
                "severity": "error",
                "message": "古地理图未关联目标层位",
            }
        )
    report = QualityReport(
        linked_map_document_id=map_document_id,
        rules=["facies_polygons_present", "target_horizon_present"],
        issues=issues,
        status="pass" if not issues else "warning",
    )
    project.quality_reports.append(report)
    return report
```

- [ ] **Step 4: Implement export record service**

Create `paleo_workbench/workflow/export.py`:

```python
from __future__ import annotations

from paleo_workbench.project.models import ExportArtifact, ProjectDocument


def record_export(
    project: ProjectDocument,
    linked_id: str,
    output_path: str,
    fmt: str,
    source_task_ids: list[str],
) -> ExportArtifact:
    artifact = ExportArtifact(
        linked_id=linked_id,
        format=fmt,
        output_path=output_path,
        included_map_elements=["legend", "north_arrow", "scale_bar"],
        source_task_ids=source_task_ids,
    )
    project.export_artifacts.append(artifact)
    return artifact
```

- [ ] **Step 5: Run QC/export tests**

Run:

```bash
python -m pytest tests/test_workflow_service.py -v
```

Expected: PASS.

- [ ] **Step 6: Checkpoint or commit**

If root git is repaired, run:

```bash
git add paleo_workbench/workflow/qc.py paleo_workbench/workflow/export.py tests/test_workflow_service.py
git commit -m "feat: add qc and export artifact records"
```

If root git is still invalid, record checkpoint: `Task 10 complete; root commit pending repository repair`.

---

