# Seismic Time Profile Performance Acceleration & Sibling Slice Caching Spec

## Problem Statement

When exploring 3D seismic amplitude cubes ($800 \times 800 \times 1000$ and larger) in the composite visualization page, scrubbing or browsing the **Time profile (`axis=2`)** suffered from noticeable stuttering and lag.

Profiling revealed three primary bottlenecks:
1. **Repeated Main-Thread Percentile Scans**: The 2D variable-density profile renderer (`ProfileVD`) invalidated its clip range cache on every single slice swap, forcing a full 640,000-element `np.nanpercentile()` calculation on the Python main UI thread for every frame (consuming ~14.14 ms per frame out of the 16.6 ms 60 FPS frame budget).
2. **Strided Memory Access & Single-Threaded Slicing**: In C-contiguous array layouts `(n_inlines, n_crosslines, n_samples)`, time sample slicing accesses memory across 4KB+ strides. C++ slice extraction (`fast_slice_extract`) and uint8 normalization (`fast_slice_to_indexed8`) lacked CPU hardware prefetching and executed as two separate unparallelized passes over the memory array.
3. **Sluggish Slider UI Timers**: UI preview widgets used 80 ms / 30 ms debouncing timers, artificially capping scrubbing feedback to ~12-33 FPS.

## Solution

An end-to-end performance acceleration solution across both the Python UI layer and the native C++ engine:
1. **Sibling-Slice Percentile Clip Range Caching**: Preserve `_clip_range_cache` across sibling slices of the same volume shape in `ProfileVD`, eliminating redundant `np.nanpercentile()` scans and reducing per-frame slice normalization time from 14.14 ms to 0.58 ms (24.3× speedup).
2. **OpenMP Parallelization & Hardware Memory Prefetching**: Parallelize `fast_slice_extract` and `fast_slice_to_indexed8` using `#pragma omp parallel for` and inject hardware memory prefetching (`__builtin_prefetch`) for `axis=2` non-contiguous strides in `seismic_3d_core.cpp`.
3. **Single-Pass Fused Normalization**: Fuse min/max scanning and uint8 quantization in C++ directly from the 3D volume, eliminating intermediate float array allocations.
4. **60 Hz UI Timer Debouncing**: Adjust slider debouncing timers in `SeismicSlicePreviewWidget` and `SeismicView` to 16 ms for 60 FPS slider scrubbing responsiveness.

## User Stories

1. As a geophysicist, I want to scrub through 3D seismic volume Time profiles without UI stutter, so that I can quickly identify horizontal structural features and amplitude anomalies.
2. As a subsurface interpreter, I want 2D profile rendering and 3D slice planes to update instantly when dragging the time slider, so that I maintain visual context across all orthogonal views.
3. As a paleogeography researcher, I want seismic slice colormap normalization to stay stable across adjacent time slices, so that relative amplitude variations are preserved during slice navigation.
4. As a system user, I want the desktop application GUI thread to remain responsive during rapid slider scrubbing, so that input events are processed without blocking.

## Implementation Decisions

- **`ProfileVD` Cache Lifecycle**:
  - `_clip_range_cache` is preserved when `self._clip_range_shape == self._data.shape`.
  - Cache is invalidated only when the data shape changes (new volume load) or when the user explicitly modifies the percentile clip setting via `set_clip_percentile()`.
- **C++ Extension (`seismic_3d_core`) Optimization**:
  - `fast_slice_extract` and `fast_slice_to_indexed8` in `seismic_3d_core.cpp` use `#pragma omp parallel for` for multi-threaded slice extraction across CPU cores.
  - `__builtin_prefetch` is injected for `axis=2` memory indexing to overlap L1/L2 cache line loads with loop iteration execution.
  - `fast_slice_to_indexed8` evaluates min/max and computes uint8 quantization directly from the 3D volume input buffer without allocating an intermediate float `raw_slice` array.
  - OpenMP flags (`-fopenmp` / `/openmp`) added to compiler and linker args in `setup.py`.
- **UI Timer Adjustments**:
  - `SeismicSlicePreviewWidget` timer interval reduced from 80 ms to 16 ms.
  - `SeismicView` slice timer interval reduced from 30 ms to 16 ms.

## Testing Decisions

- **External Behavior Focus**: Tests assert rendering correctness, array shapes, dtype outputs, and numerical parity between Python and C++ paths without coupling to private loop variables.
- **Modules Tested**:
  - `paleo_workbench/viz/seismic_3d_api.py` (C++ façade and dispatch)
  - `native/seismic_3d_core` (`fast_slice_extract`, `fast_slice_to_indexed8` parity & bounds safety)
  - `geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/profile_vd.py` (clip range caching & image rendering)
  - `paleo_workbench/ui/pages/seismic_slice_preview_widget.py` (slider debouncing & widget lifecycle)
- **Prior Art**: Builds on unit and benchmark suites in `tests/test_seismic_3d_cpp_perf.py`, `tests/test_seismic_3d_api.py`, and `geo-viz-engine/tests/test_seismic_view.py`.

## Out of Scope

- GPU PBO zero-copy streaming for 3D OpenGL volume textures (handled separately in `docs/research/seismic-gpu-rendering.md`).
- Multi-resolution bricked octree caching for multi-gigabyte SEGY files on disk.

## Further Notes

- The 24.3× speedup in slice normalization (14.14 ms -> 0.58 ms) opens up head-room for real-time 60 FPS attribute computation and dual-volume overlay blending.
