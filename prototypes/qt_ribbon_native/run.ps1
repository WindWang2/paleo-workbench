param([string]$QtRoot='C:/deps/Qt/6.8.0/msvc2022_64',[string]$Capture='')
$ErrorActionPreference='Stop'
$exe=Join-Path $PSScriptRoot 'build/Release/paleo-ribbon-prototype.exe'
if (-not (Test-Path -LiteralPath $exe)) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'build.ps1') -QtRoot $QtRoot
    if ($LASTEXITCODE -ne 0) { throw "Build did not complete (exit $LASTEXITCODE)." }
}
$env:PATH=(Join-Path $QtRoot 'bin')+';'+$env:PATH
$env:QT_PLUGIN_PATH=Join-Path $QtRoot 'plugins'
$env:QT_QPA_PLATFORM_PLUGIN_PATH=Join-Path $QtRoot 'plugins/platforms'
$env:QT_QPA_PLATFORM='windows'
# The user requested a visible, interactive native Qt window.
if ($Capture) {
    Start-Process -FilePath $exe -ArgumentList @('--capture',('"'+$Capture+'"')) -WorkingDirectory $PSScriptRoot -WindowStyle Normal
} else {
    Start-Process -FilePath $exe -WorkingDirectory $PSScriptRoot -WindowStyle Normal
}
