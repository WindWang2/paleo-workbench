# 05 — Findings: Haiyou constrained-IDW 数值核（逐符号）

逐文件、逐公开符号的阅读笔记。约定：`输入/输出`、`边界（NaN/空/并列）`、
`与已有 C++ 核的关系`、`测试缺口`。标注 `【移植】` 的符号进 C++ 核；
`【胶水·不移植】` 留在 Python 侧（含理由）；`【等值线·不移植】` 属等值线提取
管线，不影响 `run_constrained_idw` 返回的 `grid_z`（本切片验收只对账网格）。

## paleo_workbench/workflow/constrained_idw_adapter.py（721 行，全文已读）

- `CONSTRAINED_IDW_ENGINE_LABEL`【胶水】：常量 `"constrained_idw"`，进结果 dict 的
  `backend`/`method`。C++ 核不承载 UI/方法路由，不移植。
- `_ensure_haiyou_engine`【胶水】：把 vendored 根塞进 `sys.path` 后 import
  `drawing.single_factor.constrained_engine`，缓存五个符号。C++ 侧不存在此层。
- `_coord` / `_value`【胶水】：host 样本 dict → (x,y) / 有限 value；`x/y` 或
  `lng/lat`，value 接受 `value/z/v`，非有限值丢弃。fixture 生成器用真实实现。
- `_build_wells`【胶水】：点表 → `ConstraintWell(well_id=str(p.get("well") or i))`，
  无效点静默丢弃。测试缺口：`test_build_wells_maps_xy_and_lnglat_and_drops_invalid`。
- `_dedupe_wells`【胶水】：精确 (x,y) 相等 first-wins 去重，返回 (kept, dropped)。
  #399：统一 exact-hit(first-wins) 与 anchor(last-wins) 两种语义。fixture `dup_wells` 覆盖。
- `_build_barriers`【胶水】：折线 → `BarrierLine(line_id=f"break-{i}", active=True)`，
  点数 <2 丢弃。`test_build_barriers_skips_short_polylines`。
- `_build_directions`【胶水】：方向线 → `DirectionLine(ratio=…)`;
  ratio=semi_major/semi_minor（minor>1e-9 才用，默认 18），再 `max(ratio,16)`
  （fb513c2 地板）。`test_build_directions_from_constraint_layers` 断言 16.0 地板。
- `_boundary_from_samples`【胶水·GEOS】：shapely 凸包 + `buffer(0.03*span)` 外扩；
  退化（共线/<3 唯一点）回退 bbox 矩形。**GEOS 依赖不移植**——C++ 引擎直接吃
  解析后的环；fixture 用 spy 冻结真实 hull 环坐标（见 decisions D2）。
- `_anchored_grid_fidelity`（=历史名 `_leave_one_out_grid_fidelity`）【胶水】：
  双线性采样网格在井点的 in-sample 保真（锚定后 ≈1），非交叉验证 #921。
  依赖 `interpolation_evaluation.bilinear_sample_grid/signed_r_squared`。不移植。
- `_CV_FOLDS=4` / `_spatial_fold_assignment` / `_cross_validated_r_squared`【胶水】：
  空间 4 折 CV R²，每折重跑引擎（extract_contours=False）。纯宿主评估指标，
  不影响 grid_z。不移植；`r_squared`/`r_squared_method` 键由 Python 继续产出。
- `_value_range_from_wells`【胶水】：clamp 边界 = 样本 min/max + 微 pad
  （相等时 pad=max(|lo|*1e-6,1e-9)，否则 max(span*1e-9,1e-12)）。经 spy 冻结。
- `_search_radii_from_wells`【胶水】：search_radius=max(diag*1.05, span*0.75, 1e-6)；
  decluster=max(search*0.15, span*0.05, 1e-6)。v6 文档 06 号记录的口径。
- `barrier_buffer_distance_for_crs`【胶水·pyproj】：地理 CRS → 300m/111320 度；
  否则 None（引擎 auto 缓冲按地图单位）。pyproj 不可用时启发式含 "4326"/"wgs84"。
  经 spy 冻结其结果进 config，C++ 不重复实现 CRS 判断。
- `run_constrained_idw`【胶水·总装】： SciPy 强制检查 → 建井/去重 → 断层/方向 →
  边界（用户环 #928 优先，否则 hull）→ 分辨率 clamp [20,200] → Config（use_dirs
  双臂参数：along_track_blend 1.0/0.0、min_cell_g 0.025/0.05、exp_k 8/6、taper
  0.95/0.85、smooth 3.0/1.8、perp 1.85/1.0、corridor 2.65/1.0、decluster 开关）→
  contour levels（suggest_nice_levels_from_range 8 级）→ generate → 结果 dict
  （grid、min/max/mean、boundary、contours、buffer mode、radii）。**数值核是
  `generate_constrained_idw`，本函数是参数组装与报告**；错误分支：<3 有效点
  `ValueError("约束IDW 需要至少 3 个有效样本点（含坐标与数值），当前 N 个。")`、
  全 NaN 网格 `ValueError("约束IDW 未产生任何有效格网单元。")`。

## drawing/single_factor/constrained_engine.py（8826 行，全文已读）

