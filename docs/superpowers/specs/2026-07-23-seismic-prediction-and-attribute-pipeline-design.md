# Seismic Prediction & Attribute Pipeline Design Specification

## Problem Statement

Seismic geologists and geophysicists working in the Paleo Workbench need to extract 3D seismic attributes (such as 3D Coherence, Spectral Decomposition, Dip/Azimuth) and run AI deep learning models for automated sedimentary facies and fracture network interpretation.

Currently, large 3D SEG-Y computations risk freezing the user interface during multi-gigabyte volume processing. Furthermore, 2D slice profiles and 3D OpenGL viewports operate without a unified spatial state observer, causing fragmented slice navigation. AI interpretation outputs are also restricted to simple binary masks that fail to communicate prediction confidence or model uncertainty to domain experts.

## Solution

Build a deep, asynchronous **Seismic Prediction & Attribute Pipeline** powered by `NativeEngineBackend` C++ GIL-releasing workers, linked to a centralized `SeismicVolumeState` observer model, and presenting dual `ClassMap` (discrete geological facies) + `ProbMap` (continuous confidence probability) tensor outputs inside `VisualizationWorkspace`.

Key features include:
1. **Asynchronous Attribute Computation**: C++ OpenMP/SIMD accelerated 3D attribute filters (`AttributePipeline`) with progress reporting and cancellation.
2. **Synchronized 2D/3D Navigation**: Real-time cross-view sync between 2D profile slice sliders and 3D OpenGL volume viewers via `SeismicVolumeState`.
3. **Dual Grid/Geographic Coordinate Mapping**: Single-click toggling between survey grid indices $(IL, XL)$ and real-world UTM/geographic coordinates $(Easting, Northing)$ using `BinGridGeometry`.
4. **Uncertainty-Aware AI Inference Visualization**: Facies predictions rendered as color-mapped discrete classifications with continuous probability alpha-blending, rendering low-confidence regions semi-transparent automatically.

## User Stories

1. As a geophysicist, I want to initiate a 3D Coherence attribute calculation on a SEG-Y volume without freezing the UI, so that I can continue exploring other workbench tabs while the computation runs.
2. As a geophysicist, I want to see a live percentage progress indicator and a Cancel button during long attribute calculations, so that I maintain full operational control over memory and background CPU usage.
3. As a seismic geologist, I want dragging an Inline/Crossline slider on a 2D profile to immediately update the corresponding slice planes in the 3D OpenGL viewport, so that I can inspect spatial horizon boundaries interactively.
4. As a mapper, I want to toggle between Inline/Crossline numbers and Easting/Northing UTM coordinates with one click, so that I can align seismic anomalies with regional well control maps.
5. As a petroleum geologist, I want AI-predicted sedimentary facies output as both a discrete facies classification grid (`ClassMap`) and a confidence probability grid (`ProbMap`), so that I can evaluate model reliability across complex fault zones.
6. As a visualizer, I want low-confidence AI prediction regions to be rendered as semi-transparent, so that uncertain model predictions do not obscure clear seismic reflector signatures.
7. As a system administrator, I want pure-Python fallback algorithms to produce identical attribute output arrays when C++ native extensions are absent, so that the application runs reliably across non-compiled environments.

## Implementation Decisions

1. **Centralized State Observer (`SeismicVolumeState`)**:
   - Encapsulates active slice coordinates (`inline_idx`, `crossline_idx`, `t_slice_idx`), active horizon selections, and `BinGridGeometry` spatial coordinate transformations.
   - Dispatches `slice_changed` signals subscribed to by both 2D profile widgets (`SeismicView`) and 3D volume viewports (`Renderer3D`).

2. **Asynchronous Engine Pipeline (`AttributePipeline`)**:
   - Integrates with `NativeEngineBackend` to dispatch C++ multithreaded extensions (`compute_coherence_3d`, `spectral_decomp_3d`) with explicit GIL release (`py::gil_scoped_release`).
   - Managed by an `AttributeTaskWorker` (subclassing `QThread`) emitting progress signals `progress_changed(float)` and accepting cancellation flags.

3. **Dual Tensor Facies Output Contract**:
   - `SeismicPredictionTask` returns a dual-channel payload:
     - `ClassMap`: `uint8` 3D ndarray representing discrete facies codes.
     - `ProbMap`: `float32` 3D ndarray representing Softmax probabilities ($0.0 \sim 1.0$).
   - `VisualizationWorkspace` routes prediction payloads to `SeismicHost`, configuring color LUT mapping on `ClassMap` and opacity alpha modulation from `ProbMap`.

4. **Coordinate Transformation Matrix (`BinGridGeometry`)**:
   - Employs 2D affine transformation matrices to convert between $(IL, XL)$ grid space and $(Easting, Northing)$ geographic space.

## Testing Decisions

1. **Test Philosophy**:
   - Test external behavior, signal contracts, and numerical outputs at high-level seams without instantiating actual OS-level OpenGL display contexts.

2. **Target Modules & Seams**:
   - **`tests/test_seismic_volume_state.py`**: Validates `SeismicVolumeState` observer signal emissions, coordinate conversion roundtrips with `BinGridGeometry`, and slice boundary clipping.
   - **`tests/test_attribute_pipeline.py`**: Validates asynchronous GIL-release execution, progress reporting, cancellation token handling, and parity between C++ extensions and pure-Python fallbacks (`SymmetricParityContract`).
   - **`tests/test_seismic_prediction_task.py`**: Validates dual `ClassMap`/`ProbMap` payload generation and `VisualizationWorkspace` tab routing.

3. **Prior Art**:
   - Follows pattern of `tests/test_well_log_core_hardening.py` and `tests/test_composite_visualization_panel.py`.

## Out of Scope

- Real-time cloud GPU cluster distributed inference (single-node local CPU/GPU only for this specification).
- Manual point-cloud seismic horizon editing (handled by `FeatureEditor` in mapping page).

## Further Notes

- Maintains complete backwards compatibility with existing `VizPayload` structures and `DataAssetRegistry` asset specifications.
