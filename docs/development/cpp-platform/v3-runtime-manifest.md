# CPP-A v3 运行时 manifest（Linux 实测首轮）

> 状态：Measured（全部为本机实测，非计划值；Windows/MSVC/Qt6.8 列为未验证）
> 日期：2026-09-17
> 分支：`codex/cpp-v2-platform`（基线 `53e22b67`，worktree `.worktrees/cpp-v2-platform`）
> 上一版：`04-runtime-manifest.md`（v2，Windows 计划值，当时未编译）

## 1. 本轮唯一 ABI（Linux 权威验证环境）

| 项 | 值 | 证据 |
|---|---|---|
| Qt | **6.11.2**（系统包，`/usr/lib/cmake/Qt6`） | `find_package(Qt6 6.8 REQUIRED …)` 实测解析到 6.11.2；CMake configure 成功 |
| QGIS | **4.2.0 vendored**（`third_party/qgis` 快照 + `native/qgis_render_bridge/build/qgis-vendor/output` 只读产物树） | `output/lib/libqgis_{core,gui,analysis,native}.so.4.2.0` 存在性检查进 CMake（缺失即 FATAL_ERROR） |
| 编译器 | GCC 16.2.1（`-std=c++20`，无扩展） | CMake compiler identification 实测 |
| ninja / cmake | 1.13.2 / 4.4.3 | `--version` 实测 |
| 内存门禁 | 经 `scripts/cpp-migration/invoke-resource-gate.sh`（`Invoke-ResourceGate.ps1` 的 POSIX 等价端口；本机无 pwsh）。共享锁同文件 `cpp-migration-heavy.lock`、≥8 GiB、2 jobs、exit 75 语义一致 | Probe 实测 `RESOURCE_READY free=53.26 GiB`；本轮一次真实 75（B 线持锁） |

**Qt ABI 单源论证**：vendored `libqgis_core.so` 的 `NEDED` 为 `libQt6*.so.6`（`ldd` 实测全部解析到 `/usr/lib` 系统包），因此「构建用系统 Qt 6.11.2 + 运行同一 Qt」在同进程内只有一份 Qt。`PWB_QT_PREFIX` 在 `PwbQgisSdk.cmake` 中实际约束 `find_package`：前置到 `CMAKE_PREFIX_PATH` 并以 `cmake_path(IS_PREFIX …)` 校验 `Qt6_DIR` 必须落在前缀内，否则 FATAL_ERROR（本机 `/usr`）。

**Windows 环境保持未验证**：`C:/deps/Qt/6.8.0/msvc2022_64` + MSVC 14.38 组合本轮无法在本机执行（本机为 Linux）；v2 文档（00-baseline §1）的 Windows 冻结不被本文件推翻，但直到 Windows 实测完成前，平台验证状态以本 Linux 环境为准。

## 2. QGIS SDK 消费（Linux 布局差异）

| 项 | Windows（v2 计划） | Linux（本轮实测） |
|---|---|---|
| 库 | `output/lib/*.lib` + `output/bin/qgis_*.dll` | `output/lib/libqgis_*.so`（bin 为空） |
| 插件 | `output/plugins/` | `output/lib/qgis/plugins/`（provider 树） |
| PROJ data | `output/share/proj` | **不存在** → 系统 `/usr/share/proj`（`proj.db`） |
| GDAL data | `output/data` | `output/data` 为 QGIS 资源（svg/resources），GDAL data 用系统 `/usr/share/gdal` |
| 生成头 | build 树根 `qgsconfig.h/qgsversion.h` | 同左，另有 `src/{core,gui,analysis}/qgis_*.h`（本轮已补进 include 集） |

SDK 路径不写死进仓库：cache 变量 > 同名环境变量 > 平台默认（Linux 默认指向同仓 `../main` 的 sibling checkout）。测试环境变量（`PROJ_LIB/PROJ_DATA/GDAL_DATA/LD_LIBRARY_PATH`）在 `tests/cpp/platform/CMakeLists.txt` 按「vendor 存在则用 vendor，否则系统路径」的 configure 探测注入。

## 3. 本轮实编产物（全部真实构建，GCC 16.2.1 Release）

| Target | 类型 | 验证 |
|---|---|---|
| `pwb_tool_policy` | 静态库（Qt-free） | `platform.toolpolicy_matrix/golden` 通过 |
| `pwb_qgis` | 静态库（链 PwbQgis::Sdk + Qt6 Core/Gui/Widgets/Xml/Svg/PrintSupport） | 5 测试通过 |
| `pwb_application` / `pwb_ui` | 静态库 | adapters/ui_wiring 通过 |
| `pwb-platform` | 可执行（AUTOMOC） | `--self-check` 退出码 0 |
| 9 × `platform_*` 测试可执行 | 见 §4 | 9/9 通过 |

