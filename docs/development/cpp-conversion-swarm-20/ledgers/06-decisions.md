# 06-decisions — WorkflowSpec DAG 纯模型

原则：对用户流程更诚实、更少抽象（Karpathy：最小代码、外科手术、可验证）。

## D1 — 移植范围：validation.py 全部纯函数 + model.py 全部数据结构

- `validate_workflow_spec` + `_condition_nodes` + `_binding_problems` +
  `_cycle_problems` + `validate_condition_tree`：静态门，纯函数。
- `resolve_value` / `bind_parameters` / `slot_schema_problems` /
  `materialize_slot_defaults` / `BindingError` / `_context_value`：validation.py
  的运行时半区，但输入完全由调用方给定（slot_values/results/context），不触碰
  执行器/调度/registry 行为 —— 属于「validation.py 的校验」承诺范围，随本切片移植。
- `providers.execution.validate_parameters`（JSON-schema 子集校验）：slot_schema 的
  唯一依赖，纯函数，一并移植并对账（不移植则 slot 校验无法对账）。
- 不移植：engine.py / store.py / receipt.py / reproduction.py（07 执行器切片）、
  recipe.py（消费面胶水，后续切片）、plan_view.py（UI 契约，另有切片）、
  dependency_graph.py / orchestrator.py / contracts/（M9 域）。

## D2 — ActionRegistry → 最小 `ActionCatalog`

`validate_workflow_spec` 对 registry 的真实依赖面只有三点：get 未命中（LookupError→
`unknown action`）、`risk.value == "destructive"`、`workflow.` 前缀检查在命中后进行。
C++ 侧定义 `ActionCatalog`（`std::map<std::string, std::string>` action_id→risk 值，
`find()` 返回指针）。不抽象出 ActionSpec/Handler——那是 harness 域，07+ 切片需要时
再长。oracle 生成器用**真实** `ActionRegistry` + `ActionSpec` 注册动作后导出
{id: risk} 表，保证语义不手写。

## D3 — JSON 载体：复用 `pwb::domain::Json`（nlohmann::ordered_json）

- 对象键插入序必须保持（NodeSpec.to_dict 等固定键序、node_runs 插入序语义）→
  ordered_json 而非按字典序排序的普通 nlohmann::json。
- canonical_hash 需要「排序键 + 紧凑分隔符 + 非 ASCII 原样 + sha256」——ordered_json
  递归重建排序副本后 `dump()`（默认紧凑、UTF-8 原样）+ `pwb::domain::Sha256`
  （头文件声明与 hashlib 字节一致）。不重写 sha256，不引第三方。
- 依赖 `Pwb::Domain` 与 mapping_kernel 先例一致（root CMake `-DPWB_BUILD_DATA=ON`
  时可用）；libs/workflow_spec 不链 Qt/QGIS。

## D4 — Python 文案的复刻层（py-repr）

错误消息逐字对账需要 Python 语义：`{x!r}`（str 用单引号、含 ' 且无 " 时用双引号、
反斜杠/控制符转义、None/True/False；list 用 `['a', 'b']` 形态）与 `{type(value).__name__}`
（JSON 标量→ dict/list/str/int/float/bool/NoneType）。实现 `py_repr(Json)` 与
`py_type_name(Json)` 私有助手。已声明的保真边界：
- 浮点 repr 用「最短 round-trip」逼近（Python repr 同策略）；oracle 案例中出现在
  消息里的数值只使用有限小数（0.5/1.0 级），极端浮点（1e308 精度尾数）不在对账面。
- Python 对 None 值 `NodeCondition.value` 无法序列化（to_dict 的 `if ... is not None`），
  C++ 保持同款行为（round-trip 会丢 None 值条件），不「修复」——与 Python 对账优先。

## D5 — 数字/类型强转保真

from_dict 的 `int()` / `float()` / `str(... or "")` / `bool(...)` 强转逐条映射：
- int(x)：接受 JSON 整数或小数（截断，同 Python int(3.0)=3）；bool 拒绝（Python
  int(True)=1 但导出面不会出现，nlohmann 层面 bool 不是 number，保持严格）。
- float(x)：整数或小数→double。
- str(... or "")：空串/缺席→""；非空串原样；非字符串类型（导出面不出现）抛
  invalid_argument——比 Python 的 str() 静默字符串化更严格，选择理由：Python 行为
  依赖类型污染才触发，真实导出面不存在，宁可 fail-closed（对账案例不覆盖该分支）。
- 缺必需键（node_id/workflow_id/name/run_id/workflow）→ std::invalid_argument
  （对应 Python KeyError）。
- 未知 NodeState/RunState 字符串 → std::invalid_argument（对应 Python ValueError）。

## D6 — Kahn leftover 语义原样保留

环的下游节点也会留在 indegree>0 集合里，出现在 `dependency cycle among nodes [...]`
消息中。这是 Python 现行为（消息措辞 "among" 本就模糊），C++ 原样复刻，不"修好"——
修了会与 Python 对账失败，且 07 执行器的 fail-closed 语义依赖这套消息。

## D7 — `BindEnv` 取代 Python 的 duck-typed run

