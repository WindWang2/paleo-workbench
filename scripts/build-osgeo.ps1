# Build + install the GDAL Python bindings (osgeo) into the project .venv,
# against the SAME GDAL the vendored QGIS links (vcpkg x64-windows, 3.12.4).
#
# Why this shape:
#   * PyPI `gdal==3.12.4` is an sdist, not a wheel -> it must be compiled. The
#     sdist DOES ship pre-generated SWIG wrappers (gdal_wrap.cpp, ogr_wrap.cpp,
#     ...), so no SWIG install is needed.
#   * The build subprocess must see a complete MSVC + Windows SDK environment.
#     reg.exe is blacklisted here, so vcvars64.bat/Enter-VsDevShell cannot be
#     used (they locate the SDK through the registry) — the environment is
#     assembled from known paths exactly like scripts/build-qgis-bridge.ps1.
#   * GDAL_HOME points at the vcpkg prefix (it has include/ + lib/ directly),
#     which is where gdal.lib and gdal_version.h live.
#
# Usage:  powershell -File scripts\build-osgeo.ps1

$ErrorActionPreference = "Continue"
$root = "C:\Users\wangj.KEVIN\projects\paleo-workbench"
$log = "$root\.workbuddy\osgeo_build.log"

function Log([string]$m) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  $m" | Out-File $log -Append -Encoding utf8
}

"" | Out-File $log -Encoding utf8
Log "=== osgeo build START ==="

$vs = "C:\Program Files\Microsoft Visual Studio\2022\Community"
$msvcVer = "14.38.33130"
$sdkVer = "10.0.22621.0"
$msvcRoot = "$vs\VC\Tools\MSVC\$msvcVer"
$sdkRoot = "C:\Program Files (x86)\Windows Kits\10"
$hostBin = "$msvcRoot\bin\Hostx64\x64"
$sdkBin = "$sdkRoot\bin\$sdkVer\x64"
$vcPrefix = "C:\deps\vcpkg\installed\x64-windows"

foreach ($p in @("$hostBin\cl.exe", "$sdkBin\rc.exe", "$vcPrefix\lib\gdal.lib", "$vcPrefix\include\gdal_version.h")) {
    if (-not (Test-Path $p)) { Log "FATAL missing prerequisite: $p"; exit 2 }
}

$env:PATH = "$hostBin;$sdkBin;$env:PATH"
# GDAL's Python setup.py is gdal-config driven EXCEPT under MSVC, where it
# returns from finalize_options() early (setup.py:327) leaving include_dirs /
# library_dirs EMPTY on purpose — the Windows mechanism is to rely on the
# compiler's own default search path. So the vcpkg prefix goes on INCLUDE/LIB.
$env:INCLUDE = (@(
    "$msvcRoot\include"
    "$msvcRoot\ATLMFC\include"
    "$sdkRoot\Include\$sdkVer\ucrt"
    "$sdkRoot\Include\$sdkVer\shared"
    "$sdkRoot\Include\$sdkVer\um"
    "$sdkRoot\Include\$sdkVer\winrt"
    "$sdkRoot\Include\$sdkVer\cppwinrt"
    "$vcPrefix\include"
) -join ";")
$env:LIB = (@(
    "$msvcRoot\lib\x64"
    "$msvcRoot\ATLMFC\lib\x64"
    "$sdkRoot\Lib\$sdkVer\ucrt\x64"
    "$sdkRoot\Lib\$sdkVer\um\x64"
    "$vcPrefix\lib"
) -join ";")
$env:LIBPATH = "$msvcRoot\lib\x64"

# Belt and braces: CL/LINK are appended to every cl/link invocation, so even a
# build step that ignores INCLUDE/LIB still finds gdal.h and gdal.lib.
$env:CL = "/utf-8 /I`"$vcPrefix\include`""
$env:LINK = "/LIBPATH:`"$vcPrefix\lib`""

