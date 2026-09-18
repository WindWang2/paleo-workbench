# CPP-A 原生产品闭包（native product closure）— scope ledger

> 分支：`feat/cpp-native-product-closure`（基线 `origin/main` @ ff67dcf3）
> 日期：2026-09-18 起
> 目标：把已合并的 C++ 模块组合成**可作为产品主链运行的原生闭包**——
> 应用组合根、bootstrap、runtime composition、产品 preset、能力发现、
> 错误链路、产品级自检、Python-free 启动路径、安装骨架。

## 本分支负责

| # | 交付 | 落点 |
|---|---|---|
| A | `PWB_BUILD_NATIVE_PRODUCT` 产品级 CMake 闭包（fail-closed 硬依赖 + 可选模块 capability probe + link closure/capability summary），feature graph 拆入 `cmake/PwbNativeProduct.cmake`；`native-product` preset | 根 `CMakeLists.txt`、`cmake/`、`CMakePresets.json` |
| B | C++ 应用组合根分层：`main.cpp → bootstrap → ApplicationContext → MainWindow → services`；`MainWindow` 瘦身为 UI 壳（会话/运行器/存储所有权移入 `ApplicationContext`，显式启动/关停顺序） | `apps/paleo_workbench_platform/`、`libs/application/`（如需 seam） |
| C | Python-free 产品自检：`pwb-platform --self-check / --headless-self-check / --capabilities / --diagnostics`；覆盖 Qt init、QGIS runtime、provider/CRS、Data/Domain 读写、最小 DAG、mapping kernel 最小流程、project/workspace 生命周期、offscreen UI shell、service registry 完整性、进程内无 Python 断言 | `apps/.../self_check.*`、`capabilities.*`、`diagnostics.*` |
| D | 产品错误与日志链路：分类日志（startup/qgis/project/workflow/data/science）、消息 handler 收集、自检/诊断报告、顶层异常闸（不跨 Qt event loop 泄漏） | `apps/.../diagnostics.*`、`bootstrap.*` |
| E | 自动化 capability matrix：configure 期生成 `pwb/app/product_capabilities.hpp`（编译期闭包真相）+ 运行期 probe + `platform.capabilities` ctest 防漂移 + native readiness 文档 | `cmake/PwbNativeProduct.cmake`、`tests/cpp/platform/`、本文档 |
| F | C++ 产品路径 Python 依赖审计自动化：`audit-python-runtime-deps.sh`（ldd 闭包 + 源码扫描）+ `platform.python_free` ctest | `scripts/cpp-migration/`、`tests/cpp/platform/` |
| G | 安装骨架：`install()` 规则 + Linux 运行时闭包部署脚本（Qt/QGIS/geo SO + plugins + proj/gdal data + 资源），部署树 `--self-check` 验证 | `cmake/`、`scripts/cpp-migration/deploy-native-product.sh` |

## 明确不负责（其他并行方向所有）

- QGIS 编辑器/图层面板细节深化（QGIS/UI 线）；本分支只消费 `Pwb::Qgis` 现有接口。
- freshness/recompute/constraint workflow 内核（Workflow 线）；只用 `workflow_engine` 做最小 DAG 自检，不改其内核。
- Catalog/Workspace 深层持久化（Data 线）；只经 `Pwb::Data` 既有 API 做 lifecycle 自检。
- 新的 well/geomodel 算法（Science 线）；geomodel/prediction/well_science 内核在 capability matrix 中如实标注 "kernel-only, 未接线"。
- ONNX/prediction 深层逻辑（Prediction 线）。
- Python 旧产品入口的删除/切换（M12）；本分支只做 readiness 记录与分层说明。

## 与并行方向的边界控制

- 根 `CMakeLists.txt` 只加 option 声明 + include + summary 调用（最小 patch）；全部闭包逻辑进 `cmake/PwbNativeProduct.cmake`。
- 不重排/不重写既有 CONV-* 块；native-product 只通过既有开关的组合表达。
- `libs/application` 只加不改（除非接缝必需，且保持向后兼容）。
- 公共 domain header / schema / README 不动；新文档入 `docs/development/cpp-platform/`。

## 现状基线（2026-09-18 盘点结论）

