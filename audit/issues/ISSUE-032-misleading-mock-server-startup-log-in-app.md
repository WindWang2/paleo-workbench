# ISSUE-032: Misleading Server Startup Log in `src/app.py` Without Listening Daemon

- **Severity**: Low
- **Subproject**: `src` (`src/app.py`)
- **Target File**: `file:///home/kevin/projects/paleo_project/main/src/app.py#L6-L13`

---

## Defect Description & Root Cause Analysis

In `src/app.py`, `main()` executes:

```python
def main():
    logger.info(
        f"Starting {config.APP_NAME} v{config.VERSION} on {config.HOST}:{config.PORT} "
        f"[Branch: {get_health_status()['branch']}]"
    )
    print(f"Health Status: {get_health_status()}")
    print(f"System Info: {get_system_info()}")
```

The log statement claims to start the server listening on `{config.HOST}:{config.PORT}` (`0.0.0.0:8000`).
However, `main()` only prints two diagnostic dictionaries and immediately exits. No HTTP server, socket listener, or event loop is started.

---

## Impact Analysis

- **Confusing User / Container Logs**: Container supervisors or orchestration scripts running `python -m src.app` observe a startup log message but find the container process exiting immediately with code 0 without binding port 8000.

---

## Reproduction Scenario & Execution Proof

### Command Execution Trace
```bash
.venv/bin/python -m src.app
# Logs: [2026-08-25 ...] INFO in app: Starting Paleo-Workbench API v0.2.17a0 on 0.0.0.0:8000 ...
# Prints health status and immediately terminates.
```

---

## Concrete Suggested Fix

Clarify the log message to indicate diagnostic inspection mode, or integrate an ASGI runner if a web service is intended:

### Patch (`src/app.py`)
```python
def main():
    logger.info(
        f"Diagnostic inspect for {config.APP_NAME} v{config.VERSION} "
        f"(configured host: {config.HOST}:{config.PORT}) "
        f"[Branch: {get_health_status()['branch']}]"
    )
    print(f"Health Status: {get_health_status()}")
    print(f"System Info: {get_system_info()}")
```
