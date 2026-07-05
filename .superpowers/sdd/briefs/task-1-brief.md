### Task 1: Root Package And Development Entry Point

**Files:**
- Create: `pyproject.toml`
- Create: `paleo_workbench/__init__.py`
- Create: `paleo_workbench/main.py`
- Create: `tests/test_project_models.py`

**Interfaces:**
- Produces: importable package `paleo_workbench`
- Produces: runnable command `python -m paleo_workbench.main`
- Consumes: none

- [ ] **Step 1: Write the failing package import test**

Create `tests/test_project_models.py` with:

```python
def test_package_imports():
    import paleo_workbench

    assert paleo_workbench.__version__ == "0.1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_project_models.py::test_package_imports -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'paleo_workbench'`.

- [ ] **Step 3: Add root packaging**

Create `pyproject.toml`:

```toml
[project]
name = "paleo-workbench"
version = "0.1.0"
description = "Paleogeographic map compilation desktop workbench"
requires-python = ">=3.12,<3.13"
dependencies = [
    "pyside6>=6.6",
    "pydantic>=2.0",
    "numpy>=1.26",
    "pandas>=2.0",
    "openpyxl>=3.1",
    "lasio>=0.14",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-qt>=4.5.0",
]

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
testpaths = ["tests"]
qt_api = "pyside6"
timeout = 60
pythonpath = [
    ".",
    "geo-viz-engine",
    "geo-viz-engine/packages/geoviz_paleo_map",
    "geo-viz-engine/packages/geoviz_plots",
    "geo-viz-engine/packages/geoviz_seismic",
    "geo-viz-engine/packages/geoviz_well_log",
    "geo-viz-engine/packages/geoviz_cross_well",
]
```

Create `paleo_workbench/__init__.py`:

```python
"""Paleogeography map compilation workbench."""

__version__ = "0.1.0"
```

Create `paleo_workbench/main.py`:

```python
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QLabel


def main() -> int:
    app = QApplication(sys.argv)
    label = QLabel("Paleogeography Workbench")
    label.setMinimumSize(480, 240)
    label.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run package import test**

Run:

```bash
python -m pytest tests/test_project_models.py::test_package_imports -v
```

Expected: PASS.

- [ ] **Step 5: Verify app entry point imports without launching GUI**

Run:

```bash
python -c "from paleo_workbench.main import main; print(callable(main))"
```

Expected output:

```text
True
```

- [ ] **Step 6: Checkpoint**

Run:

```bash
git rev-parse --show-toplevel
```

Expected in current workspace: FAIL because root git is invalid. Record checkpoint in this plan under the task status section. If the root repository has been repaired with user approval, run:

```bash
git add pyproject.toml paleo_workbench/__init__.py paleo_workbench/main.py tests/test_project_models.py
git commit -m "chore: scaffold paleogeography workbench package"
```

---

