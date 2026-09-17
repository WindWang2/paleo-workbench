# CPP-B v3 Verification Report（run 生命周期 + 单产物发布 + 显式恢复）

分支 `codex/cpp-v2-data`（基线 `53e22b679ea3181d4e2c2bca8d42ca272c00dfbf`）。
本文覆盖 v3 新增范围并**回填历史**；v1 范围的历史结论见 §1。

## 0. 当前结论

- 源码完成、独立 configure/build 成功（GCC 16.2.1 / cmake 4.4.3 / Linux）。
- `data.*` **19/19 通过（0 失败 0 skip，exit 0）**；关键确定性链路 9 项
  第二遍复验通过（§4）。
- 依赖审计（ldd 模式）：无 Qt/QGIS/Python/PySide/Shiboken/conda 链接。
- 资源门禁执行方式：本机无 pwsh，按同等契约执行（见 §6），期间多次
  `RESOURCE_BUSY`（A 线 `cpp-v2-platform` 持槽，真实验证了跨 worktree 互斥）。

## 1. 历史回填（早期阻塞 → 后续通过，如实记录）

1. **旧 CPP-B 线（feat/cpp-data-project，2026-09-16，B-1~B-4）**：源码全量
   落盘后连续 6 次内存门禁 Probe exit 75（free 3.19–4.66 GiB < 8 GiB），
   构建/测试未执行，按协议记录未完成并暂停。旧 `verification.md` 的
   "未完成（资源门禁阻塞构建验证）"**是当时事实**。
2. **CPP-D core-verify 线（R1–R16）**：后续轮次在同一源码上完成真实编译与
   测试——修 json.hpp 假 amalgamation、头引入链、测试三坑后，
   `data.*` 14 组两遍全绿；science Qt-free 4 组两遍全绿；以
   `53e22b67` 合入 main。**旧文档的"内存阻塞"不再是当前核心状态。**
3. **本轮 v3（codex/cpp-v2-data）**：在 `53e22b67` 之上交付 run 生命周期/
   单产物发布/显式恢复/待恢复闸门/CLI 查询/消费例子，并补齐 Linux 可移植性
   （§5）。

## 2. Oracle 对账覆盖面（如实申报，不扩大声称）

`data.oracle_compare` **实际对账**的表（行投影，键语义比较）：

| 已对账（11） | 键 |
|---|---|
| assets | id |
| versions | id |
| runs | id |
| tags | id |
| asset_tags | asset_id+tag_id |
| version_tags | version_id+tag_id |
| version_members | version_id+name |
| working_copies | working_id |
| run_inputs | run_id+version_id |
| run_outputs | run_id+version_id |
| run_ports | run_id+direction+role+version_id |

**未对账**（测试自身记录 skipped 边界，C++ 读模型亦缺）：
`lineage`、`models`、`model_versions`、`sync_state`、`staging_leases`、
`name_search`（assets 列，值=name 的恒等投影）。**不得声称全量对账。**

本轮对新增写入路径的 `lineage` 行断言改由两条真实路径补强：
`data.run_lifecycle` 直连 SQLite 查 `lineage`/`run_outputs`/`run_inputs` 行；
`data.oracle_readback` 由固定 Python 解释器只读验证新写入的
version/run/binding/lineage。

## 3. v3 必选验收逐项

