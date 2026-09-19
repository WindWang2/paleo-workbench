# CONV-GEO3D — Geo-Viz / 3D Visualization / Geomodel Viewer 全面 C++ 化 — Scope Ledger

Branch: `feat/cpp-geoviz-3d-native` · Base: `origin/main` @ `ff67dcf3` · Worktree: `../worktrees/cpp-geoviz-3d-native`

## 本分支负责（in scope）

把 3D/geomodel **visualization runtime**（UI/glue/view 层）迁移到 C++，接入既有
`pwb::geomodel` 契约核（CONV-12/22）与 Qt6。新增 `libs/geo3d_viz`（target `Pwb::Geo3DViz`）：

| 模块 | Python source of truth | C++ 目标 |
|---|---|---|
| Native scene model（named objects、modes/kinds、≤6 clip planes、bounds、CPU pick） | `geoviz_seismic/scene_objects.py` | `scene_types.hpp` + `scene_object_manager.{hpp,cpp}` |
| 相机（distance/elevation/azimuth、orbit/pan/zoom、矩阵、屏幕→射线、presets 250/30/-45 与 500/30/45） | pyqtgraph `GLViewWidget` + `renderer_3d.py:1632-1698` | `orbit_camera.{hpp,cpp}` |
| Geological scene adapter（payload token diff、各 kind payload、样式常量、facies 配色、clip/selection 视图态、拾取逆变换） | `paleo_workbench/viz/geomodel/scene_adapter.py` | `scene_adapter.{hpp,cpp}` |
| Workspace controller（测量状态机 6 模式、bounds 派生 clip、视图 preset、save/restore state JSON、QC/inspector、well 选择广播 seam） | `paleo_workbench/ui/pages/geo3d_workspace.py` | `workspace_controller.{hpp,cpp}` |
| Qt6 native 3D viewport（QOpenGLWidget 渲染 mesh/lines/points/text-overlay、现代 GL 剖切、拾取、截图、生命周期安全、GL-less 诚实降级） | `renderer_3d.py` + `joint_widget.py` 直通 API | `geo3d_viewport_widget.{hpp,cpp}` |
| State JSON schema（Geo3DWorkspaceState 七键结构、严格 bool/float 收窄、demo 不持久化、逐条降级恢复） | `project/models.py:497-529` + `geo3d_workspace.py:645-878` | `workspace_controller.hpp`（state 半） |
| 平台接线（编译 guard dock，无 Python） | `geological_modeling_3d_page.py`（3D 视图半） | `apps/paleo_workbench_platform/geo3d_dock.{hpp,cpp}` |
| 测试 + oracle（style 常量、adapter payload、state JSON、offscreen smoke、反复开关、非法几何、selection） | `tests/test_geomodel_scene_adapter.py` 等 | `tests/cpp/geo3d_viz/*` + `fixtures/geo3d_*.json` |

## 不负责（out of scope）

- geomodel 建模科学（stratal slicing、层序分析、FLAC3D/Abaqus 导出科学）——CONV-22 核已有，UI 导出对话框不在本分支。
- 井震联合 LOD 体加载管线（`joint_host.py` 的 worker 链、SEGY 扫描）——体数据渲染经
  `SceneTransform` seam 预留，后续分支接入 well-seismic 场景。
- 2D map/QGIS 画布本体——只提供同步 seam（well_selected 信号、extent/CRS getter）。
- `lazy_visualization_tabs.py` / `composite_visualization_panel.py`（纯 2D 预览，与 3D 无耦合）。

## 已知限制（如实声明）

- **工程持久化的产品接线延后**：`Geo3DWorkspaceController::save_state()/restore_state()`
  作为 lib API 提供并有 oracle 级测试覆盖（七键 schema、demo 排除、逐条降级），
  但平台 dock 尚未接项目存储（Python 侧 `project.geo3d_workspace` 的宿主等价物
  属于 CONV-26 数据/项目生命周期分支的接线面）。后续分支把 dock 的状态写进
  项目 store 时调用这两个 API 即可，无 lib 层缺口。
- **井震联合场景未接**：`SceneTransform` seam 已预留（identity 默认），
  well-seismic LOD 体加载管线（joint_host.py 对应物）留待后续分支。
- **真 GL 渲染在本机未做像素验证**：构建机 offscreen 无 GL 上下文，widget 以
  诚实 GL-less 降级路径通过全部测试（registry/pick/pose/生命周期全功能）；
  现代 GL 渲染路径为编译级验证 + 代码审查，需在有 GL 的环境跑一次 smoke。
- **测量计数器为 per-controller**：Python 是模块级全局；单控制器等价，
  多控制器场景靠 `-N` 冲突后缀兜底（有意偏差，已冻结在测试中）。

## 已被其他 PR 完成的内容（不重复实现）

- CONV-12（PR 已合并）：builders/measurements/section/qc 数值核 → `pwb::geomodel`，直接复用。
- CONV-22（PR #1334 已合并）：DomainObject/ModelAssembly/QC/export/advisor 契约 → 直接复用。
- 开放 PR #1346/#1348（CONV-26）、#1351（CONV-27 UI）、#1352（CONV-28）、#1359（well-log host）、#1353（product closure）：不触碰 `libs/geo3d_viz`（lib 本体零冲突）。**接线文件存在文本冲突面**（双方都在同锚点追加 guard 块）：根 `CMakeLists.txt`（CONV-25 锚点，与 #1348/#1352）、`apps/paleo_workbench_platform/CMakeLists.txt` 与 `main_window.{hpp,cpp}`（与 #1351/#1353/#1359 相邻 hunk）。全部为机械冲突（无同名 option/target/类），后合并者 rebase 时并列保留各自 BEGIN/END 块即可。

## 共享冲突文件

- `CMakeLists.txt`（root）：仅追加一个 option + add_subdirectory 块。
- `apps/paleo_workbench_platform/CMakeLists.txt`：仅追加 TARGET-guard 块。
- `apps/paleo_workbench_platform/main_window.cpp/.hpp`：仅一个 `#ifdef PWB_WITH_GEO3D_VIZ` 挂钩块。

## Python 归类结论（迁移后）

- `viz/geomodel/scene_adapter.py` → legacy reference（行为冻结源，C++ `scene_adapter` 为产品主链）。
- `ui/pages/geo3d_workspace.py` → legacy reference（控制器语义冻结源；`_as_bool/_as_float/state` 契约在 C++）。
- `geoviz_seismic/scene_objects.py`（named registry 半）→ legacy reference（C++ `scene_object_manager` 对齐 API 契约）。
- `viz/geomodel/domain.py`/`builders.py`/`qc.py`/`measurements.py`/`section.py` → oracle-only（CONV-12/22 已移植，Python 保留为对账 oracle）。
- 建模科学页（stratal/welltie/facies、导出对话框）→ 仍为 Python production（后续分支）。

## 资源约束

- 编译一律 `-j3` 以内（gate 脚本为 -j2）；本机无 QGIS SDK，平台 app 不做本地构建验证，lib + tests + example 全量本地验证。
