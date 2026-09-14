# 00 — 基线（Baseline）

状态：Accepted ｜ 分支 `main` ｜ 基线提交 `9347f6cf`（工作区另有未提交改动，见 §4）
文档集范围：**顶点编辑/拓扑编辑可用性 + 数字化工具条·捕捉工具条全功能对齐 + 图层栈序与标注序一致性**

> 实施进度与验证结果：见 [`08-implementation-record.md`](08-implementation-record.md)
> （M0 全部落地、M3 主干落地、M1 部分落地；本文件 §3 的"已实测事实"是改动**之前**的基线证据。）

## 1. 本集回答的三个用户问题

| # | 用户表述 | 本轮结论（全部实测，见 01） |
|---|---|---|
| A | 「顶点编辑不能用，在图上没法编辑顶点」 | 有**两个独立缺陷**：① v2 顶点拖动路径在 MSVC 上必然访问违例（一行 C++ 修复，已验证）；② 宿主从不把新建图层推成画布当前层，导致桥侧 `editLayer()` 恒为 `nullptr`，拖动退化为 v1 回调后**静默失败**（无任何提示） |
| B | 「图层窗口的前后顺序应与画布要素前后一致」 | 原生栈面板与画布同源于一棵 `QgsLayerTree`，**构造上一致**；但有三处独立破坏源：`_push_mirror_order` 缺反转（把自下而上序当 top-first 推）、组模式下该推送整体静默 no-op（洋葱皮「置顶」失效）、回退面板与原生树上下语义相反 |
| C | 「标注的显示顺序也应与图层一致」 | 原生栈已一致（标注是独立 pass，按画布图层序 + `zIndex` 排序，顶层标注最后画=在最上）；**回退渲染器不一致**（标注内联在图层绘制中，会被上层几何覆盖），且 QGIS 标注对话框产出的 `labeling_xml`（Priority/Z-Index/避让）在回退栈不消费 |

## 2. 验证环境（本轮实测所用）

- 平台：Windows 10.0.26200 x64，MSVC 14.38 (VS 2022 Community)，Release
- 解释器：仓库 `.venv`（uv 管理的 CPython 3.12.13）
- 桥：`native/qgis_render_bridge/qgis_render_bridge.cp312-win_amd64.pyd`（1,687,040 B，本集全程未改动，实验用的临时构建已还原）
- vendored QGIS：`native/qgis_render_bridge/build/qgis-vendor`（`WITH_GUI=ON WITH_ANALYSIS=ON WITH_PYTHON=OFF`，实际版本见 `manifest.qgis_version`）
- Qt：PySide6 自带 Qt（`Qt6Core.dll` 等来自 `site-packages/PySide6`）；vendor 侧仅 `Qt6Core5Compat.dll` 经 PATH 解析
- 依赖 DLL：`qgis_core/qgis_gui/qgis_analysis/gdal/geos_c/proj_9/sqlite3` 均来自 `build/qgis-vendor/output/bin`（实测进程内枚举，无重复副本、无 conda 混载）

## 3. 本轮已实测事实（禁止重做；含命令与结果）

| 编号 | 事实 | 证据 |
|---|---|---|
| F1 | **v2 顶点拖动必然崩溃**：设了画布当前层 + 打开原生会话后，在顶点上按下即 `access violation`（进程死） | `pytest tests/test_qgis_topo_m1_native_editing.py::test_scenario5_shared_node_drag_moves_both_one_macro_undo -m qgis` → `Windows fatal exception: access violation`（崩在 mousePress，测试文件第 104 行）；`tests/test_qgis_topo_m2_cross_layer.py` 同 |
| F2 | 崩溃点是 `beginSharedDrag` 的第一条成员写入（**不是** marker/rubber band/QgsVertexMarker 本身） | 插桩构建探针：`[PWB] BSD enter` → `[PWB] BSD assign ok` 之后即崩；`#include <cstdio>` 探针逐句定位 |
| F3 | 触发条件是"命中顶点"这一分支：空处按下（框选起点）与 v1 路径均**不崩** | 变体矩阵：A(编辑中+命中顶点)=崩；B(未编辑+命中顶点)=通过；C(编辑中+空白处)=通过；D(编辑中+全层档+命中顶点)=崩；E(只悬停)=通过 |
| F4 | 一行修复后 M1/M2 两套真桥用例**全绿** | 先取锚点再移动容器后：`tests/test_qgis_topo_m1_native_editing.py` 5 passed；`tests/test_qgis_topo_m2_cross_layer.py` 5 passed |
| F5 | **宿主从不把新建图层推成画布当前层**：`create_layer → 树选中该层 → 开始编辑(原生会话已开)` 全流程中，桥侧**接受**的 `set_current_layer` 调用数 = **0** | 宿主级探针（`CompositeDocument` + 真桥）：`create_layer` 触发的唯一一次推送被桥以 `unknown doc_id` 拒绝；重复选中同层不再推送；`start_editing()` 后仍为 0 |
| F6 | 无当前层时拖动落 v1：**回调发出、几何不变、无任何提示** | 探针输出 `[no-push] events = ['vertex_moved']`、`[no-push] moved = False`（真桥，会话已开、只是未推当前层） |
| F7 | v1/v2 之外的既有能力完好：插点、删点、捕捉、钉住等用例均通过 | `tests/test_qgis_v10_edit_tools.py` 12 passed；`tests/test_qgis_vertex_move_tools.py` + `tests/test_qgis_snapping_config.py` 7 passed；`test_qgis_topo_phase2.py` 6 passed；`test_qgis_topo_m3/m4` 各 6 passed |
| F8 | 桥的 Windows 增量重编可行（约 3 分钟），但有**两个环境坑** | 见 §5 |
| F9 | 未提交的 `map_stack_service.cpp` 改动（既有失效镜像层 erase+重建）与本集缺陷**无关**：崩溃用例只 upsert 一次，该分支不进入 | 代码路径 + 探针（崩溃场景里 l 层为新建，`existing == nullptr`） |