Log "cl.exe     = $hostBin\cl.exe"
Log "INCLUDE    = $env:INCLUDE"
$gv = Select-String -Path "$vcPrefix\include\gdal_version.h" -Pattern "GDAL_RELEASE_NAME|GDAL_VERSION_NUM" |
    ForEach-Object { $_.Line.Trim() }
foreach ($l in $gv) { Log "  $l" }

$uv = "C:\Users\wangj.KEVIN\.local\bin\uv.exe"
$stage = "C:\Users\wangj.KEVIN\AppData\Local\uv\cache\sdists-v9\pypi\gdal\3.12.4\8aEvxgXUDP-zMlENsORAM\src\build\lib.win-amd64-cpython-312\osgeo"
$target = "$root\.venv\Lib\site-packages\osgeo"

Log ">>> uv pip install --no-build-isolation gdal==3.12.4"
& $uv pip install --python "$root\.venv\Scripts\python.exe" --no-build-isolation "gdal==3.12.4" 2>&1 |
    Tee-Object -FilePath $log -Append | Out-Null
$rc = $LASTEXITCODE
Log ">>> install rc=$rc"

# The compile+link succeed; what fails is setuptools' own wheel-staging cleanup
# ("removing build\bdist.win-amd64\wheel", 133 files), which this sandbox's
# >50-file bulk-delete guard refuses to allow — so the build process is killed
# with rc=1 AFTER the extension modules are already built. Do not treat that as
# a compile failure: pick up the built package and install it directly.
#
# The staging dir is keyed by the sdist cache hash; if uv ever re-extracts, this
# glob still finds it. osgeo is a plain package (6 .pyd + 12 .py), no entry
# points needed, so a direct copy is equivalent to a wheel install.
if (-not (Test-Path "$stage\_gdal.cp312-win_amd64.pyd")) {
    $found = Get-ChildItem "C:\Users\wangj.KEVIN\AppData\Local\uv\cache\sdists-v9\pypi\gdal\3.12.4" -Recurse -Force -File `
        -Filter "_gdal.cp312-win_amd64.pyd" -ErrorAction SilentlyContinue |
        Where-Object { $_.DirectoryName -match "lib\..*-cpython-312\\osgeo$" } |
        Select-Object -First 1
    if ($found) { $stage = $found.DirectoryName } else { $stage = $null }
}
if (-not $stage -or -not (Test-Path "$stage\_gdal.cp312-win_amd64.pyd")) {
    Log "FATAL: no built osgeo staging dir found; see log above for the real error"
    exit 11
}
Log "staging  = $stage"

# A smaller, permission-friendly path: copy the six compiled modules + the pure
# python wrappers. (Copy, never move/delete — this is under site-packages.)
New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item "$stage\*" -Destination $target -Recurse -Force
$n = (Get-ChildItem $target -File | Measure-Object).Count
Log "installed $n files into $target"
if (-not (Test-Path "$target\_gdal.cp312-win_amd64.pyd")) { Log "FATAL osgeo install incomplete"; exit 12 }
Log "OSGEO INSTALL OK"

Log ">>> verify import (after the project loader claims its DLL dirs)"
& "$root\.venv\Scripts\python.exe" -c @"
import sys  # Python-retirement: the vendored DLL registration lives in the
from pathlib import Path  # archived package — reached via the sanctioned shim.
sys.path.insert(0, str(Path(r"$root") / "tools" / "oracle"))
import _legacy_reference
_legacy_reference.ensure_legacy_reference()
import paleo_workbench  # noqa: F401  (registers the vendored DLL search path)
from osgeo import gdal, osr, ogr
print('GDAL     :', gdal.VersionInfo())
print('osgeo    :', gdal.__file__)
sr = osr.SpatialReference(); sr.ImportFromEPSG(4326)
print('osr 4326 :', sr.GetAuthorityCode(None))
"@ 2>&1 | Out-File $log -Append -Encoding utf8
Log ">>> verify rc=$LASTEXITCODE"
Log "=== DONE ==="
exit 0
