# Review package: Task 1 (no git root)

## Environment
Root git is invalid; no BASE/HEAD SHA is available. This package is generated from the current Task 1 files.

## Files changed
pyproject.toml
paleo_workbench/__init__.py
paleo_workbench/main.py
tests/test_project_models.py

## Implementer report
# Task 1 Report

## Status
Done

## RED

Command:

```bash
python -m pytest tests/test_project_models.py::test_package_imports -v
```

Result:

```text
FAILED tests/test_project_models.py::test_package_imports
ModuleNotFoundError: No module named 'paleo_workbench'
```

## GREEN

Command:

```bash
python -m pytest tests/test_project_models.py::test_package_imports -v
```

Result:

```text
PASSED tests/test_project_models.py::test_package_imports
```

Command:

```bash
python -c "from paleo_workbench.main import main; print(callable(main))"
```

Result:

```text
True
```

## Checkpoint

Command:

```bash
git rev-parse --show-toplevel
```

Result:

```text
fatal: not a git repository (or any of the parent directories): .git
```

## Notes

- Root git is invalid, so no commit was created.
- `pytest` emitted a warning about unknown config option `timeout` because the timeout plugin is not installed in this environment; the Task 1 checks still passed.

## pyproject.toml
     1	[project]
     2	name = "paleo-workbench"
     3	version = "0.1.0"
     4	description = "Paleogeographic map compilation desktop workbench"
     5	requires-python = ">=3.12,<3.13"
     6	dependencies = [
     7	    "pyside6>=6.6",
     8	    "pydantic>=2.0",
     9	    "numpy>=1.26",
    10	    "pandas>=2.0",
    11	    "openpyxl>=3.1",
    12	    "lasio>=0.14",
    13	]
    14	
    15	[project.optional-dependencies]
    16	dev = [
    17	    "pytest>=8.0",
    18	    "pytest-qt>=4.5.0",
    19	]
    20	
    21	[build-system]
    22	requires = ["setuptools>=68.0"]
    23	build-backend = "setuptools.build_meta"
    24	
    25	[tool.pytest.ini_options]
    26	testpaths = ["tests"]
    27	qt_api = "pyside6"
    28	timeout = 60
    29	pythonpath = [
    30	    ".",
    31	    "geo-viz-engine",
    32	    "geo-viz-engine/packages/geoviz_paleo_map",
    33	    "geo-viz-engine/packages/geoviz_plots",
    34	    "geo-viz-engine/packages/geoviz_seismic",
    35	    "geo-viz-engine/packages/geoviz_well_log",
    36	    "geo-viz-engine/packages/geoviz_cross_well",
    37	]

## paleo_workbench/__init__.py
     1	"""Paleogeography map compilation workbench."""
     2	
     3	__version__ = "0.1.0"

## paleo_workbench/main.py
     1	from __future__ import annotations
     2	
     3	import sys
     4	
     5	from PySide6.QtWidgets import QApplication, QLabel
     6	
     7	
     8	def main() -> int:
     9	    app = QApplication(sys.argv)
    10	    label = QLabel("Paleogeography Workbench")
    11	    label.setMinimumSize(480, 240)
    12	    label.show()
    13	    return app.exec()
    14	
    15	
    16	if __name__ == "__main__":
    17	    raise SystemExit(main())

## tests/test_project_models.py
     1	def test_package_imports():
     2	    import paleo_workbench
     3	
     4	    assert paleo_workbench.__version__ == "0.1.0"
