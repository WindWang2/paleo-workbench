# Diagnostic: what does Enter-VsDevShell actually put on PATH / INCLUDE / LIB?
$dst = "C:\Users\wangj.KEVIN\projects\paleo-workbench\.workbuddy\build_preflight.txt"
"" | Out-File $dst -Encoding utf8

$vs = "C:\Program Files\Microsoft Visual Studio\2022\Community"
Add-Content $dst "=== BEFORE ==="
Add-Content $dst ("rc on PATH? " + [bool](Get-Command rc.exe -ErrorAction SilentlyContinue))
Add-Content $dst ("mt on PATH? " + [bool](Get-Command mt.exe -ErrorAction SilentlyContinue))

Import-Module "$vs\Common7\Tools\Microsoft.VisualStudio.DevShell.dll"
Enter-VsDevShell -VsInstallPath $vs -SkipAutomaticLocation `
    -DevCmdArguments "-arch=x64 -host_arch=x64" | Out-Null

Add-Content $dst "=== AFTER ==="
Add-Content $dst ("cl on PATH? " + [bool](Get-Command cl.exe -ErrorAction SilentlyContinue))
Add-Content $dst ("rc on PATH? " + [bool](Get-Command rc.exe -ErrorAction SilentlyContinue))
Add-Content $dst ("mt on PATH? " + [bool](Get-Command mt.exe -ErrorAction SilentlyContinue))
Add-Content $dst ("WindowsSdkDir env = " + $env:WindowsSdkDir)
Add-Content $dst ("WindowsSdkVersion env = " + $env:WindowsSDKVersion)
Add-Content $dst "=== PATH entries mentioning Kits / Windows ==="
$env:PATH -split ";" | Where-Object { $_ -match "Kits|Windows Kits" } | Out-File $dst -Append -Encoding utf8
if (-not ($env:PATH -split ";" | Where-Object { $_ -match "Kits" })) { Add-Content $dst "(none)" }
Add-Content $dst "=== INCLUDE (first 5) ==="
($env:INCLUDE -split ";") | Select-Object -First 5 | Out-File $dst -Append -Encoding utf8
Add-Content $dst "=== is 10.0.22621.0 the only SDK? Kits\10\bin contents recheck ==="
Add-Content $dst ("rc full path exists? " + (Test-Path "C:\Program Files (x86)\Windows Kits\10\bin\10.0.22621.0\x64\rc.exe"))
