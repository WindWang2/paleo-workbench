# 02 — WellSectionHost Multi-Well Cross-Section & DatumFlattening Engine

**What to build:**
Multi-well cross-section track rendering with dynamic horizon top flattening ($z_{\text{flattened}} = z_{\text{true}} - z_{\text{datum}}$) and `VisualizationWorkspace` integration.

**Blocked by:** 01 — C++ LASParserProvider & Min-Max LOD Curve Downsampling

**Status:** ready-for-agent

- [ ] `WellSectionHost` renders multi-well cross-sections (`CurveTrack`, `LithologyTrack`, `WellIntervals`).
- [ ] `DatumFlattening` shifts vertical depths relative to a selected stratigraphic horizon top.
- [ ] `VisualizationWorkspace` loads `VizPayload(kind="cross_well")` seamlessly.
- [ ] Fully verified by unit tests in `tests/test_well_section_workbench.py`.
