# B 线（井间对比、剖面与井震标定）— V3 批次 scope 与净差距表

基线：`origin/main` @ `7290f727`（2026-09-19）。分支 `codex/viz-b-crosswell-welltie`。
上位计划：`docs/development/cpp-geoviz-completion-plan.md` §V3。

## 1. 净差距表（Python 源 → 主线 C++ 现状 → 本批落点）

| Python 源（geo-viz-engine@08851951） | 行数 | 主线 C++ 现状 | 本批落点 |
|---|---|---|---|
| `geoviz_cross_well/picks_model.py` | 272 | 无对应 | `libs/visualization/src/cross_well/picks_model.cpp`（Qt-free，命令+undo+JSON） |
| `geoviz_cross_well/tops_model.py` | 133 | 无对应 | `.../tops_model.cpp`（CSV 读写 + 调色板 + 排序不变量） |
| `geoviz_cross_well/auto_section_planner.py` | 172 | 无对应 | `.../auto_section_planner.cpp`（PCA + NN 贪心；固定符号约定 + 稳定平局） |
| `geoviz_cross_well/dtw_engine.py` | 161 | ✅ `ui_workers::dtw_engine_correlate`（PR#1375 逐行移植） | 复用，不重写；对比操作经 `make_dtw_propagation_job_spec` |
| `geoviz_cross_well/canvas.py`（含交互/吸附/DTW 传播 GUI 编排） | 640 | 无对应 | `.../qt/section_canvas.cpp` + `section_geometry.cpp`（几何 Qt-free 化） |
| `geoviz_cross_well/correlation_layer.py` | 130 | 部分：`ui_wellseis::correlation.cpp` 是表格语义（PR#1394），非绘制 | `.../qt/section_canvas.cpp` 内 `paint_ties`（贝塞尔 tie + 拾取点绘制，并入剖面画布单文件） |
| `geoviz_cross_well/formation_preview.py` | 280 | 无对应 | `.../formation_preview.cpp`（几何）+ `.../qt/formation_tops_preview.cpp` |
| `geoviz_cross_well/report_export.py` | 228 | 无对应 | `.../qt/report_export.cpp`（PDF/SVG/PNG 出版报告） |
| `geoviz_cross_well/seismic_tie.py` | 105 | 无对应 | `.../seismic_tie.cpp`（checkshot 表 + interp 钳制语义） |
| `geoviz_well_log/cross_well_widget.py` | 603 | 无对应（多井布局/复合导出） | `.../qt/section_canvas.cpp` 内含多井列布局 + composite 导出 |
| `geoviz_well_tie/synthetic.py` | 190 | 无对应 | `libs/visualization/src/well_tie/synthetic.cpp` |
| `geoviz_well_tie/calibration.py` | 178 | 无对应（WLE `scene/time_depth.hpp` 存在但语义不同：严格单调+线性外推 vs np.interp 钳制；不混用） | `.../well_tie/calibration.cpp`（np.interp 钳制语义逐位对齐） |
| `geoviz_well_tie/auto_tie.py` | 140 | 无对应 | `.../well_tie/auto_tie.cpp`（全 lag Pearson） |
| `geoviz_well_tie/wavelet.py` | 67 | 无对应 | `.../well_tie/wavelet.cpp`（canonical ricker/ormsby） |
| `geoviz_well_tie/sonic_units.py` | 88 | 无对应 | `.../well_tie/sonic_units.cpp` |
| `geoviz_well_tie/tie_evaluator.py` | 80 | 无对应 | `.../well_tie/tie_evaluator.cpp`（legacy 对账用） |
| `geoviz_well_tie/canvas.py` / `sidebar.py` | 245 | 无对应（Python 侧本身只画表头+游标线，道体未实现） | `.../well_tie/qt/tie_canvas.cpp`（补齐 7 轨道体绘制，语义按 canvas 列定义） |
| `geoviz_well_tie/report_export.py` | 139 | 无对应 | `.../well_tie/qt/report_export.cpp` |
| `geoviz_well_tie/synthetic_generator.py` / `wavelet_engine.py`（旧套） | 108 | — | 不迁（canonical 套已全覆盖；差异表记录在 oracle 生成器文档） |

