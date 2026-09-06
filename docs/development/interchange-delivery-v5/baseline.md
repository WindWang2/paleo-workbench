# Baseline — Geoscience Interchange, Project Packaging & Batch Delivery V5

Branch: `feat/interchange-delivery-v5` (base: `origin/main` @ `049423ab`).

## What exists today (source-audited, 2026-09-06)

### Format capability matrix (I0 audit)

| Format | Read | Inspect | Import (catalog) | Export | Roundtrip | CRS | Unit | Cataloged | Tests |
|---|---|---|---|---|---|---|---|---|---|
| LAS (.las) | Y (native `well_log_core.fast_las_parse_data` + geoviz `las_preview.inspect_las_file` + lasio fallback for wrapped) | Y (`inspect_las_file`: V/W/C sections, NULL, DLM) | Y (catalog `import_raw` via data page) | partial (LAS→CSV/XLSX/JSON summary via lasio; **no LAS writer**) | N/A | n/a (depth) | parsed but discarded by native path; kept by `inspect_las_file` | Y | `tests/test_las_parser_provider.py`, `tests/test_issue842_las_async.py`, `tests/test_exporters.py`, GVE `test_geoviz_well_log_preview.py` |
| DLIS (.dlis) | N in app (C++ `DlisSourceAdapter` exists in well-log-engine submodule, **not bound to Python**; no `dlisio` dep) | N | N | N | N | n/a | n/a | N | C++ only: WLE `tests/integration/dlis_adapter_test.cpp` |
| CSV/TSV | Y (`table_parsers.table_preview`, fixed delimiter by extension, UTF-8-sig→replace) | partial (bounded chunk probe; no delimiter sniffing) | Y (generic import; no CSV→WellTable mapping) | Y (`table_to_json`, `table_to_xlsx`) | partial | n/a | n/a | Y | `tests/test_preview_bom_and_field_limit.py`, `tests/test_data_import_service.py` |
| Excel (.xlsx/.xls) | Y (pandas/openpyxl, first sheet) | partial (sheet names) | Y (generic) | Y (CSV→XLSX) | partial | n/a | n/a | Y | `tests/test_exporters.py` |
| SEG-Y (.sgy/.segy) | Y (segyio; structured + unstructured; preview capped 128³) | Y (`segy_preview`, `SeismicLoader.inspect`, trace/sample/iline/xline fields) | Y (link/import + `transcode_segy_to_zarr` derived zarr-v3 with resume/cancel/source identity) | **N (no SEG-Y writer anywhere)** | n/a | coord scalar handled in loader | sample interval µs in header | Y | `tests/test_transcode_segy_zarr.py`, `tests/test_chunked_volume_reader.py`, GVE `test_seismic_loader.py` |
| Shapefile/GeoPackage/other OGR | Y (GDAL `ReferenceLayerService`, layer 0, CRS mandatory) | partial (layer 0 only) | Y (reference layer; not into editable model) | **N (no OGR write path)** | N | Y (osr, traditional GIS order) | n/a | reference only | `tests/test_reference_layers.py` |
| GeoJSON | Y (hand-written FeatureCollection parse; facies grouping) | Y (`geojson_document_summary`) | Y (map payload) | Y (layer export, `geojson_normalize`) | Y | string member only | n/a | Y (via map products) | `tests/test_geojson_facies_layers.py` |
| GeoTIFF | Y (rasterio preview + GDAL reference preview) | Y (CRS/bounds/dtype/nodata) | Y (reference) | **N user-facing** (internal RGBA mirror only) | N | Y (metadata) | n/a | reference only | `tests/test_preview_settings.py`, `tests/test_reference_layers.py` |
| Factor grid | Y (`.factor_grid.npz` V1/V2, atomic, descriptor JSON) | Y | Y (persisted artifacts + catalog) | N (npz internal) | Y | explicit field | unit field | Y | `tests/test_grid_artifact.py` |
| FLAC3D (.f3grid) / Abaqus (.inp) | N (no readers) | N | N | Y (hand-written writers, #829 grammar) | N | n/a | n/a | Y (`_register_mesh_export`) | `tests/test_issues_825_829_846.py` |
| VTK/OBJ/STL | N | N | N | N | N | — | — | N | none |
| Map export | — | — | — | Y (PNG/SVG/PDF composer + canvas + QGIS bridge vector) | — | — | — | Y (`record_export` choke point) | `tests/test_map_export_consistency.py` |
| Project (.paleo.json) | Y (atomic 3-phase save, .bak recovery, relativized paths) | Y | — | — | Y | strings | — | — | `tests/test_project_manager.py`, `tests/test_async_project_save.py` |
| Project package | **N (no bundle/zip packaging exists)** | — | — | — | — | — | — | — | none |

### Key existing services the interchange layer must build on

- `paleo_workbench/catalog/service.py` — `DataCatalogService` (lifecycle authority): `import_raw`, `link_external`, `materialize_external`, `register_version/register_output/register_intermediate/register_result_asset/register_derived_store`, `create_working_copy/commit_working_copy`, `register_run`, `promote_version`, `verify_integrity`, `audit`, `export_manifest`, `resolve_path`, `rebase_artifact_paths`, `get_lineage_chain`.
- `paleo_workbench/catalog/storage.py` — atomic managed placement with streaming sha256, content store `blobs/`, stage dirs.
- `paleo_workbench/catalog/checksum.py` — `sha256_file` (1 MiB chunks).
- `paleo_workbench/catalog/port.py` — `CatalogPort` seam + `CoreCatalogAdapter` (`.service` for full surface).
- `paleo_workbench/project/artifacts.py:record_export` — single export choke point (ExportArtifact + catalog OUTPUT).
- `paleo_workbench/providers/` — Provider SDK; `ProviderFamily.IMPORTER` and `DATA_FORMAT` families exist with **no built-ins yet**.
- `paleo_workbench/resources/` — classifier/io_registry/import_service/export_service/preview parsers/exporters (existing shallow IO layer).
- GDAL vendored build (`third_party/gdal+proj`, ADR 0060) — optional at runtime, lazily probed; rasterio>=1.3 is a hard dep.
- segyio (via geo-viz-engine), lasio, pandas/openpyxl — available.
- Tests run via `run_env.sh` (offscreen Qt, PYTHONPATH to geoviz packages, python3.13).

## Gaps this goal closes

1. No unified format adapter contract — format knowledge is scattered across preview parsers, import_service, exporters, reference_layers, seismic modules.
2. Extension-only format classification (`classifier.py`), no magic/header sniffing.
3. No import preflight/plan lifecycle; failed imports can leave half-registered state in caller code paths.
4. No export verification (write success ≠ verified output).
5. No portable project package (bundle manifest + checksums + reopen elsewhere).
6. No external-dependency audit/relink assistance.
7. No batch conversion orchestration (bounded concurrency, cancellation, per-item isolation).
8. No delivery profiles / machine-readable delivery QA report.
9. No package-level path-safety hardening (zip traversal, symlink, name collisions).
