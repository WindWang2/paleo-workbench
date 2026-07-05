# Review package: Task 4 re-review (no git root)

## Environment
Root git is invalid; no BASE/HEAD SHA is available. Package generated after Task 4 review fixes. Python baseline: .venv CPython 3.12.13.

## Files changed
paleo_workbench/workflow/__init__.py
paleo_workbench/workflow/service.py
tests/test_workflow_service.py

## Implementer and fix report
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

## Review Fixes

### Scope

- Updated `tests/test_workflow_service.py` to add direct stratigraphy assertions for `create_compilation_run`.
- Strengthened `test_dashboard_state_reports_missing_and_available_resources` to verify deterministic missing and available required resource derivation.
- Updated `paleo_workbench/workflow/service.py` to expose `resource_readiness` derived from required scanner-aligned resource types: `well_log`, `seismic`, and `horizon`.

### RED

Command:

```bash
.venv/bin/python -m pytest tests/test_workflow_service.py -v
```

Result:

- `test_dashboard_state_reports_missing_and_available_resources` failed with `KeyError: 'resource_readiness'`

### GREEN

Command:

```bash
.venv/bin/python -m pytest tests/test_workflow_service.py -v
```

Result:

- `2 passed in 0.09s`

### Required Verification

Command:

```bash
.venv/bin/python -m pytest tests/test_workflow_service.py tests/test_project_models.py tests/test_project_manager.py tests/test_resource_scanner.py -v
```

Result:

- `13 passed in 0.11s`

### Git Check

Command:

```bash
git rev-parse --show-toplevel
```

Result:

- Failed as expected: `fatal: not a git repository (or any of the parent directories): .git`


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
     9	REQUIRED_RESOURCE_TYPES = ["well_log", "seismic", "horizon"]
    10	
    11	
    12	def create_compilation_run(
    13	    project: ProjectDocument,
    14	    name: str,
    15	    target_horizon: str,
    16	    sequence_scheme: str,
    17	) -> CompilationRun:
    18	    project.stratigraphy.target_horizon = target_horizon
    19	    project.stratigraphy.systems_tract_scheme = sequence_scheme
    20	    run = CompilationRun(
    21	        name=name,
    22	        target_horizon=target_horizon,
    23	        sequence_scheme_ref=sequence_scheme,
    24	        workflow_steps=[WorkflowStep(step_type=step_type) for step_type in STEP_ORDER],
    25	    )
    26	    project.compilation_runs.append(run)
    27	    return run
    28	
    29	
    30	def dashboard_state(project: ProjectDocument) -> dict[str, object]:
    31	    active_run = project.compilation_runs[-1] if project.compilation_runs else None
    32	    resource_counts = Counter(resource.type for resource in project.resources)
    33	    available_counts = {
    34	        resource_type: resource_counts.get(resource_type, 0)
    35	        for resource_type in REQUIRED_RESOURCE_TYPES
    36	    }
    37	    missing_types = [
    38	        resource_type
    39	        for resource_type, count in available_counts.items()
    40	        if count == 0
    41	    ]
    42	    return {
    43	        "project_name": project.meta.name,
    44	        "active_target_horizon": (
    45	            active_run.target_horizon
    46	            if active_run is not None
    47	            else project.stratigraphy.target_horizon
    48	        ),
    49	        "sequence_scheme": (
    50	            active_run.sequence_scheme_ref
    51	            if active_run is not None
    52	            else project.stratigraphy.systems_tract_scheme
    53	        ),
    54	        "workflow_status": active_run.status if active_run is not None else "draft",
    55	        "resource_counts": dict(resource_counts),
    56	        "resource_readiness": {
    57	            "required_types": REQUIRED_RESOURCE_TYPES,
    58	            "available_counts": available_counts,
    59	            "missing_types": missing_types,
    60	            "ready": not missing_types,
    61	        },
    62	        "factor_map_count": len(project.factor_map_tasks),
    63	        "prediction_count": len(project.prediction_tasks),
    64	        "qc_issue_count": sum(len(report.issues) for report in project.quality_reports),
    65	        "export_count": len(project.export_artifacts),
    66	    }

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
    16	    assert project.stratigraphy.target_horizon == "ZJ2"
    17	    assert project.stratigraphy.systems_tract_scheme == "三级层序格架"
    18	    assert [step.step_type for step in run.workflow_steps] == [
    19	        "data_check",
    20	        "factor_map",
    21	        "prediction",
    22	        "map_compile",
    23	        "qc",
    24	        "export",
    25	    ]
    26	
    27	
    28	def test_dashboard_state_reports_missing_and_available_resources():
    29	    project = ProjectDocument.new(name="Demo")
    30	    project.resources.extend(
    31	        [
    32	            ResourceItem(name="A1.Las", path="data/A1.Las", type="well_log", format="las"),
    33	            ResourceItem(
    34	                name="200P_seismic.sgy",
    35	                path="data/200P_seismic.sgy",
    36	                type="seismic",
    37	                format="sgy",
    38	            ),
    39	        ]
    40	    )
    41	    create_compilation_run(project, "Run", "ZJ2", "三级层序格架")
    42	
    43	    state = dashboard_state(project)
    44	
    45	    assert state["active_target_horizon"] == "ZJ2"
    46	    assert state["resource_counts"]["well_log"] == 1
    47	    assert state["resource_counts"]["seismic"] == 1
    48	    assert state["workflow_status"] == "draft"
    49	    assert state["resource_readiness"] == {
    50	        "required_types": ["well_log", "seismic", "horizon"],
    51	        "available_counts": {"well_log": 1, "seismic": 1, "horizon": 0},
    52	        "missing_types": ["horizon"],
    53	        "ready": False,
    54	    }
