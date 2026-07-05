### Task 11: End-To-End MVP Smoke Path

**Files:**
- Modify: `tests/test_integration_smoke.py`

**Interfaces:**
- Consumes all services from Tasks 2-10
- Produces executable proof of MVP success criteria

- [ ] **Step 1: Add failing full-loop smoke test**

Append to `tests/test_integration_smoke.py`:

```python
from pathlib import Path

from paleo_workbench.adapters.paleo_map import PaleoMapAdapter
from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.resources.scanner import scan_resources
from paleo_workbench.workflow.export import record_export
from paleo_workbench.workflow.factors import create_mock_factor_map
from paleo_workbench.workflow.qc import run_basic_qc
from paleo_workbench.workflow.service import create_compilation_run, dashboard_state


def test_full_mvp_loop_recovers_dashboard_state(tmp_path: Path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / "A1.Las").write_text("~Version\n", encoding="utf-8")
    project_path = tmp_path / "demo.paleo.json"

    project = ProjectDocument.new("Demo")
    project.resources = scan_resources(data_root, project_path=project_path)
    run = create_compilation_run(project, "ZJ2 Run", "ZJ2", "三级层序格架")
    factor = create_mock_factor_map(project, "ZJ2", "sand_thickness", seed=42)
    pred = MockPredictionAdapter().run(project, [factor.id], seed=7)
    doc = PaleoMapDocument(name="ZJ2 Map", linked_target_horizon="ZJ2", linked_prediction_task_id=pred.id)
    project.paleomap_documents.append(doc)
    qc = run_basic_qc(project, doc.id)

    adapter = PaleoMapAdapter()
    adapter.set_data({"viewer_type": "paleo_map", "schema_version": "1.0", "resources": [], "layers": []})
    export_path = tmp_path / "demo.artifacts" / "exports" / "map.geojson"
    result = adapter.export({"path": str(export_path), "format": "geojson"})
    artifact = record_export(project, doc.id, result.output_path, result.format, [pred.id, qc.id])
    run.active_factor_map_task_ids = [factor.id]
    run.active_prediction_task_id = pred.id
    run.active_paleomap_document_id = doc.id
    run.active_quality_report_id = qc.id
    run.export_artifact_ids = [artifact.id]

    ProjectManager(project_path).save(project)
    loaded = ProjectManager(project_path).load()
    state = dashboard_state(loaded)

    assert state["project_name"] == "Demo"
    assert state["active_target_horizon"] == "ZJ2"
    assert state["factor_map_count"] == 1
    assert state["prediction_count"] == 1
    assert state["export_count"] == 1
```

- [ ] **Step 2: Run full-loop test to verify it passes or exposes integration defects**

Run:

```bash
python -m pytest tests/test_integration_smoke.py::test_full_mvp_loop_recovers_dashboard_state -v
```

Expected: PASS. If it fails, fix only the integration defect exposed by the assertion or traceback, then rerun the same test.

- [ ] **Step 3: Run full MVP test suite**

Run:

```bash
python -m pytest tests -v
```

Expected: PASS for all root `tests/`.

- [ ] **Step 4: Checkpoint or commit**

If root git is repaired, run:

```bash
git add tests/test_integration_smoke.py
git commit -m "test: add paleogeography workbench mvp smoke path"
```

If root git is still invalid, record checkpoint: `Task 11 complete; root commit pending repository repair`.

---

