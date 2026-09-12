# 13 — Verification

V11 的本地验证记录（无线上 CI，按 goal §2 本地执行）。

## 测试环境

- Python 3.12（.venv，与仓库 requirements 一致）；Windows 11。
- 全量套件通过仓库自带分批驱动 `scripts/run_suite_batched.py`（单进程全量
  在本机会因 Qt access-violation 崩溃 —— 既有已知问题，非 V11 引入）。

## V11 专项套件（全绿）

| 套件 | 覆盖 | 结果 |
|---|---|---|
| tests/test_v11_core.py | typed ports 往返/不变式、bundle 注册/完整性/工作副本/重开、pin/retention、旧 store 增表 | 11 passed |
| tests/test_v11_services.py | entity views（角色分组/primary/井索引）、impact（direct/transitive/pinned/trashed/假设模式/upstream/delete/实体范围）、explain 问题集、edit session commit/cancel | 9 passed |
| tests/test_v11_ingest.py | 计划分类/角色推断/shapefile 族/重复检测、执行绑定/一井多 LAS/幂等重跑/取消/无静默绑定 | 6 passed |
| tests/test_v11_invariants.py | committed 版本只读、同 id 拒绝、pin/retention 不动身份、ports⊆flat 重载、无悬空 required port、成员不逃逸、聚合可复算、link 幂等/primary 唯一 | 10 passed |
| tests/test_v11_multifile_well.py | 一井全数据矩阵生命周期：3 LAS+trajectory+tops+TD → 视图 → 派生预测 → 上游演进 → 陈旧 → explain → 编辑会话 → 新版本 → 视图刷新；重导入稳定性 | 2 passed |
| tests/test_v11_migration.py | schema v1 文档升级、pre-V11 manifest 裁剪重开、roles backfill 幂等/歧义安全 | 3 passed |
| tests/test_v11_scale.py | 实体视图零 list_assets 调用（计数钉）、50 层链陈旧 O(深度)、bundle 预算、缓存每 revision 一次（计数钉） | 4 passed |
| tests/test_v11_entity_tree_ui.py | 角色分组树、实体激活信号、面板渲染、workspace 栈切换 | 4 passed |
| tests/test_v11_review1_fixes.py | 嵌套 bundle 路径、预算前置拒绝、成员名唯一（嵌套/顶层/规格三态）、缺表不误判 corrupt、同计划幂等重执行、pending 门、migrate_run_ports 幂等、井视图有界探测、survey 面板、多源同内容不误判 | 12 passed |

**V11 合计：61 passed。**

## 既有回归（针对性）

| 范围 | 结果 |
|---|---|
| tests/test_catalog_*.py（db/models/service/sqlite_canonical/concurrency/lazy_open/working_copy/…） | 全绿 |
| tests/test_data_page.py + navigation_tree + workspace + manager wiring | 99 passed |
| tests/test_td_calibration_lifecycle.py（ports 接入后） | 20 passed |
| tests/test_navigation_tree*.py（角色分组重构后） | 全绿 |

## 全量分批套件（最终结论）

`python scripts/run_suite_batched.py . <out>`：780 个测试文件逐文件跑，结果
**716 pass / 52 fail / 12 crash**。对全部 64 个异常文件做了与 base
`6c08fb7d` 的**严格 A/B 对照**（每文件双向、退出码+汇总行双重判定）：

- **56 个双向一致**（base 同样 fail/crash）：QGIS 桥未构建（qgis_render_bridge
  需数小时 vendored 构建，本机未装）、visual_qa 视觉回归、native 引擎 ABI、
  kriging/插值数值环境、Windows 只读 payload 的 tmp 清理 PermissionError、
  时序 flaky（test_workflow_review_fixes 在 base 单跑 4/4 复现失败）。
- **8 个曾在分支失败**：全部因 worktree 的 geo-viz-engine 子模块未检出
  （资产/源码扫描类测试）。从本地 base 检出按 pinned SHA
  `08851951` 物化后**全部通过（71 passed, 0 failed）**。非代码回归。
- 对照期间发现并修复了两个真实的 V11 侧测试期望/token 问题：
  `well_detail_panel` 裸 font-size 字面量（改 QFont）与
  `test_external_reference_wells` 的树叶结构断言（适配角色分组）。

**结论：V11 引入的代码回归为零；分支上 64 个异常全部可归因于既有
环境因素或 worktree 子模块缺失，且后者已物化验证。**

## Review 轮次

1. **Round 1（架构+完整性 / 迁移+规模，双 agent）**：1×P0（缺表读把健康
   store 误判 corrupt → manifest 重建丢数据）、7×P1（bundle 目录推导/
   move 语义/预算/成员名、ingest 幂等与重复身份、井视图全量扫描、
   backfill 未接线）、多项 P2。全部 P0/P1 已修；P2 主要项已修（统一
   端口写入口、实体 any-ancestor 范围、缓存键、闭包上界、外部重复
   note-only、pending 门）。回归钉：tests/test_v11_review1_fixes.py。
2. **Round 2（UI 工作流 / 独立代码复审，双 agent）**：1×P1 UI（survey
   面板缺字段崩溃）+ 1×P1（成员名三池碰撞）已修；GUI 线程陈旧计算
   改 worker 迟达、详情页刷新钩子、关闭按钮、O(1) 执行查重、
   (source,sha) 组合索引、外部引用 note-only。回归钉并入同文件。
3. 残余 P3 项记录于 12-known-limitations（角色组计数展示、标签 provider
   规模注意等）。

## 结构性验证方式（反 wall-clock）

- 查询计数钉（monkeypatch 计数）：实体视图零 `list_assets()`、井视图零
  `find_missing_sources()` 全量、缓存命中后零 `_ensure_maps`。
- 语义计数：50 层链 → 恰好 50 陈旧项、恰 1 direct。
- 确定性：所有迁移/backfill 幂等断言（重跑 == 零变更）。

## 已验证的 DoD 对照

| DoD 条款 | 证据 |
|---|---|
| 井不再隐式单文件 | ingest 一井多 LAS 绑定测试 + RoleSlot 多成员 + primary |
| 一井多资产成为正式 API | EntityViewService/WellDataView + roles registry cardinality |
| compound 有正式表达 | VersionMember/表/聚合哈希/工作副本/完整性/回归钉 |
| RAW/working/version 清晰 | invariants 套件 + edit_session（复用 #1211 状态机） |
| intermediate/derived/output 可执行 | retention class + cleanup_eligibility 双门 + pin |
| typed lineage 回答真实角色 | RunPort/查询 API/manifest 往返/迁移 backfill/explain |
| downstream impact/staleness 可查询 | ImpactService 全套测试 |
| 生产流程退出 resources 权威（逐步） | 导入侧 planner catalog-first；Data Manager 读侧实体视图；遗留读取面 strangler 清单（01 §5 G12） |
| Data Manager 围绕井/调查组织 | 角色分组树 + 井详情中心面板 + 测试 |
| 10 万级不回退全量物化 | scale 套件计数钉 + 井索引 O(W) 设计 |
| 旧工程可迁移 | migration 套件 + 既有 v1→v2 迁移保持 |
| 无已知 P0/P1 | 两轮 review 后全部关闭（见上） |
| 本地相关测试通过 | 本文件全部条目 |
| review 完成 | 2 轮 ×2 agent + 回归钉 |
