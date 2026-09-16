# C 线基线：算法/工作流/科学可视化（cpp-science-viz 第一轮）

> 基线：`main@671ee426`（= `cpp-migration-plan-v1` 计划提交之上 d0347da2）。
> 子模块固定 gitlink：`geo-viz-engine@08851951`、`well-log-engine@f845e7ab`（本 worktree 已按 gitlink 初始化）。
> 编写日期：2026-09-16。本文件是 C0 交付物，冻结本轮范围、fixture、容差与 Python oracle 配方。

## 1. geoviz 包清单与主仓调用面

geo-viz-engine 共 9 个 Python 包（`geo-viz-engine/packages/`）：

| 包 | 域 | 主仓调用形态 | 第一轮处置 |
|---|---|---|---|
| `geoviz_common` | 共享值类型/色表/范围 | 经 facade 间接使用 | 不迁移；C++ 侧以 `pwb::viz` 值类型按需重设 |
| `geoviz_map` | 地图渲染/交互 | facade 少量 + A 线 QGIS 承接 | **归 A（QGIS）**，C 不做第二个 GIS layer tree |
| `geoviz_paleo_map` | 古地图 | 主流程古地理编图 | **归 A**；业务模型入 workspace/algorithms 是后续里程碑 |
| `geoviz_plots` | 通用图表 + map_edit | 直导入 1 处（map_edit scene） | map_edit 归 A/拓扑核；非地图 plot 后续里程碑 |
| `geoviz_well_log` | 测井 | 主仓 `WellLogHost`（Python）走 **WLE Python 绑定** | **本轮 C2：直接使用 WLE C++ SDK Qt adapter** |
| `geoviz_seismic` | 地震 | 切片预览、属性、zarr 读取 | **本轮 C3：切片数据源接口 + 数值对照**；viewer 后续 |
| `geoviz_cross_well` | 井间剖面 | 主仓 correlation 页 | 后续里程碑 |
| `geoviz_well_seismic_3d` | 井震三维 | 直导入（seismic_3d_api） | 后续里程碑 |
| `geoviz_well_tie` | 井震标定 | 少量 | 后续里程碑 |

主仓统计（`paleo_workbench/`，基线 SHA）：引用 geoviz 的文件 106 个；其中 `from geoviz import`（facade）66 个文件；直接子包导入集中在 `geoviz_seismic`、`geoviz_plots`、`geoviz_well_seismic_3d`（facade 边界漂移与总设计 §2.5 判断一致）。

主流程真实算法链（本轮 C1 移植对象，冻结）：

```
providers/builtin/seismic_attribute.py  (SeismicAttributeProvider, kernel="c3")
  → paleo_workbench/seismic_attributes.py  (KERNELS["c3"], halo (5,5,5))
    → geoviz_seismic.attributes.compute_coherence_c3   ← Python oracle 实现所在
```

`compute_coherence_c3`（C3 eigenstructure coherence，Marfurt et al. 1998）：半窗口
`win_il/win_xl/win_t`（默认 5），窗口尺寸 `min(2w+1, n)` 且强制奇数，reflect 填充，
对每个 (il,xl,t) 组装 `(n_traces, wt)` 矩阵做 30 次幂迭代，
`coherence = λ_max / total_energy`（`total_energy=Σv²`，=0 时输出 1.0），输出 float32 ∈ [0,1]。
同一路径还被 `VolumeAttributeJob`（全体积分带 zarr 写出）与 `roi_attribute`（交互 ROI）复用。

## 2. 已有 C++ kernel 与可复用 SDK

主仓 `native/` 现有 pybind11 扩展（全部经 `paleo_workbench/native_backend.py::dispatch` 使用，Python 侧均有 byte/数值 parity fallback）：

| 核心 | 函数 | 主流程使用 | 本轮处置 |
|---|---|---|---|
| `seismic_3d_core` | fast_slice_extract / fast_slice_to_indexed8 / fast_resample_volume_3d / compute_coherence_3d(semblance) / marching_cubes_3d | 切片预览 widget、seismic_3d_api | 语义参考；本轮不搬 pybind 包装 |
| `well_log_core` | fast_las_parse_data / minmax_downsample / dtw_match_curves | LAS ingest、测井降采样、DTW 对比 | 参考语义；WLE 已有更强 LAS adapter |
| `map_edit_core`（geo-viz-engine/native） | hit_test / snap_point / validate_ring | 地图编辑（A 线域） | 归 A |
| `grid_render_core` | render_grid_rgba（LUT/gamma/opacity） | 因子图栅格渲染 | 后续里程碑移植（无 pybind 化重构） |
| `layer_model_core` | 层模型 | 预测管线 | 后续里程碑 |