## 4. 测试证据（2026-09-17，经门禁 ctest，offscreen）

```
1/9 platform.toolpolicy_matrix   Passed   （阶段门/checked/奇偶断言，含 Qt 文档化 tooltip 回退语义）
2/9 platform.toolpolicy_golden   Passed   （28 上下文 × 77 工具 vs Python 生成 golden 全等）
3/9 platform.qgis_smoke          Passed   （真 GPKG+GeoTIFF provider、CRS 校验、QgsMapRendererParallelJob 真渲染非空白、树序读回、坏路径诚实诊断）
4/9 platform.edit_cycle          Passed   （顶点移动→undo/redo→commit→staged GeoJSON 重读几何+属性一致；bowtie 拓扑阻止提交且会话保留；修复后可提交）
5/9 platform.lifecycle_cycles    Passed   （20 次 session 开/关+编辑+提交循环，无挂起）
6/9 platform.export_layout       Passed   （PNG/PDF/SVG 内容级断言）
7/9 platform.adapters_substitutes Passed  （staged 协议 + module-only 诚实错误 + 快照派生）
8/9 platform.qgis_smoke_app      Passed   （pwb-platform --self-check 退出码 0：fixture 生成→provider→CRS→真渲染→PNG）
9/9 platform.ui_wiring           Passed   （动作真实入工具栏/菜单、已连接、触发有实效、dirty-close 三态）
```

（ui_wiring 行号见 `v3-verification.md` 实测输出；9/9 为本轮门禁内真实 ctest 结果。）

## 5. 关键修复记录（从未编译 → 全绿）

1. `qgis_gui.h/qgis_core.h/qgis_analysis.h` 生成头目录缺失 → SDK include 集补 `PALEO_QGIS_BUILD_DIR/src/{gui,analysis}`。
2. `class QWidget*` 在 `namespace pwb::qgis` 内被解释为**新类型声明**（`pwb::qgis::QWidget`） → 全局前置声明。
3. QGIS 4.x API 差异：`getFeature(fid)` 返回值式、`Qgis::VectorProviderCapability::AddFeatures` flags、`QgsApplication` 三参构造、`mapToolSet` 信号、`closestVertex` 引用式出参。
4. `QgsApplication::instance()` 是 `qobject_cast<QgsApplication*>`：进程必须以 **QgsApplication**（非 QApplication）作为应用对象，否则 acquire 抛异常 —— 全部 main/test 入口已换。
5. `EditDeltaV1` 属性变更捕获：`QgsAttributeMap` key 是字段索引，已映射为字段名（领域词汇）。
6. `pwb-platform --self-check` 渲染验证从 `canvas->grab()`（offscreen 下未 show 窗口尺寸不确定）改为 `QgsMapRendererParallelJob`（与画布同一渲染引擎，输出尺寸确定 800×600）+ 显式 `layer->extent()`。
7. ToolActionSet：`setChecked` 对非 checkable 动作是 no-op → checked 判定提升 checkable（parity 测试读回）。
8. lifecycle 测试顶点单调漂移跨过边界产生 Self-intersection → 改交替方向（测试缺陷，非产品缺陷；同时暴露「commit 持久化进 GPKG 工作副本」的真实语义）。
9. Qt/PROJ 布局差异（§2）导致的测试环境修正；AUTOMOC 缺失导致的 MainWindow vtable 链接错误。

## 6. 与 C/D 的 ABI 交握（本轮发布）

- C 线 `v3-contracts.md` 冻结头 blob SHA 以 C 分支为准；A 的 Linux 环境（Qt 6.11.2/GCC 16.2.1）与 C 的 Linux 参考 manifest 一致，WLE SDK 消费按 C handoff §1.2（`PWB_WELL_LOG_ENGINE_ROOT` install tree 或 gitlink submodule，A 不重建第二份）。
- D 线消费 `PwbQgis::Sdk`/`Pwb::Qgis` 时，Qt/编译器以本 manifest §1 为准；`PWB_QT_PREFIX` 校验是 fail-closed 的，不允许第二 Qt 进程内混装。
- 生产链无 CPython/PySide/Shiboken/`qgis_render_bridge`（链接审计见 v3-verification）。

## 7. 本轮未验证项（诚实清单）

- Windows/MSVC/Qt6.8 全链（无该环境）。
- 500 次 soak、ASan/UBSan、性能基准（属集成/稳定性门禁）。
- 可见桌面交互截图（本环境 headless offscreen；`QT_QPA_PLATFORM` 无显示服务器。UI 交互以 `platform.ui_wiring` 的动作触发断言替代，**该项标记未执行**）。
- D/E 线 target（未交付），integrated 配置见 v3-integration-verification。
