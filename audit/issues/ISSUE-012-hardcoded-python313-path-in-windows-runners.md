# ISSUE-012: Hardcoded `Python313` Path in Windows Test/Build Runners

- **Severity**: High
- **Subproject**: `scripts` (`scripts/`)
- **Target File**:
  - `file:///home/kevin/projects/paleo_project/main/scripts/run_tests_win.ps1#L23-L27`
  - `file:///home/kevin/projects/paleo_project/main/scripts/build_and_test_windows.ps1#L14-L18`

---

## Defect Description & Root Cause Analysis

In `scripts/run_tests_win.ps1` and `scripts/build_and_test_windows.ps1`, the script resolution for Windows build dependencies contains a hardcoded Python 3.13 path:

```powershell
# Ensure Scripts folder is on PATH for cmake/ninja/pytest
$UserScripts = Join-Path $env:APPDATA "Python\Python313\Scripts"
if (Test-Path $UserScripts) {
    $env:PATH = "$UserScripts;$env:PATH"
}
```

This directly conflicts with the project's specification in `pyproject.toml:7` (`requires-python = ">=3.12,<3.13"`) and architectural governance policy (which standardizes on CPython 3.12).

---

## Impact Analysis

- **Windows Build / Test Failures**: On standard Windows development workstations running Python 3.12 without Python 3.13, `$UserScripts` resolves to a non-existent path. User-installed build and test utilities (`pytest.exe`, `ninja.exe`, `cmake.exe`) are not added to `$env:PATH`, causing subsequent commands to fail with command-not-found errors.
- **Environment Corruption**: On machines where Python 3.13 happens to be installed alongside Python 3.12, the runner executes Python 3.13 binaries inside a Python 3.12 environment, leading to ABI conflicts and module load errors.

---

## Reproduction Scenario & Execution Proof

### Reproduction Scenario
1. On a Windows 10/11 machine configured with Python 3.12, execute:
   ```powershell
   .\scripts\run_tests_win.ps1 workbench
   ```
2. `$env:PATH` contains `Python\Python313\Scripts` instead of the active Python 3.12 Scripts folder.

---

## Concrete Suggested Fix

Query the active Python interpreter dynamically using `sysconfig.get_path('scripts')`:

### Patch (`scripts/run_tests_win.ps1` & `scripts/build_and_test_windows.ps1`)
```powershell
# Query active Python environment scripts directory dynamically
$pyScripts = python -c "import sysconfig; print(sysconfig.get_path('scripts'))" 2>$null
if ($pyScripts -and (Test-Path $pyScripts)) {
    $env:PATH = "$pyScripts;$env:PATH"
}
```