`well-log-engine@f845e7ab`（C++20 SDK，约 4.8 万行）：core/table/scene/session/export_* 全部
Qt-free；`WELLLOG_BUILD_QT_WIDGETS=ON` 启用 `WellLog::QtWidgets`（`WellLogView`，
QOpenGLWidget + `WellLogSession` 命令式 API + `selectionChanged` 等 Qt signals）。
`include/welllog/io/las.hpp` 提供 `LasSourceAdapter::parse` → `WellLogDocument`。
C 线是 WLE SDK 唯一构建者（共同协议 §资源预算 7）。

## 3. 本轮范围（冻结）

**纳入**：
1. `pwb::science` / `Pwb::Science` 算法 SDK：AlgorithmDescriptor、typed ports、params/units、
   `AlgorithmRequestV1`/`ResultV1`（immutable version refs）、stop_token/progress/diagnostics、
   近似标记、`IResultPublisherV1`。核心无 QWidget/QGIS/Python。
2. `pwb::workflow` 最小 task runtime：queued/running/succeeded/failed/cancelled 状态机；
   取消/异常绝不产生成功结果或成功发布。
3. 真实算法移植：`seismic.coherence_c3`（上述生产链冻结对象）+ Python 数值对照 oracle。
4. `pwb::viz`（visualization）：地震体积数据源接口（轴序/shape/strides/采样间隔/单位/
   missing value/endian/ownership）+ in-memory reference backend + X/Y/Z 三轴切片与
   缺失值/NaN/色表拉伸处理；`SelectionEventV1` 契约类型。
5. well-log-engine 直接集成：宿主 QWidget adapter（读真实 LAS fixture、曲线/深度轴、
   范围/选择/滚动、干净关闭），viewer 测试独立于主程序运行。
6. `libs/science_suite` 独立 CMake 入口 + Qt-free/viewer 测试分组 + 后续里程碑矩阵。

**不纳入（后续里程碑，见 01-migration-matrix.md）**：全地震 viewer、SEG-Y/chunked zarr
store 真实读取、井间剖面、三维、非地图 plots、grid_render/layer_model 去 pybind 化、
多视图联动、地图/古地图（归 A）。

**明确不做的**：第二个 GIS layer tree 或地图渲染器；任何 PySide/Shiboken/pybind GUI 包装；
对 geo-viz-engine / well-log-engine 子模块的提交（upstream 缺陷只记 handoff）。

## 4. Python oracle（固定版本与运行方法）

- 解释器：主仓 `.venv/Scripts/python.exe`（只读，禁止 pip install/upgrade）。
- oracle 实现：`geo-viz-engine@08851951` 的
  `packages/geoviz_seismic/geoviz_seismic/attributes.py::compute_coherence_c3`
  （numpy 路径，`use_gpu=False`；不用 CuPy）。
- 运行方法：`PYTHONPATH=<worktree>/geo-viz-engine/packages`，脚本
  `tests/cpp/science/oracle/generate_coherence_fixture.py`（入参：fixture 输出目录）。
  oracle 脚本同时用 `SeismicLoader` 读取 `tests/fixtures/realdata/tiny.sgy` 导出
  地震切片 fixture（8×8×32、dt=2 ms、iline/xline 1..8 step 1）。
- 对照执行方式：CI/本地两步——(1) Python 生成 frozen fixture（输入 .f32 + manifest.json +
  expected .f32 + stats.json 含 sha256）；(2) C++ 测试读取 fixture 比对。
  fixture 一旦冻结，重新生成必须逐字节等价（脚本确定性：固定 seed 的 PCG64）。

## 5. 冻结的 fixture、case 与容差（C1 数值对照）

输入体积（float32，C-order `.f32` + manifest：shape/seed/dtype）：

| case | shape (il,xl,t) | 内容 | 参数 (win_il,win_xl,win_t) |
|---|---|---|---|
| `synth_default` | 24×20×40 | PCG64 seed=20260916 正弦+噪声楔形体 | 5,5,5（默认） |
| `synth_asym_window` | 24×20×40 | 同上 | 3,7,2（非对称窗口） |
| `synth_small_dims` | 4×3×9 | 维度小于窗口（窗口钳制路径） | 5,5,5 |
| `synth_constant` | 8×8×16 | 常数值 2.5（rank-1 窗口；oracle 实测输出 0.99999976，非精确 1.0——float32 幂迭代漂移） | 3,3,3 |
| `synth_nan_region` | 8×8×16 | 内嵌 NaN 块（total_energy=NaN → 输出 1.0 路径） | 2,2,2 |
| `tiny_sgy_real_w3` | 8×8×32 | 真实 tiny.sgy 数据体 | 3,3,3 |
| `tiny_sgy_real_w1x1x5` | 8×8×32 | 同上 | 1,1,5 |

