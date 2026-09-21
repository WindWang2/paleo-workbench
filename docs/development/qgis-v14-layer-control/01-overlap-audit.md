# 01 — Overlap Audit（vs 执行时 origin/main + 并行 PR）

## 1. 与 #1434（fix/open-issues-batch，open）的 overlap matrix

| #1434 租约文件 | 本线动作 | 判定 |
|---|---|---|
| `libs/workflow_graph/**`, `well_science/curve_expr.cpp`, `mapping_kernel/polygonization.cpp`, `ui_data_core/**` | 不触碰 | 无 overlap |
| `libs/ui_widgets/src/qgis/mirror_snapshot.cpp` + hpp（doc_id 索引 `build_doc_id_index`/`find_mirror_layer`） | 只调用其 API，不改文件 | 复用（#1385 范围） |
| `libs/ui_widgets/src/qgis/canvas_shim.cpp`（export_vector 只导出镜像层） | 本线修**同一函数内**的树序 bug（3 行 additive：按 `layerIdsTopFirst` 排序导出列表） | ⚠️ 语义正交、文本可能冲突；已在租约 `notes` 声明，rebase 时解决 |
| `libs/ui_map/src/map_chrome_painter.cpp`（overlay 缓存）, `mapping_page.cpp`, `display_map_canvas.cpp`, `workarea_map_widget.cpp` | 不触碰 | 无 overlap |
| CI/测试环境文件 | 不触碰 | 无 overlap |

## 2. 与 #1435（devin cpp-final-closure，open）的 overlap matrix

| #1435 租约文件 | 本线动作 | 判定 |
|---|---|---|
| 根 `CMakeLists.txt` | **不触碰**（本线全部为 libs/*/CMakeLists.txt 内 additive source 行） | 无 overlap |
| `cmake/Pwb*.cmake` | 不触碰 | 无 overlap |
| `apps/paleo_workbench_platform/app_context.cpp` | 不触碰（本线 glue 只动 `main_window.cpp` 具名小块） | 无 overlap |
| `tools/migration/**`, `tests/cpp/data/CMakeLists.txt` | 不触碰（本线新测试挂 `libs/workspace/workspace_tests/`） | 无 overlap |

## 3. 与其他四路并行线（Prompt1/2/4/5）的边界

- Prompt1（catalog）：本线经 `Pwb::Catalog` 既有模型/查询读取 version/asset/run，
  不改 catalog；source_usage 的 catalog 访问以 seam 注入。
- Prompt2（三阶段页面布局）：本线提供 layer 面板/状态/动作的 Qt-free 核心
  （presentation 状态语言），不动页面总体布局；`libs/ui_composite` 内只加
  新文件 + CMakeLists additive 行。
- Prompt4（factor）：factor 产出层只消费本线的 `register_layer` 绑定请求面
  （workspace mutations 既有 API），不改 factor。
- Prompt5（composition template/layout）：只读消费本线 canonical top-first
  顺序（`layerIdsTopFirst` / 本线 planner 输出），不建第二套 order。

## 4. main 已有能力核查（防重复实现）

Prompt 列出的疑点逐项核查（执行时 main）：

- `pwb/doc_id`：已有（桥/镜像 join key）。
- `source_version_id`/`source_asset_id`/`binding_kind`/`bound_at`：
  **C++ parity 已存在**（`libs/workspace/state.hpp:37-41` + mutations）——
  本线不重建绑定模型，只补 native 面向它的注册入口与双向查询。
- order keys：仅 Python（`layer_order.py`）；`state.tree` 在 C++ 仅 verbatim
  载体——**缺 C++ 引擎**，本线补。
- semantic role bands：仅 Python `ROLE_BANDS`；C++ 组级 `order` int 在
  `layer_groups.cpp`（组间），非图层角色带——本线补图层带。
- tree transaction revision：桥已有（`begin/end_tree_update`）；**原生
  `MapSession` 路径无**——本线在 C++ applier 侧补窗口。
- echo suppression：桥已有（SuppressGuard + shadow tables）；本线控制器
  复用同语义（applier 窗口内抑制 + revision 对账）。
- active layer：`ProjectSession::set_active_layer` 统一 setter 已有；缺
  edit/tool/selection 的显式目标模型与重验证——本线补。
- mirror order / layout order / legend order：`mirrorTreeOrderTopFirst`/
  `layerIdsTopFirst` 已有且 top-first；缺 export_vector 树序（bug）与
  命名方向转换助手——本线补。
- #1412（map document edit session）、#1432（bridge setup.py layout spec）、
  #1433（mapping authoring 08 线）：已并入 base，直接复用其
  `native_edit_session`/`document_io` 能力。

## 5. 结论

本线全部工作项在执行时 main 均为真实缺口，无与 #1434/#1435 的实现级
重复；唯一文本级冲突点是 canvas_shim `export_vector`（已声明，正交语义）。
