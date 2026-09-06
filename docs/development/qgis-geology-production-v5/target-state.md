# Target State — QGIS 地质编图生产线 v5

格式约定：每项完成时勾选 `[x]`，并在括号内注明验证测试/证据文件。Goal 结束前不得留下伪完成项。

## M0 — 审计与规划

- [x] 三路源码审计完成（科学链/制图层/构建环境），结论落在 baseline.md
- [x] baseline/target-state/decisions/verification 四件套建立
- [x] 前置缺陷修复：setup.py `resource_database` NameError（commit 89601913；构建日志 + 桥 import + tests/test_qgis_layout_export.py 全套运行）

## M1 — 单因素图统一产品模型

- [x] `FactorMapSpec` 显式输入契约：factor identity/unit/源版本/target horizon/bounds+mask/faults/method/parameters，可序列化、可指纹（workflow/factor_map.py；tests/test_factor_map_product_model.py）
- [x] `FactorMapOutput`（等价扩展，包装 FactorGridResult）显式输出：grid/uncertainty/QC/provenance/map layers（tests/test_factor_map_product_model.py::test_factor_map_output_assembles_qc_and_provenance）
- [x] 主管线 unit 贯通：四处构造点全部传入（tests/test_factor_map_product_model.py::test_task_pipeline_propagates_known_unit_to_grid_and_metrics）
- [x] 派生因子带 derived 溯源标记（tests/test_factor_map_product_model.py::test_extract_factors_derived_sand_ratio_carries_provenance）
- [x] 禁止 `z → Rs → Ht` 隐式 fallback 保持废除（tests/test_factor_map_product_model.py::test_no_implicit_z_to_rs_to_ht_fallback）
- [x] 覆盖因子族抽查含 probability/paleo-water-depth（tests/test_factor_map_product_model.py::test_factor_unit_authority_covers_goal_factor_families）

## M2 — 插值工作站 V2

- [x] 统一精度评估层：空间 K 折 CV（注入生产镜像 run_fold）+ 克里金精确 LOO 产出 RMSE/MAE/bias/R²（workflow/interpolation_evaluation.py + workflow/factor_interpolation.py::cross_validate_factor_task；tests/test_interpolation_evaluation.py）
- [x] residual map：surface_check/surface_residuals + residual_features GeoJSON 点层（tests/test_interpolation_evaluation.py::test_surface_residuals_labelled_in_sample）
- [x] 克里金诊断整合：kriging_diagnostics（经验变差函数 + range/sill/nugget，defaulted 标注）（tests/test_interpolation_evaluation.py::test_kriging_diagnostics_reports_variogram_fit）
- [x] IDW 双轨决策落地（decisions.md D4：任务管线 geoviz IDW 为权威，kNN 变体显式标注）
- [x] CV 计算与显示分离：评估返回 CrossValidationReport/EvaluationMetrics 数据对象；residual_features 仅生成 GeoJSON 特征（tests/test_interpolation_evaluation.py::test_residual_features_are_geojson_points）
- [x] 不确定性可视化：variance grid + M5 融合置信度格网可构建为 FactorGridResult（unit="1"）挂图层（tests/test_factor_fusion.py::test_variance_propagation_on_common_support）

## M3 — Boundary / CRS / Unit 科学正确性

- [x] 消除 contouring.py / polygonization.py 的静默 EPSG:4326 回退：CRS 未声明时图层显式携带"未声明"状态而非猜测值（tests/test_mapping_crs_*）
- [x] 插值距离策略显式化：resolve_distance_policy 全链标注 + geographic CRS 显式警告；不可验证 CRS 注记 unverified（workflow/crs_policy.py；tests/test_crs_distance_policy.py）
- [x] unit 显式贯通 extract → interpolate → grid → contour 标注（tests/test_factor_map_product_model.py + grid.unit 进 contour label_text）
- [x] mask/boundary 单点消费（interpolate_factor 域掩膜）+ clip_ring 贯穿 contour/polygon/FactorMapOutput（tests/test_crs_distance_policy.py::test_interpolation_options_boundary_is_consumed_as_domain_mask + tests/test_polygon_quality_adversarial.py clip 组）
- [x] 0 坐标不丢失回归保持（test_mapping_crs_idw/test_geological_mapping_pipeline 全绿）

