# C 线迁移矩阵与后续里程碑（geo-viz 分域策略落地）

> 依据总设计 §7（geo-viz-engine 分域处理）与 01-parallel-development.md 文件归属。
> 「本轮」= cpp-science-viz 第一轮；后续里程碑不创建无限任务链，逐项标注依赖/复用/验收。

## 1. 本轮已交付（详见 verification.md）

| 能力 | 位置 | 复用对象 | 真实验收 |
|---|---|---|---|
| 算法 SDK 契约 | `libs/algorithms`（`pwb::science` / `Pwb::Science`） | providers/contracts.py 语义移植 | science.contracts 测试 |
| 最小 task runtime | `libs/workflow`（`pwb::workflow` / `Pwb::Workflow`） | runtime/task_scheduler.py 状态语义 | 成功/失败/取消三分支真测 |
| `seismic.coherence_c3` | `libs/algorithms/src/geology/…` | 算法语义 = geoviz_seismic@08851951 | Python oracle 对照（00-baseline §5 容差） |
| 地震数据源接口 + in-memory backend + 三轴切片 | `libs/visualization`（`pwb::viz` / `Pwb::Visualization`） | geoviz_seismic chunked.VolumeReader 抽象 | science.seismic oracle + 生命周期测试 |
| SelectionEventV1 契约类型 | `libs/visualization`（Qt-free 头） | 接口握手 v1 | 编译期 + viewer 事件测试消费 |
| WLE 宿主 QWidget adapter | `libs/visualization/src/well_log`（opt-in Qt 目标） | well-log-engine@f845e7ab C++ SDK 直链 | science.viewer 真实 WLE/Qt 测试 |

## 2. 后续里程碑矩阵

| # | 里程碑 | 依赖 | 复用对象 | 真实验收（非 stub） |
|---|---|---|---|---|
| M1 | 剩余地震属性 kernel 移植（envelope/phase/freq/rms/dip/curvature，Python 侧全 numpy） | 本轮 SDK | KERNELS 表 + halo 语义；`_time_axis_kernel` 族 | 每属性冻结 fixture 与 Python oracle 容差对照；TRACE_GLOBAL 时间轴限制测试 |
| M2 | `fast_slice_to_indexed8`/`render_grid_rgba` 去 pybind 化（把现有 C++ 热路径收编进 `pwb::viz`/`pwb::science`，生产接口不经 pybind） | 本轮 SDK + A 线集成开关 | native/seismic_3d_core、native/grid_render_core 现有 C++ 实现 | 与现 Python fallback 的 byte-parity 测试集（#446/#938 系）平移 |
| M3 | 地震 2D viewer（QWidget）+ 色表/范围 UI | 本轮数据源接口 | geoviz_seismic preview/profile widget 语义；WLE 视图模式 | 真实切片渲染 + 滚动/LOD 性能基线（总设计 §15.5） |
| M4 | chunked zarr store / SEG-Y 真实读取 backend | #148 secondary layout 结论（**消费不实现**） | geoviz_seismic chunked.py 语义 + main zarr 布局 | 真实 zarr fixture 三轴对照 + chunk 元数据/切片计划测试 |
| M5 | geoviz_plots 非地图部分（通用 plot API C++ 化） | 本轮 SDK | geoviz_plots 非 map_edit 模块 | 固定数据渲染断言 + 导出 |
| M6 | 井间剖面（cross-well scene） | M3/M4 | geoviz_cross_well + WLE scene/曲线接口 | 真实井数据剖面渲染与联动选择 |
| M7 | 井震三维组合 viewer | M3/M4/M6 | geoviz_well_seismic_3d 组合层语义；**不复制底层数据** | 三维选择/联动 + 内存不超基线 |
| M8 | 多视图 selection/range/time 联动 | A 线主程序 | SelectionEventV1 + A 的跨域接线 | 跨视图联动 E2E（A 集成门禁） |
| M9 | `layer_model_core`/`dtw_match_curves`/`minmax_downsample` 收编 | 本轮 SDK | 现有 C++ 实现 + Python parity 测试 | parity 平移 + provenance 接入 |

归 A 线（C 不重复实现）：`geoviz_map`/`geoviz_paleo_map` 渲染与 layer tree、
`map_edit_core`（hit/snap/validate）、`geoviz_plots` 的 map_edit 部分、fallback 2D 制图后端删除。

## 3. 明确声明

- 本轮**未**支持真实 SEG-Y/chunked store 读取：C++ 数据源接口允许 mmap/chunked backend 扩展
  （含 secondary layout 所需的 chunk 元数据与按轴切片计划字段），但本轮只交付 in-memory
  reference backend；地震 viewer 不标记完成。
- 本轮**未**迁移地图/古地图渲染——不得出现第二个 GIS layer tree（Oracle 6 检查项）。
- 本轮**未**创建 Python 运行时依赖：oracle 脚本只存在于 `tests/cpp/science/oracle/`，
  生产目标（Pwb::Science/Workflow/Visualization 及 viewer）不链接/不加载 Python。
