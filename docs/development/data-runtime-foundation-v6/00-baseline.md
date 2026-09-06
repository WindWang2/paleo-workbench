# Data & Runtime Foundation V6 — Baseline（D0 审计，以源码为准）

日期：2026-09-07 · worktree `.worktrees/data-runtime-foundation-v6` · branch `feat/data-runtime-foundation-v6` · base `295fabc3`

范围声明：本轮**不做** 100GB 地震体支持/基准/优化（地震仅允许小/中型 fixture 的生命周期路径）；不是 UI 重设计；不是新数据库产品；不是第二调度器。

## 0. 审计方法

六路并行源码审计（A 目录服务域模型 / B SQLite 规范库与索引层 / C 存储·工作副本·回收 / D 工程持久化与恢复 / E 运行时调度·治理·工作单元 / F 工作流·Harness 检查点 / G 交换·交付 / H 溯源·DataRun / I 跨进程并发 / J 大工程打开内存 / K 后台任务×工程生命周期 / L 测试·性能·崩溃覆盖），叠加 17 个开放 issue 的根因映射。全部 file:line 相对 `paleo_workbench/`（当前 worktree）。

## 1. 现有架构事实

### 1.1 目录核心（A/B）
- 规范库 = `metadata/catalog.sqlite`（WAL，`busy_timeout=5000`，`catalog/db.py:801-807`）；`catalog.json` 仅为 close/export checkpoint manifest（`catalog/store.py:1-12`）。`STORE_SCHEMA_VERSION=INDEX_SCHEMA_VERSION=5`。
- `DataCatalogService`（`catalog/service.py`，约 3750 行）：唯一写入口；内存持有完整 Pydantic `CatalogDocument` + `_CatalogMaps` 不可变快照（#619）；单 `RLock`（:288）。写路径 = 每 mutator 构造 `DirtySet` → `_save` → `apply_changes` 单事务 upsert；`batch_save` 合并单事务+单 revision bump（#1139）。
- **打开路径全量物化（结构性问题 #1212）**：`project_controller.py:296-299`（GUI 线程）→ `DataCatalogService.open`（`service.py:667-789`）→ `load_document` → `_load_document_once`（`db.py:1054-1199`）把**每一行**物化为 Pydantic（每 version 2 次 `json.loads`），随后 `_ensure_maps()` 第二遍 O(N)（`service.py:417-456`）。`ensure_index` 形参是死参数（:671 接受、体内未用）——控制器传 `ensure_index=False` 实际什么都没推迟。10 万资产下打开 = 秒级 GUI 阻塞 + 全量 RSS。
- 分页门面已是 SQL 支撑（索引 current 时）：`search_assets_page/count_assets/catalog_aggregates`（`service.py:3231-3410`）。实测 @100k：page0 4.31ms、深翻页 7.45ms、count 3.01ms、聚合冷 389ms（docs/development/catalog-scale-v5/explain-100k.txt）。
- 残留热路径全量物化：`search_assets` 物化 list（50k 类型过滤 746ms）；`adapter.list_versions/list_runs` 每行 `resolve_path`（每行 stat）；文档回退分页路径在 RLock 内 O(N) 过滤（`service.py:3530-3577`，100k mid-batch 秒级阻塞写者）。

### 1.2 陈旧写防护（#1220）
- #411 守卫 = **check-then-act，非 CAS**：revision 在 `service.py:887` 于事务外读取；`apply_changes` 提交时**无条件**写 `catalog_revision`（`db.py:1378-1385`）。B 读 revision 与 B 提交之间 A 提交 → 双写者都成功、revision 相同值互相掩盖。全库无 `BEGIN IMMEDIATE`（隐式 DEFERRED）。
- `rebuild_index`（`service.py:1005-1012`）**无 stale 守卫、无锁**：reset 后用过期内存文档重建；并发 flush 落入 `write_all` 全量覆盖（`db.py:1217-1223`）。
- 无范围 `_save(dirty=None)` → `reconcile()` O(N) 全库 diff——双实例下**删除对方进程的行**（`rebase_artifact_paths` `service.py:3727` 即此形态）。

