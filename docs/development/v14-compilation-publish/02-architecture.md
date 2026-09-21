# 02 — Architecture & Decisions（V14-COMPILATION-PUBLISH）

## 总体数据流（本线闭环后）

```text
Frozen inputs (prediction/constraints/factor products/manual interpretation)
   │ workflow_interpretation::CompilationInputSet（create→resolve→freeze→persist active）
   ▼
run_integrated_fusion（closure_workflow；grid seams 生产实现 ← catalog adapter + project live）
   │ 融合产物 catalog 登记 + integrated_interpretations 记录（latest_fusion_version_id 写者）
   ▼
assemble_map_product / assembly_from_workspace（payload=build_product_manifest 序列化）
   ▼ product_qa → review → freeze → publish（门禁不变）
MapProduct record（project["map_products"]，catalog OUTPUT 版本 + run lineage）
   ▼
Composition（模板物化 composer_templates → CompositionEditSession 人工整饰）
   │ 预览：composer_renderer（MapContentSeams ← MapSession 真实渲染）
   │ 导出：export 编排（QGIS layout 优先 → composer 引擎诚实回退）
   ▼
ExportArtifact 登记（sha256 + record_export → project export ledger + provenance sink）
```

## 新增/改动组件与 ownership

| 组件 | 位置 | 职责 | 状态 |
|---|---|---|---|
| composer_templates | `libs/mapping_document`（新文件） | 9 模板声明式库 + `instantiate_template`（经 CompositionFactory，新 uuid，metadata.template_id/category，title 覆写） | 新增 |
| composer_renderer | `libs/mapping_document`（新文件） | `render_to_svg(Composition, RenderSeams) -> string`：24 元素类型全量 + dict-layer 矢量路径 + 占位诚实面 | 新增 |
| composer_export | `libs/mapping_document`（新文件） | SVG 物理尺寸写出（原子）+ 分派；PNG/PDF 经注入的 replay seam（Qt 端实现于 ui_seqviz_qt） | 新增 |
| export 编排 | install 适配层 | budget → QGIS `export_composition_reported`（executor=CompositionLayoutService）→ 失败/hybrid → composer 引擎；engine 标签诚实 | 新增 |
| grid seams | `libs/closure_workflow`（新文件 grid_seams） | `decode_grid_artifact`（encode 的逆）+ `grid_for_task` 生产解析（live cache→npz→inline） | 新增 |
| catalog 适配器 | `apps/paleo_workbench_platform`（新文件） | `workflow_runtime::CatalogRepository` over 深核 CatalogClosureAdapter | 新增 |
| compilation service | `apps/paleo_workbench_platform/closure_compilation_install` | 输入集/fusion/assemble/review/freeze/publish 动作面 + shelf 按钮接线 + factor reference descriptor 服务 | 新增 |
| provenance sinks | `libs/closure_review` + install | QcProvenanceSink/VersionFinalizeSink 生产实现（catalog-backed）→ provenance_registered=true 真路径 | 新增 |
| cartographic QA | `libs/closure_review/src/cartographic_rules`（新） | cartographic_qa.py 15 规则移植，挂 review_qc_core 的 cartographic_side_checks 委托 | 新增 |
| 面板接线 | closure_mapping_install 具名块 | template_library/instantiate/render_svg/export_fn/record_export/main_map_bind 注入；默认模板开档；信号消费 | 改动 |

## 关键决策（ADR）

**D-V14-01 renderer 落位与活内容 seam。** `composer_renderer` 是 Qt-free 纯函数内核（进 `mapping_document`，与文档模型同库）。Python renderer 的三条主图取数路径中，route 1/2（活 `MapDocument`/`MapLayer` 对象）不可能进 Json——C++ 以 `MapContentSeams` 承接：host 注入 (a) `frame_content(elem)`：栅格（PNG base64 + extent，来自 MapSession 真实渲染）或矢量片段（mm 空间）；(b) `legend_entries(elem)`：活图层的图例条目（顺序=canonical top-first）；(c) `palette_stops(name)`：色带名→stops。seam 缺席 = 诚实占位/缺省（与 Python 无绑定分支同形）。route 3（dict layers，纯 JSON）在内核忠实移植（矢量要素渲染子集，见 D-V14-05）。**不移植 renderers.py 全部 8 个渲染器**——主产品路径的"真实地图渲染"由 QGIS MapSession 提供（栅格内嵌），dict-layer 矢量路径只服务 JSON 组图文档的离线/测试/兼容渲染。

**D-V14-02 确定性 ID。** Python `abs(hash(...)) % 100000`（cbar/grad/lith pattern id）进程随机，不可冻结。C++ 用 FNV-1a(id) % N 的确定性方案；oracle 生成器将 id 占位符归一化（`cbar_\d+`→`cbar_H` 等）后冻结，C++ 侧另断言 id 跨运行稳定。属文档化有意分歧。

**D-V14-03 修订 layout_export D-03。** 原决策"无 composer SVG 回退引擎，fail-closed"。本线建立了**原生 C++ composer 渲染引擎**（无 Python），故导出编排修订为：QGIS layout 执行器优先（final 高保真路径）；执行器缺席/失败/含 hybrid 元素时回退 composer 引擎（SVG 直写 + Qt replay PNG/PDF），engine 标签如实（`qgis_layout` / `composer_svg`），warnings 透传。fail-closed 语义保留：unsupported 格式仍明确拒绝，绝不伪造文件。`layout_export` 内核不改（编排差异在宿主适配层），其 oracle 不受影响。