**明确排除（复用，不重写）**：
- DTW 数值核与 worker：`libs/well_science/dtw`（#1321）、`ui_workers/{correlation_load,dtw_propagation,synthetic_points}`（#1375）。
- 链接编辑器/导出对话框：`ui_wellseis::qt::CorrelationLinkEditor`、`CrossWellExportDialog`、`CorrelationDraftSlice`（#1394）——B 只写绑定适配。
- A 线的 LAS parser/preview/bridge（未合入）：B 的加载 seam 用主线现成 `viz_resolve`（load_fn 注入点），B 自带 JSON 井数据通路保证今日可验收；A 合入后 LAS 自动经同一 seam 接通（记录依赖，不复制实现）。
- C 线联合 3D、D 线地震高级显示、geomodel 体积/section 服务：零触碰。

## 2. 架构决策（记录）

1. **DTW 不引入第二实现**：`viz::cross_well` 核心不自带 DTW；传播操作在 app adapter 层调 `pwb::ui_workers::make_dtw_propagation_job_spec`（JobCenter 通路），结果由 GUI 侧 apply 成 picks（source="dtw"）。
2. **时深模型口径**：`viz::well_tie::WellTieCalibration` 逐位复刻 Python `calibration.py`（np.interp 端点钳制、降序反转、梯形声波积分）。WLE `TimeDepthRelationship`（严格单调/线性外推）语义不同，不混用；主程序单井 TWT 轴若未来走 WLE 由 A/C 线决定。
3. **两套 well_tie 实现取 canonical**（`synthetic.py`/`wavelet.py`，`__init__.py` 导出套）；旧套（`synthetic_generator.py`/`wavelet_engine.py`）差异在 oracle 生成器注释中留档，不迁。
4. **多井剖面自绘**：V2（A 线绘制核）未合入，按任务书"不等待 A 的新增通用绘制原语、不复制 A 的 bridge"，B 在自有文件内以 QPainter 直绘剖面（井列+曲线+tops+picks+相关带），曲线数据为 B 自有的 `WellLog` 值对象；不触碰 A 的 `well_log/` host 文件。
5. **持久化**：B 线独占 sidecar `cross_well_workspace.json`（工程目录旁，经 `handle_project_closed` 受控 flush；不碰 catalog）。原因：C++ shell 当前没有工程文档保存通路（`PwbDataStore` 未暴露 `ProjectManager::save`）；payload schema 已按未来 `cross_well_workspace` 顶层节设计（Python `ProjectDocument` extra=allow），文档保存通路落地后平移。
6. **会话代际**：dock 持 `section_revision_`（仿 seismic dock 的 `slice_revision_`），openProject/换工程 bump；迟到 JobCenter 回调按代际丢弃。
7. **CMake**：根 `BEGIN/END VIZ-B` 块 + 显式 option `PWB_BUILD_VIZ_B`（默认 ON，但仅在 `PWB_BUILD_PLATFORM` 布局内真正可达；Qt-free 半只需 C++20，Qt 半需 Qt6::Widgets）。app 侧 `if(TARGET Pwb::VisualizationCrossWell AND ...)` + `PWB_WITH_VIZ_B=1`。

## 3. 验收硬门（对齐任务书）

1. 两口以上真实 fixture 井（经真实 Python/lasio 参考路径冻结）：加载→显示→编辑 picks/tops/links→保存→重开，身份/深度/关联完整恢复。
2. DTW 路径/代价沿既有 oracle（ui_workers dtw_correlate cases 回归）；标定/合成记录对真实 Python 冻结数值 + 异常路径（不等采样、深度倒序、缺测、空输入、无重叠范围）。
3. auto_section_planner 确定性（PCA 符号固定 + 稳定平局）；canvas 视口/游标与各井坐标对应正确（几何 Qt-free 测试）。
4. 报告/剖面导出可读且含选定数据身份；取消/关闭/换工程后无迟到写入。
5. 独立真实引擎 example + 主程序接线证据；关键测试两遍；ON/OFF 配置；三轮独立审核；PR。

## 4. 依赖与风险（如实）

- A 线未合入：LAS 真实解析在主线 C++ 是 V1 seam（`viz_resolve` load_fn 未绑定）。B 以 JSON 井通路 + oracle 冻结的真实 LAS 数值完成今日验收；A 合入后经同一 seam 接通（PR 说明中记录，不 stacked 依赖）。
- QGIS SDK：主程序平台构建需要；本地复用主工作区 SDK（只读 env 注入）。
- 渲染容差：QPainter vs matplotlib/PySide 像素差存在；断言用几何/文本/结构级 + 非空像素，容差在 ledger 声明。
