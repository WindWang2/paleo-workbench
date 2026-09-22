# 00 — Baseline (documentation refresh)

| Item | Value |
| --- | --- |
| Date | 2026-09-22 Asia/Shanghai |
| Branch | `docs/project-documentation-refresh-2026` |
| Worktree | `/workspace/paleo-workbench-doc-refresh` |
| Code baseline | `18c674ef` (`origin/main`) |
| Worker | sole executor (no fan-out) |

## Problem observed

Root product docs still described a **Python/PySide6-first** workstation while
`main` already ships:

- native `pwb-platform` + 63 `libs/*`
- ribbon five-workspaces shell (`fa9ba744`)
- GeoViz / platform closure ledgers under `docs/development/**`

There was **no** `docs/README.md` IA index. Agents and humans had to guess
which of hundreds of development ledgers were canonical.

## Non-goals

- No C++/Python product code changes.
- No rewriting every historical ledger under `docs/development/`.
- No flipping the packaging default entry (that is M12 / entry-switch).
