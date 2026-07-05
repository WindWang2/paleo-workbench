# Task 7 Report: Minimal Paleo Map Adapter

## Scope

- Implemented `paleo_workbench/adapters/paleo_map.py`
- Updated `tests/test_adapter_schemas.py`

## TDD Evidence

### RED

Command:

```bash
.venv/bin/python -m pytest tests/test_adapter_schemas.py::test_paleo_map_adapter_validates_payload_and_exports_metadata -v
```

Result:

- Failed during collection with `ModuleNotFoundError: No module named 'paleo_workbench.adapters.paleo_map'`

### GREEN

Command:

```bash
.venv/bin/python -m pytest tests/test_adapter_schemas.py -v
```

Result:

- `4 passed in 0.08s`

## Required Verification

Command:

```bash
.venv/bin/python -m pytest tests/test_adapter_schemas.py tests/test_mock_outputs.py tests/test_workflow_service.py tests/test_project_models.py tests/test_project_manager.py tests/test_resource_scanner.py -v
```

Result:

- `19 passed in 0.12s`

## Git Checkpoint

Command:

```bash
git rev-parse --show-toplevel
```

Result:

- Failed as expected: `fatal: not a git repository (or any of the parent directories): .git`
- Checkpoint recorded: `Task 7 complete; root commit pending repository repair`

## Self-Review

- `PaleoMapAdapter` validates `viewer_type=paleo_map` and rejects mismatched payloads.
- Export writes GeoJSON FeatureCollection stubs and records adapter metadata in `ExportResult`.
- Changes are limited to the Task 7 owned files plus this report.

## Commit

- None created, because root git is invalid.