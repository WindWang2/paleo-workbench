# Build the vendored QGIS core/gui/analysis + the qgis_render_bridge extension.
#
# Windows-only. Idempotent: cmake configure is cached and Ninja resumes, so a
# failed run can simply be re-launched.
#
#   powershell -File scripts\build-qgis-bridge.ps1 -Jobs 8
#   powershell -File scripts\build-qgis-bridge.ps1 -ConfigureOnly   # fast gate
#   powershell -File scripts\build-qgis-bridge.ps1 -Clean           # wipe + full
#
# Requires (all verified present on this machine):
#   - Visual Studio 2022 Community (x64 native tools) + Windows SDK 10.0.22621.0
#   - C:\deps\Qt\6.8.0\msvc2022_64        (Qt 6.8.0 dev prefix)
#   - C:\deps\vcpkg\installed\x64-windows (gdal / geos / proj / protobuf / ...)
#   - C:\deps\{qca-install,kc-install,qscintilla-install,winflexbison}
#   - project .venv with pybind11
#
# NOTE: reg.exe is on the command blacklist on this machine, so the standard
# vcvars64.bat / Enter-VsDevShell route cannot discover the Windows SDK. The
# MSVC + SDK environment is assembled manually below instead.

param(
    [int]$Jobs = 8,
    [switch]$ConfigureOnly,
    [switch]$SkipBridge,
    [switch]$Clean
)

$ErrorActionPreference = "Continue"
$root = "C:\Users\wangj.KEVIN\projects\paleo-workbench"
$log = "$root\.workbuddy\qgis_build.log"

function Log([string]$m) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  $m" | Out-File $log -Append -Encoding utf8
}

"" | Out-File $log -Encoding utf8
Log "=== QGIS bridge build START (jobs=$Jobs configureOnly=$ConfigureOnly skipBridge=$SkipBridge clean=$Clean) ==="

# ---------------------------------------------------------------- 1. VS x64
#
# NOTE: Enter-VsDevShell / vcvars64.bat are deliberately NOT used here. They
# shell out to `reg.exe` to locate the Windows SDK, and reg.exe is on this
# machine's command blacklist, so the SDK bin dir (rc.exe / mt.exe) silently
# never reaches PATH -> CMake fails its compiler sanity check with
# "RC Pass 1: ... failed" + "--mt=CMAKE_MT-NOTFOUND".
#
# Instead the MSVC + Windows SDK environment is assembled from known paths.
# Bump $msvcVer / $sdkVer if the toolchain is upgraded.
$vs = "C:\Program Files\Microsoft Visual Studio\2022\Community"
$msvcVer = "14.38.33130"
$sdkVer = "10.0.22621.0"
$msvcRoot = "$vs\VC\Tools\MSVC\$msvcVer"
$sdkRoot = "C:\Program Files (x86)\Windows Kits\10"
$hostBin = "$msvcRoot\bin\Hostx64\x64"
$sdkBin = "$sdkRoot\bin\$sdkVer\x64"

foreach ($p in @("$hostBin\cl.exe", "$hostBin\link.exe", "$sdkBin\rc.exe", "$sdkBin\mt.exe")) {
    if (-not (Test-Path $p)) { Log "FATAL toolchain piece missing: $p"; exit 2 }
}

$env:PATH = "$hostBin;$sdkBin;$env:PATH"
$env:INCLUDE = @(
    "$msvcRoot\include"
    "$msvcRoot\ATLMFC\include"
    "$sdkRoot\Include\$sdkVer\ucrt"
    "$sdkRoot\Include\$sdkVer\shared"
    "$sdkRoot\Include\$sdkVer\um"
    "$sdkRoot\Include\$sdkVer\winrt"
    "$sdkRoot\Include\$sdkVer\cppwinrt"
) -join ";"
$env:LIB = @(
    "$msvcRoot\lib\x64"
    "$msvcRoot\ATLMFC\lib\x64"
    "$sdkRoot\Lib\$sdkVer\ucrt\x64"
    "$sdkRoot\Lib\$sdkVer\um\x64"
    # Needed later by the bridge link: setup.py requests `gdal` + `proj` by
    # bare name and only supplies the Qt / QScintilla dirs, so the linker must
    # already find them via LIB.
    "C:\deps\vcpkg\installed\x64-windows\lib"
    "C:\deps\Qt\6.8.0\msvc2022_64\lib"
    "C:\deps\qscintilla-install\lib"
) -join ";"
$env:LIBPATH = "$msvcRoot\lib\x64"
Log "cl.exe  = $hostBin\cl.exe"
Log "rc.exe  = $sdkBin\rc.exe"
Log "mt.exe  = $sdkBin\mt.exe"

