# 07-decisions — 内存 DAG 执行器（libs/workflow_engine）

原则：对用户流程更诚实、更少抽象（Karpathy：最小代码、外科手术、可验证成功标准）。

## D1 — 新库 `libs/workflow_engine`，不触碰 `libs/workflow`

- 主计划明文 "DAG 执行器不是 TaskRuntime"：TaskRuntime 是单算法执行+发布层
  （publish-before-terminal、取消线性化），DAG 执行器是多节点编排层。二者只有语义
  词汇共享，没有代码共享——不继承、不组合、不改 task_runtime 对外契约（§6 硬边界）。
- 命名空间 `pwb::workflow_engine`；Qt-free、Python-free；链 `Pwb::MappingKernel`
  （ops 包装）与 `Pwb::Domain`（Json）。

## D2 — 最小 spec 子集 + 与 06 的对接（不造第二校验器）

- 节点四元组 `node_id / op / params(Json) / depends_on`；绑定标记只保留 `$ref`
  （整包或 `key` 取子键），必须列在 depends_on（Python "data dependencies are
  explicit" 契约）。
- 不含 slots/condition/retry/$slot/$context/schema_version/max_concurrency——这些
  归 06（libs/workflow_spec，尚未落地，其 worktree 只有账本）。06 合流时：spec
  类型换 `pwb::workflow_spec::WorkflowSpec`、校验换 `validate_workflow_spec`、$ref
  绑定换 `resolve_value`。校验消息逐字对齐 Python 以减小合流 delta。引擎对 registry
  的依赖只有 get/has——与 06 的 ActionCatalog 三点依赖面同构。
- 过渡校验器只做：重复 id / 未知 op / 依赖存在 / 自依赖 / $ref 位置 / $ref key
  类型 / 含 `$ref` 但键集不精确（多了别的键）→ fail-closed 拒绝（Python 同样拒绝，
  文案改为 C++ 诚实版，因为 Python 消息提到本切片不存在的 $slot/$context）/
  Kahn 环。**不**做成分叉的完整校验器（不复制 condition-tree、slot、binding
  白名单等 06 范围）。
- 已声明的两处 Python 伪影不复刻（审核轮 1/2 补记）：
  1. duplicate-id spec 上 Python 字典折叠会追加 `"dependency cycle among nodes
     []"`（空伪影）——C++ 空 leftover 不追加；**非空** leftover（真实环）一律照报
     （Python 会报，C++ 也报）。
  2. Python 正则 `$` 接受尾部换行（node_id `"a\n"` 可过）；C++ 字符类扫描更严，
     方向是更 fail-closed，不影响任何冻结案例。

## D3 — 状态机子集：六态节点 + 四态 run；无 retry、无并行

- NodeState 留 pending/running/succeeded/failed/cancelled/skipped；**unavailable 不
  留**：Python 的 unavailable 来自 ActionUnavailableError/ImportError（缺生产后
  端），C++ 注册表函数是进程内普通函数，"能力缺失"在本层只以 unknown-op（验证期
  拒绝）形态出现。06/harness 接线切片若引入不可用语义，再加态。
- RunState 留 running/completed/failed/cancelled；**interrupted 不留**：interrupted
  是 checkpoint/resume 世界的状态（无 store 可恢复 = 无中断面）。
- 无 retry：最小 spec 无 retry 字段；引擎层失败即终局（Python 默认
  max_attempts=1 时行为一致）。
- 顺序驱动：Python 默认 max_concurrency=1 走 `_drive_sequential`；并行驱动是
  ThreadPoolExecutor + governor 的接线面，本切片无 governor。取消测试用后台线程
  cancel + op 内显式检查点（ADR-2：诚实检查点，不假中断）。

## D4 — 取消语义三窗口（对照 Python/scheduler/ADR-2）

