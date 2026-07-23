# ADR 0003: Multi-Well Correlation & Well-Tie Architecture

* **Status**: Accepted
* **Date**: 2026-07-23
* **Deciders**: Paleo Workbench Core Architecture Team

## Context

Geoscientists using Paleo Workbench require a high-performance, interactive **Multi-Well Correlation & Well-Tie Workbench** to:
1. Parse multi-well LAS curves rapidly via C++ `LASParserProvider`.
2. Perform automated and interactive formation top correlations across adjacent wells.
3. Flatten correlation sections along key marker horizons (`WellSectionDatum`).
4. Visualize 2D well sections backed by seismic amplitude background and 3D fence curtains (`CrossWellFenceGenerator`).

Static 2D well section displays fail when wells have dipping structures, non-linear depositional thickness variations, or structural fault offsets.

## Decision

We adopt an integrated Multi-Well Correlation Architecture composed of four core modules:

1. **`WellSectionDatum`**: Supports 3 vertical alignment modes:
   - Measured Depth (MD / TVD)
   - Subsea Elevation (TVDSS)
   - Stratigraphic Horizon Flattening ($Z=0$ at target marker top)
2. **`FormationTopCorrelator`**: Renders inter-well correlation polygon bands and handles marker line drag-adjustments. Integrates `DTWLogMatcher.transfer_top_index` to compute automated non-linear depth alignment recommendations across wells with confidence scores.
3. **`CrossWellFenceGenerator`**: Extracts inter-well seismic slices along multi-well trajectories and projects 2D correlation sections into 3D OpenGL viewports as vertical curtain meshes.
4. **`LASParserProvider`**: Acceleration provider hook enabling C++ `fast_las_parse_data` for zero-overhead multi-well log parsing.

## Consequences

### Positive
- Geologists can inspect stratigraphic thickness changes by flattening key marker horizons without structural dip distortion.
- Combines automated DTW alignment with expert interactive drag-and-drop marker editing.
- Bidirectional 2D/3D well-seismic tie context keeps 2D sections and 3D viewports synchronized.

### Negative / Trade-offs
- Higher UI state complexity when switching between MD, TVDSS, and Horizon Flattening modes.
- Requires 3D fence mesh recalculation when well trajectory paths or horizon selections change.
