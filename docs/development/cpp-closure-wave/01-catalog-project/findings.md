# 01 线 findings — 盘点与证据（R0）

更新：2026-09-19（R0）。候选 SHA：`06211541ae1ccce22b0d5ba9258ce722170ca98b`（origin/main，fetch 后核实）。

## F-1 平台支持
- `/goal`、`/goal-loop` 不存在（技能清单+插件缓存已查）。→ 文件持久化循环（task_plan.md 记录）。

## F-2 缺口定位（以当前代码为准，非旧计划）
1. **Transaction::commit 吞错（#1398 ledger 遗留披露，任务书要求核实——已实锤）**
   `libs/catalog/src/sqlite.cpp`：
   - `Database::commit()` = `execute("COMMIT")` 但返回 `void`，`execute` 的 `DataError` 返回值被丢弃；
   - `Transaction::commit()` 随后无条件 `committed_ = true` → COMMIT 失败（SQLITE_BUSY/
     SQLITE_FULL/短写）时：错误不可见 + 析构不再回滚（事务状态误判）。
   - 影响 `apply_changes`/`repository` 各事务写入路径的错误通道完整性。
2. **无具体 CatalogServiceApi 适配器**：`libs/ui_controllers/include/pwb/ui_controllers/catalog_api.hpp`
   头注明确"concrete adapter lands with the catalog-service slice"。全仓 grep 仅 fake
   （ui_review tests、ui_controllers_tests）。04 数据页/09 审核无真实服务可绑。
3. **无资产变化订阅**：任何 seam 均未定义（本线新增语义，01 拥有）。
4. **workspace 未接线**：`docs/development/cpp-migration-inventory.md`：workspace =
   `native_no_python_origin`、wiring `not wired`。libs/workspace 本身已实现（codec+mutations），
   接线缺口在 composition root（12 面）——本线在 adapter/e2e 中证明其可消费（mutations 已由
   data.workspace_codec / lifecycle_ops 测试覆盖），不抢 12 的全局装配。
5. **project 版本模型**：CONV-33 轮1 已前置 `libs/project/version_models.hpp`（02 线消费），
   本线不动其语义，仅保证工程身份在 adapter 暴露面不丢。

## F-3 可复用底座（不重写）
- `CatalogServiceCore`（open R3 健康矩阵、save/batch、#411/#1220 CAS、maps 维护）。
- `CatalogRepository`（v5 schema、revision、WC registry、staging lease、import_raw/
  commit/promote/publish/finish_run 单事务、manifest L1-L5、write_all/rebuild）。
- `working_copy.hpp`（create/discard/recover/commit 编排 + StagingLeaseGuard）。
- `trash_service.hpp`（SaveHook 两阶段回滚）、`tags.hpp`（TagStore 日志回滚）、
  `sources.hpp`（missing/relink）、`queries.hpp`（search_assets_scan/find_*_by_tag/
  verify_integrity）、`queries_sql.hpp`（惰性读+8 查询）、`document_index.hpp`、
  `resolve.hpp`（七梯解析）、`gc.hpp`、`v11_bundle.hpp`、`model_registry.hpp`、
  `asset_metadata.hpp`、`legacy_migration.hpp`。
- `ProjectManager`（v6 恢复决策表、三段保存、#411/#1229 stale guard）。

## F-4 消费面契约（适配器必须同时满足）
- `ui_data_core::CatalogReadService`（document/get_asset/list_versions/list_assets/
  resolve_path/get_lineage/lineage_summaries/mutation_serial）——04 数据页 enricher 直接复用。
- `ui_controllers::CatalogServiceApi extends CatalogReadService`（trash/restore/create_derived/
  materialize/WC checkout+commit/promote/tags/runs/verify/维护面/close；方法"raise"语义 =
  抛 `domain::DataException`）。
- `ui_controllers::CatalogPortApi` + `CatalogRuntimeApi` 函数袋（ProjectControllerCore 唯一
  catalog 入口；未设置 = 诚实不可用降级）。
- `ui_review::ICatalogApi`（optional/DataError 双通道，no-throw）。
- **签名冲突**：`get_version(const std::string&)` 在 CatalogServiceApi（值返回+throw）与
  ICatalogApi（optional 返回）不兼容单类多继承 → 拆两个类，`ReviewCatalogApi` 持适配器指针。

## F-5 Python 产品链路（oracle 参考）
`ui/project_controller.py`：open_project_path → ProjectManager.load →
DataCatalogService.open(lazy) → （数据页查询/导入 import_raw L2055 → EditSession
checkout/commit）→ save_project → close。C++ 对应：ProjectControllerCore（Qt-free，
已实现）+ 本线适配器。warm/recover/migrate/sweep/ensure_index/repair_ghost/
migrate_run_ports/rebase 维护序列见 `libs/ui_controllers/src/project_controller.cpp`。

## F-6 构建与资源约定（已核实真实脚本参数）
- `scripts/cpp-migration/invoke-resource-gate.sh`：`{Probe|Configure|Build|Test|Exec}`
  `-s SRC -b BUILD -c CONF -t 'a;b' -a args -r regex -m MinFreeGiB(8) -j Jobs(2,1..8) -M 45`
  ；flock common git dir 互斥；退出码 0/1/64/75/77/124。
- `docs/development/cpp-building-and-verification.md`：默认 j2、硬上限 8（本任务书压到 j4）；
  CMAKE_BUILD_PARALLEL_LEVEL≤4、CTEST_PARALLEL_LEVEL≤2；本机无 cmake 的先例（#1398 用
  g++ 直连）——本线优先资源门+CTest，失败时如实降级并披露。
- 测试注册：`tests/cpp/data/CMakeLists.txt` 的 `pwb_data_test(target src ctest_name)`，
  链 `Pwb::Data Pwb::Catalog Pwb::Project Pwb::Workspace Pwb::Domain`；框架自研
  `pwb_test.hpp`（PWB_TEST_ASSERT）。

## F-7 已扣除的他线在途
- 05 线已登记（well/crosswell）；02（workflow）、12（组合根）、13（缺陷）、14（性能）
  尚未登记文件。无开放 PR（gh pr list 为空）。A/B/C（#1404/#1400/#1402）当时未合入——
  本基线 origin/main 已含其合并（git log viz-* 主题），无 WIP 复制。
