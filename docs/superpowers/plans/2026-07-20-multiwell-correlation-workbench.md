# Multi-Well Correlation Workbench Implementation Plan

**Spec:** `docs/superpowers/specs/2026-07-20-multiwell-correlation-workbench-design.md`  
**Date:** 2026-07-20  

---

## User Review Required

> [!IMPORTANT]
> This plan breaks down the creation of the Multi-Well Correlation Workbench into 5 self-contained, test-driven tasks.

---

## Task 1: Create `DatumTransformer` for Depth Coordinate Mapping

**Files to create/modify:**
- `geo-viz-engine/packages/geoviz_well_log/geoviz_well_log/section/datum_transformer.py`
- `geo-viz-engine/packages/geoviz_well_log/geoviz_well_log/section/__init__.py`
- `geo-viz-engine/packages/geoviz_well_log/tests/test_datum_transformer.py`

**Steps:**
1. Implement `DatumTransformer` supporting both `absolute` depth mode and `datum_shift` mode.
2. Calculate depth-to-canvas $Y$ coordinates and datum line positions.
3. Write unit tests covering both coordinate transformation modes.

---

## Task 2: Create Inter-Well Horizon Links & Facies Quad Polygon Fills

**Files to create/modify:**
- `geo-viz-engine/packages/geoviz_well_log/geoviz_well_log/section/inter_well_link.py`

**Steps:**
1. Define `HorizonLink` and `FaciesQuad` data classes.
2. Implement `paint_horizon_link` using smooth Bezier splines and `paint_facies_quad` using `QPainterPath` semi-transparent fills (`alpha=130`).
3. Add unit tests for inter-well polygon path generation.

---

## Task 3: Create `WellSectionCanvas` 2D Painter Component

**Files to create/modify:**
- `geo-viz-engine/packages/geoviz_well_log/geoviz_well_log/section/section_canvas.py`
- `geo-viz-engine/packages/geoviz_well_log/geoviz_well_log/__init__.py`

**Steps:**
1. Implement `WellSectionCanvas` inheriting `QWidget` with `WA_OpaquePaintEvent`.
2. Manage per-well track groups, inter-well spacing, and cross-well horizon/facies rendering.
3. Add real-time mouse hover probe (`QToolTip`) and depth crosshair overlay across all wells.

---

## Task 4: Integrate `WellSectionHost` & `CompositeVisualizationPanel`

**Files to create/modify:**
- `paleo_workbench/viz/hosts/well_section_host.py`
- `paleo_workbench/ui/pages/composite_visualization_panel.py`

**Steps:**
1. Create `WellSectionHost` with top control bar (Well Selector, Datum Dropdown, Spacing Spinbox, Facies Fill Checkbox, PNG/PDF Export).
2. Integrate `WellSectionHost` into `CompositeVisualizationPanel` as `🌐 多井对比剖面` tab.

---

## Task 5: End-to-End Testing & Verification

**Files to create/modify:**
- `tests/test_well_section_workbench.py`

**Steps:**
1. Test multi-well loading, datum flattening toggling, and export functionality.
2. Run `QT_QPA_PLATFORM=offscreen python -m pytest tests/` to ensure 100% clean test suite.
