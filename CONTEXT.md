# Paleo Workbench Domain Model & Vocabulary

This document records the ubiquitous domain language and module architecture for the Paleo Workbench codebase.

## Core Modules & Architecture Vocabulary

### NativeEngineBackend
A deep, centralized backend module (`paleo_workbench/native_backend.py`) that encapsulates C++ native extension loading (`seismic_3d_core`, `well_log_core`, `map_edit_core`), GIL-release execution policies, pure-Python fallback implementations, and visualization engine hook injections (`install_all_hooks()`).

### AccelerationProvider
A high-performance algorithm provider (such as C++ 4-point LOD downsampling `minmax_downsample`, fast 2D slice extraction `fast_slice_extract`, or Marching Tetrahedra `marching_cubes_3d`) injected into the `geoviz` engine or called by workbench UI widgets.

### SymmetricParityContract
An architectural invariant requiring that every native C++ algorithm has an identical pure-Python fallback implementation, verified by unit tests asserting `C++ output == Python output` within floating-point tolerance.

### DisabledAccelerationSeam
A context-manager seam (`with native_backend.disabled_acceleration():`) allowing tests and diagnostic code to temporarily bypass C++ native extensions and execute pure-Python fallback paths cleanly without monkey-patching private module variables.

### DataAssetRegistry
A deep, unified asset pipeline module (`paleo_workbench/resources/data_asset_registry.py`) that encapsulates asset classification, directory scanning, format provider registration (`FormatSpec`), preview widget parsing, and export formatting behind a small 4-method interface (`inspect`, `scan_directory`, `parse_preview`, `export`).

### VisualizationWorkspace
A deep composite visualization module (`paleo_workbench/ui/pages/composite_visualization_panel.py`) that encapsulates multi-tab widget instantiation, dataset payload routing, synchronized cross-canvas viewports, and snapshot vector/raster exports behind a 2-method interface (`load`, `export_snapshot`), replacing shallow host adapters.

### SeismicVolumeState
A centralized, event-driven state observer module (`paleo_workbench/viz/seismic_volume_state.py`) that encapsulates 3D slice coordinates (`inline_idx`, `crossline_idx`, `t_slice_idx`), active horizon selections, and `BinGridGeometry` spatial coordinate transformations behind a 2-method interface (`sync_slice`, `convert_coord`) with dual 2D/3D profile view synchronization.

### FormatSpec
A single-point registration specification data structure that bundles an asset format's classification rules (extensions/magic bytes), preview parser callable, and exporter provider into one place.

---

## Domain Concepts

### Well Log Visualization
- **CurveTrack**: Native QPainter track widget displaying depth-aligned log curves with 4-point Min-Max LOD downsampling.
- **LithologyTrack**: Track displaying geological lithology patterns (sandstone, mudstone, limestone, dolomite).
- **WellIntervals**: Formation tops, series, system, and facies interval data mapped along well depth.

### Seismic 3D & 2D Profile
- **SeismicVolume**: 3D SEG-Y volume data indexed by Inline, Crossline, and Time/Depth.
- **SliceReadWorker**: Asynchronous QThread worker using priority queues and neighborhood prefetching for stutter-free slice navigation.
- **Coherence3D**: 3D seismic attribute calculating similarity/coherence across inline, crossline, and sample vertical windows.
- **AttributePipeline**: Asynchronous, GIL-releasing seismic attribute calculation engine (`paleo_workbench/viz/seismic_3d_api.py` / `geoviz_seismic/attribute_pipeline.py`) that dispatches C++ accelerated filtering (3D Coherence, Spectral Decomposition, Dip/Azimuth) via `NativeEngineBackend` workers with progress reporting and cancellation tokens.
- **SeismicPredictionTask**: Stateful AI interpretation task model (`paleo_workbench/services/prediction_service.py`) binding a target `SeismicVolume` and well constraints to deep neural network inference.
- **ClassMap**: Discrete uint8 3D volume or 2D horizon grid representing predicted geological facies/fracture codes (e.g., 1: Fan Delta, 2: Shoreface, 3: Lacustrine Mud).
- **ProbMap**: Continuous float32 3D volume or 2D grid storing model Softmax confidence probabilities (0.0 to 1.0) used for alpha-blended transparency rendering in `VisualizationWorkspace`.
- **Isosurface**: 3D triangle mesh extracted via Marching Tetrahedra from volume scalar fields.
- **WiggleTraceRenderer**: GPU Instancing rendering engine (`geoviz_seismic/renderer/wiggle_instanced.py` & `wiggle_instanced.glsl`) handling 50,000+ seismic traces $\times$ 4,000 samples at 60 FPS.
- **WiggleDisplayModes**: 4 rendering modes: Wiggle Only, Wiggle + Positive Fill, Wiggle + Dual Fill (Variable Area), and Overlaid Wiggle + VD (Variable Density).
- **ScreenSpaceAdaptiveLOD**: Automatic density transition switching between pure VD texture mapping (when trace screen width < 2px) and instanced Wiggle waveforms (>= 3px/trace).
- **AdaptiveVectorExport**: Hybrid SVG/PDF export policy outputting pure vector `<polyline>`/`<polygon>` nodes when trace count < 500, and High-DPI raster embedding when >= 500 traces.

### FeatureEditor
A stateful, transactional layer-level map geometry editor module (`paleo_workbench/mapping/feature_editor.py`) encapsulating spatial hit testing, multi-polygon vertex snapping, coincident shared-node synchronized movement, strict topology re-closure/non-self-intersection validation (`TopologyError` auto-rollback), event pointer handlers (`on_pointer_down`, `on_pointer_move`, `on_pointer_up`), and transaction undo/redo history (`load_layer`, `select_at`, `move_selected_vertex`, `add_vertex`, `delete_vertex`, `commit`, `undo`, `redo`).

### ColormapManager
A deep colormap pipeline module (`geo-viz-engine/.../geoviz_seismic/colormap.py`) that encapsulates colormap construction, LUT caching (keyed on `name:n_colors`, not `id(lut)`), normalize→uint8-index conversion, RGBA color gathering, and GPU/CPU dispatch (lazy cupy import, `_GPU_MIN_ELEMENTS` size guard) behind a two-method interface: `normalize_to_index(data, lut_size, value_range)` returns a uint8 index array; `apply_colormap(data, name, value_range)` returns RGBA. Three rendering backends (QImage Indexed8, GL_R8+GLSL LUT shader, cupy gather) consume these methods as thin display-medium adapters.

### LASParserProvider
An AccelerationProvider hook (`set_las_parser_provider` / `get_las_parser_provider`) injected by the workbench at startup, enabling the engine's `load_las_preview(path, fast=True)` to use the C++ `fast_las_parse_data` for header-only parse + full-block data extraction + `CurveData.model_construct` (skipping Pydantic validation for the trusted C++ source). When the provider is absent or the file is wrapped/malformed, the engine falls back internally to the pure-Python `inspect_las_file` + `read_sampled_ascii` path.
