# Self-test for Invoke-ResourceGate.ps1. Exercises:
#   (a) Probe succeeds            -> RESOURCE_READY, exit 0
#   (b) a concurrent holder        -> RESOURCE_BUSY, exit 75
#   (c) a huge MinFreeGiB          -> RESOURCE_LOW_MEMORY, exit 75
#   (d) a backdated (stale) lock   -> RESOURCE_STALE_LOCK_RECOVERED + READY, exit 0
#   (e) -Jobs 99                   -> clamped to 8 (jobs=8 + warning), exit 0
#   (f) invalid usage              -> RESOURCE_GATE_ERROR, exit 64
#   (g) Build with missing build dir -> RESOURCE_GATE_ERROR "run Configure first", exit 1
#   (h) Exec -- child                -> child exit code propagated, PWB_GATE_HELD set
#   (i) -StaleLockMinutes abc        -> RESOURCE_GATE_ERROR, exit 64 (not a raw binder error)
# Prints PASS/FAIL per case and exits non-zero if any FAIL.
$ErrorActionPreference = 'Stop'

# Ensure git is on PATH for this harness (machine-specific install locations).
foreach ($p in @('C:\Program Files\Git\cmd', 'C:\Program Files\Git\bin', 'C:\Program Files\Git\usr\bin')) {
    if (Test-Path $p) { $env:PATH = "$p;$env:PATH" }
}

$gateScript = Join-Path $PSScriptRoot 'Invoke-ResourceGate.ps1'

function Invoke-Gate {
    param([string[]]$GateArgs)
    # A native child that writes to stderr becomes a *terminating* error while
    # $ErrorActionPreference is 'Stop', which would abort the harness instead of
    # recording a result. Relax it only for the duration of the child call.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & powershell -NoProfile -ExecutionPolicy Bypass -File $gateScript @GateArgs 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    return (@($out) -join "`n"), $code
}

function Get-GatePaths {
    $repoRoot = (git rev-parse --show-toplevel).Trim()
    $commonDir = (git rev-parse --git-common-dir).Trim()
    if (-not [IO.Path]::IsPathRooted($commonDir)) { $commonDir = Join-Path (Get-Location).Path $commonDir }
    $commonDir = [IO.Path]::GetFullPath($commonDir)
    return (Join-Path $commonDir 'cpp-migration-heavy.lock'), (Join-Path $commonDir 'cpp-migration-heavy.owner')
}

function Get-FreeGiB {
    $os = Get-CimInstance Win32_OperatingSystem
    return [double]$os.FreePhysicalMemory / 1MB
}

function Clean-Lock {
    param($lockPath, $ownerPath)
    try { if (Test-Path -LiteralPath $lockPath) { Remove-Item -LiteralPath $lockPath -Force } } catch {}
    try { if (Test-Path -LiteralPath $ownerPath) { Remove-Item -LiteralPath $ownerPath -Force } } catch {}
}

$results = @()
function Record($name, $ok, $detail) {
    $results += ,@($name, $ok, $detail)
    $tag = if ($ok) { 'PASS' } else { 'FAIL' }
    Write-Output ("[{0}] {1}: {2}" -f $tag, $name, $detail)
}

$freeGiB = Get-FreeGiB
$successThreshold = [Math]::Max(0.001, $freeGiB * 0.5)
$lowThreshold = ($freeGiB + 10)

$lockPath, $ownerPath = Get-GatePaths

