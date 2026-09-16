# CPP-B 数据/工程线 — Baseline（B0）

- 分支：`feat/cpp-data-project`（worktree `C:/Users/wangj.KEVIN/projects/paleo-workbench-cpp-data`）
- 基线：`cpp-migration-plan-v1` = `d0347da2`（已验证为祖先：`git merge-base --is-ancestor` 通过）
- 状态日期：2026-09-16（Asia/Shanghai）
- 上游重叠审计：基线即 `main` 头（d0347da2），远端无新提交、无开放 PR/issue 与数据线重叠（#1310 V13 已合并入基线，本线是它的 C++ 移植而非重做）。

## 1. 本线范围（Prompt B / 总设计 P0+P2+P3 持久化侧 / CPP-201..209、CPP-309、CPP-601/602）

交付 C++20 数据内核：`.paleo.json` 与 V13 `catalog.sqlite` 的兼容读写、workspace 语义、
CommitCoordinator（journal + 恢复）、`pwb-inspect` / `pwb-migrate` CLI、`Pwb::Data` 公共接口。

**不做**：QGIS/GDAL/PROJ/well-log-engine 构建；Qt 依赖；顶层 CMake/UI/算法（A/C 归属）。

## 2. 权威语义来源（已逐文件核对，非照抄旧注释）

| 领域 | Python 权威 | 关键结论 |
|---|---|---|
| 工程文件 | `paleo_workbench/project/models.py` + `manager.py` | `<name>.paleo.json`；`schema_version=1` 默认（WorkArea v2 为内存迁移，写回仍按模型字段全集）；顶层 `extra="allow"`（未知顶层节 round-trip #1170）；`json.dumps(ensure_ascii=False, indent=2)`；原子写：tmp+fsync → main→`.bak` → tmp→main → dir fsync；恢复：FileNotFound/损坏 → 校验 `.bak` → 隔离 `*.corrupt-<ts>` → 恢复，全部记录进 `meta.last_recovery` |
| 路径 | `project/paths.py` | `project_dir_for` = resolve 后父目录；5 个路径节（resources/export_artifacts/paleomap_documents.reference_layers/factor_map_tasks.grid_artifact_path/horizon_interpretations.artifact_path）保存时 relativize（项目内→POSIX 相对 + external=False；项目外→绝对 + external=True），加载时 resolve（相对路径逃逸项目根 → `ProjectPathError`）；`meta.project_root` 持久化为 `"."` |
| 目录存储 | `catalog/db.py` + `storage.py` + `store.py` | **SQLite 为 canonical**（`<proj>.artifacts/metadata/catalog.sqlite`，STORE_SCHEMA_VERSION=5，WAL，busy_timeout 5000）；`catalog.json` 是 checkpoint 清单（原子写 + `.bak`）；models.py 中“JSON canonical”注释已过时（V13 00-baseline 明确推翻，#1027） |
| 目录模型 | `catalog/models.py` | DataAsset/DataVersion/DataRun/RunPort/VersionMember/Tag/Model/ModelVersion；stage 词表 raw/derived/intermediate/output；版本不可变（重 id → `ImmutableVersionError`） |
| 落盘布局 | `catalog/storage.py` | `<proj>.artifacts/{raw,derived,intermediate,outputs,working,metadata,trash,blobs}`；managed 版本 path = 项目相对 POSIX `{stage}/{asset_id}/{version_id}/{filename}`；id 安全约束 `[A-Za-z0-9._-]` 且非点开头；RAW payload chmod 只读 |
| 提交协议 | `catalog/service.py` register_version/commit_working_copy | 版本号 commit 时分配（并发顺序化）；payload 拷贝+hash 在锁外 + staging lease；失败回滚（payload/版本/current 指针/run 输出）；working copy 状态机 checked_out→dirty→committing→(committed 删行)，crash 恢复探测 committing 行 |
| workspace | `mapping_workspace/stage_state.py` | dict 7 键：schema_version=1/current_stage/stage_states{stage→8键}/memberships{layer_id→10键}/tree/artifact_maturity/compilation_input_set；未知值回落（role→LEGACY_UNCLASSIFIED、stage→FACIES_CALIBRATION），binding_kind 空=UNKNOWN 不伪造 |
| ID/时间 | `project/models.py` | `{prefix}_{uuid4hex12}`；ISO8601 UTC `datetime.now(timezone.utc).isoformat()` |

## 3. SQLite schema v5（与 db.py 逐列核对）

表：`assets`(12列+name_search)、`versions`(15列, parent_ids JSON数组)、`tags`、`asset_tags`、`version_tags`、
`runs`(8列, model_ref JSON)、`run_inputs`、`run_outputs`、`lineage`、`models`、`model_versions`、
`sync_state`(key/value)、`staging_leases`、`working_copies`、`run_ports`(V11 typed lineage)、`version_members`(V11 bundle)。
`sync_state` 键：`schema_version`(=1)、`index_schema_version`(=5)、`catalog_revision`(int)、`manifest_mtime_ns`。
外键：无（刻意的投影设计，删除顺序 `_DELETE_ORDER` 子表先行）。upsert 用 ON CONFLICT DO UPDATE（保 rowid 顺序）。

## 4. 环境与资源

- 工具链：VS2022 Community MSVC 14.38.33130；CMake/Ninja 用 VS 自带
  （`Common7/IDE/CommonExtensions/Microsoft/CMake/{CMake,Ninja}/bin`）；经 `vcvars64.bat` 进入环境。
- Python oracle：主仓 `.venv`（3.12.13）**只读**复用；不 pip install。
- 依赖（vendored 入 `libs/data_suite/third_party/`）：
  SQLite amalgamation 3.45.1（Public Domain，sqlite.org 官方 zip）；
  nlohmann/json 3.12.0 单头（MIT，取自仓内 `third_party/qgis/external/nlohmann` 同源副本）。
- 资源门禁：`scripts/cpp-migration/Invoke-ResourceGate.ps1`（共享文件锁 + ≥8 GiB 可用内存 + 2 jobs）。
  B-1 轮 Probe = 4.31 GiB → exit 75：先做纯源码/文档工作，编译待内存达标后重探。

## 5. 旧业务字段的诚实边界（第一轮）

- 已验证语义：上表全部（读+写 round-trip 与 Python oracle 对比）。
- lossless-pass-through：`.paleo.json` 中业务负载（well_tables.rows、constraint 线坐标、
  paleomap_documents 的 facies/line/label features、user_vector_layers.features、QGIS XML 信封、
  joint_analysis、geo3d_workspace、integrated_interpretations 等）作为**类型化容器 + 原样字节级保留**处理；
  本线不解释其业务含义（算法/viewer 属 C，QGIS 呈现属 A）。
- 不宣称：全部 Python 业务已迁移；catalog 的高级服务（GC、dedup、impact、entity views）
  第一轮只实现读侧一致性检查 + 提交写路径所需的子集。
