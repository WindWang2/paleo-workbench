# Shared admission gate for the C++ migration worktrees (PowerShell 5.1+).
# Hardens the single build slot so the 7 parallel migration worktrees cannot
# OOM the machine: an exclusive slot lock in the git *common* dir, a free-memory
# gate, a bounded job ceiling, and stale-lock recovery. POSIX mirror:
# invoke-resource-gate.sh (1:1 semantics).
#
# Exit codes:
#   0   success (resource granted, action run)
#   1   internal / usage error (RESOURCE_GATE_ERROR)
#   64  invalid usage (EX_USAGE) - malformed / out-of-range flags
#   75  resource refusal (busy slot OR low memory)
#   124 timeout (reserved; not currently emitted)
#
# Diagnostic tokens (machine-readable, exactly one summary line per outcome):
#   RESOURCE_READY free_gib=.. jobs=.. lock=<path>
#   RESOURCE_BUSY holder_pid=.. age_min=..
#   RESOURCE_LOW_MEMORY free_gib=.. required=..
#   RESOURCE_STALE_LOCK_RECOVERED age_min=..
#   RESOURCE_GATE_ERROR detail=..
[CmdletBinding()]
param(
    [ValidateSet('Probe', 'Configure', 'Build', 'Test')]
    [string]$Action = 'Probe',
    [string]$SourceDir,
    [string]$BuildDir,
    [string]$Configuration = 'Release',
    [string[]]$Targets = @(),
    [string[]]$CmakeArguments = @(),
    [string]$TestRegex = '.',
    [Alias('m')]
    [string]$MinFreeGiB = '8',
    [Alias('j')]
    [string]$Jobs = '2',
    [int]$StaleLockMinutes = 45,
    [Alias('F')]
    [switch]$ForceRecoverLock
)

$ErrorActionPreference = 'Stop'
$gateStream = $null
$savedEnvironment = @{}
$exitCode = 1

function Write-Diag { param([string]$Line) Write-Output $Line }

function Test-PidAlive {
    param([int]$CandidatePid)
    if ($CandidatePid -le 0) { return $false }
    try { return ($null -ne (Get-Process -Id $CandidatePid -ErrorAction SilentlyContinue)) }
    catch { return $false }
}

function Resolve-GatePaths {
    $repoRoot = & git rev-parse --show-toplevel
    if ($LASTEXITCODE -ne 0) { throw 'Run this script from a migration worktree.' }
    $repoRoot = [IO.Path]::GetFullPath($repoRoot.Trim())
    $commonDir = & git rev-parse --git-common-dir
    if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve the shared Git directory.' }
    $commonDir = $commonDir.Trim()
    if (-not [IO.Path]::IsPathRooted($commonDir)) {
        $commonDir = Join-Path (Get-Location).Path $commonDir
    }
    $commonDir = [IO.Path]::GetFullPath($commonDir)
    return @{
        RepoRoot  = $repoRoot
        CommonDir = $commonDir
        LockPath  = Join-Path $commonDir 'cpp-migration-heavy.lock'
        OwnerPath = Join-Path $commonDir 'cpp-migration-heavy.owner'
    }
}