# ------------------------------------------------------------ 2. cmake/ninja
$cmakeBin = "$vs\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin"
$ninjaBin = "$vs\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja"
$env:PATH = "$cmakeBin;$ninjaBin;$env:PATH"
if (-not (Get-Command cmake.exe -ErrorAction SilentlyContinue)) { Log "FATAL cmake missing"; exit 4 }
if (-not (Get-Command ninja.exe -ErrorAction SilentlyContinue)) { Log "FATAL ninja missing"; exit 5 }
Log "cmake   = $((Get-Command cmake.exe).Source)"
Log "ninja   = $((Get-Command ninja.exe).Source)"

# --------------------------------------------------- 3. environment for build
#
# Two distinct prefixes are in play:
#   - Qt 6.8.0 dev prefix  (Qt6* headers/.lib, QScintilla, QCA, qt6keychain)
#   - vcpkg x64-windows    (gdal / geos / proj / protobuf / sqlite3 / ...)
# Both must be discoverable by find_package(). setup.py can only forward ONE
# prefix (`PALEO_QGIS_CMAKE_PREFIX`), so the combined list is supplied through
# the CMAKE_PREFIX_PATH *environment variable* (cmake reads it natively, and it
# sidesteps PowerShell `;`-quoting hazards). PALEO_QGIS_CMAKE_PREFIX stays on
# Qt alone because setup.py takes its first entry for the binding's include and
# library dirs.
$qtPrefix = "C:/deps/Qt/6.8.0/msvc2022_64"
$vcPrefix = "C:/deps/vcpkg/installed/x64-windows"
# Qt6Keychain (auth) and QCA (crypto) ship their own CMake config packages in
# separate install prefixes; qscintilla is included for parity.
$kcPrefix = "C:/deps/kc-install"
$qcaPrefix = "C:/deps/qca-install"
$qscPrefix = "C:/deps/qscintilla-install"
$env:PALEO_WITH_QGIS_RENDERER = "1"
$env:PALEO_QGIS_CMAKE_PREFIX = $qtPrefix
$env:CMAKE_PREFIX_PATH = "$qtPrefix;$vcPrefix;$kcPrefix;$qcaPrefix;$qscPrefix"
$env:PROJ_DATA = "C:/deps/vcpkg/installed/x64-windows/share/proj"
$env:PALEO_QGIS_BUILD_JOBS = "$Jobs"

$src = "$root\third_party\qgis"
$buildDir = "$root\native\qgis_render_bridge\build\qgis-vendor"
Log "source  = $src"
Log "build   = $buildDir"
Log "qtPrefix= $qtPrefix"
Log "vcPrefix= $vcPrefix"
Log "PREFIX_PATH(env) = $env:CMAKE_PREFIX_PATH"

