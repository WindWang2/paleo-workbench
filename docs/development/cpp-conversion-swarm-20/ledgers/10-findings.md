# CONV-10 findings — representative_facies + point_to_surface 纯数据部分

逐文件全文阅读后的符号级结论。格式：输入 / 输出 / NaN-空-并列 / 与已有 C++ 核的关系 / 测试缺口。
「已移植」指本切片落入 `libs/mapping_kernel/include/pwb/mapping/representative_facies.hpp`
与 `src/representative_facies.cpp`，冻结于 `representative_facies_oracle.json`。

## paleo_workbench/mapping/well_prediction_surface.py（全文 443 行）

### 常量
- `POINTS_LAYER_TASK_ID = "well_facies_points"`、`SURFACE_LAYER_TASK_ID = "well_facies_point_to_surface"`：
  纯标记常量，被 UI 层（stage_actions/layer membership）钉死；C++ 核不需要，移不移皆可——不移植（无行为）。
- `_DEFAULT_GRID_N = 80`：已有 C++ `nearest_neighbor_class_grid` 默认参数 80 一致。

### WellFaciesPoint（dataclass，已移植）
- 输入：x, y, facies（必填）；well_id/well_name/task_id 字符串默认 ""；probability/thickness 可空。
- 输出：值对象。C++ `WellFaciesPoint` 同字段，`std::optional<double>` 表示 None。
- NaN/空：无内建约束；构造方负责（`_spatial_point_features` 里 x/y 已过 `_finite`）。
- 与已有 C++ 核的关系：已有 `FaciesPoint{x,y,facies}`（class_grid.hpp）是其子集；
  点到面入口做字段收窄（`nearest_neighbor_class_grid` 只看 x/y/facies，签名不动）。
- 测试缺口：Python 测试无直接构造断言；经 `well_facies_points`/`point_to_surface_features` 间接覆盖。

### _finite(value)（模块私有，已移植为内部函数）
- 输入：任意 JSON 标量（Python 任意对象）。`float(value)` 成功且 `math.isfinite` 才有值。
- 输出：`float | None`。
- NaN/空：inf/nan → None；bool → 1.0/0.0（bool 是 int 子类）；字符串走 `float(str)`
  （前后空白、十进制/指数、PEP 515 下划线；inf/nan 词与 Python 终态一致 → None；
  Unicode 十进制数字位为声明的不复刻边界，见 decisions #15）；
  null/对象/数组 → None（TypeError/ValueError）。
- 与已有核的关系：mapping_kernel 尚无同款；本次在 representative_facies.cpp 内实现。
- 测试缺口：Python 测试未直接测；oracle 以 "inf"/"abc" 字符串字段钉住解析分支。

### well_xy(well, project)（**不移植**——域对象胶水）
- 输入：WellEntity + ProjectDocument。优先 project_x/y → surface_x/y → 井表行匹配
  （`normalize_well_name`（NFKC+casefold+分隔符折叠）后交集非空即用该行 x/y）。
- 输出：`(x, y) | None`。
- NaN/空：任何一级拿到非有限值就落下一级；well_id/name 均空 → want 空 → 不匹配。
- 与已有核的关系：依赖 project 域模型（wells/well_tables/normalize_well_name），属 host 接线层，
  mapping_kernel 无域模型，留在 Python（M10 UI 层任务）。归一化匹配核 name_search 已有 C++ 先例。
- 测试缺口：`test_well_xy_prefers_project_crs` 只钉了第一级；表回退路径无 Python 测试。

### representative_facies(regions, *, horizon="")（**已移植**，本切片主角）
- 输入：dict 序列（region/interval 记录）+ horizon 字符串。
- 输出：`(facies, mean_p|None, thickness) | None`。
- 语义（排序键表，见 §7.1）：
  1. 只收 dict；horizon strip 后非空 → 过滤 `horizon_text in str(record.get("stratigraphic_unit") or record.get("horizon") or "")`
     （子串包含！非全等）；**匹配集为空则放弃过滤**（保留全部）。
  2. facies = `str(facies or label or name or "").strip()`；空 → 跳过该记录。`or` 是 Python 真值链：
     空串/0/False/None 落下一键。
  3. thickness = top/bottom 都能 `_finite` 时 `abs(bottom-top)`，否则 0.0。
  4. probability = `_finite(probability or confidence)`——**先取值后 `_finite`**：probability="abc"
     （真值但解析失败）不会回落 confidence。
  5. 累计 per-facies (thickness, mass, weight)：`sample_weight = thickness if thickness > 0 else 1.0`
     （无厚度记录概率权重 1）；mass += p*sw；weight += sw。
  6. 选取：`max(items, key=(thickness, mass/weight if weight else 0.0))`——Python max 取**第一个**
     最大值 ⇒ 全并列时先插入的 facies 胜（稳定次序）。
  7. mean_p = mass/weight（weight==0 → None）。
