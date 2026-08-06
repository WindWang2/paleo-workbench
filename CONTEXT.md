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
- **Well Content Tree（井内容树）**: 选中井后的井内数据树：按 **导入源 / 逻辑数据集 → 可显示井道叶子** 两层组织（单井道源也保持两层），与工区 catalog 树分离；父节点三态复选框；深度尺标不在树上。首期叶子仅为标量曲线实例（含 AT10–AT90 等独立叶子）。规格见 `docs/superpowers/specs/2026-08-06-well-content-tree-and-table-mode-design.md`。
- **Display Set（显示集）**: 井内容树中已勾选的可显示井道叶子身份集合；图形模式与表格模式共享同一显示集，切换视图模式不改变勾选。
- **Displayable Track Leaf（可显示井道叶子）**: 源侧可单独开关显示的井道实例（稳定身份）；不是图版 BoundTrack 槽位。首期 = 标量曲线实例。
- **Dual-layer composition（双层合成）**: 显示集决定「显示哪些井道」；图版决定匹配槽位的布局/样式；未匹配的已勾选叶子使用默认样式。换图版不改显示集。默认勾选 = 当前图版可匹配项。
- **View Mode（视图模式）**: 单井主区 `graphic`（图形）或 `table`（表格）；默认图形；会话内按井记住；首期不跨会话持久化。
- **ResForm Compatibility Model（ResForm 兼容模型）**: 以商业软件 ResForm 的用户可见测井工作流为参照：导入后的深度、曲线、单位、空值和可视化语义应符合解释人员的预期；它不替代底层文件格式规范，也不要求复制其私有实现或文件识别规则。
- **Whole-File Log Import（整文件测井导入）**: 用户打开一个测井文件时，所有可用曲线数据集都被导入；不同采样轴各自保留，不因曲线名或相邻深度而被隐式合并或重采样。
- **Canonical Curve Mnemonic（标准曲线名）**: 由已知源道名别名归一出的测井曲线语义名称；原始道名仍作为显示名称保留。无法识别的道名不被改写，并作为需核对的导入诊断。
- **Canonical Log Unit（规范测井单位）**: 已识别的源单位及其数值共同换算后使用的统一单位：深度为 `m`，自然伽马为 `API`，自然电位为 `mV`，电阻率为 `Ω·m`，声波时差为 `μs/m`，密度为 `g/cm³`，中子孔隙度为 `%`，井径为 `mm`。缺失、歧义或不支持的源单位不被推测或仅改写标签，而是保留为导入诊断。
- **Inferred Null（推断空样点）**: 源格式未明确声明空值时，由白名单缺失哨兵值（`-999.25`、`-999`、`-9999`、`-99999`）或非有限值识别出的不可绘制样点；明确声明的空值优先，白名单不得叠加到该数据集。非有限值始终为空样点。推断空样点必须伴随可追溯的导入诊断，其他极端数值仍为测量值。
- **Interpretation Correction（解释校正）**: 对已导入测井数据显式执行的深度校正、曲线拼接或插值对齐；它不属于文件打开过程，必须可由用户辨认并可撤销。
- **LIS79 Import（LIS79 导入）**: 对 1979 版 Log Information Standard 的受支持导入范围；Enhanced LIS（LIS84）必须被识别并明确诊断，不被当作 LIS79 猜测读取。
- **Recoverable LIS Record（可恢复 LIS 记录）**: 长度边界可确定但不受支持或损坏的 LIS 记录；它被跳过并诊断，且只隔离所属数据集。无法继续确定物理记录边界的文件损坏不是可恢复记录，必须拒绝整个文件。
- **Imported Log Identity（导入测井身份）**: 由源文件内容指纹、逻辑数据集身份与归一化规则指纹共同确定的稳定文档、采样轴和曲线身份；相同内容及规则重复导入保持同一身份和初始 Revision，内容或规则变化则形成新文档。
- **Log Normalization Profile（测井归一化配置）**: 一个工区可审计的曲线别名、单位和缺失值规则集合；它以显式、不可变的导入参数提供，未提供时使用内置默认配置，而不读取 ResForm 私有工区文件。内置默认配置名为 `resform-compatible-v1`，其版本与规则内容共同构成稳定指纹。它决定源测井如何成为标准曲线语义，并拥有参与导入身份计算的稳定指纹。
- **LIS Text Decoding（LIS 文本解码）**: LIS 文本字段的可审计呈现规则：默认仅按 ASCII 解读；非 ASCII 原始字节保留并产生诊断，只有归一化配置显式指定代码页时才解码，绝不基于内容猜测编码。
- **Invalid Normalization Profile（无效归一化配置）**: 包含冲突别名、无法闭合的单位转换或其他自相矛盾规则的归一化配置；导入必须在读取源文件前明确拒绝它，不能静默回退或任选规则。
- **Normalization Conflict（归一化冲突）**: 源曲线名与单位分别指向不兼容测井语义的情形；该曲线保留源名称和数值而不自动换算，并作为警告交由用户核对。
- **Curve Alias Match（曲线别名匹配）**: 在忽略大小写、首尾空格、连字符和下划线后，以精确名称匹配标准曲线名的规则；数字、测次和工具后缀仍区分独立曲线实例，且不使用模糊匹配。
- **ResForm-Compatible v1 Aliases（ResForm 兼容 v1 别名）**: 内置归一化配置覆盖 `GR`（`GR`、`GAM`、`GAMMA`）、`SP`、`AC`（`AC`、`DT`、`DTC`）、`DEN`（`DEN`、`RHOB`）、`CNL`（`CNL`、`NPHI`、`TNPH`）、`CAL`（`CAL`、`CALI`），以及分别保留的深/中/浅探测电阻率语义；未列出的源道名保持原样并诊断。
- **ResForm-Compatible v1 Units（ResForm 兼容 v1 单位）**: 内置配置可识别并换算深度（`m`、`ft`、`in`）、声波时差（`μs/m`、`μs/ft`）、密度（`g/cm³`、`kg/m³`）、中子孔隙度（`%`、`v/v`）、井径（`mm`、`cm`、`in`）、电阻率（`Ω·m`、`Ω·ft`）、以及 GR 的 `API` 和 SP 的 `mV`；未列单位不换算并明确诊断。
- **Source-Domain Null（源域空值）**: 在应用 LIS 比例、偏移和规范单位换算之前识别的缺失样点；只有非空源样点可以参与这些数值变换。
- **LIS Import Limits（LIS 导入上限）**: 可由宿主覆盖的输入安全边界；默认文件为 256 MiB、单逻辑记录为 4 MiB、记录数为 1,000,000、每数据集样点为 10,000,000、每数据集曲线为 4,096。超过任一上限时导入明确失败而不截断数据。
- **LIS Production Fixture（LIS 生产样例）**: 随仓库提供、用于验证正常 LIS79 导入和表格导出的真实且去敏的数据文件；它必须附有可追溯来源与明确的再分发许可。来源或去敏状态不能证明的第三方样例即使随开源解析器发布也不得采用；程序化样例仅用于损坏与资源边界测试。
- **Canonical Curve Instance（标准曲线实例）**: 同一标准曲线语义在一个采样轴内对应的独立源曲线；即使名称归一相同，实例仍保留各自源身份与显示名，不被自动覆盖、择优或拼接。
- **LIS Curve Dataset（LIS 曲线数据集）**: 由 LIS79 数据格式说明与常规深度采样数据共同定义的可导入曲线集合；卷/文件头仅提供来源语义，其他 LIS 记录不进入标准文档而保留为诊断。
- **LIS Physical Envelope（LIS 物理封装）**: LIS79 文件所用的 Tape Image Format（TIF）包装或直接物理记录流；导入器仅在结构校验唯一成立时自动识别，无法唯一识别时必须拒绝而不根据扩展名猜测。
- **Unsupported LIS Channel（不支持的 LIS 通道）**: 字符串、掩码或多维样点等无法成为标量数值 Curve 的通道；它不被强转或压缩为伪曲线，而是以记录位置、通道名和表示类型明确诊断。
- **LIS Data Run（LIS 数据段）**: 一个数据格式说明及其后连续数据记录构成的数据集；记录按源顺序追加，前一数据格式说明后已出现数据时，下一数据格式说明即使 schema 相似也开始新的独立数据集。相邻、无数据间隔且完全相同的重复数据格式说明只是冗余元数据，折叠为一份并产生信息诊断；若不完全相同，则后一个取代前一个，前一个作为未产生样点即被替换的警告处理，不生成空数据集。数据段稳定身份锚定其有效数据格式说明的源序号/物理位置，而非可重复的曲线名或 schema；即使不同数据段的索引、单位和方向完全相同，也各自拥有独立采样轴，绝不自动共享或合并。
- **LIS Well Selection（LIS 井选择）**: 对包含多个逻辑文件或井的 LIS 物理流，先检查并列出可选逻辑文件/井身份，再显式选择其中一口井导入其全部数据集的过程；逻辑文件的稳定序号/物理位置是选择身份，井名仅作展示，缺失或重名均不得触发自动选择或跨井合并。仅一个候选时直接导入；多个候选时才要求显式选择。
- **Empty Log Import（空测井导入）**: 源文件结构有效但没有可规范化数值数据集时的成功导入结果；它包含空文档和“无可导入曲线”警告，而不把内容不受支持误诊为文件损坏。
- **LIS Depth Domain Match（LIS 深度域匹配）**: 对 LIS 索引赋予深度域的严格规则：索引名和长度单位必须同时匹配；`DEPT`、`DEPTH`、`MD` 对应 MD，`TVD` 对应 TVD，`TVDSS` 对应 TVDSS。不得仅凭单位或数值推断深度域。
- **LIS Axis Segmentation（LIS 采样轴分段）**: 同一数据段内重复索引按源顺序保留；以首个非重复差值确定轴方向，首次反向即开始独立的采样轴和曲线段，绝不排序。若索引全相同，则按递增轴导入并产生诊断。
- **Source Index Axis（源索引采样轴）**: 具有数值坐标但无法确认其深度语义的数据集索引；它可被导入和查看，但不得被解释为井深，并必须带有未知索引语义诊断。
- **Import Audit（导入审计）**: 随导入结果返回的可定位说明：自动别名匹配、单位换算和 Null 推断为信息；未知元数据、跳过记录和局部损坏为警告；无法继续确定文件结构时才是错误。
- **CurveTrack**: Native QPainter track widget displaying depth-aligned log curves with 4-point Min-Max LOD downsampling.
- **LithologyTrack**: Track displaying geological lithology patterns (sandstone, mudstone, limestone, dolomite).
- **WellIntervals**: Formation tops, series, system, and facies interval data mapped along well depth.
- **WellSectionDatum**: A multi-mode vertical alignment policy (`paleo_workbench/viz/well_section_datum.py`) supporting Measured Depth (MD/TVD), Subsea Elevation (TVDSS), and Key Marker Horizon Flattening ($Z=0$ at target marker top) across multi-well correlation sections (`WellSectionHost`).
- **FormationTopCorrelator**: An interactive multi-well formation top correlation engine (`paleo_workbench/viz/formation_top_correlator.py`) managing inter-well correlation polygon bands, marker line drag-adjustments, and `DTWLogMatcher` automated depth transfer recommendations.
- **CrossWellFenceGenerator**: A 3D curtain/fence mesh generator (`paleo_workbench/viz/geomodel/fence_generator.py`) that extracts inter-well seismic slices along multi-well trajectory paths and projects 2D correlation sections into 3D OpenGL viewports.
- **StratigraphicCorrelationEngine**: A deepened fluent correlation engine (`paleo_workbench/viz/stratigraphic_correlation_engine.py`) unifying `WellSectionDatum`, `DTWLogMatcher`, and `FormationTopCorrelator` into an expressive pipeline.
- **Plot Revision（图件修订）**: `well_log_workstation/events.py` 中 per-plot 的单调修订计数器，以 plot id 为键、随图件内容变更（emit）递增。它持久化于 `plots/<id>.json` 顶层字段（schema v3，ADR 0051），由宿主负责保存与恢复：保存时 bump 为新的已提交状态、加载时以 max 语义恢复（不回退）、emit 时 bump。它与引擎 DocumentRevision 是两套概念：后者由内核维护并描述引擎内文档内容版本，已通过 `WellLogView.documentChanged` 信号暴露到 Python 但本期不接线；Plot Revision 是宿主侧图件保存状态，供 `plot_changed` 信号的消费方（如未来 composite 面板按 revision 判断刷新或使 snapshot 失效）使用。
- **WellPlot Desktop（测井桌面产品）**: 面向测井绘图的可独立安装桌面应用；代码基线为 `well_log_workstation`（独立 QApplication 壳），**首发 epic #288（轨 F/D/E · 导出 B0，T1–T15）已交付**：品牌/启动页、单井+连井、导出 B0、打印预览骨架、几何金标子集、Win/Linux 安装包。不另起第二套画布。Paleo Workbench 内嵌测井为次要集成路径。**导出 B1 核心切片已交付**（#304 / T16；见 `docs/export-b1-status.md`）。**轨 P 规格已开**（#305 / T17；ADR 0055 + `docs/plugin-runtime-status.md`）：首发仅 Custom Layer + SDK 嵌入；完整插件 Runtime / Command 审计实现拆 P.* 子单。B1 延期项：§16 全矩阵 / 完整 ToUnicode 等。
_Avoid_: WellPlot Desktop 与 Workstation 当成两套长期分叉产品
- **Layered Log Truth（分层测井真源）**: 文档与修订的权威在 WellLog Document 与 Data Patch；运行时样点以引擎不可变自有缓冲区为准；Apache Arrow 是跨语言零拷贝交换边界，不是强制唯一运行时内存载体。
_Avoid_: “Arrow 是唯一运行时真源”作为 phase-one 实现描述
- **Export B0 / B1（导出分期验收）**: **B0 首发门禁已兑现**。**B1 核心切片已交付**（#304；选型 ADR 0053/0054 + 实现）：PDF 双模式 + Latin-1 可搜索层（B1.PDF.1–3）；CGM.1–3（写入器、宿主菜单、诊断、多 PICTURE、hatch）；**B1.GEOM** 多格式几何矩阵（0.1 mm 主容差，CGM 入口 0.5 mm）。明细见 `docs/export-b1-status.md`。**延期未宣称**：§16 全矩阵、完整 CJK ToUnicode 子集、引擎 PDF 字形锚点 0.1 mm、CGM 场景裁剪 0.1 mm。
_Avoid_: 在未实现时宣称已支持完整 0.1 mm 全矩阵或引擎 PDF 默认可搜索 CJK
- **Engine Vector Exporters（引擎矢量导出器）**: well-log-engine 的 C++ SVG（物理分页）/PDF/PNG/TIFF 导出器，输入为 `PreparedScene + ExportSnapshot`，可无头纯 CPU 运行。Stage 1 已为单井提供 Python 绑定（`export_scene_svg` / `export_scene_pdf`）及宿主 `backend="engine"` 路由；对比图与剖面图场景通路仍按 ADR 0052 后续 Stage。引擎 PDF 为字形轮廓、默认不可搜索（ADR 0047）。
_Avoid_: 假设全部六类图件已走引擎导出；忽略 PDF 不可搜索披露

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

