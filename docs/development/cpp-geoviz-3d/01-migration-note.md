# CONV-GEO3D 迁移说明 — Geo-Viz / 3D Visualization / Geomodel Viewer C++ 化

Branch `feat/cpp-geoviz-3d-native`（base `origin/main` @ `ff67dcf3`）。

## Scope

把 3D/geomodel **visualization runtime**（pyqtgraph `GLViewWidget` 栈的 UI/glue 层）
迁移到既有 C++20/Qt6 平台，复用 `pwb::geomodel`（CONV-12/22）契约核与
`Pwb::Domain` JSON/SHA-256 基础设施。**不重写 geomodel 科学**，产品主链无 Python 依赖。

新增 `libs/geo3d_viz`（target `Pwb::Geo3DViz`，`-DPWB_BUILD_GEO3D_VIZ=ON`，
implies CONV-22 + data）：

| C++ 模块 | 替代的 Python surface |
|---|---|
| `scene_types.hpp` + `scene_object_manager.{hpp,cpp}` | `geoviz_seismic/scene_objects.py`（named registry、modes/kinds、≤6 clip planes、fail-loud 校验文案、Möller–Trumbore/clamped-sweep 拾取数学、`screen_point_to_ray`） |
| `orbit_camera.{hpp,cpp}` | GLViewWidget 相机参数化（distance/elevation/azimuth）、默认 500/30/45、preset 250/30/-45 与 250/90/0、矩阵/射线 |
| `scene_adapter.{hpp,cpp}` | `viz/geomodel/scene_adapter.py`（内容寻址 payload token diff、各 kind payload、派生命名 `#head/#label/#line`、facies 调色板、视图态：可见性/透明度/选择重着色/overlay/clip 重放、拾取逆变换） |
| `workspace_controller.{hpp,cpp}` | `ui/pages/geo3d_workspace.py`（测量状态机 6 模式、`measure:point-N/…/vert-N/plane-N` 计数与 `-N` 冲突后缀、bounds 派生 clip（无 ±80 硬编码）、视图 preset、QC/inspector、七键 `Geo3DWorkspaceState` save/restore、严格 `_as_bool/_as_float`、demo 不持久化、well 选择广播 seam） |
| `geo3d_viewport_widget.{hpp,cpp}` | `renderer_3d.py` + `joint_widget.py` 直通 API（QOpenGLWidget 现代 GL 渲染 mesh/lines/points/文字 overlay、shader 三平面剖切（`as_clip_equation` 语义）、orbit/pan/zoom、25px² 点击阈值、左键点击、CPU 拾取、截图、诚实 GL-less 降级） |
| `apps/paleo_workbench_platform/geo3d_dock.{hpp,cpp}` | 页面 3D 视图半的产品接线（编译 guard：`TARGET Pwb::Geo3DViz`） |

## Python surfaces 替换归类

- `scene_adapter.py` → **legacy reference**（行为冻结源；已加 docstring 标注）。
- `geo3d_workspace.py` → **legacy reference**（已加 docstring 标注）。
- `geoviz_seismic/scene_objects.py` → registry 契约已移植（该文件属独立
  geo-viz-engine 仓库，未在本仓标注；本模块的冻结语义以 oracle fixture 为准）。
- `viz/geomodel/domain.py`/`builders.py`/`qc.py`/`measurements.py`/`section.py` →
  **oracle-only**（CONV-12/22 已移植，本分支直接复用其 C++ 核）。
- 建模科学（stratal/welltie/facies、FLAC3D/Abaqus 导出对话框）→ 仍为
  Python production，属后续分支。

## 产品接线

- root CMake：`PWB_BUILD_GEO3D_VIZ` option（在 CONV-25 块与 DATA 块之间声明，
  implies `PWB_BUILD_CONV_22=ON` + `PWB_BUILD_DATA=ON`；`add_subdirectory` 在
  CONV-19 之后，sibling target 全部就位后加入）。
- platform：`geo3d_dock` 挂 `main_window`（`#ifdef PWB_WITH_GEO3D_VIZ`），
  well_selected → statusBar（2D 同步 seam 的第一消费者）。
