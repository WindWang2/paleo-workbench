# Geological Mapping Pipeline Architecture

**Document ID**: `CORE-CONV-02`  
**Version**: `1.0.0`  
**Status**: `Production / Complete`  
**Author**: Paleo Workbench Engineering Team  
**Scope**: Features F11, F12, F13, F14, F15 (Well Factor Extraction, Spatial Interpolation, Contouring, Polygonization, Factor MapDocument Generation)

---

## 1. Overview & Pipeline Workflow

The Geological Mapping Pipeline is an automated scientific workflow that ingests point-sampled borehole measurements and transforms them into continuous, topologically consistent, multi-layer cartographic models.

The pipeline comprises five discrete stages:
1. **Well Factor Extraction**: Queries well log intervals and stratigraphic tops to extract normalized geological variables (e.g. porosity, formation thickness, sand-to-gross ratio, total organic carbon).
2. **Spatial Interpolation**: Applies statistical and deterministic interpolation methods (Ordinary Kriging, Inverse Distance Weighting) across the spatial bounding box to generate a continuous 2D regular scalar grid (`FactorGridResult`).
3. **Marching Squares Contouring**: Traces isovalue contour curves across grid cells using automatic or fixed-interval leveling, generating valid topological LineString vector geometries.
4. **Facies Zone Polygonization**: Classifies continuous scalar values into discrete geological zones (facies boundaries) and converts raster masks into closed vector Polygons.
5. **MapDocument Assembly**: Synthesizes point, grid, contour, and polygon layers into an editable, multi-layer `MapDocument` with full provenance tracking.

```
+----------------------------------------------------------------------------------------------------+
|                                    GEOLOGICAL MAPPING PIPELINE                                      |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|  +--------------------+        +---------------------+        +---------------------------------+  |
|  | Well Log Database  |  --->  |  Factor Extraction  |  --->  | Extracted Well Factor Points    |  |
|  | Stratigraphic Tops |        |  Service            |        | [(X, Y, Val), CRS, Quality]     |  |
|  +--------------------+        +---------------------+        +----------------+----------------+  |
|                                                                                |                   |
|                                                                                v                   |
|  +--------------------+        +---------------------+        +----------------+----------------+  |
|  | Variogram Fitting  |  <---  | Spatial Estimator   |  <---  | Interpolation Parameter Bounds  |  |
|  | (Sill, Range, Ngt) |        | (Kriging / IDW)     |        | (Resolution, Extent, Power)     |  |
|  +--------------------+        +----------+----------+        +---------------------------------+  |
|                                           |                                                        |
|                                           v                                                        |
|                                +---------------------+                                             |
|                                |  FactorGridResult   |                                             |
|                                |  2D Matrix, Nodata  |                                             |
|                                +----+-------------+--+                                             |
|                                     |             |                                                |
|                   +-----------------+             +-------------------+                            |
|                   |                                                   |                            |
|                   v                                                   v                            |
|  +--------------------------------+                  +--------------------------------+            |
|  | Marching Squares Contouring    |                  | Facies Zone Polygonization     |            |
|  | - Auto / Fixed Leveling        |                  | - Threshold Classification     |            |
|  | - GeoJSON LineStrings          |                  | - Closed Vector Polygons       |            |
|  +----------------+---------------+                  +----------------+---------------+            |
|                   |                                                   |                            |
|                   +-----------------+             +-------------------+                            |
|                                     |             |                                                |
|                                     v             v                                                |
|                          +-----------------------------------+                                     |
|                          |    MapDocument Assembler Engine   |                                     |
|                          |  - WellPointMapLayer              |                                     |
|                          |  - GridMapLayer (Raster Mesh)     |                                     |
|                          |  - ContourMapLayer (LineStrings)  |                                     |
|                          |  - PolygonMapLayer (Facies Zones) |                                     |
|                          |  - AnnotationMapLayer             |                                     |
|                          |  - input_version_ids & run_id     |                                     |
|                          +-----------------+-----------------+                                     |
|                                            |                                                       |
|                                            v                                                       |
|                          +-----------------------------------+                                     |
|                          | Editable MapDocument (SVG/PNG/PDF)|                                     |
|                          +-----------------------------------+                                     |
+----------------------------------------------------------------------------------------------------+
```

