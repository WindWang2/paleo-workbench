# 01 findings — mapping_kernel → MainWindow 地质因子图切片

按 §5 清单逐文件全文阅读后写。每个公开符号：输入 / 输出 / NaN·空·并列 /
与 C++ 核的关系 / 测试缺口。UI/mapping_workspace 段来自只读侦察代理
（subagent #1）的全文扫描报告（追加于文末）。

## A. libs/mapping_kernel 头与实现（C++，只读冻结核）

### contouring.hpp / contouring.cpp
- `struct Grid`：`w`(x 列数)、`h`(y 行数)、`grid_x[w]`、`grid_y[h]`、
  `grid_z[w*h]` 行主序（i=y 索引、j=x 索引），NaN=nodata。**runner 必须把
  FactorGrid(float z) 转 double Grid 时保持该布局**。
- `nice_contour_levels(vmin, vmax, target_count=7)`：非有限或
  isclose(vmin,vmax) → 空；1/2/5×10^e 阶梯，`round(curr,8)` 半偶舍入。
  Python `calculate_nice_contour_levels` 逐位对齐。
- `quantile_contour_levels(grid, quantiles)`：有限值 <2 → 空；
  np.nanpercentile 'linear' 语义；`round(v,6)` 去重 + 排序。
- `marching_squares_contours(grid, level, simplify_tol=0, smooth=0)`：
  h<2 或 w<2 → 空；NaN 格元跳过；`level<min||level>max` 跳过；16 例 +
  鞍点中心均值（case5/10）；缝合复刻 Python dict 插入序（开放端点先出发、
  首个未用邻居续接；std::map 索引但遍历走插入序数组）。
- `round_to`（半偶）/`is_close`（rel 1e-9）/`polyline_length`/
  `douglas_peucker`/`chaikin_smooth`（闭合判定 abs 1e-5）。
- 测试缺口：无（mapping_kernel.contouring 168 冻结案例）。

### interpolator.hpp / interpolator.cpp
- `SamplePoint{x,y,value,qc_flag="ok"}`；qc 合法集 `ok|good|""`（与
  Python models.valid_points 一致）。
- `InterpolateOptions`：method(idw|kriging|ordinary_kriging|ok)、grid_n=50、
  power=2、max_neighbors/search_radius optional、min_neighbors=1、
  variogram_model、boundary（空=无掩膜）、crs、distance_policy="planar"。
  **Python 默认 method="kriging"**（models.InterpolationOptions），本切片
  用户流程选 IDW → C++ 侧显式传 "idw"。
- `FactorGrid`：grid_z 是 **float**（NaN nodata）；variance_grid IDW 为空；
  statistics 由 grid_statistics 填；distance_policy(+annotation) 由
  resolve_distance_policy 填。
- `interpolate_factor(points, options)`：validate_dataset 非空 →
  std::invalid_argument（消息与 Python validate() join 一致）；
  `grid_n = max(10, options.grid_n)`；linspace extent=dataset_extent(all
  points，含非法 QC 点)；IDW：k==N 且无半径走全邻域（power 2 特例 1/dist²、
  exact-hit last-wins、wsum≤0 或 n<min_neighbors → NaN）；否则 kNN 暴力
  （同 cKDTree 唯一距离并列：dist 并列按 idx 排序，partial_sort）。
  Kriging：先 dedup（1e-9 tol 均值合并）→ 经验变差图 + 网格 OLS 拟合 →
  全局 (n+1)² 增广 OK 系统或移动邻域（256 cap）；常值场捷径 = 样本均值。
- `dataset_extent`：空 → (0,0,1,1)；pad = max(0.01, span*0.1)，共线轴 0.05。
- `validate_dataset`：<2 有效点 → "Insufficient sample points (N); at
  least 2 valid points required for spatial interpolation."；全共点 →
  "All points are collocated at the same coordinate."。**runner 把异常文案
  原样透传给用户**（与 Python ValueError 同文案）。
- `grid_statistics`：全 NaN → NaN stats + valid 0；float64 mean/std ddof=0。
- 测试缺口：无（19 冻结案例 + crs 策略用例）。

