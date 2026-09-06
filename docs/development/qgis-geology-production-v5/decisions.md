# Decisions — QGIS 地质编图生产线 v5

编号 D1…；重大项另立仓库级 ADR（接续 docs/adr/）。每条含裁决 + 理由 + Avoid。

## D1 — 成图排版：组件图保持领域权威，QgsLayout 作为导出时瞬态渲染器

裁决：不把 `MapCompositionDocument`/`CompositionEditSession` 迁移为 QgsLayout 可写文档。桥新增窄接口 `compose_export(spec_json, path, ...)`：Python 把组件图序列化为纯 JSON spec → C++ 在导出瞬间构建 `QgsPrintLayout`（QgsLayoutItemMap/Legend/ScaleBar/Picture/Label/Grid）→ 输出 PDF/SVG → QgsLayout 随即丢弃。屏幕编图继续用现有画布 + 组件面板。

理由：M6 要求"模板 = component graph + defaults"，现有 composer 已有 21 组件 + undo/redo + 模板 + schema v2 序列化，是成熟领域模型；QgsLayout 文档自身可写、事件模型复杂，若作为第二持久权威必然与组件图漂移（M0 审计确认的 style drift 风险的放大版）。导出时瞬态构造让 QGIS 原生 legend/scalebar/north arrow/grid 渲染能力（M7）全部生效，同时保持单一组件权威。ADR 0059"QGIS 为专业 authoring 核心"通过渲染路径满足，不通过"QgsLayout 当文档"满足。

_Avoid_: 双文档（组件图 + QgsLayout 各自可写）；把 QgsLayout XML 存进工程文件当第二格式。

## D2 — 无头生产导出必须走探测权威，fallback 显式化

裁决：`providers/builtin/map_export.py` 移除硬编码 `prefer_native_renderer=False`，改用 `create_map_render_backend()` 的标准探测；`ui/map_export_worker.py` 的 QGIS→painter 降级必须写入导出结果元数据（`renderer: "fallback"`），UI/产物可查。

理由：M0 审计确认 catalog OUTPUT 正式产品图由 painter fallback 生成是 fallback-as-production 事实，直接违反 ADR 0057/0059。降级可以存在（无桥环境是合法状态），但必须可见、可追溯。

_Avoid_: 静默降级；用环境变量全局压低桥。

## D3 — 精度评估层放在 paleo_workbench，不改 geo-viz submodule

裁决：RMSE/MAE/bias/residual/统一 CV 实现为 `paleo_workbench/workflow/interpolation_evaluation.py`（新层），通过既有引擎入口（geoviz `interpolate_factor_grid` / `leave_one_out_predictions` / constrained adapter）做 holdout 评估；不修改 geo-viz-engine submodule。

理由：geo-viz-engine 是独立 submodule，改动需跨仓 PR 且影响其他方向；评估层本质是"多次调用插值引擎 + 统计"，在 workbench 层组合即可，天然支持所有方法（含 vendored 约束 IDW）。克里金闭式 LOO 已存在于 geoviz，直接消费。

_Avoid_: 为评估改引擎签名；在评估层重新实现第三套插值。

## D4 — IDW 双轨收敛：任务管线 geoviz IDW 为插值权威，kNN 版降级为 pipeline 内部近邻工具

裁决：`METHOD_LABEL_TO_ENGINE` 主路径（全样本 + 断层遮挡）是"反距离加权插值"的唯一权威语义；`geological_pipeline/interpolator.py` 的 kNN IDW 保留为 geological_pipeline 内部快速路径，但其结果对象必须标注 `variant: "knn"`，不再与方法标签"反距离加权"混称。文档记录差异。

理由：两套语义不同但对外同标签，是 M0 审计的双轨漂移点。全面合并风险大（下游测试锁定两种行为），显式标注 + 权威声明以最低风险消除歧义。

