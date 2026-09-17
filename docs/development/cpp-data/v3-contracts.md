# CPP-B v3 接口契约（run 生命周期 + 单产物发布 + 显式恢复）

冻结于 `codex/cpp-v2-data` 分支（基线 `53e22b679ea3181d4e2c2bca8d42ca272c00dfbf`）。
本文替代性扩展 v1 `contracts.md`（v1 语义全部保留，结构体未改动）；
伞头 `pwb/data/contracts.hpp` 的 `kVersion` 升至 **3**。A/C/E 消费以下公共头：

```text
libs/data_suite/include/pwb/data/
  contracts.hpp          伞头（版本钉）
  run_contracts.hpp      run 生命周期类型（v3 新增）
  commit_coordinator.hpp CommitRequestV1 + PublishRequestV1 + 协调器
  facade.hpp             只读 ProjectSnapshotV1
  session.hpp            WritableSession（显式可写/恢复入口，v3 新增）
```

公共接口不携带 QGIS/Qt/Python/Science 类型：输入只有领域 ID、JSON/POD
元数据和已落盘的 staged 文件。C/E 的算法对象由 A 的 `libs/application`
转换后再调用 B；B 不链接算法库。

## 1. 状态与操作总览

| 操作 | 入口 | 写入 | 幂等键 |
|---|---|---|---|
| 工程打开（只读诊断） | `DataFacade::open_snapshot()` | **零写入** | — |
| 查询资产/版本/run/provenance | `pwb-inspect --asset/--version/--run/--provenance` | **零写入** | — |
| 编辑提交（新版本） | `CommitCoordinator::commit(CommitRequestV1)` | journal+payload+SQLite+工程 | `operation_id` |
| run 开始登记 | `CommitCoordinator::register_run(RunRegistrationV1)` | SQLite 单事务 | `run_id` |
| 单产物发布 | `CommitCoordinator::publish_run_result(PublishRequestV1)` | journal+payload+SQLite+工程+run 终态 | `operation_id` |
| 算法失败/取消终态 | `CommitCoordinator::finish_run(run_id, RunTerminalStatus{Failed\|Cancelled}, extra)` | SQLite 单事务 | 终态不可改写 |
| 显式恢复 | `WritableSession::open(...).recover()` | 恢复性写入 | 逐 journal |

## 2. 编辑提交（v1 语义保留，v3 加固）

`CommitRequestV1` / `CommitReceiptV1` 结构不变。v3 新增两条硬规则：

1. **pending 闸门**：任一未完结 journal（`written`/`payload_staged`/
   `catalog_committed`/`project_saved`/`rebound`/`run_completed`）与本次
   操作目标重叠（同 `asset_id`、同 `run_id` 或同 `rebind_layer`）时，除
   同 `operation_id` 的续传外，一律以 `recovery_required` 拒绝——先
   `recover()`，再写入。pending journal 文件永不自动删除。
2. **幂等键命名空间**：`operation_id` 全局唯一于提交与发布共享空间。
   同 id 重复 → 回放同一 receipt（`Duplicate`），不新增版本；用已属于
   另一种操作（edit_commit vs run_publish）的 id 调用 → `invalid_argument`。
   新操作（新 id）永不命中旧幂等键：每次操作生成全新 `ver_` id。

其余不变：future schema/只读禁写、payload hash 失配、stale base、缺
资源、非法 id 均在任何写入前拒绝；原版本不覆盖（目标路径已存在 →
`immutable_version`）；同 operation 重试返回同 receipt。

## 3. run 生命周期（v3 新增）

```cpp
struct RunRegistrationV1 {        // pwb/data/run_contracts.hpp
    domain::RunId run_id;         // 调用方生成，幂等键
    std::string operation;        // 如 "seismic.coherence_c3"
    std::string generator;        // "algorithm_id@version[+build]"
    domain::Json parameters;      // 完整参数记录（B 不解释）
    std::vector<domain::VersionId> input_version_ids;
    std::vector<catalog::RunPort> input_ports;   // ⊆ input_version_ids
    std::optional<domain::Json> model_ref;
};
```

- **登记** `register_run`：写一行 `status="running"` 的 run（SQLite 单
  事务 + revision bump）。同 `run_id` 重放 → 返回既有行（不重复建行，
  info 诊断 `run_registered_earlier`）；已终态的 run 重放登记 → 返回既有
  行 + warning 诊断（不复活；重试语义 = 新建 run，Python parity）。
