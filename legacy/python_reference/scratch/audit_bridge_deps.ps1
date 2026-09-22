# Find which DLL(s) in the QGIS runtime dependency closure cannot be resolved
# from the search path the app actually provides: [vendor_bin, PySide6] + System32.
$ErrorActionPreference = "Continue"
$root = "C:\Users\wangj.KEVIN\projects\paleo-workbench"
$dst = "$root\.workbuddy\dep_audit.txt"
"" | Out-File $dst -Encoding utf8

$dumpbin = "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.38.33130\bin\Hostx64\x64\dumpbin.exe"
$vendorBin = "$root\native\qgis_render_bridge\build\qgis-vendor\output\bin"
$pysideDir = "$root\.venv\Lib\site-packages\PySide6"
$sys32 = "C:\Windows\System32"

$searchDirs = @($vendorBin, $pysideDir, $sys32)
Add-Content $dst ("search dirs: " + ($searchDirs -join " | "))
Add-Content $dst ""

function Get-Dependent([string]$dllPath) {
    $out = & $dumpbin /nologo /dependents $dllPath 2>&1
    $names = @()
    $inBlock = $false
    foreach ($line in $out) {
        if ($line -match "Image has the following dependencies") { $inBlock = $true; continue }
        if ($inBlock) {
            if ($line -match "Summary") { break }
            $t = $line.Trim()
            if ($t -match "^\S+\.dll$") { $names += $t }
        }
    }
    return $names
}

$targets = @(
    "$vendorBin\qgis_core.dll",
    "$vendorBin\qgis_gui.dll",
    "$vendorBin\qgis_analysis.dll",
    "$root\native\qgis_render_bridge\qgis_render_bridge.cp312-win_amd64.pyd"
)

$missing = @{}
foreach ($t in $targets) {
    if (-not (Test-Path $t)) { Add-Content $dst "SKIP (absent): $t"; continue }
    $deps = Get-Dependent $t
    Add-Content $dst ("--- " + (Split-Path $t -Leaf) + " : " + $deps.Count + " direct imports ---")
    foreach ($d in $deps) {
        $found = $null
        foreach ($dir in $searchDirs) {
            if (Test-Path (Join-Path $dir $d)) { $found = $dir; break }
        }
        if (-not $found) {
            Add-Content $dst ("  MISSING  $d")
            if ($missing.ContainsKey($d)) { $missing[$d] += 1 } else { $missing[$d] = 1 }
        }
    }
}

Add-Content $dst ""
Add-Content $dst "=== union of unresolved direct imports ==="
if ($missing.Count -eq 0) { Add-Content $dst "(none - closure satisfied at depth 1)" }
foreach ($k in ($missing.Keys | Sort-Object)) { Add-Content $dst ("  $k  (referenced by $($missing[$k]) target(s))") }
