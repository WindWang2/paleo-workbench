# 07 — Known Limitations

## Full100g physical volume not materialized — extrapolated

`benchmarks/generate_synthetic_segy.py --preset full100g` (5000×5000×1000 ≈ 106 GB) was not written to disk in this environment. `benchmarks/acceptance_100g.py` runs the full chain on a **quick2g** preset (1024×1024×512 ≈ 2.4 GB, same chunk/shard/codec as production) and extrapolates full100g wall times in `04-benchmarks.md` (marked `[extrapolated]`). The extrapolation is linear in band/tile counts where halo fraction shrinks, so it is an upper bound.

## VRAM: viewport-proportional but no GL-frame benchmark on quick2g

`VramTextureCache` (L2, 1 GiB ledger from #1078) is the production VRAM authority (verified by `tests/test_vram_texture_cache.py` + `benchmarks/vram_l2_hit_benchmark.py` on the main branch). The LOD render path added here keeps `VRAM usage ≈ viewport pixels` (only viewport sub-slices are uploaded; L1/L2 are the only caches). No new per-frame GL timing was captured on quick2g — the per-panel LOD tests and the LodPolicy frame-budget tests cover correctness; frame budget conformance on a real GL context should be captured as a follow-up benchmark on a GPU host.

## Well-trajectory depth model

`CoordinateTransformHub` registers wells with surface x/y + a per-well station table sourced from `well.metadata["survey_stations"]` (forward-compatible passthrough). Today no production loader writes stations there — the well catalog entity carries KB/TD but not a full trajectory table, so seismic TWT→TVD/MD uses the default velocity model (2000 m/s) until a trajectory loader lands.

## QGIS bridge: syntax-level C++ verification

The `qgis_render_bridge` C++ edits (`VectorLayerSpec` wire fields, data-defined rotation/size/color, buffer_color) were verified with `g++ -fsyntax-only` + vendored QGIS stubs + Qt6 headers. No vendored QGIS build env was available locally for a full compile+link. Follow-up: validate the labeling XML round-trip in a QGIS-linked build.

## Native well-log rendering untested locally

`import welllog` raises `ImportError: GLIBCXX_3.4.35 not found` on this conda libstdc++. The ImportError probe contract is `ImportError → "not installed"` so the real environment correctly falls back to Legacy QPainter (pinned by tests). Engine-path rendering needs a host with the built binding + GLIBCXX 3.4.35.

## Pre-existing test failures on main (not introduced here)

- `tests/test_map_line_label.py::test_mapping_page_wires_layer_visibility_and_property` — fails on `main` too (unrelated to the marketing/map panes touched).
- `test_native_backend.py::test_map_edit_core_version...` — requires `map_edit_core` native build.
- `test_welllog_engine_native_integration.py::test_binding_contract_not_silently_skipped` — intentionally red without a built binding ([blocked]).
