# 06-findings — WorkflowSpec DAG 纯模型（model.py + validation.py → C++）

基线：origin/main @ `35987e13`。本文件按 §5 清单逐文件索引；被移植文件
（model/validation）每个公开符号一条，其余文件给出符号级覆盖与「与已有 C++ 核的关系 /
测试缺口」。

## paleo_workbench/workflow/dag/model.py（移植目标）

模块 docstring 设计规则：Spec 是数据不是代码（参数是 JSON 字面量或 typed
binding `$slot`/`$ref`/`$context`，条件是声明树，无 eval）；Run 每节点留检查点
（spec 版本、绑定参数、输入版本 id、cache 身份、时间、receipt）；持久化引用
catalog 版本 id，lineage 不复制进 run。C++ 侧对应纯数据 + JSON round-trip。

### `WORKFLOW_SCHEMA_VERSION = "1.0"`
- 常量；WorkflowSpec.schema_version 默认值；recipe.migrate 用它 seed
  `workflow.schema_version`。C++：`constexpr std::string_view`，from_dict 缺省用它。

### `NodeState(str, Enum)`（7 值）
- `pending/running/succeeded/failed/cancelled/skipped/unavailable`。succeeded
  含 degraded（看 receipt）；skipped = 条件假或上游失败；unavailable = 生产能力缺失。
- from_dict 用 `NodeState(data.get("state", "pending"))`——未知字符串在 Python 抛
  ValueError，C++ 抛 std::invalid_argument（对账行为一致）。

### `TERMINAL_NODE_STATES`
- frozenset{succeeded, failed, cancelled, skipped, unavailable}；resume 时不重执行。
- C++：`is_terminal_node_state(NodeState)`，供 07 执行器复用（本切片仅暴露）。

### `RunState(str, Enum)`（5 值）
- running/completed/failed/cancelled/interrupted。completed=全节点终态无失败；
  failed=≥1 节点 failed/unavailable；interrupted=进程/工程中途断，可恢复。
- plan_view._STATE_LABELS 的键按 RunState(self.state) 再解析——非法 state 字符串
  在 Python 会抛 ValueError（C++ from_string 同样抛）。

### `RetryPolicy`（frozen dataclass）
- 字段 `max_attempts:int=1`、`backoff_seconds:float=0.0`。语义：只对可重试结果
  （普通执行失败、governor 资源剥离拒绝）退避重试；guard 拒绝（schema/权限/上下文）、
  取消、unavailable 永不重试。
- `to_dict` 固定两键序 `["max_attempts","backoff_seconds"]`。无 from_dict——
  NodeSpec.from_dict 内联构造（int()/float() 强转，缺省 1/0.0）。

### `NodeCondition`（frozen dataclass，递归）
- 字段：kind、node、key、value(Any)、state、conditions(元组)、condition(子)。
- `to_dict`：恒写 `kind`；node/key/state 仅非 None 时写；value 仅非 None 时写
  （**None 值条件无法序列化**——已知限制，Python 侧同样如此）；conditions 非空写
  列表；condition 非 None 写子对象。
- `from_dict`：kind 取 `str(data.get("kind",""))`；conditions 对列表逐个递归
  （`or []` 容错 None）；condition 仅当是 dict 时递归。未知键被忽略（宽松）。
- 合法 kind 集合 `_CONDITION_KINDS`（模块私有）：node_succeeded / node_output_equals
  / node_state / all_of / any_of / not。错误消息里以 `sorted(...)` 的 py-list-repr
  出现：`['all_of', 'any_of', 'node_output_equals', 'node_state', 'node_succeeded', 'not']`。

### `validate_condition_tree(condition) -> list[str]`
- 未知 kind → 立即单条返回：`condition kind {kind!r} is not one of {sorted set}`（不做其余检查）。
- node_succeeded/node_output_equals/node_state 缺 node → `condition {kind!r} requires a node reference`。
- node_output_equals 缺 key → `node_output_equals requires an output key`。
- node_state 缺 state → `node_state requires a state value`。
- all_of/any_of 空 conditions → `{kind} requires conditions`；再逐子递归追加。
- not 无子 → `'not' requires a condition`（注意消息里带单引号）；有子则递归。
- 顺序：kind 检查 → node 检查 → key → state → conditions → not；多问题按此序拼接。