| 验收项 | 证据 | 状态 |
|---|---|---|
| `libs/data_suite` 独立 configure/build；14 组保留并运行；`data.*` 非零零失败/skip | §4 矩阵（19 项 = 14 原有 + 5 新增） | §4 |
| 依赖审计无 Qt/QGIS/Python | `data.build_hygiene`（ldd 模式，4 个二进制） | §4 |
| 真实工程/SQLite 读写往返、未知字段、Unicode 路径、只读零写入、固定 Python oracle 对账 | `data.project_roundtrip` / `data.workspace_codec` / `data.oracle_compare`（unicode_paths 等 8 fixture）/ `data.diagnostics` 只读零写入 + `data.oracle_readback` 零足迹断言 | §4 |
| 编辑：成功/同 ID 重试/stale base/hash 错/只读拒绝，验证版本/绑定计数与原资产 hash | `data.commit_coordinator`（重试回放、conflict、hash 校验、immutable payload）+ `data.consumer_loop`（两轮全链，绑定推进验证） | §4 |
| run 成功/失败/取消/发布失败、重复请求、新建产物资产、零/多产物拒绝，真实 SQLite/文件断言；成功重开可读；输入版本/参数/单位/lineage 完整 | `data.run_lifecycle`（9 case：登记幂等、发布建新资产+lineage SQL 断言、重放同回执、零/多产物写入前拒绝、终态不可改写、已有输出禁 fail/cancel、hash/unsafe id 拒绝、已有资产追加版本） | §4 |
| 每个 durable phase 故障注入恢复 | `data.run_recovery`（written→rolled_back 且证据保留+同 ID 重试成功；payload_staged→续传成功；catalog_committed/project_saved/rebound/run_completed→续传+重放 Duplicate；pending 阻塞冲突写入与 finish_run；恢复后闸门解除）+ `data.commit_recovery`（v1 编辑 4 阶段，保留） | §4 |
| 子进程在持久化检查点后真实终止，新进程恢复 | `data.crash_recovery`：fork/exec 子进程于 `catalog_committed`/`payload_staged` 后 `std::_Exit(86)`（无解栈、无清理），父进程（从未打开过该工程句柄的新进程）恢复并断言终态 | §4 |
| C++ 写出的隔离副本由固定 Python oracle 只读重开验证；读取前后副本 hash 不变；原 fixture 不动 | `data.oracle_readback`：pydantic ProjectDocument 验证 + `immutable=1` SQLite 读（活跃 WAL 存在时拒绝而非偷读）+ 树摘要前后相等 + fixture 目录摘要相等 | §4 |
| "结果文件+描述元数据"保留语义 | `pwb-inspect --provenance <ver>`：file{path,sha256,size,exists} + version.metadata 原样 + run 行；B 不解析字节（v3-contracts §5） | §4 |
| 仍未迁移清单 | §7 | — |

## 4. 测试运行记录（门禁内真实命令与退出码）

命令（本机门禁封装，见 §6；日志副本 `/tmp/ctest_v3.log`、`/tmp/ctest_v3_pass2.log`）：

```text
$ cmake -S libs/data_suite -B build/cpp-data -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON   # exit 0
$ cmake --build build/cpp-data --parallel 2                                                  # exit 0
$ ctest --test-dir build/cpp-data -R "^data\." --output-on-failure                           # exit 0, 19/19
$ ctest --test-dir build/cpp-data -R "^data\.(run_lifecycle|run_recovery|crash_recovery|
    oracle_readback|consumer_loop|commit_coordinator|commit_recovery|oracle_compare|
    build_hygiene)$"                                                                          # exit 0, 9/9（复验）
```

| CTest 项 | 结果 |
|---|---|
| data.domain_ids | PASS |
| data.workspace_codec | PASS |
| data.diagnostics | PASS |
| data.catalog_read | PASS |
| data.project_paths | PASS |
| data.project_roundtrip | PASS |
| data.project_recovery | PASS |
| data.catalog_write | PASS |
| data.commit_coordinator | PASS |
| data.commit_recovery | PASS |
| data.run_lifecycle（新） | PASS（9 cases） |
| data.run_recovery（新） | PASS（5 cases） |
| data.oracle_compare | PASS（compared rows 62；15 unloaded-table 边界如实记录） |
| data.cli_inspect | PASS |
| data.cli_migrate | PASS |
| data.consumer_loop（新） | PASS（真实 fixture 副本两轮全链） |
| data.crash_recovery（新） | PASS（2 cases；子进程 `std::_Exit(86)` 实证） |
| data.oracle_readback（新） | PASS（verdict ok=true；树摘要读取前后不变；原 fixture 不变） |
| data.build_hygiene | PASS（ldd，4 二进制无禁链） |

