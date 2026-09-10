# 07 — 渲染与样式（V10）

## 1. 样式回读验证（D12）

`qgis_mirror._verify_published_style`（qgis_mirror.py:376）在样式发布
后做**回读比对**：桥 `style_readback` flag 提供 `mirror_style_json`
读回通道，宿主比对**语义签名**：

- renderer type；
- symbol count；
- categorized 渲染的分类字段（categorized field）。

**拒绝字节比对**：QGIS XML 归一化噪声（属性顺序/空白/默认属性展开）
使同语义样式产生不同字节流——字节比对会把每个 no-op 发布都误判为
漂移。语义签名三元组是「视觉可辨」的最小刻画，签名不符才触发重发。

## 2. scale-range 通道（D13）

`upsert_mirror_layer` 新增 `min_scale` / `max_scale` 参数（桥
`layer_scale_range` flag；宿主能力探测 `_stack_supports_scale_range`，
qgis_mirror.py:298）：

- **0 = unbounded**（QGIS 惯例，非零即界）。
- 应用面：**新建与复用镜像都应用**（qgis_mirror.py:673–674 的
  scale_token 传递路径）——复用镜像不再跳过可见域更新。
- 账本配套：`MapLayer.scale_range` token 入发布账本
  （qgis_mirror.py:160 注释锚点；04-layer-registry.md §2）——
  可见域变化 = 一次重发布，不靠全量 reset。

关闭 00-baseline.md §B.10（原生画布无 scale-range 通道）。栅格镜像
**无**此通道（vector only）——12-known-limitations.md 第 7 条。

## 3. 与 ToolContext scale 事实的关系

V9 已把 `scale_denominator` 读入 ToolContext（读面）；
V10 的 min/max_scale 是**写面**（图层可见域）。两者经同一画布 scale
真值闭环：可见域外的层在工具面上按既有 availability 逻辑评估
（读 `scale_denominator`），渲染侧由 QGIS scale-range 决定是否绘制
——宿主不平行复算可见性。

## 4. Fallback QPainter backend：冻结

fallback 双视觉栈是 V8 起的 documented gate
（docs/development/qgis-geological-authoring-v9/00-baseline.md §C2
「保留」项）。V10 沿此决策谱系**冻结不扩张**：本文件的样式回读与
scale-range 都是原生（桥）路径能力；fallback 路径维持既有呈现，
不新增语义面。