数据类（全部【移植】为 C++ POD）：
- `ConstraintWell`：well_id/x/y/value/is_control_point=False。
- `BoundaryPolygon`：exterior + holes。
- `BarrierLine`：line_id/points/active/block_mode="full_block"/priority=3。
- `DirectionLine`：ratio=18、influence_radius=0（<=0 自动）、priority=1、
  core_radius=0、zone_id、extend_mode="auto"、transition=0。
- `ConstrainedIDWConfig`：33 个字段（grid_resolution=160、power=2、search_radius
  =10000、mask_radius=0、smoothing=2、smooth_across_barriers=False、
  use_extended_search=True、blank_cells=0、buffer_distance=0、
  buffer_applies_to_surface=True、buffer_auto=True、partition_extension=0、
  extend_to_boundary=False、anchor=True、anchor_radius=0、
  anchor_max_residual_fraction=0.16、taper_plateau=0.85、dir_smooth=1.8、
  dir_perp=1.0、dir_corridor=1.0、anisotropic_fill=True、use_curve=True、
  gap_fill=8、limit_to_search_radius=True、contour_* 族、extract_contours=True、
  anchor_preserve_anisotropy=True、along_track_blend=0、min_cell_g=0.05、
  exp_k=6、decluster_radius=6500、decluster_strength=2.0、min_points=3、
  max_points=12、value_min=0、value_max=1、endpoint_tolerance=1e-7、
  boundary_margin_ratio=0.02、data_hull_buffer_meters=0）。
- `ConstrainedGridResult`：grid_z/x/y + contours + diagnostics + surface_*。
  C++ 只移植网格与 diagnostics（contours/surface 不移植，见 decisions D1）。

顶层函数：
- `is_full_block_mode`【移植】：非阻塞词表 {none,off,no_block,soft,partial,0,false}；
  缺失/未知 → full_block（硬打断）。
- `resolve_interpolation_mask_radius`【移植】：explicit>0 用 explicit，否则
  max(search_radius,1.0)。
- `build_well_coverage_mask`【移植】：格元中心距任一井 ≤ coverage_radius²（bool or
  累积，分块不影响结果）。空井/半径≤0 → None。
- `resolve_barrier_buffer_distance`【移植】：requested>0 → (requested,False)；
  legacy_cell>0 → (legacy*step? 不——入参已是 map units) ；无断层或 auto 关 →
  (0,False)；否则 adaptive=max(step*2, search*0.03, extent*0.012) 再
  min(adaptive, extent*0.04, 400.0)。
- `apply_well_residual_anchoring`【移植】：井点残差回写。anchor_radius<=0 时
  preserve_aniso → max(step*4, step*2.5)（=step*4），否则 max(step*10, step*4)；
  core_radius= max(step*0.9, min(anchor*0.22, step*1.6))（aniso）/ max(step*1.5,
  min(anchor*0.32, step*3.0))；有方向时 search_bbox=anchor*max_stretch，
  radius_cells=max(3, ceil(bbox/step)+1)；blend_radius/sigma 两套；
  residual_cap=value_span*0.16；halo_target= center+residual*halo_scale；
  椭圆距离（u/ratio, v*cross）与 cos 半周期衰减；中心格强制 target；
  第二阶段融合（preserve_aniso: radial=exp(-d²/2σ²)，core_mix=0.70/outer 0.35/0.65；
  非 aniso：3×3 局部高斯均值 sample_r=1，sw=exp(-(dr²+dc²)step²/(2σ²*0.35))，
  core_mix=0.85/outer 0.55/0.45）。np.hypot vs std::hypot 允许 1 ULP
  （engine_parity 测试自证 rtol=1e-12）。返回 stats 7 键。
- `generate_constrained_idw`【移植·主入口】：流程 = 校验（<3 井 / 无边界 →
  ValueError，文案见上）→ axes（bbox+margin*0.02 linspace）→ active 过滤 →
  decluster 权重 → 缓冲解析 → boundary/blank/core_stop 掩膜 → 方向半径（曲线
  模式保留哨兵 0）→ well_coverage 掩膜（limit=True 默认）→ hull 存在性
  （limit 路径不物化 hull 栅格，#924 修复：data_hull_present=data_hull_exists）
  → domain=boundary&~blank(&coverage) → 近线掩膜 → region labels（BFS+LOS）→
  井区域归属 → 方向几何/缓存/legacy 场/井曲线坐标 → 插值（有断层：LOS 掩膜 +
  无方向 batch 核或方向逐点曲线核；无断层：`interpolate_idw_grid_batch`）→
  along-track blend（geoms+use_curve+ratio≥2+strength>0.05）→ 有限计数 →
  补洞（gap_iter=min(gap_fill, 3 if hull_active else 0) 当 limit）→
  smooth_valid_grid(2) → contour_support=bfs_reach(dilation 2.0) →
  refine_domain_boundary_transition(feather 4, iter 2) → 锚定 →
  along-track 复合 → 显示面=working_surface(域内) & display_support(有限) →
  blank&boundary 处 NaN → extract_contours=False 早退（host=True，继续等值线
  提取，但**不再修改返回的 grid_z**）。
