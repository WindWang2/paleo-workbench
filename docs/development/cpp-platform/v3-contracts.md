# CPP-A v3 接口契约（平台 + 最终集成）

> 状态：Frozen（v3 五线制；基线 `53e22b67`，分支 `codex/cpp-v2-platform`）
> 本文替代 v1 `01-contracts.md` 中已被实测推翻的部分；未提及项沿用 v1。
> C/D/E 消费本文 §1–§4；B 与 A 的互操作以 B 线 `docs/development/cpp-data/v3-contracts.md` 为准，A 的适配层实现见 §5。

## 1. ABI/SDK 契约（对 C/D 发布）

权威实测值见 `v3-runtime-manifest.md` §1–§2。要点：

1. **一个进程一个 Qt**。Linux 验证环境 Qt 6.11.2（系统包，vendored QGIS 4.2.0 的 NEEDED 即它）；Windows Qt 6.8.0 msvc2022_64 仍是计划值未实测。`PWB_QT_PREFIX` 实际约束 `find_package(Qt6)`：前缀前置 + `Qt6_DIR` 前缀校验，失败即 configure FATAL_ERROR。
2. QGIS SDK 只读消费 imported targets（`PwbQgis::Core/Gui/Analysis`）；平台是 QGIS SDK 唯一构建者，manifest 漂移才允许重建到本 worktree `build/qgis-vendor`。
3. C/D 不得向本进程引入第二个 Qt 来源（PySide/conda/自带前缀）。
4. 进程级 QGIS 生命周期：`QgsApplication`（非 QApplication）→ `QgisRuntime::acquire()`（恰好一次）→ … → `release()`（恰好一次）。`QgsProject` 一律 session-owned（`std::unique_ptr`），`QgsProject::instance()` 禁止出现在生产代码。

## 2. 平台公共 target（不变，实测可用）

| Target | 说明 |
|---|---|
| `Pwb::ToolPolicy` | Qt-free 评估器；golden 与 Python 28×77 全等（platform.toolpolicy_golden） |
| `Pwb::Qgis` | QgisRuntime/MapSession/LayerAdapter/EditController/LayoutService |
| `Pwb::Application` | ProjectSession 组合根 + B/C 适配器装配点 |
| `Pwb::Ui` | ToolActionSet（policy 结果 → QAction 投影；checked 判定提升 checkable） |
| `pwb-platform` | AUTOMOC 可执行；`--self-check` 退出码即判定 |

UI 契约（v3 新增，platform.ui_wiring 强制）：

- 菜单/工具栏/快捷键消费**同一批 QAction 对象**，enable/visible/checked 全部来自 `evaluate_all`（无第二规则源）。
- 每个 wired 动作必须真实连接处理器（`MainWindow::actionWired` 可审计）并加入工具栏。
- dirty-close 三态（保存/放弃/取消）与「保存失败不得销毁编辑」为强断言；生产用 QMessageBox，测试经 `setDirtyCloseResponder`/`setDiscardConfirmResponder` 注入。
- 动作↔语义映射（本轮 shell 词表限制）：打开矢量=`reference_import`、打开栅格=`layer_new`。两 id 的阶段语义（②/integrated_compilation 白名单）随之生效——这是有意的 policy 统一，不是绕过。

## 3. EditDeltaV1 / StagedAsset（对 B，v1 语义 + v3 事实修正）

- `EditDeltaV1.attribute_changes` 的键是**字段名**（QGIS 字段索引已在捕获层转换）。
- commit 拓扑门：GEOS 校验失败 → 会话保留可修复重试（edit_cycle 有 bowtie 断言）。
- `StagedAsset.geojson_path` 为 staged 目录内全量 GeoJSON；`sha256` 为该文件摘要；B 的 `CommitRequestV1` 直接消费。**commit 会持久化进隔离工作副本（本轮：测试/会话自建 GPKG）；平台不写用户源数据、不写 catalog。**

## 4. 对 C 的消费（v3）

- TaskRuntime `succeeded = 计算 + 发布双成功`、`publishing` 可观测、`shutdown()` 幂等 drain —— A 按其 v3-contracts §1 消费。
- `IResultPublisherV1` 适配器由 A 在 `libs/application/adapters/` 实现（见 §5），发布投递回主线程的 GUI 操作由 A 负责。
- WLE：按 C handoff §1.2 消费 install tree（`PWB_WELL_LOG_ENGINE_ROOT`）或 gitlink；A 不重建第二份 WLE。

## 5. A 的 B 适配层（v3 目标形态，进度见 v3-integration-verification）

```cpp
namespace pwb::application {
// IProjectStore 的 B 实现：pwb::data DataFacade/CommitCoordinator/WritableSession。
// ProjectSnapshotV1 ← B::open_snapshot()（零写入、诊断透传）
// commit(CommitRequestV1) → B::CommitCoordinator::commit()（operation_id 幂等、
//   pending journal → recovery_required 先显式恢复）
// IResultPublisher 的 B 实现：register_run → 产出 payload → publish_run_result；
//   失败/取消 → finish_run(Failed|Cancelled)；绝不发布 success。
}
```

- 跨域转换只放在 `libs/application`；数据库/跨文件事务只经 B。
- 结果产物：稳定描述（shape/轴/单位/布局）+ float32 payload 的单文件（B 的 publish 消费 staged 文件路径+hash）；最小验证格式带版本/边界，自带 reader，不冒充行业格式。
- 新操作新 operation_id；同操作重试复用原 id（B 幂等键语义）。

## 6. join key（不变）

`pwb/layer_id` / `pwb/version_id` / `pwb/asset_id` / `pwb/kind`（+ legacy `pwb/doc_id` 只读兼容）。领域 ID 是唯一连接键。

## 7. D/E 缺口处理（fail-closed）

`PWB_BUILD_SEISMIC_VIEWER` / `PWB_BUILD_SEISMIC_ATTRIBUTES` 开关存在且默认 OFF；置 ON 而 target 不存在（当前状态）→ configure FATAL_ERROR。禁止以测试替身冒充 D/E 生产模块。