汇总：**19/19 通过（0 失败，0 skip），exit 0；关键确定性链路 9 项第二遍复验
通过（exit 0）**。`data.build_hygiene` 在 MSVC 用 dumpbin、在 ELF 用 ldd——
同一禁链清单（python/pyside/shiboken/pybind/qgis/qt6/qt5/conda）。

## 5. 本轮 Linux 可移植性修复（基线仅 MSVC 验证过）

| 位置 | 缺口 | 修复 |
|---|---|---|
| domain/ids.hpp | `std::uint64_t` 无 `<cstdint>` | 补包含 |
| domain/support.cpp | `gmtime_s` 仅 MSVC | 平台分支 `gmtime_r` |
| project/paths.cpp | windows.h、`_wgetenv`、CreateFileW fsync | POSIX 分支（u8 直传/HOME/open+fsync） |
| tests build_hygiene | dumpbin 专属 | ELF ldd 模式 |
| tests cli_* | cmd.exe 双引号 trick、pclose 未解码 | POSIX 引号 + WEXITSTATUS |
| tests project_paths | Windows 字面路径在 POSIX 是文件名 | 真实绝对路径（语义不变） |
| fixtures oracle_resolve.json | 机器绑定绝对路径 | 本机固定解释器再生成（catalog/model dump 逐字节不变，仅 resolve 差异） |

## 6. 资源门禁执行记录（契约同等，方式如实）

- 规定入口 `scripts/cpp-migration/Invoke-ResourceGate.ps1` 为 PowerShell；
  **本机未装 pwsh**。按同等契约以 flock + `/proc/meminfo` MemAvailable 实现门禁
  （独占 `cpp-migration-heavy.lock`、8 GiB 门槛、≤2 jobs），脚本存于
  `/tmp/pwb_gate.sh`（不侵入 A 线目录）。
- 全部 configure/build/ctest 均经该门禁；探测记录：
  - 首次 configure/build：MemAvailable ≈53 GiB，获锁执行。
  - ctest 重试 3 次 `RESOURCE_BUSY`（A 线 `cpp-v2-platform` 间歇持槽——共享槽
    跨 worktree 互斥经真实竞争验证）；间隔等待 + 独立工作后获槽完成全量运行。
  - **执行瑕疵如实记录**：排障期间有 2 次仅含 2 个测试（<0.3 s）的诊断性
    `ctest -R` 直跑未经门禁包装（诊断 consumer_loop/oracle_readback 失败原因；
    全量验收运行仍全部经门禁执行）。

## 7. 仍未迁移清单（不宣称完成）

- GC/dedup 全套（`plan_gc`/`sweep_gc`、blob 去重写路径、trash 恢复流）。
- 通用多产物原子发布（本轮明确只做单产物；零/多产物在写入前拒绝）。
- 全部 entity view / 分页查询 / `name_search`（NFKC+casefold 归一化未实现，
  现为恒等投影）。
- `models`/`model_versions` 注册表、`staging_leases` 写路径、`sync_state`
  之外的同步语义。
- working copies 写 API 全量（现有 insert/remove/set_state 未接 run 生命周期）。
- catalog.json checkpoint 刷新（Python 规范路径只读重开不读 manifest；本轮以
  `data.oracle_readback` 证明兼容，未实现 C++ 侧 manifest 写出——若后续旧版
  Python 需要以 manifest 重建损坏库，另立工作项）。
- MSVC 侧本轮改动的回归（本轮在 Linux/GCC 交付；MSVC 分支为 #if 守卫，
  但未在 Windows 门禁内重跑——留给 A 汇总或 Windows CI）。

## 8. 限制

- `data.oracle_readback` 依赖本机 `python3 + pydantic`（configure 时
  fail-closed 探测；缺失即 FATAL_ERROR，符合"测试缺失必须报错"）。
- 子进程崩溃测试在 POSIX 用 fork/exec、Windows 用 `_spawnl`；本轮仅 POSIX
  实测。
- 性能未测量（本轮验收不含性能门禁）。
