# Prompt C — C++ 算法、工作流与科学可视化

将本文件全部内容作为一个独立开发任务的输入。GOAL 模式执行，并使用 `agent/skills/goal-loop/SKILL.md`。

## GOAL

在 `feat/cpp-science-viz` 独立 worktree 中交付 C++20 科学计算与可视化首轮实现：稳定的算法/任务/结果契约，至少一个真实主仓算法与 Python 数值对照，直接使用 well-log-engine 的真实测井视图，以及地震切片数据边界与确定性测试。按 geo-viz-engine 分域迁移策略提供后续实施矩阵，以本轮全部 Oracle 为完成依据。

对应总设计 CPP-40/CPP-50。第一轮覆盖一个真实算法和测井/切片竖切；全地震、井间和三维迁移留在后续明确里程碑，不能用空 viewer 或 stub 宣告全 geo-viz 已迁移。

## 启动与隔离

1. 阅读共同协议 `01-parallel-development.md`、总设计、goal-loop、`CLAUDE.md` 和适用 AGENTS。
2. 工作目录 `C:/Users/wangj.KEVIN/projects/paleo-workbench-cpp-science`；分支 `feat/cpp-science-viz`；核验 `cpp-migration-plan-v1` 为祖先。
3. 缺少 worktree 时，确认目录/branch 都未存在后，从主仓执行 `git worktree add -b feat/cpp-science-viz ../paleo-workbench-cpp-science cpp-migration-plan-v1`；已有则复用。
4. 注册/恢复对应原生 goal；最多 15 轮；根账本追加 CPP-C，遵守 goal-loop 的真实验证和卡住升级。
5. 审查主仓 #1301/#1303/#1297–#1299 与 geo-viz 最新 PR/issues，沿用固定 gitlink。geo-viz #148 是 secondary layout 的独立任务，本 prompt 消费它的接口/结论，不复制或擅自关闭。
6. 全局一个重型任务槽，禁止 subagent；编译/测试 2 jobs，线程库限流；至少 8 GiB 可用内存。C 只构建自身/WLE，QGIS SDK 归 A；缺运行时则继续 Qt-free 工作。

## 唯一写入范围

`libs/algorithms/`、`libs/workflow/`、`libs/visualization/`、`libs/science_suite/`、`tests/cpp/science/`、`docs/development/cpp-science/`。

不改顶层 CMake、Project/Catalog schema、主 UI、旧 Python 包或 submodule gitlink。不在 geo-viz 或 well-log-engine 子模块里提交变更；若确有 upstream 缺陷，在 handoff 记录精确现象和小 patch 建议，主仓通过自己的 adapter 推进。

## 必查代码

- `geo-viz-engine/README.md`、facade 和九个 Python 包的 public API
- 主仓对 `geoviz` / `geoviz_*` 的真实 imports 与调用
- `well-log-engine/CMakeLists.txt`、include/src、Qt adapter、test 和 examples
- `native/{grid_render_core,seismic_3d_core,well_log_core,layer_model_core}/`
- `geo-viz-engine/native/map_edit_core/`
- 主仓 workflow、算法 registry、任务 progress/cancel 和 provenance
- 现有性能/golden/真实格式 fixtures；geo-viz issue #148

稀疏工作区没有初始化子模块时，读取主仓相同 SHA 的只读 checkout，或按固定 gitlink 初始化所需一个子模块；不 recursive update 全部依赖。

## 交付步骤

### C0：清单和边界

在 `docs/development/cpp-science/` 生成 baseline、migration-matrix、contracts、test-plan：
- 全部 geoviz public API/主仓调用点按地图、plot、测井、地震、井间、三维分类；
- 已有 C++ kernel、可复用 C++ SDK、必须移植和本轮不纳入的功能；
- P0/P1 用户流程优先级与数值/视觉基准；
- 保留 Python oracle 的固定版本和运行方法。

地图/古地理地图进入 A 的 QGIS；C 只迁科学数据、色表/数值和非 GIS viewer，不再实现第二个 GIS layer tree。

### C1：算法 SDK 和最小工作流运行

发布 `pwb::science` / `Pwb::Science`：
- AlgorithmDescriptor、typed ports、params/units；
- AlgorithmRequestV1 / ResultV1、immutable version refs；
- stop_token、progress、diagnostics、近似标记；
- IResultPublisherV1，用于把结果交给 A 的 B-adapter，C 不写 SQLite；
- task 状态最小状态机：queued/running/succeeded/failed/cancelled；取消或异常不能产生成功结果；
- 核心不依赖 QWidget/QGIS/Python，数据使用有生命周期的 view/span/mmap，异步不能悬挂。