- C++ 产品路径（apps/、libs/application|qgis|ui）**零 Python 运行时依赖**（v3-ledger R12 链接审计；本分支以 F 自动化固化）。
- `pwb-platform --self-check` 已覆盖：GPKG fixture、渲染、layout 导出、工程生命周期（M2）、SEG-Y→属性→切片链（M3，fixture 存在时）。
- 已接线产品能力：矢量/栅格打开、地图编辑/undo/提交、QGIS layout 导出、工程新建/打开/保存、SEG-Y 导入、属性计算、切片视图、地质因子图（CONV-01）、测井 dock、因子统计 HUD（CONV-16）。
- kernel-only 未接线：prediction、geomodel、well_science 对比、factor_fusion、workflow_* 系列、interchange、ingest（capability matrix 中如实呈现）。
- 组合根现状：`main.cpp` 内联全部模式分派与自检；`MainWindow` 持有 session/runner/store 全部所有权（本分支 B 项解耦）。

## 验收口径

1. `cmake --preset linux-native-product` 一次 configure 拉起完整产品闭包，缺 SDK/模块 fail-closed；
2. `pwb-platform` 为真实组合根：`--self-check` 覆盖上表 C 项全部检查项，全绿退出 0；
3. `--capabilities` / `--diagnostics` 输出可被 ctest 断言（`platform.capabilities` / `platform.diagnostics`）；
4. 进程无 Python（`platform.python_free` ldd 闭包 + self-check 内 /proc/self/maps 双证）；
5. `platform.*`、`integration.*` 既有测试不回归；
6. 部署树（G）可跑 `--self-check`；
7. 本文档 + PR body 记录 native readiness 与 Python 残留分类。

## Native readiness 矩阵（2026-09-18）

自动对账：`ctest -R platform.capabilities` 以 configure 期闭包为准断言二进制
`--capabilities` 输出（防文档/代码漂移）；下表为人类可读快照。

### 已在原生产品闭包内（hard，fail-closed）

| 能力 | 组成 | 用户流程 |
|---|---|---|
| QGIS 平台壳 | QgsApplication/canvas/图层树/工具策略 | 打开应用即地图工作台 |
| 矢量/栅格数据打开 | ogr/gdal provider | 文件菜单打开 gpkg/geojson/shp/tif/asc |
| 地图编辑 + 撤销/提交 | EditController + tool_policy 28×77 golden | 顶点编辑→undo/redo→staged 提交 |
| Layout 出图 | QGIS print layout（PNG/PDF/SVG） | 导出布局 |
| 工程/目录数据 | Pwb::Data（newProject/openProject/manifest） | 新建/打开 .paleo 工程，catalog 事务提交 |
| SEG-Y 导入 | seismic_io 严格网格读取器 | 地震菜单导入 |
| 地震属性计算 | AlgorithmRunner + E 四内核 | 属性计算→catalog 发布 |
| 地震切片视图 | SeismicSliceWidget dock | 体版本浏览 |
| 地质因子图 | mapping_kernel + CONV-01 管线 | 地质菜单：井点→IDW/Kriging→等值线+相带 |
| 因子统计 HUD | CONV-16 dock | 插值结果统计展示 |
| 最小 DAG 工作流 | workflow_engine（CONV-07） | self-check 驻留证明 + 后续编排接线点 |

### 可选（probed，链接即在）

| 能力 | 条件 | 状态 |
|---|---|---|
| WLE 测井 dock | `Pwb::VisualizationWellLog`（WLE SDK + PWB_SCIENCE_BUILD_VIEWER） | 按需链接；LAS 加载进 self-check |

### kernel-only（已合并内核，尚未接线产品 UI — 属其他并行方向）

prediction（CONV-13/21）、geomodel（CONV-12/22）、well_science 对比
（CONV-09/11）、factor_fusion（CONV-24）、ingest（CONV-19）、interchange
（CONV-14）、workflow contracts/spec/graph（CONV-23/06/25）。`--capabilities`
以 `kernel` 类如实呈现，不进入产品链接闭包。

## Python 依赖分层（F 项审计结论）

