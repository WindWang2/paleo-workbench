# UI-08 PR ledger — feat/cpp-qt-mapedit

Branch: `feat/cpp-qt-mapedit`（base `origin/main` @ `c07d2e91`）
Worktree: `../worktrees/cpp-qt-mapedit`
PR title: `feat(ui): UI-08 — qt-mapedit 编图编辑页簇 C++ port`

> PR number/URL 在 `gh pr create` 权威输出后回填 —— 见文末「提交面」。

## 交付物

新库 `libs/ui_pages_mapedit/`（40 文件：18 hpp + 18 cpp + 2 CMake +
3 测试文件），单 target `Pwb::UiPagesMapedit`（STATIC，AUTOMOC；
`TARGET Qt6::Widgets AND TARGET Pwb::UiDataQt` 门控）。编排既有
`Pwb::UiDataCore` edit 栈（EditCommandStack/VertexEditCommand/
RingEditCommand/CreateFeatureCommand/PropertyChangeCommand/topology/
snap/draft）与 `Pwb::UiDataQt` FeatureItemApi 项，不重复实现几何/命令
原语。共享文件最小追加：根 `CMakeLists.txt`（platform 块一行，
`libs/ui_map` 之后、`apps/` 之前）。

## 文件 → 终态映射

### 清单内（UI-08 §5，10 files）

| Python | C++ 落点 | 终态 |
|---|---|---|
| map_edit_scene.py (1309) | map_edit_scene.hpp/cpp + map_edit_api + feature_query_index + document_features | ported |
| map_edit_view.py (165) | map_edit_view.hpp/cpp | ported |
| map_edit_toolbar.py (188) | map_edit_toolbar.hpp/cpp + map_icons | ported |
| map_attribute_table.py (461) | map_attribute_table.hpp/cpp | ported |
| boundary_panel.py (105) | boundary_panel.hpp/cpp | ported |
| map_reference_panel.py (123) | map_reference_panel.hpp/cpp | ported |
| map_topology_issue_panel.py (142) | map_topology_issue_panel.hpp/cpp | ported |
| map_workbench_bottom.py (34) | map_workbench_bottom.hpp/cpp | ported |
| map_factor_shelf.py (102) | map_factor_shelf.hpp/cpp | ported |
| inspector_panel.py (1026) | inspector_panel.hpp/cpp | ported |

### Seam 承接（被引用方，提前落地）

| Python | C++ 落点 | 终态 |
|---|---|---|
| factor_preview_grid.py (189，UI-10 清单) | factor_preview_grid.hpp/cpp | ported（UI-10 去核） |
| table_preview_widget.py (400) | table_preview_widget.hpp/cpp | ported |
| tag_widgets.py (712) | tag_widgets.hpp/cpp（badge/container/input + parse_multi_tag_input；治理大面 deferred UI-11） | ported（部分） |

## 验证

```bash
source ~/pwb-sdks/env.sh
cmake --build build/mapedit --target \
  pwb_ui_pages_mapedit ui_pages_mapedit.helpers ui_pages_mapedit.widgets
cd build/mapedit && QT_QPA_PLATFORM=offscreen ctest -R ui_pages_mapedit \
  --output-on-failure
```

结果（复验后权威输出）：

- build：3/3 target 全绿，0 告警
- `ui_pages_mapedit.helpers` — 16 cases / 0 fail（Qt-free 核：
  hit/环/投影/吸附/索引/归一化/tag parse）
- `ui_pages_mapedit.widgets` — 13 cases / 0 fail（scene 工具/选择/
  dirty/undo-redo/vertex/拓扑/LOD/merge-split seam + 全部部件构造/行为）
- ctest 2/2 pass（0.42s）

## Limitations（如实）

1. 本切片**不接线** mapping_page/apps —— 只交付 库+测试
   （taskbook §2.2）。
2. `TagManagerDialog`/批量增删治理面 deferred 至 UI-11（catalog tag
   服务域）；本切片只承接 inspector 消费的 badge/container/input。
3. `document_features` 与 `libs/mapping_document`（CONV-02 条件
   target）语义重叠 —— 不在本 link set，局部实现保留，集成片去重。
4. `MapGeometryBackend=nullptr` 即 Python no-shapely 终态；shapely
   等价后端属 mapping_kernel 域，接口已留。
5. 全仓 build 存在既有无关失败：`tests/cpp/platform/
   test_project_session.cpp` 引用 `PWB_WITH_DATA_INTEGRATION` 守卫的
   `MainWindow::newProject`，`PWB_BUILD_DATA=OFF` 配置下仍编译 →
   非本切片引入，未触碰。
6. 不删 Python（11 源文件原样，`git diff` 下 `paleo_workbench/`
   零改动）；`_vendored/`/`native_backend.py`/`.github/workflows/`
   未触碰。

## 提交面

- commit: `b7eca653`（feat(ui): UI-08 — qt-mapedit 编图编辑页簇 C++
  port；43 files，+9021）
- push: `git push -u origin feat/cpp-qt-mapedit`（new branch）
- PR: **`gh pr create` 权威输出 → https://github.com/WindWang2/
  paleo-workbench/pull/1379 → PR #1379**（`gh pr view` 权威：
  state=OPEN，base=main，head=feat/cpp-qt-mapedit）
