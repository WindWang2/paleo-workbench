# Unified Multi-View Coordination Architecture

**Document ID**: `CORE-CONV-03`  
**Version**: `1.0.0`  
**Status**: `Production / Complete`  
**Author**: Paleo Workbench Engineering Team  
**Scope**: Features F16, F17, F18 (SelectionContext Engine, CoordinateTransformHub, Incremental Multi-View Synchronization)

---

## 1. Overview & Architectural Motivation

In integrated geoscience workflows, interpreters continuously transition between spatial map representations, 1D/2D vertical well log tracks, and 3D seismic volumes. Prior to Core Convergence, view interactions were isolated or relied on heavyweight dataset reloads, causing UI freezing and state desynchronization.

The Multi-View Coordination subsystem provides:
1. **Source-Tagged `SelectionContext`**: A centralized event hub managing active selections across all domain views while preventing recursive echo loops via source tagging.
2. **`CoordinateTransformHub`**: A mathematically rigorous coordinate conversion engine bridging 2D/3D Geographic Map CRS, Well Trajectory depth metrics (MD, TVD, TVDSS), and 3D Seismic grid coordinates (Inline, Crossline, TWT).
3. **Lightweight Incremental Synchronization**: Viewport updates, cursor projections, and selection highlights update in real time ($< 16\text{ ms}$) without re-instantiating heavy volumetric or raster datasets.

```
+----------------------------------------------------------------------------------------------------+
|                                    MULTI-VIEW VISUALIZATION TIER                                   |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|    +------------------------+      +------------------------+      +--------------------------+    |
|    |      Map Canvas        |      |      Well Log View     |      |      3D Seismic View     |    |
|    |  (UnifiedMapCanvas)    |      |    (WellLogCanvas)     |      |   (Seismic3DCanvas)      |    |
|    |  - Well Points (X, Y)  |      |  - Log Curves (MD/TVD) |      |  - 3D Cube (IL, XL, TWT) |    |
|    |  - Facies & Contours   |      |  - Tops & Stratigraphy |      |  - Well Trajectory Paths |    |
|    +-----------+------------+      +-----------+------------+      +------------+-------------+    |
|                ^                               ^                                ^                  |
|                |                               |                                |                  |
|                +-------------------------------+--------------------------------+                  |
|                                                |                                                   |
|                         [selection_changed(ctx)] | [request_transform(pt)]                         |
|                                                v                                                   |
|                +----------------------------------------------------------------+                  |
|                |                   SelectionContext Engine                      |                  |
|                |  - active_well_id: str | None                                  |                  |
|                |  - selected_well_ids: list[str]                                |                  |
|                |  - depth_range: tuple[float, float] | None                     |                  |
|                |  - seismic_cursor: tuple[int, int, float] | None               |                  |
|                |  - source_widget_id: str (Echo Loop Suppression Guard)         |                  |
|                +-------------------------------+--------------------------------+                  |
|                                                |                                                   |
|                                                v                                                   |
|                +----------------------------------------------------------------+                  |
|                |                   CoordinateTransformHub                       |                  |
|                |  - map_to_well(x, y) -> str | None                             |                  |
|                |  - well_depth_to_map(well_id, md) -> (x, y, tvd)               |                  |
|                |  - seismic_to_map(il, xl, twt) -> (x, y, z)                    |                  |
|                |  - map_to_seismic(x, y, z) -> (il, xl, twt)                    |                  |
|                +----------------------------------------------------------------+                  |
|                                                                                                    |
+----------------------------------------------------------------------------------------------------+
```

---

## 2. SelectionContext Engine (Feature F16)

The `SelectionContext` class (`paleo_workbench/viz/selection_context.py`) maintains the canonical cross-view interaction state:

```python
@dataclass
class SelectionContext:
    active_well_id: str | None = None
    selected_well_ids: list[str] = field(default_factory=list)
    depth_range: tuple[float, float] | None = None  # (min_depth, max_depth) in MD meters
    seismic_cursor: tuple[int, int, float] | None = None  # (inline, crossline, twt_ms)
    source_widget_id: str | None = None  # Originating view identifier
    timestamp_ns: int = field(default_factory=time.time_ns)
```

### 2.1 Echo-Loop Suppression
When a user clicks a well in the Map Canvas:
1. `UnifiedMapCanvas` emits a `SelectionContext(active_well_id="W-101", source_widget_id="map_canvas")`.
2. The `SelectionContextEngine` broadcasts the updated state to all registered views.
3. `WellLogCanvas` receives the update, identifies `source_widget_id != "well_log_canvas"`, and focuses well `W-101`.
4. `UnifiedMapCanvas` receives its own broadcast, recognizes `source_widget_id == "map_canvas"`, and ignores the event, breaking potential feedback cycles.

