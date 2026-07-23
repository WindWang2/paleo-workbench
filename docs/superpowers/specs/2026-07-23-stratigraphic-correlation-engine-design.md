# Stratigraphic Correlation Engine Architecture Specification

## Problem Statement

As Paleo Workbench expanded its multi-well analysis capabilities, low-level stratigraphic calculations (vertical depth datum shifts, Dynamic Time Warping curve matching, and inter-well correlation quad polygons) were scattered across separate helper classes (`WellSectionDatum`, `DTWLogMatcher`, and `FormationTopCorrelator`). 

Callers in UI pages (`StratigraphyCorrelationPage`, `WellSectionHost`) had to manually orchestrate data transformations across these disconnected modules, leading to:
1. **High Call Site Complexity**: UI components were forced to handle coordinate math, array indexing, and DTW cost matrix evaluation manually.
2. **Brittle Testability**: Testing end-to-end multi-well correlation required setting up complex UI widget states rather than querying a single deep domain engine.

## Solution

Deepen the multi-well correlation architecture by introducing **`StratigraphicCorrelationEngine`**, a unified Fluent Pipeline Builder module (`paleo_workbench/viz/stratigraphic_correlation_engine.py`) that encapsulates datum shift policies, DTW log curve alignment, and correlation polygon quad calculations behind an expressive, chainable domain interface.

Key features of the deepened architecture include:
1. **Fluent Pipeline Interface (`with_wells().with_datum().with_layout().with_dtw_config()`)**: Allows callers to incrementally configure multi-well datasets, alignment modes, horizontal layout coordinates, and DTW parameters.
2. **Unified Terminal Execution (`execute()`)**: Runs end-to-end multi-well section evaluation and returns a single `CorrelationSectionResult` containing all datum shifts, inter-well polygon quads, DTW alignments, and top depth recommendations.
3. **Headless Domain Testability**: Enables 100% headless testing of multi-well correlation logic without instantiating PySide6 UI widgets.

## User Stories

1. As a stratigrapher, I want to configure multi-well correlation parameters fluently using an expressive builder interface, so that I can chain configuration calls without handling complex keyword argument dictionaries.
2. As a well site geologist, I want the correlation engine to compute vertical depth shifts for MD, TVDSS, and Horizon Flattening ($Z=0$) automatically, so that structural dip distortion is eliminated across dipping formations.
3. As an exploration geologist, I want the correlation engine to calculate DTW curve alignment paths between adjacent wells, so that automated formation top depth recommendations with confidence scores are generated.
4. As a visualizer, I want the correlation engine to produce quad polygon geometries for matching formation intervals, so that inter-well correlation bands can be rendered cleanly on cross-section canvases.
5. As a developer, I want all sub-engines (`WellSectionDatum`, `DTWLogMatcher`, `FormationTopCorrelator`) to be injectable into `StratigraphicCorrelationEngine`, so that unit testing and mocking remain straightforward.

## Implementation Decisions

- **`StratigraphicCorrelationEngine` Fluent Builder**:
  - `with_wells(wells)`: Binds multi-well data dictionaries (containing names, depths, curves, and tops).
  - `with_datum(mode, target_horizon, kb_elevations)`: Configures depth alignment policy (`"md"`, `"tvdss"`, or `"horizon"`).
  - `with_layout(x_positions)`: Sets horizontal X layout coordinates for well tracks.
  - `with_dtw_config(window, depth_step)`: Configures DTW window size and depth sampling step.
  - `execute(top_names, curve_key)`: Triggers full correlation evaluation and returns `CorrelationSectionResult`.
- **Domain Result Model (`CorrelationSectionResult`)**:
  - `shifts`: `dict[str, float]` mapping well name to vertical depth shift.
  - `polygons`: `list[dict]` containing quad coordinates `(4, 2)` for inter-well correlation bands.
  - `recommendations`: `dict[str, TopRecommendation]` holding DTW depth suggestions and confidence scores.
  - `alignments`: `dict[tuple[str, str], AlignmentResult]` storing DTW cost matrix alignment paths.
- **ADR & Domain Vocabulary Compliance**:
  - Registered as a domain concept in `CONTEXT.md`.
  - Compliant with ADR 0003 (`docs/adr/0003-multiwell-correlation-architecture.md`).

## Testing Decisions

- **Test Philosophy**:
  - Tests should focus exclusively on external domain behavior, validating that the fluent builder correctly configures sub-engines, calculates datum shifts, generates polygon quads, and produces DTW recommendations through headless Python API calls.
- **Target Modules**:
  - `tests/test_stratigraphic_correlation_engine.py`: Validates fluent method chaining, `execute()` output products, and `recommend_top()` calculations.
  - `tests/test_well_section_datum.py`: Validates individual datum shift calculations for MD, TVDSS, and Horizon modes.
  - `tests/test_formation_top_correlator.py`: Validates polygon quad geometry and DTW recommendation integration.
- **Prior Art**:
  - Follows pattern of `tests/test_well_section_workbench.py` and `tests/test_dtw_log_matcher.py`.

## Out of Scope

- Direct PySide6 QPainter canvas rendering logic (handled by `WellSectionHost` and `WellSectionCanvas`).
- Real-time 3D OpenGL viewport mesh rendering (handled by `CrossWellFenceGenerator` and `GeologicalModeling3DPage`).

## Further Notes

- Fully compatible with existing `VizPayload` data structures and `geoviz` engine bindings.
