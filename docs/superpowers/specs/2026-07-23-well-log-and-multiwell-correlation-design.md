# Well Log Analysis & Multi-Well Correlation Workbench Design Specification

## Problem Statement

Geologists and stratigraphers working in the Paleo Workbench need to inspect well log curves (e.g. GR, SP, NPHI, RHOB), perform multi-well stratigraphic section comparisons, apply datum flattening along target horizon tops, and utilize Dynamic Time Warping (DTW) for automated well-to-well log curve correlation.

Currently, multi-well correlation across large oilfields with dozens of wells and hundreds of log curves can suffer from rendering lag during depth scrolling, manual alignment friction, and inconsistent handling of missing lithology interval symbols.

## Solution

Build a deep, high-performance **Well Log Analysis & Multi-Well Correlation Workbench** powered by C++ accelerated LAS parsing (`LASParserProvider`), 4-point Min-Max LOD curve rendering, dynamic lithology interval fills (`LithologyTrack`), datum horizon flattening (`DatumFlattening`), and automated DTW curve alignment.

Key features include:
1. **Accelerated LAS Parsing & LOD Rendering**: Direct C++ memory block extraction for LAS files (`fast_las_parse_data`) coupled with 4-point Min-Max curve downsampling for 60 FPS viewport scrolling.
2. **Multi-Track Visualization**: Flexible multi-track layout supporting `CurveTrack` (log curves with customizable display ranges), `LithologyTrack` (sandstone, mudstone, limestone patterns), and `WellIntervals` (formation tops and sequence boundaries).
3. **Datum Horizon Flattening**: One-click flattening of multi-well cross-sections relative to a selected stratigraphic horizon top (e.g., H1, H2).
4. **Automated DTW Curve Correlation**: Dynamic Time Warping algorithm matching curve signatures between key reference wells and target exploratory wells.

## User Stories

1. As a stratigrapher, I want to load raw LAS 2.0/3.0 log files instantaneously using C++ accelerated parsing, so that I can inspect Gamma Ray and Resistivity curves without file parsing delays.
2. As a well site geologist, I want well log curves to use 4-point Min-Max downsampling during depth zooming and scrolling, so that the viewport maintains a constant 60 FPS refresh rate.
3. As a geologist, I want to view lithology interval tracks alongside log curves with standardized patterns (sandstone, shale, dolomite), so that I can quickly spot reservoir sand bodies.
4. As a stratigrapher, I want to select a target horizon top (e.g., "Top Reservoir") and flatten all cross-section wells to that datum plane, so that I can analyze lateral thickness variations across the basin.
5. As an exploration geologist, I want to run automated DTW curve matching between a reference well and a new target well, so that initial formation top picks are suggested automatically.
6. As a visualizer, I want to export multi-well cross-section figures as high-resolution SVG or PDF files, so that I can include professional stratigraphic correlation charts in exploration reports.
7. As a developer, I want pure-Python fallbacks for all C++ LAS parsing and curve downsampling functions, so that the system runs reliably across all operating systems.

## Implementation Decisions

1. **Integrated Multi-Track Layout (`WellLogHost` & `WellSectionHost`)**:
   - `WellSectionHost` encapsulates multi-well cross-sections, instantiating track containers for curves, lithology, and formation tops.
   - Leverages `VisualizationWorkspace` to load `VizPayload(kind="well_log")` or `VizPayload(kind="cross_well")`.

2. **C++ LAS Parse Provider (`LASParserProvider`)**:
   - Injected into engine startup via `set_las_parser_provider(cpp_las_parse_func)`.
   - Bypasses intermediate dict allocations for direct numpy array construction.

3. **Datum Horizon Flattening Engine (`DatumFlattening`)**:
   - Shifts vertical depth coordinates ($z_{\text{flattened}} = z_{\text{true}} - z_{\text{datum}}$) for every well in the cross-section payload upon horizon selection.

4. **Dynamic Time Warping Matcher (`DTWLogMatcher`)**:
   - Computes optimal non-linear depth alignment path between normalized log curves of two wells using dynamic programming.

## Testing Decisions

1. **Test Philosophy**:
   - Test end-to-end depth calculations, track data models, and datum flattening transformations through headless API seams without creating full PySide6 OS windows.

2. **Target Modules & Seams**:
   - **`tests/test_well_section_workbench.py`**: Validates multi-well cross-section loading, track data structure consistency, and `DatumFlattening` coordinate shifts.
   - **`tests/test_las_parser_provider.py`**: Validates C++ `LASParserProvider` execution, NULL value handling, and fallback parity.
   - **`tests/test_dtw_log_matcher.py`**: Validates DTW alignment curve warping and top candidate generation.

3. **Prior Art**:
   - Follows pattern of `tests/test_well_log_core_hardening.py` and `tests/test_composite_visualization_panel.py`.

## Out of Scope

- Real-time 3D well path trajectory steering (handled by 3D Geological Modeling page).
- Interactive petrophysical Archie equation saturation solver.

## Further Notes

- Fully compliant with `CONTEXT.md` domain vocabulary and existing `VizPayload` data structures.
