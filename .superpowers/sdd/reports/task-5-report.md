# Task 5 Report: Deterministic Factor Map And Prediction Mock Services

## Scope

- Implemented `paleo_workbench/workflow/factors.py`
- Implemented `paleo_workbench/prediction/__init__.py`
- Implemented `paleo_workbench/prediction/adapters.py`
- Added `tests/test_mock_outputs.py`

## TDD Evidence

### RED

Command:

```bash
.venv/bin/python -m pytest tests/test_mock_outputs.py -v
```

Result:

- Failed during collection with `ModuleNotFoundError: No module named 'paleo_workbench.prediction'`

### GREEN

Command:

```bash
.venv/bin/python -m pytest tests/test_mock_outputs.py -v
```

Result:

- `2 passed in 0.09s`

## Required Verification

Command:

```bash
.venv/bin/python -m pytest tests/test_mock_outputs.py tests/test_workflow_service.py tests/test_project_models.py tests/test_project_manager.py tests/test_resource_scanner.py -v
```

Result:

- `15 passed in 0.12s`

## Git Checkpoint

Command:

```bash
git rev-parse --show-toplevel
```

Result:

- Failed as expected: `fatal: not a git repository (or any of the parent directories): .git`
- Checkpoint recorded: `Task 5 complete; root commit pending repository repair`

## Self-Review

- Deterministic generators include `seed`, `generator_version`, and `input_snapshot_hash`.
- Mock prediction output is explicitly marked replaceable and non-final.
- Changes are limited to the Task 5 owned files plus this report.

## Commit

- None created, because root git is invalid.