- `_point_in_interpolation_mask`【不移植·死代码于 host 路径】：mask_radius<=0 →
  True；有方向用各向异性距离。host config 未走该路径（domain 由掩膜交集构成）。
  记录为未移植偏差（findings 证据）。
- `_build_grid_axes`【移植】：所有边界 exterior 顶点的 bbox；span=max(dx,dy,1)；
  margin=span*max(0,margin_ratio)；linspace(min-margin,max+margin,resolution) 双轴。
  空顶点 → ValueError("边界面缺少有效顶点")。
- `compute_declustering_weights`【移植】：N×N 距离²≤radius² 计数 →
  w=1/count^strength → /mean(w)。radius≤0/strength≤0/n≤1 → 全 1。
- `summarize_point_density`【移植】：孤立（count≤1）/密集（count≥5）计数（diagnostics）。
- `_interpolate_grid_point_euclidean`【移植】：blocked=labels(well≥0≠cell≥0)+LOS；
  radius passes (1.0) 或 (1,1.5,2.25,3.0)，每 pass required=min_points-pass_index；
  候选不足 → None；稳定排序（`argsort(kind="stable")`=等距按原序）取 top
  max_points；w=decluster/max(d,1e-9)^power；wsum≤0 → None。
- `_interpolate_euclidean_cells_batch`【移植·语义等价实现】：#933 逐格批量化，
  上游自证与逐点 bitwise 相同（test_cell_batch_kernel_bitwise_matches_per_cell）。
  C++ 实现逐点参考语义（同选择/同权重/同 np.sum 配对求和），不再复制 batch。
- `_interpolate_grid_point_curve`【移植】：同上但距离用 d_eff、候选用椭圆邻域
  （pairs_in_search_neighborhood）；exact = candidate & d_eff≤1e-9 取第一个
  （used_direction=True）；方向权重 = decluster*(1+corridor*0.35*g_pair[boost])。
- `_interpolate_grid_point`【移植·分发器】：exact-hit 先于一切过滤（≤1e-9 取值，
  blocked 计 0）；use_curve=use_curve && 有井曲线坐标 && cell_dir≥0 && cell_g>1e-9；
  否则 legacy 定角（nearest_direction_context + anisotropic_distance +
  direction_corridor_weight）；无方向 → 纯欧氏 path。
- `point_in_boundary` / `point_in_ring` / `point_on_segment`【移植】：ring<3 →
  False；on-segment(1e-9) 计 inside；半平行射线 (yi>y)!=(yj>y)。
  fast_grid 的栅格化是独立实现（严格 `px < x_intersect`，环上不算内）——域掩膜
  用 fast_grid 版本，此处 ring 版本仅被 point_in_boundary 使用（host 路径未用，
  保留判定语义记录）。
- `is_blocked_by_barrier`【移植】：任一 segment strict 相交即阻断。
- `_barrier_segments` / `_barrier_blocked_mask`【移植】：向量化掩膜与逐点
  `strict_segments_intersect` bitwise 相同（上游 parity 测试锁定）；C++ 逐对标量。
- `strict_segments_intersect`【移植】：|denom|≤1e-12 平行支（叉积>1e-12 → False；
  rr≤1e-24 → False；t 覆盖 (tol,1-tol)）；一般支 t∈(tol,1-tol) 且
  u∈[-tol,1+tol]，tol=endpoint_tolerance。
- `_segment_intersection_point`【移植】：非端点真交点；共线 → None。
- `_decimate_polyline_for_topology` / `sanitize_contour_crossings` /
  `guarantee_no_contour_crossings` / `heal_contour_breaks` /
  `_split_and_gap_at` / `_truncate_pair_at_crossing` /
  `_find_first_contour_crossing` / `_find_first_near_touch` /
  `_polylines_properly_cross`【等值线·不移植】：消交拓扑管线，时间预算驱动
  （perf_counter），只作用于 contours dict。
- `prepare_surface_for_barrier_interrupt` / `interrupt_contours_at_barriers` /
  `enforce_no_barrier_crossing` / `_first_barrier_intersection` /
  `enforce_min_contour_spacing` / `_estimate_auto_contour_spacing` /
  `apply_contour_topology_constraints` / `enforce_strict_no_crossing` /
  `cartographic_smooth_contours` / `project_contours_to_surface_levels` /
  `finalize_contours_hard_no_cross` / `resolve_min_contour_spacing` /
  `_point_on_segment_interior` / `_form_nested_isoline_rings` /
  `_contour_ends_on_data_boundary` / `_point_near_finite_surface_edge` /
  `_absolute_close_gap_cap` / `_both/_either_endpoint_near_barriers` /
  `_closed_ring_should_reopen_near_barrier` / `_is_false_outer_rim_close` /
  `_has_suspicious_closing_chord` / `_nearest_point_on_barriers` /
  `_barrier_seal_midpoints` / `_seal_open_contour` / `_should_force_close_contour` /
  `_polyline_bbox_center` / `_closed_polylines_similar` / `_merge_hybrid_contours` /
  `_keep_closed_contours_only` / `prune_messy_contour_fragments` /
  `push_contours_out_of_buffer` / `trim_contours_at_barrier_buffers` /
  `route_contours_around_barrier_buffers` / `_prune_short_buffer_scraps` /
  `force_wrap_open_ends_around_barrier_tips` / `extend_open_ends_along_buffer_rim` /
  `connect_open_contours_along_surface_edge` / `hug_open_ends_along_barrier_buffer` /
  `remove_barrier_artifact_contours` / `_extend_from` /
  `clip_contours_to_finite_surface` / `_contour_point_supported_by_surface` /
  `postprocess_contours` / `finalize_contour_loop_closure` /
  `extract_closed_high_rings` / `masked_marching_squares` /
  `_ambiguous_marching_segments` / `connect_segments`【等值线·不移植】：
  全部只处理等值线几何；返回的 grid_z 在等值线提取前已定型
  （generate 中 `extract_base_surface` 之后不再写 contour_grid 的有限值，
  仅 blank 处 NaN——该 NaN 语义在提取前已应用）。scipy 依赖
  （binary_erosion/label/maximum_filter）都在这条不移植链上。
