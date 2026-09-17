# CONV-03 findings — 等值线/相带 GeoJSON 图层产物（generate_contour_layer / generate_facies_polygon_layer）

> 任务 03 的逐符号阅读笔记。每个公开符号：输入、输出、NaN/空/并列语义、与已有 C++ 核的关系、测试缺口。
> 基线 origin/main @ 35987e13。全文阅读（非 grep 摘录）；行号引用以 worktree 文件为准。

## 1. paleo_workbench/mapping/geological_pipeline/contouring.py（444 行）

### calculate_nice_contour_levels(vmin, vmax, target_count=7) → list[float]
- 非 finite 或 isclose(vmin,vmax)（默认 rel_tol=1e-9）→ `[]`。flat 网格走这里，测试 `test_uniform_flat_grid` 依赖。
- raw_step=span/max(2,target_count)；frac 阶梯 1.5/3.5/7.5 → step ∈ {1,2,5,10}×10^exp；start=ceil(vmin/step)*step；curr 从 start 步进到 vmax，`round(curr, 8)`（Python 半偶舍入）后收集。
- C++ 已有 `nice_contour_levels`（contouring.cpp:157），行为冻结。无需改动。

### calculate_quantile_contour_levels(grid_z, quantiles=(0.1,…,0.9)) → list[float]
- finite<2 → `[]`；`np.nanpercentile(finite, perc)` 'linear' 插值；`sorted(set(round(float(v),6)))` 去重保序。
- C++ 已有 `quantile_contour_levels`。无需改动。

### calculate_polyline_length(coords) → float
- 逐段 `math.hypot` 累加；空/单点 → 0.0。C++ 已有 `polyline_length`。

### douglas_peucker_2d / chaikin_smooth
- C++ 已有（bit 级冻结）。chaikin 的 is_closed 判据是 abs 1e-5（无 rel 项）——已有核保持原样，不动。

### _stitch_segments(segments, simplify_tol, smooth_iterations)
- pt_key=round 6 位；dict 插入序遍历；两段式（开放端点优先、余下成环）。C++ `stitch_segments` 已复刻。**不重写。**

### _marching_squares_pure_python(grid_z, grid_x, grid_y, level, *, simplify_tol, smooth_iterations)
- 16 例 + 鞍点 v_center 均值判据；NaN 胞跳过；`level<min_z || level>max_z` 跳过；edge t 用 `math.isclose` 分母保护。
- C++ `marching_squares_contours` 已冻结 168 案例。**layer_products 直接复用。**

### _clip_polyline_to_ring(poly, clip_ring) → list[list[list[float]]]
- 延迟 import `geometry_operations.clip_polyline_to_ring`：**硬依赖 shapely**（LineString ∩ make_valid(ring)），空 → []。GEOS 交点坐标无法在 Qt-free C++ 侧精确复刻；已有 mapping_kernel 明确未移植 clip。→ 本切片 C++ 不实现 clip（见 decisions）。

