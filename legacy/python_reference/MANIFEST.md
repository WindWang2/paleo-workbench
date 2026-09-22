# legacy/python_reference — MANIFEST

Machine-readable per-file record: `metadata/retirement_manifest.json`
(1909 entries; every archived source is a `git mv` — zero deletions).

## Summary (from retirement_manifest.json)

| classification | entries |
|---|---|
| LEGACY_PRODUCT_IMPLEMENTATION (`product/paleo_workbench/**` + `src/**` + docs/prototypes) | 688 |
| LEGACY_PRODUCT_TEST (`tests/**`, incl. original conftest) | 828 |
| SCRATCH (`scratch/**`, `.scratch-*.py`, one-off runners) | 60 |
| LEGACY_PRODUCT_BENCHMARK (benchmarks/scripts measuring retired code) | 26 |
| LEGACY_PRODUCT_LAUNCHER (`run_app.py`, `run.bat`, `run-venv.bat`, `build_catalog.py`) | 4 |
| LEGACY_PRODUCT_EXAMPLE (retired plugin-API examples) | 3 |
| PRODUCT_ASSET_STAGED (assets moved to `resources/`, history follows the move) | 150 |
| REFERENCE_COPY (inert duplicates kept so the archive stays importable) | 150 |

## Per-module native replacement truth (verbatim join with
`docs/development/cpp-final-closure/migration-matrix.json`, base `0936779e`)

| matrix final_classification | modules | meaning here |
|---|---|---|
| NATIVE_PRODUCT | 205 | complete wired runtime-reachable C++ replacement exists |
| PARTIAL_NATIVE | 77 | partial per-module attribution; product-level replacement via `pwb-platform` |
| LEGACY_REFERENCE | 395 | no 1:1 native unit; replaced at product granularity by the C++ application |
| NATIVE_LIBRARY_NOT_WIRED | 1 | `mapping/geological_pipeline/native_bind.py` — library exists, unwired |

`python_runtime_required = 0`, `python_modules_packaged = 0` for every row.
Empty `cpp_replacement` in the JSON means *no per-module attribution* — it
is never filled speculatively.