---

## 2. Well Factor Extraction (Feature F11)

The extraction engine (`paleo_workbench/mapping/geological_pipeline/factor_extraction.py`) processes borehole measurement tables:

### 2.1 Extraction Mechanics
- **Horizon-Gated Interval Slicing**: Given a target horizon (e.g. `Top_Formation_A` to `Base_Formation_A`), the service queries well trajectory logs and identifies the measured depth (MD) interval $[MD_{\text{top}}, MD_{\text{base}}]$.
- **Geological Factor Computation**:
  - **Porosity ($\Phi$)**: Weighted average of neutron-density or sonic porosity curves over the horizon interval:
    $$\bar{\Phi} = \frac{1}{\Delta MD} \int_{MD_{\text{top}}}^{MD_{\text{base}}} \Phi(z) \, dz$$
  - **Net Sand Thickness ($H_{\text{sand}}$)**: Cumulative vertical thickness of intervals satisfying $V_{\text{shale}} \le V_{\text{cutoff}}$ and $\Phi \ge \Phi_{\text{cutoff}}$.
  - **Sand-to-Gross Ratio ($NTG$)**: Ratio of net sand thickness to gross stratigraphic interval thickness:
    $$NTG = \frac{H_{\text{sand}}}{MD_{\text{base}} - MD_{\text{top}}}$$
  - **Total Organic Carbon ($TOC$)**: Sourced from geochemistry core assays or $\Delta \log R$ log predictions.
- **Unit Normalization & Quality Filtering**: Normalizes units (e.g. fractional vs. percentage, meters vs. feet), drops NaN/null readings, and tags spatial coordinates with the project CRS.

---

## 3. Spatial Interpolation & FactorGridResult (Feature F12)

Spatial interpolation models (`paleo_workbench/mapping/geological_pipeline/interpolator.py`) convert irregularly distributed point observations into a dense regular grid.

### 3.1 Interpolation Algorithms
1. **Ordinary Kriging (OK)**:
   - Evaluates spatial autocorrelation via the empirical semi-variogram:
     $$\gamma(h) = \frac{1}{2 N(h)} \sum_{i=1}^{N(h)} (Z(x_i) - Z(x_i + h))^2$$
   - Fits theoretical variogram models:
     - **Spherical**: $\gamma(h) = c_0 + c \left[ 1.5 \left(\frac{h}{a}\right) - 0.5 \left(\frac{h}{a}\right)^3 \right]$ for $h \le a$
     - **Exponential**: $\gamma(h) = c_0 + c \left[ 1 - \exp\left(-\frac{3h}{a}\right) \right]$
     - **Gaussian**: $\gamma(h) = c_0 + c \left[ 1 - \exp\left(-\frac{3h^2}{a^2}\right) \right]$
     where $c_0$ is the nugget effect, $c$ is the partial sill, and $a$ is the spatial range.
   - Solves the Kriging system of linear equations with Lagrange multiplier $\mu$ to ensure unbiased minimum-variance estimates:
     $$\sum_{j=1}^N \lambda_j \gamma(x_i - x_j) + \mu = \gamma(x_i - x_0) \quad \forall i, \quad \sum_{j=1}^N \lambda_j = 1$$
2. **Inverse Distance Weighting (IDW)**:
   - Deterministic estimation based on inverse Euclidean distance with distance power $p$ (default $p=2.0$) and search radius $R$:
     $$Z(x_0) = \frac{\sum_{i=1}^k w_i Z(x_i)}{\sum_{i=1}^k w_i}, \quad w_i = \frac{1}{(d(x_0, x_i) + \epsilon)^p}$$

### 3.2 FactorGridResult Model
`FactorGridResult` (`paleo_workbench/workflow/factor_grid_result.py`) encapsulates the continuous 2D scalar field:
- `grid_x: np.ndarray`: 1D monotonic array of X coordinate cell centers.
- `grid_y: np.ndarray`: 1D monotonic array of Y coordinate cell centers.
- `grid_z: np.ndarray`: 2D $(M \times N)$ array containing estimated scalar values, with masked NaN for nodata cells.
- `crs: str`: Coordinate reference system identifier (e.g. `"EPSG:3857"`).
- `input_version_ids: list[str]`: Lineage pointers to raw input dataset versions.
- `run_id: str`: Unique execution identifier recorded in the data catalog.

