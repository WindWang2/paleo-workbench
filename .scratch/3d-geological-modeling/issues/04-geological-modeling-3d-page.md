# 04 — GeologicalModeling3DPage Host Surface & OpenGL Viewport Integration

**What to build:**
Integrated 3D modeling page featuring an OpenGL surface viewport, interactive sculpting brush tools, fault vector controls, volume calculation panel, and `VisualizationWorkspace` payload integration.

**Blocked by:** 01 — SculptableHorizonMesh Data Structure & Sparse Delta Patch Undo Engine, 02 — FaultDisplacement Kinematic Vector Field Engine, 03 — FormationVolumeIntegrator Closed Mesh Integration Engine

**Status:** ready-for-agent

- [ ] `GeologicalModeling3DPage` hosts 3D OpenGL viewport (`SurfaceWidget`) with interactive sculpting and fault controls.
- [ ] Integrates with `VisualizationWorkspace` to load and display surface payloads and volume integration results.
- [ ] Fully verified by unit tests in `tests/test_geological_modeling_3d_page.py`.
