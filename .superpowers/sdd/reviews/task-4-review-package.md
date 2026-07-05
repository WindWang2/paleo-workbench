# Review package: Task 4 (no git root)

## Environment
Root git is invalid; no BASE/HEAD SHA is available. Package generated from current Task 4 files. Python baseline: .venv CPython 3.12.13.

## Files changed
paleo_workbench/workflow/__init__.py
paleo_workbench/workflow/service.py
tests/test_workflow_service.py

## Implementer report
# Task 4 Report: Workflow Service And Dashboard State

## Scope

- Implemented `paleo_workbench/workflow/__init__.py`
- Implemented `paleo_workbench/workflow/service.py`
- Added `tests/test_workflow_service.py`

## TDD Evidence

### RED

Command:

```bash
.venv/bin/python -m pytest tests/test_workflow_service.py -v
```

Result:

- Failed during collection with `ModuleNotFoundError: No module named 'paleo_workbench.workflow'`

### GREEN

Command:

```bash
.venv/bin/python -m pytest tests/test_workflow_service.py -v
```

Result:

- `2 passed in 0.09s`

## Required Verification

Command:

```bash
.venv/bin/python -m pytest tests/test_workflow_service.py tests/test_project_models.py tests/test_project_manager.py tests/test_resource_scanner.py -v
```

Result:

- `13 passed in 0.11s`

## Git Checkpoint

Command:

```bash
git rev-parse --show-toplevel
```

Result:

- Failed as expected: `fatal: not a git repository (or any of the parent directories): .git`
- Checkpoint recorded: `Task 4 complete; root commit pending repository repair`

## Self-Review

- `create_compilation_run` updates project stratigraphy, creates ordered default workflow steps, appends the new run, and returns it.
- `dashboard_state` derives dashboard fields from project and active run data without adding UI-owned state.
- Changes stayed within the Task 4 owned files plus this report.

## Commit

- None created, because root git is invalid.


## paleo_workbench/workflow/__init__.py
     1	from paleo_workbench.workflow.service import create_compilation_run, dashboard_state
     2	
     3	__all__ = ["create_compilation_run", "dashboard_state"]

## paleo_workbench/workflow/service.py
     1	from __future__ import annotations
     2	
     3	from collections import Counter
     4	
     5	from paleo_workbench.project.models import CompilationRun, ProjectDocument, WorkflowStep
     6	
     7	
     8	STEP_ORDER = ["data_check", "factor_map", "prediction", "map_compile", "qc", "export"]
     9	
    10	
    11	def create_compilation_run(
    12	    project: ProjectDocument,
    13	    name: str,
    14	    target_horizon: str,
    15	    sequence_scheme: str,
    16	) -> CompilationRun:
    17	    project.stratigraphy.target_horizon = target_horizon
    18	    project.stratigraphy.systems_tract_scheme = sequence_scheme
    19	    run = CompilationRun(
    20	        name=name,
    21	        target_horizon=target_horizon,
    22	        sequence_scheme_ref=sequence_scheme,
    23	        workflow_steps=[WorkflowStep(step_type=step_type) for step_type in STEP_ORDER],
    24	    )
    25	    project.compilation_runs.append(run)
    26	    return run
    27	
    28	
    29	def dashboard_state(project: ProjectDocument) -> dict[str, object]:
    30	    active_run = project.compilation_runs[-1] if project.compilation_runs else None
    31	    resource_counts = Counter(resource.type for resource in project.resources)
    32	    return {
    33	        "project_name": project.meta.name,
    34	        "active_target_horizon": (
    35	            active_run.target_horizon
    36	            if active_run is not None
    37	            else project.stratigraphy.target_horizon
    38	        ),
    39	        "sequence_scheme": (
    40	            active_run.sequence_scheme_ref
    41	            if active_run is not None
    42	            else project.stratigraphy.systems_tract_scheme
    43	        ),
    44	        "workflow_status": active_run.status if active_run is not None else "draft",
    45	        "resource_counts": dict(resource_counts),
    46	        "factor_map_count": len(project.factor_map_tasks),
    47	        "prediction_count": len(project.prediction_tasks),
    48	        "qc_issue_count": sum(len(report.issues) for report in project.quality_reports),
    49	        "export_count": len(project.export_artifacts),
    50	    }

## tests/test_workflow_service.py
     1	from paleo_workbench.project.models import ProjectDocument, ResourceItem
     2	from paleo_workbench.workflow.service import create_compilation_run, dashboard_state
     3	
     4	
     5	def test_create_compilation_run_adds_ordered_steps():
     6	    project = ProjectDocument.new(name="Demo")
     7	
     8	    run = create_compilation_run(
     9	        project,
    10	        name="ZJ2 编图",
    11	        target_horizon="ZJ2",
    12	        sequence_scheme="三级层序格架",
    13	    )
    14	
    15	    assert project.compilation_runs == [run]
    16	    assert [step.step_type for step in run.workflow_steps] == [
    17	        "data_check",
    18	        "factor_map",
    19	        "prediction",
    20	        "map_compile",
    21	        "qc",
    22	        "export",
    23	    ]
    24	
    25	
    26	def test_dashboard_state_reports_missing_and_available_resources():
    27	    project = ProjectDocument.new(name="Demo")
    28	    project.resources.append(
    29	        ResourceItem(name="A1.Las", path="data/A1.Las", type="well_log", format="las")
    30	    )
    31	    create_compilation_run(project, "Run", "ZJ2", "三级层序格架")
    32	
    33	    state = dashboard_state(project)
    34	
    35	    assert state["active_target_horizon"] == "ZJ2"
    36	    assert state["resource_counts"]["well_log"] == 1
    37	    assert state["workflow_status"] == "draft"
