# 06 — Performance baseline & budgets

Machine: same-box MSVC/Ninja, `-j4` ceiling, isolated `build/` per worktree.
Baseline reference: `tests/cpp/data/metadata_scale_test.cpp` ceilings (existing) and the
frozen `data.*` suite timings on this machine at base SHA — recorded after first full build.

## Structural gates (asserted by tests, not hoped)

| Gate | Budget | Test |
|---|---|---|
| `well_index(false)` catalog reads | ZERO statements | throwing-source test |
| `well_index(false)` time @ 10k wells/100k links | < 1.5 s (O(W+L) tree walk) | scale test |
| `well_view` catalog statements | ≤ 3 + ceil(N/500) batches for N linked assets + 1 WC list | statement-counter test |
| expand-one-well materialization | ≤ (assets of that well) summaries; never the 100k store | scale test |
| `entity_staleness` | existing bounded walk (4096, pessimistic-quiet) — unchanged | impact suite (frozen) |
| nav-tree page materialization | existing kEntityPageSize=500 paging — unchanged | ui_pages_data tests |
| ingest plan | existing domain plan budget; UI executes via JobCenter async | ingest tests (frozen) |

## Measurement discipline

- Statement counting: sqlite progress/trace hook injected by the TEST source wrapper
  (production code unchanged).
- A/B: feature worktree vs clean `origin/main` worktree, same box/config/command, when a
  regression is suspected (esp. vs #1434's table/filter paths which this line must not touch).
- Memory: expand-one-well must not allocate O(total assets); asserted via the statement gate
  (no such reads possible) + spot RSS ceiling in the scale test.