Python `resolve_value(run=...)` 访问 `run.slot_values` 与 `run.context`（后者再走
getattr 链）。C++ 定义最小 `BindEnv`：slot_values(Json)、results(map<string,Json>)、
context_values(map<string,Json>，键=白名单全名)。与 Python 的偏差：tuple→list 转换
不存在（C++ 无 tuple，JSON 数组即列表）；context 值为 null 等价 Python None→不可用
（消息一致）。白名单键的 getattr 中缀路径在 C++ 中拍平为 map 查找——行为面等价：
Python 侧只有白名单键可被读取，且每键的结果由 session 决定。

## D8 — WorkflowRun.create 的时间与 id

`create()` 内部 time.time() + uuid4().hex[:16]。C++：`std::chrono::system_clock` 秒
（double）+ 随机 16-hex（std::random_device）；提供带显式 run_id/时间戳的重载供测试。
create 产物不做 oracle 值对账（非确定字段），round-trip 案例用显式字段构造。

## D9 — C++ 布局与命名

- 新库 `libs/workflow_spec`：`include/pwb/workflow_spec/{model,validation}.hpp` +
  `src/{model,validation,python_repr}.cpp`；命名空间 `pwb::workflow_spec`。
- 伞头不新增；两个头即包门面（对应 dag/__init__.py 导出面）。
- 测试目录 `libs/workflow_spec/workflow_spec_tests/`，单一可执行
  `workflow_spec.validate`（ctest 同名），fixture 由
  `tools/oracle/generate_workflow_spec_fixtures.py` 生成，路径经编译定义注入
  （mapping_kernel 同款）。
- 根 CMake 追加 `BEGIN CONV-06` / `END CONV-06` 块 + option `PWB_BUILD_CONV_06`，
  不动其他 CONV 块。

## D10 — oracle 案例组织（合法 ≥20 / 非法 ≥20 的落点）

- `valid_specs`（≥20）：线性/菱形/并行分支、2 槽中文工作流（recipe 测试骨干）、
  全部条件 kind 与嵌套（all_of/any_of/not 组合）、$ref 带/不带 key、$slot 嵌套于
  dict/list、$context 全部白名单键样本、retry 非默认、max_concurrency>1、
  workflow_id 边界（63 字符合法、点/连字符/数字）、unicode name、空 description、
  slot default 各型（int/str/None/bool）、required=false。
  每案例冻结：Python from_dict→to_dict 的重序列化 + spec_hash + problems==[]。
- `invalid_specs`（≥20）：覆盖 validate_workflow_spec 每个失败分支（§findings 清单
  16 分支）+ 组合案例（多问题全列表顺序对账）；每案例冻结**完整** problems 列表。
- `condition_trees`（≥8）：validate_condition_tree 直接对账（含未知 kind）。
- `slot_bindings`（≥12）：materialize + slot_schema_problems，覆盖
  validate_parameters 的类型/enum/bounds/items/required/additionalProperties/union/
  unknown-type 消息。
- `resolve`（≥10）：$slot 命中/缺席、$ref 整包/带 key/缺 key/未解析、$context 命中/
  不可用、嵌套容器递归、标量透传；错误案例冻结异常消息。
- `canonical_hash`（≥6）：含中文键值、数字型混排、嵌套、键序扰动不变性。
- 全部期望值由生成器 import 真实 `paleo_workbench.workflow.dag.{model,validation}`、
  `paleo_workbench.harness.registry`、`paleo_workbench.providers.execution` 后计算，
  禁止手写。

## D11 — 对抗审核后的已声明偏差（审核轮 1，2026-09-18）

以下 Python 行为**有意不复刻**，只在手写污染输入下可达（Python 导出面不存在）；
除注明外均按 D5 风格「污染即抛」或按 JSON 类型系统自然处理：

1. `int("5")`/`float("2.5")` 数字字符串强转：C++ 拒绝（只接受 JSON 数字）。
   Python 导出的 retry.max_attempts 恒为数字。
2. NodeRun/WorkflowRun 可选字符串字段（action_status/cache_identity/skip_reason/
   error/project_name/project_path/spec_hash/parent_run_id）与 NodeCondition 的
   node/key/state：非字符串值时 C++ 视为缺席（Python 原样透传任意 JSON）。
   07 的 store 切片若需要逐字节保真，可升级为 optional<Json>。
3. `depends_on: "ab"`（字符串被 Python tuple() 逐字符拆分）：C++ 抛 ModelError。
   schema 污染的对照行为：minimum/maximum 非数字——Python TypeError 崩溃 ↔ C++ 抛
   ModelError；required/enum 为字符串（Python 逐字符迭代后继续跑出怪结果）——
   C++ **静默跳过该检查**（如实记录：这是 fail-open 方向的残留，仅手写 schema
   可达；07 若把 schema 纳入静态门应改为报错）。
4. resolve_value `$context` 非字符串键：Python 在 getattr 处抛 TypeError；C++ 走
   BindingError「not available in this session」。静态门先行拦截，运行时不可达。
5. `_condition_nodes` 对多个未知 ref 的报告顺序：Python 侧受 set 迭代序（hash
   随机化）影响、跨进程不稳定，oracle 只冻结单 ref 案例（多 ref 时集合等价即可）。

审核轮 1 修复的 13 项见账本 R6；其中 P1（条件树空字符串真值）影响静态门判定，
已补 4 个 truthiness 冻结案例。
