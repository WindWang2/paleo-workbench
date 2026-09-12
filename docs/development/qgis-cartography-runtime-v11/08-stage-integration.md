# 08 — Stage Integration (V11)

## 1. 联合树原则（不变）

Phase 1/2/3 共享同一 union tree。`set_stage` 只改变：可见性（增量）、
默认锁播种、活动目标重指派（绝不跨阶段继承）、dock 建议、工具面/捕捉
重推、就绪度重算。**不** reconcile / 重 upsert / 重开层 / 丢样式选择。

## 2. V11 修复

* **空组物化**（D11-ws）：期望树的空组显隐按当前阶段评估；`set_stage`
  后 `rematerialize_for_stage()` 用最近组成快照重算（diff = 空组创建，
  组内零 move）——新阶段的空组立即可见可展开。
* **QC/AID 路由统一**（D1-ws）：`effective_home_group`（创建阶段 aux
  路由）——树构建/呈现/编辑门禁同源。
* **factor 标题**（D2-ws）：组成同步时从 `project.factor_map_tasks`
  同步 `sync_factor_titles`（此前无生产调用方，显示裸 task id）。
* **幽灵成员清理**（D13-ws）：`ensure_memberships` 清理组成中已消失
  图层的成员资格（空组成 = 加载中，不清理）。

## 3. 持久化

`state.tree`（含 order keys）+ per-stage view state + memberships +
maturity + compilation input set + QGIS XML 信封（呈现态）+
user_vector_layers（真源）。Expand-state 仍在 QSettings（项目名 key，
D12-ws 已知；V11 未迁移——`GroupNode.expanded` 已可消费，待 PHASE 10）。
