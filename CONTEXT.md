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

### WorkflowOrchestrator
A deep workflow state machine orchestrator module (`paleo_workbench/workflow/orchestrator.py`) that encapsulates step transitions, prerequisite evidence validation, and automatic state saving behind a 2-method interface (`next_step`, `get_step_context`).

---

## Domain Concepts

### Well Location Preview
- **ActiveWell（当前井）**: 数据页 `well_head` 二维 XY 预览中唯一承载当前交互焦点的井。单击散点图中的井点或常驻井名列表中的对应行，都会设置同一个 ActiveWell；图与列表共享并同步这一状态。设置另一口井会替换当前井，不形成多选集合。
- **WellLocationPreviewState（井位预览状态）**: 绑定到单个 `well_head` 资产的预览互动上下文，包含 ActiveWell、井名搜索词、列表滚动位置和用户最后看到的平移/缩放视口。在当前数据页会话内，离开资产、刷新预览或重建临时预览组件后仍可恢复精确快照；不同资产的状态彼此隔离。资产源数据变化、关闭项目或退出应用会使其失效，不跨会话持久化。
- **RenderableWellLocation（可预览井位）**: `well_head` 文件中名称非空且 X/Y 坐标均为有限数值的井记录。结构完整的文件允许跳过不满足条件的个别记录并预览其余可预览井位；文件为空、缺少必需列或没有任何可预览井位时，井位预览整体不可用。
- **WellLocationId（井位身份）**: 在单个 `well_head` 资产版本内唯一标识一条源井位记录的身份，由资产版本与源记录序号确定，不由井名或坐标充当。重名或同坐标记录仍拥有不同身份；源数据变化时旧身份随旧井位预览状态一起失效。
- **SourceXY（源 XY）**: `well_head` 文件中原样记录的 X/Y 坐标域。数据页井位预览忠实绘制 SourceXY，不将其自动解释或转换为经纬度、项目 CRS 或 survey 坐标；重投影与跨数据叠加属于其他工作流。
- **SourceCRS（源坐标系）**: 对 SourceXY 坐标域的明确坐标参考系声明，只能来自井位文件自身或 `well_head` 资产的显式元数据。项目默认 CRS、显示 CRS、survey CRS 与数值范围都不能替代缺失的 SourceCRS，也不能用于推断 SourceXY 的含义。

### Well Log Visualization
- **CurveTrack**: Native QPainter track widget displaying depth-aligned log curves with 4-point Min-Max LOD downsampling.
- **LithologyTrack**: Track displaying geological lithology patterns (sandstone, mudstone, limestone, dolomite).
- **WellIntervals**: Formation tops, series, system, and facies interval data mapped along well depth.
- **WellSectionDatum**: A multi-mode vertical alignment policy (`paleo_workbench/viz/well_section_datum.py`) supporting Measured Depth (MD/TVD), Subsea Elevation (TVDSS), and Key Marker Horizon Flattening ($Z=0$ at target marker top) across multi-well correlation sections (`WellSectionHost`).
- **FormationTopCorrelator**: An interactive multi-well formation top correlation engine (`paleo_workbench/viz/formation_top_correlator.py`) managing inter-well correlation polygon bands, marker line drag-adjustments, and `DTWLogMatcher` automated depth transfer recommendations.
- **CrossWellFenceGenerator**: A 3D curtain/fence mesh generator (`paleo_workbench/viz/geomodel/fence_generator.py`) that extracts inter-well seismic slices along multi-well trajectory paths and projects 2D correlation sections into 3D OpenGL viewports.
- **StratigraphicCorrelationEngine**: A deepened fluent correlation engine (`paleo_workbench/viz/stratigraphic_correlation_engine.py`) unifying `WellSectionDatum`, `DTWLogMatcher`, and `FormationTopCorrelator` into an expressive pipeline.

