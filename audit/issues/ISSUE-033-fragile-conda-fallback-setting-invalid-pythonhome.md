# ISSUE-033: Fragile Conda Fallback Setting Invalid `PYTHONHOME` in `run_tests.sh`

- **Severity**: Low
- **Subproject**: `scripts` (`scripts/run_tests.sh`)
- **Target File**: `file:///home/kevin/projects/paleo_project/main/scripts/run_tests.sh#L19-L33`

---

## Defect Description & Root Cause Analysis

In `scripts/run_tests.sh`, the test runner initializes Conda environment variables:

```bash
if [ -z "${PALEO_CONDA_PREFIX:-}" ]; then
    for candidate in "$HOME/.conda/envs/paleo312" /opt/miniconda3/envs/paleo312; do
        if [ -x "$candidate/bin/python" ]; then
            PALEO_CONDA_PREFIX="$candidate"
            break
        fi
    done
fi
export CONDA_PREFIX="${PALEO_CONDA_PREFIX:-/opt/miniconda3}"
export PYTHONHOME="$CONDA_PREFIX"
export PATH="$CONDA_PREFIX/bin:$PATH"
```

If neither candidate directory exists, `CONDA_PREFIX` unconditionally defaults to `/opt/miniconda3` and exports `PYTHONHOME="/opt/miniconda3"`.

On standard Linux systems where `/opt/miniconda3` does not exist (e.g. running in standard `.venv` virtualenvs or user-level Conda installed in `~/miniconda3`), setting `PYTHONHOME` to a non-existent directory corrupts the Python standard library discovery mechanism, causing:
`Fatal Python error: init_fs_encoding: failed to get the Python codec of the filesystem encoding` or `No module named 'encodings'`.

---

## Impact Analysis

- **Test Runner Failure**: Running `scripts/run_tests.sh` fails on any system lacking `/opt/miniconda3`.

---

## Reproduction Scenario & Execution Proof

### Command Execution Trace
```bash
PALEO_CONDA_PREFIX=/nonexistent scripts/run_tests.sh workbench
# Output:
# Fatal Python error: init_fs_encoding: failed to get the Python codec of the filesystem encoding
# Python runtime cannot start due to invalid PYTHONHOME.
```

---

## Concrete Suggested Fix

Only export `PYTHONHOME` and alter `PATH` if a valid interpreter executable was located; otherwise retain the active Python environment:

### Patch (`scripts/run_tests.sh`)
```bash
if [ -n "${PALEO_CONDA_PREFIX:-}" ] && [ -x "$PALEO_CONDA_PREFIX/bin/python" ]; then
    export CONDA_PREFIX="$PALEO_CONDA_PREFIX"
    export PYTHONHOME="$CONDA_PREFIX"
    export PATH="$CONDA_PREFIX/bin:$PATH"
fi
```