- **成功**：只能经 `publish_run_result` 达成——run 行在 payload、版本行、
  工程绑定全部 durable 之后才翻转为 `"complete"`（见 §6 阶段序）。
- **失败/取消** `finish_run(run_id, Failed|Cancelled, extra_parameters)`：
  单事务 `UPDATE runs SET status=...` 并把 `extra_parameters` 原样合并进
  `run.parameters`（`finished_at` 由 B 记录）。拒绝条件：run 不存在 →
  `not_found`；已终态且目标不同 → `conflict`（终态不可改写，重试建新
  run）；已有输出版本 → `conflict`（已发布的 run 不能改口为失败/取消，
  保证"失败/取消不产生成功版本或成功 lineage"）；存在持有该 run 的未完结
  发布 journal → `recovery_required`（先恢复）。
- **查询**：`run_state(run_id)`（只读投影）；`pwb-inspect --run <id>`。

run 状态词表：`running` / `complete` / `failed` / `cancelled`
（Python catalog 词表子集；`completed` 为读侧别名，B 写 `complete`）。

## 4. 显式可写会话与恢复（v3 新增）

```cpp
auto session = pwb::data::WritableSession::open(project_file);
if (!session) { /* error() 携带原因 */ }
RecoveryReportV1 report = session.value().recover();
// report.continued / report.rolled_back / report.pending + diagnostics
```

- 只读打开零写入：`DataFacade`、全部 `pwb-inspect` 查询模式不开写句柄、
  不建 WAL、不落任何文件（测试以目录 hash 前后一致断言）。
- **恢复写入只能由 `WritableSession` 触发**：future-schema/损坏工程在
  `open` 即失败，不可能"边恢复边半写"。
- `RecoveryReportV1` 三分类：`continued`（续传至成功）/ `rolled_back`
  （回滚，payload 移除、journal 保留为证据并标记 `rolled_back`）/
  `pending`（无法自动裁决，journal 原样保留并**阻塞**冲突写入，等待
  操作决定；不静默、不伪造成功、不删除失败证据）。
- CLI：`pwb-inspect --project <f> --recover` 是运维恢复入口（显式可写），
  打印 RecoveryReportV1 JSON；只读工程上拒绝（exit 3）。

## 5. 单产物发布（v3 新增）

```cpp
struct PublishRequestV1 {          // pwb/data/commit_coordinator.hpp
    domain::OperationId operation_id;   // 发布幂等键（独立于 run_id）
    domain::RunId run_id;               // 须存在且 status=="running"
    std::optional<domain::AssetId> target_asset_id;  // 空=新建结果资产
    std::string new_asset_name, new_asset_type;      // 新建时必填
    domain::DataStage stage;
    std::vector<StagedAssetV1> products;  // **必须恰好 1 个**
    domain::Json result_metadata;          // 原样存入 version.metadata
    std::optional<domain::LayerId> rebind_layer;
};
```

- **零/多产物在任何写入前拒绝**：`products.size() != 1` →
  `invalid_argument`（诊断 `publish_requires_single_product`，携带实际
  数量），journal、payload、SQLite、工程文件均不动。通用多产物原子
  发布本轮**不做**（见 v3-verification 未迁移清单）。
- **允许新建结果资产**：`target_asset_id` 为空时 B 生成新 `asset_` id，
  在同一 SQLite 事务里落 资产行+版本行+lineage+current 指针+run_outputs
  （Python `register_result_asset` 的"无零版本窗口"语义）。调用方不需要
  预造目标资产。
- 版本 lineage：`parent_version_ids = run.input_version_ids`；
  `version.run_id = run_id`；`version.metadata = result_metadata` 原样。
- **禁止**对已 `complete` 或已有输出的 run 再次发布（`conflict`，
  单任务单结果 volume）；对 `failed/cancelled` run 发布 → `conflict`。

### 记录字段映射（provenance 完整性）

| 要求 | 落点 |
|---|---|
| 算法 ID/version/build | `run.generator`（"id@version+build"）+ `run.parameters` 原样 |
| 完整参数 | `run.parameters`（JSON，B 不解释；推荐键：`algorithm_id`/`algorithm_version`/`build_id`/`units`/`approximate`） |
| 输入 asset/version | `run.input_version_ids` + `run.input_ports`（entity_type/entity_id 可携带 asset 信息） |
| 单位/近似标记 | 调用方放 `result_metadata`（`units`/`approximate`），B 原样存 `version.metadata` |
| 时间 | `run.created_at`、`run.parameters.finished_at`、`version.created_at` |
| lineage | `lineage` 表（parent→child）+ `run_inputs`/`run_outputs` + `versions.parent_ids` |

