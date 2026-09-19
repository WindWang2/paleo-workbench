# CONV-32 decisions — workflow 引擎完成面 + 解释域核

Branch `feat/cpp-workflow-contracts`（base origin/main 5a6373bd）。Scope：`32-findings.md`。

## D1 — 移植面（13 Python 文件 → 双库 13 TU）
workflow_engine 追加：store/reproduction（checkpoint+缓存索引+lineage+复现契约）、receipt/plan_view（执行收据+计划视图）、**run_engine**（engine.py 全语义生命周期：create/run/resume/rerun/cancel、条件、重试、缓存复用、checkpoint 失败语义、双跑/项目守卫）。
新库 workflow_interpretation（8 TU）：constraint_capabilities + algorithm_registry（能力权威）、factor_product + summaries（单因素投影+检查器摘要）、constraint_product + revision（约束产品+解释修订链）、compilation（输入集冻结状态机）、integrated_interpretation（综合解释一等成果+提交编排）。

## D2 — RunEngine 增量而非重写 legacy Engine
engine.hpp 的 CONV-07 最小面有库外消费者（apps/paleo_workbench_platform/self_check.cpp、workflow_runtime node_adapters/runtime_service）。重写将波及平台面与并行分支。决定：新 `RunEngine`（= engine.py WorkflowEngine 全语义）与 legacy `Engine` 并存于 pwb::workflow_engine；头文件内全部使用 `workflow_spec::` 全限定类型规避同 namespace 同名冲突（I3 实证必要）。legacy 退役 = 消费方接线切片（连同 store 驱动切换）。

## D3 — swarm 冻结契约协议（本切片执行方式）
9 路并行实现（≤10 上限）。协调者先行冻结 5 个跨簇头（store/receipt/constraint_capabilities/algorithm_registry/revision）+ 全部 CMake 预接线（文件名先绑定），实现 agent 独占各自 .cpp/.hpp/测试/生成器，禁改 CMake 与冻结头。并行冲突点全部经冻结头解除（engine→store/receipt、registry 双消费、revision↔integrated 互指）。I8 对 revision.cpp 的临时 /tmp stub 在姊妹簇落地后以真源重验（如实记录）。

## D4 — Oracle 与验证边界
8 个生成器真实 import 冻结（determinism：uuid/time/environment_identity/_RunCancelToken.wait 注入或 monkeypatch；{ROOT}/{TMP} 占位；再生成字节一致）。replay 8 二进制 ×2 全绿（598 checks）+ 30 处 negative self-check。**本机无 cmake**：g++ 16.2.1 直连全闭包并编（解释 8 TU + runtime 9 + engine 新 5 + legacy 2 + spec/graph/fusion/factor_host/mapping_kernel 减 ring_ops/domain）；CMake 已按 CONV-06/07 先例接线（PWB_BUILD_CONV_32 门，要求 CONV_25+26B+24；CONV_07 门新增要求 CONV_06）供 CI。旧 workflow_engine.run 回归绿。

## D5 — 延后（如实，均在 run_engine.hpp 注释声明）
parallel drive/scheduler 桥（顺序驱动；主计划「DAG 执行器不是 TaskRuntime」）、`_register_cache_run` catalog provenance 轨（Python 自注复用限于 store）、session 指针 merge/restore（ISessionContext 默认 no-op）。staleness 的 evaluate_verdict/workspace_verdicts/propagate_to_products 三函数依赖未移植的 mapping_workspace 依赖服务，延后至该域切片。

## D6 — 有界偏离与 Python 侧发现（如实）
- **rbf prerequisites 字符串迭代**：Python 源码 `prerequisites=("global solve; ...")` 缺尾逗号→裸字符串被逐字符迭代为 51 项；oracle 冻结即此形状，C++ 以 `python_iterate_str` 复现（Python 权威优先于任务书文字）。
- **register_run 在 try 外**：integrated commit 中 register_run 失败直接传播、无 failed 状态回写（无 run_id 可写）；任务书文字与此矛盾，按 Python 源码冻结（fail-in-register_run 与 fail-in-register_result_asset 两形都冻）。
- **revision._stab 无 dict 分支**：dict 根几何原样透传（docstring 的 9dp 仅作用于列表内数值）；两形均冻。
- FACTOR_FAMILIES 未被 factor_fusion 导出→factor_product.cpp 局部冻结 6 条目（避免跨库改公共面）。
- grid_shape 的 JSON bool 按 Python isinstance(True,int) 计 1/0；state_label 未知状态优雅返回原串（Python 为 ValueError）；receipt from_dict 对 duration_ms/attempt 为 null 时取默认（Python 抛）；compile schema_version 畸形钳回 1。均为不可达或文档化边界。
- KeyError → std::out_of_range（str() 双引号形式另冻）；ValueError 族 → invalid_argument/runtime_error 子类 + python_class()。
- constraint_versions.hpp 读路径非 const → 投影 seam 处 const_cast（注释声明）。
- 浮点格式化：python_round3 半偶、最短往返 str(float)、python_repr_double 复用 factor_host——逐字对账 oracle。

## D7 — 测试资产
5 个解释测试目标 + 3 个引擎测试目标（argv[1] 传 fixture，workflow_graph 先例）；fixtures 共 8 份 ~370KB；生成器 8 个入 tools/oracle/。全部 Qt-free。

## D8 — 后续
31b（service/db 深核）与 CONV-33+（workflow 顶层编排面 orchestrator/recipe/versioning 等）按依赖序；legacy Engine 退役与 RunEngine 平台接线（self_check/node_adapters 切换 + store 落盘路径接 artifact_dir_for）单列消费方切片。
