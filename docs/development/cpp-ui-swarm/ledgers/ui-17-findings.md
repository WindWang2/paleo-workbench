# UI-17 W5 integration — MainWindow/AppContext 接线 findings

## 范围（任务书 W5）

`apps/paleo_workbench_platform` 组合根：`MainWindow::buildUi` 在全部 UI 片
target 齐备时以 `AppShell`（新增 `app_shell.hpp/.cpp`）为中央控件——
WorkstationFrame + CompositeDocument（宿主注入会话 QGIS 画布）+ 5 hub 页栈
（dock `hub` 内 HubScrollArea）+ CommandPalette + StatusBar + 快捷键注册表。
全部 UI target 缺席时保持原直连画布壳（诚实降级，非半成品）。

## 关键决策

| 决策 | 内容 |
|---|---|
| CMake 求值位置 | UI-17 块在根 `CMakeLists.txt` 全部 `libs/ui_*` add_subdirectory **之后**——`apps/` 先挂载，`if(TARGET …)` 提前求值会假阴性 |
| 页注册表 | 5 hub：数据(项目概述+数据管理)/井(测井预测+层序格架+地层对比)/地震(地震预测+井震3D)/编图(编图画布+数据制备+成图审核)/可视化(flat) — Python `app_shell.py` 组合对等 |
| deferred 诚实登记 | `DataPage`/`PreparationPage` 实现未交付 → `DataWorkspace` 承载管理面 + `PagePlaceholder`；joint engine host 缺 → `UnavailableJointHost` stub（`has_scene=false`，页面自渲染不可用面）；`IReviewActions` 缺 → provider 返回 nullptr（页面 "未绑定工程" 守卫）；解析注册表 preview seam 缺 → `LocalVizProvider` base_builder 回 message 态 |
| 状态条 | `AppShell::status_bar()` 挂 `MainWindow::statusBar()`（`addWidget(w,1)`），无顶层宿主时 shell 自带底部条（Python parity） |
| 画布注入 | `install_canvas(canvas_, uses_native_stack)` → `CompositeDocument::set_canvas`；`QgsMapCanvas` 的 `xyCoordinates`/`extentsChanged` 经 duck-type 连接喂文档状态槽 |

## 接线信号面（MainWindow::wire_app_shell）

`status_message`/`about_requested`/`new_project_requested`/`open_project_requested`
（数据集成存在时）直绑；`theme_requested`/`density_requested` 经
`theme_from_string`/`density_from_string` → `ThemeService`；
`workspace_preset_requested` → `apply_layout_preset`；`save_project_requested`/
`open_sample_project_requested`/`properties_requested`/`preview_settings_requested`
**deferred**（无对应宿主动作，如实登记）。

## 修复记录（接线暴露的存量缺陷）

| 文件 | 问题 | 修复 |
|---|---|---|
| `libs/ui_seqviz/CMakeLists.txt` | agent 产出的 5 个 `src/qt/*.cpp` 未入 target | `correlation_page`/`preview_controller`/`visualization_page`/`viz_workspace` 入库（+`Pwb::UiWorkers`/`Pwb::UiDataCore` 链接）；`composition_panel.cpp` 引用不存在的 mapping_document API（40+ 错），**登记 deferred** |
| `visualization_page.hpp:85` | `preview_provider = {}` 默认实参非法（`PreviewProvider` 无默认构造，ctor 被使用时才诊断——UI-10 自身 TU 不调用所以未炸） | provider 改必填参 |
| `correlation_page.hpp` | 前置声明缺 `QScrollArea`/`QSpinBox` → 成员 `class X*` 在命名空间内造遮蔽类 | 补进全局前置块 |
| `correlation_page.cpp` | 成员 `probe_engine()` 遮蔽自由函数；`ProgressFn` 已演化为 `(double, QString)` | `ui_seqviz::probe_engine` 限定 + done/total 经 `input.on_progress` 邮箱→GUI hop |
| `shortcut_registry.hpp` | 全局注册表持悬垂 `QShortcut*`（上个 shell 销毁后），重注册 `deleteLater` SIGSEGV（`platform.qgis_smoke_app` 捕获） | `shortcuts_` 改 `QPointer<QShortcut>` |
| `command_palette.hpp` | `apply_filter` 私有 → 宿主无法预填 palette（Python parity） | 新增公有 `set_filter_text`（走 `textChanged`→`apply_filter` 自有链） |
| 根 `CMakeLists.txt` UI-17 门 | `MappingPage` 在 `Pwb::UiMapQgis`（QGIS-gated），门误检 `UiMapQt` | 门+链接改 `UiMapQgis` |

## 测试

- `platform.app_shell`（新增，`PWB_WITH_APP_SHELL=1` 编译真 MainWindow+AppShell）：
  中央控件=AppShell、5 hub 页栈、6 个 dock（hub/composite_*/facies/mapping_stage）
  存在、`navigate_to` 切 hub+submodule+dock 标题/显隐、越界导航忽略、palette
  popup/dismiss、页面实例齐全（含 unavailable-host 页面）、`shutdown_workers`
  幂等、**第二窗口生命周期**（QPointer 注册表重注册路径——正是原崩溃点）。
- 直连画布回退：其余 MainWindow 测试（ui_wiring/edit_cycle/lifecycle…）
  不定义 `PWB_WITH_APP_SHELL`，继续覆盖 reduced shell。

## 验证

- `pwb-platform --self-check`：12/12（含 `ui_shell — MainWindow + AppContext
  constructed/destroyed`），offscreen。
- 全量 ctest：见 §验证轮（linux-ninja，PALEO_QGIS_* 覆盖）。

## deferred 汇总（本片登记，非本波目标）

`data_page.cpp`、`preparation_page.cpp`、`composition_panel.cpp`、joint engine
host、`IReviewActions` 项目后端、解析注册表 preview base seam、`save/open_sample/
properties/preview_settings` 宿主动作、`CommandPalette` context_provider/
tool_details_provider（未注入）。
