# Testing Infrastructure & E2E Test Suite Architecture

## Overview

The Paleogeography Workbench (Paleo Workbench) uses a 4-tier end-to-end (E2E) testing framework designed for rigorous verification across all architectural layers: Runtime Stability, Mapping Engine 2.0, Geological Pipeline, Multi-View Coordination, and Data Lifecycle & Provenance.

```
tests/e2e/
├── conftest.py                   # Shared synthetic test fixtures, mock views & coordination hubs
├── test_tier1_features.py        # Tier 1: Feature Coverage (>=5 test cases per feature in isolation)
├── test_tier2_boundaries.py      # Tier 2: Boundary, Corner Case & Adversarial Stress Tests
├── test_tier3_interactions.py    # Tier 3: Cross-Feature Pairwise Integration Tests
└── test_tier4_scenarios.py       # Tier 4: Real-World End-to-End User Application Scenarios
```

---

## Environment & Execution

### Python Environment
- **Path**: `/home/kevin/.conda/envs/paleo312/bin/python`
- **Framework**: `pytest 9.1.1`, `pytest-qt 4.5.0`, `pytest-mock 3.15.1`
- **Scientific Stack**: `numpy`, `scipy`, `shapely`, `rasterio`, `pillow`, `matplotlib`, `pydantic`
- **UI Framework**: `PySide6 6.11.2` (Qt 6.11.2 offscreen/headless)

### Run Commands

```bash
# Run the entire E2E test suite
pytest tests/e2e/ -v

# Run individual tiers
pytest tests/e2e/test_tier1_features.py -v
pytest tests/e2e/test_tier2_boundaries.py -v
pytest tests/e2e/test_tier3_interactions.py -v
pytest tests/e2e/test_tier4_scenarios.py -v

# Run with short traceback
pytest tests/e2e/ -v --tb=short
```

---

## 4-Tier Test Architecture

