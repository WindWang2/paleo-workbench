# 08 — 状态反馈（M4：编辑/捕捉/拓扑/CRS/比例尺/选择）

## MapStatusBar v2（`apply_context` 主入口）

| 读数 | 词表 |
|---|---|
| 坐标 | X/Y（地理 6 位/投影 2 位小数，按 CRS 缓存） |
| 比例尺 | `1:250,000`（千分位）；未知 `1:—`（不伪造精度） |
| CRS | 声明 auth id / `CRS: 未声明`；可证不一致 → `⚠` 前缀 + tooltip 解释（不只靠颜色） |
| 选择 | `已选 N` |
| 捕捉 | `捕捉: 开/关` + tooltip（容差/模式/参与引用层/角色推荐态/引擎可用性） |
| 拓扑 | `拓扑: 开/关` + 错误计数 chip `⚠ 拓扑: N 个问题`（>0 才出现；点击 → 显式校验 + 首问题选中定位） |
| 编辑 chip | `Edit 层名 ● 未保存` / `层名 · 可编辑` / `RAW · 只读` / `已冻结` / `可编辑性未知` / `查看` |

## 接线

`_sync_status_bar` 一次 `tool_context()` 投影全部读数（状态条与工具条
同一事实源）；坐标指针事件走 `point` 增量（高频路径不重算上下文）。
legacy 页面继续用 `update_state`（兼容入口）。

## 拓扑 chip 点击路径

`_on_topology_issue_activated`：显式 `validate_active_layer_topology`
（结论进运行时计数缓存）→ 0 问题「校验通过」；否则计数 + 首问题判词 +
首要素选中定位（`_locate_feature`）。