### `NodeSpec`（frozen dataclass）
- 字段：node_id、action_id、parameters(dict,默认{})、depends_on(元组)、
  condition(NodeCondition|None)、retry(RetryPolicy 默认)、description("")。
- `to_dict` 固定 7 键序：node_id, action_id, parameters, depends_on(list),
  condition(无则 null), retry, description。
- `from_dict`：`str(data["node_id"])`（缺键抛 KeyError→C++ invalid_argument）；
  parameters `dict(...or {})`；depends_on 元组化；condition 仅 dict 时递归；
  retry 内联（见上）；description `str(... or "")`。

### `SlotSpec`（frozen dataclass）
- 字段：name、schema(dict,默认 `{"type":"string"}`)、required(True)、default(None)、
  description("")。rerun-with-new-inputs 契约的 typed 输入槽。
- `to_dict` 5 键序：name, schema, required, default, description。
- `from_dict`：schema 缺失/空 → 回落 `{"type":"string"}`；required `bool(get("required",True))`；
  default 原样（None 语义 = 「无默认」，materialize 时跳过）。

### `WorkflowSpec`
- 字段：workflow_id、name、nodes(元组)、slots(元组)、
  schema_version(=WORKFLOW_SCHEMA_VERSION)、max_concurrency(1,结构性上界)、description("")。
- `node(node_id)`：线性扫描；未命中抛 KeyError
  `workflow {workflow_id!r} has no node {node_id!r}`（C++ out_of_range 同文案）。
- `spec_hash` property = canonical_hash(to_dict())——cache 身份与 spec 身份。
- `to_dict` 7 键序：schema_version, workflow_id, name, description, max_concurrency,
  slots(list), nodes(list)。
- `from_dict`：nodes/slots 缺省空元组；schema_version 缺省常量；
  max_concurrency `int(get(...,1))`；description `str(... or "")`。
- 注意 name 不做 or "" 回落（`str(data["name"])`，缺键抛）。

### `NodeRun`（非 frozen dataclass）
- 检查点：node_id、state(PENDING)、attempt(0)、action_status(None,canonical ActionResult
  状态)、from_cache(False)、parameters(绑定后的具体值)、input_version_ids(元组)、
  cache_identity(None)、output_version_ids(元组)、outputs(dict,$ref 恢复投影)、
  receipt(dict|None,科学执行回执)、skip_reason、error、started_at/finished_at(float|None,epoch 秒)。
- `to_dict` 15 键固定序（含 null）；`from_dict` 各字段缺省回落 + int/bool 强转 +
  `NodeState(data.get("state","pending"))`。
- 与 store.py 的契约：run 文件即 `WorkflowRun.to_dict()` 的 JSON（本切片只做模型与
  round-trip，store I/O 不移植）。

### `WorkflowRun`
- 字段：run_id、workflow(内嵌完整 spec)、state(RUNNING)、slot_values(dict)、
  node_runs(dict node_id→NodeRun,插入序=spec 节点序)、project_name/project_path、
  created_at/updated_at、spec_hash、parent_run_id(V8 M7 lineage,rerun/resume 链；
  None=原始执行)。
- `create(workflow, slot_values)`：run_id=uuid4().hex[:16]；created/updated=now；
  spec_hash 预计算；node_runs 按 spec 节点序初始化为 PENDING。
- `to_dict` 10 键序：run_id, workflow, state, slot_values, node_runs(值列表),
  project_name, project_path, created_at, updated_at, spec_hash, parent_run_id（10+1）。
- `from_dict`：node_runs 反序列化后对 spec 缺失节点 setdefault PENDING
  （容忍 store schema drift）。state/state 非法字符串抛（同 NodeState）。