# ------------------------------------------------------------- 4. configure
$cfg = @(
    "-S", $src, "-B", $buildDir, "-G", "Ninja"
    "-DCMAKE_BUILD_TYPE=Release"
    "-DWITH_PYTHON=OFF", "-DWITH_BINDINGS=OFF", "-DWITH_DESKTOP=OFF"
    "-DWITH_QGIS_PROCESS=OFF", "-DWITH_3D=OFF", "-DWITH_GUI=ON"
    "-DWITH_ANALYSIS=ON", "-DWITH_AUTH=ON", "-DWITH_CRASH_HANDLER=OFF"
    "-DWITH_SERVER=OFF", "-DWITH_CUSTOM_WIDGETS=OFF", "-DWITH_QUICK=OFF"
    "-DWITH_QTWEBENGINE=OFF", "-DWITH_QTPOSITIONING=OFF", "-DWITH_PDAL=OFF"
    "-DWITH_DRACO=OFF", "-DWITH_QTSERIALPORT=OFF"
    "-DWITH_INTERNAL_SPATIALINDEX=ON", "-DUSE_OPENCL=OFF", "-DENABLE_TESTS=OFF"
    "-DENABLE_LOCAL_BUILD_SHORTCUTS=ON", "-DUSE_CCACHE=OFF"
    "-DCMAKE_FIND_USE_PACKAGE_REGISTRY=FALSE"
    "-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=FALSE"
    # Windows-only: no MSVC packages for these providers in the C:/deps tree.
    "-DWITH_INTERNAL_SPATIALITE=ON", "-DWITH_SPATIALITE=OFF"
    "-DWITH_POSTGRESQL=OFF", "-DWITH_EXIV2=OFF"
    "-DFLEX_EXECUTABLE=C:/deps/winflexbison/win_flex.exe"
    "-DBISON_EXECUTABLE=C:/deps/winflexbison/win_bison.exe"
    "-DProtobuf_LIBRARY=C:/deps/vcpkg/installed/x64-windows/lib/libprotobuf.lib"
    "-DProtobuf_INCLUDE_DIR=C:/deps/vcpkg/installed/x64-windows/include"
    "-DProtobuf_PROTOC_EXECUTABLE=C:/deps/vcpkg/installed/x64-windows/tools/protobuf/protoc.exe"
    # NOTE: no -DCMAKE_PREFIX_PATH here on purpose — it would override the
    # combined Qt+vcpkg CMAKE_PREFIX_PATH environment variable with Qt alone.
    # Explicit, because the SDK bin dir reachability is exactly the thing that
    # broke the first attempt; do not leave it to PATH luck.
    ("-DCMAKE_RC_COMPILER=" + ($sdkBin -replace "\\", "/") + "/rc.exe")
    ("-DCMAKE_MT=" + ($sdkBin -replace "\\", "/") + "/mt.exe")
)
if ($Clean -and (Test-Path $buildDir)) {
    Log ">>> -Clean: removing $buildDir"
    Remove-Item $buildDir -Recurse -Force -ErrorAction SilentlyContinue
}
Log ">>> cmake CONFIGURE"
& cmake @cfg 2>&1 | Tee-Object -FilePath $log -Append | Out-Null
$rc = $LASTEXITCODE
Log ">>> configure rc=$rc"
if ($rc -ne 0) { Log "CONFIGURE FAILED - see log above"; exit 10 }
Log "CONFIGURE OK"
if ($ConfigureOnly) { Log "configureOnly requested -> stop here"; exit 0 }

# ----------------------------------------------------------------- 5. build
Log ">>> cmake BUILD --parallel $Jobs  (hours; Ninja resumes on re-run)"
& cmake --build $buildDir `
    --target resources qgis_core qgis_gui qgis_analysis `
    --parallel $Jobs 2>&1 | Tee-Object -FilePath $log -Append | Out-Null
$rc2 = $LASTEXITCODE
Log ">>> vendor build rc=$rc2"
if ($rc2 -ne 0) { Log "VENDOR BUILD FAILED"; exit 11 }
Log "VENDOR BUILD OK"

$libDir = "$buildDir\output\lib"
foreach ($f in @("qgis_core.lib", "qgis_gui.lib", "qgis_analysis.lib")) {
    if (Test-Path "$libDir\$f") { Log "ARTIFACT OK      $f" } else { Log "ARTIFACT MISSING $f" }
}
if (Test-Path "$buildDir\resources\srs.db") { Log "ARTIFACT OK      srs.db" }
else { Log "ARTIFACT MISSING srs.db" }

# --------------------------------- 5b. make the vendor runtime self-contained
#
# loader.py's default VENDOR recipe is documented as "vendor/output/bin carries
# every third-party runtime the QGIS DLLs need; the process Qt is PySide6's own
# wheel copy (single-Qt rule). Loader: MSVCP pre-pin + [vendor_bin, pyside_dir]".
# Our build links against C:/deps prefixes, so those DLLs must be collected into
# output/bin or the bridge import dies with ERROR_MOD_NOT_FOUND.
#
# Two groups on purpose:
#   1. every non-debug DLL from the geo/crypto prefixes (gdal, proj_9, geos_c,
#      sqlite3, zlib, libexpat, zstd, curl, tiff, ... , qca-qt6, qt6keychain,
#      qscintilla2_qt6);
#   2. ONLY the Qt modules PySide6 does not ship (notably Qt6Core5Compat.dll) —
#      everything else must keep resolving to PySide6's copy, per the single-Qt
#      rule. Copying all of deps' Qt would let a second Qt "home" directory win
#      the plugin lookup (qt.conf / plugins/) and break the QPA platform plugin.
$vendorBin = "$buildDir\output\bin"
$pysideDir = (Get-ChildItem "$root\.venv\Lib\site-packages" -Directory -Filter "PySide6" -ErrorAction SilentlyContinue | Select-Object -First 1).FullName
if (-not $pysideDir) { Log "WARN PySide6 dir not found; skipping Qt-gap copy" }
$copiedGeo = 0
$copiedQt = 0