_Avoid_: 静默换核；删除 kNN 实现（下游 geological_pipeline 依赖）。

## D5 — CRS 契约：未声明 ≠ EPSG:4326

裁决：`contouring.py`/`polygonization.py` 删除 crs=None → "EPSG:4326" 静默回退，改为携带 None（未声明）并在 QA 规则 `crs_mismatch/undeclared_crs` 中可见；插值层对 geographic CRS（lat/lon 度单位）输入执行显式策略：默认拒绝需距离的计算并提示投影，或显式 `distance_policy="planar_degrees"` 豁免（结果标注）。

理由：FactorGridResult 契约（"None=未声明，禁止猜测"）是既有权威，下游静默回退是对权威的破坏；lat/lon 等距平面假设在小范围制图常见但必须可见。

_Avoid_: 全局默认投影（用户数据语义不明）；把度当米。

## D6 — mask/boundary 全链单对象传递

裁决：`bounds/mask/boundary/exclusion` 在 FactorMapSpec 中为单一声明，由 pipeline 解析为同一 mask 载荷传给 interpolation → contour → polygon → 融合；各阶段不得自行重算凸包兜底（约束 IDW 引擎内部凸包 fallback 仅在用户未给边界时生效并标注）。

理由：M3 要求 mask 全链一致；多处独立解析是 drift 源。

_Avoid_: 每层各自裁剪；凸包静默替代用户边界。

## D7 — 融合框架可解释优先

裁决：多因素融合（M5）仅支持 weighted evidence + rule-based（threshold/table），每条权重/规则必须可序列化溯源；不确定性传播限于线性化近似（加权方差、最小置信度）；不做 ML 黑箱。sensitivity comparison 通过权重扰动重跑实现。

理由：Goal 明令禁止黑箱 ML 冒充地质专家判断；`prediction/` 的 ONNX 路径与融合无耦合，保持隔离。

_Avoid_: 神经网络融合；不可解释的权重自动寻优默认开启。

## D8 — 桥扩展零 ABI 重编 vendored QGIS

裁决：全 Goal 复用 `main` worktree 的 qgis-vendor build（PALEO_QGIS_REUSE_VENDOR=1 + PALEO_QGIS_BUILD_DIR），只编译桥扩展本体（7 个 cpp，-j2）；不修改 vendored QGIS 源。先修 setup.py NameError 前置缺陷。

理由：构建预算硬规则；vendor 与本分支 third_party/qgis commit 一致（UPSTREAM.md SHA 校验）。桥扩展若需新 C++ API（D1 layout 导出），只改桥源码，不改 QGIS。

_Avoid_: 任何触碰 vendored QGIS 源的行为；跨 worktree 重编。

## D9 — 测试与并发纪律

裁决：pytest 用 run_env.sh（offscreen + 软件 GL），qgis-marked 测试串行小批；无 `xdist -n auto`；C++ 增量编译 -j2；每 milestone 一轮 targeted tests → package/integration → 最后必要的 regression。

_Avoid_: 全量回归先行；并行重型构建。

## D10 — GeoPDF 策略（占位，M11 时裁决）

裁决：M11 期间实测 QGIS 4.2 QgsLayoutExporter GeoPDF 能力 + 本地 PDF 校验工具可用性；可靠则纳入 `pdf_geo` 输出选项，否则在 verification.md 记录证据并仅在文档中标注"未启用 GeoPDF"。不伪造支持。

## D11 — 派生因子溯源标记

裁决：`extract_factors` 的砂地比/厚度派生保留（显式请求键缺失时触发），但派生行/数据集必须携带 `derived_from`（源列 + 公式）标记，QC 报告可见；MapProduct assemble 的 scientific_fingerprint 纳入派生标记。

理由：#1151 废除的是"跨列静默填充"，显式派生是合法地质操作；缺的是可追踪性，不是禁止派生。

_Avoid_: 派生值冒充实测；指纹忽略派生来源。