- `nearest_direction_context`【移植】：有向线段扫描；perp>radius 且 distance>
  radius → skip；distance>1.25*radius → skip；along 包络（起点前
  1+along/max(radius*0.25,length*0.15)，段内 1，终点后衰减）；perp 包络
  `_direction_taper`；effective_ratio=1+(ratio-1)*env；优选 rank_dist
  （on_seg_bonus=0.15*radius 离段罚）→ priority → -env 的严格序。
  无有效（ratio_eff≤1+1e-9）→ None。
- `_direction_taper`【移植】：plateau 截断 [0,0.999]；≤plateau*R→1；≥R→0；线性。
- `_resolve_direction_radii`【移植】：曲线走廊模式下恒等复制（保留哨兵 0）。
- `build_direction_field`【移植】（fallback legacy 场）：域内逐格
  nearest_direction_context，field=(tx,ty,ratio_eff)，无影响格 (0,0,1)。
- `anisotropic_distance`【移植】：u=沿轴，v=垂轴；cross=max(perp_scale,1)；
  sqrt((u/max(ratio,1))²+(v*cross)²)。
- `direction_perpendicular_scale`【移植】：1+max(ratio-1,0)*max(strength,0)。
- `direction_corridor_weight`【移植】：taper=1/(1+(cross/(R/ratio))²)；
  1+stretch*strength*taper。
- `closest_point_on_segment`【移植】：投影 + 单位切向；len²≤1e-24 → (a, dist,(1,0))。
- `extend_barriers_for_partition`【移植】：barrier_extend_to_boundary=True 时端点
  沿切向外延 map_diagonal（host 默认 False，但语义移植）。
- `build_barrier_proximity_mask`【移植】：线段按 0.5*min(dx,dy) 采样，格 ±2 邻域
  置 True。空 barriers → None。
- `build_region_labels`【移植】：4 邻接 BFS 泛洪；近线格（near[row,col] 或
  near[nr,nc]）做中心连线 LOS（tol=1e-9）；域外 -1；种子扫描行序决定 label 序。
- `assign_well_regions`【移植】：井 → 最近已标号格（半径 0..3 扩环，距离² 严格
  小于更新，先到先得）；找不到 → -2（参与所有区）。
- `apply_barrier_gradient_fade`【不移植】：缓冲区渐变显示效果（host 未调用于
  generate 主路径；grep 证明仅独立显示路径使用）。
- `_point_to_segment_distance`【移植】：len2<1e-12 → 到 a 距离；t clamp [0,1]。
- `build_barrier_blank_mask`【移植】：体育场距离（逐段 clamp 投影，段长≤1e-12 →
  到端点距离），best_d≤R+1e-12；domain 裁切；全空 → None。<2 点的折线跳过。
- `_anisotropic_fill_multiplier`【移植】：stretch≤1+1e-9 → 1；ox=dc,oy=dr*aspect；
  align=|o·tangent|/|o|；1+(stretch-1)*align。
- `fill_internal_gaps`【移植】：fillable=domain&~finite；8 邻域权重（正交 2 斜 1）
  + 各向异性乘子；min_neighbors=2（非最后轮）/1（最后轮）；同区约束 + LOS
  （tol=1e-9，近线格才判）；clamp value_min/max；输出域外强制 NaN；
  返回 filled 计数。逐 pass 复制（next_grid）。
- `complete_gap_fill`【移植】（host limit 路径跳过，API 完整）：BFS 种子=
  邻值 NaN；队列序；同区 + LOS + exclusion；权重 2/1 + 方向乘子；clamp。
- `prepare_contour_extraction_surface`【等值线·不移植】。
- `finalize_contour_loop_closure`【等值线·不移植】。
- `smooth_valid_grid`【移植】：9 offset（中心 4，正交 2，斜 1）；valid=finiteness
  固定于首轮；区域一致 + LOS（offset 预计算掩膜 `_offset_barrier_blocked_mask`，
  tol=1e-9，near 门控）；方向乘子 eff=weight*(1+(base-1)*strength)（base>1 才乘，
  `_anisotropic_fill_multiplier_vec` 语义）；next[populated]=Σv·w/Σw；invalid 格
  保持 NaN。每轮 valid 掩膜不变。