### 1.3 载荷注册与回收（C/#1218/#1222）
- `place_managed_file`（`storage.py:371-465`）：复制中流式 SHA-256、fsync、`.place-*` temp + `os.replace` + 只读位；`known_sha256` 与实际字节比对。大 IO **刻意在锁外**（`register_version` `service.py:1357-1365` 等）——正确方向。
- `register_derived_store`（`service.py:1505-1609`）：**无哈希、无任何 fsync**，仅结构指纹 {files,bytes}。
- 两处**直接写进 stage 树**的非受控生产路径：地震属性计算 `derived/{asset}/{ver}/.attr-*`（`seismic_lifecycle.py:562`）；Harness mapping npz 直写 `intermediate/`（`harness/actions/mapping.py:366-387`）——计算期间文件无引用，显式 GC 可删（#1222 家族）。
- GC（`catalog/gc.py`）：`plan_gc/sweep_gc/cleanup_working_copies` **全程无锁**（`catalog/audit.py:625` 明文）；分类=纯可达性快照；sweep = 快照后逐项删除、**删除时不复查**（`gc.py:265-294`）。载荷先落盘后提交元数据的窗口内，显式 sweep 把活载荷判为 STAGE_ORPHAN 删除 → 提交出 `payload_missing` 版本。**无任何 lease/epoch/心跳机制**。
- 工作副本现状（#1211）：`create_working_copy` 全量复制到 `working/{version_id}/`（`storage.py:468-494`）；**目录存在即全部状态**——无登记、无 dirty 标记、无崩溃恢复；重复 checkout **原子替换未提交编辑**（`tests/test_storage_m1.py:30-55` 钉为"预期"）。
- #1218：`commit_working_copy`（`service.py:1837-1891`）→ `register_version(move=True)`；move+元数据在锁内。GB 级 move 同卷 rename 本身快，但哈希/dedup 验证若在锁内则持锁跨 IO（实现阶段核实并修复）。

### 1.4 工程持久化与恢复（D/#1229）
- 保存三阶段（`project/manager.py:425-552`）：prepare（mtime 陈旧守卫 :474-483）→ execute 工作线程（mkstemp+fsync+replace main→bak、tmp→main :392-423）→ commit。
- **恢复缺陷（#1229）**：`_load_data`（:554-576）把 `(OSError, ValueError, TypeError, ValidationError)` 一律当损坏 → `.bak` `os.replace` **破坏性**顶替 main。**暂时性不可读（杀软/同步工具锁 → PermissionError）会把较新的 main 静默降级为较旧 .bak**。无隔离区（目录层有 `catalog.sqlite.corrupt-<ts>` 先例 `service.py:715-735`，工程层没有）；`last_recovery_message` 挂在一次性 manager 上，UI 从不读取；恢复事件无持久记录。
- 工程文件**无持久 revision 计数器**（仅 `schema_version:1`），陈旧保存检测纯 mtime（同步工具误报；prepare→execute 间 TOCTOU）。
- 未知字段往返 OK（`extra="allow"` + portable snapshot 保留）。save-as 有 relocation 暂存与回滚。

