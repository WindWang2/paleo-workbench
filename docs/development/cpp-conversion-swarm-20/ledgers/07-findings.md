# 07-findings — Workflow DAG 执行器（内存版）阅读记录

全部 §5 文件**全文阅读**后逐符号记录。格式：输入 / 输出 / 空·NaN·并列语义 / 与已有
C++ 核的关系 / 测试缺口。本切片实现范围用 ➤ 标出。

## paleo_workbench/workflow/dag/engine.py（1120 行，全文）

### WorkflowValidationError(ValueError)
- 输入：workflow_id + problems 列表；输出：`workflow '<id>' invalid: <p1; p2>` 消息。
- 空 problems 不该构造（create_run 只在 problems 非空时 raise）。并列：problems 以
  `"; ".join` 顺序拼接，validate_workflow_spec 的输出顺序即消息顺序。
- C++：`pwb::workflow_engine::ValidationError`，`problems` 向量 + 同款 join 文案。
- 测试缺口（Python 已覆盖）：消息只断言子串（"cycle"/"does not exist"…），C++
  对账保持同宽。

### _RunCancelToken / _SyncedToken / _ExternalSyncedToken
- 协作取消：`threading.Event`；`raise_if_cancelled()` raise `TaskCancelled("workflow
  run cancelled")`；`wait(seconds)` 可被取消唤醒。
- _SyncedToken 把 scheduler 的 TaskContext.cancelled 事件汇入同一 token（「scheduler
  事件赢，永不丢」）；_ExternalSyncedToken duck-type 外部 token（is_cancelled 属性 /
  cancelled Event）。取消是 RUN 的一等终态，engine.run 捕获 TaskCancelled 后落
  CANCELLED，而不是向上抛。
- C++：单 `CancelToken`（std::atomic<bool>）+ `Cancelled` 异常，`throw_if_cancelled()`
  文案逐字 "workflow run cancelled"。三个变体不需要——本切片无 scheduler/外部
  token 桥（那是接线切片）。

### WorkflowEngine.__init__ / registry / store 属性
- 依赖注入 registry（动作注册表）、HarnessExecutor、WorkflowRunStore、catalog；
  store 默认落到 `<project>.artifacts/workflows/`。
- ➤ C++ 内存引擎：无 store、无 catalog、无 harness executor——registry 即函数表，
  执行即调用。SQLite/JSON checkpoint 是 catalog 切片的事（§7.5 明令不写）。

### create_run(spec, slot_values, context)
- validate_workflow_spec 全问题列表 → 非空即 WorkflowValidationError（fail-closed，
  任何节点都不执行）。之后 materialize_slot_defaults + slot_schema_problems。
- ➤ C++：`Engine::run` 入口先 `validate_spec(spec, registry)`，问题列表非空抛
  ValidationError。slots 在最小 spec 里不存在（06 对接点，见 decisions D2）。

### run(run_id, ...) 主流程
- 并发防护：同进程同 run 二次 run/resume 拒绝（"concurrent run/resume would
  double-execute nodes"）。COMPLETED/CANCELLED 直返。project_path 不匹配拒跑。
- TaskCancelled → `_cancel_pending("run cancelled")` + `_finalize`：取消是终态落地，
  不向上抛。finally 再 checkpoint 一次。
- ➤ C++：顺序驱动一次 `run(spec, token)`；单进程单 run 天然成立；INTERRUPTED/
  project guard 无内存对应物（无 store 可恢复），decisions D4。

### _drive_sequential（默认 max_concurrency=1 路径）
- 循环：`cancel_token.raise_if_cancelled()` → `_ready_batch(limit=1)` → guard →
  `_execute_node` → checkpoint → notify；batch 为 None（无 pending 无 running）即完
  成，`_finalize`。
- ➤ C++ 引擎就是这条路径的移植：拓扑序遍历 + 每节点前查 token + 每节点执行 +
  stdout 日志。并行驱动（ThreadPoolExecutor + clamp_workers）不在切片内。

### _ready_batch(run, limit) → list | None
- PENDING 且所有 deps 终态才就绪。硬失败（FAILED/CANCELLED/UNAVAILABLE）或任何
  SKIPPED dep ⇒ 该节点 SKIPPED("dependency did not succeed")。带 condition 的节点
  等所有被引用节点终态再判定（条件可引用 depends_on 之外的节点）。
