# UI-12 PR ledger — feat/cpp-ui-workstation-shell

Branch: `feat/cpp-ui-workstation-shell`（base `origin/main`，merge 至
`a9ed53ba`，含 UI-08/09/10/11）
Worktree: `../worktrees/cpp-ui-workstation-shell`
PR title: `feat(ui-workstation): UI-12 workstation shell — cores + Qt widgets`

## 权威输出

- Commit: `f8e09334`（54 files：1 根 CMakeLists 改 + libs/ui_workstation/**
  + ui-12-findings + .goal-loop-ledger 追加）
- PR: **#1397** — https://github.com/WindWang2/paleo-workbench/pull/1397
  （`gh pr create` 输出；base=main，head=feat/cpp-ui-workstation-shell）

## 交付物

`libs/ui_workstation/`（53 文件，~7.5k 行）：

- `Pwb::UiWorkstation`（STATIC，Qt-free，不链 Qt）— 13 TU：ui_context /
  mode_state / state_language / tool_surface / tool_help / action_help /
  explorer_spec / inspector_spec / task_projection / agent_plan /
  stage_actions / keybinding_intent / log_buffer。
- `Pwb::UiWorkstationQt`（STATIC，AUTOMOC，`TARGET Qt6::Widgets` 门控）—
  11 TU：ui_context_qt / mode_state_qt / app_bar / activity_rail /
  explorer_panel / inspector_panel / task_center / process_hub /
  agent_panel / keybinding_manager / workstation_frame。
- `ui_workstation_tests/`：core（26 case，headless）+
  qt_widgets_smoke（offscreen 构造 + dock 组合）。

根 `CMakeLists.txt`：UI-12 `add_subdirectory` 一行块（
`libs/ui_pages_mapedit` 后、`apps/` 前）；merge 保留全部 UI-08..11 块。

## 验证（linux-ninja preset，cmake 4.4.3 / ninja @ /tmp/pwb-oracle-venv）

- `cmake --build --target pwb_ui_workstation pwb_ui_workstation_qt` — link。
- `ctest -R ui_workstation` — **2/2 pass**（core 26/0 fail；smoke
  ~30 checks/0 fail，`QT_QPA_PLATFORM=offscreen` + `LD_LIBRARY_PATH`
  prepend `PALEO_QGIS_RUNTIME`）。
- QGIS SDK：主机兄弟 checkout 布局与 `PwbQgisSdk.cmake` 默认
  `<repo>/../main` 不符 → cache 覆盖 `PALEO_QGIS_{SOURCE,SDK,BUILD}_DIR`
  指向 `~/project/paleo-workbench`（文档化机制；首次失败 configure 的
  默认 cache 值须 `-D` 显式覆盖）。

## 构建期修缺（详见 ui-12-findings.md §修缺记录）

- `job_runtime::` → `pwb::job::` 命名空间（6 文件）。
- `requires` 变量撞 C++20 关键字 → `horizon_gated`。
- MD5 末位取位：`d>>24` 低半字节（hexdigest 末位，mod-8 parity）。
- 嵌入 QMainWindow：`Qt::Window` 自带 → `setWindowFlags(Qt::Widget)`。
- `TaskTableModel` ctor 定义、`<stdexcept>`/QLabel/QScrollBar include。
- 测试：context_text 签名对齐、首 refresh emit parity、frame.show()、
  smoke `LD_LIBRARY_PATH`。

## 终态

ported：shell/app_bar/activity_rail/explorer/inspector/task_center/
process_hub/tool_surface/ui_context/mode_state/state_language/
keybinding_manager/action_help/stage_actions/agent_panel（15/16）。
reused：`common.py` → `pwb/ui_widgets/icon_factory`（不重复移植）。
deferred：宿主 QSettings 持久化（ui_shell layout_persistence 域）、
面包屑/命令 palette 接线（host 集成片域）。
