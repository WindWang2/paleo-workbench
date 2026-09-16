# CPP-A platform build wrapper: assembles the MSVC/SDK environment (reg.exe
# is blacklisted on this machine, so vcvars is not usable) and delegates the
# heavy action to the shared resource gate (one slot, 2 jobs, >=8 GiB).
# Run from the platform worktree root.
#
#   powershell -File scripts/cpp-migration/Invoke-PlatformBuild.ps1 -Action Probe
#   powershell -File scripts/cpp-migration/Invoke-PlatformBuild.ps1 -Action Configure
#   powershell -File scripts/cpp-migration/Invoke-PlatformBuild.ps1 -Action Build
#   powershell -File scripts/cpp-migration/Invoke-PlatformBuild.ps1 -Action Test -TestRegex '^platform\.'
[CmdletBinding()]
param(
    [ValidateSet('Probe', 'Configure', 'Build', 'Test')]
    [string]$Action = 'Probe',
    [string]$Configuration = 'Debug',
    [string]$TestRegex = '^platform\.'
)

$ErrorActionPreference = 'Stop'

$vs = 'C:\Program Files\Microsoft Visual Studio\2022\Community'
$msvcVer = '14.38.33130'
$sdkVer = '10.0.22621.0'
$msvcRoot = "$vs\VC\Tools\MSVC\$msvcVer"
$sdkRoot = 'C:\Program Files (x86)\Windows Kits\10'
$hostBin = "$msvcRoot\bin\Hostx64\x64"
$sdkBin = "$sdkRoot\bin\$sdkVer\x64"
$cmakeBin = "$vs\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin"
$ninjaBin = "$vs\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja"

foreach ($piece in @("$hostBin\cl.exe", "$sdkBin\rc.exe",
                     "$cmakeBin\cmake.exe", "$ninjaBin\ninja.exe")) {
    if (-not (Test-Path $piece)) { throw "toolchain piece missing: $piece" }
}

$env:PATH = "$hostBin;$sdkBin;$cmakeBin;$ninjaBin;$env:PATH"
$env:INCLUDE = @(
    "$msvcRoot\include", "$msvcRoot\ATLMFC\include",
    "$sdkRoot\Include\$sdkVer\ucrt", "$sdkRoot\Include\$sdkVer\shared",
    "$sdkRoot\Include\$sdkVer\um", "$sdkRoot\Include\$sdkVer\winrt",
    "$sdkRoot\Include\$sdkVer\cppwinrt"
) -join ';'
$env:LIB = @(
    "$msvcRoot\lib\x64", "$msvcRoot\ATLMFC\lib\x64",
    "$sdkRoot\Lib\$sdkVer\ucrt\x64", "$sdkRoot\Lib\$sdkVer\um\x64"
) -join ';'

$gate = Join-Path $PSScriptRoot 'Invoke-ResourceGate.ps1'
$common = @('-Configuration', $Configuration)
switch ($Action) {
    'Probe'     { & $gate -Action Probe; $code = $LASTEXITCODE }
    'Configure' { & $gate -Action Configure -SourceDir . -BuildDir ./build/cpp-platform @common
                  $code = $LASTEXITCODE }
    'Build'     { & $gate -Action Build -BuildDir ./build/cpp-platform @common
                  $code = $LASTEXITCODE }
    'Test'      { & $gate -Action Test -BuildDir ./build/cpp-platform @common -TestRegex $TestRegex
                  $code = $LASTEXITCODE }
}
exit $code
