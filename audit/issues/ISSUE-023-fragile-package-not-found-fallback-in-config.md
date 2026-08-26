# ISSUE-023: Fragile `PackageNotFoundError` Fallback in `src/config.py`

- **Severity**: Medium
- **Subproject**: `src` (`src/config.py`)
- **Target File**: `file:///home/kevin/projects/paleo_project/main/src/config.py#L8-L15,L19`

---

## Defect Description & Root Cause Analysis

In `src/config.py`, version detection for the core configuration object is implemented as follows:

```python
def package_version() -> str:
    try:
        return importlib.metadata.version("paleo-workbench")
    except importlib.metadata.PackageNotFoundError:
        from paleo_workbench import __version__

        return __version__


class Config:
    APP_NAME: str = "Paleo-Workbench API"
    VERSION: str = package_version()
```

`package_version()` only catches `importlib.metadata.PackageNotFoundError`. If `paleo-workbench` is not installed as an editable pip package in the active virtual environment, it falls back to `from paleo_workbench import __version__`.

However, importing `paleo_workbench` triggers `ensure_geoviz_on_path()` and imports additional subpackages. If optional dependencies are missing, or if `sys.path` does not yet include `paleo_workbench`, the import raises `ModuleNotFoundError` or `ImportError`.

Because `Config.VERSION = package_version()` is evaluated at module import time, any module importing `src.config` (`src.app`, `src.api.routes`, etc.) crashes immediately with an unhandled exception.

---

## Impact Analysis

- **Startup Failure**: Core API services and tools in `src/` fail to import if `paleo_workbench` is not installed in the Python environment metadata or fails to import cleanly.

---

## Reproduction Scenario & Execution Proof

### Command Execution Trace
```bash
.venv/bin/python -c '
import sys, importlib.metadata
from unittest.mock import patch
with patch("importlib.metadata.version", side_effect=importlib.metadata.PackageNotFoundError):
    with patch.dict("sys.modules", {"paleo_workbench": None}):
        import src.config
'
```

### Traceback Output:
```
ModuleNotFoundError: import of paleo_workbench halted; None in sys.modules
```

---

## Concrete Suggested Fix

Catch general exceptions and provide a static fallback version string:

### Patch (`src/config.py`)
```python
def package_version() -> str:
    try:
        return importlib.metadata.version("paleo-workbench")
    except Exception:
        try:
            from paleo_workbench import __version__

            return __version__
        except Exception:
            return "0.2.17a0"
```