## 4. 工作区状态（写文档时的真实状态）

未提交改动共 21 个文件、+801/−32 行，其中与本集相关的：

- `native/qgis_render_bridge/src/map_stack_service.cpp`（+8）：既有失效镜像层 erase+重建（与本集缺陷无关，见 F9）
- `paleo_workbench/ui/qgis_stack/canvas_shim.py`（+97）：`bridge_available()` 预探测 + **TEMP-DIAG 发布追踪**（把每次 publish 的 seen/failures/canvas_layer_count/树可见层写 `.workbuddy/publish_trace.txt`，并 `canvas.grab()` 落盘）
- `paleo_workbench/ui/qgis_stack/layer_tree_panel.py`（+41）：原生树右键补「复制为草稿…」
- `paleo_workbench/qgis_runtime/{loader,paths}.py`：vendor 配方的非 Qt 预载子集 + deps 缺失告警去重
- `run.bat` / `run_app.py`：启动链
- `tests/*`：4 个测试文件的增量断言

**TEMP-DIAG 与 `.workbuddy/publish_trace.txt` 是现场调试脚手架**，本集 M0 收口时应移除或降级为受开关控制的诊断（见 05 §M0-4）。

## 5. 构建/运行须知（本轮实测路径）

**首选**：仓库已有 `scripts/build-qgis-bridge.ps1`（设置 `LIB`/vcpkg 前缀/CMake 定位，走 `uv pip install -e native/qgis_render_bridge`）。V10 文档记录的 `pip install -e native/qgis_render_bridge`（`PALEO_QGIS_REUSE_VENDOR=1` + `PALEO_QGIS_BUILD_DIR=<vendor>`）等价。

**本轮诊断走的是手工增量重编**（只改一个 `.cpp` 时更快，约 3 分钟），命令如下（`cmake`/`ninja` 用 VS 2022 自带的那份即可）：

```
set PALEO_WITH_QGIS_RENDERER=1
set PALEO_QGIS_REUSE_VENDOR=1
set PALEO_QGIS_BUILD_DIR=<repo>\native\qgis_render_bridge\build\qgis-vendor
set PALEO_QGIS_CMAKE_PREFIX=C:/deps/Qt/6.8.0/msvc2022_64
set LIB=C:\deps\vcpkg\installed\x64-windows\lib;%LIB%
cd native\qgis_render_bridge          ← 关键：cwd 必须在这里
python setup.py build_ext --inplace
```

坑 1 — **`LIB` 必须含 vcpkg 库目录**：`gdal.lib`/`proj.lib` 不在 vendor `output/lib`，也不在 `setup.py:_windows_link_library_dirs()` 的搜索路径里，缺了就是 `LNK1181: 无法打开输入文件"gdal.lib"`（`scripts/build-qgis-bridge.ps1:72-80` 已编码该要求；手写命令时容易漏）。

坑 2 — **`build_ext --inplace` 的 cwd 决定产物落点**：在仓库根目录执行会把 `.pyd` 落到**仓库根**，而根目录在 `sys.path` 里、优先级高于包目录——后续测试与启动都会静默加载这个"影子桥"，`native/qgis_render_bridge/*.pyd` 反而失效（本轮曾因此把一次 5 passed 误读为"修复已生效"）。走 `pip install -e` 路线不会踩到；手写 `build_ext` 时必须在包目录内执行，或事后删除根目录产物。M0-5 的 conftest 断言即为兜底。

## 6. 硬排除（沿用既有约束，不在本集范围）

- 100GB 地震数据零接触（沿用）
- RAW 保护层不可直接编辑（沿用；派生草稿路径不变）
- Z/M 值：系统 2D，不引入（沿用 V10 `NOT_REQUIRED`）
- 不引入 QGIS Application 层（`QgsVertexTool`/`QgsAdvancedDigitizingDockWidget` 等 app 类不可链接；工具一律自研薄 `QgsMapTool`）
