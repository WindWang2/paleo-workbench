# 02 — Target Architecture

## 1. 分层总览（演进，不重写）

```
┌──────────────────────────────────────────────────────────────┐
│ UI 层                                                        │
│  Data Manager（实体树 + 资产表 + 版本 + lineage 视图）         │
│  各业务页（预测/因子/编修/QC…）                               │
├──────────────────────────────────────────────────────────────┤
│ 业务服务层                                                    │
│  EntityViewService (catalog/entity_views.py)   ← V11 新增     │
│  ImpactService     (catalog/impact.py)         ← V11 新增     │
│  ExplainService    (catalog/explain.py)        ← V11 新增     │
│  IngestPlanner     (resources/ingest_plan.py)  ← V11 新增     │
│  FreshnessService  (workflow/freshness.py)     ← 既有，扩展   │
│  catalog/lifecycle.py 各注册 helper            ← 既有，扩展   │
├──────────────────────────────────────────────────────────────┤
│ Catalog Core（单一权威）                                      │
│  DataAsset / DataVersion(+members) / DataRun(+typed ports)    │
│  DataCatalogService（单写者 + SQLite canonical + 分页）        │
│  CatalogPort / CoreCatalogAdapter                             │
├──────────────────────────────────────────────────────────────┤
│ Project Domain 层                                            │
│  WellEntity / SeismicSurveyEntity / EntityAssetLink(+ordinal) │
│  RoleRegistry (project/roles.py)              ← V11 新增      │
│  WorkArea / WellRegistry / resolve_well                       │
├──────────────────────────────────────────────────────────────┤
│ 遗留兼容层（strangler 收缩中）                                │
│  ResourceItem / project.resources / legacy_projection         │
└──────────────────────────────────────────────────────────────┘
```

## 2. 核心决策（ADR 级）

### D1 — 复合资产 = 版本级成员，不是新顶层实体

一个逻辑资产由多物理文件组成 → `DataVersion.members: list[VersionMember]`。
理由：身份/版本/lineage/回收/工作副本语义全部复用（新版本=新成员集）；避免引入
与 DataAsset 平行的 Bundle 实体造成双头身份。`member.rel_path` 相对版本 payload
目录；聚合校验和 = 对有序成员 sha256 的再哈希（`aggregate_sha256()`）。
"一口井的多个业务资产"**不是**复合资产 —— 那是 G1/G2 的 role 模型。

### D2 — typed lineage = DataRun 上的端口绑定，扁平 id 列表保持为投影

`DataRun.input_ports/output_ports: list[RunPort]`，`RunPort = {role, version_id,
ordinal, required, entity_type, entity_id, note}`。不变式：
`ports 中出现的 version_id ⊆ input_version_ids/output_version_ids`（扁平列表
= ports ∪ 未类型化补充）。旧 run（无 ports）合法 —— 查询面把无 ports 的输入
按 `input` 角色降级解释。写入只有一个入口 helper 维护两侧一致。

### D3 — 存储演进：只加表，不 bump STORE_SCHEMA_VERSION

`STORE_SCHEMA_VERSION` 停在 5。新增 `run_ports`、`version_members` 两张表：
进 `_SCHEMA_DDL` + `_DELETE_ORDER` + `_connect` 的幂等 DDL 列表（staging_leases/
working_copies 同款模式）。理由：bump 会让现存 v5 store 被归类 "legacy" 而从
可能过期的 manifest 重建（checkpoint 只在 close 时写）→ 数据丢失路径。
Pin / retention class 放 `version.metadata`（治理覆盖层，不动身份字段；
SQL 侧可用 json_extract 过滤，仓库已有该先例）。

### D4 — Role registry 是唯一角色词表权威

`project/roles.py`：`RoleDefinition(role, entity_types, cardinality, primary_policy,
display, stage_default…)`。`WELL_ROLES`/`SURVEY_ROLES` 从这里派生（domain.py
re-export 保持 import 兼容）。cardinality 是**指导性元数据**（0..1 / 0..N /
primary+alternatives / ordered），用于 ingest 推断、冲突检测与 UI 分组；
**不**作为硬约束拒绝加载旧数据（link 合法性由 upsert 幂等保证）。

### D5 — EntityDataView 是纯查询 facade，不是第二存储

`catalog/entity_views.py`：`EntityViewService` 从 project（wells/links）+ catalog
（assets/versions/working copies）即时组装 `WellDataView`/`SurveyDataView`/
`GeologicalEntityView`：per-role 资产分组、primary、current/历史版本、
related runs、derived products、missing sources、unresolved bindings、
uncommitted edits。物化上限受控（per-view 一次实体 scope），10 万级走
分页/lazy（井列表来自 project.wells —— 数量级 ≤10k；每井展开才触达资产）。

