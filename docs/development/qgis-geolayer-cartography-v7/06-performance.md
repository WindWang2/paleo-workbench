# 06 — Performance (§15)

All numbers from this machine (Windows 11, 32 GB, MSVC build, -j2 vendor
QGIS), worktree venv cp312, offscreen Qt. Budgets are the goal-time
acceptance bars encoded in the perf tests; slow-marked suites opt out of
fast CI selections.

## Mirror publish (§9) — tests/perf/test_mirror_publish_scale.py

| scale (layers × 40 features) | full publish | no-op publish | budget (full/no-op ms) |
|---|---|---|---|
| 50 | 38.9 ms | 4.7 ms | 60 / 8 |
| 200 | 113.9 ms | 8.6 ms | 240 / 30 |
| 500 | 256.9 ms | 22.6 ms | 700 / 80 |
| 1000 | 535.5 ms | 30.6 ms | 1600 / 180 |

No-op is O(changed): ≈0.03 ms/layer — a single-layer change at 1000 layers
does not re-ship the other 999. Single-feature edit ships exactly 1 feature
(asserted); style-only change re-ships only the restyled layer's payload
(asserted: 40 of 200×40); visibility-only likewise.

## Host-side payloads (§15)

- single-feature edit over a 100k-feature layer: full diff + delta ship in
  **2.5–3.0 s** (budget 4 s) — `single-edit-100k` in
  tests/perf/test_v7_goal_perf.py. The C++ side then applies 1 delete+add
  instead of truncating/re-adding 100k features.
- 500×500 grid, 5-factor weighted fusion (250k cells, 10% NaN each):
  **≈60 ms** — the 500×500×50 envelope stays in the same memory class
  (evidence count adds linear numpy passes, not grids).

## Vendor build cost (record for future worktrees)

- conda deps env ≈ 3.5 GB; vendor build dir ≈ 6 GB (Release, Ninja, -j2):
  core+gui+resources ≈ 4.5 h wall on this machine; analysis ≈ 1 h.
  Reuse via `PALEO_QGIS_REUSE_VENDOR=1` + `PALEO_QGIS_BUILD_DIR` — bridge
  rebuild ≈ 5–10 min (7 TUs).

## Layout / renderer / save-reopen (§15 remainder)

- QGIS renderer + layout export + project reopen numbers captured in
  05-verification once the bridge suite runs on this machine (the bridge was
  never buildable here before this goal; CI qgis-renderer leg documents
  ~50 min vendor build at -j4 for scale comparison).
