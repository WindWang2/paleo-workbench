# CPP-A 平台/QGIS 线 — 运行时与工具链基线（A0）

> 状态：Frozen（本轮冻结实际运行时与接口 ABI 选择）
> 日期：2026-09-16
> 分支：`feat/cpp-platform-qgis`（基线 `cpp-migration-plan-v1` → `d0347da2`）

## 1. 唯一 ABI 决策

**Qt 6.8.0 LTS / MSVC 2022 x64 / C++20 / Multi-threaded DLL CRT（/MD）**。

候选复核（总设计 §11.1 要求 P0 定死一个 Qt）：

| 候选 | 来源 | 结论 |
|---|---|---|
| Qt 6.8.0 | `C:\deps\Qt\6.8.0\msvc2022_64` 开发前缀（本机既有） | **采纳**。vendored QGIS 4.2.0 就是用它构建的（import 面向其 Qt6*.lib）；满足 well-log-engine Qt ≥ 6.8 要求；同一前缀提供 headers/.lib/DLL/plugins，构运行时同源 |
| Qt 6.11.1 | 仅 Linux CI 的 conda qt6-main 前缀 | 本机不存在；不引入第二个 ABI |
| PySide6 wheel Qt 6.8.0 | `.venv` | **禁止用于构建**（Python 产品路径）。C++ 平台进程不加载 PySide |

一个进程一个 Qt：C++ 平台 exe 只从 Qt 6.8.0 前缀解析 Qt（构建链接其 .lib，部署复制其 DLL + plugins）。不混装系统 Qt、PySide Qt、Conda Qt。

## 2. QGIS SDK（A 是唯一构建者；本轮复用已验证 install artifact）

| 项 | 值 |
|---|---|
| QGIS 版本 | 4.2.0（vendored 源码快照，upstream `final-4_2_0` @ `ca5812c8`） |
| 源码（含全部公共头） | 主仓 `third_party/qgis`（只读引用，不复制进 worktree；协议 §资源预算 8） |
| 预构建产物 | 主仓 `native/qgis_render_bridge/build/qgis-vendor/output`：`lib/qgis_{core,gui,analysis,native}.lib` + `bin/qgis_*.dll` + 89 个三方运行时 DLL（gdal/geos/proj/qca/qscintilla/qt6keychain/Qt6Core5Compat…）+ `plugins/` + `data/` + `share/proj` |
| 构建 flags | 旧桥 `native/qgis_render_bridge/CMakeLists.txt` 的 ExternalProject 配方（WITH_PYTHON/BINDINGS/DESKTOP/PROCESS/3D/SERVER=OFF，GUI/ANALYSIS=ON，INTERNAL_SPATIALINDEX=ON…），Windows 脚本 `scripts/build-qgis-bridge.ps1` |
| 复用判据 | manifest 匹配：同一 Qt 6.8.0 前缀、同一 MSVC 14.38、同机产物、qgis_core.dll 版本 4.2.0 → 满足。不匹配时由 A 以 ≤2 jobs 独立重建到本 worktree `build/qgis-vendor`（12 GiB 内存门禁） |

平台构建把 `qgis-vendor/output` 当作只读 imported SDK：`PwbQgis::Core/Gui/Analysis` imported targets 指向其 .lib；运行时 DLL 目录经 `PALEO_QGIS_RUNTIME` 变量注入测试/主程序的 PATH。**不在本 worktree 重编译 QGIS 源码**（除非 manifest 漂移）。

## 3. 编译工具链（本机实际核验）

- MSVC `14.38.33130`（VS2022 Community），Windows SDK `10.0.22621.0`，x64。
- CMake `3.27.2-msvc1` + Ninja：`C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\{CMake\bin,Ninja}`。
- `reg.exe` 在本机命令黑名单 → 不能走 vcvars64/Enter-VsDevShell；MSVC/SDK 环境按 `scripts/build-qgis-bridge.ps1` §1 的手工路径组装（PATH/INCLUDE/LIB）。
- 所有 configure/build/test 经共享门禁 `scripts/cpp-migration/Invoke-ResourceGate.ps1`（文件锁 + ≥8 GiB 空闲内存 + 2 jobs）。

## 4. 头文件解析策略（继承旧桥已验证方案）

QGIS core 头跨子目录非限定 include：按 `src/core/**` 递归 glob 收集 include 目录 + `src/core` + build 目录（`qgsconfig.h`）。本平台额外需要 gui/analysis 头：同样递归 glob `src/gui/**`、`src/analysis/**`。生成的 `qgsconfig.h/qgsversion.h` 取自 vendor build 树 `qgis-vendor/`（顶层）。矢量编辑需要 `src/gui`（canvas/maptool/layertree/dockwidget）与 `src/analysis/vector`（geometry checks）。

## 5. 进程内 QGIS 生命周期（唯一 init/exit）

- `QCoreApplication` 存在后：`QgsApplication::setPrefixPath(vendor_output, true)` → `QgsApplication::init()` → `initQgis()`，进程恰好一次（静态原子守卫，重复调用为编程错误并 abort）。
- `QgsProject` 为 **session-owned**（`std::unique_ptr`），不使用 `QgsProject::instance()` 单例路径；画布/树经 `QgsLayerTreeMapCanvasBridge` 绑定该 project。
- 关闭顺序（移植自旧栈并简化为单 session）：map tool `unsetMapTool` → canvas `setLayers({})` → `setProject(nullptr)` → project `removeAllMapLayers()` → project 析构 → （进程退出前）`QgsApplication::exitQgis()` 恰好一次。
- GUI 线程独占 QGIS GUI；worker 只交不可变结果；无嵌套 processEvents 等待（渲染等待用 `QEventLoop` + `renderCompleted` 信号或同步 job API）。

## 6. 已知能力边界（本轮诚实记录）

- vendor tree 无 Qt6Core/Gui/Widgets 主 DLL（旧 Python 路径借 PySide 同版本 Qt）——C++ 部署从 Qt 前缀补齐并保证只此一份。
- `Qt6Core5Compat.dll`、`qca-qt6.dll` 等在 vendor bin；plugins 目录为 QGIS provider 插件。
- GDAL/PROJ data 在 vendor `data/`、`share/proj`（PROJ 必须 `PROJ_LIB`/`proj.db` 可达）。
- 本轮不做：签名（P6）、全部旧 UI、完整 Python 产品功能对等。

## 7. 内存/资源现状

启动时空闲 ~3.96 GiB < 8 GiB 门禁 → 编译未开始；先完成 A0 契约/A1 源码，等空闲内存回升（门禁 Probe 通过）再进编译。资源返回 75 时只做轻量工作，不轮询。