- `refine_domain_boundary_transition`【移植】：scipy `distance_transform_edt`
  （精确 EDT，C++ 用 Felzenszwalb 两趟，见 decisions D4）→ dist_to_edge；
  edge_band=domain & 0<dist≤feather(4)；8 邻域权重×max(edge_factor,0.35)；
  interior=Σv·w/Σw；blend=clip(dist/feather,0,1)；band 格 = interior*blend +
  旧值*(1-blend)；invalid 保持 NaN；scipy 缺失时原样返回（C++ 永不缺）。
- `sample_bilinear_grid`【不移植于本核】：轴范围外/窗口含 NaN → None（宿主
  bilinear 度量用，不属于 grid 生成路径）。
- `_estimate_grid_step`【移植】：nanmedian(diff) 的 max(|dx|,|dy|,1e-9)。
- `_grid_aspect`【移植】：step_y/step_x（step_x≤1e-12 → 1）。
- `_dedupe_consecutive_points` / `_polyline_length` / `_point_distance` /
  `_contour_close_tolerance`(step*0.35) / `_is_closed_polyline`【等值线辅助·
  不移植】（仅等值线管线引用）。
- `_rdp_simplify` / `_chaikin_smooth_polyline` / `_collapse_grid_stairs` /
  `_moving_average_polyline` / `_densify_polyline_segments` /
  `_cartographic_smooth_polyline` / `_remove_polyline_spikes` /
  `_query_local_direction` / `_direction_align_polyline`【等值线·不移植】。
- `_cross` / `_segments`【移植】（LOS/blank 依赖 `_segments`）。
- `_offset_slices`【移植·语义】：向量化邻域切片；C++ 直接双循环等价。
- `_offset_barrier_blocked_mask`【移植·语义】：smooth/refine 的每 offset LOS
  掩膜；与逐点 strict 相交同式（tol=1e-9）；C++ 逐格逐邻居判交等价。

## drawing/single_factor/fast_grid.py（704 行，全文已读）

- `resolve_performance_grid_resolution` / `resolve_adaptive_gap_fill_iterations` /
  `resolve_adaptive_contour_upsample`【不移植】：UI 预算/自适应档位；
  `generate_constrained_idw` 不调用（分辨率由 config 直给）。
- `rasterize_polygon_mask`【移植】：逐环射线 cast，`(yi>py)!=(yj>py)` 且
  **严格** `px < x_intersect`（denom≤1e-30 → 1e-30 护栏）→ 环上格心不算内
  （adapter 注释引用的严格语义）。
- `_direction_perpendicular_scale`【移植】：与 engine 同名函数同式。
- `build_boundary_union_mask`【移植】：exterior≥3 栅格化，hole≥3 取反交集，
  多边形并集。
- `build_domain_mask_fast`【移植】：boundary ∩ ~blank ∩ (areas 并) ∩ coverage
  ∩ hull——host 路径 areas=None、hull=None（limit 路径）。
- `_idw_row_block`【移植·语义等价】：无断层批核。距离 = `np.hypot`（C++ 用
  std::hypot，Linux 同 libm）；exact=≤1e-9 取 argmax 第一真值；方向场（若给）
  aniso=sqrt((u/ratio)²+(v*perp_scale)²)，stretched 才替换；filter=use_extended?
  dist:euc；radius passes；region_ok=(wl<0)|(cl<0)|(cl==wl)（cl<0 全放行——与逐点
  path 的 cell_label≥0 门一致）；top-k= min(max_pts,n_wells) 稳定序（argpartition
  合成键路径与 stable sort 等价，上游 parity 自证）；valid=isfinite(d_k)；
  w=decl*dir/max(d_safe,1e-9)^power（无效 0）；vals=Σ(w·z)/wsum（**未夹 wsum**，
  #828 注释）；update=eligible&wsum>0。线程/分块只影响调度不影响每行数学。
- `interpolate_idw_grid_batch`【移植·入口】：wrap `_idw_row_block`（线程/GPU
  探测：use_gpu 恒 False，#1225 threadpoolctl 作用域化——数值无关）；
  value clamp：isfinite 才夹；域外 NaN。
- `apply_min_decay_to_empty_areas`【不移植】：独立显示衰减（generate 不调用）。
- `dilate_mask` / `upsample_mask_nearest` / `upsample_bilinear_grid`【等值线·
  不移植】（upsample factor=1 时为恒等，host config contour_upsample_factor=1；
  即便如此仍在提取链上，不移植）。

## drawing/single_factor/masks.py（256 行，全文已读）

- `data_hull_exists`【移植】：唯一化排序点集 ≥3 且 monotone chain 凸包（cross≤0
  弹栈，严格凸）≥3 顶点。
- `build_data_hull_mask`【移植】（limit=False 支路需要）：monotone chain 凸包 +
  中心辐射外扩 + 栅格化；空栅格（凸包不含任何格心）仍视为"已物化"并清空整个
  domain（与 fast_grid.build_domain_mask_fast 的 `domain &= mask` 一致）。
