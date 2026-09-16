# Paleo Workbench 全 C++ 迁移开发设计

> 状态：Proposed
>
> 基线日期：2026-09-16（Asia/Shanghai）
>
> 主仓库基线：`main@671ee426679156098133847c186fda97722c43ab`
>
> geo-viz-engine 基线：`08851951f3bbc0beb90886adf52e1928f4383c16`
>
> 目标：把当前 Python + PySide6 + pybind11 + QGIS C++ 桥接架构迁移为单一 C++20 / Qt 6 / QGIS C++ API 桌面应用，同时保持工程、工区、目录、数据血缘和既有用户成果可读、可验证、可回退。

并行实施入口：见 [三线并行开发协议](01-parallel-development.md) 及其中的三个 GOAL/goal-loop 开发 prompt；它们规定本轮范围、独立 worktree、文件归属、共享接口和资源门禁。

## 0. 结论与推荐决策

推荐采用“同仓库、分阶段绞杀式迁移”，不做一次性重写。

最终产品应只有一个 Qt/QGIS C++ 进程、一个 Qt ABI、一个 QGIS 生命周期和一套地图编辑状态。Python 版本在迁移期作为兼容产品、行为基准和算法对照实现存在，但不嵌入最终主进程，也不继续扩张 QGIS 桥接口。

核心决策如下：

1. **直接链接 QGIS C++ API。** 删除 PySide/Shiboken 原生地址穿透、pybind 回调、GIL 管理和两套 QGIS 初始化路径。
2. **保留现有业务成果，迁移承载层。** V11–V13 已完成的图层树权威、工具可用性、原生编辑、目录 SQLite、数据血缘、阶段视图和编图控制面都作为目标模型输入，不重新设计同名功能。
3. **每类状态只设一个权威。** 数据版本、血缘和工程语义由领域/目录层负责；地图运行态与编辑工作副本由同进程的 `QgsProject`、`QgsMapLayer` 和 QGIS edit buffer 负责；提交时通过一个事务协调器生成新版本并更新绑定。
4. **geo-viz-engine 分域处理。** 地图/古地理地图渲染并入 QGIS；测井优先复用现有 `well-log-engine` C++20 SDK；地震、剖面和三维逐模块迁移，Python 实现暂作对照基准，禁止整库机械翻译。
5. **兼容优先于格式升级。** 第一阶段继续读写现有 `.paleo` JSON、`catalog.sqlite`、QGIS project XML 和数据资产布局；未知字段必须保留。格式升级另立 ADR 和迁移工具。
6. **新功能冻结在旧桥边界之外。** 除阻断性缺陷外，不再给 `QgisMapStack` / `QgisRenderBridge` 增加新跨语言方法；新能力优先落到可被新 C++ 应用直接复用的 Qt-free C++ 库或 QGIS C++ 服务。

## 1. 基线、范围与重叠审计

### 1.1 当前代码与协作状态

基线拉取后：

