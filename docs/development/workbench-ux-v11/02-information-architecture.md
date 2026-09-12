# 02 — Information Architecture (Workbench UX V11)

## 用户工作作业模型（goal §10）

地学工作站用户的作业按六个工作域组织（导航枢纽即按此设计，V5 已定型，V11 保持并明确语义边界）：

| 工作域 | Hub / 入口 | 覆盖页面 | 用户问题 |
|---|---|---|---|
| **Project 工程概览** | hub 0 `overview` | HomePage | 项目健康吗？下一步做什么？ |
| **Data 数据** | hub 0 `management`（DataPage）+ 工作站 explorer | 数据管理、导入、目录、井位图 | 我有什么数据？质量如何？ |
| **Interpretation 解释** | hub 1（测井预测/层序格架/地层对比）、hub 2（地震预测/井震联合 3D） | 井/震解释各页 | 地下是什么样？ |
| **Mapping 编图** | hub 3（画布/制备/审核）+ 工作站中央 CompositeDocument | 编图全流程 | 如何编出一张可信的图？ |
| **QC 质检** | hub 3 `review` + 各页 QC 面板 | 审核、拓扑问题、质检表 | 结果可信吗？ |
| **Output 成果** | hub 4 可视化 + 导出工具 | 可视化、导出 | 如何交付？ |

阶段模型（Phase ①智能预测 ②约束与单因素 ③综合编图）是 **Mapping 域内的工作流上下文**，不是页面切换——同一画布/图层权威跨阶段保持（`mapping_workspace/stages.py` 设计不变）。

## 入口矩阵（V11 现状）

| 目标 | Rail | Explorer | Palette | 快捷键 | 阶段面板 | 跨页跳转 |
|---|---|---|---|---|---|---|
| 数据管理 | 模式（非导航，见 B1） | ✓ | ✓ | `1` | data 路由 | open_in_* |
| 测井预测 | — | ✓ | ✓ | `2`/`Alt+1` | — | ✓ |
| 层序格架 / 地层对比 | — | ✓ | ✓ | `Alt+2`/`Alt+3` | — | — |
| 地震预测 / 井震 3D | — | ✓ | ✓ | `3`/`Alt+2` | — | ✓ |
| 编图画布 | 模式 | ✓ | ✓ | `4` | 阶段路由 | send_to_mapping |
| 制备 / 审核 | — | ✓ | ✓ | `Alt+2`/`Alt+3` | 阶段动作 | send_to_prep |
| 可视化 | 模式 | ✓ | ✓ | `5` | — | open_in_visualization |

## 审计发现与 V11 处置

| # | 发现 | 处置 |
|---|---|---|
| B1 | Rail 数据/图层按钮过滤 explorer 而非导航——期望落差 | 保留 rail=explorer 模式的设计意图，tooltip 明确说明（`activity_rail.py` `_MODE_TOOLTIPS`）；页面导航走 palette/explorer/数字键。**不为 rail 增加第二导航语义**（避免一个功能两个状态） |
| B2 | 编图 hub 页三个宿主（hub dock / ToolPageDialog / canvas 隐藏 hub） | 维持（V9/V10 决策：编图页不与中央画布抢 dock）；文档固化该规则 |
| B3 | 可视化 hub 自称临时但占永久键位 `5` | 记录于 12-known-limitations；移除属于功能裁剪，超出 UX goal 边界 |
| B4 | 井/震双表面（hub 页 + 工作站 dock） | 设计意图（轻页 vs 工作站深度视图），由 ViewCoordination 保证同源选择；V11 的身份规范化（C1 修复）消除了两者错位 |
| B5 | 阶段动作导航离开画布 | 阶段面板动作现在带禁用原因（V11）；返回画布经 `4`/palette |

## V11 IA 相关变更

1. **Rail tooltip 词汇化**（B1）——rail 按钮的 tooltip/accessibleName 统一为「资源管理器 · …」，说明其为资源视图模式。
2. **阶段面板动作与 palette 同因**——同一阶段动作在阶段面板与 palette 上一致启用/禁用并给原因（05-action-surface）。
3. **任务中心成为所有长操作的单一出口**（07-task-feedback）——数据域、编图域、校验/导入/导出操作不再分散在各页状态条。
