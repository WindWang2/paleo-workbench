# Remove the 7 stale worktree checkouts and delete their already-merged branches.
#
# Why this is safe (verified 2026-09-14):
#   * Every branch backing these worktrees was merged upstream:
#       v10-review-fixes             -> PR #1267 MERGED
#       review-convergence-20260912  -> PR #1277 MERGED
#       data-fabric-v11              -> PR #1288 MERGED
#       workbench-ux-v11             -> PR #1289 MERGED
#       qgis-runtime-v11             -> PR #1290 MERGED
#       fix/dead-shell-review-20260913 -> PR #1296 MERGED
#       review-followups-20260913    -> PR #1293 CLOSED, but its 4-file / 16-line
#                                       change is already present in main
#   * Local main was re-pointed at upstream tip e7214566; the previous local-only
#     844 commits are preserved on branch: backup-local-main-20260914
#   * Process artifacts (.scratch / .agent-work) from 5 worktrees were copied to
#     .workbuddy\worktree-backup before this script is meant to run.
#
# NOTE on `git worktree prune`: it is only safe here because ALL registered
# worktrees except the main checkout are intentionally being deleted. Do not run
# it casually in this repo - it previously wiped 12 valid worktree registrations.
#
# Usage:  powershell -ExecutionPolicy Bypass -File .\scripts\cleanup-worktrees.ps1

$ErrorActionPreference = "Continue"
$root = "C:\Users\wangj.KEVIN\projects\paleo-workbench"

$paths = @(
    "$root\.worktrees\fix-dead-shell-review-20260913",
    "$root\.worktrees\review-followups-20260913",
    "$root\.worktrees\v10-review-fixes",
    "C:\Users\wangj.KEVIN\projects\paleo-workbench-data-fabric-v11",
    "C:\Users\wangj.KEVIN\projects\paleo-workbench-qgis-runtime-v11",
    "C:\Users\wangj.KEVIN\projects\paleo-workbench-review-convergence-20260912",
    "C:\Users\wangj.KEVIN\projects\paleo-workbench-workbench-ux-v11"
)

$branches = @(
    "data-fabric-v11",
    "fix/dead-shell-review-20260913",
    "qgis-runtime-v11",
    "review-convergence-20260912",
    "review-followups-20260913",
    "v10-review-fixes",
    "workbench-ux-v11"
)

Write-Host "=== 1/3 deleting worktree directories ===" -ForegroundColor Cyan
foreach ($p in $paths) {
    if (Test-Path $p) {
        Write-Host "  rd /s /q $p"
        cmd /c "rd /s /q `"$p`""
    } else {
        Write-Host "  (already gone) $p"
    }
}

Set-Location $root

Write-Host "=== 2/3 pruning worktree registrations ===" -ForegroundColor Cyan
git worktree prune
git worktree list

Write-Host "=== 3/3 deleting merged branches ===" -ForegroundColor Cyan
foreach ($b in $branches) {
    git branch -D "$b"
}

Write-Host "=== final state ===" -ForegroundColor Cyan
git worktree list
git branch --format="%(refname:short)"
git status -sb