### 1.5 运行时（E/F/#1223/#1224/#1225）
- `TaskScheduler` 单例：**全进程仅 2 守护线程**（heavy lane 并发=1 + interactive=1）。取消纯协作（Event）。治理 lease **持有到 callable 返回**（`task_scheduler.py:495-499`）——不查 token 的任务取消后仍占 heavy lane + `task_key`（同键重提交 ValueError 直到旧任务落地）。
- `OwnedWorkerJob`：每任务一 QThread；`shutdown(3000ms)` 超时后 DetachedJobKeeper 收养。
- 取消真实性：**真** = 转码（逐 shard）/属性（逐 band）/DAG 节点边界/factor-prepare/ONNX 逐 tile/打包/relink/audit；**假（cosmetic）** = LAS 井数据解析（`well_log_load_worker.py:36-56` 仅前后检查）、地图导出渲染（`map_export_worker.py:195-221`）；**无取消** = 哈希（`catalog/checksum.py:20-26`）、`fast_grid.interpolate_idw_grid_batch`（零检查，大网格批不可中断）。
- **治理旁路（#1225）**：vendored `fast_grid.py:19-36` 进程生命周期 `_shared_executor` 由 `os.cpu_count()` 定宽；`_pin_blas_threads`（:441-456）**每次调用运行时改写** `OMP/OPENBLAS/MKL/NUMEXPR/VECLIB_NUM_THREADS`，且 `threadpoolctl.threadpool_limits` **不带 with 使用**（全局生效、上下文泄漏）。DAG 引擎池宽 = spec `max_concurrency` 不经 `clamp_workers`（`workflow/dag/engine.py:465-471`）；`interchange/batch.py:103-108` 自行 clamp 1..4。
- **会话代际（#1223）**：`ProjectController._session_generation` 只护住异步保存+目录维护；各页 on_done 依赖 `job.target is not self.project` 身份检查；`mapping_page._on_map_export_finished`（:2283-2301）用的是导出开始时捕获的 project 对象，**槽本身无检查**——目前靠 OwnedWorkerJob released-guard 基础设施间接兜底，脆弱。
- `resume_pending`（`seismic_lifecycle.py:460`）**未接线到工程打开**（docstring 是愿景；仅在首次生命周期活动时触发）；workflow INTERRUPTED 恢复仅有 agent 面板入口。

### 1.6 溯源与身份（G/H/#1219/#1221）
- **幽灵 run 窗口（#1219）**：`map_product.assemble_map_product`（`workflow/map_product.py:124-169`）先 `register_run`（**默认 status="completed" 且无输出**）再 `register_result_asset`——两保存之间崩溃 = 永久幽灵；异常路径**不**补偿 run。audit `orphan_completed_run` 只检查 `{materialize, working_copy_commit}`（`catalog/audit.py:296-316`）→ map_product 幽灵**不可检测**。同"预记 completed"模式：`data_lifecycle_controller.py:860/924`（有 `_fail_booked_run` 补偿 + audit 覆盖）。interchange `_record_run` 异常吞掉（`executor.py:114-115`，fail-open 溯源丢失）。
- **身份 fail-open（#1221）**：`resolve_path` basename 回退在版本**既无 sha 又无 size** 时 `_fallback_identity_ok` 直接 `return True`（`service.py:1187-1202`）——同名无关文件可被绑定。`relink_external_source` 本身 fail-closed（`sources.py:223-241` 要求 sha 或 size+mtime_ns 证据）；legacy 迁移产物**无任何身份事实**（`migration.py:195-208` 不 stat 不哈希）→ 永久不可 relink + resolve fail-open。
- 交换打包：catalog.json 随包；溯源截断为前 1000 条 run、无边；vendored 外部文件**不回绑**包内路径。

### 1.7 跨进程与规模（I/J）
- 全库**无文件锁**（无 msvcrt/portalocker/fcntl）；双实例仅靠 #411 revision 栅栏 + mtime 守卫协作。B 在 A 提交后、下次 flush 前静默供旧读。
- 无两**真进程**测试（所有"跨进程"= 单进程两个 service 对象）；跨 flush TOCTOU 无测试。
- 打开内存下限 = 全量 Pydantic 图。capacity 守卫钉的是 UI 层单驻留，不是 open RSS。500k 档未实现。
- 崩溃测试强项：真 SIGKILL/TerminateProcess（`crash_kill_helper.py`）。**缺**：GC 竞态、工作副本状态机、main PermissionError 恢复、双进程写冲突测试。

## 2. 开放 issue 根因映射