- 返回 None = 全部终态（驱动结束）；返回 [] = 有 running（顺序路径不该发生）。
- ➤ C++：无 condition → 就绪判定 = 所有 dep SUCCEEDED；失败下游由
  `_skip_dependents` 立即标记（见下），就绪循环里只留 "dependency did not
  succeed" 兜底。

### _execute_node(...)（每节点状态机）
- 状态置 RUNNING、attempt+=1、started_at；绑定参数（BindingError → FAILED
  action_status="rejected" + skip 下游）；schema 校验失败 → FAILED("bound
  parameters invalid: …")。
- 成功（success/degraded）：receipt 落地次序 = payload 字段先于终态（torn
  checkpoint 不会声称"成功但空输出"）；outputs 是 `_jsonable` 投影。
- cancelled 状态：节点 CANCELLED + `_cancel_pending("cancelled at <id>")`。
- 失败：failed（或 resource-shed rejected）按 retry.max_attempts 重试（backoff 可
  取消唤醒），耗尽 → FAILED/UNAVAILABLE + `_skip_dependents`。
- ➤ C++：注册表函数只区分 成功返回 / 抛异常（FAILED, error=e.what()）/ 抛
  Cancelled（CANCELLED）；无 retry（最小 spec 无 retry 字段，decisions D3）。

### _skip_dependents(run, node_id, reason)
- 不动点循环：PENDING 且（直接依赖 node_id 或任一 dep 已 SKIPPED）→ SKIPPED
  (skip_reason=reason)；有 condition 的节点不在此标。reason 文案
  `f"upstream {node_id} failed"`。
- ➤ C++ 逐字复刻（含 reason 文案与不动点语义），这是"失败节点阻止下游"的核。

### _cancel_pending(run, reason) / _finalize(run)
- cancel：所有 PENDING/RUNNING → CANCELLED(error=reason)。
- finalize：任一 RUNNING/PENDING ⇒ INTERRUPTED；任一 FAILED/UNAVAILABLE ⇒ FAILED；
  任一 CANCELLED ⇒ CANCELLED；否则 COMPLETED。
- ➤ C++：无 RUNNING/PENDING 残留可能（顺序驱动 + cancel 立即标 CANCELLED），故
  RunState 只保留 running/completed/failed/cancelled 四态；INTERRUPTED 属于
  checkpoint/resume 世界（decisions D4）。

### rerun / resume / cancel / submit_to_scheduler
- rerun：新 run，from_nodes + 传递依赖重跑，其余按 cache_identity 携带（携带条件：
  旧 SUCCEEDED + identity 相等）；parent_run_id 记 lineage。
- resume：RUNNING→INTERRUPTED→PENDING 重跑中断节点（`_prepare_interrupted`）。
- cancel(run_id)：仅对进程内 active run 生效，返回 bool。
- submit_to_scheduler：整个 run 作为 TaskScheduler 的**一个**任务（单队列权威）。
- ➤ 全部不移植：无 store/cache/scheduler 的内存切片无对应物。cancel 通过
  CancelToken 直接实现。

### _checkpoint / CheckpointFailed
- save 失败 ⇒ 全部未完节点回 PENDING、run FAILED、注入 `__checkpoint__` 伪节点、
  抛 CheckpointFailed 驱动即停（fail-closed：不能假装 COMPLETED）。
- ➤ 无持久化 → 无对应物；该 fail-closed 精神体现在：op 抛异常节点必 FAILED，
  下游必 SKIPPED，run 必 FAILED，三者不可伪造。

### 条件树 _evaluate_condition / _condition_node_ids
- kinds：node_succeeded / node_output_equals / node_state / all_of / any_of / not；
  未知 kind → False。
- ➤ 不移植（最小 spec 无 condition；06 的 validation/model 切片拥有条件树的静态
  校验）。

### _RESOURCE_SHED_MARKERS / _is_resource_shed
- governor 拒绝（"resourceexhausted"/"cpu:"/"ram:"/…）按可重试处理；普通 guard
  拒绝不重试。
- ➤ 不移植（无 governor 接线）。

## paleo_workbench/workflow/dag/model.py（430 行，全文）

### NodeState / TERMINAL_NODE_STATES / RunState
- 节点七态：pending/running/succeeded/failed/cancelled/skipped/unavailable；
  终态 = 除 pending/running 外全部（unavailable 也算终态，resume 不再执行）。
- RunState：running/completed/failed/cancelled/interrupted。
- ➤ C++ NodeState 六态（unavailable 不保留——见 decisions D4），RunState 四态。
  to_string 文案与 Python value 逐字一致。

### RetryPolicy(max_attempts=1, backoff_seconds=0.0)
- 固定退避重试；只有 failed 与 resource-shed rejected 可重试；取消/不可用/guard
  拒绝不重试。
- ➤ 不移植。最小 spec 无 retry；引擎层失败=终局。

### NodeCondition（树）+ validate_condition_tree + _CONDITION_KINDS
- 六种 kind；node_succeeded/node_output_equals/node_state 必须带 node；
  node_output_equals 必带 key；all_of/any_of 非空；not 必带子条件。
- ➤ 不移植（06 切片范围）。

### NodeSpec(node_id, action_id, parameters, depends_on, condition, retry, description)
- 节点=纯数据；parameters 是 JSON 字面量或 {"$slot"/"$ref"/"$context"} 绑定标记。
- ➤ C++ `NodeSpec{node_id, op, params(Json), depends_on, description}`——op 即
  action_id 的注册表键；绑定标记只保留 `$ref`（含可选 `key`）。

### SlotSpec / WorkflowSpec(workflow_id, name, nodes, slots, schema_version, max_concurrency, description)
- spec_hash = canonical_hash(to_dict())；node(node_id) KeyError 即诚实失败。
- ➤ C++ `WorkflowSpec{workflow_id, name, nodes}`；slots/schema_version/
  max_concurrency 不保留（顺序驱动）。06 的 libs/workflow_spec 落地后是对接点
  （decisions D2）。

### NodeRun / WorkflowRun
- NodeRun：state/attempt/action_status/from_cache/parameters(绑定后)/
  input_version_ids/cache_identity/output_version_ids/outputs(JSON 投影)/receipt/
  skip_reason/error/started_at/finished_at。
- WorkflowRun：run_id(uuid4.hex[:16])、spec_hash、slot_values、node_runs、项目
  绑定、parent_run_id。
- ➤ C++ `NodeRun{node_id, state, attempt, outputs(Json), error, skip_reason,
  started_at, finished_at}` + `WorkflowRun{spec, state, node_runs(spec 序)}`。
  cache/receipt/version 字段全部不保留。

### canonical_hash / _normalize
- 排序键 + 紧凑分隔符 + ensure_ascii=False + sha256；Enum 取 value；有 to_dict 的
  先 to_dict；其余 str()。
- ➤ 不移植（无 cache identity 需求；06 切片拥有 canonical_hash）。

## paleo_workbench/workflow/dag/store.py（261 行，全文）

### WorkflowRunStore
- 每 run 一个 JSON 文件原子写（mkstemp+os.replace）；load 损坏 → ValueError
  ("checkpoint is corrupted")；list_run_ids 排序。
- cache index：cache_identity → [(run_id, node_id)]，RUNNING run 不入索引；
  (run_id,node_id) 幂等去重；rebuild 按 updated_at 升序种入、读出倒序（新者优先）。
- find_reusable_node 复用契约：identity 相等 + 终态 run + 节点 SUCCEEDED + 非
  from_cache + output_version_ids 非空 + catalog 可解析（可选 integrity 校验）。
  任何一条不满足 ⇒ 重执行（宁可重跑，不假命中）。
- run_lineage：parent 链倒序最老在前，环守卫。
- ➤ 全部不移植（§7.5：不写 store）。语义教训进 decisions：复用必须"证明一致才
  复用"——内存切片没有跨 run 复用面。

## paleo_workbench/workflow/dag/receipt.py（258 行，全文）

### ExecutionReceipt + build_receipt
- 引用不复制：catalog run ids、version ids、action/provider 版本；status 沿用
  ActionResult 六态；degraded 由 warnings 推导 degraded_reason。
- _collect_output_version_ids：artifacts[].version、outputs["version_ids"]、单数
  outputs["version_id"] 三来源去重；receipts 不发明身份。
- _summarize_outputs：标量直录、list/dict 只给长度、句柄值给 "<in-process
  handle>"；environment_identity 给 python/platform/workbench（H12：是"复现说明"
  不是位等承诺）。
- ➤ 不移植（内存切片无 catalog 可引用）。NodeRun.outputs 的 JSON 投影承接
  "_jsonable 输出面"角色。

## paleo_workbench/workflow/dag/reproduction.py（67 行，全文）

### describe_reproduction(run)
- 逐节点：action/参数/输入输出版本 ids/provider/cache_identity/from_cache/executed
  （executed = SUCCEEDED 且非缓存）+ 环境 + contract 文案（bit_identity 只对声明
  deterministic 且输入 ids 匹配的节点承诺）。
- ➤ 不移植；对账精神 = 执行事实与身份分开记录。

## paleo_workbench/workflow/dag/validation.py（264 行，全文；06 主 owns，读以对齐）

### validate_workflow_spec(spec, registry)
- workflow_id 正则 `^[a-z][a-z0-9_.-]{1,63}$`；≥1 节点；max_concurrency≥1；
  node_id `^[a-z][a-z0-9_]*$`；重复 id；未知 action（LookupError）；workflow.* 禁
  入；destructive 禁入；retry.max_attempts≥1；condition 树合法；依赖存在/不自环；
  条件引用存在；绑定合法（$slot 声明过、$ref 必须在 depends_on、$context 白名单）；
  Kahn 环检测（leftover 全报 `dependency cycle among nodes [sorted]`）。
- ➤ 本切片的 validate_spec 是它的**子集**：重复 id、未知 op、依赖存在/不自环、
  $ref 必须在 depends_on、$ref key 类型、Kahn 环（同款消息文案）。消息文案逐字对
  齐 Python（"duplicate node id '<id>'"、"node '<id>': unknown action '<op>'"、
  "node '<id>': dependency '<dep>' does not exist"、"node '<id>': self-dependency"、
  "binding $ref '<ref>' must be listed in depends_on"、"dependency cycle among
  nodes [...]"）。**不**做成分叉的完整校验器（decisions D2）。

### resolve_value / bind_parameters / BindingError
- 递归解析；$slot 未绑定 → BindingError("slot '<n>' has no bound value")；$ref 未
  就绪 → "reference '<id>' has no resolved output yet"；缺 key → "reference '<id>'
  produced no output key '<k>'"；$context 不可用 → "context binding '<k>' is not
  available in this session"。
- ➤ 只移植 $ref 半分支，消息文案逐字（测试冻结）。$slot/$context 归 06 的
  BindEnv。

### slot_schema_problems / materialize_slot_defaults
- unknown slot / required 无值 / schema 校验；显式值覆盖 default。
- ➤ 不移植（无 slots）。

## paleo_workbench/workflow/dag/plan_view.py（203 行，全文；对照状态语义）

- 纯数据 checklist：七态符号 ○●✓✗⊗↷⊘、进度=终态/总数（round 3）、拓扑序保持。
- ➤ 不移植（UI 契约另切片）；但其"进度=终态计数"提示 run 级日志可以给出
  terminal 计数——本切片日志按节点逐条打 + run 终态一行即可，不加进度模型。

## paleo_workbench/workflow/dag/__init__.py（52 行，全文）

- 门面导出表（WorkflowEngine/WorkflowSpec/NodeSpec/NodeRun/NodeState/RunState/
  WorkflowRunStore/ExecutionReceipt/validate_workflow_spec/BindingError）。
- ➤ C++ 两个头（engine.hpp / ops.hpp）即门面，不设伞头（mapping_kernel 先例）。

## paleo_workbench/runtime/task_scheduler.py（707 行，全文）

### TaskCancelled / TaskState / TERMINAL_TASK_STATES
- TaskCancelled 是任务在安全点放弃的异常；任务态 queued/running/cancelling/done/
  degraded/failed/cancelled，后四者终态。
- 语义输入：引擎把 TaskCancelled 落成 run/node 的 CANCELLED（而不是 FAILED）。

### TaskContext
- cancelled Event + check_cancelled() + report_progress（回调异常永不杀死任务）+
  sleep_interruptible(50ms 粒度)。**协作式**：任务看到 cancelled 必须在下一个安全
  点停，工作目录永不删（crash-safe partial results）。
- ➤ CancelToken 契约来源：is_cancelled / throw_if_cancelled / 轮询等待；引擎在每
  节点边界查一次（对应"安全点"）。

### TaskScheduler（队列权威）
- FIFO+优先级（seq 保序）、admission hook（无锁运行、lease 协议）、aging 防饿、
  双泳道（interactive/background strict）、task_key 去重（QUEUED 被 #1224 supersede，
  RUNNING 报错）、cancel 线性化（QUEUED 直接 CANCELLED；RUNNING 置 cancelling+事件
  +cancel_requested；claim 窗口竞态由 handle 标志兜底）、返回值后仍见 cancelled ⇒
  CANCELLED（部分结果不是完成）、shutdown 拒新任务+取消全部+join、历史 200 条上
  限。get_scheduler 单例 = background 并发 1 + interactive 1。
- ➤ 全部不移植——主计划明确 "DAG 执行器不是 TaskRuntime"；本切片顺序驱动，无
  队列。教训：取消的每个竞态窗口都要有一个诚实的可见状态。

## paleo_workbench/runtime/cancellation.py（108 行，全文）

### CancellationToken / CancellationSource / cancel_callable / as_event
- 三种取消方言的适配器而非替代：scheduler TaskContext（check_cancelled）、geoviz
  token（cancel/is_cancelled/raise_if_cancelled→JobCancelled）、裸 callable/Event。
  check-only token 无法被外部 cancel（显式 RuntimeError）。
- ➤ 单一 CancelToken（atomic）足够；方言桥属接线切片。命名对齐 geoviz 形状
  （is_cancelled/cancel/raise_if_cancelled）。

## paleo_workbench/harness/executor.py（466 行，全文；只对照取消/失败语义）

### ActionResult
- 六态 status：success/degraded/failed/cancelled/rejected/unavailable；ok=success∨
  degraded。elapsed_ms、verification、warnings、metrics。

### HarnessExecutor.execute 管线（语义对照表）
- guard 拒绝（schema/permission/context）→ rejected（工作前发生，永不 failed）；
  TaskCancelled → **cancelled**（一等终态，#1137：返回而非上抛，循环不崩）；
  ActionUnavailableError/ImportError → unavailable（诚实缺能力，永不假结果）；
  ResourceExhausted → rejected（governor 原因透传）；其余异常 → failed
  （"{TypeName}: {msg}"）；输出 schema 不匹配 → failed；验证 FAIL → failed、
  WARNING → degraded。
- admission：#1180——admission 模块 ImportError 绝不静默放行（degraded 标记+保守
  默认预算或大声失败）。
- ➤ 内存注册表函数只能产生：返回值=SUCCEEDED、普通异常=FAILED（error=what()）、
  Cancelled=CANCELLED。rejected/unavailable 在 C++ 侧出现于：unknown op（验证期
  拒绝）、空 registry。失败文案 "{TypeName}: {msg}" 不复刻——C++ 侧注册表函数的
  异常类型名（如 std::invalid_argument）不是 Python 类型名，对账只在消息本体
  （decisions D5）。
- _jsonable：dict/list/标量透传、to_dict 优先、ndarray→{shape,dtype,finite_ratio}、
  其余 str()。➤ C++ outputs 直接是 Json（构造时即保证可投影）。

## libs/workflow/src/task_runtime.cpp（340 行，全文）+ task_runtime.hpp（192 行）

- 单 worker 线程 runtime：queued→running→publishing→{succeeded|failed|cancelled}；
  PUBLISH BEFORE TERMINAL；publish 抛异常 success 降级 failed（稳定码
  publisher.publish_threw）；wait() 自等检测；取消线性化 L0-L4（queued 取消永不跑
  算法；run 返回后结局不可撤销）；析构排空队列。
- **对外契约不动**（§6 硬边界）。新引擎与其关系：DAG 执行器是**多节点编排层**，
  TaskRuntime 是**单算法执行+发布层**；本切片引擎不派生、不包含 TaskRuntime
  （主计划："DAG 执行器不是 TaskRuntime"）。共用的只有语义词汇：终态才可观察、
  取消是终态、失败码稳定。

## libs/mapping_kernel interpolator API（interpolator.hpp 133 行 + src/interpolator.cpp 908 行，全文）

### SamplePoint / InterpolateOptions / GridStatistics / FactorGrid
- SamplePoint{x,y,value,qc_flag="ok"}；Options：method(idw|kriging|ordinary_kriging|
  ok)/grid_n(50)/power(2.0)/max_neighbors/search_radius/min_neighbors(1)/
  variogram_model/boundary/crs/distance_policy("planar")。
- FactorGrid：grid_x/grid_y(float64 linspace)、grid_z(row-major float32, NaN=nodata)、
  variance_grid（仅 kriging）、algorithm_id/method/model/variogram_fit/power/range/
  sill/nugget/grid_n/n_samples/duplicates_merged/variogram_bins/domain_masked_cells/
  min_neighbors/max_neighbors/search_radius/distance_policy(+annotation)/statistics。
- 空/NaN 语义：valid = isfinite(value) ∧ qc∈{ok,good,""}；<2 valid → throw
  invalid_argument("Insufficient sample points (N); at least 2 valid points
  required for spatial interpolation.")；全部共点 → "All points are collocated at
  the same coordinate."（多问题 "; " join）。grid_n<10 → 10（clamp）。IDW：
  power=max(1,p)、dist=max(d,1e-12)、exact-hit last-wins、min_neighbors 未满足 →
  NaN。statistics：finite-cell float64 mean/std(ddof=0)，全 NaN → valid_count=0 且
  min/max/mean/std=NaN。distance_policy 由 resolve_distance_policy(crs,declared)
  决定（空 crs+planar → "planar"+未声明注释）。
- ➤ `interpolate_idw` op 直接调用 `pwb::mapping::interpolate_factor`；异常即节点
  FAILED，消息本体冻结进 oracle。数值本身已被 mapping_kernel.interpolator 19 案例
  冻结——引擎 oracle 只需冻结**链路产物**（extract 输出→idw 网格/统计/策略注释）
  与失败消息，不重复冻 IDW 数学。

### dataset_extent / valid_points / validate_dataset / deduplicate_samples /
### model_semivariance / linspace / grid_statistics（公开辅助）
- extent 空 → (0,0,1,1)；pad 10%（span≥0.01）/共线 0.05；linspace endpoint=True 且
  尾元强制 stop；dedup tol=1e-9 均值合并。测试缺口（引擎面）：全 NaN 统计在链路
  中只会因 domain mask 出现——本切片两案例不触 mask，statistics 全有限。

## libs/mapping_kernel extract API（extract.hpp 65 行 + src/extract.cpp 470 行，全文）

### ExtractOptions / FactorPoint / FactorDataset / extract_factors
- records 非 object 跳过；坐标族 project/xy/lnglat(longitude-latitude)/surface 依
  序取**完整对**（0.0 合法、不跨族配对），再 coordinates[0:2] 兜底；缺坐标计数
  skipped_missing；float() 失败计数 skipped_invalid。值查找：精确名→"value"→"val"→
  casefold 别名→attributes/properties/metadata 嵌套（嵌套无 "val"）→派生
  （sand_ratio=100·Hs/Ht、formation_thickness=base−top，带 derived 溯源）。unit
  nullopt→FACTOR_DEFAULTS（porosity→"%"），"" 显式空。永不抛异常：0 命中即
  point_count=0 的空数据集（诊断在 metadata）。
- ➤ `extract_factors` op 包装为 NodeResult.outputs：{factor_name, unit,
  target_horizon, crs, point_count, points:[{x,y,value,qc_flag,well_id,well_name,
  formation}], metadata(诊断原样)}，typed payload=FactorDataset。**空产出不是节点
  失败**（Python 同构：extract 成功但 0 点 → 下游 interpolate 抛
  invalid_argument → 链路在此失败）——这正是 extract→idw 两节点流程的天然失败
  短路案例。

## tests/test_workflow_dag.py（894 行，全文）→ C++ oracle 案例表

| Python 案例 | C++ 对应（workflow_engine.run） |
|---|---|
| linear_run_order_and_receipts（a→b→c 严格序） | noop 三链，日志序断言 + 全 SUCCEEDED + COMPLETED |
| diamond_dependencies（b,c 并列后 d） | 菱形 noop 链 COMPLETED |
| test_binding_failure_fails_node_and_skips_dependents | $ref 缺 key → FAILED + 下游 SKIPPED |
| test_condition_false_skips_node | 不移植（无 condition，decisions D3） |
| unavailable…unavailable+skips | 不移植（无 unavailable 源） |
| retry_then_success / retry_exhausted | 不移植（无 retry） |
| parallel_branches_with_max_concurrency | 不移植（顺序驱动） |
| cancel_between_nodes_propagates（a 成功，c 未跑，全 CANCELLED） | 同构：慢节点起线程，外部 cancel → a SUCCEEDED、其余 CANCELLED、run CANCELLED |
| scheduler_bridge_cancellation | 不移植（无 scheduler 桥），但 op 内部查 token 的模式被 block op 复刻 |
| rerun/resume/cache 组 | 不移植（无 store/cache） |
| project_switch / corrupted_checkpoint | 不移植（无 project/store） |
| static gates（cycle/missing dep/dup/unknown action/$ref 不在 depends_on/$slot/$context） | 子集：cycle/missing/dup/unknown op/$ref-not-in-deps（消息逐字） |

- 额外缺口（Python 无、C++ 切片新增）：op 内抛 Cancelled 的节点级取消（Python 由
  executor 状态转换承接）；typed payload（FactorGrid）可取回。

## tests/test_task_scheduler.py（268 行，全文）

- FIFO 单并发、priority+boost、cancel queued 不执行、cancel running 协作且保留部
  分产物、task_key 冲突、progress/失败回调、shutdown 取消并拒新、全局单例并发 1、
  预算缩放。
- ➤ 语义输入两处：(1) cancel 在协作点才生效且终态诚实；(2) 队列权威唯一——C++
  引擎不做第二个队列（顺序驱动）。其余为 TaskScheduler 域，不移植。

## ADR / 开发文档（命中本专题者，全文）

- `docs/development/scientific-workflow-v8/00-overlap-audit.md`：#1198 交付了
  Workflow DAG/Recipe/ActionSpec V2/六态 ActionResult——"extend only"；DAG 缓存
  O(runs×nodes) 是已知痛点（07 不碰 store）；冲突面 `workflow/**`、`harness/**`。
- `01-architecture.md`：M7 生产化=cache index+run lineage；M8 取消诚实化（ADR-2：
  不可中断的单调用要"诚实阶段+丢弃"，不假中断）——引擎取消点必须放在节点边界
  与 op 内部显式检查，绝不假装能在任意点停。
- `02-verification.md`：全本地验证、无 CI 依赖先例；对抗案例钉法（取消：before/
  mid/late 三窗口）。
- `03-limitations.md`：ADR-4 索引只是查找辅助不是权威——内存引擎没有索引面；ADR-2
  教训直接进入本引擎取消语义。
- `04-review-rounds.md`：三轮审核记录格式（正确性/架构/对抗）——本任务 §8 同款
  三轮。
- `docs/development/cpp-conversion-main-plan.md`：M7 范围="workflow/ 2.8 万行中引
  擎部分"且明确 **"DAG 执行器不是 TaskRuntime"**；方法论=纯算法核先行+冻结
  Python oracle+Qt-free。
- `docs/agents/domain.md` / `issue-tracker.md`：术语用 glossary；PR 经 gh CLI。

## 与 06（feat/cpp-conv-06-workflow-spec，未合并）的对接点

- 06 拥有 `libs/workflow_spec`（pwb::workflow_spec：model+validation+bind 全量、
  canonical_hash、py-repr 消息层）与 ctest `workflow_spec.validate`。**其 worktree
  尚无代码，只有账本**（基线同为 35987e13）。
- 本切片按任务书 §5 在 libs/workflow_engine 内做**最小 spec**（node_id/op/params/
  depends_on + $ref[key] 绑定 + 子集校验），是过渡形态，不是第二校验器：不含
  slots/condition/retry/$slot/$context/canonical_hash。
- 合流路径（06 落地后）：workflow_engine::WorkflowSpec 换成
  pwb::workflow_spec::WorkflowSpec 的别名或适配构造；Engine::run 前置校验改调
  validate_workflow_spec（unknown action 检查经 06 的 ActionCatalog）；$ref 绑定
  改调 resolve_value（BindEnv.results 即引擎的 node outputs 视图）。引擎状态机、
  拓扑驱动、短路、取消、日志全部不受影响。
- 冲突面：无文件重叠（06 只写 libs/workflow_spec+tests/oracle generator；07 只写
  libs/workflow_engine）。消息文案刻意逐字对齐以减小合流 delta。
