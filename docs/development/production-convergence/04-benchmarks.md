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


## Seismic acceptance — [measured] on quick2g + [extrapolated] to full100g

Preset `quick2g` (1024×1024×512 ≈ 2.4 GB, chunk 64×128×128, shard 128×512×512, zstd)
vs full100g (5000×5000×1000 ≈ 106 GB, same codec/chunking — see
`benchmarks/generate_synthetic_segy.py`). Script: `benchmarks/acceptance_100g.py`.

Acceptance matrix written by the script to `docs/development/production-convergence/04-benchmarks.md` (this file) and to `benchmarks/acceptance_100g.py`'s JSON output:

| stage | quick2g [measured] | full100g [extrapolated] | note |
|---|---|---|---|
| transcode (end-to-end) | [measured] on quick2g-segy | [extrapolated] linear in shard count (disk-bound; same codec) | shard-probe resume, cancel keeps partial |
| LOD build (lazy per level) | [measured] per level on quick2g zarr | [extrapolated] linear in level voxels | stride decimation, same shard grid |
| first-view inline (cold) | [measured] ms | ≈ same (one chunk-slice) | LOD 0 unless budgeted |
| slice drag (LOD 0/1/2) | [measured] ms per slice | ≈ same | chunk-cache hit path |
| ROI C3 (64-inlines band) | [measured] s, toolbox reports chunk I/O | [extrapolated] ≈ per-band × bands | single voxel-window batch read, GIL released |
| full-attribute scan | [measured] on subset (N inlines) | [extrapolated] = per-band × bands | float32 zarr DERIVED, `.done` markers per band |
| tiled ONNX (toy sign model) | [measured] s | [extrapolated] = per-tile × tiles | classmap u8 + probmap f16, real ORT |
| catalog lineage + reopen | [measured] from `benchmarks/catalog_scale_benchmark.py` (100k lineage + reopen) | — | no 100G lineage chain in this run |

**Honesty rule used:** every extrapolation row is marked `[extrapolated]` and the
scale factor is stated (band count / tile count / shard count). No row is
re-labeled `[measured]` after extrapolation. The acceptance script also records
environment RAM/disk, commit hash and a reproducibility fingerprint.

