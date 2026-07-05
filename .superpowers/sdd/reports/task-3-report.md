# Task 3 Report: Resource Scanner And Format Classifier

## Scope

Implemented Task 3 in the owned files:

- `paleo_workbench/resources/__init__.py`
- `paleo_workbench/resources/classifier.py`
- `paleo_workbench/resources/scanner.py`
- `tests/test_resource_scanner.py`

## TDD Evidence

### RED

Added `tests/test_resource_scanner.py` first, then ran:

```bash
.venv/bin/python -m pytest tests/test_resource_scanner.py -v
```

Observed expected failure:

- `ModuleNotFoundError: No module named 'paleo_workbench.resources'`

This confirmed the test was exercising missing Task 3 functionality rather than passing against existing behavior.

### GREEN

Implemented the minimal resource package:

- `classify_path(path: Path) -> tuple[str, str, str]`
- `scan_resources(root: Path, project_path: Path | None = None) -> list[ResourceItem]`

Then reran:

```bash
.venv/bin/python -m pytest tests/test_resource_scanner.py -v
```

Result:

- `3 passed`

## Implementation Notes

- Known indexed formats:
  - `las` -> `well_log`
  - `sgy`/`segy` -> `seismic`
  - `dat` -> `tabular`, with path-based special cases for `time_depth`, `horizon`, and `well_stratification`
  - `xlsx`/`xls`/`xml` -> `spreadsheet`
- Unsupported or proprietary/reference-oriented formats are indexed with `status=indexed_reference`
  - `dfb` or filenames containing `相图` -> `reference_map`
  - `wlp` -> `well_reference`
  - `pdf`/`ppt`/`pptx` -> `document`
  - `png`/`jpg`/`jpeg`/`tif`/`tiff` -> `image_reference`
  - unknown extensions -> `unknown`
- Scanner emits `ResourceItem` records compatible with Task 2:
  - `source="scan"`
  - `parsed_summary={"size_bytes": ...}`
  - `checksum=<sha256>`
  - `external` determined through Task 2 path relativization when `project_path` is provided
- Scanner skips macOS sidecar files prefixed with `._`

## Focused Sample Scan

Ran:

```bash
.venv/bin/python -c "from pathlib import Path; from paleo_workbench.resources.scanner import scan_resources; items = scan_resources(Path('data')); print(len(items)); print(sorted({item.format for item in items})[:10])"
```

Observed concise result:

- resource count: `200`
- first formats: `['dat', 'dfb', 'jpg', 'las', 'pdf', 'png', 'pptx', 'sgy', 'wlp', 'xls']`

## Required Verification

Ran:

```bash
.venv/bin/python -m pytest tests/test_resource_scanner.py tests/test_project_models.py tests/test_project_manager.py -v
```

Result:

- `9 passed`

## Checkpoint

Ran:

```bash
git rev-parse --show-toplevel
```

Observed expected repository failure:

- `fatal: not a git repository (or any of the parent directories): .git`

Checkpoint recorded instead of commit:

- `Task 3 complete; root commit pending repository repair`

## Self-Review

- Kept changes scoped to the Task 3 owned files.
- Preserved Task 2 path semantics by delegating project-relative/external handling to `relativize_path`.
- Kept unsupported/proprietary resources indexed as references rather than attempting parsing.
- No commit created because root git is invalid.

---

## Task 3 Review Fixes

### Findings Addressed

- Fixed `scan_resources(..., project_path=None)` so scanned resources now retain their canonical absolute source path instead of being rewritten relative to the scan root.
- Preserved existing Task 2 semantics when `project_path` is provided by continuing to route stored path and `external` handling through `relativize_path`.
- Added checksum coverage that fails if the scanner emits `checksum=None` or an incorrect SHA-256 digest for a known file payload.
- Tightened scanner assertions for `format`, `parsed_summary["size_bytes"]`, and `indexed_reference` behavior across representative well-log, document, image, and reference cases.

### RED Evidence

Ran before the production fix:

```bash
.venv/bin/python -m pytest tests/test_resource_scanner.py -v
```

Observed the expected regression failure:

- `test_scan_resources_without_project_path_preserves_canonical_source_path`
- actual path: `logs/A1.Las`
- expected path: absolute canonical file path under the temp directory

This isolated the root cause to the scanner's default `path.relative_to(root)` behavior.

### GREEN Verification

Focused scanner suite:

```bash
.venv/bin/python -m pytest tests/test_resource_scanner.py -v
```

Result:

- `5 passed`

Required verification suite:

```bash
.venv/bin/python -m pytest tests/test_resource_scanner.py tests/test_project_models.py tests/test_project_manager.py -v
```

Result:

- `11 passed`

Repository root check:

```bash
git rev-parse --show-toplevel
```

Observed expected failure:

- `fatal: not a git repository (or any of the parent directories): .git`