- example：`geo3d_viewer_example`（offscreen 可跑的最小闭环）。

## Local build & test

本机构建环境：无 cmake/ninja（用户级安装 cmake 3.30.5 至 `~/.local/opt`），
无 QGIS SDK（`PWB_BUILD_PLATFORM=OFF`），无 pip/numpy/PySide6（Python oracle
fixture 按仓内惯例以 `tools/oracle/generate_geo3d_fixtures.py` 提供可再生产，
冻结值自 Python 源精确转录，oracle 测试含 negative self-check）。

- Configure：`cmake -S . -B build/geo3d -G "Unix Makefiles" -DCMAKE_BUILD_TYPE=Release
  -DPWB_BUILD_GEO3D_VIZ=ON -DPWB_BUILD_PLATFORM=OFF`
- Build：resource gate（`scripts/cpp-migration/invoke-resource-gate.sh Build`，
  `--parallel 2`，≤3 上限），全树 100%，`-Wall -Wextra -Wpedantic` 0 警告。
- ctest：**27/27 通过**（geo3d.core 112 checks、geo3d.widget 11 checks
  offscreen GL-less 诚实模式、geo3d.oracle 149 checks + 既有
  data.*/geomodel.volume/geomodel.contracts/ingest.parsers 全部无回归）。

> Local verification completed; online CI is not required or awaited for this task.

## Oracle

- `tests/cpp/geo3d_viz/fixtures/geo3d_style_oracle.json`：ObjectStyle 12 项、
  facies 8 色板、clamp+per-face 均色（含越界 99→7 clamp 用例）、512 抽稀
  stride（1024→2、513→1、64→1）、`format_result` 文案。
- `tests/cpp/geo3d_viz/fixtures/geo3d_state_oracle.json`：七键 payload 键序、
  demo 排除、测量 meta 字段、clip 三轴、相机无 viewport 时空、`_as_bool/
  _as_float` 全矩阵（含 "false" 永不 truthify、"1e400"→inf、strip 大小写）。
- negative self-check：oracle 测试内置"篡改 fixture 值必须被比较器发现"。
- 边界覆盖：NaN 顶点/孔洞高度场（10 面/15 点精确断言）、出界 face index、
  零法向 clip、>6 平面、空 stations、provider-null、空/null/数组/标量型非法
  payload、Unicode 名称 roundtrip、10 次反复开关、无效几何不致死。

## -j3 资源说明

全部构建经 `invoke-resource-gate.sh`（-j2）或 `--parallel 3` 以内完成；
无 OOM，无全量重复编译（增量 + targeted）。

## Parallel-branch interaction

与 open PR #1346/#1348（CONV-26）、#1351（CONV-27 UI）、#1352（CONV-28）、
#1353（product closure）、#1359（well-log host）无语义冲突（无同名
option/target/类）。文本冲突面（双方同锚点追加 guard 块）：根 `CMakeLists.txt`
（CONV-25 锚点，与 #1348/#1352）、`apps/paleo_workbench_platform/CMakeLists.txt`
与 `main_window.{hpp,cpp}`（与 #1351/#1353/#1359 相邻 hunk）。均为机械冲突，
后合并者并列保留 BEGIN/END 块即可。

## Known limitations

- 工程持久化的 dock→项目 store 接线延后（save/restore 为 lib API + oracle
  测试；宿主等价物属 CONV-26 接线面）。
- 井震联合场景（LOD 体、fence、切片联动）未接：`SceneTransform` seam 预留。
- 本机 offscreen 无 GL 上下文：渲染路径为编译级验证 + 诚实降级测试，
  像素级 smoke 需有 GL 环境复核（`geo3d_viewer_example`）。
- core-profile 驱动会把线宽钳到 1（`glLineWidth` 为 best-effort 提示）。
- 测量计数器 per-controller（Python 为模块级全局；`-N` 后缀兜底）。

## Remaining Python

建模科学页（stratal/welltie/facies/导出对话框）、井震 joint_host LOD 加载链、
2D map/QGIS 画布本体仍为 Python production（后续分支 scope）。