### 结果保留语义（A/D 消费边界）

B 负责**字节与事务**：payload 文件落在
`{stage}/{asset}/{version}/`，hash/size 入库，版本不可变、不覆盖旧资产。
数值产物的**编码/解码归 A**：`result_metadata` 与 payload 内容 B 一律
不解析。消费端取用：`pwb-inspect --provenance <version_id>` 输出

```json
{ "version": {...行投影+metadata...},
  "file": {"path": "<相对工程>", "sha256": "...", "size_bytes": N},
  "run": {...完整 run 行...},
  "lineage": {"parents": ["ver_..."], "inputs": [...], "algorithm": "..."} }
```

## 6. journal 阶段序（run_publish）

`write_journal` → `stage_payload` → `catalog_commit`（资产行?+版本行+
lineage+指针+run_outputs，run 仍 running）→ `project_save`（rebind+工程
原子替换）→ `rebound` → **`run_complete`**（run→complete+finished_at，
单事务）→ `complete` → `clean_up`。

每个 durable 阶段后故障（进程真死或 fault hook）→ 新进程
`WritableSession::recover()`：

| 崩溃时 journal 相位 | 恢复结果 |
|---|---|
| written | `rolled_back`（无 durable 副作用；run 仍 running，可重发或 finish_run） |
| payload_staged | 续传 catalog→…→complete（成功）或 `pending` |
| catalog_committed / project_saved / rebound | 补工程保存（若未达）→ run 终态 → `continued` |
| run_completed | 落 completed 标记 → `continued` |

编辑提交（edit_commit）的相位与恢复语义同 v1，未变更。

## 7. CLI 退出码（v3 增补）

`pwb-inspect`（默认只读）：`--project`（必需）；新增
`--asset <id>` / `--version <id>` / `--run <id>` / `--provenance <version_id>`
（输出 JSON，任何查询不写盘）；`--recover`（显式可写恢复，输出
RecoveryReportV1 JSON）。退出码：0 正常；2 用法错误；3 工程不可读/损坏/
只读工程上请求恢复；4 future schema（诊断仍输出）；5 内部错误；
**6 恢复后仍有 pending journal**（报告 JSON 中列出）。

`pwb-migrate` 契约不变（§8 v1）。

## 8. Python oracle 对账边界（如实申报）

- v1 `data.oracle_compare` 实际对账表（11）：`assets`、`versions`、
  `runs`、`tags`、`asset_tags`、`version_tags`、`version_members`、
  `working_copies`、`run_inputs`、`run_outputs`、`run_ports`。
- **未对账**（读侧亦无 C++ 模型，不得声称已全量对账）：`lineage`、
  `models`、`model_versions`、`sync_state`、`staging_leases`、`name_search`。
- v3 新增 `data.oracle_readback`：C++ 在隔离副本上完成
  提交+登记+发布后，由固定 Python 解释器只读重开（项目 pydantic 模型 +
  `sqlite3` mode=ro），断言新增版本/run/binding/lineage 与
  `finished_at`/参数/单位元数据完整；读取前后副本 hash 不变；原
  fixture 目录不动。
- `catalog.json` checkpoint：Python 规范路径（SQLite canonical）只读重开
  **不读** manifest（仅损坏重建/legacy 迁移时用）。C++ 写路径不刷新
  `catalog.json`，以 `data.oracle_readback` 作为兼容性证明；差异与理由
  记录在 v3-verification.md。

## 9. 构建与依赖（不变 + 增补）

`cmake -S libs/data_suite -B build/cpp-data -DBUILD_TESTING=ON`；
`Pwb::Domain/Project/Workspace/Catalog/Data` + `pwb-inspect/pwb-migrate`
+ 新增 example 目标 `pwb-data-loop`（A 线消费样例）。
C++20，无 Qt/QGIS/Python 链接；vendored 依赖仅在
`libs/data_suite/third_party/`。测试名前缀 `data.`；`data.*` 非零且
零失败/skip 为门禁。`data.oracle_readback` 需要 `python3 + pydantic`
（configure 时 fail-closed 探测，缺失即 FATAL_ERROR，不静默跳过）。