try {
    # (a) Probe succeeds
    Clean-Lock $lockPath $ownerPath
    $out, $code = Invoke-Gate @('-Action', 'Probe', '-MinFreeGiB', $successThreshold)
    Record '(a) Probe succeeds' ($code -eq 0 -and $out -match 'RESOURCE_READY') ("exit=$code; $out")

    # (b) concurrent holder -> busy
    Clean-Lock $lockPath $ownerPath
    $holder = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    Set-Content -LiteralPath $ownerPath -Value ("pid={0} action=Test root=x time={1}" -f $PID, (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')) -NoNewline
    $out, $code = Invoke-Gate @('-Action', 'Probe', '-MinFreeGiB', $successThreshold)
    $holder.Dispose()
    Record '(b) concurrent busy' ($code -eq 75 -and $out -match 'RESOURCE_BUSY') ("exit=$code; $out")

    # (c) huge MinFreeGiB -> low memory
    Clean-Lock $lockPath $ownerPath
    $out, $code = Invoke-Gate @('-Action', 'Probe', '-MinFreeGiB', $lowThreshold)
    Record '(c) low memory' ($code -eq 75 -and $out -match 'RESOURCE_LOW_MEMORY') ("exit=$code; $out")

    # (d) stale lock recovery
    Clean-Lock $lockPath $ownerPath
    New-Item -ItemType File -Path $lockPath -Force | Out-Null
    New-Item -ItemType File -Path $ownerPath -Force | Out-Null
    # A pid that cannot exist: pid 1 is init on Linux and always alive, which
    # would make recovery correctly refuse and this case fail there.
    Set-Content -LiteralPath $ownerPath -Value 'pid=999999 action=Test root=x time=2020-01-01T00:00:00Z' -NoNewline
    $old = (Get-Date).AddMinutes(-(60 + 45))
    (Get-Item -LiteralPath $ownerPath).LastWriteTime = $old
    (Get-Item -LiteralPath $lockPath).LastWriteTime = $old
    $out, $code = Invoke-Gate @('-Action', 'Probe', '-MinFreeGiB', $successThreshold)
    Record '(d) stale lock recovered' ($code -eq 0 -and $out -match 'RESOURCE_STALE_LOCK_RECOVERED' -and $out -match 'RESOURCE_READY') ("exit=$code; $out")

    # (e) Jobs 99 clamped to 8
    Clean-Lock $lockPath $ownerPath
    $out, $code = Invoke-Gate @('-Action', 'Probe', '-MinFreeGiB', $successThreshold, '-Jobs', '99')
    Record '(e) Jobs clamp to 8' ($code -eq 0 -and $out -match 'jobs=8' -and $out -match 'RESOURCE_GATE_WARNING') ("exit=$code; $out")

    # (f) invalid usage -> 64
    Clean-Lock $lockPath $ownerPath
    $out, $code = Invoke-Gate @('-Action', 'Probe', '-MinFreeGiB', 'notanumber')
    Record '(f) invalid usage' ($code -eq 64 -and $out -match 'RESOURCE_GATE_ERROR') ("exit=$code; $out")

    # (g) Build with missing build dir -> refuse (run Configure first)
    Clean-Lock $lockPath $ownerPath
    $out, $code = Invoke-Gate @('-Action', 'Build', '-BuildDir', 'build/__gate_test_missing__', '-MinFreeGiB', $successThreshold)
    Record '(g) Build missing build dir refused' ($code -eq 1 -and $out -match 'RESOURCE_GATE_ERROR' -and $out -match 'Configure first') ("exit=$code; $out")

    # (h) Exec runs a child under the slot: the marker must be visible to the
    # child and the child's exit code must be propagated unchanged.
    # NOTE: `powershell -File` can bind only ONE argument to the string[]
    # parameter -CommandArguments, and a single space-containing token gets
    # re-quoted on the way to a native child (cmd.exe then sees a stray quote).
    # So the marker probe is a space-free batch file, and the exit-code probe
    # uses the one child command line that survives the round trip.
    $probeBat = Join-Path ([IO.Path]::GetTempPath()) 'pwb_gate_marker_probe.bat'
    Set-Content -LiteralPath $probeBat -Encoding Ascii `
        -Value "@echo off`r`necho GATE_MARKER=%PWB_GATE_HELD%`r`nexit /b 0"
    Clean-Lock $lockPath $ownerPath
    $out, $code = Invoke-Gate @('-Action', 'Exec', '-MinFreeGiB', $successThreshold,
        '-Command', $probeBat)
    $markerOk = ($code -eq 0 -and $out -match 'GATE_MARKER=1')
    $out2, $code2 = Invoke-Gate @('-Action', 'Exec', '-MinFreeGiB', $successThreshold,
        '-Command', 'cmd.exe', '-CommandArguments', '/c exit 7')
    try { Remove-Item -LiteralPath $probeBat -Force -ErrorAction SilentlyContinue } catch {}
    Record '(h) Exec sets PWB_GATE_HELD and propagates child exit code' `
        ($markerOk -and $code2 -eq 7) ("marker_exit=$code child_exit=$code2")

    # (i) a non-numeric StaleLockMinutes is invalid usage, not a raw binder error
    Clean-Lock $lockPath $ownerPath
    $out, $code = Invoke-Gate @('-Action', 'Probe', '-MinFreeGiB', $successThreshold, '-StaleLockMinutes', 'abc')
    Record '(i) invalid StaleLockMinutes' ($code -eq 64 -and $out -match 'RESOURCE_GATE_ERROR') ("exit=$code; $out")
} finally {
    Clean-Lock $lockPath $ownerPath
}

$failed = $results | Where-Object { -not $_[1] }
if ($failed.Count -gt 0) {
    Write-Output ("SELF-TEST FAILED: {0} case(s) failed" -f $failed.Count)
    exit 1
}
Write-Output 'SELF-TEST PASSED'
exit 0