### extract.hpp / extract.cpp
- `extract_factors(records:Json, factor_name, options)`：records 必须是
  JSON 数组（非数组 → 空数据集）；坐标族优先序 project/xy/lnglat×2/surface，
  不跨族配对；`coordinates[0..1]` 兜底；0.0 合法（is_null 判缺失）；
  py_float 接受数字/布尔/可解析字符串；值查找 exact→value→val→casefold
  别名→嵌套 attributes/properties/metadata（嵌套无 val）；
  派生：砂地比=100*H_s/H_t（H_t>0）、地层厚度=base−top（base>top），
  metadata.derived 带 rule+sources；诊断 metadata 含
  coordinate_key_families_used / skipped_missing_coordinates /
  skipped_invalid_coordinates / derived_points / mixing 标记。
- `FactorPoint`：well_id←(well_id|id)、well_name←(name|well_name|well|id)、
  qc←qc_flag 默认 "ok"、formation←(formation|target_horizon|options)。
  单位：unit=nullopt → FACTOR_DEFAULTS 表；unit="" 显式空。
- **runner 入口：井点 JSON（QGIS 图层读出的要素转 Json 数组）→
  extract_factors → FactorDataset**。C++ FactorDataset.crs 需来自工程 CRS。
- 测试缺口：无（22 冻结案例，坐标族 #1150）。

### polygonization.hpp / polygonization.cpp
- `classify_grid(grid, thresholds, n_classes)`：z 从 0 起；`z>=th` 依次置
  min(idx+1, n_classes-1)；**NaN 格元不满足 >= 恒为 0**（分类 0=最低相）。
  Python 侧 `grid_z >= th` 同语义（NaN→False）。
- `polygonize_class(grid, class_grid, target_class)`：要求
  class_grid.size()==h*w 且 grid_z.size()>=h*w；格元边追踪（dict 插入序 +
  append 序邻接、首条未用边出发）；闭环 len>=4 且首尾 isclose abs 1e-5；
  signed_area>0 外环 / <0 洞 / ≈0（abs 1e-12）丢弃；无外环 → 洞反转提升；
  外环按面积升序 stable_sort；洞归属 = bbox 预滤 + 顶点多数票
  （严格 >，最小外环赢并列）；未匹配洞反转提升并计数。
- `default_class_thresholds(vmin,vmax)`：isclose → [vmin]；否则
  vmin+span*{0.333,0.666}（与 Python generate_facies_polygon_layer 默认
  阈值一致——**runner 默认相带用这个**）。
- `filter_small_polygons(geoms, min_area)`：净面积（外环−洞）< min_area 丢。
- `polygonize_factor_grid(grid[, level])`：level 缺省 = 有限格元中位数
  （numpy median 偶数取均值）；分类 0/1，target=1。
- shapely repair / clip-ring **未移植**（Python oracle 打成 identity）——
  runner 不做 repair，与冻结核一致。
- 测试缺口：无（24 冻结案例，坐标 diff 0）。

### class_grid.hpp / class_grid.cpp（nearest_neighbor_class_grid）
- 相点（FaciesPoint{x,y,facies}）→ first-seen 相 id int16；nx=ny=max(2,n)；
  argmin 平方距离（并列取最小索引）；可选 inclusive PIP 裁剪（on-edge
  true）。异常："point-to-surface needs at least one well facies point"。
- 本切片用户流程只要求等值线 + 相带多边形；NN 分类栅格不在最小链上
  （相带多边形由 classify_grid + polygonize_class 承担）。保持只读。

### crs_policy.hpp / crs_policy.cpp
- `resolve_distance_policy(crs, distance_policy)`：builtin 地理 id 表 +
  EPSG:3857 投影例外；未知 id → axes_known=nullopt（不猜）；
  非法声明 → std::invalid_argument（"distance_policy must be one of …"）。
  **interpolate_factor 内部调用**：FactorGrid.distance_policy/
  annotation 已填，runner 无需再调。
- EPSG:4326（8 井点 fixture 的 CRS）→ planar_degrees + 警告文案
  "CRS EPSG:4326 is geographic (degree axes)…"。