**D-V14-04 依赖方向与样式/色带子集。** `cartography` 依赖 `mapping_document`（geological 模板产出 Composition），故 renderer 不能反向依赖 cartography（环）。dict-layer 路径所需的样式解析（fill/stroke/stroke_width/marker/marker_size/line_pattern/categories/labels 只读子集）在 renderer 内部实现为 `style_view`，默认值与 `map_styles.py` 逐字对齐（cartography 的 VectorStyle 仍是 to_dict/from_dict 权威；本子集是只读消费面，登记于 08）。`palette_stops` 经 seam 由 host 绑 cartography color_ramps（含 jet/water_depth 别名目标）；seam 缺席时落文档化 2-stop 缺省。

**D-V14-05 导出编排次序。** `check_pixel_budget`（caller error）→ QGIS spec 路径（hybrid 边界照旧 itemized）→ 可执行则出 `qgis_layout` 报告 → 否则 composer 引擎出 `composer_svg` 报告（hybrid 元素被真实渲染，不再必败）。两条路径共享同一 `Composition` 与同一 `build_layout_spec` 几何（element mm 几何单源），spec parity 由 `screen_export_parity` + 结构断言测试守护。

**D-V14-06 catalog 桥。** 平台新增 `WorkflowCatalogRepository : workflow_runtime::CatalogRepository`，包住深核 `CatalogClosureAdapter`（register_run/register_result_asset/register_version/update_run_status/promote_version/set_current 等已具备）。closure_workflow 全部目录面经此适配器；不建第二目录、不绕过深核事务纪律（回滚语义由深核承担）。失败语义：适配器抛异常→closure_workflow 按既有 catch 路径诚实降级（registered=false + reason）。

**D-V14-07 provenance 收口。** `QcProvenanceSink`/`VersionFinalizeSink`（workflow_runtime 已有 seam）获得 catalog-backed 生产实现并注入 closure_review install；`provenance_registered` 只在登记成功时为 true（失败仍 false + 原因，不虚报）。QC report 的 `catalog_version_id` 在登记成功后回填真实版本 id。

**D-V14-08 ExportArtifact。** 组图导出成功后：sha256 + bytes + format/dpi/engine + product/revision 关联，经 (a) project export ledger（document 段，Python `project/artifacts.py record_export` 对应面）与 (b) `record_export` seam 注入面板。无 catalog 时 ledger 仍写 project（降级诚实标注 registered=false）。

**D-V14-09 模板库语义。** 内核数据 = Python `TEMPLATE_LIBRARY` 9 模板逐字段冻结（含 style/data bindings 声明）。`instantiate_template` 与 Python 逐行为对齐（z 排序物化、metadata、title 覆写、未知 id → Python KeyError 语义 invalid_argument）。面板安装时以首个模板开档（Python `composition_panel.__init__` 行为），"模板新建"菜单全活。不引入第二套模板系统（cartography/geological 模板保持其独立职责：直接产出带内容的 factor-map 文档）。

**D-V14-10 融合/编图动作边界。** 本线提供 fusion/assemble/lifecycle 动作与 `latest_fusion_version_id` 写者（integrated_interpretations 记录，`create_integrated_interpretation` 内核已有）。`compile_map_draft/production`（PaleoMapDocument 编图管线）是 #1436 租约：本线在 install 层以 optional seam 声明该能力，main 无该符号时不出现对应菜单项（诚实缺位，不复制实现）。

## 失败语义（统一）

- 每个导出：失败清理部分文件（executor 契约）；成功回读校验（size>0 / SVG parse / PNG magic）。
- unsupported 格式：明确 ValueError 语义（异常/报告 ok=false），不生成文件。
- 输入集 freeze 拒绝：原子回滚（内核既有）；UI 呈现原因。
- publish 门禁失败：记录保持不变（绝不半状态）；`publish` 成功才写 published + export_path。
- 融合 seam nullopt = 拒绝，绝不静默替换输入。

## 线程/异步模型

- 预览渲染：GUI 线程同步（单页 SVG，量级小；与 Python 面板一致）。地图栅格内容由 host 缓存的最近渲染帧提供（不阻塞）。
- 导出：经 `WorkerHost` 后台线程（closure_mapping 既有模式），完成经 QueuedConnection 回 GUI；协作取消沿用 map_export_worker 模式（3 检查点）。
- fusion/assemble：WorkflowScheduler（closure_workflow 既有，单队列+取消令牌）——本线首次将其接入 app。

## 规模预算（性能目标，见 06）

预览 SVG 生成 ≤50ms（50 元素）；图例 100 条目 ≤5ms（线性）；模板物化 ≤1ms；批量导出 10 图不重建 QGIS project（executor 复用 spec 构建）；save/reopen 保真零丢失（结构断言）。

## 与其他四线边界

- Prompt1（catalog/lineage）：经深核 API/适配器，不直写库。
- Prompt2（shell）：descriptor/widget 供给，不布局。
- Prompt3（layer order）：只读 `layerIdsTopFirst`（canonical）；#1437 合并后自动受益，无硬依赖。
- Prompt4（factor compute）：只消费 frozen factor products/catalog 版本。
