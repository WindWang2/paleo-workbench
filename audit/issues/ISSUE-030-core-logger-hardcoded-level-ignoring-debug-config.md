# ISSUE-030: Logger Hardcoded to `INFO`, Suppressing `config.DEBUG`

- **Severity**: Low
- **Subproject**: `src` (`src/core/logger.py`)
- **Target File**: `file:///home/kevin/projects/paleo_project/main/src/core/logger.py#L4-L12`

---

## Defect Description & Root Cause Analysis

In `src/core/logger.py`, `setup_logger()` initializes the core logging instance with an unconditionally hardcoded `logging.INFO` level:

```python
def setup_logger():
    logger = logging.getLogger("paleo_main")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
    handler.setFormatter(formatter)
    if not logger.handlers:
        logger.addHandler(handler)
    return logger
```

Meanwhile, `src/config.py:20` defines `DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"`.
`setup_logger()` never inspects `config.DEBUG` or the `DEBUG` environment variable, permanently silencing `logger.debug()` statements across the application.

---

## Impact Analysis

- **Debugging Obstruction**: Developers setting `DEBUG=true` in `.env` or environment variables cannot view debug logs from `paleo_main`.

---

## Reproduction Scenario & Execution Proof

### Verifiable Python Code Execution
```python
import os, logging
os.environ["DEBUG"] = "true"

from src.core.logger import logger
print("Logger level:", logger.level)  # Output: 20 (logging.INFO) instead of 10 (logging.DEBUG)
```

---

## Concrete Suggested Fix

Check `os.getenv("DEBUG")` or accept an optional parameter during logger initialization:

### Patch (`src/core/logger.py`)
```python
import logging
import os

def setup_logger(debug: bool | None = None) -> logging.Logger:
    logger = logging.getLogger("paleo_main")
    if debug is None:
        debug = os.getenv("DEBUG", "false").lower() in ("true", "1", "t")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    handler = logging.StreamHandler()
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
    handler.setFormatter(formatter)
    if not logger.handlers:
        logger.addHandler(handler)
    return logger
```
