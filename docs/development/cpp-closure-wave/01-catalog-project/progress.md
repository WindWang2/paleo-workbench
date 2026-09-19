# 01 线 progress — 逐轮记录

每轮记录：候选 SHA、目标、范围差量、真实命令/退出码、测试数据、资源租约、发现/处理、下一步。

## R0 盘点轮 — 2026-09-19

- 候选 SHA：`06211541`（origin/main，`git fetch` 后 `git rev-parse` 核实；开放 PR 为空）。
- 目标：ledger 建立 + 缺口定位。范围差量：无代码改动。
- 已完成：
  - worktree `/home/kevin/project/worktrees/cpp-close-01-catalog-project`（分支
    `codex/cpp-close-01-catalog-project-20260919`），主工作区零接触。
  - 协调登记 `.git/codex-coordination/cpp-close-wave/task-01-catalog-project.md`（原子创建，
    未覆盖他线文件；05 线登记已存在并读取确认格式）。
  - Explore 子代理 1 次（agent_9353851c，163,539 tokens，累计 163,539 / 预算上限
    360,000,000）：ledger/文档/平台宿主/资源门/Python 链路盘点。
  - 缺口实锤：Transaction::commit 吞错（sqlite.cpp:419-427）；无 CatalogServiceApi 具体
    适配器；无资产变化订阅；workspace wiring not wired（composition root 属 12）。
- 资源租约：R0 无重构建，未占门。
- 下一步：R1 实现（sqlite 错误传播 → 适配器 → installer → 测试）。

## R1 实现轮 — 2026-09-19

