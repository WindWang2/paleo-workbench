# UI-12 findings — workstation-shell（16 Python 源 → 13 核 + 11 壳）

Branch: `feat/cpp-ui-workstation-shell`（base `origin/main`，合并至
`a9ed53ba` — 含 UI-08 mapedit / UI-09 wellseis / UI-10 seqviz /
UI-11 review）。Worktree: `../worktrees/cpp-ui-workstation-shell`。
切片 UI-12 of the M10 UI→C++ migration：工作站组合壳 —— dock 宿主框
架、应用栏、活动轨、资源管理器、检查器、任务中心、进程/日志枢纽、
Agent 面板、键位管理、UIContext 与模式状态机、统一状态语言。UI-13
composite 页面不在本切片 —— 一律走注入 factory，缺省落
`PagePlaceholder`，绝不伪造面板。

## Scope ledger（Python source → semantics → C++ target → 终态）

| Python source | Semantics | C++ target | 终态 |
|---|---|---|---|
| `workstation/ui_context.py` | 权威事实聚合壳：43 字段快照、provider 注册（未知字段抛）、provider 异常 → honest unknown（fail-closed，stderr 留痕）、`_last` 起 None → 首 refresh 必发、同值静默、listener 异常吞没（死壳纪律） | `ui_context`（Qt-free：snapshot/field_kinds/provider 注册/refresh 变更检测）+ `ui_context_qt`（QObject 桥 `context_changed`） | ported |
| `workstation/mode_state.py` | 模式 FSM：idle/digitizing/adjusting/inspecting-qc/time-travelling；PanHeld/Released 为瞬态（不发信号）；travelling 中拒绝工具激活；EpochCommit 回 pre-travel 模式；Esc/QC 入出；hint 文案 | `mode_state`（Qt-free FSM）+ `mode_state_qt`（`mode_changed` 信号桥） | ported |
| `workstation/state_language.py` | 统一状态语言：glyph+label+tone；未知值 → 「·/未知/muted」honest token；未知类别 → throw（KeyError parity）；tone→badge 单向桥；workbench_context_text 段（阶段·编辑目标·后端·任务，空段 → 未打开工程/就绪） | `state_language` | ported |
| `workstation/tool_surface.py` | 工具面呈现适配：evaluate_all 直通（无第二门）、backend 三态（capability_mode 优先、桥布尔回退、皆无 → unknown 显式）、LayerCapabilitySnapshot → ToolContextSnapshot 扁平化 | `tool_surface` + `tool_help`（静态工具帮助注册表） | ported |
| `workstation/action_help.py` | explain/format_tooltip/format_details：走 canonical evaluator；未知工具 honest（label=id、requirements=未知工具）；无阶段 → legacy 文案 | `action_help` | ported |
| `workstation/explorer.py` | 树 spec：project/workspaces/data 模式；分组（井/地震体…）；行截断（cap+truncated tail）；footer 计数文案；navigation 节点；未开工程 → 未打开工程 | `explorer_spec`（Qt-free）+ `explorer_panel`（QTreeWidget 壳 + 复制/展开菜单） | ported |
| `workstation/inspector.py` | 检查器文档模型：feature/layer/未知 kind 分派；几何中文映射（面…）；是/否/缺失值；feature_assign 按钮；layer → style_edit 可见 + layer_id + `N 个要素` 摘要；空态单行 | `inspector_spec`（Qt-free）+ `inspector_panel`（壳） | ported |
| `workstation/task_center.py` | 双权威一行表：JobSnapshot + OperationRegistry 记录合并（submitted_at desc、stable_sort、cap 100）；状态文案（取消中 > 运行中 N%）、标题附失败前缀 40 字、elapsed `<60s→N s / else MM:SS`；菜单（取消/跳转/重试[registry 禁]/复制 ID/详情）；context 信号+轮询 | `task_projection`（Qt-free）+ `task_center`（QAbstractTableModel diff 壳 + delegate 取消按钮 + 详情对话框） | ported |
| `workstation/process_hub.py` | 进程/日志枢纽：有界 log buffer（FIFO drop）、`HH:MM:SS LEVEL   name: msg` 行格式、信号+轮询双排空、只读 viewer、console 诚实占位 | `log_buffer`（Qt-free）+ `process_hub`（`LogBridge` + viewer + `WorkstationConsolePane`） | ported |
| `workstation/agent_panel.py` | 计划→风险→WRITE 门：resolver/risk/executor 全注入 seam；未解析动作 fail-closed 记 WRITE；env 三元（PALEO_AGENT_ALLOW_WRITE / 显式覆盖 / 会话精确集合）；一次性确认对话框（无会话记忆 hook parity）；收据 id；迟到回调不死壳 | `agent_plan`（Qt-free：risk/write_actions/grants/allowed）+ `agent_panel`（壳 + grant dialog + `write_grant_changed`） | ported |
| `workstation/stage_actions.py` | 阶段动作表（dispatch dict 逐字含别名 run_factor→open_factor_workbench、stage_qc→run_qa）；_REQUIRES_HORIZON 门（先设层位，handler 不跑）；未知/未接入/失败三态诚实文案；facies 调色板 fallback（真 MD5 → int(hexdigest,16)%8 parity）、空白相集合 | `stage_actions`（Qt-free） | ported |
| `workstation/keybinding_manager.py` | 键位意图：Space 临时平移（press/release 成对、文本焦点先拒）；Tab 循环仅 digitizing/adjusting 域（idle 不抢焦点链）；Z/X 缩放无修饰（Ctrl+Z 不吞）；Esc 链（取消手势→结束洋葱→停工具→关 QC→FSM） | `keybinding_intent`（Qt-free 决策）+ `keybinding_manager`（eventFilter 壳 → host 回调） | ported |
| `workstation/shell.py` | dock 契约：QMainWindow 宿主嵌于 frame（**Qt::Widget 强制**——QMainWindow 构造器自带 Qt::Window，不重置则是隐藏顶层窗）；registry 逐描述符建 dock（pwbDockId 属性、Movable/Closable、can_float 门——GL 面禁浮）；topLevelChanged 浮动最小尺寸；面板 factory 注入 → PagePlaceholder；preset visibility 矩阵（不动用户尺寸）；inspector 视口 hysteresis（<1100 隐 / >1200 恢复至用户态）；用户手动切换 → preset 回 自定义 | `workstation_frame`（Qt 壳） | ported |
| `workstation/app_bar.py` | 全局栏：工程/工作区 preset/命令输入/Agent/任务/主题/密度/关于动作；命令输入 floor 随视口类 | `app_bar`（Qt 壳） | ported |
| `workstation/activity_rail.py` | 活动轨：模式切换 + 折叠请求（explorer 展开态回写） | `activity_rail`（Qt 壳） | ported |
| `workstation/common.py` | 图标染色（主题感知 SVG tint、DPR、缓存） | —（复用 `pwb/ui_widgets/icon_factory.hpp`） | reused |

