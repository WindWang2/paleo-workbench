# UI-02 PR ledger — feat/cpp-ui-components

Branch: `feat/cpp-ui-components`（base `origin/main` @ `5a6373bd`）
Worktree: `../worktrees/cpp-ui-components`
PR title: `feat(ui): UI-02 — components + modelview + qgis_stack`

> PR number/URL 在 `gh pr create` 权威输出后回填 —— 见文末「提交面」。

## 交付物

新库 `libs/ui_widgets/`（69 文件：32 hpp + 35 cpp + 2 CMake），三
target：`Pwb::UiWidgetsCore`（Qt-free）/ `Pwb::UiWidgets`（Qt 壳）/
`Pwb::UiWidgetsQgis`（QGIS 栈，SDK 准入门控）。共享文件最小追加：
根 `CMakeLists.txt`（platform 块一行）+ `libs/qgis/CMakeLists.txt`
（`if(TARGET Pwb::Domain)` 缺陷修复守卫）。

## 文件 → 终态映射

### components/（13 + `__init__`）

| Python | C++ 落点 | 终态 |
|---|---|---|
| badges.py | badges.hpp/cpp | ported |
| buttons.py | buttons.hpp/cpp | ported |
| constraint_factor_hud.py | constraint_factor_hud.hpp/cpp + core/hud_sampling | ported |
| dialog.py | dialog.hpp/cpp | ported |
| facies_eyedropper.py | facies_eyedropper.hpp/cpp + core/facies_pick | ported |
| facies_palette_widget.py | facies_palette_widget.hpp/cpp + core/facies_patterns + core/facies_taxonomy | ported |
| headers.py | headers.hpp/cpp | ported |
| inputs.py | inputs.hpp/cpp（current_density→ui_context/ThemeService） | ported |
| interactive_qc_hub.py | interactive_qc_hub.hpp/cpp + core/qc_hub_core | ported |
| states.py | states.hpp/cpp | ported |
| stratigraphic_timeline_slider.py | stratigraphic_timeline_slider.hpp/cpp + core/epoch_switching | ported |
| toast.py | toast.hpp/cpp | ported |
| views.py | views.hpp/cpp | ported |
| __init__.py | pwb::ui_widgets 命名空间 | ported（消解） |

### modelview/（3）

| Python | C++ 落点 | 终态 |
|---|---|---|
| async_query.py | async_query.hpp/cpp | ported |
| object_table.py | object_table.hpp/cpp | ported |
| reconcile.py | reconcile.hpp/cpp | ported |

### qgis_stack/（6 余 + `__init__` + covered）

| Python | C++ 落点 | 终态 |
|---|---|---|
| canvas_shim.py | qgis/canvas_shim.hpp/cpp | ported |
| display_canvas.py | qgis/display_canvas.hpp/cpp | ported |
| events.py | qgis/stack_events.hpp/cpp | ported |
| mirror.py | qgis/mirror_snapshot.hpp/cpp | ported（文档域真身 deferred） |
| tree_sync.py | core/tree_sync | ported |
| widgets.py | qgis/qgis_widgets.hpp/cpp | ported（shiboken 面消解） |
| __init__.py | pwb::ui_widgets::qgis 命名空间 | ported（消解） |
| layer_tree_panel.py | libs/ui（CONV-27） | covered（不重转） |

辅助缝：`icon_factory`（workstation_icon asset 解析）、`ui_context`
（theme/density 访问→ThemeService）、`map_chrome`（unified_map_canvas
paint 帮助函数子集，供 canvas_shim chrome；UI-15 复用）。

## 测试清单

| ctest | 内容 | 环境 |
|---|---|---|
| `ui_widgets.core` | 20 case / 80 checks — epoch/facies/HUD/QC/tree-sync Qt-free 核 | 无 Qt |
| `ui_widgets.modelview` | 8 case / 17 checks — ObjectTable/StableSelection/reconcile/AsyncQuery | offscreen |
| `ui_widgets.widgets_smoke` | 15 case / 82 checks — 全部部件构造+响应 | offscreen |
| `ui_widgets.qgis` | 5 case / 33 checks — canvas shim/display canvas/events/host widgets | 真 vendor QGIS SDK + offscreen |

`ctest -R ui_widgets` → **4/4 pass（48 case 全绿）**。

## 生命周期修复（自审 P0）

`mark_disposed`（display_canvas + canvas_shim）曾在 `QObject::
destroyed` 里 `session_.reset()` —— 半销毁 QGIS 子树上析构
MapSession → SIGSEGV/invalid free。改为只置记账标志，session 由有序
析构负责。对齐 Python `_mark_disposed`「纯记账」语义。

## 验证命令

```bash
source ~/pwb-sdks/env.sh
cmake --preset linux-native-product
cmake --build build/native-product --target \
  pwb_ui_widgets_core pwb_ui_widgets pwb_ui_widgets_qgis \
  ui_widgets.core ui_widgets.modelview ui_widgets.widgets_smoke \
  ui_widgets.qgis -j3
cd build/native-product && ctest -R ui_widgets --output-on-failure
```

## Limitations（如实）

1. 本切片**不接线** MainWindow/AppContext —— 只交付 库+测试
   （taskbook §2.2）。
2. `EpochTimelineController` 的 stratigraphy 持久化经注入 `HorizonIo`
   —— 未绑定时不落 domain 服务（deferred 非缺失）。
3. domain 轨收编待办：`core/facies_*`、`core/epoch_switching`、
   `map_chrome` 与 `mapping*/`/`unified_map_canvas` 的语义重叠面
   在各自迁移时收编/去重（decisions D2/D3）。
4. 不删 Python；`_vendored/`/`native_backend.py`/`.github/workflows/`
   未触碰。

## 提交面

- commit: `fe2b3a0f`（feat(ui): UI-02 — components + modelview + qgis_stack
  C++ port；75 files，+12813）
- push: `git push -u origin feat/cpp-ui-components`（new branch）
- PR: **`gh pr create` 权威输出 → https://github.com/WindWang2/
  paleo-workbench/pull/1371 → PR #1371**（2026-09-20 创建；
  gh 提示 2 uncommitted = 刻意不提交的 taskbook.md + ui-01-findings.md）
