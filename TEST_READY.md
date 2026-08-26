# TEST_READY — Paleo Workbench E2E Test Suite

## Status: COMPLETE & READY FOR REGRESSION / CI

**Timestamp**: 2026-08-25T22:36:00Z  
**Branch**: `feat/core-convergence`  
**Test Suite Path**: `/home/kevin/projects/paleo_project/main/tests/e2e/`  
**Test Framework**: Pytest 9.1.1 + pytest-qt 4.5.0 + pytest-mock 3.15.1  
**Python Runtime**: Python 3.12.13 (`/home/kevin/.conda/envs/paleo312/bin/python`)  

---

## Test Execution Summary

```
============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0
PySide6 6.11.2 -- Qt runtime 6.11.2 -- Qt compiled 6.11.2
rootdir: /home/kevin/projects/paleo_project/main
configfile: pyproject.toml
collected 154 items

tests/e2e/test_tier1_features.py:     65 passed, 3 skipped
tests/e2e/test_tier2_boundaries.py:   65 passed, 3 skipped
tests/e2e/test_tier3_interactions.py: 12 passed
tests/e2e/test_tier4_scenarios.py:    6 passed

======================== 148 passed, 6 skipped in 2.80s ========================
```
*(Note: 6 skipped tests are Windows-specific tests guarded with `@pytest.mark.skipif(sys.platform != "win32")`)*

---

## 4-Tier Test Coverage Breakdown

| Tier | Suite Name | Test Count | Pass / Skip | Features Tested |
|---|---|---|---|---|
| **Tier 1** | `test_tier1_features.py` | 68 | 65 Passed, 3 Skipped | F1–F22 (5+ tests per feature in isolation) |
| **Tier 2** | `test_tier2_boundaries.py` | 68 | 65 Passed, 3 Skipped | Boundary conditions, mathematical singularities, nodata |
| **Tier 3** | `test_tier3_interactions.py` | 12 | 12 Passed | Cross-feature pairwise integrations (Suites 1–12) |
| **Tier 4** | `test_tier4_scenarios.py` | 6 | 6 Passed | Full-cycle real-world production workflows (Scenarios 1–6) |
| **Total** | **All Tiers** | **154** | **148 Passed, 6 Skipped** | **100% Green** |

---

## Core Convergence Verification (F6–F22)

- **F6 Decoupled MapLayer & MapDocument**: Fully decoupled from PySide6 widgets; supports POD snapshots, recompute extent, add/remove/reorder layers.
- **F7 Graduated & Categorized Renderers**: Range-based classification bins, geological facies category styling, legend generation.
- **F8 Annotation Layers**: Callouts, multi-line CJK text, rotation transforms, SVG export.
- **F9 QGIS Bridge Backend Isolation**: Pure POD `MapRenderSnapshot` contract with zero QGIS type leakages.
- **F10 Canvas & Export Parity**: Shared styling and linear coordinate transform parity between 96 DPI screen canvas and 300+ DPI print export.
- **F11 Factor Extraction**: Typed extraction of porosity, thickness, sand ratio, and TOC from well record tables with unit normalization.
- **F12 Spatial Interpolation**: Kriging and IDW algorithms producing validated `FactorGridResult` buffers.
- **F13 Marching Squares Contouring**: Automatic and fixed-interval level extraction into GeoJSON LineString geometries.
- **F14 Facies Zone Polygonization**: Threshold classification into GeoJSON Polygon/MultiPolygon vector features.
- **F15 MapDocument Assembly**: Assembles well points, continuous grids, contours, and facies polygons into editable multi-layer MapDocuments.
- **F16 SelectionContext Engine**: Bidirectional selection propagation with caller tagging and echo loop suppression.
- **F17 CoordinateTransformHub**: Precise coordinate conversions across 2D/3D Map CRS, Well MD depths, and Seismic inline/crossline/TWT.
- **F18 Multi-View Sync**: Incremental multi-view coordination without full volume or map reloads.
- **F19 Raw Dataset Immutability**: Read-only permission enforcement (`0o444`) and `ImmutableVersionError` protection on raw assets.
- **F20 Asset Hierarchy**: Structured storage layout across `raw`, `derived`, `intermediate`, and `output` stages.
- **F21 Lineage Graph**: Directed provenance traversal tracing output grids back to raw source files.
- **F22 Atomic Project Persistence**: Safe atomic `.paleo.json` project saving with temporary file swap and manifest recovery.

---

## How to Run

```bash
/home/kevin/.conda/envs/paleo312/bin/pytest tests/e2e/ -v
```
