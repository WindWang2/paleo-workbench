# 08 — Known Limitations（V14-COMPILATION-PUBLISH）

诚实登记：未交付、降级、以及有意识的简化。每条给出依据与后续方向。

## 跨线依赖（本线不可单独关闭）

1. **`compile_map_draft/production` 编图菜单未接线**。#1436（open PR）持有 `libs/closure_workflow/map_compile.*` 租约（draft+production 编图管线 + payload parity）。本线不复制实现；合入后经 install 的 optional seam 接线（seam 形态见 03 §5）。当前面板模板/预览/导出闭环不依赖它。
2. **深核 catalog 适配器缺失**。`workflow_runtime::CatalogRepository` over `CatalogClosureAdapter`（register_result_asset 的 managed dedup/bridge/external-link 深层）被 #1436 明确声明为独立子史诗。当前生产登记面 = workflow provenance rail（`FileCatalogRepository`，cpp-close-02 建立的生产 CatalogRepository）；深核桥接后替换，seam 不变。
3. **Stage3 factor reference 卡片内容模型（§13）未实现**。需要 Prompt2 的卡片 shell 与 Prompt4 的 factor 数据面；本线只消费 frozen products 的契约已定义（03 §6）。
4. **编图→发布 UI 动作面未接线**。`MapProduct` 生命周期阶梯（draft→reviewed→frozen→published→superseded）在 main 已有库级实现与 oracle；`map_product_requested` 信号仍悬空、review/freeze/publish 无 C++ 菜单入口（Python 侧同样只有 harness 动作）。接线需要 UI 外壳决策（Prompt2 范围）。
5. **cartographic QA 15 规则未移植**（`mapping/cartographic_qa.py`）。`CartographicQaDelegate` seam 已存在，默认几何委托真实（未闭合环/重复顶点/退化面）；全量规则移植超出本线预算。后果：`unpublished_data_in_export`（maturity ≥ REVIEWED 导出下限）等规则缺失 → 相关检查如实 skipped。

## 本线范围内的诚实降级

6. **组图导出的地图帧是栅格**（画布帧 base64 PNG）。矢量高保真路径 = QGIS layout 执行器（install seam），需要平台注入活 MapSession（当前未注入 → 编排走 composer 引擎，engine 标签如实为 `composer_svg`）。
7. **预览/导出的图例是扁平近似**：每个可见图层一条 entry（顺序 = 画布快照顺序 = canonical layer order）。Python 的 `legend_items(lyr)` 对 categorized 层每类一条、对 grid 层产 gradient 条目。丰富化需要层渲染器的图例面（跨线）。
8. **`py_splitlines` 只处理 `\n \r \v \f \r\n`**（Python 还切 `\x1c \x1d \x1e \x85 \u2028 \u2029`）。地图文本出现概率低。
9. **histogram 的 values 不接受数值字符串**（Python `float(value)` 接受 `"1.5"`）。C++ 只接受 JSON number（`_floats`/`histogram_data`）。bins 的截断语义已对齐。
10. **帧缓存**（install，TTL 300ms）：函数局部静态 map 按裸指针键控、无清理（多窗口场景地址复用有串味风险）；当前仅 GUI 线程调用。修复方向：`QPointer` + `ClosureContext` 生命周期收殓。
11. **QC provenance rail 每次注册全量重写 store**（`persistent_catalog` 既有设计）；验收环反复 QC 时 store 线性膨胀。批量提交/摘要化是后续优化。
12. **组图导出为同步路径**：无取消点、无进度。`export_to` 已是 headless 入口，迁入 WorkerHost 成本低但未做（画布导出的取消检查点由 `map_export_worker` 提供，非本路径）。
13. **`check_pixel_budget` 的 NaN/负 dpi 防护在编排层**（install），内核 `export_composition_page` 自身不设防（composer/export.py 也没有预算概念——parity 选择）。

## 文档化的有意分歧（Python → C++）

| 分歧 | 理由 |
|---|---|
| SVG 梯度/pattern id 用 FNV-1a 确定性哈希（Python `hash()` 进程随机） | 可冻结、可缓存；oracle 归一化后比对 |
| 未知元素字段/顶层键保存在 `extras` 并回写（CONV-02 D-08 既有） | 前向兼容 |
| dict-layer 的 `grid/scalar_grid/contour` 图层类型拒绝渲染 | Python 的 Grid/ContourRenderer 需要 VectorMapLayer 不携带的网格数据（Python 那两支同样空转/抛错） |
| 颜色/样式属性不转义（与 Python 一致） | 文本节点全部转义；样式属性透传是 Python 行为，文档须可信 |

## 验证边界

- 本机 Linux only；Windows/macOS 未验证。
- ASan/UBSan 未运行（资源与时间约束；建议 CI 补）。
- 真机 QGIS 执行器路径的端到端导出未在平台测试中注入（需要活 MapSession）；`platform.composition_export`（既有）覆盖 QGIS 链本身。