- `apply_mask_to_grid`【不移植】：通用工具，generate 不调用。
- `estimate_hull_buffer_meters` / `resolve_data_hull_buffer_meters`【移植】：
  limit=True → min(max(r*0.15, diag*0.02), r*0.5)，r=max(search,1)；决定
  hull_requested → data_hull_active → gap_iterations。
- `build_bfs_reach_mask`【移植】：scipy EDT(~seeds) ≤ cells（精确 EDT）。
- `resolve_bfs_reach_cells`【移植】：limit → min(4, max(2, res*0.02))；否则
  max(res*4, 9999)。
- `resolve_contour_support_dilation_cells`【移植】：limit → min(3, max(2, res*0.015))。
- `build_contour_support_mask`【移植】：= bfs_reach(seed=IDW 有限格, dilation)。
- `build_contour_component_mask`【等值线·不移植】（scipy label 逐组件膨胀；
  只影响提取支撑）。
- `resolve_contour_component_dilation_cells` / `resolve_contour_hole_fill_max_cells` /
  `build_contour_hole_fill_mask`【等值线·不移植】。

## drawing/single_factor/direction_corridor.py（1487 行，全文已读）

- `DirectionLineSpec` / `PolylineGeometry` / `PointCurveCoord`【移植】为 C++ 结构。
- `_unit`【移植】：len≤1e-15 → (1,0)。
- `_polyline_length`【移植】（dc 版本）。
- `resolve_direction_params`【移植】：base_search=max(search,1)；spacing=
  max(spacing, base*0.15, 1)；auto_core=min(max(base*0.65, len*0.12, spacing*1.05),
  map_e*0.16, len*0.20)；auto_influence=min(max(core*3.2, spacing*3.2, base*1.45,
  len*0.30), map_e*0.38, len*0.48)；explicit 组合规则（influence 显式 core 隐式 →
  core=min(auto_core, max(influence*0.55, influence*0.4))；core>influence 三支
  收缩）；core∈[0, influence*0.99]；influence≥core+1e-6；transition≤0 →
  max(influence-core, max(core*0.2,1e-6))；extend_mode 白名单。
- `estimate_mean_well_spacing`【移植·带偏差】：n≤400 全对最近邻均值
  （`np.hypot` 行 + `np.min`）；**n>400 上游用 default_rng(0) 子采样 400——numpy
  PCG64 不跨语言复现**，C++ 决策 D6：n>400 不子采样（全点计算），fixture 保证
  n≤400。d[i]=inf 自身排除。
- `build_polyline_geometry`【移植】：连续重复点（>1e-12）去重；<2 点 → 点复制
  退化几何（total_length=0）；auto/tangent 且 extend>0 → 首尾切向延伸，
  s_start=extend、s_end=total-extend；cumlen 累积。
- `project_point_to_polyline`【移植】：逐段 clamp 投影，dist 严格 `<` 更新
  （并列保首段）；s=cum[i]+t*len；n_signed 左正。
- `project_points_to_polyline`【移植·语义】：向量化版本与逐点同序同式。
- `influence_strength`【移植】：d≤core→1；d≥inf→0；t=(d-core)/(inf-core) clamp；
  g=(exp(-k t)-exp(-k))/(1-exp(-k))，k=max(exp_k,0.5)，clip [0,1]。
- `along_track_envelope`【移植】：span 内（±1e-9）→1；none 模式→0；
  tip≤0 → max(0.1*span,1e-6)；t=越界距/tip，t≥1→0；smoothstep 1-t²(3-2t)。
- `combined_influence`【移植】：g_perp≤1e-12 → 0；tip≤0 →
  max(0.12*max(s_end-s_start,1), core*0.35, 1)；g_perp*g_along。
- `_influence_strength_vec` / `_along_track_envelope_vec` / `combined_influence_vec`
  【移植·语义】：与标量同式（mid 支逐元素）。
- `build_along_track_well_profiles`【移植】：每条 geom：well valid & g≥min_g &
  |n|≤n_lim（n_lim=max(min(core*0.46,inf*0.22), core*0.24, 1)）& 有限值 → (s,z)
  样本；`np.argsort(ss)`（quicksort——s 并列时顺序未定，fixture 避免 s 并列，
  见 decisions D7）；merge_eps=max(core*0.05,1) 桶合并，桶内 `np.median`（偶数取
  两中位均值）；硬规则：首尾 tip 锚点继承最近局部值 z_lo/z_hi。
- `sample_along_track_value`【不移植】：标量版（blend 用向量化 `_interp_profile_vectorized`）。
- `_interp_profile_vectorized`【移植】：`np.interp` 常数外推（ps 升序化—— profiles
  已升序；ps.size==1 常数；==0 全 NaN）。
