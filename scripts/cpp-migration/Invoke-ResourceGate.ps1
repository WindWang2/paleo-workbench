# Shared admission gate for the three C++ migration worktrees (PowerShell 5.1+).
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
    [ValidateRange(8, 128)]
    [int]$MinFreeGiB = 8
)

$ErrorActionPreference = 'Stop'
$gateStream = $null
$savedEnvironment = @{}
$exitCode = 1
try {
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
    $gatePath = Join-Path $commonDir 'cpp-migration-heavy.lock'

    # FileShare.None is atomic across all worktrees. File contents are diagnostic,
    # not the lock: a leftover file after a process exits is harmless.
    try {
        $gateStream = [IO.File]::Open($gatePath, [IO.FileMode]::OpenOrCreate,
            [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch [IO.IOException] {
        Write-Output 'RESOURCE_BUSY: another migration job holds the shared slot; exit=75.'
        exit 75
    }
    $ownerText = "pid=$PID action=$Action root=$repoRoot time=$([DateTime]::UtcNow.ToString('o'))"
    $ownerBytes = [Text.Encoding]::UTF8.GetBytes($ownerText)
    $gateStream.SetLength(0)
    $gateStream.Write($ownerBytes, 0, $ownerBytes.Length)
    $gateStream.Flush()

    $osInfo = Get-CimInstance Win32_OperatingSystem
    $freeGiB = [double]$osInfo.FreePhysicalMemory / 1MB
    if ($freeGiB -lt $MinFreeGiB) {
        Write-Output ("RESOURCE_LOW_MEMORY: free={0:N2} GiB required={1} GiB; exit=75." -f $freeGiB, $MinFreeGiB)
        exit 75
    }
    if ($Action -eq 'Probe') {
        Write-Output ("RESOURCE_READY: shared slot available; free={0:N2} GiB; jobs=2; probe only." -f $freeGiB)
        exit 0
    }

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

    foreach ($entry in @{
        CMAKE_BUILD_PARALLEL_LEVEL = '2'
        CTEST_PARALLEL_LEVEL = '2'
        OMP_NUM_THREADS = '1'
        OPENBLAS_NUM_THREADS = '1'
        MKL_NUM_THREADS = '1'
        NUMEXPR_NUM_THREADS = '1'
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
            & cmake --build $resolvedBuild --config $Configuration --parallel 2 --target @Targets
        } else {
            & cmake --build $resolvedBuild --config $Configuration --parallel 2
        }
    } else {
        & ctest --test-dir $resolvedBuild -C $Configuration --parallel 2 --output-on-failure --no-tests=error --timeout 180 -R $TestRegex
    }
    $exitCode = $LASTEXITCODE
    if ($null -eq $exitCode) { throw 'Native command produced no exit code.' }
} catch {
    Write-Error -ErrorAction Continue ("RESOURCE_GATE_ERROR: " + $_.Exception.Message)
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
