# 04 — Test Strategy

Local-only verification (online CI intentionally not awaited or used as a
gate, per the goal contract). Environment: `run_env.sh` — offscreen Qt,
software GL, engine submodules on PYTHONPATH, PySide6 + numpy 2.4.6 +
pydantic 2.13.4 on python3.13.

## New test modules (this convergence)

| Module | Pins |
|---|---|
| test_geological_context_scenarios.py | scenarios A–D, calibration gate (refusal paths), echo/bleed, page-level sinks |
| test_paged_catalog_mode.py | SQL paging determinism, keyset, counts, aggregates, lazy model, paged-mode entry/exit, 100k budgets |
| test_composition_components.py | component contract (create/move/scale/configure/undo/z-order), serialization roundtrip + forward compat, 9-template library, binding resolution, every-component SVG (no placeholders), PNG/SVG/PDF physical-size + DPI |
| test_composition_panel_ui.py | editor panel state, bindings, export signal |
| test_horizon_picking_workflow.py | survey geometry mapping, sparse undoable picks, line interpolation, controller both ways, refusal without geometry |
| test_seismic_attributes_kernels.py | halo parity for 10 kernels, trace-global refusal, band seams (BLOCKER-pinned) |
| test_fault_interpretation_ui.py | break-line lift (direction excluded), save no-op, reopen roundtrip |
| test_unified_scene_extensions.py | VRAM boot wiring + ledger cap, stratal grid path ≡ dat path, probe highlight |
| test_curve_interpretation.py | numeric kernels, RAW immutability (bytes pinned), full provenance set, refusal paths |
| test_map_product.py | fail-closed validation, OUTPUT version + run lineage, fingerprint reproducibility |

## Regression sweep

Full `tests/` suite (514 files incl. e2e + perf) run locally before review;
results recorded in 07-final-verification.md. Existing suites for the
touched seams re-run per slice during development (data page, catalog,
navigation tree, asset table, composer, mapping page, seismic panel,
interpretation lifecycle, 3D page, joint host).
