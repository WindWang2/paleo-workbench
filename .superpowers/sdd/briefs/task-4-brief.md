### Task 4: Workflow Service And Dashboard State

**Files:**
- Create: `paleo_workbench/workflow/__init__.py`
- Create: `paleo_workbench/workflow/service.py`
- Create: `tests/test_workflow_service.py`

**Interfaces:**
- Consumes: `ProjectDocument`, `CompilationRun`, `WorkflowStep`
- Produces: `create_compilation_run(project, name, target_horizon, sequence_scheme) -> CompilationRun`
- Produces: `dashboard_state(project) -> dict[str, object]`

- [ ] **Step 1: Write failing workflow tests**

Create `tests/test_workflow_service.py`:

```python
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.workflow.service import create_compilation_run, dashboard_state


def test_create_compilation_run_adds_ordered_steps():
    project = ProjectDocument.new(name="Demo")

    run = create_compilation_run(
        project,
        name="ZJ2 编图",
        target_horizon="ZJ2",
        sequence_scheme="三级层序格架",
    )

    assert project.compilation_runs == [run]
    assert [s.step_type for s in run.workflow_steps] == [
        "data_check",
        "factor_map",
        "prediction",
        "map_compile",
        "qc",
        "export",
    ]


def test_dashboard_state_reports_missing_and_available_resources():
    project = ProjectDocument.new(name="Demo")
    project.resources.append(
        ResourceItem(name="A1.Las", path="data/A1.Las", type="well_log", format="las")
    )
    create_compilation_run(project, "Run", "ZJ2", "三级层序格架")

    state = dashboard_state(project)

    assert state["active_target_horizon"] == "ZJ2"
    assert state["resource_counts"]["well_log"] == 1
    assert state["workflow_status"] == "draft"
```

- [ ] **Step 2: Run workflow tests to verify they fail**

Run:

```bash
python -m pytest tests/test_workflow_service.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `paleo_workbench.workflow`.

- [ ] **Step 3: Implement workflow service**

Create `paleo_workbench/workflow/__init__.py`:

```python
from paleo_workbench.workflow.service import create_compilation_run, dashboard_state

__all__ = ["create_compilation_run", "dashboard_state"]
```

Create `paleo_workbench/workflow/service.py`:

```python
from __future__ import annotations

from collections import Counter

from paleo_workbench.project.models import CompilationRun, ProjectDocument, WorkflowStep


STEP_ORDER = ["data_check", "factor_map", "prediction", "map_compile", "qc", "export"]


def create_compilation_run(
    project: ProjectDocument,
    name: str,
    target_horizon: str,
    sequence_scheme: str,
) -> CompilationRun:
    project.stratigraphy.target_horizon = target_horizon
    project.stratigraphy.systems_tract_scheme = sequence_scheme
    run = CompilationRun(
        name=name,
        target_horizon=target_horizon,
        sequence_scheme_ref=sequence_scheme,
        workflow_steps=[WorkflowStep(step_type=step) for step in STEP_ORDER],
    )
    project.compilation_runs.append(run)
    return run


def dashboard_state(project: ProjectDocument) -> dict[str, object]:
    active_run = project.compilation_runs[-1] if project.compilation_runs else None
    counts = Counter(resource.type for resource in project.resources)
    return {
        "project_name": project.meta.name,
        "active_target_horizon": active_run.target_horizon if active_run else project.stratigraphy.target_horizon,
        "sequence_scheme": active_run.sequence_scheme_ref if active_run else project.stratigraphy.systems_tract_scheme,
        "workflow_status": active_run.status if active_run else "draft",
        "resource_counts": dict(counts),
        "factor_map_count": len(project.factor_map_tasks),
        "prediction_count": len(project.prediction_tasks),
        "qc_issue_count": sum(len(report.issues) for report in project.quality_reports),
        "export_count": len(project.export_artifacts),
    }
```

- [ ] **Step 4: Run workflow tests**

Run:

```bash
python -m pytest tests/test_workflow_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Checkpoint or commit**

If root git is repaired, run:

```bash
git add paleo_workbench/workflow tests/test_workflow_service.py
git commit -m "feat: add compilation workflow service"
```

If root git is still invalid, record checkpoint: `Task 4 complete; root commit pending repository repair`.

---

