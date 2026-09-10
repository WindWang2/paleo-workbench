# 04 — 可用性矩阵与状态机测试（M6/M13）

## 方法

Goal §9 的维度（project/stage/backend/layer/role/editing/selection/CRS/
snapping/topology）不做全笛卡尔——采用**成对组合 + 边界 + 对抗**：

* `test_state_matrix_invariants`（参数化 ~30 组合）：每组合断言 10 条
  不变量（cancel 永远可用 / 阻塞全禁 / RAW-冻结判词 / kind 门禁 /
  抢主位防护 / 选择联动 / 阶段组隐藏 / 拓扑错误阻断合并 / CRS 阻断拓扑 /
  捕捉不可用判词）。
* `test_stage_group_visibility_matrix`：三阶段 + 未知 + 无阶段语义。
* 对抗 re-gate（`test_authoring_ux_v10.py` M6 组）：层切换/阻塞/选择
  消失/会话结束/修复 kind/阻塞下 toggle 六个「刷新间隙」场景。

## 发现并修复的 P1

**cancel 被阶段隐藏**：未知阶段 fail-closed 时 `_stage_group_gate` 把
snapping 组（含 cancel）整组隐藏 → Esc/取消按钮在未知阶段下死锁。
修复：`_stage_group_gate` 豁免 cancel（全局逃生口不参与阶段裁决）。
矩阵不变量 #1（cancel 永远可用）钉住该回归。

## 判词措辞单一化（M10）

`stage_whitelist_reason()`（tool_availability）成为阶段白名单判词的唯一
措辞真源；command_registry `_stage_reason` 复用（此前两套文案对同一语义）。