---

## 3. CoordinateTransformHub (Feature F17)

The `CoordinateTransformHub` (`paleo_workbench/viz/coordinate_hub.py`) encapsulates all spatial conversions between spatial reference frames:

### 3.1 Mathematical Transformation Spaces
1. **Map Coordinate Space $(X, Y)_{\text{CRS}}$**: Projected geographic coordinates (e.g. UTM Easting/Northing in meters).
2. **Well Trajectory Space $(MD, \text{TVD}, \text{TVDSS}, X, Y)$**:
   - **Measured Depth ($MD$)**: Length along borehole path from rotary table / surface Kelly bushing.
   - **True Vertical Depth ($TVD$)**: Vertical distance below surface datum:
     $$TVD(MD) = \int_0^{MD} \cos(\theta(s)) \, ds$$
     where $\theta(s)$ is the borehole inclination angle.
   - **Subsea True Vertical Depth ($TVDSS$)**: $TVDSS = TVD - \text{KB\_Elevation}$.
   - **Borehole Drift ($X, Y$)**:
     $$X(MD) = X_{\text{surface}} + \int_0^{MD} \sin(\theta(s)) \sin(\phi(s)) \, ds$$
     $$Y(MD) = Y_{\text{surface}} + \int_0^{MD} \sin(\theta(s)) \cos(\phi(s)) \, ds$$
     where $\phi(s)$ is the azimuth angle.
3. **3D Seismic Grid Space $(\text{Inline}, \text{Crossline}, TWT)$**:
   - **Affine Transform to Map Coordinates**:
     $$\begin{pmatrix} X \\ Y \end{pmatrix} = \begin{pmatrix} X_0 \\ Y_0 \end{pmatrix} + \begin{pmatrix} \Delta X_{il} & \Delta X_{xl} \\ \Delta Y_{il} & \Delta Y_{xl} \end{pmatrix} \begin{pmatrix} \text{Inline} - IL_0 \\ \text{Crossline} - XL_0 \end{pmatrix}$$
   - **Time-to-Depth Conversion (TWT $\leftrightarrow$ TVD)**: Utilizes checkshot velocity surveys or calibrated time-depth functions $V_{\text{int}}(z)$:
     $$TWT(TVD) = 2 \int_0^{TVD} \frac{1}{V(z)} \, dz$$

### 3.2 TransformHub API
- `map_to_well(x: float, y: float, tolerance_m: float = 100.0) -> str | None`: Spatial nearest-neighbor query identifying well collar within tolerance.
- `well_depth_to_map(well_id: str, md: float) -> tuple[float, float, float]`: Evaluates deviated trajectory spline returning $(X, Y, TVD)$.
- `seismic_to_map(il: int, xl: int, twt: float) -> tuple[float, float, float]`: Converts seismic grid position to geographic $(X, Y, Z_{\text{depth}})$.
- `map_to_seismic(x: float, y: float, z: float) -> tuple[int, int, float]`: Inverts geographic position to seismic $(\text{Inline}, \text{Crossline}, TWT)$.

---

## 4. Incremental Multi-View Synchronization (Feature F18)

Synchronization across views operates strictly on lightweight state mutations:

### 4.1 Synchronized Workflows
- **Map $\leftrightarrow$ Well Log Selection**:
  - Selecting a well point in the Map Canvas highlights the well item and scrolls the Well Log view to the corresponding log tracks.
  - Selecting a formation top in the Well Log view broadcasts the depth interval $[MD_{\text{top}}, MD_{\text{base}}]$, highlighting the well location on the map and updating the active horizon in the mapping shelf.
- **Seismic Probe $\leftrightarrow$ Map Navigation**:
  - Dragging the 3D seismic probe slice updates `seismic_cursor=(IL, XL, TWT)`.
  - The Map Canvas renders an interactive intersection line showing the exact ground track of the active seismic line.
  - The Well-Tie module updates the synthetic seismogram overlay corresponding to the intersecting borehole.

### 4.2 Performance Characteristics
- Selection propagation latency: $< 5\text{ ms}$.
- Zero memory reallocation: No volume slicing or raster mesh re-triangulation occurs on selection events.

---

## 5. Verification Summary

Multi-view coordination is verified by:
- `tests/test_selection_context.py`: Multi-source event dispatch and echo loop suppression.
- `tests/test_coordinate_hub.py`: Bidirectional mathematical accuracy across Map, Deviated Well, and Seismic survey coordinate frames.
- `tests/e2e/test_tier1_features.py` (F16–F18) & `tests/e2e/test_tier3_interactions.py` (Suite 5: Map $\leftrightarrow$ Well Log $\leftrightarrow$ Seismic Coordination).
