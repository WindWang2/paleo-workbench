# 05 — Performance Budgets & Measurements

All numbers measured locally (this machine, offscreen Qt, software GL)
through `run_env.sh`. Extrapolations are labelled.

## P0-B Explorer @ 100k assets (tests/test_paged_catalog_mode.py)

| Operation | Budget | Measured |
|---|---|---|
| SQL page fetch (500 rows, keyset) | < 50 ms | p50 ≈ 17–20 ms (view build ≈ 3 ms included) |
| count_assets | < 100 ms | < 10 ms |
| text search count | < 100 ms | < 15 ms |
| catalog_aggregates | refresh-cheap | ~60 ms one-time per refresh |

Pre-existing catalog budgets (docs/development/production-convergence/
04-benchmarks.md, unchanged): metadata_update 0.2 ms, add_tag 0.2 ms at 100k.
The gap this convergence closed: no more one-view-per-asset materialization
per refresh above 25k assets (was O(N) GUI-thread; now O(page)).

## P1-B Attributes

ROI vs full-memory parity: exact (rtol 1e-5) for window-local kernels at
interior and survey-edge windows; band-vs-full exact (rtol 1e-4) including
trace-global kernels (bands carry complete traces). Trace-global kernels
REFUSE cropped-time ROIs by contract.

## P0-D Composition

Template instantiation: 9 categories, < 5 ms. Composition SVG render
(7-component document): < 10 ms. PNG export @300 dpi A4 (3508×2480):
~250 ms one-page synchronous. PDF export: vector replay, ~150 ms.

## P1-C 3D

VRAM budget applied at boot: `VRAM.budget_bytes() == 1 GiB` on ≥16 GB
machines (pinned by test). Probe-marker highlight: O(trajectory) lookup,
no GL work beyond one marker update.

## Not re-measured (unchanged paths)

Well 100-curve/1M-sample rendering, 100G seismic slice latency, 3D soak —
covered by the pre-existing perf suites (tests/perf/, #1112/#1114 legs);
this convergence did not modify those code paths.
