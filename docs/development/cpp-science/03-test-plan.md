# C 线测试计划（cpp-science-viz 第一轮）

> CTest 命名前缀 `science.`（共同协议）。0 tests、全 skip、stub 输出不算通过。
> 测试框架：仓内最小自注册断言头 `tests/cpp/science/pwb_test.hpp`（无外部拉取依赖；
> A 线依赖清单发布后可平移 Catch2/GTest——矩阵 M2 期间评估）。每个测试文件一个
> 可执行文件，退出码非 0 即失败；CTest 逐项注册。

## 1. 测试分组与门禁

| 组 | 目标 | 需要 | CTest 名 |
|---|---|---|---|
| G1 契约 | descriptor/请求/结果校验、不可变性 | Qt-free | `science.contracts.*` |
| G2 算法 oracle | coherence_c3 与 Python 对照（冻结 fixture） | Qt-free + 预生成 fixture | `science.algorithms.coherence_c3_oracle` |
| G3 task runtime | 成功/失败/取消三分支 + 发布不变量 + shutdown | Qt-free | `science.workflow.task_runtime` |
| G4 地震切片 | 三轴/strides/边界/缺失值/生命周期 + oracle | Qt-free | `science.seismic.*` |
| G5 viewer（opt-in） | 真实 WLE Qt adapter：fixture 渲染/选择/范围/关闭 | `PWB_SCIENCE_VIEWER_TESTS=ON` + Qt6.8 + WLE | `science.viewer.well_log` |

- G1–G4 是**必选组**：缺 fixture/配置即失败，不允许 skip。
- G5 显式 opt-in（`-DPWB_SCIENCE_VIEWER_TESTS=ON`）：开启后找不到 Qt/WLE 必须
  **configure 失败**，禁止静默跳过伪装通过；默认 OFF 只构建 Qt-free 核心。

## 2. G2 数值对照细节

fixture 由 oracle 脚本生成并提交入库（`tests/cpp/science/fixtures/coherence_c3/`）：
每个 case 含 `input.f32`、`manifest.json`（shape/seed/params）、`expected.f32`、
`stats.json`（min/max/mean/sha256）。C++ 测试：
1. 逐元素 `max_abs_diff ≤ 2e-3`（00-baseline §5 冻结容差）；
2. 输出范围 ⊆ [0,1]；`synth_constant` case 全 1.0；
3. stats 一致性：mean 相对差 ≤ 1e-6；
4. 重复执行两次结果逐位一致（确定性）。

**实际 case 数**（含异常/取消/近似，写进 verification）：
- 数值 case ×5（synth_default/synth_asym_window/synth_small_dims/synth_constant/tiny_sgy_real[两组参数] = 6 组对照）
- 异常输入 ×4：win≤0（3 个参数各 1）+ 维度不一致体积
- 取消 ×2：首个 inline 后取消 → Cancelled 且不发布成功；开始前取消（queued→cancelled）
- 近似标记 ×1：descriptor.approximate=true 且 provenance.approximate=true 断言
- 进度 ×1：progress 单调且到达 1.0（成功路径）

## 3. G3 task runtime 用例

| # | 用例 | 断言 |
|---|---|---|
| 1 | 成功路径 | 终态 succeeded；publisher 恰一次 publish_success；provenance 含 inputs/version/params |
| 2 | 算法失败（参数非法） | 终态 failed；error_code 非空；publish_failure(code) 恰一次；无成功发布 |
| 3 | 运行中取消 | cancel() 后终态 cancelled；publish_failure(cancelled=true)；无成功发布 |
| 4 | 排队中取消 | queued→cancelled；算法 run 不被调用 |
| 5 | 状态机非法迁移 | succeeded/failed/cancelled 后再 cancel 为 no-op |
| 6 | shutdown 不悬挂 | 析构 join；worker 中 late publish 不崩（publisher 弱化路径） |

## 4. G4 地震切片用例

- 三轴各取首/中/尾索引 + 越界（前/-1/n/+1）→ 越界返回 0 且不写 out；
- 非对称 shape（如 5×3×17）与非对称 strides（crossline-major 置换内存）下切片与
  C-order 参考一致（oracle：Python numpy take/transpose 生成 expected）；
- missing_value/NaN：切片保留 NaN；`map_slice_to_indexed8` 的 min/max 拉伸排除
  非有限值、NaN→0、退化范围→全 0 且 (0,0)——与 `_py_fast_slice_to_indexed8` oracle 对照；
- 生命周期：source buffer 存活期间视图可读；guard 释放后 ISeismicVolume 自身不再
  可达（unique_ptr 释放断言 + 共享保活计数断言）；无全卷复制（大体积分配计数）。

## 5. G5 viewer 用例（真实 WLE，禁 Qt-free fake）

1. `WellLogHostWidget` 读 `tests/fixtures/realdata/A1.Las` → LasSourceAdapter 解析
   （20 采样、DEPT/GR/DT）→ 构建文档 + presentation；
2. 窗口 expose 后 capability_report().graphics_available，`grab()` 非空像素且曲线
   区域有非背景像素（深度轴/曲线绘制证据）；
3. `set_selection(axis, range)` → `selectionChanged` 信号 → host 转 `SelectionEventV1`
   （document_id=稳定 domain ID、unit="m"、revision=文档修订）；
4. viewport range 变更（reset_viewport/set_selection 路径）事件可观察；
5. 关闭顺序：先释放 view 再释放 session；二次关闭/父先销毁不崩（WLE 生命周期语义）。

运行环境：真实窗口（非 offscreen fake），Windows 默认平台插件；通过资源门禁 Test 槽执行。

## 6. Oracle 资产与运行方法（冻结）

- `tests/cpp/science/oracle/generate_coherence_fixture.py`：生成 G2 全部 case；
- `tests/cpp/science/oracle/generate_seismic_fixture.py`：从 tiny.sgy 导出
  crossline-major 置换 raw + expected 切片 + expected indexed8；
- 运行：`../paleo-workbench/.venv/Scripts/python.exe tests/cpp/science/oracle/generate_coherence_fixture.py --out tests/cpp/science/fixtures/coherence_c3`
  （PYTHONPATH 指向本 worktree geo-viz-engine/packages；只读 venv，不安装任何包）。
- 生成物提交入库（评审可复算）；CI/本地验证不依赖生成步骤。

## 7. 通过标准（Oracle 对应）

| 本轮 Oracle | 由哪些测试/检查满足 |
|---|---|
| O1 独立构建退出码 0、核心无 Python/Qt Widgets/QGIS | science_suite configure+build；G1–G4 目标链接检查（无 Qt/Python 接口符号） |
| O2 真实算法 Python 对照 | G2（容差+case 数记录） |
| O3 task runtime 三分支 + provenance + 取消不伪成功 | G3 |
| O4 真实 WLE Qt adapter | G5（opt-in 但本轮必须实际开启执行） |
| O5 三轴切片 oracle + 生命周期 | G4 |
| O6 生产路径无 PySide/Shiboken/pybind GUI、无重复地图栈 | 源检查 + 目标链接清单（verification 记录命令与输出） |
| O7 CTest 有测试且必选组全过、关键二次复验 | ctest 输出 + 复验记录 |
| O8 文档矩阵/review/提交 | docs + review 修复 + 分支 commit |
