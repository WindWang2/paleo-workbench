# C 线移交说明（cpp-science-viz 第一轮）

> 分支 `feat/cpp-science-viz`（worktree `C:/Users/wangj.KEVIN/projects/paleo-workbench-cpp-science`）。
> 本文件面向 A/B 线与后续里程碑执行者；构建/测试实际输出见 verification.md。

## 1. 交付物与公共入口

| 交付物 | CMake 目标 | 命名空间 | 头文件根 |
|---|---|---|---|
| 算法 SDK | `Pwb::Science`（静态库 pwb-science） | `pwb::science` | `libs/algorithms/include/pwb/science/` |
| 任务运行时 | `Pwb::Workflow` | `pwb::workflow` | `libs/workflow/include/pwb/workflow/` |
| 可视化核心（Qt-free） | `Pwb::Visualization` | `pwb::viz` | `libs/visualization/include/pwb/viz/` |
| 测井宿主适配（opt-in） | `Pwb::VisualizationWellLog` | `pwb::viz` | `libs/visualization/src/well_log/` |
| 独立入口 | `cmake -S libs/science_suite -B build/cpp-science` | — | — |

关键头文件：契约 `pwb/science/{types,algorithm,publisher,registry,outcome}.hpp`；
算法 `pwb/science/algorithms/coherence_c3.hpp`；任务 `pwb/workflow/task_runtime.hpp`；
切片/选择 `pwb/viz/{seismic_volume,selection}.hpp`。

## 2. A 线如何消费

1. **算法结果入库**：A 在 `libs/application/adapters/` 实现
   `pwb::science::IResultPublisherV1`（把 `AlgorithmResultV1.outputs` 的 VolumeView
   落为 staged asset，再走 B 的 CommitRequestV1 版本事务）。C 不接触 SQLite。
   失败/取消以 `publish_failure` 到达（`cancelled=true` 区分取消）——A 不得把任何
   failure 转成成功 DataRun。
2. **调度接线**：`pwb::workflow::TaskRuntime::submit(algorithm, request, publisher)`
   返回 `TaskHandle`（cancel/snapshot/wait）；取消即 `stop_token`，成功路径 progress
   到 1.0。本轮单 worker；A 的线程池策略在集成时叠加。
3. **测井视图**：`WellLogHostWidget`（真实 WLE `WellLogView`）。A 把它嵌入工作台
   dock；`set_selection_callback` 给 A `SelectionEventV1`（document_id/origin/revision/
   unit/domain），A 广播联动时跳过同 `origin` 防反馈环。**禁止**用 widget 指针或
   `WId()` 做 ID。
4. **SelectionEventV1 / 结果发布**是冻结契约（见 02-contracts.md）；变更需三方评审。

## 3. well-log-engine SDK 构建配方（C 线为唯一构建者）

- 子模块 gitlink：`well-log-engine@f845e7abbbdc3133d28738975d72b2159a2d30f6`
  （主仓 gitlink 固定，未动远端）。
- 选项：`WELLLOG_BUILD_QT_WIDGETS=ON`、`WELLLOG_BUILD_PYTHON=OFF`、
  `WELLLOG_BUILD_TEXT=OFF`（Windows 无 harfbuzz/freetype/icu 的 pkg-config；
  视图无文本引擎仍可用，只是不走 HarfBuzz 管线）、`WELLLOG_BUILD_TESTS=OFF`。
- 本轮 viewer 测试 Qt 来源：`C:/ProgramData/anaconda3` base 的 **qtbase 6.9.2**
  （`-DCMAKE_PREFIX_PATH=C:/ProgramData/anaconda3/Library`），MSVC x64。
  ⚠️ 这是**测试配置**，不是最终产品配置：主仓 `.venv` 的 PySide6 6.8.0 无 CMake
  开发配置不可用于 C++ 构建；最终 Qt 版本等 A 线 ABI manifest（总设计建议 6.8 LTS
  统一），发布前用 manifest 重建并复跑 `science.viewer.*`。
- 编译器/CRT：VS2022 MSVC 14.38 `/MT`-default（CMake 默认动态 CRT `/MD`）；
  与 A 的最终选择对齐时如需改 CRT 需整树重建。
- WLE SDK 的 install-tree 发布（供 A/B 只读消费）**留待 A manifest 发布后**按
  `cmake --install` + commit/Qt/compiler/CRT/config 清单输出；本轮 viewer 测试直接
  同树构建，未发布共享 SDK。

## 4. Python oracle 固定版本与复算方法

- 解释器：主仓 `.venv`（CPython 3.12，只读使用）。
- geoviz oracle：`geo-viz-engine@08851951`（venv 的 editable 安装可能解析到主仓
  副本——两仓同 SHA，生成脚本内置 SHA 断言防漂移）。
- 切片着色 oracle：`paleo_workbench/native_backend.py::_py_fast_slice_to_indexed8`
  @ `671ee426`（纯 Python fallback 语义）。
- 复算：
  `../paleo-workbench/.venv/Scripts/python.exe tests/cpp/science/oracle/generate_coherence_fixture.py --out tests/cpp/science/fixtures/coherence_c3`
  （同目录 `generate_seismic_fixture.py`）。生成物已提交入库；重新生成必须与入库
  版本逐字节一致（stats.json 带 sha256）。

## 5. 已知限制 / 未迁移清单

见 01-migration-matrix.md（M1–M9）与 00-baseline.md §3。要点：
- 地震数据源本轮只有 in-memory reference backend；真实 SEG-Y/chunked zarr 读取
  未实现（#148 secondary layout 只保留接口位，未实现未关闭）。
- 地震 2D viewer、井间、三维、非地图 plots、grid_render/layer_model 去 pybind 化
  均未开始；地图/古地图归 A。
- `coherence_c3` 契约严于 oracle：拒绝 `win_*=0`（oracle 会算出空间退化结果），
  拒绝 2D 输入（生产路径恒为 3D 块）——差异已记录在 00-baseline §5。
- TaskRuntime 为单 worker 最小实现；恢复/断点（Python VolumeAttributeJob 的 band
  resume）未迁移。
- 测试框架为仓内最小 harness（无外部拉取）；A 依赖清单定型后可平移 Catch2/GTest。

## 6. 资源与过程记录

- 全部构建/测试须经 `scripts/cpp-migration/Invoke-ResourceGate.ps1`（共享锁 +
  ≥8 GiB + 2 jobs）。本轮开发期机器可用内存长期 ~4.5 GiB（桌面应用占用 ~26 GiB，
  Available≈Free，非度量问题），门禁多次 exit 75——实际构建/ctest 执行记录见
  verification.md（若标注 blocked-on-memory 则该项尚未运行）。
