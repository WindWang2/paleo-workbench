# 08 — Performance（V10）

## A. 预算（矢量 authoring 规模）

- 1k / 10k / 100k features 单层；数百层；大顶点数多边形；高频 mouse move；
  顶点拖动；snapping；拓扑；增量镜像；undo 栈。

## B. 既有守卫（V7–V9，勿退化）

| 守卫 | 内容 |
|---|---|
| `test_map_tool_operation_performance.py` | 拖动/选择点击 0 次快照构建；每次 digitize 提交恰 1 次 + 只 bump 编辑层 revision |
| `test_map_vertex_drag_snap_performance.py` | 30 次拖动会话复用 snap 候选缓存（0 重建），提交时恰 1 次重建；100/2000 多边形参数化 |
| `tests/perf/test_v7_goal_perf.py` | 100k 层暖发布后单要素编辑 delta 只 ship 1 个要素 |
| `tests/perf/test_mirror_publish_scale.py` | 50–1000 层发布预算；style/visibility-only 不重 ship 要素 |
| ToolContext 收集链 | O(layers) 封顶，无 O(features) 热点（frame-level） |
| topology validate | 仅有限刷新点，(revision) 缓存 |

## C. V10 新增路径的性能纪律

1. **snap_feedback 回调节流**：仅匹配状态变化（无↔有、层/要素/类型变化）
   或 snapped 点位移 > 当前容差时回传 Python；纯 hover 位移在 C++ 内消化
   （marker 更新零 Python 往返）。以 call-count 测试锁定
   （N 次 move ≤ O(状态变化数) 次回调）。
2. **hover vertex marker**：`nearestVertex` 复用 `pickFeature` 的层集与
   容差策略，仅当前 pick 层（不做全层扫描 × 每次 move）——与既有
   press 路径同阶。
3. **vertex insert/delete**：单要素几何操作（QgsGeometry 单要素），无层扫描；
   提交链走既有 120ms 防抖增量镜像。
4. **part/ring/convert 命令**：只触碰选中要素几何；explode/collect 的
   bridge 调用是 O(选中要素)，与 split/merge 同阶。
5. **ring 闭环维护**：O(1) 坐标联动（仅首/尾两个下标）。
6. **`_split_inputs`/availability**：维持 O(layers+selection)（V9 W10 决策
   不加缓存，V10 不翻案）。

## D. V10 call-count/复杂度测试

- `test_v10_edit_paths_callcount.py`：
  - digitizing 过程回调 ≤ 每 captured 顶点 1 次；
  - snap_feedback 节流契约（见 C1）；
  - native vertex 三操作每次手势恰 1 次 session 命令 + 1 次 revision bump。
- 100k 层单要素 insert/delete vertex：delta publish 恰 1 要素
  （沿用 v7_goal_perf 模式）。

## E. 明确不测

- 100GB seismic（硬排除）；
- wall-clock 绝对阈值（既有纪律：call-count / 复杂度比 / 重建计数，不用 ms）。
