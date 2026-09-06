# Target State — QGIS 地质编图生产线 v5

格式约定：每项完成时勾选 `[x]`，并在括号内注明验证测试/证据文件。Goal 结束前不得留下伪完成项。

## M0 — 审计与规划

- [x] 三路源码审计完成（科学链/制图层/构建环境），结论落在 baseline.md
- [x] baseline/target-state/decisions/verification 四件套建立
- [ ] 前置缺陷修复：setup.py `resource_database` NameError（native/qgis_render_bridge/setup.py:156,:229）（tests: 构建日志 + 桥 import 成功）

## M1 — 单因素图统一产品模型

- [ ] `FactorMapSpec` 显式输入契约：factor identity/unit/源版本/target horizon/bounds+mask/faults/method/parameters，可序列化、可指纹
- [ ] `FactorMapResult`（或等价扩展 FactorGridResult）显式输出：grid/uncertainty/contour/classified zones/QC/provenance/map layers
- [ ] 主管线（workflow/factor_interpolation.py）unit 贯通：FactorGridResult.unit 不再为 None（当因子有已知 unit）（tests/test_factor_interpolation*.py 扩展）
- [ ] 派生因子（砂地比/厚度）带 derived 溯源标记（provenance 字段记录 derivation rule），不再无标记混入
- [ ] 禁止 `z → Rs → Ht` 隐式 fallback 保持废除（回归测试存在且通过）
- [ ] 覆盖因子族抽查：sandstone thickness / formation thickness / sand ratio / porosity / probability / paleo-water-depth（FACTOR_DEFAULTS 契约测试）

## M2 — 插值工作站 V2

- [ ] 统一精度评估层：LOO/k-fold CV 对 IDW/constrained IDW/kriging/spline/directional trend 产出 RMSE/MAE/bias/R²（tests/test_interpolation_evaluation.py）
- [ ] residual map（站点残差向量/残差点层）可生成并挂入 MapDocument
- [ ] 克里金诊断整合：empirical variogram + model params + variance min/max + fit 诊断可从一次运行导出（tests/test_kriging_diagnostics.py）
- [ ] IDW 语义收敛决策落地（文档化 D 决策 + 单一权威路径或显式参数化差异），不再静默双轨
- [ ] CV 计算与显示分离（评估结果是数据对象，渲染是图层的事）
- [ ] 不确定性可视化：variance/uncertainty 图层可挂入 MapDocument（kriging 方差 + IDW 距离代理）

## M3 — Boundary / CRS / Unit 科学正确性

- [ ] 消除 contouring.py / polygonization.py 的静默 EPSG:4326 回退：CRS 未声明时图层显式携带"未声明"状态而非猜测值（tests/test_mapping_crs_*）
- [ ] 插值距离策略显式化：声明等距平面假设 + 文档化 lat/lon 输入的投影前置要求；geographic CRS 输入给出显式警告/拒绝策略（tests/test_interpolation_distance_policy.py）
- [ ] unit 显式贯通 extract → interpolate → grid → contour 标注 → legend
- [ ] mask/boundary 在 interpolation + contour + polygon 全链一致（同一 mask 对象传递，tests/test_mask_chain_consistency.py）
- [ ] 0 坐标不丢失回归保持（_first_present 语义测试已有 → 保持通过）

## M4 — 等值线 / 分区 / 相带质量

- [ ] 小多边形处理参数化（min_area 阈值，删除计数进 QC，绝不静默删科学结果）（tests/test_polygon_quality.py）
- [ ] 用户域/边界多边形 clip 贯穿 contour + polygon 输出
- [ ] 孔洞归属确定性（共享边/包含关系判定，消灭"塞给第一个"兜底）
- [ ] adversarial 套件：NaN holes / coincident wells / zero area / narrow corridor / nested rings / self-intersection / boundary edge / sparse points（tests/test_contour_polygon_adversarial.py）
- [ ] invalid geometry repair 在 polygon 输出前强制（topology.repair_invalid_geometry 复用）

## M5 — 多因素融合框架

- [ ] `FusionModel` 数据契约：factors + normalize/evidence transform + rules/weights + thresholds，可序列化、每条 weight/rule 有 provenance（tests/test_factor_fusion.py）
- [ ] weighted evidence 融合：归一化 → 加权 → likelihood 网格（FactorGridResult 同构输出）
- [ ] rule-based classification：threshold/table 规则 → facies class（可解释，非 ML 黑箱）
- [ ] 不确定性传播：evidence 不确定性（方差/会员度）合理范围内的 summary（如加权方差/最小置信度）
- [ ] factor enable/disable + sensitivity comparison（权重扰动对比报告）
- [ ] 融合结果 → polygon → MapProduct 链路：融合 facies 图层挂入 MapDocument 且可装配成 MapProduct
- [ ] 融合输出 provenance 注册进 catalog（DataRun）

## M6 — Map Component Graph（扩展现有 composer）

