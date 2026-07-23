# 01 — SeismicVolumeState & BinGridGeometry Coordinate Synchronization Observer

**What to build:**
Stateful slice coordinate observer (`inline_idx`, `crossline_idx`, `t_slice_idx`) with `BinGridGeometry` grid-to-geographic affine coordinate transformation and `slice_changed` signal emissions for 2D/3D view synchronization.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] `SeismicVolumeState` encapsulates active slice indices and horizon selections.
- [ ] `BinGridGeometry` provides bi-directional affine conversion between (IL, XL) grid space and (Easting, Northing) geographic space.
- [ ] Emits `slice_changed` signal when slice indices change.
- [ ] Fully verified by unit tests in `tests/test_seismic_volume_state.py`.
