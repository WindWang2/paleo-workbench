# Task 2 Report

## Scope

Implemented Task 2 only in the owned files:

- `paleo_workbench/project/__init__.py`
- `paleo_workbench/project/models.py`
- `paleo_workbench/project/paths.py`
- `paleo_workbench/project/manager.py`
- `tests/test_project_models.py`
- `tests/test_project_manager.py`

## TDD Evidence

### RED 1

Command:

```bash
.venv/bin/python -m pytest tests/test_project_models.py::test_project_defaults_include_crs_and_empty_workflow -v
```

Result:

- Exit code `4`
- Failed during collection with `ModuleNotFoundError: No module named 'paleo_workbench.project'`

### GREEN 1

Command:

```bash
.venv/bin/python -m pytest tests/test_project_models.py -v
```

Result:

- Exit code `0`
- `2 passed`

### RED 2

Command:

```bash
.venv/bin/python -m pytest tests/test_project_manager.py::test_project_round_trip_uses_relative_paths -v
```

Result:

- Exit code `4`
- Failed during collection with `ModuleNotFoundError: No module named 'paleo_workbench.project.manager'`

### GREEN 2

Command:

```bash
.venv/bin/python -m pytest tests/test_project_manager.py -v
```

Result:

- First run exposed a real implementation bug:
  - Exit code `1`
  - `artifact_dir_for()` produced `demo.paleo.artifacts` instead of required `demo.artifacts`
- After fixing artifact path derivation:
  - Exit code `0`
  - `1 passed`

## Final Verification

Command:

```bash
.venv/bin/python -m pytest tests/test_project_models.py tests/test_project_manager.py -v
```

Result:

- Exit code `0`
- `3 passed in 0.09s`

## Checkpoint

Command:

```bash
git rev-parse --show-toplevel
```

Result:

- Exit code `128`
- Expected failure: `fatal: not a git repository (or any of the parent directories): .git`
- Checkpoint recorded instead of commit: `Task 2 complete; root commit pending repository repair`

## Self-Review

- Verified `.paleo.json` artifact root resolves to `project-name.artifacts/`
- Verified in-project resource paths persist as relative POSIX paths
- Verified external flag remains `False` for project-local resources
- No commit created because root git is invalid

## Task 2 Review Fixes

### Scope

Addressed the review findings only in Task 2-owned files:

- `paleo_workbench/project/models.py`
- `paleo_workbench/project/paths.py`
- `paleo_workbench/project/manager.py`
- `tests/test_project_models.py`
- `tests/test_project_manager.py`

### RED Evidence

Command:

```bash
.venv/bin/python -m pytest tests/test_project_models.py::test_project_defaults_include_crs_and_empty_workflow -v
```

Result:

- Exit code `1`
- Failed because `project.coordinate.project_crs` was `EPSG:4326` instead of required `EPSG:4326 / WGS84`

Command:

```bash
.venv/bin/python -m pytest tests/test_project_manager.py::test_resaving_loaded_project_keeps_relative_resource_paths -v
```

Result:

- Exit code `1`
- Failed because a second save rewrote `data/well.las` to `/home/kevin/projects/paleo_project/data/well.las`

Command:

```bash
.venv/bin/python -m pytest tests/test_project_manager.py::test_export_artifact_output_path_is_relativized_when_inside_project -v
```

Result:

- Exit code `1`
- Failed because `ExportArtifact.output_path` remained absolute instead of serializing as `exports/demo.png`

### Fix Summary

- Updated coordinate defaults to `EPSG:4326 / WGS84` for both project and display CRS.
- Fixed `relativize_path()` so relative inputs are resolved against the project directory, not the process CWD.
- Extended save-time normalization to relativize `ExportArtifact.output_path` when it lives under the project directory.
- Added coverage for repeated save/load cycles, external resource paths remaining external, and export artifact output path relativization.

### Verification

Focused checks:

- `tests/test_project_models.py::test_project_defaults_include_crs_and_empty_workflow` -> passed
- `tests/test_project_manager.py::test_resaving_loaded_project_keeps_relative_resource_paths` -> passed
- `tests/test_project_manager.py::test_external_resource_paths_remain_absolute_and_external` -> passed
- `tests/test_project_manager.py::test_export_artifact_output_path_is_relativized_when_inside_project` -> passed

Required full run:

```bash
.venv/bin/python -m pytest tests/test_project_models.py tests/test_project_manager.py -v
```

Result:

- Exit code `0`
- `6 passed in 0.09s`

Git root check:

```bash
git rev-parse --show-toplevel
```

Result:

- Exit code `128`
- Expected failure: `fatal: not a git repository (or any of the parent directories): .git`