### generate_contour_layer(grid_result, levels=None, interval=None, leveling_mode="nice", simplify_tolerance=0.0, smooth_iterations=0, layer_id=None, name=None, style=None, clip_ring=None) → ContourMapLayer
- **早退分支**：`finite.size < 2` → 空 features、levels=[]、metadata `{"contour_qc": {"clipped_to_domain": 0, "empty_after_clip": 0}}`、extent=grid.extent、crs=`grid.crs or ""`。注意 1x1 网格（finite.size=1）与全 NaN/Inf 网格都落这里（tests test_100_percent_nan_grids、test_degenerate_1x1）。
- levels 三路：显式列表原样；`interval>0` → start=ceil(vmin/interval)*interval 步进 `round(curr,6)`；"quantile" → quantile 函数；否则 nice。
- 逐 level：`_marching_squares_pure_python`（含 simplify/smooth 参数）。
- is_index_contour：interval 路径 = `isclose(flevel % (5*interval), 0, abs_tol=1e-5) or isclose(flevel % (5*interval), 5*interval, abs_tol=1e-5)`；否则 `idx % 5 == 0`。**Python `%` 对负 flevel 结果落在 [0, 5*interval)（如 -3%5=2），C++ 必须用 Python-mod（fmod 后按符号修正）而非 std::fmod 直译。**
- label_text = `f"{flevel:g} {unit}".strip()`（有 unit）否则 `f"{flevel:g}"`。`%g` 6 位有效数字、去尾零；C++ 用 snprintf("%g")。
- 逐 polyline（len≥2）：clip 分支（本切片 C++ 不做）→ 每段：
  - length=`calculate_polyline_length`；
  - is_closed = `isclose(x0,x_last,abs_tol=1e-5) and isclose(y0,y_last,abs_tol=1e-5)`——**math.isclose 默认 rel_tol=1e-9 仍然参与**：容差 = max(1e-9·max(|a|,|b|), 1e-5)，大坐标（1e6 级）下 rel 项达 1e-3，不能写成纯 abs 1e-5。
  - properties 键序（Python dict 插入序）：`level`(float), `label_text`(str), `is_index_contour`(bool), `length`(float), `is_closed`(bool), `factor`(str), `unit`(str)。
  - geometry：`{"type": "LineString", "coordinates": poly}`（clip 无时 pieces=[poly]）。
- layer 级：levels、contour_interval=interval、style（默认 `default_style_for("contour")` → **_STYLE_FOR_KIND 无 "contour" 键，实际回退 STYLE_LIBRARY["facies"]**——UI 产物，本切片不迁）、metadata `{"contour_qc": {...}}`（clip 时计数，无 clip 恒 0）。
- 测试缺口→oracle 案例源：显式 levels（test_contour_generation_marching_squares）、quantile（test_quantile_and_fixed_interval）、interval 指标线（同上 + test_m3_adversarial interval=10）、flat/NaN/1x1 早退、单像素峰 is_closed=True、极端量级 1e-6/1e8/负值。

## 2. paleo_workbench/mapping/geological_pipeline/polygonization.py（616 行）

### calculate_shoelace_area / calculate_signed_area / ring_area_centroid
- n<3 → 0.0/0.0；centroid 在 `isclose(area2,0,abs_tol=1e-12)` 时回退首顶点。C++ 已有且冻结。

### _point_in_ring / _hole_vertex_votes / _ring_bbox / _assign_holes_to_exteriors
- 射线奇偶 + bbox 预过滤 + 严格 `votes > best_votes`（最小外环胜出）；未配对洞反转升级为外环并计数。C++ `polygonize_class` 内部已有等价实现并冻结（洞升级计数在 PolygonizeQc）。

### simplify_collinear_ring
- 轴对齐共线删除，abs_tol=1e-9、同向（dx1*dx2>0 / dy1*dy2>0）；keep<3 返回原环。C++ 已有。

### _compute_geometry_area(geom) → float
- Polygon：max(0, ext − Σholes)（shoelace abs）；MultiPolygon：逐 part max(0,·) 求和；其它类型 → 0.0。**layer_products 的 raw_area 直接用它**；C++ 复用 `shoelace_area` 自行组装。

### _polygonize_raster_boundaries(class_grid, grid_z, extent, target_class)
- mask=(class==t)&isfinite；胞边追踪 → 环（len≥4 且首尾 isclose 1e-5）→ 共线简化 → signed>0 外环 / <0 洞 / ≈0 丢弃 → 全是洞时全部反转成外环 → 按面积升序 → 洞归属 → 产出 raw Polygon dict（**未 repair**）。C++ `polygonize_class` 冻结对等（repair=identity 前提）。

### _mapping_to_lists(obj)
- shapely mapping 的 tuple→list 递归转换；仅在 repair 后的 shapely 输出路径用（identity 打补丁时不触发）。C++ 无需。