1. 节点边界：引擎每节点执行前查 token，已取消 → 未跑节点全部 CANCELLED("run
   cancelled")，run CANCELLED（已完成节点保持 SUCCEEDED——Python
   cancel_between_nodes 语义）。
2. op 内部：op 查 `token.throw_if_cancelled()` 抛 `Cancelled` → 该节点
   CANCELLED("cancelled: workflow run cancelled")，其余 pending
   CANCELLED("cancelled at <node_id>")（Python _cancel_pending 文案）。
3. 运行前：预取消 token → 零节点执行，run CANCELLED。
- CancelToken = `std::atomic<bool>` + geoviz 形状接口（is_cancelled/cancel/
  throw_if_cancelled）；无 Event/cv 等待面（本切片 op 用轮询，50ms 级，测试用
  started-标志同步，无数据竞争）。

## D5 — 节点失败文案：消息本体逐字，异常类型名不复刻

- Python 失败 error = `"{TypeName}: {msg}"`（TypeName 是 Python 异常类）。C++ 注册
  表函数抛 `std::invalid_argument` 等标准异常，类型名不是对账面；NodeRun.error 取
  `e.what()` 本体。oracle 冻结的是 interpolate 的 validate 消息本体（"Insufficient
  sample points (0); at least 2 valid points required for spatial
  interpolation."），与 C++ kernel 抛出的串逐字一致（kernel 已被 mapping_kernel
  oracle 冻结同款）。
- 绑定失败与执行失败的下游 skip_reason 尾巴对齐 Python 两条分支（engine.py:607/
  709）：绑定失败 = `"upstream <id> failed: <cause>"`；执行失败 =
  `"upstream <id> failed"`。绑定在 op 调用**前**独立进行（Python
  bind_parameters 同构）。非 std::exception 的 op 异常（`throw 42` 级误用）落
  FAILED("unknown non-standard exception")——运行诚实落地，绝不击穿引擎。

## D6 — 数据流：Json 投影 + std::any 载荷

- 引擎核只见 `Json`（NodeRun.outputs，对应 Python `_jsonable` 投影 + $ref 解析面）；
  op 另可返回 `std::any payload` 携带类型化产物（本切片：FactorDataset/FactorGrid）。
  拒绝的备选：variant<monostate,FactorDataset,FactorGrid>（把 mapping 类型焊进引
  擎核）与纯 std::any 无投影（丢日志/绑定面）。Json NaN 序列化为 null（nlohmann
  默认），oracle 生成器同款（non-finite→null）。
- `extract_factors` op 输出 points 为 **4 元组行** `[x, y, value, qc_flag]`（审核
  轮 2 修正：本文曾误记 7 字段；实现、头契约、oracle 生成器三处自洽均为 4 元组；
  well_id/well_name/formation 在 typed payload FactorDataset 里，不进投影面）；
  `interpolate_idw` op 经 `samples` $ref 消费，CRS 经 `{"$ref": <extract>,
  "key": "crs"}` 从上游链式流入（Python interpolate_factor 用 dataset.crs 解析
  distance policy，不是插值选项）。**空 extract 产出不是失败**（Python 同构），失
  败发生在下游 interpolate 的 validate——两节点流程的天然短路案例。

## D7 — 注册表：显式注册，无静态自注册

- `NodeRegistry::register_op(name, fn)`；M1 先例（host 侧显式注册 E 四算法，无静
  态自注册）。内置 `register_builtin_ops`（noop）；`register_mapping_ops` 注册
  `extract_factors`/`interpolate_idw`。测试在自己的 registry 实例上加 fail/
  block_until_cancelled 测试 op（lambda 捕获，不经生产注册表）。
- op 签名 `NodeResult(const Json& bound_params, const CancelToken&)`——最小闭包；
  不传 run/registry（Python 侧 handler 也只拿 context+params）。

## D8 — stdout 级日志：可注入 sink，默认 std::cout

- 行格式（前缀 `[workflow_engine] `）：
  `run <workflow_id>: start (<N> nodes)` / `node <id> (op=<op>): running` /
  `node <id> (op=<op>): succeeded in <ms> ms` / `node <id> (op=<op>): failed: <err>` /
  `node <id>: skipped (<reason>)` / `node <id>: cancelled` /
  `run <workflow_id>: <completed|failed|cancelled>`。
- Logger 是 `std::function<void(const std::string&)>` 注入（测试捕获断言"每个节点
  有 stdout 级日志"），默认写 std::cout 并 flush。不用 syslog/Qt/log4q——Qt-free。

## D9 — CMake：BEGIN CONV-07 追加块

- option `PWB_BUILD_CONV_07`（默认 OFF）→ `add_subdirectory(libs/workflow_engine)`；
  ON 但 MappingKernel 未开 → FATAL_ERROR（fail-closed，同 D/E 门先例）。测试目标
  `workflow_engine.run`（单一可执行，fixture 路径编译定义注入，mapping_kernel 同
  款）。不动其他 CONV 块、不整理根 CMakeLists。

## D10 — oracle 生成器落点与案例

- `tools/oracle/generate_workflow_engine_fixtures.py`：import 真实
  `GeologicalMappingPipeline.extract_factors` + `interpolate_factor`
  （geological_pipeline），冻结：
  1. 链案例 ×2（extract→idw，不同 options：grid_n=12/power=2.0/EPSG:3857 与
     grid_n=10/power=1.0/kNN3）——extract 输出（point_count/unit/points 全量）+
     idw 输出（grid_x/grid_y/grid_z 全量、statistics、n_samples、distance_policy、
     annotation）。
  2. 失败案例 ×1——无值 records → extract 成功 0 点 → interpolate 抛 validate
     消息本体。
  3. 消息案例：环/未知 op 等校验消息由 C++ 测试按 Python 文案字面断言（文案即
     oracle，生成器侧以真实 validate_workflow_spec 冻结 problems 列表佐证）。
- 生成器是测试工具（与既有 tools/oracle/*.py 同类），不是生产代码；允许清单外落点
  在此显式声明理由：既有约定目录，oracle 必须可再生成。
- C++ 侧数值阈值沿用 mapping_kernel 测试：grid_z(float32) ≤1e-6、axes ≤1e-12、
  statistics ≤1e-9。

## D11 — 验收流程（用户流程口径）

两节点 spec（extract→idw，再加一个下游 noop 证明"阻止下游"）在 C++ 引擎跑完：
成功链产出 FactorGrid（typed payload + Json 投影，数值对冻结 oracle）；中游失败
（0 点 → interpolate invalid_argument）→ 该节点 FAILED、下游 SKIPPED、run FAILED；
取消 → run CANCELLED 且已完成节点诚实保留 SUCCEEDED。
