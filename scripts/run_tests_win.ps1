# Windows PowerShell test runner for paleo-workbench + geo-viz-engine.
#
# Usage:
#   .\scripts\run_tests_win.ps1 workbench [pytest args...]
#   .\scripts\run_tests_win.ps1 engine    [pytest args...]
#   .\scripts\run_tests_win.ps1 native    [pytest args...]

[CmdletBinding()]
param(
    [Parameter(Position=0)]
    [ValidateSet("workbench", "engine", "native", "all")]
    [string]$Target = "workbench",

    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$EngineDir = Join-Path $RepoRoot "geo-viz-engine"

# Ensure Scripts folder is on PATH for cmake/ninja/pytest
# Derive the user Scripts dir from the active interpreter instead of
# hardcoding Python313 (pyproject pins <3.13; a hardcoded minor silently
# misses the pinned install's Scripts dir).
$PyUserScripts = python -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='nt_user'))" 2>$null
if (-not $PyUserScripts -or -not (Test-Path $PyUserScripts)) {
    $PyVer = python -c "import sys; print(f'Python{sys.version_info.major}{sys.version_info.minor}')" 2>$null
    if ($PyVer) { $PyUserScripts = Join-Path $env:APPDATA "$PyVer\Scripts" }
}
$UserScripts = $PyUserScripts
if (Test-Path $UserScripts) {
    $env:PATH = "$UserScripts;$env:PATH"
}

# Set headless Qt environment
$env:QT_QPA_PLATFORM = "offscreen"

Set-Location $RepoRoot

switch ($Target) {
    "workbench" {
        Write-Host "==> Running paleo-workbench test suite on Windows..." -ForegroundColor Cyan
        python -m pytest -p no:randomly --continue-on-collection-errors @PytestArgs
    }
    "native" {
        Write-Host "==> Running native C++ module verification tests..." -ForegroundColor Cyan
        python -m pytest tests/test_audit_native.py `
                         tests/test_grid_render_core_cpp.py `
                         tests/test_layer_model_core_cpp.py `
                         tests/test_seismic_3d_cpp.py `
                         tests/test_well_log_cpp.py `
                         tests/test_map_edit_core_cpp.py `
                         tests/test_native_compile_flags.py `
                         tests/test_workflow_integrity.py `
                         -v @PytestArgs
    }
    "engine" {
        Write-Host "==> Running geo-viz-engine tests on Windows..." -ForegroundColor Cyan
        Set-Location $EngineDir
        $pkgPaths = @($EngineDir)
        Get-ChildItem (Join-Path $EngineDir "packages") -Directory | ForEach-Object {
            $pkgPaths += $_.FullName
        }
        $env:PYTHONPATH = ($pkgPaths -join ";") + ";$env:PYTHONPATH"
        python -m pytest -p no:randomly tests packages/geoviz_well_seismic_3d/tests packages/geoviz_well_log/tests @PytestArgs
    }
    "all" {
        Write-Host "==> Running all Windows test suites..." -ForegroundColor Cyan
        & $PSCommandPath native
        & $PSCommandPath engine
        & $PSCommandPath workbench @PytestArgs
    }
}