### Custom Layer Primitives

- **PatternDefinition**: The single vector source of truth for a geological fill pattern (ADR 0020). Restricted vector primitives + repeat unit + physical tile size, anchored in scene coordinates to avoid translation drift. The GL backend caches it as a texture atlas / distance field; PDF/SVG backends consume the raw vectors. Referenced by EntityId from Intervals and CustomQuads.
_Avoid_: hatch, fill style, texture

- **CustomPolyline**: A declarative polyline stroke primitive in the Custom Layer (ADR 0018/0046). Scene-mm points, optional ring closure, color, stroke width, and optional dash pattern. Decomposed into GL quad ribbons and SVG/PDF path elements by the kernel — extensions never emit rendering calls directly.
_Avoid_: freehand line, annotation line

- **CustomQuad**: A declarative filled rectangle primitive in the Custom Layer. Axis-aligned in scene millimetres, solid `fill_color` or pattern-filled via a `pattern_id` referencing a registered PatternDefinition.
_Avoid_: rectangle annotation, box primitive

- **DashPattern**: An explicit on/off segment array in scene millimetres defining a stroke's dash style (e.g. `[4.0, 2.0]` = 4mm dash, 2mm gap). Maps directly to SVG `stroke-dasharray` and PDF line dash arrays; GL renders it via CPU segment subdivision. An empty array means solid.
_Avoid_: line style, stroke style, dash style
