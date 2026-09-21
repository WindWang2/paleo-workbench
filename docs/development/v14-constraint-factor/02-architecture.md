# V14-CONSTRAINT-FACTOR — 02 架构

## 目标状态（Stage 2 闭环）

```text
PreparationPage（已存在，生命周期守卫完备）
   │ set_prepare_worker_fn ← 真核绑定（本线）
   ▼
ui_workers::run_factor_prepare_schedule（已存在，调度器移植）
   │ seams: classify_fn / batch_fn / group_key_fn / grid_peek_fn
   ▼
closure_workflow::factor_prepare_production（本线新增，组成根）
   ├─ classify_fn   → factor_host 指纹（fingerprints_for_task 胶水）+ classify_factor_recompute
   ├─ batch_fn      → 每任务隔离插值（mapping_kernel IDW/kriging/constrained_idw）
   │                  + 任务补丁（_attach_result_to_task 语义）+ LiveFactorGridStore
   ├─ group_key_fn  → factor_host plan 摘要（纯 IDW 几何组）
   └─ grid_peek_fn  → LiveFactorGridStore::peek
   ▼
PrepareResultView（DTO 已存在）
   │ set_commit_prepare_fn ← 真核 commit（本线）
   ▼
closure_workflow::commit_prepare_batch_result（GUI 线程）
   ├─ 代数/目标守卫（页面已做；commit 再验 generation）
   ├─ stale-input 守卫（无 memo 重推导指纹，用 scheduled overrides）
   ├─ 定点索引替换（live task JSON 整体替换 = Python item.task 深拷贝语义）
   ├─ LiveFactorGridStore::store/clear_if_fingerprint（#834/#881 契约）
   └─ catalog 登记（factor_map run：running→INTERMEDIATE 版本→complete，
      stamp task.grid_artifact_version_id → workflow_runtime freshness 即刻可读）
   ▼
等值线 leg（已真核）→ commit 升级为 upsert + apply_contour_draft_to_map
   （contour_drafts 保 id upsert + paleomap_documents line features 推送）
   ▼
cross-well dock：FactorContextProvider（井链上叠加当前 factor/约束上下文）
```

## Source of truth（逐项）

| 状态 | 权威 | 说明 |
|---|---|---|
| 任务列表/补丁 | project JSON `factor_map_tasks[]`（PwbDataStore 文档） | commit 是唯一写者（GUI 线程） |
| 网格数值载荷 | `LiveFactorGridStore`（进程内 LRU）→ catalog 版本 payload（INTERMEDIATE） | `task.parameters` 永不携带网格数组（GRID_ARRAY_PARAMETER_KEYS 剔除） |
| 版本/provenance | `workflow_runtime::CatalogRepository` seam；app 侧 `FileCatalogRepository`（`<项目目录>/workflow_provenance.json`，原子写） | 不建第二个 catalog；不直写 SQLite |
| 指纹/复用判定 | `factor_host`（SHA-256 Python-canonical JSON） | 单一实现，classify 与 commit 复验共用 |
| 等值线草稿 | project JSON `contour_drafts[]` + `paleomap_documents[]` line features | upsert 保 id |
| 约束 | project JSON `constraint_layers[]`（编辑属 QGIS 会话/Prompt3） | 本线只读消费 + 指纹 |
| 图层顺序/激活 | Prompt3（QGIS layer control plane） | 本线不触碰 |

## Ownership / lifecycle

- `factor_prepare_production` 模块**实际落点 = `apps/paleo_workbench_platform/`**（namespace `pwb::factor_production`），而非最初计划的 `libs/closure_workflow`：执行时核实所有标准 preset（linux-ninja / native-product / developer-fast）都不开 `PWB_BUILD_CPP_CLOSE_02`——平台构建里 closure_workflow 目标不存在，PreparationPage 的真核绑定无法落在那里。app 层已 PUBLIC 链接 MappingKernel/WorkflowRuntime/UiWorkers/FactorHost（CMake 的 CLOSURE-MAPPING 块按 `PWB_BUILD_CONV_05/18` 条件加源），无环。02 线（cpp-close-02）进入平台配置后可无迁移地替换 `PersistentRuntimeCatalog` 为 `closure_workflow::FileCatalogRepository`（同一 `<root>.json` 契约）。
- `LiveFactorGridStore`：`closure_workflow` 内进程级单例风格（显式实例由 app 注入，测试可自建）。容量 env：`PALEO_LIVE_FACTOR_GRIDS_MAX`（默认 64 条）/`PALEO_LIVE_FACTOR_GRIDS_MAX_BYTES`（默认 256 MiB），LRU 逐出；条目密封（axes float64 拷贝 + z float32）。
- app 侧 `FileCatalogRepository` 生命周期：`ClosureContext` 持有，随项目打开/切换 reopen（notify_project_changed 重绑）。线程约束：CatalogRepository 按合同线程封闭——登记在 GUI 线程 commit 内完成（每任务一个原子事务，20 因子规模无压力）。