### D6 — staleness/impact 复用 DependencyGraph，实体视角 + pin 豁免

`catalog/impact.py`：`upstream_impact(version_id)`（改动/删除会破坏什么）、
`downstream_staleness(scope)`（实体或版本下游的陈旧报告，直接/传递、
nearest_changed_ancestor、pinned 豁免）、`delete_impact`（lineage 断裂清单）。
计算基于 catalog runs（含 typed ports），永不写回版本（既有 freshness 原则）。
与 `workflow/freshness.py` 的关系：freshness 回答"相对当前选择是否最新"，
impact 回答"相对任意上游版本演进/删除，下游会怎样"。两者共享 DependencyGraph
构建与缓存。

### D7 — Ingest plan 是显式两阶段：plan（纯计算）→ execute（可取消/分块）

`resources/ingest_plan.py`：scan → classify（复用 import_service/scanner 的类型
探测）→ identity match（resolve_well / SurveyRegistry，歧义→unresolved）→
role inference（RoleRegistry + 格式启发）→ duplicate detection（对已注册
RAW 的 sha/size；对 external 的 path）→ `IngestPlan`（纯数据类，可序列化、
可审查、可编辑）→ 用户确认/调整 → execute（catalog batch_save + 域绑定 +
primary 选择，分块可取消，幂等重入）。无法可靠判断的永远进 unresolved，
不从文件名静默猜科学语义。

### D8 — working copy 语义保持 #1211/#1232 既有设计，补齐业务编排

单文件 checkout→dirty→committing→committed 状态机不变。V11 新增
`catalog/edit_session.py` 薄编排层：按业务对象（well+role）成组 checkout、
批量 commit/cancel、组内一致性检查（同源版本冲突检测）。不引入第二套
workspace 存储。

### D9 — project.resources strangler 收缩路径

1. 写侧：catalog 已是权威（保持）；ResourceItem 继续作为兼容镜像由
   legacy_projection 维护。
2. 读侧：输入选择面（预测 input_contract、联合分析 resolve、井日志画布选择）
   逐步切到 EntityViewService，resources 遍历降级为 fallback。
3. Data Manager 实体树直接以 entity view 为数据源。
4. 不做一次性大删除。

### D10 — 组合/导出旁路收编

composition panel 保存 / SVG·PNG 导出走 `record_export`（OUTPUT 注册）；
recipe 文档与 DAG run store 保持非管理（设计如此，记录在 known-limitations）。

## 3. 模块清单

| 模块 | 状态 | 职责 |
|---|---|---|
| `project/roles.py` | 新增 | 角色词表权威 + cardinality + 推断/校验 helper |
| `catalog/models.py` | 扩展 | `VersionMember`、`RunPort`、模型字段 |
| `catalog/db.py` | 扩展 | `run_ports`/`version_members` 表 + 读写路径 |
| `catalog/service.py` | 扩展 | bundle 注册/校验、ports 写入口、pin API、cleanup 资格、实体 scope 轻查询 |
| `catalog/entity_views.py` | 新增 | EntityViewService + WellDataView 等 |
| `catalog/impact.py` | 新增 | 影响面/陈旧性/删除影响 |
| `catalog/explain.py` | 新增 | "为什么存在"问答 |
| `catalog/edit_session.py` | 新增 | 业务对象级编辑编排 |
| `catalog/lifecycle.py` | 扩展 | 各注册 helper 声明 typed ports |
| `resources/ingest_plan.py` | 新增 | 批量导入计划 |
| `ui/pages/data_page.py` | 扩展 | 实体树视图模式 |
| `ui/data_lifecycle_controller.py` | 扩展 | 实体树数据供给、ingest 计划执行 |

## 4. 不变量（新增 + 继承）

继承 01-current-state §4 全部 10 条，新增：

11. `DataRun` ports 与扁平 io 列表一致性（D2）。
12. bundle 成员的 `rel_path` 不得逃逸版本 payload 目录；聚合校验和可复算。
13. pin/retention 属治理/策略层，永不改变版本 payload/path/sha。
14. EntityViewService 无自有状态副本 —— 每次查询从权威数据即时组装（允许
    revision 键控缓存）。
15. IngestPlan 是纯数据 —— 确认前零副作用；execute 幂等可重入。
16. impact/staleness 永不写回版本（同 freshness 原则）。