- 主仓库 `HEAD` 与 `origin/main` 均为 `671ee426`。
- 主仓库没有开放 PR，也没有开放 issue。
- 最近合并成果包括：
  - [#1310 V13 数据血缘、工区与 QGIS 编图控制面](https://github.com/WindWang2/paleo-workbench/pull/1310)
  - [#1304 V12 QGIS 顶点/拓扑编辑、栈序和标注一致性](https://github.com/WindWang2/paleo-workbench/pull/1304)
  - [#1303 矢量交互、增量拓扑、LOD 和总线性能](https://github.com/WindWang2/paleo-workbench/pull/1303)
  - [#1302 古地理专属 UI 与多期次联动](https://github.com/WindWang2/paleo-workbench/pull/1302)
  - [#1301 QGIS 原生地质拓扑编辑与相带协同](https://github.com/WindWang2/paleo-workbench/pull/1301)
  - #1297–#1299 渲染、拓扑、入库和编图计算性能优化
  - #1305–#1309 合并门禁与跨平台 CI 修复
- `geo-viz-engine` 固定在 `08851951`，与其远端主分支一致，没有开放 PR。
- `geo-viz-engine` 仅有一个开放 issue：[暂存储切片友好的 secondary layout #148](https://github.com/WindWang2/geo-viz-engine/issues/148)。本计划只把它视为地震存储设计约束，不复制该任务。
- 其他子模块：
  - `well-log-engine@f845e7ab`
  - `third_party/gdal@ed29baf1`
  - `third_party/proj@41f79ccf`
- `third_party/qgis` 不是 submodule，而是仓库内固定源码快照：QGIS 4.2.0 `final-4_2_0`，上游提交 `ca5812c8`，并带项目自己的构建/运行补丁。

### 1.2 本文覆盖范围

本文覆盖：

- 桌面主程序、工程/工区、目录和数据血缘；
- QGIS/Qt 生命周期、地图、图层树、编辑、布局、导出和工具状态；
- 算法执行、可视化边界以及 geo-viz-engine 处置；
- 构建、依赖、打包、迁移、测试、验收和任务拆分。

本文不覆盖：

- 新增地学算法或新业务工作流；
- 重新设计 V13 已落地的数据目录和血缘语义；
- 立即替换所有文件格式；
- 把 QGIS、GDAL、PROJ 或 well-log-engine 自身重写；
- geo-viz-engine #148 的具体实现。

### 1.3 规模判断

当前主程序约有 676 个 Python 文件、25 万行一方代码，其中 UI 约 9.5 万行；测试约 21 万行。QGIS 桥自身虽然只有约 1.7 万行 C++，但其 Python 宿主、镜像、运行时加载和工具协调分散在 `mapping`、`ui/qgis_stack`、`qgis_runtime`、`workstation` 等目录。geo-viz-engine 约 5.3 万行 Python，而 well-log-engine 已经是约 4.8 万行的 C++20 SDK。

因此工作量的主项不是“把 1.7 万行桥改成可执行程序”，而是：

- 抽取并固化现有业务契约；
- 将 Python 领域模型和 UI 编排迁到 C++；
- 消除重复状态与序列化路径；
- 为多种可视化模块建立稳定 C++ 边界；
- 用兼容测试证明没有破坏工程和科学结果。

## 2. 现状架构

### 2.1 逻辑结构

~~~mermaid
flowchart LR
    UI[PySide6 主程序与工作台] --> Domain[Python 工程/目录/工区/工作流]
    UI --> GFacade[geoviz Python facade 与子包]
    Domain --> Mirror[QGIS mirror / snapshot / WKT / GeoJSON]
    UI --> Shim[QgisCanvasShim / DisplayCanvas]
    Shim --> Addr[Shiboken QWidget 地址包装]
    Mirror --> Bridge[pybind11 QgisRenderBridge]
    Shim --> Stack[pybind11 QgisMapStack]
    Bridge --> QGIS[QGIS C++ core/gui/analysis]
    Stack --> QGIS
    GFacade --> GNative[零散 pybind C++ kernels]
    GFacade --> WLE[well-log-engine C++ SDK/适配]
    Domain --> Files[.paleo JSON / catalog.sqlite / 资产文件]
~~~

### 2.2 Python 业务与 UI 层

当前 Python 层同时承担：

- `ProjectDocument`、`UserVectorLayer` 等工程持久化模型；
- `CatalogDocument`、`DataAsset`、`DataVersion`、`DataRun` 等数据目录与血缘；
- `MappingWorkspaceState`、阶段视图、图层成员绑定和成熟度；
- `MapDocument`、`MapAuthoringDocument`、`VectorLayer`、`VectorEditSession` 等地图/编辑抽象；
- 工作流、算法编排、任务、命令和历史；
- PySide6 窗口、面板、对话框、模型/视图和 QAction 状态；
- geo-viz-engine 的控件创建和数据准备。

V13 后目录的规范持久化已经是 SQLite WAL，JSON 是检查点/兼容表示；较老类注释中“JSON canonical”的描述不能再作为新架构依据。

### 2.3 QGIS 桥接层

QGIS 集成有两条相互关联但并不完全相同的原生路径：

1. **离屏/导出路径：`QgisRenderBridge`**
   - Python 生成 `MapRenderSnapshot`；
   - 图层以 WKT、GeoJSON、栅格描述和样式字典/XML 跨过 pybind 边界；
   - C++ 创建镜像图层并执行同步渲染或矢量导出。
2. **嵌入式交互路径：`QgisMapStack`**
   - C++ 创建 `QgsMapCanvas`、`QgsLayerTreeView`、编辑工具和原生对话框；
   - Python 通过数值地址取得 QWidget，再用 Shiboken 包装成 PySide 对象；
   - Python 负责宿主布局、事件过滤、回调、镜像发布、编辑提交和关闭顺序。

`bindings.cpp` 暴露了大量图层、树、样式、布局、编辑、几何、拓扑、回调和工程 XML 方法。这已不是一个窄渲染适配器，而是跨语言复制了一部分 QGIS 应用框架。

### 2.4 Qt/QGIS 运行时

当前进程必须同时满足：

- PySide6 自带 Qt；
- Shiboken 与 PySide 完全匹配；
- QGIS 及桥构建时使用的 Qt；
- Qt Core5Compat、Multimedia、SVG、XML、Widgets 等组件；
- QGIS、GDAL、PROJ、GEOS、SQLite、SpatiaLite、插件和资源目录；
- Windows DLL 搜索顺序或 Linux 动态库搜索路径。

`qgis_runtime/loader.py` 必须在 PySide 导入前预装 DLL/动态库并修改搜索路径。专用 QGIS CI 还需要一个完整 Conda Qt 前缀来避免系统 Qt 与 PySide Qt 混装。普通 PR 主 CI 主要覆盖回退路径，QGIS 桥走独立、耗时且按路径触发的 fail-closed workflow。

### 2.5 geo-viz-engine 边界

geo-viz-engine 名义上通过 `geoviz` facade 提供 prepared preview 和 UI-thread 控件创建，但主程序仍有直接导入 `geoviz_seismic`、`geoviz_plots`、`geoviz_well_seismic_3d` 的代码，边界已经发生漂移。

其主要模块包括：

- `common`：共享数据和工具；
- `map`、`paleo_map`、`plots`：地图、古地理和图表；
- `well_log`：测井；
- `seismic`：地震；
- `cross_well`：井间剖面；
- `well_seismic_3d`：井震三维；
- 一个较小的 C++ `map_edit_core`，以及主仓库其他零散 C++ kernels。

地图域与 QGIS 已有明显重叠；测井域则已有成熟的独立 C++20 well-log-engine 可复用；地震和三维仍主要依赖 Python/NumPy/PySide/OpenGL。

### 2.6 当前权威边界

V11–V13 已把边界收敛为：

- Python 工程、目录、数据版本和血缘：持久业务权威；
- live QGIS layer tree：运行期图层结构、顺序、可见性、画布、图例和布局权威；
- QGIS 原生编辑：几何操作和拓扑能力；
- Python `ToolContext` + `evaluate_tool`：动作可用性的规范判定；
- Python 映射/编辑层：把 QGIS 工作副本变化重新提交为工程语义。

这个方向正确，但实现上仍需跨语言同步同一份状态。

## 3. 问题根因

### 3.1 根因不是“pybind 不稳定”，而是边界过宽

pybind11 对纯函数、小型 POD 和粗粒度计算是可行的。当前问题来自在边界上承载了：

- QObject/QWidget 生命周期；
- 原生指针地址；
- 双向回调；
- 可重入事件循环；
- 编辑工作副本和 undo/redo；
- 大型图层快照；
- 进程级 QGIS 初始化；
- Qt 插件、平台插件和私有 ABI。

跨语言接口越接近完整 GUI 框架，越难定义所有权、线程和关闭顺序。

### 3.2 对象所有权和生命周期分裂

C++ 创建 QWidget/QGIS 对象，Python 持有包装对象，Qt parent tree 又拥有析构权。半构造失败、窗口先销毁、Python GC、QGIS shutdown 和回调到达的次序都可能不同。

历史问题直接体现了这一点：

- [#1134 悬空 canvas 地址再次 reinterpret_cast](https://github.com/WindWang2/paleo-workbench/issues/1134)
- [#1133 释放 GIL 后 shutdown 与渲染并发导致 UAF](https://github.com/WindWang2/paleo-workbench/issues/1133)
- [#1156 嵌套 processEvents 与重入销毁竞态](https://github.com/WindWang2/paleo-workbench/issues/1156)
- [#1155 两个桥服务重复初始化 QGIS](https://github.com/WindWang2/paleo-workbench/issues/1155)

这些问题已经被逐项修复，但修复依赖地址墓碑、live registry、弱引用、shutdown guard 和特殊关闭顺序，说明结构性风险仍在。

### 3.3 一个进程中存在多个 Qt/ABI 来源

当前安装和 CI 必须协调 PySide6 Qt、QGIS Qt、Core5Compat 与系统/Conda 库。历史上出现过：

- [#993 Windows 桥构建失败](https://github.com/WindWang2/paleo-workbench/issues/993)
- [#1265 非 Windows loader 崩溃](https://github.com/WindWang2/paleo-workbench/issues/1265)
- [#1263 开发机绝对路径泄漏](https://github.com/WindWang2/paleo-workbench/issues/1263)
- [#925 bridge 可导入但运行时损坏](https://github.com/WindWang2/paleo-workbench/issues/925)

全 C++ 不能自动消除依赖复杂度，但可以把它收敛为一套在配置、链接、部署时就能验证的 Qt/QGIS 二进制闭包。

### 3.4 双重或多重状态权威

当前同时存在 Python layer/document/edit session、QGIS mirror/layer/edit buffer、render snapshot 和 workspace binding。V11–V13 已显著收敛这些角色，但提交链仍然是“QGIS 改工作副本 → 跨桥读回 → Python 命令/版本/绑定 → 再发布镜像”。

后果包括：

- 当前图层、编辑图层和工具目标容易失配；
- Python undo 与 QGIS undo 的边界难解释；
- 关闭或异常时需要判断哪一份状态最新；
- 每次小编辑仍可能触发大对象转换。

历史性能问题 [#932](https://github.com/WindWang2/paleo-workbench/issues/932) 和 [#1272](https://github.com/WindWang2/paleo-workbench/issues/1272) 虽已优化，但揭示了镜像协议的固有成本。

### 3.5 序列化和语义翻译损失

WKT/GeoJSON、样式字典、QGIS XML、Python enum 和 C++ enum 之间需要重复转换。曾出现：

- [#922 像素与毫米单位及样式字段丢失](https://github.com/WindWang2/paleo-workbench/issues/922)
- [#1051 回退后端多 CRS 重投影不一致](https://github.com/WindWang2/paleo-workbench/issues/1051)

直接使用 QGIS 对象可以消除运行期镜像翻译；工程持久化边界仍需显式 schema 和版本迁移。

### 3.6 GIL、线程和事件循环相互耦合

同步渲染、导出、Python 回调、Qt 主线程和 QGIS worker 的组合，要求精确决定何时持有 GIL、何时允许关闭、何时泵事件。[#1031](https://github.com/WindWang2/paleo-workbench/issues/1031) 是这一成本的直接例子。全 C++ 后应使用 Qt signal/slot、`QFuture`/线程池和显式取消令牌，不再以 GIL 作为并发边界。

### 3.7 测试矩阵被拆开

历史上的 [#437](https://github.com/WindWang2/paleo-workbench/issues/437)、[#827](https://github.com/WindWang2/paleo-workbench/issues/827) 和 [#935](https://github.com/WindWang2/paleo-workbench/issues/935) 表明，桥构建成本使真实 QGIS 路径长期与普通合并门禁分离。全 C++ 目标仓必须让“应用能链接、启动、加载 provider、打开画布”成为每个相关 PR 的基础门禁，而不是附加模式。

## 4. 迁移目标与约束

### 4.1 功能目标

- 以 C++20 和 Qt 6 Widgets 实现桌面壳、面板、模型/视图和交互；
- 直接使用 QGIS core/gui/analysis；
- 保持 V13 工程、目录、血缘、工区和阶段语义；
- 保持现有地图编辑、拓扑、样式、布局和导出能力；
- 保留并逐步迁移 geo-viz 的科学可视化；
- Windows 为首要交付平台，Linux 保持 CI 与开发可运行；
- 支持旧工程无损读取、迁移预检和显式升级。

### 4.2 质量目标

- 生产包不包含 CPython、PySide6、Shiboken 或 `qgis_render_bridge` Python 扩展；
- 不通过整数地址传递 QWidget/QObject；
- QGIS 只初始化/退出一次；
- UI 主线程不执行长时算法或全量数据复制；
- 每项可变状态只有一个当前权威；
- 核心领域与算法库不依赖 QWidget，可独立测试；
- 构建和运行依赖由 CMake preset 与包清单固定。

### 4.3 非目标

- 第一版不追求所有 Python 插件兼容；
- 第一版不把所有科研脚本变成内置 C++ 功能；
- 第一版不引入全新的云服务或分布式架构；
- 第一版不同时迁移所有 geo-viz 视图；
- 不以行对行翻译 Python 为验收标准。

### 4.4 设计原则

1. **领域核心不依赖 UI。**
2. **QGIS 类型不穿透到目录、工作流和算法公共接口。**
3. **UI 只投影状态，不自行推导业务规则。**
4. **跨模块传值优先不可变值对象、ID、span/view 和资源句柄。**
5. **所有持久化更改都有 schema version、迁移记录和恢复路径。**
6. **高成本数据不经 JSON/GeoJSON 作为进程内总线。**
7. **先建兼容测试，再替换实现。**

## 5. 目标架构

### 5.1 总体结构

~~~mermaid
flowchart TB
    App[PaleoWorkbench C++ Qt Application]
    UI[pwb_ui / Qt Widgets]
    Session[pwb_application / ProjectSession]
    Domain[pwb_domain + pwb_workspace + pwb_workflow]
    Catalog[pwb_catalog / SQLite WAL]
    Project[pwb_project / .paleo compatibility]
    Qgis[pwb_qgis / direct QGIS C++]
    Algo[pwb_algorithms]
    Viz[pwb_visualization]
    WLE[well-log-engine]
    Data[GDAL/PROJ/GEOS + asset stores]

    App --> UI
    UI --> Session
    Session --> Domain
    Session --> Qgis
    Session --> Algo
    Session --> Viz
    Domain --> Catalog
    Domain --> Project
    Qgis --> Data
    Algo --> Data
    Viz --> WLE
    Viz --> Data
~~~

### 5.2 目标模块职责

| 模块 | 职责 | 禁止依赖 |
|---|---|---|
| `pwb_domain` | ID、实体、值对象、错误、版本/血缘核心规则 | Qt Widgets、QGIS、SQLite |
| `pwb_project` | `.paleo` schema、兼容读写、未知字段保留、升级报告 | Qt Widgets、QGIS GUI |
| `pwb_catalog` | SQLite repository、事务、WAL、资产/版本/run 查询 | Qt Widgets、QGIS GUI |
| `pwb_workspace` | 阶段、成员绑定、视图状态、成熟度、输入集 | QWidget |
| `pwb_workflow` | workflow graph、任务、命令、运行状态 | QWidget |
| `pwb_qgis` | QGIS 生命周期、project/layer/tree/canvas/edit/layout/provider | Python、Shiboken、业务数据库细节 |
| `pwb_algorithms` | 算法描述、参数、执行、取消、进度、结果和 provenance | QWidget |
| `pwb_visualization` | 测井、地震、剖面、三维的 C++ viewer/service | Python |
| `pwb_application` | use case、ProjectSession、事务协调、错误映射 | 具体 QWidget 布局 |
| `pwb_ui` | MainWindow、dock、dialog、model/view、presenter | 直接 SQL、直接文件 schema |

### 5.3 权威模型

| 状态 | 唯一权威 | 说明 |
|---|---|---|
| 工程元数据 | `ProjectDocument` C++ model + ProjectRepository | 兼容现有 `.paleo` |
| 数据资产、版本、血缘 | CatalogRepository / SQLite | V13 语义保持不变 |
| 工区成员与阶段 | Workspace aggregate | 通过 ID 绑定数据版本与 QGIS 图层 |
| live 图层结构、顺序、可见性 | 一个 `QgsProject` 的 layer tree | 延续 V11 决策 |
| 当前画布/图例/布局 | QGIS 对象 | 不再生成第二套 render mirror |
| 编辑中的几何工作副本 | QGIS edit buffer | 编辑期间唯一可变几何 |
| 已提交几何 | 新 DataVersion 指向的数据资产 | 提交成功后成为持久权威 |
| QAction 可用性 | C++ ToolPolicy evaluator 输出 | QAction 不内嵌规则 |
| undo/redo | 当前编辑会话的 QGIS undo stack；工程级命令栈处理非几何操作 | 不双写同一几何命令 |

### 5.4 ProjectSession

`ProjectSession` 是应用层组合根，不是全局单例。它拥有：

- 当前 ProjectRepository、CatalogRepository 和 Workspace；
- 一个 `QgsProject`；
- MapSession、EditSession、AlgorithmScheduler；
- Selection/Tool/Stage 状态；
- dirty 状态、保存协调器和恢复日志。

MainWindow 通过 use case 和只读 view model 与 ProjectSession 交互。QGIS UI 对象仍遵循 Qt parent ownership；领域对象使用值语义、`unique_ptr` 或明确的共享句柄。

## 6. 模块迁移、重写与保留

### 6.1 可直接保留或演化

| 当前资产 | 策略 | 说明 |
|---|---|---|
| `third_party/qgis` | 保留 | 初期继续使用固定源码和补丁，形成统一 CMake superbuild |
| GDAL/PROJ submodule | 保留 | 继续固定版本，补充 CMake imported targets |
| `well-log-engine` | 保留并直接链接 | 已是 host-independent C++20；启用 Qt Widgets/OpenGL adapter |
| QGIS 桥中的 Qt-free 算法 | 抽取复用 | 地质拓扑、空间索引、增量拓扑等移入独立库 |
| QGIS 桥中的 QGIS 服务实现 | 重构复用 | 去掉 pybind/raw-address/registry 后成为 `pwb_qgis` 内部服务 |
| V13 SQLite schema 与数据语义 | 保留 | 建 C++ repository，不重新发明目录模型 |
| `.paleo` JSON schema | 保留 | 先兼容读写，再按 ADR 升级 |
| QGIS style/project XML | 保留 | 作为兼容输入；新代码直接操作 QGIS 对象 |
| 现有测试数据、golden、性能场景 | 保留 | 作为新旧实现对照基准 |

### 6.2 必须迁移到 C++

- ProjectDocument、Catalog model、Workspace model、workflow/task command；
- ToolContext、tool availability evaluator 和 action presentation；
- 工程加载/保存、autosave、恢复与迁移报告；
- 目录查询、版本/血缘/绑定事务；
- 主窗口、工作台、dock、属性表、检查器、对话框；
- 算法注册、执行、取消、进度和结果发布；
- geo-viz 中纳入首版交付的 viewer 和数据适配；
- 测试夹具、CLI 迁移工具和打包启动器。

### 6.3 必须重写或删除

| 组件 | 目标 |
|---|---|
| `bindings.cpp` | 删除；不再暴露 QGIS GUI 到 Python |
| `canvas_shim.py` | 由直接 C++ CanvasHost/MapSession 替代 |
| `display_canvas.py` 的地址包装 | 删除 |
| `qgis_runtime/loader.py` 的 PySide 前置加载逻辑 | 删除；由安装布局和启动时 QGIS path 配置替代 |
| Shiboken `getCppPointer` / `wrapInstance` | 全部删除 |
| QGIS render mirror 全量序列化 | 删除；直接使用同一 `QgsProject` |
| Python VectorEditSession 与 QGIS 几何双栈 | 收敛为 QGIS edit buffer + 提交事务 |
| fallback 2D cartographic backend | 产品模式删除；仅可保留无 QGIS 的纯算法测试替身 |
| Python 生产入口和 editable-install 打包 | 被 C++ executable/installer 替代 |

### 6.4 桥代码复用边界

不应把现有 `QgisMapStack` 原样搬进主程序。建议拆为：

- `QgisRuntime`：单次 init/exit、prefix/plugin/provider 诊断；
- `MapSession`：QgsProject、canvas、layer tree、selection；
- `LayerAdapter`：领域 ID 与 QgsMapLayer custom property 映射；
- `EditController`：start/commit/rollback、map tools、snapping、topology；
- `LayoutService`：layout、legend、export；
- `StyleService`：QGIS XML、renderer/labeling 与兼容导入；
- `ProjectXmlService`：旧工程 XML 导入/导出；
- Qt-free `GeologyTopologyCore` 和 `SpatialIndexCore`。

## 7. geo-viz-engine 处理策略

### 7.1 原则

geo-viz-engine 不是一个统一技术栈，不能用单一“全部保留”或“全部重写”决策。按领域、成熟度、QGIS 重叠度和 C++ 资产分别处置。

### 7.2 分模块策略

| geo-viz 模块 | 目标策略 | 迁移顺序 |
|---|---|---|
| `geoviz_map` | 地图渲染/交互并入 `pwb_qgis`；通用色标或数据变换抽到 Qt-free 库 | 早期 |
| `geoviz_paleo_map` | 古地理业务模型进入 workspace/algorithms；显示交给 QGIS | 早期 |
| `geoviz_plots` | 通用 plot API 重新定义；地图编辑部分并入 QGIS；非地图图表按需求迁移 | 中期 |
| `geoviz_well_log` | 以 well-log-engine 为实现核心，主程序直接链接其 Qt adapter | 早中期 |
| `geoviz_seismic` | 建独立 `pwb_seismic` C++ 数据/切片/渲染模块；先覆盖主流程 | 中后期 |
| `geoviz_cross_well` | 基于 C++ plot/section scene 重建，复用测井与地震数据接口 | 中后期 |
| `geoviz_well_seismic_3d` | 最后迁移为组合层，不复制底层数据 | 后期 |
| `geoviz_common` | 值类型、色表、范围、采样等迁到 `pwb_viz_core` | 按需 |
| `native/map_edit_core` | 与主仓地质/空间算法合并，避免第三套编辑核心 | 早期 |

### 7.3 过渡形态

迁移期允许：

- Python 旧应用继续使用固定 submodule；
- C++ 测试工具读取相同 fixture，生成结果与 Python oracle 比较；
- 对尚未迁移的重型地震算法提供开发期离线对照工具。

迁移期不建议：

- 在新 C++ 主进程内嵌 CPython；
- 再建一层 C++ → Python → C++ GUI 桥；
- 让新旧应用同时写同一个打开的工程；
- 将 Python worker 作为首版正式产品的必需运行时。

如果确有必须保留的 Python 科研扩展，后续应设计**可选、进程外、版本化消息协议**，并把其输出当作数据资产导入，而不是允许远端脚本操纵 QWidget 或 QgsProject。

### 7.4 issue #148 的关系

地震 C++ 存储接口必须允许主布局与 secondary layout、chunk 元数据和按轴切片计划，但具体 secondary layout 方案仍由 geo-viz-engine #148 决定。本仓迁移任务只消费最终格式/接口，不重复实现或关闭该 issue。

## 8. 数据层、工程与工区模型迁移

### 8.1 格式兼容策略

第一阶段采用“旧格式、双实现、单写者”：

- Python 旧版与 C++ 新版都能读取当前 `.paleo`；
- C++ 默认先写与现有 schema 等价的格式；
- 新字段必须带 schema version，Python 旧版无法安全处理时阻止降级写入；
- catalog.sqlite 继续作为目录规范存储；
- 迁移工具在写入前生成兼容性报告和备份；
- 不改写原始数据资产，只更新工程元数据、目录记录或生成派生版本。

### 8.2 C++ 模型

建议使用：

- 强类型 ID：`ProjectId`、`AssetId`、`VersionId`、`LayerId`、`RunId`；
- `std::chrono` 时间、`std::filesystem::path` 路径；
- `std::variant` 表示封闭联合类型；
- `std::optional` 表示可空字段；
- nlohmann/json 或等价库实现兼容 JSON；
- SQLite C API/轻量 RAII wrapper 实现 repository；
- 明确的 `SchemaVersion` 与 migrator registry。

不应把 QObject 作为领域实体基类，也不应把 QJsonObject 当作核心领域模型。

### 8.3 未知字段保留

Pydantic 当前允许额外字段。C++ 兼容层必须为每个可扩展对象保留 `extensions`/raw unknown members，并在 round-trip 时原样写回。验收测试应覆盖：

- 未知顶层字段；
- 未知实体字段；
- 未知枚举值的可诊断处理；
- 老 schema 缺省值；
- Windows/Unix 路径与 Unicode；
- future schema 的只读打开。

### 8.4 QGIS 绑定

继续使用稳定 domain ID 作为连接键：

- `QgsMapLayer` custom property 保存 `pwb/layer_id`、`pwb/version_id`、`pwb/asset_id`、`pwb/kind`；
- Workspace membership 保存相同 ID 和角色；
- 不把运行时 QgsMapLayer 指针、provider URI 或 tree node 地址写入领域模型；
- 打开工程时执行 binding audit，检测孤儿、重复、过期版本和不可访问资源；
- layer tree XML 只描述 QGIS 运行态，不取代 catalog lineage。

### 8.5 编辑提交事务

几何提交不能再先复制回 Python model。推荐流程：

~~~mermaid
sequenceDiagram
    participant U as User
    participant E as EditController
    participant Q as QGIS edit buffer
    participant T as CommitCoordinator
    participant C as CatalogRepository
    participant P as Project/Workspace

    U->>E: Commit
    E->>Q: validate + topology check
    Q-->>E: normalized feature delta
    E->>T: CommitRequest(layer, baseVersion, delta)
    T->>T: write recovery journal
    T->>C: create derived asset/version/run
    T->>P: update membership binding
    T->>Q: commit provider / rebind layer
    T->>T: mark journal complete
    T-->>U: new version + status
~~~

SQLite、工程 JSON 和外部数据文件无法形成单一 ACID 事务，因此必须有恢复日志：

1. 记录 base version、预期输出、临时文件和操作 ID；
2. 数据写入临时位置并 fsync；
3. 目录事务提交新版本/血缘；
4. 原子替换工程文件或更新保存点；
5. 更新 QGIS binding；
6. 标记完成并清理临时文件。

启动时检测未完成 journal，提供完成、回滚或另存恢复，不静默猜测。

### 8.6 QGIS project XML

首版继续读取 `map_qgis_project_xml`，由 QGIS 直接解析。中期可评估将大体积 XML 移到工程 sidecar 或 `.qgz`，但必须经过独立 ADR，因为这会影响便携性、diff、恢复和 Python 旧版兼容。

## 9. 算法与可视化接口

### 9.1 算法契约

建立 Qt-free 或 QtCore-only 的稳定契约：

~~~cpp
struct AlgorithmRequest {
    AlgorithmId algorithm;
    ParameterMap parameters;
    std::vector<DataVersionRef> inputs;
    WorkspaceContext workspace;
};

struct AlgorithmResult {
    std::vector<ProducedAsset> outputs;
    ProvenanceRecord provenance;
    DiagnosticList diagnostics;
};

class IAlgorithm {
public:
    virtual AlgorithmDescriptor descriptor() const = 0;
    virtual AlgorithmResult run(
        const AlgorithmRequest&,
        ProgressSink&,
        std::stop_token
    ) = 0;
    virtual ~IAlgorithm() = default;
};
~~~

要求：

- 参数、输入/输出端口和单位可验证；
- 无 QWidget、QgsMapCanvas 或 Python object；
- 取消、进度和诊断是一等接口；
- 算法结果先落资产/版本，再由 UI 展示；
- provenance 记录算法版本、参数、输入版本、运行环境和近似标记；
- 大数组使用 memory map、Arrow C Data、GDAL dataset、span/view 或领域句柄，避免 JSON；
- QGIS Processing 通过 adapter 使用，不让其参数类型污染领域接口。

### 9.2 调度

- CPU 任务进入有上限的线程池；
- GDAL/QGIS provider 线程安全能力在 descriptor 中声明；
- GUI/QGIS GUI 操作强制回到主线程；
- 取消使用 `std::stop_token`，Qt 层适配为 signal/slot；
- 任务完成只发布不可变结果，不让 worker 修改 UI；
- crash-prone 第三方任务可后续隔离为 worker process，但不是默认。

### 9.3 可视化接口

按三层拆分：

1. **Data source**：切片、曲线、网格、轨迹、元数据和异步读取；
2. **Scene/model**：范围、色表、采样、selection、annotation；
3. **View adapter**：QWidget/OpenGL/QGIS canvas。

同一数据源可被 2D、3D、导出和测试复用。公共 API 不返回 Python 数组；可使用 `std::span`、strided view、Arrow C Data 或 GPU resource handle。

### 9.4 地图与非地图可视化边界

- 地理参考 2D 地图、图层、标注、布局和地图导出全部由 QGIS 承担；
- 测井、地震道集、井间剖面等非 GIS scene 使用专用 viewer；
- 需要地图联动时只交换 domain selection、坐标、范围和时间/层位 ID；
- 不在 geo-viz 中再维护第二个 GIS layer tree；
- 不让 QGIS canvas 成为地震体或测井数据的通用渲染器。

## 10. UI 与 QGIS 工具状态机

### 10.1 从当前规则迁移

当前纯 Python `ToolContext` + `evaluate_tool` 是应保留的正确设计。迁移时把它翻译为：

- 不可变 `ToolContextSnapshot`；
- 纯函数 `ToolPolicy::evaluate(action, snapshot)`；
- `ToolStateReducer` 处理事件并生成新状态/effects；
- `ActionPresenter` 只把结果映射到 QAction enabled/checked/text/tooltip。

不能把规则重新散落到 toolbar、右键菜单、dock 和快捷键中。

### 10.2 建议状态

主状态：

- `NoProject`
- `Browsing`
- `LayerReady`
- `EditingClean`
- `EditingDirty`
- `CapturingGeometry`
- `Validating`
- `Committing`
- `Blocked`
- `Degraded`

正交上下文：

- 当前 workflow stage；
- 当前 active/selected/edit layer；
- provider 可写性与 capability；
- task lock；
- CRS、scale、snapping、topology；
- selection；
- 后台任务和未保存更改；
- 数据版本绑定状态。

### 10.3 关键不变量

1. active layer、canvas current layer 和 edit target 必须解析为同一 `LayerId`。
2. `CapturingGeometry` 必须存在可写的 QGIS edit buffer。
3. 切换 stage、工程或 edit layer 前必须结束当前 map tool。
4. `EditingDirty` 离开时只能 commit、rollback 或显式取消导航。
5. `Committing` 禁止再次编辑、关闭工程或替换绑定。
6. 只有 `CommitCoordinator` 能把 working copy 变成新 DataVersion。
7. QAction、菜单、快捷键和 agent command 使用同一 policy 结果。
8. QGIS tool 析构和 canvas/project 析构次序由 MapSession 明确控制。

### 10.4 事件与 effect

Reducer 接收 `ProjectOpened`、`LayerActivated`、`BeginEdit`、`MapToolArmed`、`GeometryChanged`、`CommitRequested`、`CommitSucceeded`、`CommitFailed`、`StageChanged`、`ShutdownRequested` 等事件。

副作用通过 effect queue 执行，例如 `StartQgisEditing`、`RunTopologyCheck`、`PersistVersion`、`ShowDiagnostic`。执行结果再以事件反馈，避免 signal handler 中递归调用完整业务流程。

## 11. 构建、依赖与打包

### 11.1 构建系统

建议建立顶层 CMake 3.28+ superbuild：

- C++20，MSVC 2022 / clang-cl 为 Windows 主工具链；
- Ninja Multi-Config 或 Ninja；
- `CMakePresets.json` 固定开发、CI、ASan、Release、package preset；
- vcpkg manifest 固定通用依赖；
- QGIS/GDAL/PROJ 使用项目固定源码和已验证构建选项；
- well-log-engine 作为 subdirectory 或安装后 CMake package；
- 所有一方库导出 namespaced targets；
- 禁止依赖开发机绝对路径和环境中偶然存在的 DLL。

初始依赖建议：

| 类别 | 依赖 |
|---|---|
| UI | Qt 6 Core/Gui/Widgets/Concurrent/OpenGLWidgets/Svg/Xml/Test |
| GIS | QGIS core/gui/analysis、GDAL、PROJ、GEOS |
| 数据 | SQLite、zlib/zstd、必要时 Arrow |
| JSON | nlohmann/json |
| 测试 | Catch2 或 GoogleTest 二选一；QtTest 用于 UI |
| 日志 | spdlog 或 Qt logging category 二选一 |
| 打包 | CPack + WiX；必要时单独签名脚本 |

当前 well-log-engine 要求 Qt 6.8+，而 QGIS 桥 CI 使用 Qt 6.11.1。P0 必须做 ABI/build spike，选择一个固定的 Qt 版本。建议优先验证 Qt 6.8 LTS；如果 vendored QGIS 补丁要求更高版本，则以“QGIS + well-log-engine + Windows 部署均通过”为准，不允许各子项目自带不同 Qt。

### 11.2 QGIS superbuild

沿用当前已验证的裁剪：

- `WITH_PYTHON=OFF`
- `WITH_BINDINGS=OFF`
- `WITH_DESKTOP=OFF`
- `WITH_QGIS_PROCESS=OFF`
- `WITH_SERVER=OFF`
- `WITH_3D` 仅在确认使用 QGIS 3D 时开启
- `WITH_GUI=ON`
- `WITH_ANALYSIS=ON`

将现有 bridge CMake 的 QGIS ExternalProject 提升到顶层，生成正规的 imported targets、安装树和运行时 manifest，避免每个扩展重复配置 QGIS。

### 11.3 CI

建议门禁：

1. **fast-core**：格式、静态分析、领域/算法单元测试；
2. **linux-app**：构建应用、QGIS provider smoke、offscreen GUI 测试；
3. **windows-app**：构建应用、启动、打开 fixture、编辑/导出 smoke；
4. **compatibility**：Python/C++ schema 与算法 golden 对照；
5. **sanitizers**：Linux ASan/UBSan，定时运行；
6. **performance**：10 万要素、栅格、地震切片、测井基准；
7. **package-smoke**：在干净 VM/runner 安装，不继承构建机 PATH，验证 provider/plugin/font/license。

与 QGIS 有关的源文件变化必须触发 linux-app 和 windows-app，不能再只依赖手工 workflow dispatch。

### 11.4 Windows 打包

安装包包含：

- 主 executable 和一方 DLL；
- 同一来源的 Qt DLL、platform plugins、imageformats、styles；
- QGIS core/gui/analysis、providers、resources、SVG、必要插件；
- GDAL/PROJ data、数据库和证书；
- well-log-engine 与可视化 DLL；
- VC runtime；
- 字体或明确的字体依赖；
- 第三方许可证、GPL 源码/对应源码获取信息；
- crash dump、日志和诊断 manifest。

使用 `windeployqt` 只能作为起点，QGIS provider、GDAL/PROJ data 与资源必须由显式清单部署。安装后 smoke test 应清空开发 PATH，并验证：

- Qt platform plugin；
- QGIS provider registry；
- CRS transform；
- 打开 GeoPackage/GeoTIFF；
- 画布渲染；
- 编辑提交；
- PDF/SVG/PNG 导出。

### 11.5 许可证

QGIS 为 GPL-2.0-or-later，当前应用已经采用兼容 GPL 许可。正式发布仍需维护第三方 notice、修改源码、构建说明和对应源码提供方式。新增第三方库必须在引入前完成许可证审查。

## 12. 兼容与过渡方案

### 12.1 双产品期

迁移期发布：

- **Legacy/Python 版**：维护现有用户与功能，除阻断问题外冻结桥 API；
- **Next/C++ 版**：逐阶段获得只读、编辑、算法和可视化能力。

同一工程同一时刻只允许一个写者。工程锁包含 app family、PID、host、时间、schema 和 recovery token。

### 12.2 四级兼容验证

1. **结构兼容**：JSON/SQLite schema、ID、枚举、未知字段；
2. **语义兼容**：workspace membership、stage、active layer、lineage；
3. **视觉兼容**：固定 QGIS/字体/尺寸下的 golden render；
4. **行为兼容**：工具可用性、编辑、undo、提交、恢复和导出。

### 12.3 Shadow read 与 dual run

- C++ 先只读打开工程，输出结构化 audit，与 Python dump 对比；
- 纯算法在同一 fixture 上 dual run，比较数值容差和 provenance；
- 编辑用复制工程运行，不让两个实现并发写；
- C++ 写回后由 Python 旧版只读打开验证；若 schema 升级不可降级，则明确标记。

### 12.4 回退

- 每次 schema 写入前复制工程元数据和 catalog checkpoint；
- 数据输出采用新版本，不覆盖 base version；
- installer 支持并存，不共享可变配置目录；
- feature flag 只控制新 C++ 模块，不用于在一个进程内切回 Python QGIS；
- P5 前保留 Python 正式版作为业务回退路径。

## 13. 分阶段实施路线

时间是相对量级，需在 P0 完成后按团队容量校正。

| 阶段 | 目标 | 主要交付 | Exit gate |
|---|---|---|---|
| P0 契约冻结与可行性 | 建立真实基线 | schema 清单、行为快照、Qt/QGIS/WLE spike、迁移 ADR | Windows/Linux 最小 C++ app 直接显示 QGIS canvas；兼容 fixture 完整 |
| P1 C++ 壳与 QGIS runtime | 单 Qt/单 QGIS 生命周期 | MainWindow、MapSession、layer tree、日志、崩溃诊断、CI/package skeleton | 干净机器启动并渲染/导出；无 Python |
| P2 工程/目录只读 | 读取真实项目 | Project/Catalog repositories、workspace、binding audit、只读 UI | V13 fixture 100% 可打开，未知字段保留 |
| P3 地图与编辑闭环 | 替代桥最核心路径 | ToolPolicy、active/edit 状态、QGIS edit、拓扑、commit coordinator、undo/恢复 | 主编图流程可创建、编辑、提交新版本、重开一致 |
| P4 工作流与算法 | 迁移业务执行 | workflow/task、算法 SDK、调度、provenance、核心算法 | 选定 P0/P1 工作流结果与 Python 基线一致 |
| P5 科学可视化 | 覆盖发布必需 viewer | well-log-engine 集成、地震/剖面/三维优先场景 | 发布功能矩阵达标，交互性能达标 |
| P6 兼容写入与切换 | C++ 成为默认 | 完整写入、迁移工具、installer、手册、遥测/诊断 | RC soak、数据恢复演练、签名包、验收通过 |
| P7 清理 | 移除旧生产路径 | 删除 bridge/PySide 打包、归档 Python 产品 | 连续两个稳定版本无阻断回退 |

### 13.1 阶段依赖

P1 可与 P2 的 schema/fixture 工作并行；P3 必须建立在 P1、P2 之上。P4 中 Qt-free 算法可提前开始，但结果发布必须接入 P2 catalog。P5 的 well-log 集成可提前，地震/三维依赖 P4 数据接口。P7 必须在 P6 稳定后执行。

### 13.2 首个可交付竖切

建议首个竖切不是“空 MainWindow”，而是：

1. 打开一个现有 V13 工程；
2. 读取 catalog 和 workspace；
3. 在直接链接的 QGIS canvas/layer tree 中显示一个绑定图层；
4. 进入编辑，移动一个顶点；
5. 拓扑校验；
6. 提交为新 DataVersion；
7. 保存、关闭、重开并验证 lineage。

这条竖切能尽早验证最危险的工程、QGIS、状态机和事务边界。

## 14. 风险与缓解

| 风险 | 概率/影响 | 缓解 |
|---|---|---|
| 迁移规模被低估 | 高/高 | 以用户流程和契约切片，不以目录或行数宣称完成；每阶段有 exit gate |
| C++ 重写引入内存安全问题 | 中/高 | RAII、sanitizer、clang-tidy、禁裸 owning pointer、生命周期测试 |
| QGIS/Qt ABI 和打包仍复杂 | 高/高 | 单一 Qt 版本、superbuild、运行时 manifest、干净 VM smoke |
| 数据 schema 语义漂移 | 中/高 | unknown-field round-trip、cross-implementation contract tests、只读先行 |
| 编辑提交跨文件/SQLite 非原子 | 中/高 | recovery journal、临时文件、幂等 operation ID、故障注入 |
| geo-viz 全量迁移拖延主线 | 高/高 | 分域优先级；地图并入 QGIS；well-log 复用 SDK；地震/3D 后置 |
| Python 科学库缺少 C++ 等价 | 中/高 | 明确算法清单；优先复用成熟 C/C++ 库；开发期 oracle；必要时可选进程外扩展 |
| 视觉结果变化 | 中/中 | 固定字体/Qt/QGIS；golden + 结构检查；允许平台容差 |
| 性能回退被“C++ 应该更快”掩盖 | 中/高 | P0 记录基线，持续 p50/p95、内存、启动、交互和 I/O benchmark |
| 团队同时维护两版 | 高/中 | 冻结旧桥新能力、兼容层有截止日期、按工作流切换所有权 |
| 已合并 V11–V13 被重复实现 | 中/高 | 本文的“保留/复用”矩阵和 PR 重叠审计作为 backlog gate |
| QGIS 4.x 快照升级 | 中/高 | 迁移期固定版本；升级另立项目，不与语言迁移捆绑 |
| GPL/第三方合规遗漏 | 低/高 | CI 生成 SBOM/notice，发布 checklist 和对应源码归档 |

## 15. 测试策略与验收标准

### 15.1 测试金字塔

1. **领域单元测试**：schema、状态机、版本/血缘规则、路径；
2. **repository 测试**：SQLite 事务、WAL、并发读、故障恢复；
3. **QGIS 组件测试**：layer/tree/edit/layout/provider，offscreen 与真实窗口；
4. **算法 golden/性质测试**：数值、拓扑、CRS、随机/模糊输入；
5. **跨实现契约测试**：Python 与 C++ dump/结果比较；
6. **GUI 流程测试**：打开、选择、编辑、提交、保存、恢复、导出；
7. **性能与稳定性**：大数据、反复开关、取消、低内存、异常 provider；
8. **安装包测试**：干净机器、无开发环境、离线启动。

### 15.2 数据兼容验收

- 仓库选定的全部 legacy/V13 fixture 可读；
- round-trip 后所有已知字段语义一致，未知字段原样保留；
- asset/version/run ID、hash、stage、membership 和 lineage 不变；
- C++ 产生的新版本可由 legacy 版只读识别，或被清晰标记为不可降级；
- 故障注入到提交每一步后，重启都能恢复或回滚；
- 不覆盖原始资产，不产生无法归属的孤儿文件。

### 15.3 QGIS/UI 验收

- 生产代码中不存在 `shiboken6`、`getCppPointer`、`wrapInstance`；
- 进程级只调用一次 QGIS init/exit；
- active/current/edit layer 不变量有自动化测试；
- 所有 action surface 对同一 ToolContext 得到一致结果；
- 500 次工程打开—编辑—关闭循环无崩溃、UAF 或 QObject leak；
- 关闭期间到达的 worker 回调不会访问已销毁 UI；
- 无业务代码调用嵌套 `processEvents` 等待渲染；
- QGIS provider、CRS、标注、图例、布局和导出通过 golden。

### 15.4 算法/科学结果验收

- 每个迁移算法有 descriptor、单位、输入/输出、取消和 provenance；
- 离散结果完全一致，浮点结果按算法定义容差；
- 近似/降采样结果显式标记，不能冒充精确结果；
- 同一输入版本与参数可重现；
- 不通过截图相似度替代科学数值比较。

### 15.5 性能验收

P0 固化硬件、数据集和 Python 当前基线；默认门槛建议：

- 10 万要素常用交互 p95 不低于当前已合并性能基线，目标主线程响应小于 50 ms；
- 单要素编辑不得触发整层 GeoJSON/WKT 重编码；
- 打开工程、首帧、编辑提交、布局导出 p95 不超过基线 1.2 倍；
- 稳态内存不超过基线，反复打开/关闭无持续增长；
- 地震轴向切片和测井滚动按各自数据集定义帧率/延迟；
- installer 启动不依赖 PATH、Conda、Python 或开发机缓存。

具体数值在 P0 benchmark 报告中冻结，后续 PR 不得自行放宽。

### 15.6 最终切换验收

- 选定发布功能矩阵无 P0/P1 缺口；
- 生产安装包不含 Python runtime 和桥扩展；
- 连续 RC soak 无阻断 crash/data-loss；
- schema 升级、备份、恢复和降级说明通过演练；
- 用户文档、运维诊断、第三方许可和 SBOM 齐全；
- Python 版仅作为独立 legacy 产品，不再是 C++ 产品运行依赖。

## 16. 建议目录结构

~~~text
paleo-workbench/
  CMakeLists.txt
  CMakePresets.json
  vcpkg.json
  cmake/
    PaleoDependencies.cmake
    PaleoQgisSuperbuild.cmake
    PaleoPackaging.cmake
  apps/
    paleo-workbench/
      main.cpp
      resources/
  libs/
    domain/
    project/
    catalog/
    workspace/
    workflow/
    application/
    qgis/
      runtime/
      map/
      edit/
      layout/
      style/
    algorithms/
      core/
      geology/
      raster/
      adapters/
    visualization/
      core/
      well_log/
      seismic/
      cross_well/
      well_seismic_3d/
    ui/
      shell/
      workstation/
      models/
      dialogs/
  tools/
    pwb-migrate/
    pwb-inspect/
    pwb-render-baseline/
  tests/
    cpp/
      unit/
      contract/
      integration/
      gui/
      performance/
      fixtures/
  legacy/
    README.md
  geo-viz-engine/
  well-log-engine/
  third_party/
    qgis/
    gdal/
    proj/
  docs/
    adr/
    development/full-cpp-migration-v1/
~~~

迁移期间现有 Python 目录保持原位，不应为了外观先大规模移动。只有当对应 C++ 竖切完成并通过兼容门禁后，才把退役代码归档/删除。

## 17. 任务拆分

### Epic CPP-00：基线与 ADR

- CPP-001：冻结主仓、submodule、QGIS/Qt/编译器版本清单；
- CPP-002：导出 Project/Catalog/Workspace schema 与 fixture corpus；
- CPP-003：记录打开、编辑、提交、布局、导出的行为快照；
- CPP-004：Qt 6.8/候选版本 + QGIS 4.2 + well-log-engine Windows/Linux spike；
- CPP-005：ADR——单进程、单 Qt、无嵌入 Python；
- CPP-006：ADR——数据权威、编辑工作副本和提交事务；
- CPP-007：桥 API 冻结规则与 code-owner 门禁。

### Epic CPP-10：构建与应用壳

- CPP-101：顶层 CMake/vcpkg/presets；
- CPP-102：QGIS superbuild 与 imported targets；
- CPP-103：C++ main、QgisRuntime、日志和 crash diagnostics；
- CPP-104：MainWindow、MapCanvas、LayerTree；
- CPP-105：Linux/Windows app CI；
- CPP-106：最小 Windows installer 与 package smoke；
- CPP-107：SBOM、第三方 notice 和源码归档。

### Epic CPP-20：领域、工程与目录

- CPP-201：强类型 ID 和 domain primitives；
- CPP-202：ProjectDocument C++ schema/codec；
- CPP-203：未知字段 round-trip；
- CPP-204：Catalog SQLite repository；
- CPP-205：DataAsset/DataVersion/DataRun 与 lineage；
- CPP-206：Workspace、stage、membership、input set；
- CPP-207：ProjectSession、dirty/save/autosave；
- CPP-208：`pwb-inspect` 兼容审计工具；
- CPP-209：Python/C++ contract test harness。

### Epic CPP-30：QGIS 地图与编辑

- CPP-301：MapSession 与唯一 QgsProject 生命周期；
- CPP-302：layer binding/custom properties；
- CPP-303：layer tree plan 与 V11 顺序规则；
- CPP-304：style/label/project XML 兼容；
- CPP-305：C++ ToolContext/Policy/Reducer；
- CPP-306：active/current/edit layer 统一；
- CPP-307：QGIS map tool 与 edit controller；
- CPP-308：snapping/topology/geometry command 复用；
- CPP-309：CommitCoordinator + recovery journal；
- CPP-310：layout/legend/export；
- CPP-311：删除第二套 render mirror 的 C++ 路径；
- CPP-312：500-cycle 生命周期与故障注入测试。

### Epic CPP-40：工作流与算法

- CPP-401：AlgorithmDescriptor/Request/Result；
- CPP-402：scheduler、progress、cancel、diagnostics；
- CPP-403：provenance 与 catalog output publish；
- CPP-404：QGIS Processing adapter；
- CPP-405：主地质/栅格/拓扑算法迁移清单；
- CPP-406：Python oracle/golden runner；
- CPP-407：workflow/task/command runtime；
- CPP-408：agent command 与同一 ToolPolicy 接轨。

### Epic CPP-50：可视化

- CPP-501：pwb_viz_core 数据、范围、色表、selection；
- CPP-502：well-log-engine 直接链接与 Qt adapter；
- CPP-503：地图/paleo-map 能力归并 QGIS；
- CPP-504：seismic data source 与切片接口；
- CPP-505：地震 2D viewer；
- CPP-506：cross-well scene；
- CPP-507：well-seismic 3D 组合；
- CPP-508：跨视图 selection/range/time 联动；
- CPP-509：geo-viz facade 直导入依赖清理；
- CPP-510：消费 #148 的最终 secondary-layout 契约。

### Epic CPP-60：迁移、发布与清理

- CPP-601：`pwb-migrate` 预检/备份/升级/恢复；
- CPP-602：完整工程保存与锁；
- CPP-603：视觉 golden 和真实数据 UAT；
- CPP-604：性能基线与回归门禁；
- CPP-605：签名 Windows installer；
- CPP-606：用户迁移手册和故障诊断；
- CPP-607：C++ 版默认切换；
- CPP-608：删除 PySide/Shiboken/qgis bridge 生产依赖；
- CPP-609：legacy 归档与支持终止标准。

### 17.1 Backlog 防重复规则

创建上述任务前必须搜索已合并 PR/现有文档。以下能力不得作为“从零实现”重新立项：

- QGIS live layer tree 权威、顺序、可见性、布局和图例；
- active/current/edit layer 统一规则；
- QGIS 顶点/拓扑/几何编辑和相带协同；
- 增量拓扑、LOD、空间索引和零拷贝方向；
- Catalog SQLite、DataVersion/DataRun 血缘；
- Workspace membership、stage policy 和 input set；
- V13 数据入库/使用位置/绑定信息；
- 现有 CI 修复和真实性能 fixture。

这些任务的措辞应是“移植契约、复用核心、建立 C++ parity”，不是“重新设计功能”。

## 18. 决策记录与待确认项

需要在 P0 形成或更新 ADR：

1. C++ 应用分层和依赖规则；
2. 单 Qt/QGIS 二进制闭包；
3. Project/Catalog/Workspace 权威；
4. QGIS edit buffer 与 DataVersion 提交协议；
5. geo-viz 分域迁移；
6. Python 扩展是否永久只允许进程外；
7. 工程 XML 是否继续内嵌；
8. Qt 版本与 QGIS vendor 升级策略；
9. 测试框架、日志库和包管理器最终选择；
10. Windows installer、签名和自动更新机制。

尚不能在本文直接定死的事项：

- 地震三维最终采用 Qt OpenGL、QRhi 还是独立渲染后端；
- Arrow 是否作为所有大数据域统一内存接口；
- QGIS 3D 是否启用；
- Python 科研扩展的正式产品需求；
- `.paleo` 是否最终演化为目录/压缩容器。

这些选择不阻塞 P0–P3 的核心地图与数据迁移。

## 19. 建议立即执行的下一步

1. 评审本文的权威边界和 geo-viz 分域决策；
2. 建立 CPP-00 epic，但先不批量创建实现 issue；
3. 生成 machine-readable schema/fixture 清单；
4. 完成 Qt/QGIS/well-log-engine 最小 C++ spike；
5. 实现只读 `pwb-inspect`，对比 Python/C++ 工程 dump；
6. 用“打开 V13 工程—编辑一个顶点—提交新版本—重开验证”作为首个竖切；
7. 只有竖切验证通过后，再承诺 P4/P5 的详细日期。

## 20. 代码证据索引

本文主要依据：

- `README.md`、`PROJECT.md`、`pyproject.toml`、`requirements-geoviz.txt`
- `native/qgis_render_bridge/CMakeLists.txt`
- `native/qgis_render_bridge/src/bindings.cpp`
- `native/qgis_render_bridge/src/qgis_render_bridge.hpp`
- `native/qgis_render_bridge/src/map_stack_service.hpp`
- `paleo_workbench/qgis_runtime/loader.py`
- `paleo_workbench/ui/qgis_stack/widgets.py`
- `paleo_workbench/ui/qgis_stack/canvas_shim.py`
- `paleo_workbench/ui/qgis_stack/display_canvas.py`
- `paleo_workbench/mapping/qgis_mirror.py`
- `paleo_workbench/mapping/map_render_backend.py`
- `paleo_workbench/mapping_workspace/*`
- `paleo_workbench/project/models.py`
- `paleo_workbench/catalog/*`
- `paleo_workbench/mapping/tool_context.py`
- `paleo_workbench/mapping/tool_availability.py`
- `docs/adr/0057-qgis-backed-map-authoring-workbench.md`
- `docs/adr/0059-qgis-authoring-core.md`
- `docs/development/qgis-cartography-runtime-v11/*`
- `docs/development/qgis-editing-authoring-v12/*`
- `docs/development/geodata-qgis-control-v13/*`
- `.github/workflows/ci.yml`
- `.github/workflows/qgis-renderer.yml`
- `scripts/build-qgis-bridge.ps1`
- `well-log-engine/CMakeLists.txt`
- `geo-viz-engine/README.md` 及各 `geoviz_*` 包

文档中的代码规模是基线日的近似统计，用于迁移量级判断，不作为质量指标或交付计数。
