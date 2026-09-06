# Workstation UX V6 — 01 信息架构

Date: 2026-09-07 · Status: implemented in this branch (see 00-baseline.md for the as-was state)

## 1. 不变的骨架

V6 没有引入新的导航层级，也没有新增任何全屏页面。骨架保持：

```
PaleoWorkbenchWindow (QMainWindow, dock host)
└── AppShell（页面栈 + 命令面板 + 状态条 + UIContextService）
    └── WorkstationFrame（13 dock + 中央 CompositeDocument）
```

中央 2D 地图权威仍是 `CompositeDocument`（QGIS 桥 → `QgsMapCanvas`；无桥诚实回退 `UnifiedMapCanvas`）。编图阶段（phase1/2/3）是**工作上下文而非页面**——地图永不切换，只有阶段面板/工具面/输入树随阶段变化。

## 2. V6 的收敛点

| 变化 | 之前 | 之后 |
|------|------|------|
| 面板可恢复性 | `_PANEL_TOGGLE_TABLE` 7/13 dock，关掉即失联 | 13/13 dock 全量可从 面板菜单/Ctrl+K 恢复 |
| Hub 页 | 一律 force-float 弹窗 | 保持（本轮未改浮窗形态；见 10-known-limitations） |
| 预设几何 | 具名预设无条件 `dock_all_panels()` 摧毁用户几何 | 具名预设只切可见性；恢复默认才重置几何 |
| 窗口几何 | 主窗口从不持久化 | 与 dock 布局同一版本栅栏持久化 + 跨屏 clamp |
| 阶段命令面 | `StageToolProfile` 零消费者，工具条静态 | 构造/切阶段即过滤数字化动作；阶段动作入 palette |
| 领域命令入口 | palette 只有 29 条 chrome 命令 | +`workflow:recompute` + 阶段动作命令（阶段限定） |

## 3. 十大用户任务的承载面（审计结论，V6 未新增页面）

1. 工程/工区 — home 页 + 状态条工程名
2. 数据与溯源 — Data hub（分页目录 + 概览缓存聚合 + 生命周期控制器）
3. 井解释 — Well hub（canvas panel + 预测页）
4. 地震解释 — Seismic hub（SeismicViewPanel）
5. 井震联合 — LinkedInterpretationWorkspace（L10 状态条）
6. 单因素 — 阶段2 面板动作 + 因素工作台 dock
7. 地质编图 — 中央 CompositeDocument（权威）
8. 成图排版 — MappingPage dock（非中央）
9. 三维建模 — GeologicalModeling3D 页 + geo3d 控制器
10. Agent/自动化 — Agent dock + 任务中心 dock（harness 权威）

正确形态判定沿基线审计结论：本轮修复把「dock 关闭后不可恢复」「阶段命令无过滤」两类错配关掉；其余承载面维持审计时的合理归属。

## 4. 明确不做的事

- 不建第二个地图页面/第二套图层树（QGIS 树是运行时权威）
- 不把 Hub 页改造成新页面形态（本轮范围外，遗留见 10）
- 不删 WellSeismicJointPage 等死代码（留待独立清理 PR；基线清单在 00-baseline §1）
