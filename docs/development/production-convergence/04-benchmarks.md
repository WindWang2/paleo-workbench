# 04 — Benchmarks

Honest benchmark ledger. Every number tagged [measured] / [simulated] / [extrapolated].

## Catalog scale (SQLite canonical, re-landed #1099) — [measured]

`benchmarks/catalog_scale_benchmark.py`, 2026-08-29, local NVMe, py3.13, production
`DataCatalogService` API only. Seeding: batch `import_raw` (100k ≈ 54 s ≈ 1850 assets/s).

| operation | 10,000 ms | 50,000 ms | 100,000 ms |
|---|---|---|---|
| metadata_update | 0.2 | 0.2 | 0.2 |
| add_tag (new) | 0.3 | 0.3 | 0.2 |
| add_tag (2nd asset) | 0.1 | 0.1 | 0.1 |
| remove_tag | 0.1 | 0.1 | 0.1 |
| rename_tag | 0.1 | 0.1 | 0.1 |
| register_version (copy+hash+fsync) | 6.6 | 16.5 | 39.1 |
| trash_version / restore_version | 1.1 / 5.0 | 1.0 / 15.6 | 0.9 / 39.4 |
| trash_asset / restore_asset | 2.1 / 1.3 | 8.8 / 9.0 | 9.7 / 13.9 |
| search (hit / miss) | 1.6 / 0.8 | 6.5 / 4.7 | 20.2 / 12.2 |
| filter_by_tag | 3.2 | 19.4 | 38.0 |
| filter_by_type (returns ALL rows) | 74.0 | 543.3 | 1449.6 |

Acceptance (#1027): ordinary metadata/tag mutations at 100k **< 20 ms → achieved
with ~100× headroom** (0.1–0.3 ms). trash/restore stay interactive (≤ 14 ms).
`register_version` includes file copy + sha256 + fsync — a data-ingest op, not a
UI mutation. `filter_by_type` cost is proportional to the **returned result size**
(materializing 100k pydantic rows); the UI path for large lists is the
virtualized table (#1090), not this list API. No mutation rewrites the JSON
manifest (pinned by `tests/perf/test_catalog_scale.py`).

Pre-#1099 baseline for comparison [measured, from the dropped PR's audit]:
each tag/metadata mutation deep-copied the CatalogDocument and rewrote the
whole ~80 MB catalog.json — seconds at 100k (the exact numbers were recorded
in the P1 audit as 3–10 s UI ops).