### Tier 1 — Isolated Feature Coverage (`test_tier1_features.py`)
Validates individual functional units, classes, and algorithms in isolation with deterministic synthetic inputs.
- **Coverage**: All features F1 through F22 (including bug fix features #962–#1012 and Core Convergence F6–F22).
- **Assertions per feature**: >= 5 distinct functional assertions covering inputs, transformations, and outputs.

### Tier 2 — Boundary, Corner Case & Adversarial Stress (`test_tier2_boundaries.py`)
Validates edge cases, numerical singularities, non-finite values, and failure modes:
- Zero, negative, and extreme dimensions (aspect ratio 10,000:1, high DPI 1200).
- Inverted depth ranges, collinear interpolation singularities, and 100% NaN/nodata grids.
- Circular lineage graphs, locked/read-only file mutations, and corrupted JSON manifests.
- Multi-listener echo suppression under high-frequency selection updates.

### Tier 3 — Cross-Feature Pairwise Interactions (`test_tier3_interactions.py`)
Validates interaction contracts between decoupled modules:
- **Suite 10**: `Well Factor Extraction -> Kriging Interpolator -> Marching Squares Contours -> Facies Polygons -> MapDocument -> High-Res SVG Export`.
- **Suite 11**: `Map Click Selection -> CoordinateTransformHub (Well MD <-> 3D Map <-> Seismic Inline/TWT) -> SelectionContext -> Multi-View Synchronization (Map, Well Log, Seismic)`.
- **Suite 12**: `RAW Asset Ingest (0o444) -> Lineage Tracking -> Multi-Stage Asset Storage (Raw, Derived, Intermediate, Output) -> Atomic Project Manifest Persistence`.

### Tier 4 — Real-World Application Scenarios (`test_tier4_scenarios.py`)
Validates complete end-to-end production workflows:
- **Scenario 1**: Petroleum Exploration 3D Seismic Interpretation Pipeline.
- **Scenario 2**: Multi-Well Correlation & Chinese Well-Log Interpretation.
- **Scenario 3**: Multi-Horizon Facies Reconstruction & SVG Cartographic Publishing.
- **Scenario 4**: Enterprise Storage Resilience & Atomic Disaster Recovery.
- **Scenario 5**: Multi-Factor Environmental Spatial Modeling & Provenance Export.
- **Scenario 6**: Complete Geological Mapping & Multi-View Coordination Workflow (F6–F22 Full Cycle).

---

## Core Convergence Feature Matrix & Test Mapping

| Feature ID | Feature Description | Tier 1 Test Method | Tier 2 Boundary Method | Tier 3 / 4 Scenario |
|---|---|---|---|---|
| **F6** | Decoupled Map Layer Model & Document | `test_f6_decoupled_map_layer_models_and_document` | `test_f6_map_layer_zero_extent_empty_features` | Suite 10 / Scenario 6 |
| **F7** | Graduated & Categorized Renderers | `test_f7_graduated_and_style_renderers` | `test_f7_graduated_renderer_overlapping_and_inverted_bins` | Suite 10 / Scenario 6 |
| **F8** | Annotation Layer & Callout Symbology | `test_f8_annotation_layer_support` | `test_f8_annotation_layer_empty_text_extreme_rotations` | Suite 10 / Scenario 6 |
| **F9** | QGIS Bridge Backend Isolation | `test_f9_qgis_bridge_backend_isolation` | `test_f9_qgis_bridge_null_geometry_and_crs_mismatch` | Scenario 6 |
| **F10** | Canvas & Print Export Parity | `test_f10_canvas_and_export_parity` | `test_f10_canvas_export_extreme_scale_and_dpi` | Suite 10 / Scenario 6 |
| **F11** | Well Geological Factor Extraction | `test_f11_well_factor_extraction` | `test_f11_factor_extraction_missing_columns_and_all_nan_values` | Suite 10 / Scenario 6 |
| **F12** | Spatial Interpolation (Kriging / IDW) | `test_f12_spatial_interpolation_and_factor_grid_result` | `test_f12_interpolation_zero_points_and_collinear_singularities` | Suite 10 / Scenario 6 |
| **F13** | Marching Squares Vector Contouring | `test_f13_marching_squares_contouring` | `test_f13_marching_squares_all_nodata_and_constant_grids` | Suite 10 / Scenario 6 |
| **F14** | Facies Zone Polygonization | `test_f14_facies_zone_polygonization` | `test_f14_facies_polygonization_all_single_class_and_noisy_zones` | Suite 10 / Scenario 6 |
| **F15** | MapDocument Output Assembly | `test_f15_factor_map_document_generation` | `test_f15_map_document_generation_missing_layers_and_conflicting_crs` | Suite 10 / Scenario 6 |
| **F16** | Shared SelectionContext & Echo Guard | `test_f16_selection_context_engine` | `test_f16_selection_context_extreme_and_invalid_inputs` | Suite 11 / Scenario 6 |
| **F17** | CoordinateTransformHub (Map/Well/Seismic) | `test_f17_coordinate_transform_hub` | `test_f17_coordinate_transform_hub_out_of_bounds_and_singularities` | Suite 11 / Scenario 6 |
| **F18** | Incremental Multi-View Synchronization | `test_f18_incremental_multi_view_sync` | `test_f18_incremental_multi_view_sync_rapid_events_and_echo_cycles` | Suite 11 / Scenario 6 |
| **F19** | Raw Dataset Immutability (`0o444`) | `test_f19_raw_dataset_immutability` | `test_f19_raw_dataset_immutability_violation_rejection` | Suite 12 / Scenario 6 |
| **F20** | Asset Hierarchy (Raw/Derived/Inter/Out) | `test_f20_asset_hierarchy_and_storage` | `test_f20_asset_hierarchy_invalid_stages_and_trash_recovery` | Suite 12 / Scenario 6 |
| **F21** | Lineage Graph & Provenance Traversal | `test_f21_lineage_graph_and_provenance` | `test_f21_lineage_graph_circular_dependencies_and_orphan_nodes` | Suite 12 / Scenario 6 |
| **F22** | Atomic Project Persistence (*.paleo.json) | `test_f22_project_persistence_and_reopen` | `test_f22_project_persistence_corrupted_json_and_atomic_failure_recovery` | Suite 12 / Scenario 6 |

---

## Test Harness & Fixtures (`conftest.py`)

- `selection_context`: Thread-safe Qt signal-based `SelectionContext` fixture with source tagging and echo suppression.
- `coordinate_hub`: Bidirectional `CoordinateTransformHub` mapping between 2D/3D Map CRS, Well MD depths, and Seismic inline/crossline/TWT coordinates.
- `synthetic_kriging_points`: Deterministic 25-well spatial factor point distribution.
- `synthetic_seismic_cube`: 3D synthetic seismic volume `(50, 60, 100)` with descending inline indexes.
- `synthetic_well_logs`: Multi-curve well logs with Chinese curve name aliases and GB18030 encodings.