- `blend_corridor_along_track`【移植】：逐 profile（dict 迭代序=geoms index 序）：
  sel=domain & dir_idx==di & g≥min_cell_g；g_along（span 内 1，左右指数衰减
  e_k=exp(-k_exp)，t≥1 → 0）；g_perp（mid=(core,inf) 开区间，k_perp=max(0.65*k,2)）；
  axis_w=max(0,1-(n_abs/(core*1.65))²)；use=g_along>1e-9 & g_perp>1e-9；
  w_lin=clip(g*g_along*(0.30*axis_w+0.70*g_perp),0,1)；changed=|v_along-base|>1e-9
  & isfinite(base) → w_lin=clip(w_lin*1.45+0.24,0,1)；raw=1-exp(-k*strength*
  (1.05+2.8*w_lin))；alpha=clip(raw/raw_max*0.995,0,0.995)；on_corridor →
  max(alpha,0.78*strength)；on_core → max(alpha,0.995*strength)；use 外 alpha=0；
  fill=use&~finite&(g_perp>0.08) → v_along；blend=use&finite&(alpha>1e-6) →
  (1-alpha)*base+alpha*v_along。stats 4 键。
- `curve_distance_sq` / `blend_effective_distance`【移植】：g≥0.25 →
  g=min(1,0.70+0.30g)；sqrt(max((1-g)e²+g·dc²,0))。
- `elliptical_search_accept`【移植】：r_par=r*(1+g*(a-1)*1.15)；line_length>0 →
  r_par=max(r_par, max(g*len*1.20, len*1.05*g))；r_par=max(r_par, r*a*max(g,0.85))；
  (ds/r_par)²+(dn/r)²≤1 或 (g<0.35 & euc≤r)；g≤1e-9 → euc≤r。
- `build_direction_geometries`【移植】：resolve → extend=min(a*r_base, influence,
  max(map_e*0.35, r_base))（auto/tangent）→ build_polyline_geometry(index=i)。
- `project_points_batch` / `pick_controlling_direction`【不移植】：cache 的标量
  前身（cache 用向量化版实现同一 score 语义）。
- `dual_angle_blend_tangent`【移植】：2θ 向量合成；g=max(a.g,b.g)；ratio 取 g 大者。
- `build_grid_direction_cache`【移植】：仅域内格；逐 geom score=
  g*(1+0.15*prio_boost)/(1+dist/max(influence,1))；is_best=valid&score>best；
  multi_dir（≥2 geoms）时 second 滚动记录；junction compete=hit&second≥0&
  best_g>0.15&second_g>0.15&|best-second|≤max(0.15*best,1e-6) → 双角度混合
  （zone_id 相容才混），g=max(best_g, second_g*0.85)，ratio=blended；
  stretch=1+(ratio-1)*g；15 键 dict。
- `build_legacy_direction_field`【移植】：(tx,ty,max(stretch,1))；g≤1e-9 格清零
  (0,0,1)。
- `precompute_well_curve_coords`【移植】：每 geom 每 well (s,n,g,tx,ty,valid) +
  ratio/zone_id/line_length=max(s_end-s_start, total_length, 0)。
- `_blend_effective_distance_vec` / `_elliptical_search_accept_vec`【移植·语义】。
- `pairs_effective_distance`【移植】：cell_dir<0 或 cell_g≤1e-9 → (euc, 0)；
  wc 缺 → 同；g_pair=min(cell_g,well_g)（valid 才非 0）；a=max(cell_ratio,
  wc.ratio,1)；ds=(cell_s-well_s)/a；dn=cell_n-well_n；d_curve=sqrt(ds²+dn²)；
  d_eff=blend(euc,d_curve,g_pair)；inactive→(euc,0)。
- `pairs_in_search_neighborhood`【移植】：fallback=use_extended? d_eff≤r : euc≤r；
  cell_dir<0 → fallback；wc 缺 → euc≤r；use_extended → 椭圆接受；gp≤1e-9 →
  fallback。
- `pair_effective_distance` / `pair_in_search_neighborhood` / `_well_coords_at`
  【不移植】：标量切片壳（perf 测试断言产品路径不走它们）。

## drawing/compute/performance.py（484 行，全文已读）

- `ComputeSettings` / `get_compute_settings` / `cpu_workers` / `idw_row_block` /
  `use_gpu`（恒 False）/ `use_float32`（恒 False）【不移植】：线程块大小与
  GPU 探测，逐元素数学不变（`_idw_row_block` 分块只影响行分组）。
  `PALEO_HAIYOU_CPU_PERCENT` 环境钮。Windows SUBST/Qt 持久化=host 修复记录。

## drawing/__init__.py、single_factor/__init__.py、compute/__init__.py、
## haiyou_constrained_idw/__init__.py（1/1/17/0 行）

- Qt-free 桩（包根 `__init__.py` 为 0 字节空文件）；compute/__init__ 导出
  settings 访问器。C++ 无对应层。

## paleo_workbench/mapping/geological_pipeline/interpolator.py（1009 行，全文已读）

- `Interpolator`/`KrigingInterpolator`/`IDWInterpolator`/`_idw_all_neighbors`/
  `_idw_knn`/`_pure_numpy_kriging`/`_fit_variogram_numpy`/`_empirical_variogram`/
  `_model_semivariance`/`_deduplicate_samples`/`_kriging_moving_targets`/
  `_solve_single_system`/`_domain_mask`/`_apply_domain_options`/
  `interpolate_factor`：**已在 `libs/mapping_kernel`（M6 第二片）移植并冻结
  （mapping_kernel.interpolator 19 案例）**。与 haiyou 引擎零共享代码——本切片
  是独立第四方引擎（Adapter 文档明确两者互不 import）。只读对照，未改。

