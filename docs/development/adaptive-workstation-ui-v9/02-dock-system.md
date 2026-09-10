# 02 — Dock System V2 (V9)

## Descriptor schema

Each dock is described once, declaratively (`ui/dock_framework.py`):

| Field | Meaning |
|---|---|
| `dock_id` | Stable id (`"nav"`, `"inspector"`, …) — persistence/vocabulary key |
| `title` | Native title (also objectName `WorkstationDock_<id>`) |
| `preferred_area` | Initial dock area |
| `importance` | `core` / `secondary` / `utility` — drives default visibility + responsive priorities |
| `default_visible` | First-run visibility |
| `can_float` | False for GL-bearing docks (well/seismic, hub-when-GL) |
| `can_tabify` | Advisory (all currently True; bottom row tabifies) |
| `min_floating_size` | Minimum **while floating only** (docked minimum is always 0) |
| `preferred_size` | First-run `resizeDocks` target (first run / reset only — never on preset apply) |
| `workflow_tags` / `context_tags` | Stage/workflow affinity (consumed by stage dock recommendations) |

## Resize correctness contract

1. Docked docks: `setMinimumSize(0,0)`; content must not impose structural minimums (see 04-responsive-rules).
2. Floating docks: enforce `min_floating_size` via `topLevelChanged` (existing behavior, kept).
3. `resizeDocks` is called only from: first-run defaults, explicit layout reset, and grow-only affordances (`ensure_dock_usable`) — never after user interaction, never on preset apply.
4. `restoreState` runs under the existing version fence; after restore the responsive policy re-runs **debounced**.
5. All docks (13/13) are wired to the save-signal set.
6. Screen set changes at runtime (`screenAdded`, `primaryScreenChanged`, `screenRemoved`) re-clamp the host window + floating docks to the visible desktop.

## Fixes over V8 (each mapped to audit findings)

| Audit | Fix |
|---|---|
| B-1 hub page floors | Pages lose fixed-width side panels (min ≤180 + scroll); splitters collapsible; see 04 |
| B-2 constraint stack | window min 1180x720 → 960x600; inspector 280 → 220; explorer floor 210 → 180; central 420 → 320 |
| B-3 resizeDocks clobber | preset apply no longer sizes; `_expand_agent_dock` grow-only via `ensure_dock_usable` |
| B-4 mid-drag reflow | responsive policy debounced 180ms, restarts on resize; no mutation in resizeEvent |
| B-5 GL float crash | can_float=False for well/seismic; hub dynamic |
| C-4 save wiring | all docks wired |
| C-7 screens | runtime screen-change re-clamp |