## M4 — 等值线 / 分区 / 相带质量

- [x] 小多边形处理参数化 min_area + QC 计数（tests/test_polygon_quality_adversarial.py::test_small_polygon_threshold_drops_and_counts）
- [x] 用户域 clip_ring 贯穿 contour + polygon（shapely fail-closed；tests/test_polygon_quality_adversarial.py::test_facies_layer_clips_to_user_domain 等）
- [x] 孔洞归属确定性（环顶点多数票 + 未匹配晋升孤岛，消灭"塞给第一个"兜底）
- [x] adversarial 套件 8 场景（tests/test_polygon_quality_adversarial.py；既有 test_m3_adversarial_contour_polygon.py 保持绿）
- [x] invalid geometry repair 在 polygon 输出前强制（polygonization 每 geom 调 repair_invalid_geometry；self-intersecting clip ring 用例覆盖）

## M5 — 多因素融合框架

- [x] `FusionModel` 数据契约：可序列化 + 指纹 + from_dict 校验（tests/test_factor_fusion.py::test_model_roundtrip_and_fingerprint 等）
- [x] weighted evidence 融合：归一化 → 加权（NaN 重归一）→ likelihood（tests/test_factor_fusion.py::test_weighted_fusion_exact_maths 等）
- [x] rule-based classification：有序首中规则 + 显式默认类（tests/test_factor_fusion.py 规则组）
- [x] 不确定性传播：平方权方差传播 + coverage×agreement 置信度（tests/test_factor_fusion.py::test_variance_propagation_on_common_support）
- [x] leave-one-factor-out sensitivity（tests/test_factor_fusion.py::test_sensitivity_identifies_dominant_factor）
- [x] 融合结果 → facies polygon 图层（tests/test_factor_fusion.py::test_fused_likelihood_builds_facies_polygons；装配走既有 assemble_map_product 链）
- [x] 融合输出经 catalog 单一写路径注册 DERIVED+DataRun（tests/test_factor_fusion.py::test_register_output_creates_derived_version_with_run）

## M6 — Map Component Graph（扩展现有 composer）

- [x] 组件清单补齐 SUBTITLE/WELL_LEGEND/PROFILE（models.py ElementType + registry specs；tests/test_map_component_graph.py）
- [x] 组件统一 serializable/editable/z-order（ComposerElement + CompositionEditSession；tests/test_composite_editing.py 285+ 绿）
- [x] 模板 = 组件图 + 默认 + 绑定（composer/templates.py 9 套；registry 测试覆盖）
- [x] Profile/WELL_LEGEND 未绑定仅渲染占位框（tests/test_map_component_graph.py::test_profile_unbound_renders_placeholder_only）

## M7 — QGIS 原生组件映射

- [x] 桥窄接口 layoutExport：瞬态 QgsPrintLayout + QgsLayoutExporter PDF/SVG/PNG，导出即弃（tests/test_qgis_layout_export.py，7 项全绿）
- [x] MAIN_MAP 成图内容走 QGIS 渲染路径（layout map item 直接渲染镜像 QgsMapLayer；tests/test_qgis_layout_export.py::test_layout_export_vector_content_survives）
- [ ] 色带映射（未做，显式保留）：标量层仍走预栅格化 RGBA 镜像；单带伪彩 renderer 映射涉及 scalar mirror 管线重构，留待后续（decisions.md 未列新裁决）
- [x] vendored QGIS 复用构建成功（REUSE_VENDOR=1；桥本体 4 次增量重编；verification.md）
- [x] 桥 API 纯 JSON spec/报告（layoutExport；review R2 确认无 domain 泄漏）

## M8 — 图层管理 / 编辑 / 属性闭环

- [x] 图层操作矩阵回归全绿（visibility/opacity/reorder/rename：mapstack 套件；group/duplicate：composite_editing/composite_document 既有实现 + 测试）
- [x] 属性表过滤 + 排序 + 选择同步（tests/test_map_attribute_table.py 6 项含 filter/sort/selection-survival）
- [x] 编辑闭环回归全绿（test_composite_editing.py；vector_layer 命令栈/几何服务/拓扑未改动）
- [x] echo 防护回归保持（mapstack lifecycle/tools 套件绿）