| 入口 | 定位 | Python runtime |
|---|---|---|
| `python -m paleo_workbench.main` / `run_app.py` | legacy 产品入口（M12 前保留） | 必须 |
| `pwb-platform`（原生入口） | 本分支交付的产品主链 | **零**（ldd + /proc/self/maps + 源码扫描三重断言） |
| `libs/mapping_bind`（CONV-20 pybind 门面） | 兼容 seam：供 Python 旧产品调 C++ 内核，默认 OFF，不进原生闭包 | 有（其存在即 Python 面） |
| `libs/**/oracle/*.py`、`tools/oracle/*.py` | dev 时 fixture 生成器（test/oracle only） | 有，永不入产品 |

审计自动化：`scripts/cpp-migration/audit-python-runtime-deps.sh`（源码
pattern 扫描 + 可选 `--exe` ldd 闭包扫描）；ctest 侧 `platform.python_free`
与 self-check 内进程映射扫描双保险。

## 组合根分层（B 项落地形态）

```
main.cpp            # 6 行：-> Bootstrap::run
└─ bootstrap.cpp    # 日志链安装 → QgsApplication/QgisRuntime → 模式分派
                   #    --capabilities/--diagnostics/--self-check/interactive
                   #    顶层异常闸（exit 2 + 结构化 fatal 报告）
   └─ AppContext    # 服务层：ProjectSession + AlgorithmRunner(内核注册)
                   #    + 工程存储句柄；capabilities()/auditServices()
      └─ MainWindow # UI 壳：菜单/工具栏/dock/对话框；服务经 context_ 使用
         └─ services（libs/application|qgis|ui 的 ProjectSession 等）
```

- `MainWindow(AppContext&)`：产品路径（bootstrap 组合）；`MainWindow(QWidget*)`
  便捷构造（内嵌私有 context）仅供测试/小宿主。
- 关停顺序契约：窗口析构体内先 `session().close()`（canvas 存活），
  context 析构幂等收尾 runner/store；QgisRuntime 由 bootstrap 最后一站释放。
- 部署 seam：`PWB_QGIS_PREFIX` 环境变量覆盖编译期 SDK 前缀（默认行为不变）。

## 部署骨架（G 项）

`scripts/cpp-migration/deploy-native-product.sh <build-dir> <dist-dir>`：
二进制 + ldd 非系统 SO 闭包 + QGIS prefix（plugins/resources/proj/gdal
data）+ gdal 驱动插件 + 启动器（注入 `PWB_QGIS_PREFIX`/`LD_LIBRARY_PATH`/
`PROJ_LIB`/`GDAL_DATA`/`GDAL_DRIVER_PATH`）+ 部署树 `--self-check` 冒烟。
Windows 侧同构布局由 windeployqt + vendor `bin/` 树组装（文档化，不做
线上 CI）。

实测（2026-09-18，Linux）：部署树 `--self-check` 12/12 全绿（prefix 指向
`<dist>/qgis`，进程内 Python-free 断言在部署环境同样通过）。

## 工具链 note（重要，2026-09-18 排障记录）

本验证主机上出现过一类**选择性工具链缺陷**：`libs/qgis/src/qgis_runtime.cpp`
（含本分支的 `PWB_QGIS_PREFIX` deploy seam）编译产物中 `QgisRuntime::
acquire()`/`prefix_path()` 被无声替换为 `eb fe`（`jmp $` 自旋）——链接后
表现为本分支与 main 共有的全部 QGIS 平台测试超时（挂死在第一次
`QgsApplication::instance()` 调用内，LD_DEBUG 终验）。对照实验锁定：
同一编译器对 main 原版同文件编译健康（9632B、无自旋），仅该**路径**的
编译视图损坏；**将同一 TU 移至新文件名 `qgis_runtime_entry.cpp`（内容
等价，函数级微调）后编译健康**（11368B、含全部 QGIS 调用、无自旋）。
处置：runtime TU 更名重建（见 libs/qgis/CMakeLists 注释），修复后
native-product 全量 ctest 65/65、`--self-check` 12/12、部署树 12/12。
遗留观察（不阻塞）：vendored sqlite3.c 的 `clearSelect+0x280` 在最终
二进制里也有一个自旋字节序列，但 data.* 全部通过（该路径未被踩到，
sqlite amalgamation 不在本分支责任面内，如实记录移交）。
