# 02 — FaultDisplacement Kinematic Vector Field Engine

**What to build:**
Spatial kinematic displacement vector field $\vec{D}(\vec{x})$ for 3D fault plane geometries (Dip, Strike, Throw Magnitude), deforming horizon surface vertices across hanging-wall and footwall blocks without self-intersection artifacts.

**Blocked by:** 01 — SculptableHorizonMesh Data Structure & Sparse Delta Patch Undo Engine

**Status:** ready-for-agent

- [ ] `FaultDisplacement` calculates spatial displacement vector maps across hanging-wall and footwall blocks.
- [ ] Applies Gaussian distance decay along fault plane normal vectors to deform horizon meshes smoothly.
- [ ] Fully verified by unit tests in `tests/test_fault_displacement.py`.
