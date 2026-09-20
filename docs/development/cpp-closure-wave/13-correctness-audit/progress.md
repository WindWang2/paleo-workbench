# Task 13 — progress ledger

Each round: candidate SHA → goal → commands+exit codes → data/lock notes →
findings → next step. Latest round last.

## Round 1 — baseline + inventory (2026-09-19)
- SHA: `06211541ae1ccce22b0d5ba9258ce722170ca98b` (origin/main, re-fetched).
- `/goal`/`/goal-loop`: not real commands on this platform — file-persisted
  loop (this directory) used instead; recorded honestly.
- Actions: `gh` auth OK; fetched #1380–#1392, #1399 bodies; created worktree +
  branch `codex/cpp-close-13-correctness-audit-20260919`; registered
  `.git/codex-coordination/cpp-close-wave/13-line.json` with file/function
  leases; wrote `task_plan.md`.
- Classification result in task_plan.md table: #1380/#1381/#1382/#1383/#1399
  already fixed on base; #1386/#1387/#1389(items2+3)/#1390/#1391 confirmed
  reproducible; #1384/#1385/#1388/#1392 classified to line 14.
- Toolchain: no cmake/ninja on PATH → located
  `~/.local/opt/cmake-3.30.5-linux-x86_64/bin/cmake`, `~/toolchain/ninja`;
  Qt6 system 6.11.2; QGIS SDK vendored read-only at main checkout.
- Exit: all light ops 0.

## Round 2 — fixes + reproductions (2026-09-19)
- Implemented (see findings.md for per-defect detail):
  - #1386 py_split/py_parse_float/py_strip Unicode-space parity + oracle cases
    regenerated from real Python 3.14 (2 new cases only; env churn reverted).
  - #1387 write==size && flush() fail-closed at both save sites.
  - #1389 QPointer floatable_ + inspector re-registration + QPointer lambda
    captures in floatable_panel_entries.
  - #1390 data() column bound; NaN→tier-2 sort key; layoutChanged connect.
  - #1391 optional-returning filter_query_from_dict + reachable warning;
    generated str.lower/str.casefold tables in Pwb::Domain wired into
    filter_index/table_model/chips; any_to_grid ragged-row PyValueError;
    algorithms() mutex_.
- Tests added/extended: ingest.parsers (unicode float/strip cases + 2 oracle
  cases), ui_data_core.asset_view_guard (Unicode fold + variant/null),
  ui_pages_data.smoke (malformed saved filters), ui_widgets.modelview (column
  OOB + NaN sort), ui_shell.qt_widgets_smoke (entry callbacks vs destruction),
  ui_workers.lifecycle (ragged grid — was an empty stub).
- Resource gate: `Probe` → RESOURCE_BUSY holder_pid=3706969
  (line-04 `Build -b build/cpp-integrated -j2`, age ~27min). Queued: ledger
  writes + self-review of diffs while waiting. No gate bypass attempted.
- Self-review of full diff: fixed one isfinite→isnan overreach (±inf must stay
  numeric per Python), one stale `field()` call in chips.cpp after helper
  rename, simplified filter_query_from_dict to required/optional helpers.
- Verified no `\xNN`+hex-literal merge hazard in generated lower_table.inc.
- Next: acquire gate → configure `build/cpp-integrated` → build touched
  targets → run the six affected test binaries (+viz_c.store_concurrency
  regression) → sanitizer pass if feasible → independent review → commit/PR.

## Round 3 — build + evidence (2026-09-19)
- Gate: contended (lines 04/14/06/03/05/02 serialized ~1.5h); honored —
  queued with retry loops on Exec, never bypassed.
- Configure: `build/cpp-integrated` Release, integrated option set,
  QGIS SDK from main checkout (read-only). Configure OK.
- Iterations fixed: generated lower_table.inc missing closing quote
  (generator f-string bug → regenerated); modelview test QString assign;
  smoke test `domain::Json` qualification; lifecycle harness g_failures
  never incremented (would have masked failures — fixed before any run).
- PRE-FIX evidence (production sources stash-popped):
  #1386 FAIL x3; #1389 SIGSEGV(139); #1390 OOB FAIL; #1391.1 repro exit=1;
  #1391.2 FAIL x2; #1391.3 FAIL x2. #1380/81 regression PASS on base.
- POST-FIX: 7/7 targets PASS twice (determinism); adjacent ctest set
  13/13 PASS.
- ASan+UBSan post-fix on the 4 instrumented test/source pairs: all clean.
- TSan (#1391.4 locking) not run — see acceptance.md.
- Next: independent review pass → commit → push → PR.

## Round 5 — review fixes + delivery (2026-09-19)
- Independent review (subagent_explore, full diff): no high-severity
  findings; 3 actionable items fixed (falsy-payload no-op, whitespace set
  completion, non-ASCII casefold sort coverage) + doc drift corrected.
- Rebuilt + re-ran touched tests under gate: 2/2 PASS.
- Committed 8cbfc6f1 on base 06211541 (origin/main unchanged at push
  time); pushed branch; PR #1416 opened against main.
- Remaining recorded limitations: TSan not run; disk-full fault injection
  not simulated; final-sigma str.lower() context rule; see findings.md.