### Seismic 3D & 2D Profile
- **SeismicVolume**: 3D SEG-Y volume data indexed by Inline, Crossline, and Time/Depth.
- **Orthogonal Slice Set（正交切片组）**: 井震联合三维视口中的默认地震切片组合，由一张 Inline 切片、一张 Crossline 切片和至少一张 Time 切片构成；三个方向共享同一个地震体空间。
- **Time Slice Stack（Time 切片栈）**: 正交切片组中可同时显示的多张水平 Time 切片集合。每张切片以地震双程时间（ms）表达独立位置并拥有独立可见状态；其中一张作为 ActiveTimeSlice 接收当前的时间调整、显示切换和删除操作，样点序号不作为用户可见位置。它只在 Time 竖直域中显示和接受编辑，切换到 Depth 时保留原配置但不呈现。
- **ActiveTimeSlice（活动 Time 切片）**: Time 切片栈中当前接收编辑和二维剖面探针联动的唯一切片；切换活动切片不会改变其它切片的位置或可见状态。
- **Per-Well Visibility（逐井可见性）**: 在同一个井震联合工作台中，每口井各自拥有独立的显示状态，并由一处控制其在 3D、Time 连井剖面及点选交互中的全部呈现。它不表示为每口井创建独立视窗。
- **JointWellId（联合井身份）**: 在井震联合场景中唯一且稳定地标识一口源井，不以可重复的井名充当身份。井名只用于显示；重名井仍拥有不同的 JointWellId。
- **Seismic Amplitude Color Scale（地震振幅色标）**: 表达井间地震剖面的振幅值与颜色关系，零振幅为语义中心；它只解释地震底图，不解释井曲线。
- **GR Well Color Scale（GR 井色标）**: 表达自然伽马值（API）与井轨迹沿程颜色的关系；它独立于地震振幅色标，同一口井可因不同深度的 GR 值而呈现不同颜色。
- **GR-Colored Well Trajectory（GR 着色井轨迹）**: 井轨迹本体按对应深度的自然伽马值连续着色，而不是在井旁偏移绘制一条 GR 波形；无有效 GR 的区间使用中性灰色，且不跨缺测区伪造插值。
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
- **SculptableHorizonMesh**: A stateful 3D horizon surface mesh data structure (`paleo_workbench/viz/horizon_sculpting.py`) encapsulating 3D vertex position arrays `(N, 3)`, triangle face indices `(M, 3)`, grid spatial metadata, and a sparse delta patch undo/redo stack (`sculpt_surface`, `smooth_anneal`, `undo`, `redo`), ensuring fast interactive RBF brush editing on 500,000+ vertex meshes without full array cloning.
- **FaultDisplacement**: A kinematic vector field engine (`paleo_workbench/viz/fault_displacement.py`) encapsulating 3D fault surface geometry (Dip, Strike, Throw Magnitude) and applying spatial displacement vector maps $\vec{D}(\vec{x})$ across hanging-wall and footwall blocks to deform horizon meshes and compute structural fault offsets.
- **FormationVolumeIntegrator**: A closed formation volume computation module (`paleo_workbench/viz/formation_volume.py`) that constructs vertical side-wall mesh strips between top ($H_{top}$) and bottom ($H_{bot}$) horizons to build a watertight 3D Polyhedron Mesh and evaluates exact reservoir volume via Gauss Divergence Theorem surface integrals.

### FeatureEditor
A stateful, transactional layer-level map geometry editor module (`paleo_workbench/mapping/feature_editor.py`) encapsulating spatial hit testing, multi-polygon vertex snapping, coincident shared-node synchronized movement, strict topology re-closure/non-self-intersection validation (`TopologyError` auto-rollback), event pointer handlers (`on_pointer_down`, `on_pointer_move`, `on_pointer_up`), and transaction undo/redo history (`load_layer`, `select_at`, `move_selected_vertex`, `add_vertex`, `delete_vertex`, `commit`, `undo`, `redo`).

### ColormapManager
A deep colormap pipeline module (`geo-viz-engine/.../geoviz_seismic/colormap.py`) that encapsulates colormap construction, LUT caching (keyed on `name:n_colors`, not `id(lut)`), normalize→uint8-index conversion, RGBA color gathering, and GPU/CPU dispatch (lazy cupy import, `_GPU_MIN_ELEMENTS` size guard) behind a two-method interface: `normalize_to_index(data, lut_size, value_range)` returns a uint8 index array; `apply_colormap(data, name, value_range)` returns RGBA. Three rendering backends (QImage Indexed8, GL_R8+GLSL LUT shader, cupy gather) consume these methods as thin display-medium adapters.

### LASParserProvider
An AccelerationProvider hook (`set_las_parser_provider` / `get_las_parser_provider`) injected by the workbench at startup, enabling the engine's `load_las_preview(path, fast=True)` to use the C++ `fast_las_parse_data` for header-only parse + full-block data extraction + `CurveData.model_construct` (skipping Pydantic validation for the trusted C++ source). When the provider is absent or the file is wrapped/malformed, the engine falls back internally to the pure-Python `inspect_las_file` + `read_sampled_ascii` path.
