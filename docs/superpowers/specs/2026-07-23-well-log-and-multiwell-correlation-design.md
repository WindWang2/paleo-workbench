# Well Log Analysis & Multi-Well Correlation Workbench Specification

## Problem Statement

Geologists, stratigraphers, and interpreters working in Paleo Workbench need to inspect well log curves (GR, SP, NPHI, RHOB), perform multi-well stratigraphic section comparisons, apply datum horizon flattening, and utilize Dynamic Time Warping (DTW) for automated well-to-well log curve correlation.

Currently, multi-well correlation across large oilfields with dozens of wells can suffer from:
1. **Structural Dip Distortion**: Displaying wells solely by measured depth (MD) obscures depositional thickness and facies variations across dipping structures or fault blocks.
2. **Manual Alignment Friction**: Correlating formation tops manually across multiple wells is tedious and lacks automated depth recommendation assistance.
3. **Disconnected 2D/3D Context**: 2D well correlation charts are often isolated from 3D seismic volume backgrounds and 3D viewport spatial fence curtains.

## Solution

Build a deep, high-performance **Well Log Analysis & Multi-Well Correlation Workbench** powered by:
1. **Multi-Mode Datum Alignment Policy (`WellSectionDatum`)**: Supports 3 vertical depth alignment modes: Measured Depth (MD/TVD), Subsea Elevation (TVDSS), and Stratigraphic Horizon Flattening ($Z=0$ at target marker top) to analyze depositional thickness without structural dip distortion.
2. **Interactive Top Correlator & DTW Recommender (`FormationTopCorrelator`)**: Renders inter-well correlation polygon bands and handles marker line drag-adjustments. Integrates `DTWLogMatcher.transfer_top_index` to compute automated non-linear depth alignment recommendations across wells with confidence scores.
3. **Bidirectional 2D/3D Seismic Fence Projection (`CrossWellFenceGenerator`)**: Extracts inter-well seismic slices along multi-well trajectories to render seismic amplitude background in 2D `WellSectionHost` and project vertical 3D curtain meshes into 3D OpenGL viewports.
4. **Accelerated LAS Parsing & LOD Rendering (`LASParserProvider`)**: Injects C++ `fast_las_parse_data` provider hook for zero-overhead multi-well log parsing and 4-point Min-Max LOD curve downsampling.

## User Stories

1. As a stratigrapher, I want to load raw LAS log files instantaneously using C++ accelerated parsing, so that I can inspect Gamma Ray and Resistivity curves without file parsing delays.
2. As a well site geologist, I want well log curves to use 4-point Min-Max downsampling during depth zooming and scrolling, so that the viewport maintains a constant 60 FPS refresh rate.
3. As a geologist, I want to view lithology interval tracks alongside log curves with standardized patterns (sandstone, shale, dolomite), so that I can quickly spot reservoir sand bodies.
4. As a stratigrapher, I want to select a target horizon top (e.g., "Top Reservoir") and flatten all cross-section wells to that datum plane ($Z=0$), so that I can analyze lateral thickness variations without structural dip distortion.
5. As an exploration geologist, I want to run automated DTW curve matching between a reference well and a target well, so that initial formation top picks are suggested automatically with confidence scores.
6. As an interpreter, I want inter-well seismic amplitude background rendered behind log tracks in the 2D section and projected as a 3D fence curtain in the 3D viewport, so that well-seismic tie context is preserved.
7. As a visualizer, I want to export multi-well cross-section figures as high-resolution SVG or PDF files, so that I can include professional stratigraphic correlation charts in exploration reports.

## Implementation Decisions

- **`WellSectionDatum` Multi-Mode Datum Engine**:
  - `align_depths(wells, mode="horizon", target_marker="H1")`: Computes depth shifts $z_{\text{aligned}} = z_{\text{true}} - z_{\text{datum}}$ for each well track depending on selected mode.
- **`FormationTopCorrelator` Interactive Engine**:
  - Manages correlation polygon bands between adjacent wells.
  - Connects marker drag events to `DTWLogMatcher.transfer_top_index()` to compute suggested depth markers on target wells.
- **`CrossWellFenceGenerator` 2D/3D Projection Engine**:
  - Samples seismic 3D volume along piecewise multi-well path $(X_i, Y_i) \to (X_{i+1}, Y_{i+1})$.
  - Outputs 2D seismic background slice for `WellSectionHost` and 3D GL mesh curtain for `GeologicalModeling3DPage`.
- **`WellSectionHost` & `VisualizationWorkspace` Integration**:
  - `WellSectionHost` encapsulates multi-well cross-sections, instantiating track containers for curves, lithology, and formation tops.
  - Integrates with `VisualizationWorkspace` to load `VizPayload(kind="cross_well")`.
- **ADR Compliance**:
  - Fully compliant with `docs/adr/0003-multiwell-correlation-architecture.md` and `CONTEXT.md` vocabulary (`WellSectionDatum`, `FormationTopCorrelator`, `CrossWellFenceGenerator`).

## Testing Decisions

- **Test Philosophy**:
  - Test end-to-end depth calculations, track data models, and datum flattening transformations through headless API seams without creating full PySide6 OS windows.
- **Target Modules & Seams**:
  - **`tests/test_well_section_datum.py`**: Validates `WellSectionDatum` coordinate transformations for MD, TVDSS, and Horizon Flattening ($Z=0$).
  - **`tests/test_formation_top_correlator.py`**: Validates `FormationTopCorrelator` marker drag-adjustments, correlation polygon band geometry, and DTW auto-recommendations.
  - **`tests/test_cross_well_fence.py`**: Validates `CrossWellFenceGenerator` 3D fence curtain mesh generation and 2D seismic slice extraction along multi-well trajectory paths.
  - **`tests/test_well_section_workbench.py`**: Validates `WellSectionHost` multi-well cross-section integration and payload loading.
- **Prior Art**:
  - Follows pattern of `tests/test_dtw_log_matcher.py` and `tests/test_las_parser_provider.py`.

## Out of Scope

- Real-time 3D well path trajectory steering (handled by 3D Geological Modeling page).
- Interactive petrophysical Archie equation saturation solver.

## Further Notes

- Fully compliant with `CONTEXT.md` domain vocabulary and existing `VizPayload` data structures.