### _clip_polygon_to_ring(geom, clip_ring)
- shapely intersection；空 → None；GeometryCollection 拆包合并成 Polygon/MultiPolygon。**同 clip 决策：本切片不迁。**

### _filter_small_polygons(geoms, min_area) → (kept, dropped)
- `_compute_geometry_area(geom) < min_area` → 丢（严格 <，等于 min_area 保留——fixture `min_area_equal_dropped` 钉死）。C++ `filter_small_polygons` 只返回 kept；dropped = before−after 在 layer_products 自算（语义等价）。

### generate_facies_polygon_layer(grid_result, thresholds=None, facies_names=None, colors=None, layer_id=None, name=None, min_area=None, clip_ring=None) → PolygonMapLayer
- **早退分支**：`finite.size==0 or h<1 or w<1` → 空 features + polygon_qc 五键（small_polygon_threshold 可为 null / small_polygons_dropped / clipped_to_domain / empty_after_clip / holes_promoted_to_exterior 全 0）。全 NaN、全 Inf 落这里。
- thresholds：None → isclose(vmin,vmax) ? [vmin] : [vmin+span·0.333, vmin+span·0.666]；显式 → `sorted(set(float(t)))`（去重升序）。C++ 已有 `default_class_thresholds` / `unique_sorted_thresholds`。
- facies_names：None 时 len(th)==2 → [低值相带,中值相带,高值相带]；len==1 且 isclose(vmin,vmax) → [均一相带]；否则 [f"相带 {i+1}"]×(len+1)。**显式 thresholds 数与 names 数不一致时按 names 长度 cap：`class_grid[z>=th]=min(idx+1, len(names)-1)`**（int16）。C++ `classify_grid` 已对齐。
- colors：None → default_palette 6 色循环 `["#b0bec5","#ffe082","#d73027","#81c784","#4fc3f7","#ba68c8"]`；feature 的 `color` 取 `colors[c_idx % len(colors)]`。
- polygon_qc 组装序：small_polygon_threshold(可 null) → small_polygons_dropped → clipped_to_domain → empty_after_clip → thresholds([float]) → thresholds_source("explicit"|"data_derived_default") → nodata_cells(int) → total_cells(int) → area_unit(area_unit_label(crs)) → [area_warnings(list, 地理 CRS 或空 CRS 时预置一条)] →（循环内）holes_promoted_to_exterior（get 缺省 0 累加）→（循环内、地理/未声明 CRS 的 ring 警告字符串 append 到 area_warnings）。
- 逐 class（c_idx in range(len(facies_names))）：`c_mask=(class_grid==c_idx)&isfinite`；空 → continue（**跳过的类不产生 feature 也不产 polygon**）；mean_val=float(np.mean(grid_z[c_mask]))——**float32 累加语义**（np.mean 对 float32 输入用 float32 累加器 + numpy pairwise sum；oracle 生成时实测，若 double 直算在 round(,4) 后有边界分歧则须复刻 pairwise）。
- polygonize → [clip（不迁）] → min_area 过滤（`min_area is not None and min_area>0` 才过滤；0/None 不过滤）→ 逐 geom：
  - raw_area=_compute_geometry_area(geom)（CRS 轴单位）；
  - geom_area 仅在地理 CRS 用于 area_approx_m2：`ring_area_with_unit`（ext−holes，每环按环平均纬度 cos 换算 ≈m²，_METRES_PER_DEGREE_LAT=111320），max(geom_area,0)；
  - ring_area_with_unit 的 warning 字符串在首次出现时 append 到 polygon_qc.area_warnings（与预置 warning 文案不同，会各加一条）；
  - area_pct = raw_area/total_grid_area·100，total_grid_area=max(1e-12,(xmax−xmin)(ymax−ymin))；
  - **properties 键序**：`facies_id`(int=c_idx+1), `facies_name`(str), `facies`(=facies_name), `color`(str), `area`=round(raw_area,4), `area_unit`=area_unit_label(crs), `area_percent`=round(area_pct,4), `mean_value`=round(mean_val,4), [地理 CRS: `area_approx_m2`=round(geom_area,4)]。
  - **round(x,4) 是 Python 半偶舍入**（C++ `round_to(value,4)` 已有，168 案例验证）。