## 测试断言 → C++ oracle 案例表（tests/ 全文已读）

- `test_constrained_idw_algorithm.py`：#369 hull 井有限且=观测（平面场 9 点）；
  anchored_fidelity>0.99 且 CV R²<0.99（7 点平面）；3% hull buffer；
  #370 断层走廊 NaN（5 井 20-80 + break y=5）；min=20 来自真实数据；
  #382 死端断层 6 分辨率探针>9 且极差<0.5；无断层确定性 array_equal；
  #399 重复坐标 first-wins（n_points=5、dropped=1、值≈1.0）；
  #400 CRS 缓冲单位（pyproj/启发式）；度 CRS 走廊 ≤1 格；米制 CRS 与 auto
  array_equal；#933 batch=逐点 bitwise（5 组参数×700 格，含标签/LOS/精确命中/
  零 decluster）；generate 走 batch（monkeypatch 断言）。
  → fixture 场景：plain_plane_9、barrier_fault、barrier_deadend、dup_wells、
  error_too_few、error_message 精确匹配。
- `test_constrained_idw_engine_parity.py`：LOS 掩膜 vs 逐对循环（含共线/在线）；
  smooth/refine/anchor vs 标量参考（**anchor 允许 rtol=1e-12，np.hypot vs
  math.hypot 1 ULP**）；blank mask vs 采样版（≤4 格 1-ULP 翻转）；
  euclidean 快路径 vs 参考循环（逐格 `==`）。
  → C++ 对照容差决策 D5；blank 掩膜阈值 R+1e-12 语义保留。
- `test_constrained_idw_integration.py`：契约键齐；grid_n clamp 5000→200、2→20；
  lnglat 输入；同输入 array_equal(equal_nan)；断层 n_break_lines=1；方向
  n_direction_lines=1；断层改变曲面；<3 点 ValueError 匹配 "至少 3 个"；
  cancellation 前中后（胶水）；method 路由（胶水）；CV R² 有符号。
- `test_constrained_idw_diagnostics.py`：adapter 事实进 FactorGridResult
  （search_radius/decluster_radius/buffer mode/duplicates/r² method/fidelity）——
  FactorGridResult 是 Python 侧序列化层，不在本核。
- `test_constrained_idw_p2_perf.py`：pairs 向量化=标量逐对（rtol 1e-12）；
  #524 曲线+断层逐点路径走向量化 pair 函数；#525 块预算。
- `test_constraint_routing_honesty.py` / `test_constraint_capabilities.py`：
  克里金断层→unsupported 诚实上报；IDW→applied；constrained_idw 支持
  boundary+barrier（capability 矩阵）。约束路由是宿主调度，不进数值核。
- `tests/perf/test_interpolation_perf.py`、其余 grep 命中文件均为宿主/产品层
  （factor_interpolation 编排、任务质量指标、UI 注册、perf 预算）——胶水，
  findings 记录不移植原因。

## docs/workflow/AUDIT_MATRIX.md（factor_interpolation 行）

- 输入 sample_points/constraints/method → FactorGrid NPZ INTERMEDIATE；QC=
  quality_metrics+fingerprints；下游 prediction/paleomap；contract gap=
  "horizon version in inputs"；expert question=地质因子定义目录。约束：本核只
  负责"IDW/kriging/constrained IDW"里的 constrained 网格数值，不碰 DataRun。

## docs/development/scientific-interpretation-v6/06-idw-constrained-idw.md

- 普通井间 IDW：断层面权重归零、nodata=NaN、重复坐标不合并（各自投票）——
  与 haiyou 引擎语义**不同**（haiyou 去重 first-wins），移植时不得混同。
- v6 已知 host 常数：search=1.05×diag、decluster=0.15×search、ratio 地板 16/
  默认 18、分辨率 clamp 20–200、度 CRS ≈300 m 缓冲——全部经 spy 冻结，
  C++ 不重推导。

## ATTRIBUTION.md（vendored 根，135 行）

- 上游 WWX9/haiyou-visualization @ 5b8f8f98；只 vendor 纯 NumPy 闭包；host 修复
  三类：显示走廊 NaN（#370）、LOS 点路径恒开（#382）、gap-fill hull 存在性
  （#924）；#933 batch 核 bitwise；性能向量化 parity 锁定。C++ 头注释须携带
  出处与 SHA（decisions D8）。

## scipy 依赖清单（移植语义）

- `scipy.ndimage.distance_transform_edt`：两处（refine 的 domain EDT、
  masks.build_bfs_reach_mask 的 ~seeds EDT）→ C++ 精确 EDT（整数平方距离 +
  sqrt，bit 级一致；decisions D4）。
- `scipy.ndimage.binary_erosion/label/maximum_filter`：只在等值线提取链
  （不移植）。
- `shapely`（adapter hull+buffer）、`pyproj`（CRS 判断）：胶水，不移植。
