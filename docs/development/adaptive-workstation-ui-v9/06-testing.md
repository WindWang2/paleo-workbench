# 06 — Testing (V9)

## New test assets

| File | Covers |
|---|---|
| `tests/test_dock_framework_v9.py` | descriptor registry contract; GL docks not floatable; viewport classification; grow-only resize authority; preset = visibility-only; HubScrollArea/AdaptivePageStack per-page minimum; constraint-stack floors; save wiring for all 13 docks; debounced responsive policy; restore-state normalization |
| `tests/test_ui_sizing_ratchet_v9.py` | structural ratchets: fixed ≥100px, min-width ≥400px, QDockWidget construction site, resizeDocks authority, non-collapsible splitters, theme-drifted stylesheets (snapshot-locked) |
| `tests/test_visual_qa_v9.py` + `ui/visual_qa_v9.py` | 6 adaptive-layout states with semantic gates: compact/wide/ultrawide viewport policies, narrow-window hub scroll degradation, preset keeps user sizes, agent grow-only |
| updated `tests/test_workstation_shell.py`, `tests/test_workstation_lifecycle.py` | V9 contract updates (floatability, responsive thresholds, content-driven dock minimums) |

## Semantic assertions (not pixel comparison)

Visual QA v9 asserts widget-level truths: inspector folded with the right flag, command-input floor values, central canvas ≥300px at 960-wide windows, hub dock minimum ≤80px (scroll host, not content minimum), user dock widths surviving preset apply, agent row not snapping back.

## How to run (local, batched — full-repo pytest is wasteful)

```bash
QT_QPA_PLATFORM=offscreen python -m pytest \
  tests/test_dock_framework_v9.py \
  tests/test_ui_sizing_ratchet_v9.py \
  tests/test_visual_qa_v9.py \
  tests/test_workstation_shell.py tests/test_workstation_lifecycle.py \
  tests/test_workstation_presets.py tests/test_layout_presets.py \
  tests/test_layout_persistence.py tests/test_shell_p0_fixes.py \
  tests/test_app.py tests/test_app_shell.py -q --timeout=600
```

Page-level batches for touched pages: `test_seismic_prediction_page.py`, `test_review_export_page.py`, `test_visualization_page.py`, `test_data_reader_panel.py`, `test_new_project_wizard.py`, `test_resource_summary.py`, `test_seismic_slice_preview_widget.py`, `test_project_well_map.py`.

Visual QA suites: `test_visual_qa_v6.py … v9.py` (35 tests). Perf: `tests/perf/test_catalog_scale.py`, `tests/perf/test_v8_goal_perf.py`.