- NaN/空：regions None/空/全非 dict/全空 facies → None；top="inf" → 视为缺 top。
- 与已有核的关系：无依赖，纯数据；返回值供点要素 properties。
- 测试缺口：Python 4 例（最厚、同类累计、层位过滤、并列未测）；
  oracle 补：全概率无厚度、并列稳定次序、confidence 回落、0 概率回落、负厚度 abs、字符串数值、匹配空回退全量。

### _task_regions(task)（纯核心已移植为 `task_regions(summary)`）
- 输入：`task.result_summary` dict。spatial 为 dict 时取之；`spatial.get("intervals") or spatial.get("well_intervals") or []`
  真值链；非空 list 才收（过滤 dict）；否则 `summary.get("predicted_regions") or []` 同样过滤。
- 输出：list[dict]。
- NaN/空：全空 → []。intervals=[]（falsy）落 well_intervals → 再落 predicted_regions。
- 与已有核的关系：mock 设计文档（2026-09-10）钉死 regions 形状
  `{region_id, well_id, well_name, stratigraphic_unit, top, bottom, facies, probability}`；本函数是其消费端。
- 测试缺口：无直接 Python 测试（mock 测试间接覆盖 predicted_regions 路径）；oracle 补 intervals 优先/well_intervals 回退/regions 回退/空。

### _spatial_point_features(task)（纯核心已移植为 `spatial_point_features(summary, task_id)`）
- 输入：result_summary + task.id。`spatial.features` 非 list → []。
- 过滤链：dict → geometry dict 且 type=="Point" → coordinates list/tuple 长度≥2 → x/y `_finite` →
  properties 里 facies/label/name 真值链 strip 非空。
- 输出：WellFaciesPoint（thickness 恒 None；probability 走 probability or confidence 真值链再 `_finite`；
  well_name = `well_name or well`）。
- NaN/空：任何一步不过即丢弃该条，不报错。
- 与已有核的关系：产出直接可喂 `nearest_neighbor_class_grid`。
- 测试缺口：`test_spatial_point_features_used_when_present` 一例；oracle 补几何/坐标/相名各过滤分支。

### _wells_for_task / _points_from_intervals（**不移植**——域对象胶水）
- 依赖 `well_registry`、`entity_ids_for_asset`（project 域），井分组键 well_id/well_name/well；
  单井特例：全组键为 "" 且恰一井时直接归属。`_emit` 里 `thickness if thickness else None`（0.0 → None）。
- 留 Python（host 接线）；C++ 宿主拿到 (xy, records) 后可直接调 `representative_facies`。

### well_prediction_tasks / well_facies_points（编排，**不移植**）
- `well_facies_points`：target = horizon 或 stratigraphy.target_horizon；每 task 先空间点后区间回退。
  编排依赖 task 分类（`classify_prediction_task`），域对象遍历留 Python。

### point_features(points)（**已移植**为 `point_features`）
- 输出 (geometry, properties) 对：`{"type":"Point","coordinates":[x,y]}` +
  `{facies, well_id, well_name, prediction_task_id[, probability][, thickness]}`——键序即插入序；
  probability/thickness None 时**键缺席**（不是 null）。
- 测试缺口：无直接 Python 测试；oracle 补全字段/缺字段两例，C++ 按键集合精确比对。

### _extent_from_workarea / _extent_from_points / _clip_ring（纯核心已移植）
- workarea：boundary 顶点取 float 失败/非有限跳过；有限顶点 <3 → None；否则 bbox。
- points：全部点的 min/max；`span = max(max-min, 1.0)`（1.0 下限！）；10% padding 四向外扩。
  空列表 Python 会 ValueError——C++ 前置条件非空（invalid_argument）。
- clip ring：有限顶点 <4 → None，否则清洗后的环。注意 ≥4 而 **非 ≥3**（closed ring 惯例）。
- 测试缺口：无直接 Python 测试；oracle 以真实私有函数冻结（ring bbox / padding / 短环）。

### nearest_neighbor_class_grid（**已有 C++，禁止改**）
- 已在 `class_grid.hpp/.cpp` 冻结（10 案例）。本切片只调用：`point_to_surface_features`
  组 `FaciesPoint` 收窄后传入。clip 语义 inclusive PIP，NaN 出格。

