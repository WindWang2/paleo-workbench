# V14-CONSTRAINT-FACTOR — 01 重叠审计（overlap matrix）

基线 `412d8baf`；审计对象 = open PR #1434/#1435/#1436 + 并行线 V14-QGIS-CONTROL + 近期 merged PR。

## Overlap matrix

| 对象 | 与本线交叠 | 处置 |
|---|---|---|
| #1434 `fix/open-issues-batch` | `libs/mapping_kernel/src/polygonization.cpp`（#1358 r[0] 精确闭合）、`libs/well_science/src/curve_expr.cpp`、`libs/workflow_graph/**`、`libs/ui_data_core/**`、`libs/ui_map/**`、`libs/ui_widgets/src/qgis/**` | **禁止重复实现**。本线不改这些文件；polygonization 差异交给 #1434。 |
| #1435 `devin/...cpp-final-closure` | 根 `CMakeLists.txt`（+6/-2）、`cmake/Pwb*.cmake`、`apps/.../app_context.cpp`、`tools/migration/**`、`tests/cpp/data/CMakeLists.txt` | 本线不碰 cmake/Pwb*、tools/migration、tests/cpp/data。`libs/closure_workflow/CMakeLists.txt` 是本线独占（#1435 不触及）。 |
| #1436 `feat/cpp-residual-conversion` | `libs/mapping_kernel/src/{representative_facies,layer_products,extract,polygonization}.cpp`（小改）、`libs/factor_host/src/semantics.cpp`（3 行）、`libs/job_runtime/**`（新增 ResourceGovernor/Budget/MemoryPressure）、`libs/closure_workflow/src/python_json.cpp`、`libs/closure_workflow/CMakeLists.txt`（+2 map_compile）、`libs/ui_canvas/**`、`libs/interchange/src/exporters.cpp` | 关键：本线**新增** `factor_prepare_production.{hpp,cpp}` + 测试目标，closure_workflow CMakeLists 只做**加行**（与 #1436 的加行正交，合并时两行共存）。不改 semantics.cpp/representative_facies/layer_products/extract。job_runtime 只**复用**现有 JobSpec/CancellationToken API（ResourceGovernor 若合入则 governor_clamp_fn 可选接入，不依赖）。 |
| V14-QGIS-CONTROL（Prompt3） | `libs/workspace/**`、`libs/mapping_document/**`、`libs/ui_widgets/**/qgis/**`、`native/qgis_render_bridge/**`、`libs/ui_map/src/qgis_layer_control*`、共享 `apps/.../main_window.cpp` | 本线不动这些。地图图层控制/顺序/激活目标全部交给该线；本线只写 project JSON（contour line features / paleomap_documents）与 catalog 版本。 |
| 近期 merged #1412（QGIS 编辑会话） | 约束几何编辑的 QGIS 腿 | 本线只消费 commit 后的 `constraint_layers` JSON（content_fingerprint/坐标），不造编辑器。 |
| 近期 merged #1419（well/crosswell） | well identity/LAS/DTW | 复用 API；不重写渲染引擎。 |
| 近期 merged #1433（mapping authoring） | `closure_mapping_install.cpp` 的假 worker 与 commit stub、`preparation_page.cpp` | 本线核心替换目标。`ui_pages_data` 仅在需要时做 additive 改动（预期零改动——页面 seam 已完备）。 |

## 本线独占面（写入租约）

- `libs/closure_workflow/include/pwb/closure_workflow/factor_prepare_production.hpp`（新）
- `libs/closure_workflow/src/factor_prepare_production.cpp`（新）
- `libs/closure_workflow/closure_workflow_tests/factor_prepare_production_test.cpp`（新）+ 测试 CMakeLists 加行
- `libs/ui_workers/include/pwb/ui_workers/worker_common.hpp`（**单点 additive**：`FactorTaskSlice::source_json` 字段，任何 PR 均不触及该文件）
- `apps/paleo_workbench_platform/closure_mapping_install.cpp`（BEGIN/END V14-FACTOR 命名块内替换假 worker）
- `tests/cpp/platform/test_closure_mapping.cpp`（additive 测试用例）
- `docs/development/v14-constraint-factor/**`

## 合并顺序假设

本 PR 只依赖 main（`412d8baf`），不依赖 #1434/#1435/#1436。与 #1436 在 `closure_workflow/CMakeLists.txt` 有两行级文本冲突风险（两者都 add_subdirectory 加源/加测试），合并时 trivial 解决。
