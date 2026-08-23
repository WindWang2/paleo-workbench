# Windows Build & Test Pipeline for paleo-workbench
# Builds all C++ extensions with MSVC, builds WellLogEngine C++ SDK, and runs test suites.

[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$BuildOnly
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

# Ensure Scripts folder is on PATH for cmake/ninja/pytest
$UserScripts = Join-Path $env:APPDATA "Python\Python313\Scripts"
if (Test-Path $UserScripts) {
    $env:PATH = "$UserScripts;$env:PATH"
}

# Auto-initialize Visual Studio MSVC environment if cl.exe is not on PATH
function Enter-VsDevEnvironment {
    if (Get-Command cl.exe -ErrorAction SilentlyContinue) { return }
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    $vsPath = if (Test-Path $vswhere) {
        & $vswhere -latest -property installationPath
    } else {
        "C:\Program Files\Microsoft Visual Studio\2022\Community"
    }
    $vcvars = Join-Path $vsPath "VC\Auxiliary\Build\vcvars64.bat"
    if (Test-Path $vcvars) {
        Write-Host "  -> Initializing MSVC environment from $vcvars..." -ForegroundColor Gray
        cmd /c "`"$vcvars`" >nul && set" | ForEach-Object {
            if ($_ -match "^(.*?)=(.*)$") {
                Set-Item -Force -Path "env:\$($matches[1])" -Value $matches[2]
            }
        }
    }
}

Enter-VsDevEnvironment

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Paleo Workbench Windows Build & Verification Pipeline   " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

Set-Location $RepoRoot

# 1. Build C++ native python extensions
Write-Host "`n[1/5] Building Native C++ Python Extensions with MSVC..." -ForegroundColor Green
$nativeDirs = @(
    "native\grid_render_core",
    "native\layer_model_core",
    "native\seismic_3d_core",
    "native\well_log_core",
    "geo-viz-engine\native\map_edit_core"
)

foreach ($dir in $nativeDirs) {
    $fullDir = Join-Path $RepoRoot $dir
    Write-Host "  -> Building $dir..." -ForegroundColor Gray
    python -m pip install --no-build-isolation --no-deps -e $fullDir
}

# 2. Compile standalone C++ selftest binaries
Write-Host "`n[2/5] Building & Executing Standalone C++ Selftest Executables..." -ForegroundColor Green
$binDir = Join-Path $RepoRoot "native\bin"
if (-not (Test-Path $binDir)) {
    New-Item -ItemType Directory -Path $binDir | Out-Null
}

$gridSelftestExe = Join-Path $binDir "grid_render_selftest.exe"
cl.exe /nologo /O2 /fp:fast /std:c++17 /utf-8 /EHsc `
    (Join-Path $RepoRoot "native\grid_render_core\src\standalone_test.cpp") `
    (Join-Path $RepoRoot "native\grid_render_core\src\grid_render_core.cpp") `
    (Join-Path $RepoRoot "native\grid_render_core\src\scalar_grid_layer.cpp") `
    /I (Join-Path $RepoRoot "native\grid_render_core\include") `
    /Fe:$gridSelftestExe
& $gridSelftestExe

$layerSelftestExe = Join-Path $binDir "layer_model_selftest.exe"
cl.exe /nologo /O2 /fp:fast /std:c++17 /utf-8 /EHsc `
    (Join-Path $RepoRoot "native\layer_model_core\src\standalone_test.cpp") `
    (Join-Path $RepoRoot "native\layer_model_core\src\layer_model.cpp") `
    /I (Join-Path $RepoRoot "native\layer_model_core\include") `
    /Fe:$layerSelftestExe
& $layerSelftestExe

# 3. Build WellLogEngine C++ SDK with CMake
Write-Host "`n[3/5] Building WellLogEngine C++ SDK & Running ctest..." -ForegroundColor Green
$welllogBuildDir = Join-Path $RepoRoot "well-log-engine\build"
cmake -S "$RepoRoot\well-log-engine" -B $welllogBuildDir -DWELLLOG_BUILD_TEXT=OFF -DWELLLOG_BUILD_TESTS=ON
cmake --build $welllogBuildDir --config Release --parallel 4
if (-not $SkipTests) {
    ctest --test-dir $welllogBuildDir -C Release --output-on-failure
}

# 4. Install geo-viz-engine packages & paleo-workbench
Write-Host "`n[4/5] Installing geo-viz-engine & paleo-workbench in editable mode..." -ForegroundColor Green
python -m pip install --no-deps -r requirements-geoviz.txt
python -m pip install --no-deps -e .

# 5. Run test verification
if (-not $SkipTests -and -not $BuildOnly) {
    Write-Host "`n[5/5] Running verification tests..." -ForegroundColor Green
    & "$ScriptDir\run_tests_win.ps1" native
}

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host "  All Windows builds and tests completed successfully!    " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
