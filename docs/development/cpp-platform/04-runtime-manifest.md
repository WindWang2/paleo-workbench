# CPP-A 运行时 manifest（首轮）

> 单一 ABI：Qt 6.8.0 (msvc2022 x64) + QGIS 4.2.0 vendored + MSVC 14.38 /MD CRT。
> 本文件列出可执行程序运行所需闭包及来源；打包部署按此清单显式复制，不依赖开发机 PATH。

## 1. 进程内组件

| 组件 | 来源 | 说明 |
|---|---|---|
| `pwb-platform.exe` | 本仓构建 | C++20 主程序（直接链接 QGIS） |
| `pwb_qgis.dll/静态库` | 本仓构建 | QgisRuntime/MapSession/EditController/LayoutService |
| `pwb_tool_policy` | 本仓构建 | Qt-free 工具状态机 |
| `pwb_application` / `pwb_ui` | 本仓构建 | ProjectSession 组合根 / QAction 投影 |

生产链**无** CPython、无 PySide6、无 Shiboken、无 `qgis_render_bridge.pyd`（Oracle 1 链接审计强制）。

## 2. QGIS SDK 闭包（只读消费）

| 路径 | 内容 |
|---|---|
| `<sdk>/bin/qgis_{core,gui,analysis,native}.dll` | QGIS 主库（4.2.0） |
| `<sdk>/bin/*.dll`（89 个） | 三方运行时：gdal、geos(_c)、proj、spatialite、qca-qt6、qt6keychain、qscintilla2_qt6、Qt6Core5Compat、expat/sqlite3/zstd/curl/… |
| `<sdk>/plugins/` | QGIS provider/插件树（ogr/gdal 等） |
| `<sdk>/data/` | QGIS 资源（svg、crs 等） |
| `<sdk>/share/proj` | PROJ 数据库（`proj.db`）——测试/打包必须设 `PROJ_LIB`/`PROJ_DATA` |

SDK 实例（本机）：`C:/Users/wangj.KEVIN/projects/paleo-workbench/native/qgis_render_bridge/build/qgis-vendor/output`；构建配方与 manifest 复用判据见 `00-baseline.md` §2。

## 3. Qt 闭包（唯一 Qt 来源）

`C:/deps/Qt/6.8.0/msvc2022_64`：构建用其 `.lib`/headers；运行需要 `Qt6{Core,Gui,Widgets,Xml,Svg,Network,OpenGL,OpenGLWidgets,Concurrent,PrintSupport}.dll` + `plugins/{platforms/qwindows.dll,styles/,imageformats/}`。`Qt6Core5Compat.dll` 取自 QGIS vendor bin（同 6.8.0 ABI）。

## 4. 测试/运行环境（CTest 已注入）

```
PATH=<qt>/bin;<qgis-sdk>/bin;%PATH%
QT_QPA_PLATFORM=offscreen        # 测试；交互运行用 qwindows
PROJ_LIB=<sdk>/share/proj        # 兼旧名
PROJ_DATA=<sdk>/share/proj
GDAL_DATA=<sdk>/data
```

## 5. 最小 Windows package（首轮）

`deploy/` 布局：`pwb-platform.exe` + 上述 DLL/plugins/data 复制成一棵树，干净 PATH 下 `pwb-platform --self-check` 通过（fixture 生成→provider→CRS→渲染→PNG 导出→退出码 0）。签名/安装器属 P6，本轮不伪造。

## 6. 已知限制

- Linux CI workflow 已配置但本轮未在 runner 上执行（见报告）；本地权威验证仅 Windows。
- 500 次 soak、ASan/UBSan、性能基准 = 集成/稳定性阶段门禁，本轮未跑、不宣称。
- B/C 真实模块未合入：`PWB_BUILD_DATA/SCIENCE` 保持 OFF；适配器验证为 substitutes（module-only）。
