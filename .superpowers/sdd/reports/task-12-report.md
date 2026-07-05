# Task 12 Report: Optional Engine Adapter Hardening

## Scope

- Added `geo-viz-engine/tests/test_paleo_workbench_adapter_import.py`
- Verified `PaleoMapCanvas` is already exported from `geoviz_paleo_map.__init__`

## TDD Evidence

### Initial Run (before uv sync)

Command:

```bash
cd geo-viz-engine && .venv/bin/python -m pytest tests/test_paleo_workbench_adapter_import.py -v
```

Result:

- Failed with `ModuleNotFoundError: No module named 'geoviz_paleo_map'` (workspace packages not installed in venv)

### Environment Fix

Command:

```bash
cd geo-viz-engine && uv sync --extra dev
```

Result:

- Workspace packages installed from `paleo_project/geo-viz-engine`

### GREEN

Command:

```bash
cd geo-viz-engine && .venv/bin/python -m pytest tests/test_paleo_workbench_adapter_import.py -v
```

Result:

- `1 passed in 0.29s`

## Required Verification

Command:

```bash
.venv/bin/python -m pytest tests -v
```

Result (paleo_project root):

- `24 passed in 0.14s`

## Git Checkpoint

Command:

```bash
cd geo-viz-engine && git add tests/test_paleo_workbench_adapter_import.py && git commit -m "feat: expose paleo map canvas for workbench adapter"
```

Result:

- Committed in `geo-viz-engine` repository (valid git root)

## Self-Review

- `PaleoMapCanvas` was already present in `geoviz_paleo_map.__all__`; no `__init__.py` change required.
- New import test locks the public API surface for workbench adapter integration.
- `geo-viz-engine` remains an independent boundary; only the import contract test was added.

## Commit

- `geo-viz-engine`: test file committed
- `paleo_project` root: still no git repository