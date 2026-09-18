# CONV-25 findings — dependency_graph + interpretation/evidence 核

## 切片范围

`paleo_workbench/workflow/dependency_graph.py`(391 行，全量）+
`paleo_workbench/workflow/interpretation/evidence.py`(464 行，全量——resolver 逻辑原生,seam 注入）。

### dependency_graph.py 移植面

| 对象 | 语义 |
|---|---|
| `DataRunRef`/`DataVersionRef` | 轻量引用结构；图算法只读 run_id/operation/input_version_ids/output_version_ids/parameters/domain_task_id/status/generator_version/input_snapshot_hash/started_at 与 version_id/asset_id/producing_run_id(+evidence 用 name) |
| `GraphEdge` | frozen 三元组 + operation |
| `DependencyGraph.rebuild` | 全索引重建；`producing_run` 先收版本声明（`ver.producing_run_id`)再以 run 输出 `setdefault`(**首写胜出**);consumers/asset_versions/domain_task_runs 按登记序 append;edges=in×out 叉积 |
| `_detect_cycle_nodes` | 版本→版本迭代三色 DFS;adj 按边序去重；cycle 结果集与遍历起点无关（set 语义） |
| `direct_downstream_runs` | consumers 序，过滤未注册 run |
| `transitive_downstream_runs` | BFS visited;`steps>max_nodes` 截断；顺序确定 |
| `transitive_downstream_versions` | 下游 run 输出的去重序 |
| `latest_run_for_domain_task` | 最后登记的 run |
| `find_reuse_run` | **倒序**遍历 runs.values()（最新优先）;operation/status∈{complete,completed}/输入序列等值/generator_version/snapshot_hash/parameters 子集匹配/require_outputs；首中即返 |
| `topological_runs` | Kahn(sorted 初始队列+sorted 邻接）;version 边 + **synthetic task 边**(map_compile 读 linked_prediction_task_id/source_task_ids + task_consumers 注入，绑定 (started_at,rid) 最大的 run，经 _reachable 防护）;requested 子集有环→DependencyGraphError |
| `_reachable` | DFS 可达 |

### evidence.py 移植面

| 对象 | 语义 |
|---|---|
| `EvidenceKind`/`EvidenceStatus` | str-enum;is_usable = RESOLVED/FLOATING/STALE |
| `EvidenceSelector` | kind+ref_id+version_id+floating;`raw`/`__str__`=format 结果 |
| `format_evidence_selector` | 五种 kind 模板；constraint `current` 撞词 ValueError;CATALOG_VERSION=`version:{version_id or ref_id}` |
| `parse_evidence_selector` | strip→空拒；constraints:current 特判；`_PREFIX_KINDS` **dict 序**前缀匹配；factor/prediction/constraints 切 `:` 段数校验（2 段且非空=带版本）;裸 id 兜底 `_looks_like_version_id`;无法识别 ValueError 带 `!r` repr |
| `_looks_like_version_id` | `ver_`/`dver_` 前缀 或 (len≥32 且含 `-` 且不以 `sha:` 开头） |
| `EvidenceResolution` | is_usable + to_dict(selector.raw + 全字段） |
| `_resolve_draft` | 图层名尽力查（id 匹配）;workspace.membership 缺失→MISSING;pinned 空→UNPINNED;catalog None→UNKNOWN else resolve 失败→MISSING（均带 content_fingerprint quality);成功→RESOLVED |
| `_resolve_factor` | task 扫 id;无→MISSING;version=selector.ver or task.grid_artifact_version_id;无→UNPINNED;resolve 失败→UNKNOWN(catalog None)/MISSING;**current_version≠pinned→STALE**(R3-F6);quality 收 r2/n_points/variance_min/variance_max + source_kind∈{mock,mixed}→mock_data |
| `_resolve_prediction` | task 扫 id;status 非 complete/completed/done→MISSING;adapter_kind=mock→mock_data;summary dict 收 classes/mean_confidence;无 version→UNPINNED(run 级溯源）;resolve 失败→MISSING（注意：catalog None 也走 MISSING，与 draft/factor 不同!) |
| `_resolve_constraint_group` | floating→约束 verdict status_map(clean/current→FLOATING, stale/superseded→STALE, unknown→UNKNOWN);非 floating→组 ref 拼回字符串过 resolver;missing→MISSING 带 pinned;UNKNOWN 时 pinned_version_id 置空 |
| `_resolve_catalog_version` | version_id or ref_id;catalog None→UNKNOWN;失败→MISSING;成功→RESOLVED(detail=name) |
| `resolve_evidence` | str→parse 后按 kind 分派 |
| `available_evidence` | workspace.layers_with_role(initial_facies_draft)+完成 factor tasks(rstrip(":"))+完成 prediction tasks+constraint_layers 非空→constraints:current;document None→[] |

### 显式 seam（注入接口，非实现）

1. `catalog.resolve_version(version_id)` → `optional<VersionInfo{asset_id,name}>`;`_resolve_version` 吞掉一切异常→nullopt。
2. document 视图：Json —— user_vector_layers[{id,name}]、factor_map_tasks[{id,name,status,grid_artifact_version_id,quality_metrics,source_kind}]、prediction_tasks[{id,name,status,adapter_kind,probability_summary}]、constraint_layers 存在性。
3. `workspace_state.membership(layer_id)` → optional{source_version_id};`layers_with_role(role)` → ids。
4. `resolve_constraint_ref(document,catalog,ref)` → `{status,detail}` 或异常(→UNKNOWN)。`constraint_versions` 本体（682 行 + content-hash + catalog service）不进本切片——callback seam,oracle 用 stub 冻结 dispatch。

## C++ 结构

`libs/workflow_graph`:`graph.hpp/.cpp`(refs+graph 全量）+ `evidence.hpp/.cpp`(selector/parse/format/resolution + resolver 接口 + dispatch + available)。依赖仅 `Pwb::Domain`(Json)。`PWB_BUILD_CONV_25` 默认 OFF,imply DATA。
