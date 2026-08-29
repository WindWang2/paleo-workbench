# 06 — Architecture After

Branch: `feat/production-workflow-convergence` (based on `main` af92f59e)

## Catalog

- SQLite is the canonical metadata store (WAL, row-level txns, `DirtySet` dirty-row writes, `reconcile`, `load_document`, `write_all`, schema migration from v4 index DBs). `catalog.json` is a checkpoint/export (never rewritten on single-row mutations). Re-landed from the dropped #1099 onto the post-P1 main (merged with the #1089 legacy-projection + #1088 bulk-deletion changes).
- Lineage DAG walk: `deque` BFS + per-traversal tag/asset/run maps (no `pop(0)`, no per-node `dict` rebuild).

## Seismic (100G out-of-core)

```
SEG-Y RAW (segyio fallback, browse-during-transcode)
  ↓  seismic_lifecycle.SeismicLifecycleService → TaskScheduler(single IO worker)
Zarr v3 store (chunk 64×128×128, shard 128×512×512, zstd, grid attrs)
  ↓  open_volume() → VolumeReader
ChunkedVolumeReader  — zarr + lazy cascade LOD sibling stores (_l{N} per strategy)
SegyVolumeReader     — same contract over segyio (degraded path)
  ↓  read_inline/crossline/timeslice/trace/voxel_window/arbitrary_line(*, lod=)
     LOD keeps logical inline/crossline VALUES; window = one chunk-coverage slice
  ↓  L1 RamSliceCache (2 GB global) + scheduler
  ↓  LodPolicy (16 ms frame budget, 250 ms idle refine) + DirectionalPrefetcher + ChunkedSliceWorker
  ↓  ROI C3 (band+halo, bit-identical to full-memory) → float32 zarr DERIVED
  ↓  Full-attribute VolumeAttributeJob (same kernel, inline bands, .done markers) → float32 zarr DERIVED
  ↓  Tiled ONNX (64×128×128, overlap=center-crop, class u8 + prob f16, per-tile .done, OOM backoff)
  ↓  Catalog DataRun/parent lineage + project trash/restore (directory payloads)
```

All heavy I/O (transcode, LOD builds, attributes, inference) goes through the single `TaskScheduler(max_workers=1)` — FIFO + priority + boost, cooperative cancel, bounded history, crash-safe work dirs (no partial results deleted).

## Mapping

- CRS: `project.coordinate.project_crs` is the single source (the old `project.crs` probe removed).
- IDW: cKDTree + chunked kNN/radius (no M×N distance matrix).
- Kriging dispatches real variogram ordinary kriging; MVP linear alias removed.
- Fallback renderer: per-layer CRS reprojection via pyproj (degrees≠meters no longer silently mixed).
- QGIS bridge: wire carries `label_buffer_color` + per-feature rotation/size/color data-defined fields.

## Well-log

- `WellLogHost` prefers the native `welllog` engine (when importable and env enabled), falls back to QPainter on any engine failure (same payload).
- DTW: min-max peak-preserving decimation (thin-bed extrema survive).

## Multiview

- `ViewCoordinationController.bind_project/clear_project` registers wells + bin-grid geometry into `CoordinateTransformHub` on project open; `SeismicViewPanel` publishes logical cursor moves via the engine's real `cursor_moved_3d` signal through a debounced gate. Seismic→well routing logs instead of silently swallowing.

## Single authorities preserved

DataCatalogService/SQLite — one catalog. LayerRegistry — one layer truth. `open_volume()` — one volume IO. TaskScheduler — one heavy queue. SelectionContext — one selection bus.