### `canonical_hash(value)` / `_normalize`
- `json.dumps(_normalize(value), sort_keys=True, separators=(",",":"), ensure_ascii=False)`
  的 sha256 hex。C++：ordered_json 递归按键排序（UTF-8 字节序=码点序）→
  nlohmann dump()（默认紧凑、非 ASCII 原样）→ `pwb::domain::Sha256`（与
  hashlib.sha256 字节一致，头文件注明）。
- `_normalize`：dict 键 str 化+排序递归；list/tuple→list；标量原样；Enum→value；
  有 to_dict 则递归其结果（异常则落到 str()）；其余 str(value)。
  对本模型 JSON 输入只需前两支 + 标量。

## paleo_workbench/workflow/dag/validation.py（移植目标）

### `_NODE_ID_RE` / `_SLOT_RE`
- 均 `^[a-z][a-z0-9_]*$`。node_id/slot name 同一形态。C++ 手写字符判断（无需 regex 库），
  匹配语义=完全匹配（Python re.match+`$`）。

### `CONTEXT_BINDING_WHITELIST`
- 9 键：workspace_id, project_path, active_survey_id, active_well_id, current_map_id,
  selection.active_well_id, selection.selected_well_ids, selection.seismic_cursor,
  selection.depth_range。`$context` 绑定白名单；错误消息 `sorted(...)` py-list-repr
  （9 项按码点序，注意 "selection.*" 排在 "project_path" 之后、"workspace_id" 之前）。

### `validate_workflow_spec(spec, registry) -> list[str]`
- 注册/运行前的 fail-closed 门。问题追加顺序（C++ 必须逐条一致）：
  1. workflow_id 空 或不匹配 `^[a-z][a-z0-9_.-]{1,63}$` →
     `workflow_id {id!r} must match ^[a-z][a-z0-9_.-]{1,63}$`（f-string 花括号还原）。
  2. 无节点 → `workflow needs at least one node`。
  3. max_concurrency<1 → `max_concurrency must be >= 1`。
  4. 逐节点（spec 序）：node_id 不匹配 → `node_id {id!r} must match {pattern}`；
     重复 id → `duplicate node id {id!r}` 且 **continue**（后续检查全跳）；
     registry.get 抛 LookupError → `node {nid!r}: unknown action {aid!r}` 且 continue；
     action_id 以 `workflow.` 开头 → `node {nid!r}: workflow.* actions cannot be nodes of a workflow (meta-workflow recursion is not supported)`（两行源码字符串拼接，单条消息）且 continue；
     risk==destructive → DESTRUCTIVE 拒绝消息（默认 registry 注册期已拒，pragma no cover，
     C++ 目录接口保留该分支）；
     retry.max_attempts<1 → `node {nid!r}: retry.max_attempts must be >= 1`；
     condition 存在 → validate_condition_tree 每条加前缀 `node {nid!r}: {p}`。
  5. slot：每个 slot name 不匹配正则各一条 `slot name {name!r} must match {pattern}`；
     set(名)≠个数 → `duplicate slot names`（单条）。
  6. 第二遍逐节点：depends_on 中不在 seen → `node {nid!r}: dependency {dep!r} does not exist`；
     ==自身 → `node {nid!r}: self-dependency`；condition 引用节点（_condition_nodes）
     不在 seen → `node {nid!r}: condition references unknown node {ref!r}`；
     _binding_problems 每条加前缀 `node {nid!r}: {p}`。
  7. _cycle_problems 追加。
- registry 依赖面：仅 (a) get 是否抛 LookupError (b) action.risk.value 是否 "destructive"。
  C++ 以 `ActionCatalog`（action_id→risk 字符串表）注入；oracle 用真实
  ActionRegistry+ActionSpec 生成。

### `_condition_nodes(condition) -> set[str]`
- 收集 condition.node + 递归 conditions[] + condition（not 子）。只收集引用，无去重问题
  （set）。C++ 返回排序 vector 或 set。