try {
    # --- validate flags (invalid usage -> 64, before touching the lock) ---
    try { $minFree = [double]$MinFreeGiB } catch {
        Write-Diag ("RESOURCE_GATE_ERROR detail=invalid MinFreeGiB: '{0}' must be a positive number" -f $MinFreeGiB)
        exit 64
    }
    if ($minFree -le 0) {
        Write-Diag ("RESOURCE_GATE_ERROR detail=invalid MinFreeGiB: '{0}' must be a positive number" -f $MinFreeGiB)
        exit 64
    }
    try { $jobs = [int]$Jobs } catch {
        Write-Diag ("RESOURCE_GATE_ERROR detail=invalid Jobs: '{0}' must be an integer 1..8" -f $Jobs)
        exit 64
    }
    if ($jobs -lt 1) {
        Write-Diag ("RESOURCE_GATE_ERROR detail=invalid Jobs: {0} must be >= 1" -f $jobs)
        exit 64
    }
    if ($jobs -gt 8) {
        Write-Diag ("RESOURCE_GATE_WARNING detail=Jobs {0} clamped to 8 (unbounded parallelism rejected)" -f $jobs)
        $jobs = 8
    }
    if ($StaleLockMinutes -le 0) {
        Write-Diag ("RESOURCE_GATE_ERROR detail=StaleLockMinutes must be a positive integer (got {0})" -f $StaleLockMinutes)
        exit 64
    }

    $paths = Resolve-GatePaths
    $repoRoot = $paths.RepoRoot
    $commonDir = $paths.CommonDir
    $gatePath = $paths.LockPath
    $ownerPath = $paths.OwnerPath

    # --- acquire the exclusive build slot (FileShare.None == cross-process lock) ---
    try {
        $gateStream = [IO.File]::Open($gatePath, [IO.FileMode]::OpenOrCreate,
            [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch [IO.IOException] {
        # A live process holds the OS-level exclusive lock -> the slot is busy.
        # The owner sidecar is a separate file and stays readable while locked.
        $holderPid = 'unknown'; $ageMin = 0.0
        if (Test-Path -LiteralPath $ownerPath) {
            $ownerText = (Get-Content -LiteralPath $ownerPath -Raw).Trim()
            if ($ownerText -match 'pid=(\d+)') { $holderPid = $Matches[1] }
            $ageMin = [Math]::Max(0.0, ([DateTime]::Now - (Get-Item -LiteralPath $ownerPath).LastWriteTime).TotalMinutes)
        }
        Write-Diag ("RESOURCE_BUSY holder_pid={0} age_min={1:N1}" -f $holderPid, $ageMin)
        exit 75
    }

    # --- stale lock recovery (only reached when WE hold the lock) ---
    # If the previous owner died without releasing, the OS freed the lock and we
    # acquired it; an old owner sidecar means it was abandoned. Never reclaim a
    # lock whose recorded owner pid is still alive.
    if (Test-Path -LiteralPath $ownerPath) {
        $ownerText = (Get-Content -LiteralPath $ownerPath -Raw).Trim()
        $holderPid = $null
        if ($ownerText -match 'pid=(\d+)') { $holderPid = [int]$Matches[1] }
        $ageMin = [Math]::Max(0.0, ([DateTime]::Now - (Get-Item -LiteralPath $ownerPath).LastWriteTime).TotalMinutes)
        $stale = $ForceRecoverLock -or ($ageMin -ge $StaleLockMinutes)
        if ($stale -and -not (Test-PidAlive $holderPid)) {
            Write-Diag ("RESOURCE_STALE_LOCK_RECOVERED age_min={0:N1}" -f $ageMin)
        }
    }

    # Publish our ownership (readable sidecar; the .lock file stays exclusively held).
    $ownerText = ("pid={0} action={1} root={2} time={3}" -f $PID, $Action, $repoRoot,
        (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))
    Set-Content -LiteralPath $ownerPath -Value $ownerText -NoNewline

    # --- free-memory gate ---
    $osInfo = Get-CimInstance Win32_OperatingSystem
    $freeGiB = [double]$osInfo.FreePhysicalMemory / 1MB
    if ($freeGiB -lt $minFree) {
        Write-Diag ("RESOURCE_LOW_MEMORY free_gib={0:N1} required={1:N1}" -f $freeGiB, $minFree)
        exit 75
    }

    if ($Action -eq 'Probe') {
        Write-Diag ("RESOURCE_READY free_gib={0:N1} jobs={1} lock={2}" -f $freeGiB, $jobs, $gatePath)
        exit 0
    }

    # --- action-specific guards ---
    if ([string]::IsNullOrWhiteSpace($BuildDir)) { throw 'BuildDir is required.' }
    $resolvedBuild = $BuildDir
    if (-not [IO.Path]::IsPathRooted($resolvedBuild)) {
        $resolvedBuild = Join-Path (Get-Location).Path $resolvedBuild
    }
    $resolvedBuild = [IO.Path]::GetFullPath($resolvedBuild)
    $allowedBuildRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot 'build'))
    $allowedPrefix = $allowedBuildRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $resolvedBuild.StartsWith($allowedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'BuildDir must be a child of this worktree/build; shared writable build trees are forbidden.'
    }
    if (($Action -eq 'Build' -or $Action -eq 'Test') -and -not (Test-Path -LiteralPath $resolvedBuild)) {
        throw ("Build directory '{0}' does not exist yet. Run Configure first to create it." -f $resolvedBuild)
    }

    # Bounded job ceiling + thread-limiting env (restored in finally).
    foreach ($entry in @{
        CMAKE_BUILD_PARALLEL_LEVEL = [string]$jobs
        CTEST_PARALLEL_LEVEL       = [string]$jobs
        OMP_NUM_THREADS            = '1'
        OPENBLAS_NUM_THREADS       = '1'
        MKL_NUM_THREADS            = '1'
        NUMEXPR_NUM_THREADS        = '1'
    }.GetEnumerator()) {
        $savedEnvironment[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key, 'Process')
        [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process')
    }

    if ($Action -eq 'Configure') {
        if ([string]::IsNullOrWhiteSpace($SourceDir)) { throw 'SourceDir is required for Configure.' }
        $resolvedSource = (Resolve-Path -LiteralPath $SourceDir).Path
        $sourcePrefix = $repoRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
        if ($resolvedSource -ne $repoRoot -and -not $resolvedSource.StartsWith($sourcePrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'SourceDir must be in this worktree. Pass read-only external SDK paths through CMake variables.'
        }
        & cmake -S $resolvedSource -B $resolvedBuild -G Ninja "-DCMAKE_BUILD_TYPE=$Configuration" @CmakeArguments
    } elseif ($Action -eq 'Build') {
        if ($Targets.Count -gt 0) {
            & cmake --build $resolvedBuild --config $Configuration --parallel $jobs --target @Targets
        } else {
            & cmake --build $resolvedBuild --config $Configuration --parallel $jobs
        }
    } else {
        & ctest --test-dir $resolvedBuild -C $Configuration --parallel $jobs --output-on-failure --no-tests=error --timeout 180 -R $TestRegex
    }
    $exitCode = $LASTEXITCODE
    if ($null -eq $exitCode) { throw 'Native command produced no exit code.' }
} catch {
    Write-Diag ("RESOURCE_GATE_ERROR detail=" + $_.Exception.Message)
    $exitCode = 1
} finally {
    foreach ($key in $savedEnvironment.Keys) {
        if ($null -eq $savedEnvironment[$key]) {
            Remove-Item -LiteralPath "Env:$key" -ErrorAction SilentlyContinue
        } else {
            [Environment]::SetEnvironmentVariable($key, $savedEnvironment[$key], 'Process')
        }
    }
    if ($null -ne $gateStream) { $gateStream.Dispose() }
}
exit $exitCode
