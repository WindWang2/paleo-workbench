# 03 — CrossWellFenceGenerator Bidirectional 2D/3D Seismic Fence Projection Engine

**What to build:**
Extracts inter-well seismic slices along multi-well trajectory paths, rendering seismic background in 2D `WellSectionHost` and projecting 3D curtain meshes into 3D OpenGL viewports.

**Blocked by:** 01 — WellSectionDatum Multi-Mode Datum Alignment Engine, 02 — FormationTopCorrelator Interactive Tops Correlation & DTW Recommender Engine

**Status:** ready-for-agent

- [ ] `CrossWellFenceGenerator` extracts 2D seismic background slice along multi-well trajectory path $(X_i, Y_i) \to (X_{i+1}, Y_{i+1})$.
- [ ] Generates 3D curtain GL mesh for 3D viewports.
- [ ] Fully verified by unit tests in `tests/test_cross_well_fence.py`.