### sample_normalization.hpp / sample_normalization.cpp
- `normalize_factor_samples(points, policy)`：mean/first/error/keep；
  精确坐标相等分组；非有限丢弃计数；error+重复 → 异常（含首组坐标）。
  **本切片不动它**（提取层无重复合并语义；Python extract 也不合并）。

## B. 应用层（C++）

### apps/paleo_workbench_platform/main_window.cpp/.hpp
- 组合根：构造时注册 E 内核（attribute_runner_）；`buildUi` 建画布/图层树
  dock/状态栏；`buildMenusAndToolbar` 用 governed QAction（policy 词汇表
  物化），`wire` lambda 连 triggered 并记 wired_action_ids_。
- 菜单样板（照抄模式）：`menuBar()->addMenu` + `addAction(tr("…"), this,
  &MainWindow::handler, QKeySequence)`；地震菜单在
  `#if defined(PWB_WITH_SEISMIC_IO)…` 内。**新「地质因子图…」走同模式，
  由 `PWB_WITH_CONV_01` 编译开关守卫**。
- `openProject`：PwbDataStore::open → recover → 绑定 GeoJSON/GPKG 工作副本
  物化 → DomainLayerFacts（role=facies_boundary 默认）→ refreshActionStates。
  `loadFixtures`（模块模式）用 "fixture.facies_boundary"。
- 属性对话框样板 `runAttributeDialog`：project_store_ 空则提示；QDialog+
  QFormLayout+QComboBox+QDialogButtonBox；modal 进度用 QTimer+QEventLoop。
  **地质因子图对话框同构（无工程先提示）**。
- `refreshActionStates()` = evaluate_all(session_->snapshot()) →
  actions_.apply(availability)。**动作启停唯一权威是 tool_policy**。
- closeEvent 三方决策 + session_->close() 契约销毁序——新动作不改。

### libs/application/project_session.cpp/.hpp
- `snapshot()`：project_open = map_ && map_->project()（QgsProject 常在 →
  平台会话里基本恒 true；tool_policy 测试用纯快照直接构造 project_open=false）。
  mapping_stage 三态（未设=无阶段语义 → factor 组白名单门不触发）。
- `stage_commit`：stage(活缓冲) → B commit → finalize；模块模式诚实报错。
- DomainLayerFacts：role/role_label/artifact_maturity/write_granted →
  snapshot 填 ctx。**新图层（等值线/相带）注册 facts 时 role 用
  factor_contour / factor_classification（layer_roles 词汇已存在）**。

### libs/application/algorithm_runner.cpp（模式参照）
- submit: store 空报错 → kernel 查找 → 输入装载 → runtime.submit →
  outcome 轮询（queued/running/publishing → 终态）；CatalogResultPublisher
  发布到 .pwb-runs。**本切片不发布 catalog 版本（无此要求，最小实现）；
  runner 产出内存 GeoJSON 特征 → 内存图层**。

### libs/qgis/map_session.cpp / layer_adapter.cpp / edit_controller.cpp
- `addVectorLayer(uri, name, binding, &error)`：ogr provider；失败删层并
  返回诊断；layer_adapter 把 layer_id/asset/version/kind 写 custom
  property（join key `pwb/layer_id`）；project_->addMapLayer + syncCanvasLayers。
- **内存图层 URI（QGIS memory provider）**：
  `"LineString?crs=EPSG:4326&field=level:double&field=label_text:string(64)…"`；
  addFeatures 前必须 startEditing 或直接用 provider addFeatures——测试
  fixture 用 memory provider + startEditing + addFeature + commitChanges
  （test_fixtures.make_gpkg_fixture 样板）。
- `layerIdsTopFirst`/`vectorLayerById`/`zoomToFullExtent`/`setDestinationCrs`。
- EditController：start_editing/move_vertex/undo/redo/stage/finalize —
  不动。

### libs/tool_policy/*（全文）
- 词汇表 kToolGroups：`factor` 组已含 `factor_workbench`、`factor_overlay`；
  `rule_factor` = project_gate + stage_whitelist（constraint_factor）。
  **不追加新 id：复用 `factor_workbench` 承载「地质因子图…」**（无阶段时
  仅受 project_gate 约束；project_open=false → disabled "未打开工程"——
  满足 §7.5）。libs/ui/tool_actions 无需改（ToolActionSet 从 evaluate_all
  物化全部词汇 id）。
