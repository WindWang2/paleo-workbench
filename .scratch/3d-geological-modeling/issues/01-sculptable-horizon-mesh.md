# 01 — SculptableHorizonMesh Data Structure & Sparse Delta Patch Undo Engine

**What to build:**
Stateful 3D horizon surface mesh representation with RBF radial brush sculpting and a sparse delta patch undo/redo stack (`sculpt_surface`, `smooth_anneal`, `undo`, `redo`), ensuring 60 FPS interactive editing on 500k+ vertex meshes without full mesh duplication.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] `SculptableHorizonMesh` encapsulates 3D vertex positions `(N, 3)`, triangle face indices `(M, 3)`, and grid spatial metadata.
- [ ] `sculpt_surface()` deforms vertex heights within a radial brush sphere using Gaussian RBF weighting and records sparse delta patches `{indices, old_z, new_z}` on the undo stack.
- [ ] `undo()` and `redo()` restore modified vertices in-place without cloning unmodified vertices.
- [ ] Fully verified by unit tests in `tests/test_horizon_sculpting.py`.