- layer 级：categories=[{name,color}×names]（UI 侧渲染分类；本切片不迁 style，features 已带 color）、style（不迁）、metadata={"polygon_qc":…}。
- 测试缺口→oracle 案例源：min_area 丢数并计数（test_small_polygon_threshold_*）、均一相带 100%（test_edge_cases/test_uniform_flat）、洞归属（test_facies_polygonization_with_holes、checkerboard、nested、archipelago）、thresholds 乱序/重复/越界（challenger thresholds_boundary_resilience）、地理 CRS area_unit=deg²+area_approx_m2（test_geometry_units_qa）、undeclared CRS（test_crs_distance_policy：crs=""）。

### polygonize_factor_grid(grid_result, *, level=None) → dict
- level 默认 finite 中位数（numpy median 偶数取均值）；class=(z>=level)→{0,1}；polygons 截 500 + truncated 标记。C++ `polygonize_factor_grid` 已冻结（本切片不触及，确认不被改动）。

## 3. paleo_workbench/mapping/layers.py（716 行）

- `LayerType` 枚举：CONTOUR="contour"、POLYGON="polygon"（dataclass layer_type 字段值即此）。
- `MapLayer`（基类）：id（`lyr_`+uuid4 前 8 hex——非确定性，C++ 产物不迁 id 生成）、name、extent、crs、data_revision/style_revision、visible/opacity、style、metadata、source_version_id；`to_dict()` 平铺序列化。
- `VectorMapLayer`：`features: tuple[Mapping,…]`；`recompute_extent` 走 `geometry_planar.extent_of_geometries` + 退化垫宽 pad=max(1,|min|,|max|)·1e-6、isclose 单边扩 pad；空 features 的层不重算 extent（保留传入 extent）。**本切片 C++ 只打包 features + levels/qc，不做 extent 重算（Python 侧构造函数在 extent 给定时也不重算）。**
- `ContourMapLayer(VectorMapLayer)`：layer_type="contour"、levels list、contour_interval、show_labels；__post_init__ 只在 style 空时填默认样式（UI 语义）。
- `PolygonMapLayer(VectorMapLayer)`：layer_type="polygon"、categories list[dict]；同上，样式懒填。
- `GridMapLayer`（rasterize_rgba/color ramp——渲染侧，不在本切片）；`WellPointMapLayer`、`AnnotationMapLayer`（annotation→Point features 同步）、`RasterMapLayer`、`MapDocument`（layers 聚合/重排/快照）——阅读确认与 feature 打包无耦合。
- 对 C++ 产物的约束：features 元素是纯 GeoJSON dict（{"type","geometry","properties"}），to_snapshot/to_dict 原样携带；C++ 用 ordered_json 输出同构数据即可被 descriptors 消费。

## 4. paleo_workbench/mapping/color_ramps.py（251 行）

- `ColorStop(position,color)`、`ColorRamp.evaluate/evaluate_value/sample_table/to_dict/from_dict`、`_hex_to_rgb/_rgb_to_hex`（3/6/8 位 hex 容错、非法 → 灰 128）、内置 11 条 ramp（viridis/plasma/magma/coolwarm/jet/porosity/permeability/thickness/sand_thickness/toc/water_depth）、`get_color_ramp`（未知回退 viridis）、`register_color_ramp`、`list_color_ramps`。
- **结论：全部是渲染/样式侧数据。** generate_contour_layer/facies 只在 style 缺省时用 `default_style_for`（map_styles），features 的 `color` 来自 polygonization 内联 default_palette，与本模块无关。无 C++ 迁移需求；findings 记录以证明"无样式 UI"边界成立。