## M9 — Geological Style Library

- [x] 地质样式库 9 类可版本化 JSON（mapping/geological_style_library.py schema v1；tests/test_geological_style_library.py）
- [x] categorized/graduated/line pattern/marker/legend label 全支持；透明度经图层 opacity_hint（样式不持有透明度权威）
- [x] 样式绑定可追踪（style_binding field/classes 随 layer.style；tests/test_geological_style_library.py::test_apply_style_records_binding_and_opacity_hint）

## M10 — MapProduct Lifecycle V2

- [x] clone（tests/test_map_product_lifecycle.py::test_clone_is_independent_record_over_same_versions）
- [x] rerun：经 assemble 单一 run graph 重建 + supersede 前任（tests/test_map_product_lifecycle.py::test_rerun_creates_successor_and_supersedes）
- [x] compare：指纹/因子快照（方法/参数/网格版本/QC）/解释引用/组合/输出 sha256（tests/test_map_product_lifecycle.py::test_compare_reports_factor_and_hash_differences）
- [x] promote/supersede/freeze/publish 门面 + 状态机防护（tests/test_map_product_lifecycle.py::test_supersede_frozen_and_double_supersede_refused 等）
- [x] describe 报告 staleness（workflow/map_product.py describe_map_product；tests/test_map_product_lifecycle.py::test_staleness_detects_rerendered_inputs）

## M11 — 专业输出

- [x] PNG/SVG/PDF 参数化：纸张/方向/DPI/背景（page.background）/字体（label font）/图例/比例尺/extent（layout spec + composer set_paper；页边距以组件坐标承担）
- [x] 无头生产导出走探测 + 记录 renderer（providers/builtin/map_export.py；tests/test_export_parity.py::test_provider_prefers_probe_and_records_renderer）
- [x] 降级写导出报告/产物元数据（render_and_save_map_export 返回 engine/degraded/reason；tests/test_export_parity.py::test_fallback_export_reports_itself）
- [x] screen/export 引擎一致性契约（canvas QGIS→export QGIS；fallback 显式；tests/test_export_parity.py）
- [x] SVG/PDF/PNG 内容验证（%PDF 头、svg 文本/尺寸、PNG 魔数、中文标题进 spec；tests/test_qgis_layout_export.py::test_qgis_layout_export_svg_and_png）
- [x] GeoPDF：能力实测失败（PrintError=4），D10 记录明确理由 + opt-in 失败显式契约（tests/test_export_parity.py::test_geopdf_capability_is_explicit_never_fake）

## M12 — 成图 QA

- [x] QA 规则扩展 10 条（workflow/map_qa_rules.py EXTENDED_QC_RULES + run_map_qc 生产接线 review_export_page；tests/test_map_qa_rules.py 12 项）
- [x] QA 结果可定位（issue 携带 ref/feature_id/geometry；tests/test_map_qa_rules.py::test_out_of_bound_feature_locates_geometry）
- [x] 合成页 QA：composition_incomplete（主图/图例/比例尺缺失检出；tests/test_map_qa_rules.py::test_composition_qa_missing_core_furniture）

## 交付与流程

- [ ] 分层本地验证：pure geometry → factor pipeline → MapDocument → QGIS bridge → composite → export → save/reopen → adversarial → visual QA
- [ ] 三轮独立 review（Correctness / Architecture / UX-Performance-Adversarial）完成并修复
- [ ] 原子 commits（按 milestone）
- [ ] PR 到 main：背景/架构变化/功能/测试证据/性能证据/兼容性/风险/未做事项
- [ ] 不运行 100GB seismic benchmark
- [ ] vendored QGIS 零重编（复用 main vendor build）

## 硬约束

- QGIS 是 2D authoring 权威；fallback 只做测试/headless/minimal，不新增专业制图特性
- Map style 不反向篡改科学栅格值
- 不建立第二套 Catalog/图层权威/工程文件格式/run graph
- MapDocument 与 QGIS layer tree 不双权威（Python 权威 + 树语义回写不变）
- 编译并发 ≤2；pytest 无界 xdist 禁用；QGIS 重型测试串行/小批