### `_binding_problems(node, seen, slot_names) -> list[str]`
- walk(parameters)：
  - dict 恰有键 `{"$slot"}`：值非 str 或不在 slot_names → `binding $slot {name!r} is not a declared slot`。
  - 键集恰为 `{"$ref"}` 或 `{"$ref","key"}`：ref 非 str 或不在 seen → `binding $ref {ref!r} is not a node in this workflow`；
    在 seen 但不在 node.depends_on → `binding $ref {ref!r} must be listed in depends_on (data dependencies are explicit)`；
    有 "key" 且值非 str → `$ref key must be a string`。
  - 键集恰 `{"$context"}`：值非 str 或不在白名单 → `binding $context {key!r} is not whitelisted {sorted whitelist}`。
  - 含 "$ref"/"$slot"/"$context" 之一但键集不匹配 → `binding objects must be exactly one of {"$slot": name} / {"$ref": node} / {"$context": key}`。
  - 其余 dict → 递归 values（**键不查**）；list → 递归元素；标量忽略。
- 顺序：dict 分支按源码序短路；多问题按遍历序（Python dict 插入序=JSON 序）。

### `_cycle_problems(spec) -> list[str]`
- Kahn：indegree 只数存在于 spec 的 dep；queue 初值=sorted 入度 0（**pop() 从尾**——
  LIFO，但终集与处理序无关）；visited==N → 空列表；否则
  `dependency cycle among nodes {sorted leftover}`——**leftover 含环的下游节点**
  （如 a↔b 环 + c 依赖 a → `['a', 'b', 'c']`）。消息是 py-list-repr：`['a', 'b']`。
- **oracle 实测怪癖（必须复刻）**：`visited == len(spec.nodes)` 按**节点条目数**计，
  而 indegree/consumers dict 按 node_id 去重——因此 duplicate node id 的 spec 即便无环
  也会追加一条 `dependency cycle among nodes []`（frozen 案例
  `duplicate_node_id_skips_action_check`）。C++ 若按去重集合比较 visited 就对不上账。

### `BindingError(ValueError)`
- 运行时绑定失败（fail-closed）。C++：`class BindingError : std::runtime_error`。

### `_context_value(context, key)`
- 含 "."：head.tail 两段 getattr；任一层 None → 值 None。值 None → 抛
  `context binding {key!r} is not available in this session`；tuple→list（Python 特有，
  C++ JSON 无 tuple，记 deviations）。

### `resolve_value(value, *, run, results)`
- dict 键集恰 `{"$slot"}`：run.slot_values 无该名 → `slot {name!r} has no bound value`。
- 键集 `{"$ref"}`/`{"$ref","key"}`：results 无该节点 → `reference {nid!r} has no resolved output yet`；
  带 key：outputs 非 dict 或缺 key → `reference {nid!r} produced no output key {key!r}`；
  无 key：整个 outputs 原样返回。
- 键集 `{"$context"}`：`_context_value(run.context, ...)`。
- 其余 dict/list 递归（保插入序）；标量原样。
- C++ 载体：`BindEnv{ slot_values(Json object), results(map<string,Json>),
  context_values(map<string,Json>) }`；map 命中且非 null 视为可用。

### `bind_parameters(node, *, run, results)`
- = resolve_value(node.parameters, ...)。执行器在 07 接线（engine.py:604/885 已确认调用点）。

### `slot_schema_problems(spec, slot_values)`
- 未知 slot → `unknown slot {name!r} (declared: {sorted known})`；
  声明 slot 有值 → `validate_parameters(slot.schema, value, label=f"slot {slot.name}")`（见下）；
  required 且 default 为 None 且无值 → `required slot {name!r} has no value`。
- 顺序：先全部 unknown（按 slot_values 迭代序=JSON 序），再按 spec.slots 序。

### `materialize_slot_defaults(spec, slot_values)`
- 复制后为「缺席且 default 非 None」的槽填默认；显式值胜。engine.create_run 先
  materialize 再 schema 校验。

### 依赖 `providers.execution.validate_parameters(schema, parameters, label)`（需一并移植）
- 依赖无关 JSON-schema 子集：type（含列表 union：任一已知成员匹配即过；全未知成员
  → `expected one of [...] (no known JSON type in union)`）、enum、minimum/maximum、
  minItems/maxItems、items 递归、properties 递归、required、additionalProperties
  （仅显式 false 才拒）。
