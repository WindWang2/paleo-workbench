# CPP-A 平台/QGIS 线 — 进度

## 2026-09-16

- R1 侦察完成：工具链/SDK manifest 冻结（见 00-baseline）；无新 PR/issue 重叠；内存 3.96 GiB 暂不能编译。
- A0 四件套就位（00-baseline / 01-contracts / 02-test-plan / 本文件）。
- R3 全量源码落盘：根 CMake/Presets/`cmake/PwbQgisSdk.cmake`（QGIS 4.2.0 SDK 只读 imported targets + 单 Qt 6.8.0 ABI）；`libs/tool_policy`（tool_availability.py 逐字移植：80 工具×12 组、门序、阶段 fail-closed、cancel 豁免、severity/checked）；`libs/qgis`（QgisRuntime 唯一 init/exit、MapSession session-owned QgsProject + 画布/树 + 关闭顺序、LayerAdapter join key、EditController 顶点/undo/redo/拓扑门禁/staged asset、LayoutService PNG/PDF/SVG）；`libs/application`（ProjectSession 快照采集 + B/C adapter 接口）；`libs/ui`（ToolActionSet 纯投影）；`apps/paleo_workbench_platform`（main + MainWindow + --self-check）；`tests/cpp/platform` 6 个测试 + fixtures（运行时生成 GPKG + 提交的 64×64 GeoTIFF）；`Invoke-PlatformBuild.ps1`（MSVC 手工环境 + 门禁委派）；CI 两平台 workflow（本轮未执行，如实记录）；04-runtime-manifest / 05-build-and-run。
- 预编译自查修复：getFeature 单参重载、QColor/QStatusBar/cmath includes、SnappingTypes QFlags 构造、QgsVersionInfo→QGSVERSION、printf 宽字符。
- 门禁 Probe ×2：锁空闲但内存 4.96–5.06 GiB < 8 GiB → exit 75（资源拒绝，非失败）。编译待内存回升。