- layer_roles.hpp：`factor_contour`、`factor_classification`、`factor_grid`、
  `factor_input` 已存在（kLineRoles/kPolygonRoles 不含它们 → 不影响
  既有捕获工具路由）。
- golden 测试（platform.toolpolicy.golden）对全词汇矩阵对账 —— 不改
  评估器就不会降级；新测试行放我自己的 map_pipeline 测试里。

### libs/ui/tool_actions.hpp/.cpp
- `ToolActionSet::apply` 物化/更新 QAction（enabled/checked/visible/tooltip=
  disabled_reason）。动作 id 无中文文本 —— 文本在 MainWindow wire 表里设
  （`action->setText(tr(wire.text))`）。

## C. Python 产品对照

### mapping/geological_pipeline/pipeline.py
- `GeologicalMappingPipeline.extract_factors` —— 与 C++ extract.cpp 冻结
  一致（别名表/坐标族/派生规则/诊断 metadata 逐字段）。
- `interpolate(dataset, options)` → interpolate_factor（C++ 同名函数）。
- 图层生成顺序（build_factor_map_document）：grid → polygon → contour →
  well_point（bottom→top）。**本切片画布顺序：相带多边形在下、等值线在上
  （不含 grid 栅格与井点层——QGIS 内存面/线两层即验收）**。
- `create_well_point_layer`：feature properties = {name, well_id, value,
  unit, factor, formation, qc_flag}；id=well_id or "well_{well_name}"。

### mapping/geological_pipeline/contouring.py
- `generate_contour_layer(grid_result, levels=None, interval=None,
  leveling_mode="nice")`：levels 缺省 nice(7)；feature =
  {type:Feature, geometry:{type:LineString, coordinates}, properties:{level,
  label_text, is_index_contour, length, is_closed, factor, unit}}；
  label = f"{level:g} {unit}"；is_index：interval 路径 = level%(5*interval)
  ≈0，否则 idx%5==0；finite<2 → 空层（levels=[]）。
- **runner 输出的等值线 GeoJSON 特征字段照抄这组 properties**（QGIS 字段
  名即 properties 键）。

### mapping/geological_pipeline/polygonization.py
- `generate_facies_polygon_layer`：阈值缺省 ⅓/⅔ span；facies_names 缺省
  2 阈值 → ["低值相带","中值相带","高值相带"]；色板缺省
  ["#b0bec5","#ffe082","#d73027",…]；每类 polygonize（洞归属/提升）→
  feature properties = {facies_id(1基), facies_name, facies, color,
  area(round4), area_unit, area_percent(占全格), mean_value(round4)}；
  style = categorized renderer on "facies_name"。
- NaN 格元：`class_grid==c & isfinite` 才进 mask；全 NaN → 空层。
- repair_invalid_geometry 在 Python 有；C++ 冻结核对 identity（oracle
  打补丁）→ **runner 输出 Polygon（外环+洞环）不做 make_valid**，
  geometry type 用 Polygon（每 group 一个）。

### mapping/geological_pipeline/interpolator.py
- KrigingInterpolator/IDWInterpolator 语义已冻结进 C++ 核（见 A 段）。
  引擎路径（geoviz WLS/LOO/r_squared）**不在** C++ 核——FactorGrid.method=
  "kriging_fallback"、variogram_fit="numpy-grid-ols" 对应；本切片 IDW 无
  该分歧。
- `_idw_all_neighbors`：p==2 特例 1/dist²、exact-hit last-wins（行主序
  并列后写者赢）、wsum≤0 → NaN —— C++ idw_fill 相同。

### mapping/geological_pipeline/models.py
- GeologicalFactorDataset.valid_points：finite 且 qc∈(ok,good,"")；
  extent 含全部点（含非法 QC）；validate 同 C++。
- InterpolationOptions 默认 method="kriging"（C++ InterpolateOptions 默认
  "idw" —— runner 显式传参，不依赖默认）。