- 类型映射：object=dict, array=list, string=str, integer=int, number=int|float,
  boolean=bool, null=None；integer/number 拒绝 bool。
- 消息格式（C++ 用 py-repr/py-type-name 复刻）：
  - `{path}: expected {expected}, got {type(value).__name__}`（类型名映射 dict/list/str/int/float/bool/NoneType）
  - `{path}: expected {expected}, got boolean`
  - `{path}: unknown type {expected!r}`
  - `{path}: {value!r} not in enum {enum!r}`
  - `{path}: {value} < minimum {m}` / `{value} > maximum {m}`（str() 数字渲染）
  - `{path}: {n} items < minItems {m}` / `> maxItems`
  - `{path}.{key}: required` / `{path}.{key}: not declared and additionalProperties false`
  - `{path}: expected one of {expected!r}{detail}, got {type}`
  - 顶层：`{label}: expected object`；路径从 label 起，子键 `.key`，数组 `[i]`。

## paleo_workbench/workflow/dag/plan_view.py（只读，不移植）

- `_SYMBOLS`：○●✓✗⊗↷⊘ 七态符号表；`_STATE_LABELS`：运行中/已完成/失败/已取消/
  已中断（可恢复）。
- `PlanItem`：node_id/label/state/detail/from_cache/receipt_status/error + symbol()；
  to_dict 8 键（含 symbol）。
- `WorkflowPlanView`：from_spec（计划视图，全部 PENDING，spec 序）；from_run（按
  node_runs，终态计数 → progress=round(done/total,3)，items 按 spec 拓扑序重排，
  order.get(id,10**9) 兜底）；from_summary（无引擎重建，spec 传入时按 spec 过滤排序）；
  checklist()：running 行 detail 空则填 `{int(progress*100)}%`，当前 running 行加
  current=true；to_dict 6 键（state_label 中文）。
- **不在 06 写入范围**（UI 接线层），C++ 侧由 UI 切片处理；此处 findings 记录其纯数据
  形态以便后续切片引用。

## paleo_workbench/workflow/dag/__init__.py（只读）

- 包门面：导出 WorkflowEngine/WorkflowValidationError、模型 9 符号、ExecutionReceipt、
  WorkflowRunStore、BindingError、validate_workflow_spec。`__all__` 15 项。
- C++ 对应伞头 `pwb/workflow_spec/model.hpp` + `validation.hpp`。

## paleo_workbench/workflow/recipe.py（只读，07+ 切片）

- `RECIPE_SCHEMA_VERSION="1.0"`、`RECIPE_SUFFIX=".paleo-workflow.json"`；
  `_FORBIDDEN_KEYS` 17 键（api_key...command）；`_ABSOLUTE_PATH_RE ^(/|\\\\|[A-Za-z]:[/\\])`。
- `RecipeDocument`：recipe_id/name/workflow/description/created_at/source_run_id/tags/
  schema_version；to_dict 键序 recipe_schema_version 在首。
- `structural_problems`：键 strip+lower 后命中禁键且值为 str → `{path}.{key}: forbidden recipe key ({key_l})`；
  绝对路径非 `$` 开头 → `{path}: absolute path {value!r} — recipes are portable; use workspace-relative paths or slot bindings`。
- `migrate_recipe`：v1.0 仅补 workflow.schema_version；未知未来版抛
  `{v!r} is newer than this build supports (1.0) — upgrade paleo-workbench`。
- `save_recipe` 原子写（tmp+os.replace，indent=1）；`load_recipe` 缺文件/坏 JSON/结构
  违规都 RecipeError；`recipe_from_run` 把 slot_values 烤成 defaults；`clone_recipe`
  换 id/created_at、清 source_run_id；`diff_recipes` 节点/槽/参数三级 diff；
  `inspect_recipe` 无参数摘要；`_slug` 小写化非 [a-z0-9._-] → '-'，strip('-')，空→"recipe"。