- 候选 SHA：`06211541` + 本线改动（未提交前）。
- 实现内容（全部 Qt-free，编译级验证 -fsyntax-only 通过）：
  1. **Transaction 错误传播修复**（#1398 遗留，任务书点名核实）：
     `libs/catalog/include/pwb/catalog/sqlite.hpp` + `src/sqlite.cpp`：
     `Database::{begin_immediate,commit,rollback}` 返回 `DataError`；
     `Transaction::commit()` 仅在验证成功后置 committed_，失败保持事务打开由析构回滚；
     BEGIN 失败记录 `begin_error_` 并使 commit/rollback/析构安全空转。
     `repository.cpp` 23 处调用点：20 处传播错误、3 处簿记路径显式 swallow parity。
     回归语义（测试 case d）：嵌套 BEGIN 失败不再错误提交外层事务。
  2. **closure_catalog_service.{hpp,cpp}**（apps/paleo_workbench_platform）：
     CatalogClosureAdapter —— 同一对象实现 `ui_controllers::CatalogServiceApi` +
     `CatalogPortApi`，经继承覆盖 `ui_data_core::CatalogReadService`；
     `ReviewCatalogApi` 实现 `ui_review::ICatalogApi`（no-throw 通道；因
     get_version 双 seam 契约不同而拆类，friend 共享单写者锁）。
     组合语义逐条对齐 service.py：import_raw(2055)/link_external/create_derived(2645)/
     materialize_external(2208)/promote_version(3665，冻结 shape)/register_run(2734)/
     update_run_status(2770 终态守卫)/repair_ghost_runs(3780 #1219)/
     migrate_run_ports_persist/migrate_legacy_resources/rebase_artifact_paths(4538)。
     失败统一回滚：save 失败 → 移除新实体 + 恢复 current 指针 + 删除已放置载荷
     （is_cas_path blob 保护；工作副本移动回原位）。
     01 线新增语义：CatalogProjectIdentity（工程身份随事件携带）、
     CatalogChangeFeed（提交后事件订阅；失败事务零发布）、CatalogRecoveryReport
     （中断恢复用户报告）、search_assets（查询/筛选）、conflict_guidance()。
  3. **closure_catalog_install.{hpp,cpp}**：InstalledCatalogClosure +
     CatalogRuntimeApi 函数袋绑定（open_catalog 失败抛异常走控制器错误通道；
     全部 lambda 按 this 捕获避免重开后悬垂；lifecycle seams 留空 = 诚实不可用）。
  4. **CMake**：apps/paleo_workbench_platform/CMakeLists.txt 新
     `BEGIN cpp-close-01` 块（块内 option PWB_BUILD_CATALOG_CLOSURE，不动 12 的
     PwbFeatures.cmake；12 可原样提升）+ tests/cpp/data/CMakeLists.txt 注册
     `data_catalog_closure`（编译同一对 closure TU）。
  5. **测试** tests/cpp/data/catalog_closure_test.cpp（6 用例）：事务错误通道
     （嵌套 BEGIN 回归）、闭环（查询/筛选→导入→WC→提交→提升→关闭重开）、
     并发 revision 冲突+回滚无半成品、损坏库隔离重建/检查点短写 .bak 梯/
     只读目录诚实拒绝、中断恢复报告、变更订阅、ProjectControllerCore 生产链
     （真实 runtime bag + 真实 ProjectManager 保存 + 工程切换）。
  6. **用户文档** docs/specs/catalog-recovery-and-conflicts.md（中断恢复/冲突/
     损坏/只读/工程身份，中文用户视角）。
- 环境约束（如实记录）：本机无 cmake/ctest（与 #1398 披露一致）。验证通道 =
  `direct-build-01.sh`（g++ 直连，j2，对象级缓存；CMake 改动供 CI 复放），
  全程在 `invoke-resource-gate.sh Exec` 资源门内执行。
- 资源租约：13 线持有重型构建锁（pid 3866750，13+ 分钟，活跃），本线排队
  未抢占；门空闲后执行构建与测试。
- 子代理用量：累计 163,539 tokens（仅 R0 Explore）。
- 下一步：门内构建 + 三个受影响测试（closure/catalog_service/lifecycle_ops）×2。

## R3 独立审查轮 — 2026-09-19

- 审查者：general-purpose 子代理（agent_8df4f59f，只读审查 + /tmp 最小补丁实测；
  本会话第 2 个根级子代理，4,626,204 tokens；累计 4,789,743 / 360,000,000）。
- 结论：FIX_REQUIRED → 全部 P1/P2/P3 已修复：
  - P1-1 repository.cpp 三处类型错误（rebase→-1、acquire lease→nullopt、prune→-1；
    批量替换在返回 int/optional 的函数里漏了类型判断——审查者实机编译抓到，
    证明端到端验证不可省）。
  - P1-2 materialize_external / promote_version 回滚误删既有资产（remove_asset
    会连带全部版本）：plan.assets 置空，仅删新实体 + restore_current。
  - P1-3 测试 6 处断言失效：嵌套事务可见性改第二连接判定；mutation_serial
    跨会话归零改断言；冲突用例 B 视图为 0 资产；corrupt 用例改破坏文件头
    （确定性触发 isolate）；只读用例改 文件0444+目录0555 且 geteuid()==0 跳过
    （root 下 chmod 无效 → 如实标 SKIP，非全skip）；恢复用例先 close 适配器再
    直写 registry，避免 BEGIN IMMEDIATE 撞活 WAL 句柄。
  - P2-4 materialize_external run 输出链：run 存在校验（NotFound）+ 同保存内
    追加 output_version_ids + 回滚恢复原列表（Rollback.restore_run_outputs）。
  - P2-5 rebase_artifact_paths 补 model_versions[].artifact_uri 重写。
  - P3-6 import_raw legacy 桥仅在不与存活资产重复时绑定（service.py 2113 parity）。
  - P3-7 get_catalog_service/get_catalog 在 close 后返回 nullptr；
    install.hpp 注明 closure 必须先安家再 make_runtime（lambda 捕 this）。
  - P3-8 rollback_ 目录剪枝收敛为 Python parity 的两级；direct-build-01.sh
    去 job_bridge.cpp（Qt）、补 nlohmann shim include。
- 审查者独立实测记录：data_catalog_service oracle 套件 28/28 通过（验证
  Transaction 修复对冻结行为无回归）；其余 6 用例修复前失败清单已逐条对应修复。
- 待办：资源门空闲后跑 direct-build-01.sh（本轮修复后的复验）×2。

## R2 验证轮 — 2026-09-19（两轮门内执行）

- 资源门：`invoke-resource-gate.sh Exec`（共享 `.git/cpp-migration-heavy.lock`）。
  排队记录：13 线 Build → 14 线 Exec → 06 线 Build → 02 线 Exec 等先后持有；
  本线以 60s 退避循环排队，从未抢占、从未绕门。第一轮成功获取于第 60 次尝试。
- 构建：`direct-build-01.sh`（g++ 直连，j2，53 TU：catalog 32 + project 6 +
  workspace 2 + domain 3 + job_runtime 2（去 Qt bridge）+ ui_controllers 2 +
  data_suite 6 + closure 2 + sqlite3.c + 测试）。构建脚本自身的链接闭包迭代
  （fixture define、data_suite 面、job_bridge Qt 排除）均在门内完成。
- **第一轮结果（修复 legacy 守卫/只读场景前）**：
  - data_catalog_service **28/28 PASS**（oracle 逐字节回放，证明 Transaction
    修复零回归——独立审查者已在 /tmp 预先实测同一结论）
  - data_lifecycle_ops 6/6 PASS
  - data_catalog_closure 4/7（transaction 通道/冲突回滚/变更订阅/生产控制器链
    4 例 PASS；chain/readonly/reopen 3 例 FAIL）
- 失败根因分析（重要发现，已修复）：
  1. **service_core 双存储纪律**：`document()` 返回物化缓存；`add_*` 使缓存
     失效重建，但 `find_*` 纯读不失效；经节点指针的编辑若发生在一次缓存
     物化之后则永远不可见。import_raw/link_external 的 legacy 绑定原本在
     `document()` 扫描（触发物化）后才经 `added` 节点写入 → 永久丢失。
     修复：预加扫描 + 绑定写入本地 asset 后再 add。
  2. update_run_status / repair_ghost_runs / rebase_artifact_paths 的
     document() 编辑统一改为"编辑缓存 → `invalidate_maps()` 折叠 → save"
     （折叠次序错误会导致 save 的 map 查找读到旧 store 节点）。
  3. 只读场景设计误差：仅 chmod store 文件+根目录时，`.artifacts/metadata/`
     子目录仍可写，manifest 重建梯合法走通（这是设计行为不是缺陷）。修复：
     全树 chmod（文件 0444/目录 0555）关闭全部写 rung 后断言诚实拒绝；
     root 下 chmod 无效 → 显式 SKIP（环境不可能，非全 skip）。
  4. mutation_serial 是会话内计数，重开归零——删除跨重开断言。
- **第二轮结果（最终代码状态，第一遍）**：
  - data_catalog_closure **7/7 PASS**（exit 0）
  - data_lifecycle_ops **6/6 PASS**（exit 0）
  - data_catalog_service **28/28 PASS**（exit 0）
- **第三轮结果（第二遍确定性回归，同一代码状态）**：
  - data_catalog_closure **7/7 PASS**（exit 0）
  - data_lifecycle_ops **6/6 PASS**（exit 0）
  - data_catalog_service **28/28 PASS**（exit 0）
  两遍全绿，A11 满足。后续任何代码变化都重跑受影响集；无变化不机械重复。
- ON/OFF 闭包：本机无 cmake，无法真实 configure。如实记录：apps CMake 块为
  纯增量（option + TARGET 存在双守卫，OFF 时零源文件加入、零定义），直连
  构建已证明 closure TU 可独立编译；CMake ON/OFF configure 留给 CI 复放
  （标记：未执行）。
- 子代理用量：累计 4,789,743 / 360,000,000 tokens。
