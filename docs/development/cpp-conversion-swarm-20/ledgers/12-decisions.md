# 12 — Decisions（非显然选择）

D1 **机器路径差异**。任务文本引用 `/home/kevin/projects/paleo_project/main`、
`/home/kevin/.grok/skills/goal-loop/SKILL.md` 等路径在本机不存在。实际仓库是
`/home/kevin/project/paleo-workbench`（origin/main = `35987e13`，与任务给出的
BASE 一致）；goal-loop / karpathy 技能在仓内 `agent/skills/`；worktree 按既有
swarm 惯例放 `/home/kevin/project/worktrees/cpp-conv-12-formation-volume`
（conv-11/15 同目录）。基线、分支名、红线全部照任务执行。

D2 **切片范围（§7 分类）**。几何核移植：formation_volume、horizon_sculpting、
fault_displacement、geomodel/{builders,measurements,section} 全量公开面 +
qc 的三个数值子核（degenerate/edge-manifold/connected-components）+
domain 的 slug 与构造校验语义（错误文案）。**不移植**（findings 逐文件有据）：
scene_adapter（渲染，§4 排除）、demo（自述 NOT production code）、analysis
（geoviz 引擎 pass-through）、lithology 表（测井域）、advisor/models
（业务规则层，无体积/厚度）、real_geological_scene（project/catalog 域）、
exporters（文件格式 I/O + legacy 合成网格）、ModelAssembly/meta 序列化
（ADR-03 持久化层）。用户流程验收（体积/厚度与 Python 一致）不需要它们。

D3 **不复制 domain dataclass 层**。Python 的校验在 frozen dataclass
`__post_init__`；C++ 核直接接收网格/数组参数，把同一组校验（kind 前缀、
MD 严格递增、±inf 拒绝、faces 越界、curtain z 约定等）放进 builders 入口，
`std::invalid_argument` 文案逐字对齐 Python DomainError。理由：meta/序列化
不属本切片，复制 dataclass 层是无消费的死代码（Karpathy §2）。

D4 **QC 只移植数值子核**。四级阶梯/文案/导出门禁是业务约定（QCReport 被
UI/导出消费），C++ 侧尚无消费方；本切片移植 `_tri_degenerate_fraction`、
`_edge_manifold_stats`、`_connected_components`（并查集实现，计数与 scipy
路径等价——Python 自己的 no-scipy 回退即此算法）并以 oracle 冻结数值，
为后续 qc 阶梯切片备料。

D5 **新建严格 even-odd PIP，不复用 mapping_kernel**。builders 走
`geometry_planar.points_in_polygon_vectorized`（PNPOLY 严格 `<`，y1==y2
跳过，XOR），而 mapping_kernel 公开的 `point_in_ring_inclusive` 是带
on-edge 阈值的**另一语义**（class_grid 契约）。复用会改变边界行为；
geomodel 内实现 `point_in_ring_strict`（~15 行）并在 oracle 冻结
与 inclusive 变体的分歧案例。不修改 mapping_kernel 任何文件。

D6 **oracle 冻结容差分档**。同为 float32 且只有 +−×÷ 的链路
（sculpt/smooth/fault 位移/displacement 数组）目标 diff=0；含超越函数的
float32 链路（np.exp vs libm expf）与 LAPACK SVD vs Jacobi 特征分解取
1e-6；float64 求和（formation_volume 的 np.sum 成对求和 vs C++ 顺序和）
取 1e-9 相对。所有容差在 oracle JSON 的 case 内显式携带，测试无魔法数。

D7 **Python 环境**。系统 python3 无 numpy；`paleo_workbench.viz.__init__`
→ adapter → prediction_helpers → `import geoviz`，geoviz.engine 顶层
import PySide6，因此新建 `/home/kevin/project/oracle-venvs/conv12`
（numpy/scipy/PySide6-Essentials/pydantic/matplotlib/pyproj/segyio/
pyqtgraph/PyOpenGL —— 全 wheel，未重编任何 QGIS vendor）。geo-viz-engine
子模块在主 checkout 初始化（`git submodule update --init geo-viz-engine`，
公开仓库源码，非构建）；oracle 生成器以
`PYTHONPATH=<worktree>`（被测模块取自基线 worktree）+
`PALEO_REPO_ROOT=/home/kevin/project/paleo-workbench`（引擎根，供
ensure_geoviz_on_path 解析）运行。