### services/geological_mapping_service.py
- extract_well_factors：WellTable 行 → 记录（well_id/name/x/y/z/H_s/H_t/
  R_s/qc_flag/attributes/properties）；井实体回退（#1131 保留键不被
  metadata 覆盖）；CRS 权威 = project.coordinate.project_crs，空 →
  resolve_crs 回退 EPSG:4326（记录在案）。
- **C++ 切片对应**：井点来源 = 工程内点图层（QGIS 要素读出）或内置
  fixture；CRS 取活动工程/图层 CRS 传 extract options.crs +
  InterpolateOptions.crs（诚实 undeclared 路径：空字符串=未声明）。
- create_factor_map：InterpolationOptions(method, grid_n, variogram,
  color_ramp, contour_levels, crs=dataset.crs)；任务记录/指纹/staleness
  锚点 **不在本切片**（无 B 目录发布要求）。

### tests/test_geological_mapping_pipeline.py（oracle 案例源）
- `sample_well_dataset`：8 井 孔隙度(%) EPSG:4326 T1：
  W1(114.10,22.50,18.5) W2(114.25,22.52,22.3) W3(114.38,22.48,15.2)
  W4(114.15,22.65,24.1) W5(114.30,22.68,19.8) W6(114.42,22.62,12.4)
  W7(114.20,22.80,26.5) W8(114.35,22.82,21.0)。
- 断言翻译成 C++ oracle：kriging g40 全有限+方差≥0；idw g30 全有限；
  contour levels [15,18,21,24] → features>0、首特征 LineString ≥2 点、
  properties.level 在；polygon thresholds [16,22] 三相 → features>0、
  properties 有 facies_name；全 NaN 网格 → 等值线 0 特征 + 相带 0 特征；
  常值网格 → 等值线 0 特征 + 相带 1 特征 area_percent=100。
- audit #1150 系列：0,0 合法坐标保留；缺 y 不跨族；project 族优先；
  缺失计数；混合族诊断。

### mapping/geological_pipeline/geometry_units.py
- `is_geographic_crs(crs)`：委托 D5 权威 crs_policy（异常 → False）。
- `area_unit_label(crs)`：地理 → "deg²"；非空非地理 → f"{crs}-unit²"；
  空 → "unknown-unit²"。
- `ring_area_with_unit(ring, crs)`：地理 CRS → 本地尺度 ≈m² 近似
  （111320·cos(radians(平均纬度))·111320 缩放）+ 警告；投影 → 原始
  shoelace；未声明 → unknown-unit² + 警告。
- `polyline_length_with_unit`：同思路（本切片未消费）。
- runner 复刻前两者（runner.cpp `crs_is_geographic_or_false`/
  `area_unit_label`/`ring_approx_m2`，含弧度换算——第一轮实现漏乘
  π/180 被 oracle 抓出并修复）。

### tests/test_factor_interpolation.py / test_factor_grid_pipeline.py /
### test_e2e_factor_map_contract.py / test_native_factor_map.py
- workflow 侧（factor_interpolation/engine、artifact 缓存、ContourDraft、
  NativeMapScene）——非本切片链路；要点：r_squared 符号语义、grid_z 不入
  任务参数（artifact-first）、方向趋势/约束线不在 geological_pipeline。
- native scene 的 N-S 行序事实（display row 0 = 北）仅作用于栅格镜像；
  本切片矢量层无行序问题。

## D. 平台测试（风格与 fixture 学自）
- test_attribute_ui：QgsApplication(offscreen) + QgisRuntime::acquire →
  真 MainWindow + openProject（copy_tree typical fixture）→ 调公开入口 →
  轮询终态 → 断言落库/显示。**我的 E2E 照此**，但轮询对象是同步 runner。
- test_fixtures：memory provider + startEditing + addFeature +
  commitChanges + QgsVectorFileWriter 写 GPKG；PWB_TEST_SRC_DIR 注入。
- test_framework：PWB_CHECK/PWB_CHECK_MSG + report()，进程级失败计数。
- test_ui_wiring：toolbar/menu 同对象审计 + window.actionWired()。
- test_tool_policy(.golden)：纯快照矩阵；新行（factor_workbench 无工程
  禁用）进我的测试文件，不动 golden。

