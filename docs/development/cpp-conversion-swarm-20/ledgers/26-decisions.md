# CONV-26 — 移植决策记录（decisions）

## D1 移植范围 = CONV-25 台账点名的"后续切片" + 组合层

`freshness.py / recompute_plan.py / constraint_versions.py`（25-decisions D1 明确排除项）+ `current_context.py` 数据类核 + `provenance_graph.py` + `interpretation/staleness.py` 词汇层，加新组合层（CatalogRepository seam / NodeAdapter registry / AdmissionGate / WorkflowRuntimeService）。不做：`service.py` UI 聚合面、`orchestrator.py`（legacy）、`resolve_current_project_version_context` 属性图粘合、staleness 的 workspace 评估入口（mapping_workspace 属 UI workspace 分支）。

## D2 catalog 以 repository seam 换 SQLite 直连

Python freshness/constraint/provenance 直接调 DataCatalogService（SQLite）。C++ 定义 `CatalogRepository` 接口（读 5 + 写 8，attach_run_output 显式化）+ `RuntimeStore` 确定性内存实现（id 计数器 %06d、sha256 checksum、固定时钟）——测试与 WorkflowRuntimeService 的 provenance 池。SQLite adapter 归 Data 分支实现同一接口。payload 传输为字符串（Python 临时文件路径中 payload 字节才是身份）。

## D3 状态唯一源 = repository

freshness / recompute plan / provenance trace / list_outputs 全部从 `snapshot()`（repository listing → DependencyGraph + VersionLookup）派生；workflow node 执行 → register_run/register_result_asset 发布 provenance。workflow、catalog、UI 不再各自维护状态副本（F 项）。

## D4 复用而非复制

- 校验：`workflow_engine::validate_spec`（不在 runtime 里写第二份 Kahn）。
- canonical encode/sha256：FactorHost/Domain。
- 图算法：WorkflowGraph（CONV-25）。
- node bodies：engine registry 提升为 adapter（`register_builtin_ops`/`register_mapping_ops` 的 NodeFunction 原体 + ResourceHints 包装）。
- 审查修正记录：初版 validate 自带 Kahn/词汇，Review C P0-1 指出后改为复用。

## D5 oracle 形态：input 携带完整场景

fixture 每案例的 `input` 携带可独立重建场景的 JSON（versions/runs/context/group/task/project），C++ 测试用与 Python 生成器相同形状的 builder 重建 — fixture 是唯一共享产物（区别于场景仅存在于生成器代码的形态）。数字类型经 dump/parse 归一化（Python 一切结果过 JSON 序列化）。raise parity 以 `python_class` + 消息冻结（`ConstraintValueError`）。

## D6 保真修正记录（review 驱动）

- constraint line `target_horizon`：初版 C++ 继承组 horizon 且生成器 group_ns 同步洗白 — Review A 指出真实 pydantic 模型默认 ""（不继承）；两侧改为不继承并新增显式行 horizon 案例锁定。
- `constraint_group_content_hash`：move 后读 size（moved-from=0）→ 提前捕获。
- commit 成功路径补 attach_run_output + set_current_version（Python catalog 在 register_* 内完成；freshness 规则 2 依赖 current 指针前进）。
- provenance grid id：Python falsy 语义（空串=无网格→gap），非仅 null。
- pins/groups 去重：Python dict（首现顺序+末值胜出）。
- resolve ref 多冒号：恰取 split 第 2/3 段。
- expected_identity generator 守卫：Python `is not None`（非 truthy；空串期望仍比较）。
- FreshnessSession 堆稳定（shared_ptr snapshot + context），修复链式调用悬垂。

## D7 资源模型

默认 max_concurrency=1（确定性串行）；AdmissionGate 有界准入 + cancel 感知 acquire（50ms 轮询兜底 — CancelToken 无 CV）+ cancel_all/reset（终局关闭/再武装）；全库 thread-confined 契约已在头文件声明（除 AdmissionGate/CancelToken）。

## D8 构建挂接

`PWB_BUILD_CONV_26`（默认 OFF）implied 开关置于 CONV-25 块之前（DATA/MAPPING_KERNEL/CONV-07/08/25），add_subdirectory 置于 engine/factor_host/graph 块之后。FactorHost 为 PRIVATE 链接（公共头干净）。tests 链 Threads。