## 结构

`libs/ui_workstation/`（两 target，同 ui_shell 先例）：

- **`pwb_ui_workstation`**（`Pwb::UiWorkstation`，STATIC，Qt-free，不链
  Qt）— 13 TU：`ui_context`、`mode_state`、`state_language`、
  `tool_surface`、`tool_help`、`action_help`、`explorer_spec`、
  `inspector_spec`、`task_projection`、`agent_plan`、`stage_actions`、
  `keybinding_intent`、`log_buffer`。PUBLIC 链 `Pwb::ToolPolicy` +
  `Pwb::UiShell`；`Pwb::Domain`/`UiWidgetsCore`/`Cartography`/`JobRuntime`
  按 TARGET 在场条件链。
- **`pwb_ui_workstation_qt`**（`Pwb::UiWorkstationQt`，AUTOMOC，仅
  `TARGET Qt6::Widgets` 时）— 11 TU：`ui_context_qt`、`mode_state_qt`、
  `app_bar`、`activity_rail`、`explorer_panel`、`inspector_panel`、
  `task_center`、`process_hub`、`agent_panel`、`keybinding_manager`、
  `workstation_frame`。链 `Pwb::UiWorkstation` + `UiShellQt` +
  `UiWidgets` + `Qt6::Widgets`。

## 服务 seam（不移植不伪造）

| seam | 服务域 | 承接方式 |
|---|---|---|
| `UIContextService::Provider` | 工程/层位/编辑/选择/能力等 43 字段权威 | 逐字段 std::function 注入；未注册 → honest unknown |
| `WorkstationFrame::PanelFactory` | UI-13 composite 页 + 外部面板 | dock_id → widget；缺省 `ui_shell::PagePlaceholder` |
| `TaskCenter` snapshots/registry 槽 | 调度器 JobSnapshot 列表 + OperationRegistry | std::function 注入快照源；registry 指针注入 |
| `PlanResolver`/`AgentRiskResolver`/`PlanExecutor`/`ConfirmWriteFn` | Agent 计划解析/风险/执行/写确认 | 全 std::function 注入；无 executor → 收据诚实拒 |
| `KeybindingManager` host 回调 | 工具切换/缩放/QC/FSM dispatch | intent → host 注入回调，壳不持权威 |