D8 **构建工具链**。本机无 cmake/ninja/make 之外的构建器；cmake 4.4.3 +
ninja 1.13 经 pip wheel 装入 conv12 venv（用户级，不改系统）。生成器
-G Ninja，与任务验证模板一致；资源门禁满足（空闲 RAM ≈55 GiB，-j 2）。

D9 **float32 语义复刻**。numpy NEP 50 下 float32 数组与 python float 的
运算保持 float32（弱标量折返）。C++ 对 float32 路径用 `float` 链路 +
把 double 标量先转 float 再运算；smooth_anneal 的 `(A+B+C+D+E*4)/8`
保持左结合 float 链。sculpt 的 tail/denom 保持 double（python math.exp）
后按需折 float——与 numpy 弱标量行为一致。

D10 **oracle 协议**。沿用 swarm 约定：JSON `null` = NaN（grid 洞）；
2D 网格行主序展平；错误分支冻结 `{"raises": "<原文案>"}`，C++ 捕获
异常后逐字比对（含中文/°/换行）。生成器 import **真实** Python 模块
（D7 环境），期望值零手写。

D11 **测试目标名**。单一 ctest 目标 `geomodel.volume`（任务 §8 指定名），
单可执行文件按 family 遍历同一 oracle JSON；库目标 `pwb_geomodel`，
root CMake 仅追加 `BEGIN CONV-12` 块（option `PWB_BUILD_CONV_12`），
并复用 `PWB_BUILD_MAPPING_KERNEL`/`PWB_BUILD_DATA` 开关联编
（geomodel 测试链接 Pwb::Domain 的 nlohmann JSON，同 mapping_kernel）。

D12 **两轮审核后的语义修正**。subagent#2 对抗性 spec 审核（10 项发现）+
subagent#3 Karpathy 审核（10 项发现）后落地：
- `bilinear_z` 退化网格（1 行/1 列）：Python 让 i0/j0 钳到 -1 后靠 numpy
  负索引回绕（g[-1]=末行）；C++ 复刻为 min() 钳位 + 显式 wrap 读角点
  （首版 max(0) 钳位对 fj≠0 的拾取是错的，Karpathy P0 指出）；
  `thickness_single_column_x{0.0,0.4}` 双案例冻结回绕路径。
- `plane_orientation` 零散布输入（三点重合）：numpy SVD 零矩阵给垂直法向
  dip 0；Jacobi 的任意特征向量会得 dip 90——早返回垂直法向对齐。
- deg↔rad 用预除常数 `kDegToRad/kRadToDeg` 单次乘（math.radians/
  np.degrees 语义），两步 `x*π/180` 在 ~30% 输入上差 1 ulp。
- float32 超越函数链路（np.exp vs libm）容差档定为 1e-4（实测差 ~4e-6）。
- inf 拒绝文案前缀对齐 `{object_id}.z_grid: ...`；smooth_anneal 尺寸失配
  复刻 numpy reshape 文案（`... into shape (6,5)` 无空格）。

D13 **API 面收窄（Karpathy）**。Python 侧私有的助手不下放 C++ 公出头：
`divergence_theorem_mesh_volume`/`z_sign`/`orient_faces_outward`/
`shell_is_closed`/`bilinear_z` 转内部；`build_volume_shell` 去掉无消费方的
name/formation 形参；`MeasurementResult` 增加 `crs` 字段真实存储而非
(void) 丢弃；`Plane` 移除无对应的默认构造。`sculpt_surface_vertices`/
`smooth_anneal_grid` 保留——它们是 Python 公开类 `HorizonSculpting` 的
无状态对应面。

D14 **环境文案边界**。numpy 的广播错误文案随版本变化，不冻 oracle：
`set_heights` 长度失配守卫携带 C++ 自有文案（decisions 内声明）；reshape
文案格式确定故照抄。oracle 容差全部由 fixture 的 `tol`/`rtol`/`z_tol`
字段携带，测试零魔法数（D6 的落实）。
