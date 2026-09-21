# 01 — Overlap Audit（与当前 main / 并行 PR 的重叠矩阵）

执行时点：2026-09-20，基线 `412d8baf`（= origin/main HEAD）。

## Open PR：#1434（唯一）

范围（lease 视角，本线**禁止重复实现**）：issues #1339–#1345（workflow_graph 语义）、
#1357（curve_expr）、#1358（polygonization）、#1385（QGIS mirror/export 性能）、#1388（表格/过滤性能）、
#1392（卫生：strip 重复 + overlay provider `Json()`→`const Json&` 脏缓存）、#1427–#1431（CI 环境）。

### 文件级重叠矩阵（#1434 changed-files × 本线预计触点）

| 文件 | #1434 | 本线 | 处置 |
|---|---|---|---|
| `libs/ui_map/src/mapping_page.cpp` | 改（11 行增） | 改（shell 装配） | 本线只加具名块/新方法，不碰其 update_state/chrome 路径；rebase 时若有冲突以双方块拼接 |
| `libs/ui_map/src/map_chrome_painter.cpp`、`display_map_canvas.cpp`、`workarea_map_widget.cpp` | 改（perf） | 不改 | 避让 |
| `libs/ui_widgets/src/qgis/canvas_shim.cpp`、`mirror_snapshot.cpp` | 改（perf） | 不改 | 避让 |
| `libs/ui_data_core/**`、`libs/ui_pages_data/src/qt/data_asset_table.cpp` | 改（表格 perf） | 不改（PreparationPage 仅装配面） | 避让 |
| `tests/test_map_chrome.py` 等 pytest | 改 | 不改 Python 测试 | 避让 |
| `scripts/capture_workstation_screens.py` | 改 | 不改 | 避让 |
| 根 `CMakeLists.txt` | 不改 | 改（2 处既有 guard 修正 + ui_stageflow 一行挂载） | 无冲突 |

### 其他并行线（V14 wave，Prompt 1/3/4/5）

- Prompt 1（data fabric lineage）：worktree `paleo-workbench-v14-data-fabric-lineage` 已存在；
  属主 `libs/catalog/**`/data page 深层。本线不改 catalog schema。
- Prompt 3（QGIS layer tree/order）：本线不碰 `native/qgis_render_bridge/**`、layer ordering；
  图层面板只做容器布局与状态展示。
- Prompt 4（factor/constraint 数值核）：本线只做 presentation。
- Prompt 5（composition/export engine）：本线只放置入口与容器。
- 租约区：`.git/paleo-v14-parallel/leases/v14-three-stage-ux.json`（本线）。

## 与已合 main 的边界确认（不重建权威）

| 已有权威 | 本线态度 |
|---|---|
| `ProjectSession.mapping_stage_`（运行时 stage） | 唯一写入口仍是 `MainWindow::applyStageValue`；本线补「工程重开恢复」读路径，不建第二 stage 状态 |
| `mapping_workspace.current_stage`（工程持久化，workspace codec） | 本线让 ProjectSession 打开工程时从它恢复——弥合两处脱节，而非新增 |
| `tool_policy::kStageGroupVisibility` / `kStageActionWhitelist` | 面板可见性矩阵从它派生（projection），不自造第二套可见性真源 |
| `ui_shell::command_registry()` | 唯一命令真源；本线做生产注册（当前为空壳），不建第二注册表 |
| `SelectionBus`/`ViewCoordinationCore`（ui_controllers） | 唯一 selection 总线；本线在产品里实例化接线，不另造 bus |
| `WorkstationTaskCenter` | 唯一任务中心组件；本线注入 providers |
| `MapDocumentBank`/`MappingPage::update_state` | 唯一 hub3 文档数据链；本线补信号接线 |
| ThemeService/theme tokens | 唯一主题权威；本线只消费 + 补 QSS 选择器缺口 |

## 发现的 main 潜在 configure bug（本线带最小修复，均不与 #1434 重叠）

1. **UI-14-IMPLY 漏落 `PWB_BUILD_MAPPING_KERNEL`**：fresh `PLATFORM+DATA` configure（CONV-30
   默认开→DATA 开→UI-14 imply CONV_07）在 CONV-07 option block FATAL。预设显式传参掩盖了它。
   修复：UI-14-IMPLY 块补 `set(PWB_BUILD_MAPPING_KERNEL ON)`（CONV-26B 本会设置的开关）。
2. **`tests/cpp/well_crosswell` 挂载缺 WLE 守卫**：`VIZ-B(默认 ON)+DATA+BUILD_TESTING` 且无
   WLE viewer 闭合时，其第一条 fail-closed FATAL 中止 configure。修复：挂载条件补
   `AND TARGET Pwb::UiWorkersWleLoad`。

两处均为 1–3 行、带注释、不改任何语义面；Linux 全闭合构建（总是带 WLE/显式 kernel flag）不受影响。