### point_to_surface_features(points, *, project=None, grid_n=80)（**已移植**，descriptor 版）
- Python 链：`len(points)<1 → []`；extent = workarea bbox 或 points+padding；ring = `_clip_ring(project)`；
  `nearest_neighbor_class_grid` → `FactorGridResult`（factor_name 测井预测相 / algorithm nearest_neighbor /
  parameters{method,n_points,grid_n} / crs）→ `generate_facies_polygon_layer(thresholds=[0.0] 或 [i+0.5]、
  facies_names、clip_ring、name 测井预测相（点到面）)` → features 抽 (geometry, properties)，
  `properties.setdefault("facies", facies_name or "")` + `properties["source"]="well_point_to_surface"`。
- 阈值：n_class==1 → [0.0]；否则 [0.5, 1.5, ...]（进 layer 后 `sorted(set(float))` 去重排序）。
- 分类：`class_grid = zeros; for idx,th: grid_z >= th → min(idx+1, n_names-1)`（NaN 比较为 False ⇒ NaN 格保持 0
  但被 `& isfinite` 排除出任何类）。
- 每类：`c_mask = (class==c) & isfinite`；无格跳过；`mean_val = float(np.mean(grid_z[c_mask]))`
  （float32 语义，C++ 以 `(double)(float)(sum/n)` 复刻到 4 位舍入精度）；`_polygonize_raster_boundaries`
  （C++ `polygonize_class` 已冻结同款，dx=span/w、插入序遍历、洞指派、**repair=identity** 先例）。
- 属性（键序）：facies_id=c+1(int)、facies_name、facies、color=默认调色板[c%6]、area=round(raw,4)、
  area_unit=area_unit_label(crs)、area_percent=round(raw/total*100,4)、mean_value=round(mean,4)、
  [geographic: area_approx_m2=round(scaled,4)]、source。raw_area=max(0, ext−Σholes)（shoelace）；
  total_grid_area=max(1e-12, span_x*span_y)。
- **范围裁决（见 decisions）**：多边形级 `_clip_polygon_to_ring`（shapely intersection）与
  `repair_invalid_geometry`（make_valid/orient）不复制（polygonization 切片已定 repair=identity 先例）；
  C++ descriptor 只复刻 clip_ring=None 的 polygon 路径；grid 级 clip 由
  `nearest_neighbor_class_grid` 已冻结的 NaN 掩膜承担（class_grid_oracle 已冻 clip_square）。
  Python 端 `_task_regions`/`_spatial_point_features`/`point_features`/extent/clip-ring 纯核心全部移植。
- 测试缺口：`test_point_to_surface_assigns_nearest_well_facies` 只断言 facies 名集合；
  oracle 冻结完整 features（几何坐标 + 全属性 + 键型）。

## 已有 C++ 核（只读复用，禁改）
- `class_grid.hpp/.cpp`：`FaciesPoint`、`ClassGrid`、`point_in_ring_inclusive`、
  `nearest_neighbor_class_grid(points, extent, grid_n=80, clip_ring={})`；空点抛
  invalid_argument（文案已冻结）。本切片唯一栅格来源。
- `polygonization.hpp/.cpp`：`classify_grid`（含 NaN≥th=False、cap min(idx+1,n-1)）、
  `unique_sorted_thresholds`、`polygonize_class`（identity-repair 语义、dx=span/w、插入序缝合、
  洞多数票指派、升位洞提升计数）、`shoelace_area`、`simplify_collinear_ring`。24 案例冻结。
- `contouring.hpp`：`Grid{w,h,grid_x,grid_y,grid_z(double)}`、`round_to`（Python round 半偶）、
  `linspace`（interpolator.hpp）。
- `crs_policy.hpp`：`crs_is_geographic(optional<string>) → optional<bool>`（builtin 表，未知 nullopt；
  Python 侧 None/异常 → False 同型）。`area_unit_label` 映射：true→"deg²"；非空→"{crs}-unit²"
  （**strip 后**的 crs）；空→"unknown-unit²"。
- `domain json.hpp`：`Json = nlohmann::ordered_json`（对象键序保持）、`json_semantically_equal`
  （int≠float 类型敏感）——oracle 比对用。

## paleo_workbench/mapping/factor_layer_products.py（prediction 相关，已读 547-652 + 头部）
- `classify_prediction_task(task)`：input_refs 键名拼接 lowercase 含 "seis"→seismic；含 "well"/"log"→well；
  再 task.name 里 "seis"/"地震"→seismic、"well"/"测井"/"井"→well；否则 unknown。
  **不在本切片移植**（well_facies_points 的编排输入，纯字符串规则，留待接线切片）。
- `confidence_overlay_layers` / `_prediction_polygon_features` / `_probability_of`：
  Polygon/MultiPolygon 过滤 + _PROBABILITY_FIELDS(probability/confidence/confidence_probability/mean_probability)
  clamp [0,1]；与 representative_facies 的取概率口径**不同**（无真值链回落，逐字段 _finite+clamp）。
  不移植（描述符胶水，主计划明示）。
