# 10 — Data Migration & Compatibility

## 1. 兼容矩阵

| 旧状态 | V11 打开后 | 迁移动作 |
|---|---|---|
| 无 catalog（纯 resources 工程） | 既有 `migrate_legacy_resources` 投影 + 域绑定 | 已有，不动 |
| catalog v5 store（无新表） | 新表按连接幂等建；全部字段默认空 | 无显式迁移 |
| 旧 run（无 ports） | 匿名端口降级解释 | 可选启发补标（06 §5），幂等 |
| 单文件版本 | members=[] | 无 |
| 旧 EntityAssetLink（无 ordinal） | ordinal=0 | 无 |
| schema v1 工程文档 | 既有 workarea 迁移 | 已有，不动 |

## 2. 迁移原则（继承并强化）

- deterministic / idempotent / restart-safe：所有新迁移可重复执行且结果一致。
- 打开永不失败：每步独立守卫，失败进 report issue。
- 不静默猜 ambiguous 井绑定（既有 resolve_well 原则）。
- SQLite 演进只加表不 bump 版本（02/D3）—— 已论证避免 manifest 重建丢数据。
- 前向兼容：新字段对旧版本 app 可跳过（Pydantic extra 数据在
  catalog.json 上由旧 loader 忽略；ProjectDocument `extra="allow"`）。

## 3. V11 新增迁移点

1. `role_backfill`（打开时，一次性）：对既有 links 做角色词表校验
   （未知角色 → 保留但标记，UI 归 other）；为缺 primary 的 required_single
   角色补 primary（唯一候选时）；歧义不自动选。
2. `migrate_run_ports`（可选开关，默认开启一次）：06 §5 规则。
3. 损坏工程诊断：既有 store_health + audit 扩展 bundle 成员缺失、
   ports 引用悬空（version 不存在）的报告项。

## 4. 回归风险与守卫

- run_ports/version_members 悬空引用：load 时过滤 + audit 报告，不抛异常。
- reconcile 漂移检测必须覆盖新表（否则脏行不修复）。
- catalog.json manifest 往返：members/ports 随模型 dump/load 自动往返
  （Pydantic 默认值兼容旧 JSON）。