## 5. paleo_workbench/mapping/factor_layer_products.py（750 行）——消费方契约

### _contour_child(grid, task_id, title, contour_limit=200) → descriptor
- grid None → absent_reason="no live factor grid (open the preparation page to load)"，features=[]。
- 否则：`levels = calculate_nice_contour_levels(stats.min, stats.max) or None` → `generate_contour_layer(grid, levels=levels, name=…)`；snapshot.features → (geometry, properties) 二元组；metadata 带 feature_count_total/truncated/contour_qc/feature_count。异常 → absent_reason="contour extraction failed: {exc}"（诚实失败）。
- **契约含义：C++ 产物 features 必须是 (geometry, properties) 同构对 + contour_qc 可取；levels 由 nice 路径给。**

### _classification_child(grid, task_id, title) → descriptor
- `generate_facies_polygon_layer(grid, name=…)` 全默认（默认阈值/名称/颜色），features → (geometry, properties)，metadata.polygon_qc 透传；异常 → absent_reason="polygonization failed: {exc}"。
- **契约含义：C++ 默认参数路径（无显式 thresholds/names）必须与 Python 完全一致——这是用户流程验收主路径。**

- 其余符号（_input_child/_grid_child/_scalar_payload/_uncertainty_child/_qc_child/factor_group_layers/classify_prediction_task/confidence_overlay_layers/_iter_polygon_rings/boundary_features_from_polygons/integrated_boundary_action_helpers）：描述符/QC/边界环提取，不触碰本切片的两个生成器；阅读确认无隐藏的 properties 再加工（features 原样透传）。

## 6. 已有 C++ 核（只读复用清单）

### libs/mapping_kernel/include/pwb/mapping/contouring.hpp + src/contouring.cpp
- `Grid{w,h,grid_x,grid_y,grid_z(double)}`、`nice_contour_levels`、`quantile_contour_levels`、`polyline_length`、`douglas_peucker`、`chaikin_smooth`、`marching_squares_contours(grid,level,simplify_tol,smooth_iterations)`、`round_to(v,digits)`（nearbyint 半偶）、`is_close`（rel 1e-9）。
- 缺口（由 layer_products 自补，不改本文件）：带 abs_tol 的 isclose 变体、Python `%` 取模、`%g` 格式化。

### libs/mapping_kernel/include/pwb/mapping/polygonization.hpp + src/polygonization.cpp
- `Polygon{exterior,holes}`、`shoelace_area/signed_area`、`default_class_thresholds`、`unique_sorted_thresholds`、`classify_grid(grid,thresholds,n_classes)`、`polygonize_class(grid,class_grid,target_class) → (polygons, qc)`、`filter_small_polygons(geoms,min_area)`（只返回 kept）、`polygonize_factor_grid`。
- 缺口：facies 默认名/颜色、_compute_geometry_area 的 MultiPolygon 语义、dropped 计数、properties 打包——全部落 layer_products。

### libs/mapping_kernel/include/pwb/mapping/crs_policy.hpp
- `crs_is_geographic(optional<string>) → optional<bool>`（空/未知 → nullopt）。geometry_units.is_geographic_crs = bool(value_or(None))——**nullopt → false**；输入先 strip。

### libs/domain/include/pwb/domain/json.hpp
- `Json = nlohmann::ordered_json`（键序保持）、`json_semantic_diff`（对象键序无关/数组有序/数值类型敏感/缺≠null）——测试断言的基础设施。

## 7. Python 依赖模块（非 §5 但被读全文）