- 与本切片关系：recipe 只消费 WorkflowSpec.to_dict/from_dict + validate_workflow_spec；
  C++ 侧 06 交付后 recipe 可直接叠上（纯胶水），不在本切片实现。

## paleo_workbench/workflow/dependency_graph.py（只读）

- `GraphEdge`：source_version_id/run_id/target_version_id/operation。
- `DependencyGraph.rebuild(catalog)`：versions→producing_run/version_asset/asset_versions；
  runs→run_inputs/run_outputs/consumers/domain_task_runs；笛卡尔 input×output 生成边。
- `_detect_cycle_nodes`：迭代 DFS 三色；GRAY 命中→两端入环集；自环同权收集，无早退。
- `transitive_downstream_runs`：BFS，max_nodes=100_000 步护栏；环安全（visited 集）。
- `find_reuse_run`：倒序扫 runs；operation/status∈{complete,completed}/输入列表精确相等/
  generator_version、input_snapshot_hash（非 None 才比）/部分参数键比较/require_outputs。
- `topological_runs`：版本边 + 域任务合成边（map_compile 的 linked_prediction_task_id、
  source_task_ids、task_consumers），_reachable 防合成边成环；子集含环才抛
  DependencyGraphError；latest_by_domain 用 (started_at, rid) max 定序（跨进程确定性）。
- 与本切片关系：catalog 血缘图，与 WorkflowSpec 静态 DAG 是两个图；不移植（M9 服务层）。

## paleo_workbench/workflow/orchestrator.py（只读）

- 遗留 headless 步进助手：STEP_ORDER 6 步（data_check→factor_map→prediction→
  map_compile→qc→export）；get_step_context：`is_valid = status in {complete,running,warning}`；
  非 data_check 且无 resources → 前置 `数据资产清单不能为空`；next_step：有前置→
  `无法进入下一步: {', '.join}`；步骤未有效 → `当前步骤 [{name}] 尚未完成，不能进入下一步`；
  成功 → `已成功切换至第 {n} 步 [{name}]`；全完 → `工作流已全部完成`。
- 不持久化（audit #847-2）；与本切片无关（workflow/service 域）。

## paleo_workbench/workflow/contracts/（只读，Stage 11）

- `models.py`：13 个 str-Enum（Certainty/ImplementationStatus/InputCardinality/
  InputVersionSemantics/InputRole/ParameterCategory/QCSeverity/ExpertQuestion*/
  ReadinessStatus）+ 9 个 Pydantic 模型（WorkflowSourceEvidence/InputSpec/ParameterSpec/
  OperationStep/OutputSpec/QCSpec/ExpertConsultationQuestion/ReadinessReason/
  DomainWorkflowContract.completeness() 6 布尔）。
- `modules.py`：build_all_contracts() 14 个合同（data_import…geomodel_3d），全部
  代码审计产物；未证实的科学声明一律 EXPERT_CONFIRMATION_REQUIRED + 专家问题。
- `registry.py`：WorkflowContractRegistry 内存表；重复 id 抛 ValueError；构造即
  validate_registry 缓存 issues；p0_ids 10 项；模块级单例 get/reset。
- `validation.py`：KNOWN_DATARUN_OPERATIONS 11 项；CONTRACT_DATARUN_MAP 9 对；
  validate_registry 查上下游互为镜像（audit #848）、未知 op、EXPERT 参数缺
  expert_question_id、空问题文本、证据缺 path。
- `readiness.py`：元数据只读评估（不打开 SEG-Y/LAS/NPZ）；required 输入计数门
  （missing_input:/ambiguous_input: EXACTLY_ONE 超一个→warn）；模块级软检查
  （need_two_wells、depth_domain_mismatch、no_factor_task、no_sample_points、
  no_target_horizon、no_paleomap_document、no_linked_target_horizon、paleomap_demo_only、
  prediction_demo_only、mock_adapter、no_production_model、catalog_read_error、
  no_map、nothing_to_export、demo_modeling）；blocks>BLOCKED、warns>PARTIAL、
  PLACEHOLDER>UNKNOWN、否则 READY。catalog 缺席不假装没模型——区分 no-model 与
  read-error。