# MSVC debug DLLs (Qt6Cored.dll, gdald.dll, ...) must not ship. Detect them as
# "name ends in d AND the same dir also has the d-less twin" — NOT by a bare
# `d\.dll$` regex, which wrongly discards legitimate release libraries such as
# zstd.dll (that exact mistake cost a full DEBUG of ERROR_MOD_NOT_FOUND: the
# missing module was zstd.dll, a direct import of qgis_core.dll).
function Copy-ReleaseDlls([string]$src, [ref]$counter) {
    if (-not (Test-Path $src)) { Log "WARN missing DLL source: $src"; return }
    $files = @(Get-ChildItem $src -File -Filter "*.dll" -ErrorAction SilentlyContinue)
    $names = @($files | Select-Object -ExpandProperty Name)
    foreach ($f in $files) {
        $isDebugTwin = $false
        if ($f.BaseName -match "d$") {
            $twin = $f.BaseName.Substring(0, $f.BaseName.Length - 1) + ".dll"
            if ($names -contains $twin) { $isDebugTwin = $true }
        }
        if ($isDebugTwin) { continue }
        Copy-Item $f.FullName -Destination $vendorBin -Force
        $counter.Value++
    }
}

Log ">>> collecting runtime DLLs into output/bin"
foreach ($src in @(
    "C:\deps\vcpkg\installed\x64-windows\bin",
    "C:\deps\kc-install\bin",
    "C:\deps\qca-install\bin",
    "C:\deps\qscintilla-install\bin"
)) {
    Copy-ReleaseDlls $src ([ref]$copiedGeo)
}
if ($pysideDir) {
    $qtFiles = @(Get-ChildItem "$qtPrefix\bin" -File -Filter "*.dll" -ErrorAction SilentlyContinue)
    $qtNames = @($qtFiles | Select-Object -ExpandProperty Name)
    foreach ($f in $qtFiles) {
        $isDebugTwin = $false
        if ($f.BaseName -match "d$") {
            $twin = $f.BaseName.Substring(0, $f.BaseName.Length - 1) + ".dll"
            if ($qtNames -contains $twin) { $isDebugTwin = $true }
        }
        if ($isDebugTwin) { continue }
        if (Test-Path (Join-Path $pysideDir $f.Name)) { continue }
        Copy-Item $f.FullName -Destination $vendorBin -Force
        $copiedQt++
    }
}
Log "    geo/crypto DLLs copied : $copiedGeo"
Log "    Qt-gap DLLs copied     : $copiedQt  (modules PySide6 lacks)"
Log "    output/bin total       : $((Get-ChildItem $vendorBin -File | Measure-Object).Count) files"

# 3. PROJ data. paths.py resolves vendor_proj_data as
#    <vendor_root>/output/share/proj, which a Windows vendor build does not
#    produce — the vendored proj_9.dll then reports
#    "proj_get_authorities_from_database: Cannot find proj.db" and every CRS
#    lookup degrades to "unknown CRS". Copy the data next to the DLLs.
$projSrc = "C:\deps\vcpkg\installed\x64-windows\share\proj"
$projDst = "$buildDir\output\share\proj"
if (Test-Path "$projSrc\proj.db") {
    New-Item -ItemType Directory -Force -Path $projDst | Out-Null
    Copy-Item "$projSrc\*" -Destination $projDst -Recurse -Force
    Log "    PROJ data copied       : $projDst ($((Get-ChildItem $projDst -File -Recurse | Measure-Object).Count) files)"
} else {
    Log "WARN PROJ data not found at $projSrc (proj.db lookups will degrade)"
}

# ------------------------------------------------- 6. compile the .pyd bridge
if ($SkipBridge) { Log "skipBridge -> done"; exit 0 }

Log ">>> uv pip install -e native/qgis_render_bridge"
$uv = "C:\Users\wangj.KEVIN\.local\bin\uv.exe"
& $uv pip install --python "$root\.venv\Scripts\python.exe" `
    --no-build-isolation `
    -e "$root\native\qgis_render_bridge" 2>&1 | Tee-Object -FilePath $log -Append | Out-Null
$rc3 = $LASTEXITCODE
Log ">>> bridge install rc=$rc3"
if ($rc3 -ne 0) { Log "BRIDGE BUILD FAILED"; exit 12 }
Log "BRIDGE BUILD OK"
Log "=== ALL DONE ==="
exit 0