## 合并说明

- `origin/main`（UI-08..UI-11）已并入；根 `CMakeLists.txt` 冲突解法：
  保留全部既有 `add_subdirectory` 块，UI-12 块追加在
  `libs/ui_pages_mapedit` 之后、`apps/` 之前。
- 主机 SDK 解析：`PwbQgisSdk.cmake` 的非 Windows 默认期望
  `<repo>/../main` 兄弟 checkout；本机主 checkout 在
  `~/project/paleo-workbench`。以 cache 覆盖
  `PALEO_QGIS_SOURCE_DIR/SDK_DIR/BUILD_DIR` 指向之（环境变量同名可注入；
  首次失败 configure 已把默认值写入 cache，须 `-D` 显式覆盖）。
  文档化的 cache-overridable 机制，未改动 SDK 检查本体。

## 修缺记录（构建期暴露）

| 位置 | 问题 | 修法 |
|---|---|---|
| `task_projection.*` 等 6 文件 | 命名空间误写 `job_runtime::`（实为 `pwb::job`） | 全文替换 |
| `stage_actions.cpp` | 变量名 `requires` 撞 C++20 关键字；MD5 末位取错 nibble（`(d>>28)` 应为 `(d>>24)` 低半字节 = hexdigest 末位） | 改名 + 取位修正（mod-8 parity） |
| `ui_context.cpp` | 缺 `<stdexcept>` | 补 |
| `workstation_frame.cpp` | `new QMainWindow(this)` 自带 `Qt::Window` → 隐藏顶层窗，dock isVisible 恒假 | `setWindowFlags(Qt::Widget)` 嵌入 |
| `agent_panel.hpp` / `explorer_panel.cpp` | 缺 `QLabel` / `QScrollBar` include | 补 |
| `task_center.cpp` | `TaskTableModel` ctor 声明未定义（moc getDefaultCtr 引用） | 补定义 |
| tests | `workbench_context_text` 旧签名（快照+layer_name 现行）；`ui_shell::` 缺 `pwb::`；首 refresh 期望错（Python `_last=None` → 首发必 emit parity）；dock 可见性需祖先 shown | 测试对齐实现与 Python parity |

## 测试（ctest `ui_workstation.*`，linux-ninja preset）

- **`ui_workstation.core`** — 26 tests / 0 failures：FSM 迁移/瞬态/信号
  纪律、状态语言 token/tone/context 文案、UIContext provider/fail-
  closed/变更发射、tool surface 直通与扁平化、action help、explorer
  分组/截断/footer、inspector 文档各 kind、task 投影（op 适配/文案/
  菜单/合并序/elapsed）、agent 风险/WRITE fail-closed/授权集、stage
  动作表/门控/dispatch/facies 色确定性、键位意图全链、log buffer。
- **`ui_workstation.qt_widgets_smoke`** — `QT_QPA_PLATFORM=offscreen`
  （ctest 属性携带）+ `LD_LIBRARY_PATH` prepend `PALEO_QGIS_RUNTIME`
  （传递链接经 UiShellQt 触 vendored QGIS，libodbc 等在其 lib/ 下）：
  桥发射纪律、mode 机、app bar、rail、explorer、inspector、task center
  （行注入/菜单/取消）、log bridge+viewer+console pane、agent plan
  执行流、键位（临时平移/恢复）、frame dock 组合（nav/inspector/agent/
  hub dock、pwbDockId、GL dock 禁浮、可见性切换、preset、首跑尺寸）。

## 偏差 / 遗留

- `shell.py` 的宿主持久化（QSettings dock state 读写）、面包屑/命令
  palette 挂接、`common.py` 图标染色 → 分别由 `ui_shell`
  layout_persistence、host 层、`ui_widgets/icon_factory` 承担，不在本
  切片重复实现；workstation_frame 暴露 `layout_changed` 信号供宿主
  持久化订阅。
- Agent console 面板为诚实占位（命令输入接入 seam 在 agent_panel，
  console 只读呈现）——Python 侧 console 同样为 TODO 占位。
- 未做 Python oracle 对账脚本（tool_policy golden 模式）：本切片
  projection 的 golden 需快照级 fixture，价值有限，未引。