## 插值方法矩阵（诚实性）

| UI 方法 | backend | C++ 路径 | 处置 |
|---|---|---|---|
| IDW | idw | `mapping::interpolate_factor(method="idw")` | 生产 |
| 克里金 | kriging | `mapping::interpolate_factor(method="kriging")` | 生产 |
| 约束IDW | constrained_idw | `mapping::constrained_idw::generate_constrained_idw` | 生产（≥3 井、边界环/样本凸包、分辨率 clamp 20–200） |
| 样条 | cubic | 无 C++ 核（SciPy griddata 未移植） | **诚实失败**：task failed + `last_error`（"插值后端 cubic 未原生接入"），不伪成功 |
| 方向趋势 | directional | 无 C++ 核 | 同上诚实失败 |

决策记录：geoviz WLS kriging 与 `interpolate_factor` 的 numpy-OLS 估计器是**不同估计器**（interpolator.hpp 明示）。本线以 mapping_kernel 为权威（其 oracle 已冻结于 main），不并行引入第二个 kriging。网格轴 padding 差异（mapping 10%/0.01 vs geoviz 5%）同样以 mapping_kernel oracle 为准——这是 CONV-28 既定权威。

## 失败语义（fail-closed）

- 采样 <2 有效点 → task failed（Python validate 文本）；
- 约束 CRS 组不兼容 → task failed（不静默换 CRS）；
- CRS 未声明 → planar 距离策略注记（既有多态行为），不猜测投影；
- catalog 登记失败 → run 标 failed（吞内层异常后重抛，map_product 模式），task 补丁仍落 project（数值真源），版本戳留空，UI QC 显示"版本未登记"；
- 取消 → 无部分 commit + 非 reused 任务的 live grid 失效；
- 不支持的方法 → per-task 诚实失败，批次继续。

## 线程/异步模型

- GUI 线程：snapshot 构建（指纹输入与分类一致）、commit、catalog 登记。
- WorkerHost 线程（现有）：调度器 + batch_fn；`WorkerHost::marshal` 回 GUI 线程回调（已存在）。
- 并行组（`PALEO_PREPARE_WORKERS`>1）：std::async 组（调度器已实现）；`FingerprintMemo` 自带 mutex。本机默认 1（保守）；governor_clamp_fn 按 `std::thread::hardware_concurrency` 与 4 取小 clamp（不写死 ≥4）。
- 取消：`job::CancellationToken` 经 WorkerHost 注入；内核在阶段边界检查（sub-second 粒度，science_service 既定）。

## Scale budget

- 目标规模：1k 井采样 × grid_n 200 单任务 < 1s（IDW O(N·n²) 全邻在 1k×200²=4e7 距离≈百 ms 级）；20 因子队列串行 < 20s。10k 采样走 kNN（max_neighbors 语义既有）。
- live store 上限 256 MiB（float32 z：200² ×4B=160KB/格，64 条≪上限）。

## 与其他四线的边界

- Prompt1（catalog 深层）：本线只用 seam（FileCatalogRepository），不碰 SQLite schema。
- Prompt2（三阶段 UI 布局）：本线零 layout 改动；只让既有按钮/信号真工作。
- Prompt3（QGIS 控制）：图层添加/顺序/激活不碰；contour 经 paleomap_documents 数据面推送。
- Prompt5（综合成图）：fusion/integrated_compilation 既有路径消费 grid_artifact_version_id，本线为其补上输入版本。

## 迁移/向后兼容

- 旧工程：task.parameters 内联 grid_x/grid_y/grid_z（legacy）→ 分类时 `task_has_numerical_output` 识别；等值线读取走 legacy inline（已实现）。
- 旧任务只有 monolithic `input_snapshot_hash` → stored_fingerprints_from_task 走 legacy 分支（factor_host 已实现）。
- 新增字段全部为 task JSON 内 additive key；无 schema 破坏。