| Issue | 根因 | 子系统 | 架构家族 | 修复方式 |
|---|---|---|---|---|
| #1212 P1 打开全量物化 | `_load_document_once` + `_ensure_maps` 是 open 的必经路；死参数 `ensure_index` | catalog service/db | **懒加载缺失** | 收敛：lazy repository |
| #1228 P2 GUI 物化旁路家族 | overview/legacy map/地层对比/属性表仍走 `search_assets` 物化 API | ui pages | 同上（消费侧） | 收敛：改走分页/懒 API |
| #1220 P2 stale TOCTOU + rebuild 绕过 | revision 检查在事务外；rebuild 无守卫无锁；reconcile 全量 diff | catalog service/db | **事务级 CAS 缺失** | 收敛：BEGIN IMMEDIATE+CAS |
| #1218 P2 commit 持锁跨 IO | move/hash/dedup 在锁内 | catalog service | 锁内 IO | 收敛：staging 协议 |
| #1222 P2 sweep×注册竞态 | GC 无锁 + 快照后不复查 + 无 lease | catalog gc/storage | **注册/GC 协调缺失** | 收敛：staging lease + 删除前复查 |
| #1211 P1 工作副本覆盖 | 目录存在即状态，无登记 | catalog storage/service | **工作副本无生命周期** | 收敛：状态机 |
| #1229 P2 .bak 误回退 | OSError 与损坏不分流 | project manager | **恢复判定表缺失** | 收敛：恢复决策表 |
| #1223 P2 旧代际回调 | 守卫散落、槽级无检查 | runtime/ui | **会话代际不统一** | 收敛：session token 守卫 |
| #1224 P2 假取消 | LAS/导出无 chunk 检查；哈希无 token | runtime/ui | **取消不可达内部循环** | 逐路径收敛 |
| #1225 P2 IDW env 改写+旁路 | vendored 运行时改 env + 自建池 | vendored/runtime | **治理旁路** | 收敛：governor 收编 |
| #1219 P2 幽灵 provenance | 预记 completed + audit 盲区 | workflow/audit | **溯源原子性** | 收敛：begin→register→complete + audit 扩展 |
| #1221 P2 basename fail-open | 无身份事实时 return True | catalog service/migration | **身份 fail-closed 缺失** | 收敛：证据要求 + 迁移补事实 |
| #1213 P1 WellRegistry O(N×W) | 每次 extract 重建注册表 | well binding | 规模（边缘） | 视 PHASE 11 余量 |
| #1214–#1217, #1226, #1227, #1230 | 井域算法/地震 footprint/CI | — | 井域/算法/CI 家族 | **本轮范围外** |

**收敛判断**：12 个范围内 issue 归为 6 个共享根因家族（懒加载、事务 CAS、载荷/GC 协调、工作副本生命周期、会话代际/取消、溯源/身份 fail-closed）+ 1 个恢复判定表。全部按家族收敛修复，不做独立补丁堆叠。

## 3. 必须保留的有效契约
- DataCatalogService 唯一写权威 + DirtySet 单事务写 + batch_save 单 revision bump（#1027/#1139）。
- 版本不可变性（ImmutableVersionError、promote=复制新版本）、只读位作为意外防护而非安全边界。
- place_managed_file 的 temp+fsync+replace+known_sha 校验；CAS blob 内容证明采纳。
- trash 先 tombstone 后 move + 崩溃探针恢复；purge 的 blob 引用计数保护。
- 分页契约（SQL/文档回退行形一致、keyset、order 白名单、revision+serial 键控缓存）。
- resolve_path 精确匹配阶梯 + 已记录身份事实的校验（#1140 主体）；relink fail-closed 证明阶梯。
- 线程所有权不变量（#1026/#394：per-thread 连接池、interrupt-不-close）。
- 工程保存三阶段 + 未知字段往返 + save-as relocation 回滚。
- TaskScheduler 双 lane + aging + governor lease 语义；OwnedWorkerJob released-guard。
- 交换打包的 staging+原子发布 + 校验器 fail-closed。

## 4. 本轮目标形态（详见 01–07 各篇）

```
Canonical Catalog Store (catalog.sqlite, WAL)
        ↓
Transactional Indexed Repository（BEGIN IMMEDIATE + revision CAS + staging lease 表）
        ↓
Lazy Entity Repository（按 id 行→Pydantic + SQL list/page/aggregate/lineage）
        ↓
DataCatalogService（唯一公开生命周期权威；文档对象=后台温备缓存，非热路径必需）
        ↓
query / aggregate / resolve / lifecycle APIs（UI/业务不触 SQLite）
```

硬指标：100k 工程 open 到响应壳 <500ms；查询在温备期间可用或给出诚实加载态；单冲突写者成功、另一个收到类型化陈旧错误；无 payload_missing 由 GC 竞态产生；工作副本无静默覆盖；恢复只在损坏确证时发生且留痕。
