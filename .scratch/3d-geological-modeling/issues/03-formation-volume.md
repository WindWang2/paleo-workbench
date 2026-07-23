# 03 — FormationVolumeIntegrator Closed Mesh Integration Engine

**What to build:**
Automatic side-wall mesh strip generation between top ($H_{top}$) and bottom ($H_{bot}$) horizons to form a watertight 3D Polyhedron Mesh, evaluating exact reservoir volume via Gauss Divergence Theorem surface integrals.

**Blocked by:** 01 — SculptableHorizonMesh Data Structure & Sparse Delta Patch Undo Engine, 02 — FaultDisplacement Kinematic Vector Field Engine

**Status:** ready-for-agent

- [ ] `FormationVolumeIntegrator` constructs vertical side-wall quadrilateral/triangle strips connecting top and bottom horizon boundaries.
- [ ] Verifies mesh closure/watertightness and evaluates surface integrals via Gauss Divergence Theorem.
- [ ] Fully verified by unit tests in `tests/test_formation_volume.py`.
