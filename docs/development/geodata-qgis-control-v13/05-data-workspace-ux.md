# 05 — Data Workspace UX（V13）

## 1. 本轮交付

| 面 | 交付物 | 入口 |
|---|---|---|
| 规划导入 | `IngestPlanDialog`（构建 worker/逐项编辑/执行 worker/幂等重跑/可取消） | DataPage 工具栏「规划导入…」（Ribbon 同键代理） |
| 影响预览 | `confirm_trash_impact`（血缘+地图用途聚合，markdown 明细，默认取消） | 移出项目前自动 |
| 地图用途反查 | Inspector 概要「编图图层引用/地图产品」行 | 数据页选中资产 |
| Inspector map→data | 图层「数据来源/生成方式/上游输入/校验和」行 | 编图页选中图层（context seam） |

## 2. IA 分层原则（V11 既有 + V13 坚持）

Entity→Role→Asset→Version→Physical member 五层不在一个平面列表混排：
导航树到 asset 叶（500/页 lazy），版本在 VersionWorkbench/检查器页签；
井详情按角色矩阵。V13 未改动该骨架——增量是把「版本→地图」的第五维
（用途）接进检查器，而不是再造一棵树。

## 3. 确认式 vs 快速路径

- 旧快速导入（import_files/folder）保留——单文件急速路径；
- 规划导入面向批量/陌生目录——两阶段零副作用，Agent 与人共用
  `build/execute_ingest_plan`（W-S 红线）。

## 4. 未做（诚实记录）

- 井详情页 per-role 动作（设 primary/补缺角色/提交工作副本按钮组）——
  域 API 均已存在（upsert_entity_asset_link/EditSession），UI 未接；
- 版本级树导航（版本仍在对话框域）；
- Lineage Explorer 去 modal 化（保持 V11 modal 懒展开——够用且已达标
  bounded/lazy，docking 化留待反馈）。

判定：goal §8 的「层级清楚/ingest plan 可用/lineage explorer 可用/
impact/explain 可用/不全量 materialize」五条 DoD 全部满足（explainer
走既有 ExplainService + 检查器页签）；井工作台动作按钮属于增强，
不阻塞闭环。