- **geometry_units.py**：is_geographic_crs（crs_policy 委托 + try/except→False）、area_unit_label（deg² / "{crs}-unit²" / "unknown-unit²"）、ring_area_with_unit（地理 CRS：raw·111320²·cos(mean_lat)，≈m² 标签+警告；未声明 CRS：raw + unknown 标签+警告）、polyline_length_with_unit（本切片未用到——contour 的 length 是纯轴长）。
- **topology.py repair_invalid_geometry**：非 dict/非 Polygon|MultiPolygon 原样；Polygon 先做精确相等闭环保守（r[0]!=r[-1] 则 append）；shapely make_valid+orient(CCW)+mapping；异常/无 shapely → 仅闭合修正的几何。**oracle 打 identity 后这些全不发生**；C++ polygonize 核已按 identity 冻结。
- **geometry_operations.py**：clip_polyline_to_ring/clip_polygon_to_ring 均 `_shapely` 硬依赖（"a requested clip must never degrade to silently unclipped output"）；确认 clip 不可移植性判断成立。
- **geometry_planar.py**：射线奇偶/含边 PIP/extent 内核——polygonize/PIP 已有 C++ 对应，无需新动作。
- **map_styles.py**：`default_style_for("contour")` 经 `_STYLE_FOR_KIND`（无 contour 键）回退 facies 预设；style 是 UI 数据，本切片不迁（decisions 记录）。
- **factor_grid_result.py**：grid_z float32(NaN=nodata)、grid_x/y float64、extent=min/max(axes)、statistics float64 全 finite 统计、crs=None 表示未声明；`crs or ""` / `unit or ""` 在 layer 构造处发生。
- **crs_policy.py crs_is_geographic**：空 → None；token=crs.split("/")[0].strip().upper()；projected 例外表优先于 geographic 表；其余 pyproj（C++ 无 → nullopt）。

## 8. 测试断言 → oracle 案例表（fixtures 冻结依据）

| Python 测试 | 断言要点 | 转成 C++ oracle 案例 |
|---|---|---|
| test_contour_generation_marching_squares | 显式 levels=…、features[0] LineString ≥2 点、properties.level 存在 | contour 显式 levels 案例 |
| test_quantile_and_fixed_interval_contour_levels | quantile 模式 levels 非空；interval=2.0 → is_index_contour 每第 5 档 | quantile 案例 + interval 案例（fmod 边界） |
| test_m3_adversarial_contour_polygon §1/2/3/4/5/6/12 | 全 NaN×5 形状（levels 空）、flat（0 特征+1 全域相带 100%）、1x1（两层皆空）、1x10 条带（marching 需 2x2 → 特征空）、1000:1 长条（interval=10、3 相带面积守恒）、checkerboard 鞍点、单像素峰（is_closed=True、洞面积 4800/100）、极端量级 1e-6/1e8/负 | 逐条冻结（真实 Python 输出全量 JSON） |
| test_polygon_quality_adversarial | min_area 丢数计数/None 不丢、NaN 洞、单胞岛 min_area=2 丢 ≥2、窄廊道、常量场=均一相带 | min_area 案例 ×3、NaN 洞、廊道 |
| test_geometry_units_qa | area_unit 前缀/deg²、area_approx_m2>0、nodata_cells/total_cells、未声明 CRS unknown-unit² | CRS 三态案例（projected/geographic/空） |
| test_crs_distance_policy | 层 crs = grid.crs or ""（未声明→""） | crs 传 "" 的属性断言 |
| test_geological_mapping_pipeline | NaN/常量早退（features==0/==1 且 area_percent==100.0）、holes 两名俱在 | 复用上述网格 |
| test_m3_stress_topological_remediation / challenger_m6 | 5 层俄式套娃、群岛多洞、环方向 CCW/CW、阈值乱序重复越界 | 套娃/群岛/阈值边界案例 |
| test_gis_mapping_batch5 | 4x4 对角 ramp → 4 features/3 名（#977 回归钉） | ramp4x4 案例 |

## 9. 关键语义清单（实现必须逐条对账）

