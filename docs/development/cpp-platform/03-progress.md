# CPP-A 平台/QGIS 线 — 进度

## 2026-09-16

- R1 侦察完成：工具链/SDK manifest 冻结（见 00-baseline）；无新 PR/issue 重叠；内存 3.96 GiB 暂不能编译。
- A0 四件套就位（00-baseline / 01-contracts / 02-test-plan / 本文件）。
- R3 全量源码落盘：根 CMake/Presets/`cmake/PwbQgisSdk.cmake`（QGIS 4.2.0 SDK 只读 imported targets + 单 Qt 6.8.0 ABI）；`libs/tool_policy`（tool_availability.py 逐字移植：80 工具×12 组、门序、阶段 fail-closed、cancel 豁免、severity/checked）；`libs/qgis`（QgisRuntime 唯一 init/exit、MapSession session-owned QgsProject + 画布/树 + 关闭顺序、LayerAdapter join key、EditController 顶点/undo/redo/拓扑门禁/staged asset、LayoutService PNG/PDF/SVG）；`libs/application`（ProjectSession 快照采集 + B/C adapter 接口）；`libs/ui`（ToolActionSet 纯投影）；`apps/paleo_workbench_platform`（main + MainWindow + --self-check）；`tests/cpp/platform` 6 个测试 + fixtures（运行时生成 GPKG + 提交的 64×64 GeoTIFF）；`Invoke-PlatformBuild.ps1`（MSVC 手工环境 + 门禁委派）；CI 两平台 workflow（本轮未执行，如实记录）；04-runtime-manifest / 05-build-and-run。
- 预编译自查修复：getFeature 单参重载、QColor/QStatusBar/cmath includes、SnappingTypes QFlags 构造、QgsVersionInfo→QGSVERSION、printf 宽字符。
- 门禁 Probe ×2：锁空闲但内存 4.96–5.06 GiB < 8 GiB → exit 75（资源拒绝，非失败）。编译待内存回升。

## 2026-09-16（续）— 资源阻塞结论

- Python golden 对账矩阵生成（28 上下文 × 77 工具，主仓评估器导出）+ C++ 对账测试就位。
- 累计 7 次门禁 Probe（约 35 分钟跨度）：内存 4.21–5.06 GiB，始终 < 8 GiB 门槛；锁始终空闲。占用来源为桌面应用常态（进程清单核验），无本任务遗留进程。
- **本轮状态：未完成（外部资源阻塞）**。源码/契约/文档/golden/CI 全部就位并已提交（28c610b6）；Oracle 1–6、8（编译、真实 QGIS smoke、CTest 统计、二次复验）与 Oracle 7 的复验半程**均未执行**，不宣称通过。

### 恢复步骤（内存 ≥8 GiB 后，在 platform worktree 根目录）

```powershell
powershell -File scripts/cpp-migration/Invoke-PlatformBuild.ps1 -Action Probe      # 期望 RESOURCE_READY
powershell -File scripts/cpp-migration/Invoke-PlatformBuild.ps1 -Action Configure -Configuration Debug
powershell -File scripts/cpp-migration/Invoke-PlatformBuild.ps1 -Action Build -Configuration Debug
powershell -File scripts/cpp-migration/Invoke-PlatformBuild.ps1 -Action Test -Configuration Debug -TestRegex '^platform\.'
# 链接审计（Oracle 1）：
#   dumpbin /dependents build/cpp-platform/pwb-platform.exe | findstr /i "python pyside shiboken qgis_render_bridge"
```

预期需要修错的环节（首编风险清单）：QGIS 4 头文件签名（已在 vendored 源核验过主要 API）、MSVC /utf-8 下中文判词、QFlags 构造、imported SDK 路径。全部修完后按 02-test-plan 逐项出 Oracle 证据，再跑一次关键 smoke 复验（Oracle 7 收口）。
