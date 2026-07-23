# 02 — Asynchronous AttributePipeline Engine & GIL-Release Worker

**What to build:**
Background QThread worker (`AttributeTaskWorker`) executing C++ accelerated 3D Coherence and Spectral Decomposition filtering via `NativeEngineBackend` with progress reporting (0-100%), cancellation tokens, and pure-Python parity fallbacks.

**Blocked by:** 01 — SeismicVolumeState & BinGridGeometry Coordinate Synchronization Observer

**Status:** ready-for-agent

- [ ] `AttributePipeline` executes C++ 3D Coherence and 3D Spectral Decomposition with GIL release.
- [ ] `AttributeTaskWorker` runs asynchronous calculations off main UI thread with progress signals.
- [ ] Supports cancellation tokens for instant task termination.
- [ ] Pure-Python fallback maintains `SymmetricParityContract`.
- [ ] Fully verified by unit tests in `tests/test_attribute_pipeline.py`.
