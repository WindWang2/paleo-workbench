# CPP-B Integration Handoff（A/C 消费指南）

状态：首轮实现完成；构建/测试验收状态见 `verification.md`（如未通过构建门禁则如实标注）。

## 1. 构建

```text
cmake -S libs/data_suite -B build/cpp-data -DBUILD_TESTING=ON
cmake --build build/cpp-data --config Release        # ≤2 jobs（共享门禁）
ctest --test-dir build/cpp-data -R "^data\." --output-on-failure
```

- C++20 / MSVC 2022（14.38）+ VS 自带 CMake/Ninja；无 Qt/QGIS/Python 链接。
- 导出目标：`Pwb::Domain` `Pwb::Project` `Pwb::Workspace` `Pwb::Catalog` `Pwb::Data`。
- vendored：`libs/data_suite/third_party/{nlohmann/json.hpp@3.12.0(MIT),
  sqlite/sqlite3.{c,h}@3.45.1(Public Domain)}`。
- A 根构建接入：`PWB_BUILD_DATA=ON` 时 `add_subdirectory(libs/data_suite)`，
  target 名如上；模块亦可单独 add_subdirectory（`PWB_VENDOR_DIR` 缓存变量定位
  third_party，默认相对解析 `../data_suite/third_party`）。

## 2. A 如何消费（冻结契约）

头文件：`libs/data_suite/include/pwb/data/contracts.hpp`（跨 DLL ABI 第一轮
不冻结，见 01-parallel-development §"接口握手 v1"；先静态链接）。

```cpp
#include "pwb/data/facade.hpp"          // 只读快照
pwb::data::DataFacade facade(path_to_paleo_json);
auto snapshot = facade.open_snapshot();  // Result<ProjectSnapshotV1>
// snapshot->layer_bindings / workspace / resources / catalog_* / diagnostics

#include "pwb/data/commit_coordinator.hpp"   // 写路径（B 唯一 CommitCoordinator）
pwb::project::ProjectManager manager(path);
pwb::catalog::CatalogRepository repo(pwb::project::catalog_sqlite_for(path));
pwb::data::CommitCoordinator coordinator(
    manager, repo, pwb::data::DataFacade::journal_dir_for(path));
auto receipt = coordinator.commit(request, document);
```

- A 的编辑流：QGIS edit buffer → staged asset（落盘文件 + 可选 sha256）→
  `CommitRequestV1`。B 不接受 QgsFeature/QgsGeometry。
- `recover()` 必须在应用启动、任何新 commit 之前调用；返回
  continued/rolled_back/pending 三分类（pending 需用户决策，不静默）。
- 只读打开不写工程文件（含 future schema 降级只读 + 诊断）。

## 3. 工具

- `build/cpp-data/tools/pwb-inspect(.exe)`：只读审计，JSON 稳定输出；
  退出码 0/2/3/4/5（contracts §8）。
- `pwb-migrate`：默认预检；转换需 `--input`(副本) + `--output-dir`，
  拒绝输出=输入目录、拒绝覆盖既有目标；转换前备份 `.migrate-bak`。

## 4. Python oracle（fixture 再生成，主仓解释器只读）

```bash
PYTHONPATH=<worktree> <main>/.venv/Scripts/python.exe \
  tools/oracle/generate_fixtures.py --out tests/cpp/data/fixtures
for d in tests/cpp/data/fixtures/*/; do
  PYTHONPATH=<worktree> <main>/.venv/Scripts/python.exe \
    tools/oracle/dump_fixture.py --fixture "$d"
done
```

产物入库（含 `manifest.json` sha256 清单）。禁止向主仓 venv 安装任何包。

## 5. 已知边界（第一轮诚实清单）

- `name_search` 列以原样名称写入（未做 NFKC+casefold 折叠）——ASCII/中文
  fixture 等价，检索语义待 P2 补齐（Python #897 行为）。
- catalog 高级服务（GC/dedup blob 写入路径、impact、entity views、lazy warm）
  未实现——读侧审计 + 提交写路径子集已覆盖。
- CAS blob 布局识别（读 OK）；写路径不做 blob 注册（`register_blob`）。
- ProjectMeta 默认 version 常量 "0.2.17a0" 与 Python 基线一致，随 Python 版本
  演进需同步。
- 未知字段保留为 Python 的**超集**（schema-map §7 已记录差异）。
- 单进程会话语义：跨进程 stale-write 检测为内容 hash 级（#411/#1229 语义），
  无工程锁文件（P6 CPP-602 范围）。

## 6. 后续工作（P4/P6 对接）

- CommitCoordinator ↔ A 的 EditController 接线（EditDeltaV1→staged asset 由
  A 的 adapter 完成）；
- run 生命周期助手（manual_edit register/complete 的 C++ 对应 API）；
- `catalog.json` checkpoint 导出（close 时）目前未在 C++ 写路径实现（读侧
  支持）；
- C 层 IResultPublisherV1 的结果入库经同一 CommitRequestV1 协议。
