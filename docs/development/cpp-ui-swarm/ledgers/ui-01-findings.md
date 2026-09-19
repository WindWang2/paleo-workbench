# UI-01 findings — foundation shell substrate

## Scope ledger (Python source → semantics → C++ target)

| Python source | Semantics | C++ target | Status |
|---|---|---|---|
| `ui/dock_framework.py` | DockDescriptor model, canonical dock registry, viewport classes, grow-only resize, first-run sizes | `dock_registry` (Qt-free) + `dock_resize` (Qt) | 已移植 |
| `ui/navigation.py` | 5-hub model, submodule registry, legacy page→hub map, defaults | `navigation` (Qt-free) | 已移植 |
| `ui/command_registry.py` | spec registration/replace, subsequence find, context evaluate, recents persistence | `command_registry` (Qt-free) + `command_palette` (Qt) | 已移植 |
| `ui/dock_manager.py` | panel registry (exact id + `:`-suffix), preset seeding, shared config identity | `dock_manager` (Qt-free) | 已移植 |
| `ui/layout_presets.py` | workspace presets, panel-title vocabulary seeding | `layout_presets` (Qt-free) | 已移植 |
| `ui/operations.py` | op lifecycle state machine, terminal eviction, cancel | `operation_registry` (Qt-free) + `operation_registry_qt` (signals) | 已移植 |
| `ui/deferred_page_bindings.py` | name-replace ordering, drain flush, project-first | `deferred_page_bindings` (Qt-free) | 已移植 |
| `ui/style.py` | inline-QSS registry, theme re-render, metrics callbacks, control-height tracking | `style_registry` (Qt, ThemeService-bound) | 已移植 |
| `ui/shortcuts.py` | QShortcut registry, conflict detection, text-input guard | `shortcut_registry` (Qt) | 已移植 |
| `ui/status_bar.py` | project/status/coord segments, engine badge | `status_bar` (Qt) | 已移植 |
| `ui/map_status_bar.py` | canonical ToolContext projection, chip vocabulary, collapse priority, clickable readouts | `map_status_bar` (Qt) | 已移植 |
| `ui/floating_panel.py` | floated-panel top-level window, visibility reporting | `floating_panel` (Qt) | 已移植 |
| `ui/panel_float_controller.py` | float/dock records, splitter restore, persistence, screen clamp, ribbon entries | `float_controller` (Qt) | 已移植 |
| `ui/layout_persistence.py` | QSettings panel layout store, legacy identity migration | `layout_persistence` (Qt) | 已移植 |
| `ui/page_placeholder.py` | placeholder page, theme-bound text color | `page_placeholder` (Qt) | 已移植 |
| `ui/crs_guidance.py` | one-shot CRS-mismatch guidance dialog | `crs_guidance` (Qt) | 已移植 |
| `ui/screen_inventory.py` | navigation-derived surface inventory | `screen_inventory` (Qt-free build) | 已移植 |
| `ui/app_shell.py` (partial) | CommandPalette + AdaptivePageStack only | `command_palette` / `adaptive_page_stack` (Qt) | 已移植（局部） |
| `ui/app_shell.py` (rest) | AppShell composition root: project/page wiring, dock host, view coordination, UIContext | — | 不移植（依赖未转页面；UI-12/14 域） |
| `ui/theme.py` | ThemeManager runtime owner | `libs/platform_services` ThemeService | 已有（复用，不重转） |
| `ui/tokens.py` | palette/density tokens | `libs/platform_services` theme_tokens | 已有（复用） |
| `mapping/tool_availability.py` | gate/stage reason vocabulary | `libs/tool_policy` | 已有（复用） |

## Oracle

`tools/oracle/generate_ui_shell_fixtures.py` →
`libs/ui_shell/ui_shell_tests/fixtures/ui_shell_oracle.json`（真实 Python
import 冻结；PySide6 缺失环境下经 importlib 叶子加载 + sentinel stub —
`tool_availability` 判词面由 tool_policy 自身 oracle 覆盖，本切片验证
调用边界而非措辞）。