- 约束：本模块 Qt-free、纯 descriptor；诚实规则（不造数据、缺明确 absent_reason）对本切片属性组装是先例。

## paleo_workbench/prediction/spatial_result.py（全文）
- `spatial_type_of`：result_summary.spatial.type 优先，features/polygons→VECTOR_POLYGONS、
  intervals/well_intervals→WELL_INTERVALS、grid/classes→CLASSIFIED_RASTER、否则 NONE。
  `_task_regions`/`_spatial_point_features` 的形状假设与此一致。
- `extract_polygon_features`：Geometry type ∈ {Polygon,MultiPolygon} 且 coordinates 非空才收。
- `validate_spatial_result`/`is_map_compilable`/demo 方块探测（114/22.5/0.04）：校验层，不移植。
- 与本切片关系：只读约束——C++ descriptor 的输入点可以来自 VECTOR_POLYGONS（spatial）或
  WELL_INTERVALS（区间+井位），两分支与 Python 相同优先级。

## paleo_workbench/prediction/mock_facies.py（全文）
- `MockWellFaciesProvider`：每井一条 region（top/bottom=0.6/0.8*td 或 (600,800)；stratigraphic_unit=horizon
  双写 horizon 键；probability round3）→ `result_summary.predicted_regions`。**representative_facies 的
  真实上游数据形状**——oracle 的 region 记录按此构造。
- `MockSeismicFaciesProvider`：自实现 12 锚点最近邻填格 + `generate_facies_polygon_layer(thresholds=[i+0.5])`
  + clip ring（与 well_prediction_surface 同款 inclusive PIP 掩膜）→ VECTOR_POLYGONS。
  说明：它**不复用** well_prediction_surface.nearest_neighbor_class_grid（设计文档明示 prediction 层自包含），
  C++ 不移植该 provider（mock 演示件）。
- `_HONESTY` 标记集：mock 隔离制度，不在纯数据核范围。

## paleo_workbench/workflow/well_table.py（全文）
- 井身份字段：`WellTableRow.well_id`（身份）+ `.name`（显示）；`well_table_from_sample_points`
  的 well_id = `pt["well_id"] or pt["id"] or _id("well")`、name = `pt["well"] or pt["name"] or pt["well_name"] or f"W{i+1}"`。
- `well_xy` 井表回退匹配读 `rows[].well_id/name/x/y`——身份字段即此四列。
- value_key_for_factor_type（z/H_s/H_t/R_s 别名组）：插值域，不移植；其「任务优先、冲突告警」的
  语义纪律是 decisions 的先例参照。
- 与本切片关系：`well_xy` 不移植的直接依据（域模型胶水），但身份字段的真值链口径写进 findings
  供 host 接线切片使用。

## tests/（全部命中文件已全文阅读）
- `test_well_prediction_surface.py`（161 行，8 例）：thickest / sums_same_class / horizon 过滤 /
  well_xy project 优先 / intervals↔xy 连接 / 无 xy 空 / spatial features 优先 /
  point_to_surface 最近邻两相名 + 空点空表 + task id 常量。→ oracle 案例表直接来源。
- `test_stage_prediction_overlay.py`（158 行）：UI 编排（Qt）。纯数据断言仅点层要素数与 facies 集合。
- `test_stage_prediction_mock_actions.py`（212 行）：mock 端到端；regions 形状 `{stratigraphic_unit}=={Sq1}`、
  input_refs、血缘。确认 predicted_regions 消费链。
- `test_mapping_stage_ui.py`（327 行）：阶段面板 UI；与本切片唯一交点=「测井点到面」动作文案。
- `test_render_engine.py`（301 行）：命中仅为同名 `_point_features` helper；渲染引擎，不相关。
- C++ 侧既有 `mapping_kernel.class_grid` 测试（10 案例精确比对 + inclusive/even-odd 分歧钉死 +
  空文案钉死）——本切片测试的结构模板。

## docs（相关 ADR/开发文档）
- `docs/development/cpp-conversion-main-plan.md`：M6 进度明示 nearest_neighbor_class_grid 已落地、
  factor_layer_products 仍是描述符胶水——本切片即补 well_prediction_surface 剩余纯数据叶。
- `docs/superpowers/specs/2026-09-10-mock-facies-prediction-design.md`：regions 契约
  （well_id/well_name 双写；stratigraphic_unit 原值不做二次加工——子串匹配陷阱警示）
  与点到面工区优先惯例。
- `docs/agents/domain.md` / `issue-tracker.md`：无领域词表冲突；PR 走 gh CLI。
- ADR 目录无 point-to-surface / representative 专题 ADR（0051-0068 均不涉本核）。
