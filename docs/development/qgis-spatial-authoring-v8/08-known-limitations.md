# 08 — Known limitations

PR 时的诚实边界（编号续 V7 惯例）。

1. **标量栅格（osgeo）路径在本 worktree 默认配方下跳过**：osgeo python
   绑定与其 gdal DLL 必须同源，而默认配方（authoring 自包含 vendor +
   PySide6 Qt）里 gdal 来自 vendor——同 DLL 名双源冲突在 Windows loader
   下无解。conda-Qt 配方（`PALEO_QGIS_CONDA_QT=1`，cartography 系）或
   CI qgis 腿覆盖该路径。这是运行时配方约束，不是产品缺陷（03-decisions
   D6 记录了两配方并存的工程事实）。
2. **C++ 侧行指示器呈现常量（glyph/中文 tooltip/色板 hex）**与
   tokens.py 无单一真源绑定——kinds 词汇 host 权威、未知 kind 跳过的
   M10 边界成立，但视觉常量可能随设计系统改版漂移（观察项；面板 parity
   测试为后续加固面）。
3. **merge/split 门面兜底的空几何守卫**依赖类型过滤 + 输入侧
   VectorFeature 验证；极端退化输入（union 收敛为空 Polygon）理论上
   可产生空要素替换（review-1 P2-11，观察项）。
4. **`Range` 编辑器 config 的 `Step=1.0`** 是桥端补的 wire 未声明默认
   （数值语义不受影响——Range 只约束 Min/Max）；spec wire 增加 step
   字段为后续。
5. **复合撤销组持有会话强引用**直至 COMPOUND_LIMIT（256）驱逐或会话
   终结收口（discard_ended_session_compounds）；极端长会话 + 无终结
   路径调用的宿主理论上可积累快照引用（当前两宿主均已收口）。
6. **geoviz 原生扩展腿**（layer_model_core/grid_render_core 等）在本
   worktree 未编译——相关存量测试为环境性失败（与主线一致，CI 覆盖；
   已用改动前后对照验证非本 goal 回归）。
7. **#951 的完整修复**：W6 消除了 qgis_stack 侧已识别的 stale-QTimer
   投递面（singleShot 带 context + RuntimeError 守卫 + 竞态测试），
   但 #1230 指向的 3.13 腿崩溃全貌（含其它模块的同类模式）需要独立
   修复单（本 goal 仅产品侧 + 所有权面；CI 部分明确排除）。
8. **100GB seismic**：硬排除，未新增任何支持/基准/优化（PR body 复述）。