Replay：`ui_shell.oracle_replay` — 8 groups / **8 tests, 0 failures**
（dock_framework / navigation / command_registry / dock_manager /
layout_presets / operations / deferred_bindings / negative_selfcheck）。

Qt 面：`ui_shell.qt_widgets_smoke` — 20 checks / 全过
（QT_QPA_PLATFORM=offscreen）。

## 验证

- `cmake --preset linux-ninja` configure + `pwb_ui_shell` /
  `pwb_ui_shell_qt` / `ui_shell.oracle_replay` / `ui_shell.qt_widgets_smoke`
  构建全绿（AUTOMOC 正常）。
- `ctest -R ui_shell` → 2/2 pass。
- 全部 21 个源文件 `-fsyntax-only` 单独验证过。

## Review round 1 corrections (e9d28f2c)

- `command_palette`：`MENU_BAR_HEIGHT` 40（原误 28；tokens.MENU_BAR_HEIGHT）。
- `screen_inventory`：移入 Qt-free `pwb_ui_shell`（纯 navigation 派生，
  无 Qt 依赖）。
- `operation_registry`：补 `operation_registry()` 全局访问器 +
  `bind_registry_to_shell` 的**替换**语义（Python 全局引用被 shell
  实例接管；Qt 桥在 shell 销毁时回退 lazy fallback）。
- `style_registry`：删死代码 `refresh_min_heights`（bind_metrics 回调
  已经 repolish_all 重跑）。

## Known deviations / limitations

1. **`_coordinate_decimals` 的 pyproj 路径**：Python 用 pyproj 判
   geographic；C++ 默认走 magnitude 启发式（Python 缺 pyproj 时的同一
   回退），并暴露 `set_crs_decimals_resolver` 注入点 —— 平台接线时
   绑 QGIS/PROJ 解析即恢复全语义。记为可恢复偏离而非等价缺失。
2. **FloatingPanel 图标**：Python 用 `workstation_icon("pane-restore.svg"
   /"rb-clear.svg")`；C++ 用文字 glyph 占位（⇩/×），图标资源体系属
   UI-02/12 域。
3. **`tool_details` 注入**：palette 的 `map:` tooltip 解释层
   （action_help/tool_surface）属 UI-12；`set_tool_details_provider`
   注入，缺省无 tooltip（Python 同款 try/except 空路径）。
4. **engine badge 探测**：`native_backend.has_cpp` + GL context 探测
   改为 `EngineProbe` 注入（默认 CPU badge）；接线时由 AppContext 提供
   真值。offscreen 永不创建 GL context（Python 同款守卫）。
5. **AppShell 组合根本体未转**（页面栈/视图协调/延迟绑定调度器/窗口
   集成）——依赖未转页面与 WorkstationFrame，归 UI-12/14。
6. **QShortcut guard 的 `focus_in_text_input`**：完整复制 Python 的
   类型清单（QLineEdit/QTextEdit/QPlainTextEdit/QTextBrowser/spinbox/
   editable combo/item-view 编辑器）。
7. **未做**：QSS token sheet 的应用级广播（ThemeService.apply 已覆盖）、
   快捷键的 palette 展示联动测试（行为已覆盖）。

## 冲突面声明（merge 时）

- `libs/qgis/CMakeLists.txt`：补 `Pwb::Domain` 链（main 预存缺陷修复 —
  `map_session.cpp` 无条件 include `pwb/domain/json.hpp` 但只有
  CONV_29 链传递该 include；linux-ninja 不开 CONV_29 即断）。若与其他
  分支冲突，保留 `if(TARGET Pwb::Domain)` 守卫形式。
- 根 `CMakeLists.txt`：`if(PWB_BUILD_PLATFORM)` 块内
  `add_subdirectory(libs/ui_shell)`（platform_services 之后）。
- 不触碰 `apps/`、`main_window.*`、`app_context.*` —— 接线属后续
  轮次（需 UI-12/14 面）。