选定一个当前主仓真实算法（例如已有 C++ 栅格或地震切片核中确实被主流程使用者）。在 baseline 冻结选择、数据与容差，再移植/复用其核心，移除 pybind 对生产接口的依赖。不得为了容易通过只添加 identity/demo 算法。

### C2：well-log-engine 直接集成

启用现有 C++ SDK 的 Qt Widgets/OpenGL adapter，关闭 Python bindings；使用与 A 确定的 Qt/compiler/CRT 一致的配置。若 A 的 ABI manifest 尚未发布，可继续 Qt-free 核心和 API 工作，不能自选另一套 Qt 作为最终产品配置。

建立自己的宿主 QWidget adapter：
- 读取真实小型测井 fixture；
- 显示曲线/深度轴；
- 范围变更、选择和滚动；
- SelectionEventV1 携带稳定 domain ID、单位、origin/revision，避免联动反馈环；
- 清晰关闭和数据 ownership；禁止 Shiboken 或整数 widget 地址；
- viewer 测试可独立于主程序运行。

不要把 Python geoviz_well_log 行对行重写；先建立与现有 WLE 的能力矩阵，再补主流程确实缺的宿主适配。

### C3：地震切片接口与正确性

定义有明确轴顺序、shape、strides、采样间隔、单位、missing value、endian 和数据 ownership 的 C++ 数据源接口。

本轮实现/复用一个 in-memory 或小型 mmap reference backend 与切片处理：
- X/Y/Z 三轴切片；
- 非对称尺寸/strides，边界、无效索引和取消；
- NaN、缺失值、色表/范围处理；
- 与 Python oracle 对比数值；
- 不一次性复制完整大体积数据；
- secondary layout 可扩展但不重新实现 #148；
- 明确本轮是否支持真实 SEG-Y/chunked store，未支持不能标记完整地震 viewer 完成。

### C4：模块发布与后续 roadmap

提供 `libs/science_suite/CMakeLists.txt` 独立入口，区分 Qt-free tests 与需要真实 WLE/Qt 的 viewer tests。显式 opt-in 的真实 viewer 目标缺依赖要失败，不能通过静默 skip 伪装通过。

后续里程碑列出：其他核心算法、geoviz_plots 非地图部分、seismic viewer、cross-well、3D 和多视图联动；逐项标注依赖、复用对象与真实验收。本轮不创建无限任务链去追完全部 5 万行 Python。

## 本轮 Oracle（全部必选）

1. science-suite C++20 独立 configure/build 退出码 0，核心无 Python runtime/Qt Widgets/QGIS 依赖。
2. 至少一个被现有主流程使用的真实算法，在冻结 fixture/case 上与 Python 对照满足已写明容差；含异常输入/取消/近似标记测试，记录实际 case 数。
3. 最小 task runtime 的成功/失败/取消分支真实测试通过；产物携带 inputs/version/params/provenance，取消不发布伪成功。
4. 真实 well-log-engine Qt adapter 运行，读 fixture 并绘制曲线/深度轴；selection/range 事件与关闭测试通过。Qt-free fake viewer 不能替代此项。
5. 三轴切片的非对称 shape/stride/边界/缺失值 oracle 全通过，数据生命周期测试通过。
6. 生产路径不包含 PySide/Shiboken/pybind GUI 包装；未引入重复地图渲染/图层树。
7. CTest 实际有 tests 且必选组无失败/无依赖缺失跳过；关键数值/ownership 测试二次复验。
8. 输出 migration matrix、公共 target/headers、sample fixtures、性能基线和 known limitations；顺序 review 修复高优先级问题并提交本分支。

## 收尾与资源释放

生成 `docs/development/cpp-science/verification.md`、`handoff.md`、`ledger.md`。说明 WLE SDK 的 commit/Qt/compiler/CRT/config，A 如何消费 viewer/algorithm/result publisher；给出实际测试输出、commit、未迁移列表。保留 worktree，释放自己的测试/GUI 进程和锁。15 轮或外部资源条件阻塞时如实记录未完成，不启动后台无限循环，不以删减 Oracle 收尾。
