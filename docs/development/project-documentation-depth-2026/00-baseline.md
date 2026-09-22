# 00 — Baseline (documentation depth / pass-2)

| Item | Value |
| --- | --- |
| Date | 2026-09-22 Asia/Shanghai |
| Branch | `docs/project-documentation-depth-2026` |
| Worktree | `/workspace/paleo-workbench-doc-depth` |
| Code baseline | `470d7500d9a22ec477a9b2e05bdbe09d330b6a9f` (short `470d7500`) |
| Prefer PR base | `docs/project-documentation-refresh-2026` (pass-1) |
| Worker | sole executor (no fan-out) |

## Why a second pass

Pass-1 (`docs/project-documentation-refresh-2026`, PR #1474) fixed **IA + dual-track honesty**:
native `pwb_platform` first, Python legacy/oracle explicit, shallow module map, conversion snapshot,
ribbon adoption status.

It did **not** yet freeze:

- the full ribbon command table (ids / groups / primary / overflow / effective install)
- a per-library inventory for all 63 `libs/*`
- the app `*_install*` composition-root map

Agents still had to reverse-engineer `ribbon_spec.cpp` + `ribbon_command_install.cpp` to answer
“what does this button do?” and “which lib owns X?”.

## Non-goals

- No C++/Python product code changes.
- No inventing backends for disabled ribbon commands.
- No rewriting every historical ledger under `docs/development/`.
- No packaging default-entry flip (M12 / entry-switch).