---

## 4. Marching Squares Contouring (Feature F13)

The contour extraction module (`paleo_workbench/mapping/geological_pipeline/contouring.py`) applies an optimized Marching Squares algorithm to extract isovalue curves:

### 4.1 Leveling Strategies
- **Automatic Interval Leveling**: Computes clean round-number contour intervals based on data range $[\min Z, \max Z]$ and target line count $N_{\text{target}}$ (e.g. using standard $1, 2, 5 \times 10^k$ step increments).
- **Fixed Interval Leveling**: User-specified step $\Delta Z$ starting at base datum $Z_0$.
- **Custom Explicit Levels**: Arbitrary list of user-defined threshold values $[z_1, z_2, \dots, z_k]$.

### 4.2 Curve Extraction & Topology
- Evaluates each $2 \times 2$ grid cell, computing binary state indices ($\sum_{k=0}^3 b_k 2^k$) relative to threshold $Z_{\text{level}}$.
- Linearly interpolates exact boundary crossing coordinates along grid cell edges:
  $$x_{\text{cross}} = x_1 + (x_2 - x_1) \cdot \frac{Z_{\text{level}} - Z_1}{Z_2 - Z_1}$$
- Chains unordered line segments into continuous, topologically closed loops or boundary-terminated open paths.
- Emits standard GeoJSON `FeatureCollection` containing `LineString` and `MultiLineString` features with elevation attributes.

---

## 5. Facies Zone Polygonization (Feature F14)

The polygonization engine (`paleo_workbench/mapping/geological_pipeline/polygonization.py`) segments continuous scalar fields into distinct geological facies zones:

### 5.1 Classification & Vectorization
- **Threshold Binning**: Groups grid cells into discrete category classes (e.g. Class 1: $< 0.10$, Class 2: $0.10 - 0.20$, Class 3: $\ge 0.20$).
- **Raster-to-Vector Polygon Extraction**: Traces external and internal (hole) boundaries for connected component regions using topological boundary walkers.
- **Topological Clean-up**: Eliminates sub-pixel sliver polygons, resolves self-intersections, and outputs valid GeoJSON `Polygon` and `MultiPolygon` geometries.

---

## 6. Factor MapDocument Generation (Feature F15)

The pipeline synthesis engine (`paleo_workbench/mapping/geological_pipeline/pipeline.py`) unifies all extracted components into a cohesive `MapDocument`:

```python
def build_factor_map_document(
    name: str,
    target_horizon: str,
    factor_type: str,
    grid_result: FactorGridResult,
    contours: dict | None = None,
    facies_polygons: list[dict] | None = None,
    wells: list[dict] | None = None,
    project_crs: str = "EPSG:3857",
    run_id: str | None = None,
    input_version_ids: list[str] | None = None,
) -> MapDocument:
    ...
```

### Layer Hierarchy in Compiled MapDocument
1. **`GridMapLayer`** (Base): Renders the continuous color-ramped scalar surface.
2. **`PolygonMapLayer`**: Overlays geological facies zones with semi-transparent hatching or solid classification fills.
3. **`ContourMapLayer`**: Draws major and minor isovalue contour curves with elevation text labels.
4. **`WellPointMapLayer`**: Displays borehole locations, well names, and spot measurement values.
5. **`AnnotationMapLayer`**: Places map title, geological formation banner, north arrow, graphic scale bar, and color legend.

All generated layers inherit `source_version_id` and metadata `run_id`, guaranteeing full lineage traceability from raw well log files to published maps.

---

## 7. Verification Summary

The Geological Mapping Pipeline is verified by:
- `tests/test_geological_mapping_pipeline.py`: End-to-end factor extraction $\to$ Kriging/IDW $\to$ Marching Squares $\to$ MapDocument assembly.
- `tests/test_factor_*.py`: Variogram model fitting, numerical interpolation stability, boundary edge cases.
- `tests/test_catalog_lineage_chain.py`: Lineage chain traversal from raw well inputs to compiled MapDocuments.
- `tests/e2e/test_tier1_features.py` (F11–F15) & `tests/e2e/test_tier4_scenarios.py` (Scenario 2: Geological Mapping E2E).