1. 属性键与顺序（§1/§2 列表）；ordered_json 保序输出。
2. Python round 半偶：area/area_percent/mean_value → round_to(x,4)；interval levels → round_to(x,6)；nice → round_to(x,8)（已核内）。
3. math.isclose 的 rel+abs 双容差出现在：is_closed（abs 1e-5）、is_index（abs 1e-5）、vmin≈vmax（默认）、洞/环闭合判据（已核内）。
4. Python `%` 负操作数语义（is_index 的 interval 路径）。
5. `%g` 标签格式化（C snprintf %g 对齐，oracle 钉值）。
6. mean float32 累加 vs double（实测 numpy 为 float32 pair-wise + float32 除法；已实现 float32_mask_mean 并由 mean_units 钉死）。
7. **CPython math.hypot ≠ glibc hypot（差 1 ulp）**：length 属性须复刻 CPython vector_norm（幂次缩放 + VD 平方 + Neumaier 补偿和 + 根号微分修正，fma 版）；30 万对模糊对拍 0 失败。max 遇 NaN/inf 用 `if (x>max)` 循环语义（std::max(NaN,y) 语义不同）。
8. facies_id=int、nodata_cells/total_cells=int、bool 原生——json 类型敏感比较下的类型纪律；Python JSON 非负整数解析为 unsigned，测试侧 dump→parse 规范化后比较（线格式一致）。
9. 早退分支的 qc 键集合差异（contour 两键；facies 五键，且 small_polygon_threshold 逐字回显 min_area——审核轮 1 修复）。
10. 空类（c_mask 无元）跳过 → 不产 feature；holes_promoted_to_exterior 键只在循环至少跑过一次后出现。
11. clip_ring：Python 硬依赖 shapely → 本切片 C++ API 不含 clip 参数（decisions D1）。
12. interval 阶梯起点：Python math.ceil 返回 int → 0*interval=+0.0（标签 "0"）；C++ std::ceil 产 -0.0 → 规范化（审核轮 1 修复，contour_neghalf4_interval 钉死）。

## 10. 审核轮 2（完整性）分支矩阵 → 案例映射（最终态）

**contour**：finite<2（nan6/inf6/one1）；显式 levels（ramp8/spike7/constant8）；显式空列表（ramp8_explicit_empty）；interval>0（ramp8/neg3/neghalf4/islands10/holed10）；interval≤0 falls-through 且 contour_interval 记录（ramp8_interval_zero）；quantile（ramp8/plain12）；nice（多例）；is_index 双路径（interval 系 vs idx%5 系）；label 有/无 unit（ramp8 "m" vs islands10 ""）；is_closed 真/假（spike7/其余）；simplify>0（ramp8_simplify）；smooth>0（ramp8_smooth）；负值 %g + 负 flevel 取模（neg3）；极端量级 %g（micro3/macro3）；1xN 条带 marching 需 2x2（strip1x10）；clip 分支 N/A（D1，QC 计数钉 0）。

**facies**：早退五键 + min_area 回显（nan6_default/nan6_minarea/inf6）；默认阈值等值场（constant8）/跨度 ⅓⅔（ramp8/batch4/donut10/geo 系）；显式阈值 sorted(set)（ramp8_explicit 乱序+重复）；默认名三档/均一/"相带 N"（ramp8/constant8/nested12）；显式名（spike7/ramp8_names_short）；名少于 thresholds+1 类 id cap（ramp8_names_cap）；默认色板/显式 colors（ramp8_colors）；空类跳过（ramp8_outside_high 类 1/2 无元）；min_area None/0/正/相等（moat12 四例）；CRS projected/geographic/未声明（geoproj12/geodeg12/geonone12）+ area_approx_m2 + area_warnings 双文案 + 逐环警告去重；洞升级计数（promote8 fallback——400 种子猎取无 >0，与 polygonization oracle 同状，QC 管道冻结）；float32 均值（mean_units 10 档尺寸 + 全部案例端到端）；MultiPolygon 几何在 identity-repair 下不可达（始终 Polygon，已记录）。