- [ ] 组件清单核对补齐：MainMap/InsetMap/Title/Subtitle/Legend/ColorRamp/ScaleBar/NorthArrow/CoordinateGrid/TextAnnotation/GeologicalSymbol/WellLegend/Histogram/Profile placeholder/Metadata/Neatline（models.py ElementType 对照，缺则补）
- [ ] 每组件 serializable + editable + bounds/anchor + style + visibility + z-order（CompositionEditSession 统一入口回归）
- [ ] 模板 = component graph + defaults（bind_template 数据绑定回归），非死截图
- [ ] Profile/Section placeholder：无真实数据不渲染内容（占位符契约测试）

## M7 — QGIS 原生组件映射

- [ ] 桥新增窄接口：QgsLayout 组装导出（component graph JSON → QgsLayoutItemMap/Legend/ScaleBar/Picture/Label/Grid → PDF/SVG），布局为导出时瞬态构造、不成为第二可写权威（tests/test_qgis_layout_export.py，pytest.mark.qgis）
- [ ] MAIN_MAP 成图内容走 QGIS 渲染路径（桥可用时），QGIS renderer XML 符号不再降义
- [ ] 色带映射：标量栅格层在 QGIS 路径暴露 QgsColorRamp 等价能力（至少 singleband pseudocolor 或等价 renderer），fallback 保持现状（tests/qgis）
- [ ] vendored QGIS 复用构建成功（PALEO_QGIS_REUSE_VENDOR=1，-j2，零重编 QGIS）
- [ ] 桥 API 无 Python domain 泄漏（payload 为 JSON/XML 字符串）

## M8 — 图层管理 / 编辑 / 属性闭环

- [ ] 图层操作矩阵回归：create/import/visibility/opacity/reorder/group/rename/duplicate/zoom（现有 tree_sync/mirror 测试保持 + 补 group/duplicate 若缺）
- [ ] 属性表补齐：过滤（field-based filter/sort）+ 选择双向同步保持（tests/test_map_attribute_table.py）
- [ ] 编辑闭环回归：edit mode/snapping/split/merge/topology/repair 现有测试全绿
- [ ] QGIS tree selection/reorder 无 active-layer echo、编辑工具不掉回 pan（现有 SuppressGuard 测试保持通过）

## M9 — Geological Style Library

- [ ] 地质样式库：well symbols/facies fills/contour/fault/horizon/uncertainty/boundary/reference/annotation 分类样式集（JSON，可版本化）（tests/test_geological_style_library.py）
- [ ] categorized/graduated/continuous ramp/line pattern/marker/transparency/legend label 全支持（映射到现有 VectorStyle + QGIS renderer spec）
- [ ] 样式与科学 class/field 绑定可追踪（style 记录 field/class source）（round-trip 测试）

## M10 — MapProduct Lifecycle V2

- [ ] clone：产品级克隆（新 id、引用同版本集、可独立演进）（tests/test_map_product_lifecycle.py）
- [ ] rerun：按产品配方重跑 → 新 catalog 版本 + lineage（复用 workflow/dag 与 recompute_plan，不复制第二套 run graph）
- [ ] compare：input versions/parameters/factor methods/map layers/style/layout/QC/output hashes 逐项 diff 报告（tests/test_map_product_compare.py）
- [ ] promote/supersede/freeze/publish 产品级门面（背后走 catalog promote + versioning.finalize，不绕权威）
- [ ] stale detection 接入产品描述（describe 报告 stale 因素）

## M11 — 专业输出

- [ ] PNG/SVG/PDF 页面参数化：page size/orientation/DPI/vector-raster policy/background/fonts/margins/metadata/legend/scale/extent（composer/export.py + 布局导出扩展）
- [ ] 无头生产导出修复：providers/builtin/map_export.py 不再硬编码 fallback；QGIS 可用即走 QGIS，结果记录实际 renderer（tests/test_map_export_provider.py）
- [ ] QGIS 失败降级显式化：ui/map_export_worker.py 降级必须出现在导出结果元数据（不再仅 log）
- [ ] screen vs export parity：关键语义（renderer/symbol class/label visibility/extent）一致性测试（tests/test_export_parity.py）
- [ ] SVG/PDF 几何与文本验证：非空矢量内容、文本存在、图例存在、透明度保留、clip 生效、高 DPI、中文字体渲染（offscreen）
- [ ] GeoPDF：验证环境能力，能则纳入，不能则在 decisions.md 记录明确理由（不伪造）

## M12 — 成图 QA

- [ ] QA 规则扩展：missing horizon/factor、invalid geometry、no wells、CRS mismatch、legend completeness、class/renderer mismatch、low confidence/uncertainty、out-of-bound feature、stale inputs、broken external reference、export validation（workflow/qc.py 扩展 + tests/test_map_qa_rules.py）
- [ ] QA 结果定位到 layer/object（issue 带 layer_id/feature_id/element_id）
- [ ] 合成页（composer）QA：元素绑定失效、图例项与图层不符可检出

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
