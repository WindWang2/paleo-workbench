# Multi-Well Correlation Workbench Design Spec

**Date:** 2026-07-20  
**Status:** Approved  
**Target Package:** `geo-viz-engine/packages/geoviz_well_log/geoviz_well_log/section/` & `paleo_workbench/viz/hosts/well_section_host.py`

---

## 1. Executive Summary

The **Multi-Well Correlation Workbench (多井连井地层对比剖面)** extends the paleogeography visualization engine (`geoviz_well_log` & `paleo_workbench`) with cross-well stratigraphic correlation capabilities. It enables users to align multiple wells in sequence, switch between absolute depth elevation and datum horizon flattening, auto-connect horizon boundary polylines across wells, render semi-transparent inter-well facies polygon fills, and interactively adjust stratigraphic pinch-outs.

---

## 2. Architecture & Module Boundaries

The system is decoupled into a core section rendering engine inside `geoviz_well_log` and an application host component inside `paleo_workbench`:

```
geo-viz-engine/packages/geoviz_well_log/geoviz_well_log/
├── section/
│   ├── __init__.py
│   ├── datum_transformer.py      # Datum transformation logic (Depth <-> Flattened Canvas Y)
│   ├── inter_well_link.py        # Data models for horizon links & facies polygons
│   ├── section_track_group.py    # Per-well track group within section
│   └── section_canvas.py         # 2D QPainter Multi-Well Section Canvas (QWidget)
```

```
paleo_workbench/viz/
├── hosts/
│   └── well_section_host.py      # Integrated section workbench host (Toolbar + WellSectionCanvas)
```

---

## 3. Datum Flattening & Coordinate Transformation (`DatumTransformer`)

`DatumTransformer` manages depth-to-pixel $Y$ mapping across all wells in the section.

### 3.1 Absolute Depth Mode (绝对海拔深度模式)
Maps each well's measured depth directly to canvas $Y$:
$$Y(w_i, d) = Y_{\text{header}} + (d - d_{\text{global\_min}}) \times s_y$$

### 3.2 Datum Horizon Shift Mode (标志层拉平模式)
Given a selected datum horizon $H_{\text{datum}}$ with measured depth $d_{\text{datum}, i}$ for well $w_i$:
$$Y(w_i, d) = Y_{\text{datum\_line}} + (d - d_{\text{datum}, i}) \times s_y$$

- A horizontal dashed reference line is drawn across all wells at $Y_{\text{datum\_line}}$ annotated with `⚓ 拉平基准层: <Datum Name>`.

---

## 4. Cross-Well Inter-Well Rendering & Interaction

### 4.1 Horizon Boundary Links
For adjacent wells $W_k$ and $W_{k+1}$ sharing a common stratigraphic top boundary $H$:
- Computes endpoints $(X_{k, \text{right}}, Y(W_k, d_{H, k}))$ and $(X_{k+1, \text{left}}, Y(W_{k+1}, d_{H, k+1}))$.
- Renders smooth control polylines with boundary name labels across the inter-well gap (`inter_well_spacing`).

### 4.2 Facies Polygon Fills
Constructs quad polygons for matching facies intervals between adjacent wells:
- Polygon vertices: $[(X_{k, \text{right}}, Y_1), (X_{k+1, \text{left}}, Y_3), (X_{k+1, \text{left}}, Y_4), (X_{k, \text{right}}, Y_2)]$.
- Fills polygon with semi-transparent color matching the facies theme (`QColor(..., alpha=130)`).

### 4.3 Interactive Mouse Probe
- Hovering over inter-well zones displays real-time tooltips showing depth, horizon name, and facies classification.

---

## 5. UI Integration & Controls (`WellSectionHost`)

Integrated into `CompositeVisualizationPanel` as a dedicated tab: `🌐 多井对比剖面`.

### Toolbar Controls:
1. **Well Sequence Selector (`QComboBox` / Select Dialog)**: Choose and reorder wells (e.g., `HZ26-6-1 ➔ HZ27-10-1 ➔ XJ24-1-1X`).
2. **Datum Flattening Dropdown (`QComboBox`)**: Toggle between `绝对海拔深度` and `⚓ 按标志层拉平`.
3. **Inter-Well Spacing SpinBox (`QSpinBox`)**: Adjust horizontal gap between adjacent wells ($100\text{px} \sim 500\text{px}$).
4. **Facies Fill CheckBox (`QCheckBox`)**: Toggle inter-well facies color fills on/off.
5. **High-Res Export Button (`QPushButton`)**: Export cross-section diagram to PNG / PDF.

---

## 6. Testing & Quality Assurance

- Unit tests for `DatumTransformer` math under absolute TVD vs datum shifted modes.
- Rendering smoke tests for 2 to N well sequences.
- Integration tests ensuring zero regressions across `CompositeVisualizationPanel` tabs.