## E. 文档约束
- cpp-conversion-main-plan：M6/M7 已落地核清单 + 「纯算法核先行 + 冻结
  Python oracle + C++ 对账」方法论；Qt-free 核在 libs、QGIS 接线另文件。
- cpp-entry-switch-review：已覆盖流程证据表；本切片新增「编图计算→画布」
  一行（未覆盖前的诚实缺口）。
- ADR 0057/0059（qgis-authoring-core）：QGIS 是权威制图核；QgsVectorLayer
  renderer 载荷是权威样式模型（qgis_style XML）——**本切片不做样式编辑，
  categorized renderer 字段预留 facies_name**；fallback 不新增专业特性。
- ADR 0059 workarea：工程 CRS 权威 = project.coordinate.project_crs
  （C++ 侧：PwbDataStore 工程文档 coordinate 段；简单路径用图层/画布 CRS
  并透传）。
- geological-mapping-workspace-v5 00-07：阶段=工作流上下文；factor 组
  （phase2.factors/factor.<task_id>）子序 输入→栅格→等值线→分级→不确定性
  →QC；STALE 不删除；QGIS 树是运行时唯一权威 —— 本切片只是把两层放进
  树（无组操作），符合最小边界。

## F. UI/工作区侦察（subagent #1 只读全文扫描，2026-09-17）

覆盖：ui/pages 17 个 factor/map/geological 命中文件（create_factor_map_dialog
/factor_task_panel/factor_prepare_worker/factor_preview_grid/mapping_page/
workarea_map_widget/project_well_map_page 等）、mapping_workspace（layer_roles
/stages/geological_layer_spec/readiness/source_usage）、tests（factor_map_
product_model / native_factor_map_export / factor_layer_products /
factor_map_architecture_guards / mapping_crs_idw 全文）。

关键契约（照抄，不发明）：
1. 角色 vocabulary 精确串：`factor_input/factor_grid/factor_contour/
   factor_classification/factor_uncertainty/factor_qc`；factor 角色全部
   不可编辑；grid/classification 是 RAW 保护（输出只来自显式域动作）——
   C++ 新图层注册 facts 时 write_granted=false + role 用上述串。
2. geological_layer_spec 绑定字段（QGIS schema 对齐）：
   factor-contour-v2 → line，字段 level(real,required)/is_index_contour(
   bool)/unit(text)；factor-classification-v2 → polygon，字段
   facies_name(required)/area(real)/area_unit(text)。**内存图层字段按此
   建**（+label_text/length/is_closed/factor 等 Python feature properties
   超集）。
3. CreateFactorMapDialog 流程：因素组合（砂岩厚度/地层厚度/孔隙度/渗透率/
   TOC/古水深/砂地比）→ 层位（工程 horizon 优先，缺省 T1）→ 方法（克里金
   缺省/IDW）→ 网格 N（20–300 缺省 50）→ 图层复选（相带多边形默认关）。
   成功 `成功生成地质图件：{title}\n包含 {n} 个 GIS 图层。`；失败
   `地质编图失败：{error}`。C++ 对话框字段最小化（因素/层位/方法/网格 N）
   并沿用同一成功/失败措辞方向。
4. mapping_page `_on_create_factor_map_requested`：无工程 →
   「请先打开或绑定工程。」（模态 info）——C++ 无点数据时的提示对齐。
5. CRS 权威 = project.coordinate.project_crs；空 → EPSG:4326 回退（记录在
   案）；描述性拼写经 crs_contract 归一。C++ 切片：工程 store 存在时读
   coordinate.project_crs，否则图层/空=未声明诚实路径。
6. IDW 契约（#1048/#1150/#1131）：power 缺省 2；半径/min_neighbors 之外
   NaN；精确命中返回井值；x=0 合法；2000 井×200² < 5s（不适用于本切片
   规模）。
7. 架构守卫（test_factor_map_architecture_guards）：面向算法的模块必须
   GUI-free——C++ runner 保持 Qt-free，QGS* 只在 main_window 接线层。
8. source_usage/exports/lineage、MapProduct 门槛（grid_artifact_version_id
   等）不在本切片（无 catalog 发布要求），如实记录为未移植边界。