容差（冻结，依据首轮实测最大偏差加安全余量；实测量见 verification.md）：
- `max_abs_diff(C++ , oracle) ≤ 2e-3`（幂迭代 float32 求和顺序差异上限量级 1e-4~1e-3，余量 ×2+）；
- 双方结果都在 [0,1]；全零体（total_energy=0）必须逐元素精确等于 1.0；常数值体按容差对照（见上表注记）；
- stats 对照：expected 的 min/max/mean 已入 stats.json（生成时打印并记录于 verification.md）；
- 离散行为（参数校验）：契约要求 `win_* ≥ 1`（严于 oracle：oracle 对 win<0 经 np.pad 隐式报错、win=0 产生空间退化输出，C++ 一并拒绝并返回稳定诊断码）。

异常/取消/近似标记 case（计入"实际 case 数"，在 test-plan §3 登记）：
- 参数非法（0/负/偶数窗口组合中 Python 侧会钳制的只钳制、会报错的必须报错）；
- stop_token 取消（首个 inline 边界后请求取消 → 返回 cancelled，不发布成功）；
- 近似标记：幂迭代 30 次是"近似算法"（非精确特征值）→ descriptor 固定
  `approximate=true` 并写入 provenance（迭代次数入 params 记录）。

## 6. P0/P1 用户流程优先级与数值/视觉基准

| 优先级 | 用户流程 | 本轮覆盖 | 基准 |
|---|---|---|---|
| P0 | 地震属性（c3 相干体）计算与结果入库链路 | 算法+task runtime+oracle | 数值：§5 容差；provenance 完整性 |
| P0 | 单井测井曲线查看（LAS→曲线/深度轴→选择/滚动） | C2 宿主 adapter + WLE | 真实 A1.Las；选择/范围事件语义 |
| P1 | 地震切片浏览（inline/xline/timeslice + 色表） | C3 数据源+切片处理（无 GUI） | 三轴 oracle + 边界/缺失值 |
| P1 | 地震剖面/三维浏览 | 不纳入 | — |
| P1 | 井间对比 | 不纳入 | — |

视觉基准说明：本轮测井视图验证以「真实 WLE Qt adapter 可运行 + capability report +
渲染像素非空 + 事件语义」为准，不做跨实现截图 golden（WLE 自身 tests/qt 已有像素级
覆盖；跨实现 golden 待 A 线统一 Qt/字体清单后补）。

## 7. 工具链与资源配置（实测）

- 编译器：VS 2022 Community MSVC 14.38（`cl`），VS 捆绑 CMake + Ninja；构建走
  `scripts/cpp-migration/Invoke-ResourceGate.ps1`（共享文件锁 + ≥8 GiB 内存门禁 + 2 jobs）。
- Qt：本机两个候选——主仓 `.venv` PySide6 6.8.0（**不带 CMake 配置**，仅运行时 DLL，不能用于 C++ 构建）；
  `C:/ProgramData/anaconda3` base 的 **qtbase 6.9.2**（带 `Library/lib/cmake/Qt6` 完整开发配置，MSVC x64）。
  A 线 ABI manifest 未发布 → 本轮 viewer 测试使用 conda base Qt 6.9.2 作为**测试配置**
  （满足 WLE ≥6.8），不是最终产品配置；A manifest 发布后按其重建（handoff 记录消费方式）。
- WLE 构建选项：`WELLLOG_BUILD_QT_WIDGETS=ON`、`WELLLOG_BUILD_PYTHON=OFF`、
  `WELLLOG_BUILD_TEXT=OFF`（Windows 无 harfbuzz/ICU pkg-config；text 关闭时视图仍可用，
  仅不装 HarfBuzz 文本引擎）、ZLIB 缺省走 FetchContent 1.3.1。
- 首轮探测可用内存 4.17 GiB < 8 GiB 门禁 → 先完成全部源码/契约/文档工作，构建阶段
  逐次过门禁（协议 §资源预算 5：不做轮询，两次拒绝且无独立工作则记账等待）。