- `report.py`：确定性咨询/缺口报告生成器（Markdown；SECTION_ORDER 11 类）。
- 与本切片关系：合同/就绪是另一条轴（元数据），与 DAG spec 校验无共享代码；不移植。

## paleo_workbench/harness/spec.py + validation.py + registry.py（对照）

- `ActionSpec`：version/deterministic/cacheable/idempotent/verifier/input_refs/
  output_refs/domain_tags；cacheable ⇒ deterministic + output_refs；registry 注册期
  拒 DESTRUCTIVE（产品策略）。`ActionRisk` 4 值；`ActionStatus` 6 值
  （rejected=guard 拒绝 / failed=执行或验证未成立 / unavailable=生产能力缺失，无别名）。
- `validate_parameters` 见上（validation.py 的 slot schema 校验依赖它）。
- `validate_schema_shape`：注册期 schema 形状门（unknown type/properties/required/
  items/additionalProperties 错位）。
- `ActionRegistry.get` 未命中抛 UnknownActionError(LookupError)——validate_workflow_spec
  捕 LookupError 转 `unknown action` 消息。C++ ActionCatalog 以 map 查找模拟。
- harness/validation.py（ScientificValidator/MapValidationHook）是执行末端验证，
  与 DAG spec 校验无关；不移植。

## libs/workflow/include/pwb/workflow/task_runtime.hpp（既有 C++，只读）

- 单 worker 线程任务运行时（queued/running/publishing/{succeeded,failed,cancelled}）；
  publish-before-terminal、取消线性化 L0-L4、shutdown 语义。**这是 science 算法的
  TaskRuntime，不是 DAG 执行器**——DAG 引擎（07 切片）不复用也不改造它；
  libs/workflow_spec 是新库，不往 libs/workflow 里塞（任务红线）。

## 测试→C++ oracle 案例翻译表（来源文件 → 冻结案例）

- `tests/test_workflow_dag.py` TestStaticValidation 8 例：cycle、missing dep、
  duplicate node、unknown action、$ref 缺 depends_on、$slot 未声明、$context 非白名单、
  meta-workflow（来自 review_fixes）→ invalid_specs 案例逐条冻结（消息全等）。
- `test_adversarial_harness.py` self-dependency → invalid 案例；ghost $ref 静态拒绝。
- `test_workflow_recipe.py` _spec（3 节点 2 槽中文工作流）→ valid 案例骨干 +
  round-trip/hash 基准；save/load/clone/diff 不在本切片（recipe 未移植）。
- `test_dag_cache_index_lineage.py`：parent_run_id round-trip 字段 → run round-trip 案例。
- `test_plan_view.py`/e2e/abc：引擎/面板行为，非本切片 oracle（07+）。
- 引擎契约（engine.py:147-153）：create_run = validate → materialize →
  slot_schema_problems → create；WorkflowValidationError 文案
  `workflow {id!r} invalid: {'; '.join(problems)}`——C++ 测试按 problems 列表对账，
  join 形态由 07 执行器复刻。

## 测试缺口（Python 侧未见测试、由本切片 oracle 补齐冻结）

- validate_workflow_spec 的具体问题**顺序**与**全量文案**无逐字断言（现测试全是
  `any(...)`）→ oracle 冻结完整 problem 列表。
- canonical_hash / spec_hash 无直接测试（仅经 cache 身份间接使用）→ oracle 冻结 hash 值。
- 条件树深层嵌套（all_of 内 not 内 node_state）无测试 → oracle 冻结。
- cycle 消息中「环下游节点也出现在 leftover」无测试 → oracle 冻结 a↔b+c 案例。
- NodeRun/WorkflowRun 字段级 round-trip（除 parent_run_id 外）无专门测试 → oracle 冻结。
- validate_parameters 的 union/unknown-type/bounds 消息文案无逐字测试 → oracle 冻结。
