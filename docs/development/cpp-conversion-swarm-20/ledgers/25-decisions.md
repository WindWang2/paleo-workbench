# CONV-25 decisions — dependency_graph + interpretation/evidence

## D1 范围

dependency_graph 全量 + evidence 全量（含全部 resolver)。`freshness.py`/`recompute_plan.py`/`constraint_versions.py` 依赖更深的服务面，后续切片。

## D2 catalog/document/workspace 三缝注入

- `DependencyGraph::rebuild(versions, runs)` 直接收 listing 向量——`catalog.list_*()` 调用留在调用侧；`from_listings` 等价 `from_catalog`。
- evidence:`DocumentView` = Json(document 字段以 getattr 语义读取——缺键/None 均按 Python `or []`/`or {}` 处理）;`WorkspaceStateView`/`CatalogResolver`/`ConstraintResolver` 为 `std::function` 注入点，语义与 Python duck-typing 一致（返回 nullopt/异常按 Python except 路径处理）。

## D3 dict 序与集合语义

- `self.runs`/`versions`/`consumers` 等均保插入序（C++ `vector`+`map` 组合或有序结构）;`find_reuse_run` 的 `reversed(list(runs.values()))` 用插入序反向遍历。
- `_detect_cycle_nodes` 只标记 DFS 回边的两端点（`{node, nxt}`）：对 ≥3 节点环，成员集合**取决于 DFS 遍历起点**（Python 以 hash 序 set 遍历、跨进程不确定；C++ `std::set` 按序遍历、确定性）。修正 #1342 指出的错误论断：原"遍历起点不影响成员集合"不成立——只在简单 2 环/自环下成立。Oracle 对 ≥3 环仅冻结 `has_cycle`+非空（`"*"` sentinel），不冻结成员集合。返回 `frozenset`→`std::set`。
- `_PREFIX_KINDS` 按声明序线性匹配（draft→factor→prediction→constraints→version)——`constraints:current` 特判在前。
- `topological_runs` Kahn 队列 init 与邻接均 `sorted`(UTF-8 字节序 = code point 序）。

## D4 `task_consumers`/`parameters` 的 Json 语义

`topological_runs(run_ids, task_consumers)`:`task_consumers` 为 `map<string,set<string>>` 注入；`run.parameters` 存 Json——`linked_prediction_task_id`/`source_task_ids` 的 `or`/`str()` 语义按 Python 对齐（falsy→空、元素 str 化）。

## D5 `EvidenceResolution.to_dict` 键序

按 Python dict 声明序（selector,kind,ref_id,version_id,status,pinned_version_id,asset_id,display,detail,quality);`quality` 拷贝语义（dict(self.quality))。

## D6 错误类型

`DependencyGraphError`(RuntimeError 子类语义）、`ValueError`(selector 消息带 `{text!r}` repr——复用 fusion 同款 py_repr 规则，小范围本地实现）。

## D7 oracle 的 seam 冻结约定

- `catalog.resolve_version`:SimpleNamespace 版/None——`resolve_version` 方法实现为可抛错 stub（冻 MISSING/UNKNOWN 两路）。
- `constraint resolver`:stub callback 返回 `{status,detail}` 或 raise——冻结 status_map/missing/UNKNOWN/异常四路，**不冻结 constraint_versions 内部**（单独切片）。
- `workspace_state`:SimpleNamespace membership + layers_with_role 桩。
- document:SimpleNamespace 记录位 + dict 叶子（conv-21/23 惯例）。
- `find_reuse_run`/`topological_runs`/`available_evidence` 等以结构化 listing 输入冻全分派。

## D8 C++ 落点

`libs/workflow_graph` → `Pwb::WorkflowGraph`；只链 `Pwb::Domain`(Json)。`PWB_BUILD_CONV_25` 默认 OFF，块前置 imply `PWB_BUILD_DATA`。
