param([string]$QtRoot='C:/deps/Qt/6.8.0/msvc2022_64',[switch]$UnderGate,[switch]$Verify)
$ErrorActionPreference='Stop'
$nativeRoot=$PSScriptRoot
$repoRoot=[IO.Path]::GetFullPath((Join-Path $nativeRoot '../..'))
if (-not $UnderGate) {
    # This isolated one-TU prototype uses j1 and a 1.5 GiB admission floor.
    # The repository-wide lock still excludes concurrent heavy builds.
    $childArgs=@('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+$PSCommandPath+'"'),'-UnderGate','-QtRoot',('"'+$QtRoot+'"'))
    if ($Verify) { $childArgs+='-Verify' }
    & (Join-Path $repoRoot 'scripts/cpp-migration/Invoke-ResourceGate.ps1') -Action Exec -Jobs 1 -MinFreeGiB 1.5 -Command powershell.exe -CommandArguments ($childArgs -join ' ')
    exit $LASTEXITCODE
}
if ($env:PWB_GATE_HELD -ne '1') { throw 'Build must run through the shared resource gate.' }
$cmakeCommand=Get-Command cmake -ErrorAction SilentlyContinue
if ($cmakeCommand) { $cmakeBin=$cmakeCommand.Source }
else { $cmakeBin='C:/Program Files/Microsoft Visual Studio/2022/Community/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe' }
if (-not (Test-Path -LiteralPath $cmakeBin)) { throw 'CMake not found; add CMake to PATH.' }
if (-not (Test-Path -LiteralPath (Join-Path $QtRoot 'lib/cmake/Qt6/Qt6Config.cmake'))) { throw 'Qt Widgets 6.8+ SDK not found; supply -QtRoot.' }
$buildDir=Join-Path $nativeRoot 'build'
$env:CMAKE_BUILD_PARALLEL_LEVEL='1'
$env:CTEST_PARALLEL_LEVEL='1'
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
& $cmakeBin -S $nativeRoot -B $buildDir -G 'Visual Studio 17 2022' -A x64 "-DCMAKE_PREFIX_PATH=$QtRoot"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $cmakeBin --build $buildDir --config Release --parallel 1
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($Verify) {
    $env:PATH=(Join-Path $QtRoot 'bin')+';'+$env:PATH
    $env:QT_PLUGIN_PATH=Join-Path $QtRoot 'plugins'
    $env:QT_QPA_PLATFORM_PLUGIN_PATH=Join-Path $QtRoot 'plugins/platforms'
    $env:QT_QPA_PLATFORM='offscreen'
    & (Join-Path $buildDir 'Release/paleo-ribbon-prototype.exe') --self-test --output (Join-Path $nativeRoot 'evidence')
    exit $LASTEXITCODE
}
