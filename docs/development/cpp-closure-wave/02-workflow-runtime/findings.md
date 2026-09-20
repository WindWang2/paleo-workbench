# 02 — findings（盘点轮 1，base 06211541）

## 能力四列清单（implemented / merged / wired / verified）

| 能力 | Python 冻结源 | 状态 @06211541 | 本线动作 |
|---|---|---|---|
| RunEngine 全语义面（create/run/resume/rerun/cancel、条件、重试、缓存身份、__checkpoint__） | workflow/dag/engine.py (1120) | merged (CONV-32 #1378) | 复用；补 scheduler/cancel-sync/cache-run 轨 |
| store 原子 checkpoint + 缓存索引 | dag/store.py | merged | 复用 |
| freshness / recompute_plan / staleness / provenance_graph / constraint_versions | workflow/freshness.py 等 | merged (CONV-26) | 复用 |
| WorkflowRuntimeService（execute 发布 provenance、plan、explain_stale、provenance_trace） | 组合面（C++ 原生权威） | merged | 复用 |
| service/orchestrator/recipe/versioning/qc/map_qa_rules | workflow/{service,orchestrator,recipe,versioning,qc,map_qa_rules}.py | merged (CONV-33 #1410) | 复用 |
| current_context 数据面 | workflow/current_context.py (431) | merged（仅数据面） | **本线：真实 resolve 五段注入 + _deselect_superseded_domain_tips** |
| map_product catalog OUTPUT 编排 | workflow/map_product.py (1078) | 未移植（33-findings A3 留消费方） | **本线移植** |
| integrated_compilation 证据→融合→注册 | workflow/integrated_compilation.py (683) | 未移植（依赖 factor_fusion 内核已就绪 CONV-24） | **本线移植** |
| _drive_parallel / submit_to_scheduler / token 同步 | dag/engine.py | 未移植（32-findings D5 延后） | **本线：WorkflowScheduler + 同步取消 + 有界并行** |
| _register_cache_run catalog 轨 | dag/engine.py:735 | 未移植 | **本线：cache-run 溯源轨** |
| provenance/catalog 持久化（重开恢复） | catalog SQLite（C++ 无宿主） | RuntimeStore 仅内存 | **本线：FileCatalogRepository（原子 JSON 持久化）** |
| UI 控制器接入 | workflow_controller.py | WorkflowCore seam 注入面已存（UI-14），宿主绑定缺 | **本线：typed host bindings** |
| 会话指针 merge/restore | dag/engine.py:713 | ISessionContext seam no-op | **本线：宿主注入实现** |

## 真实 Python 冻结源（oracle 权威）

paleo_workbench/workflow/{current_context.py, map_product.py, integrated_compilation.py}；oracle venv /tmp/pwb-oracle-venv（Python 3.14.6）import 验证通过。指纹语义：sha256(json.dumps(sort_keys, ensure_ascii=False).encode)（map_product scientific_fingerprint L65-66）；resolve 顺序 5 段（catalog current → horizon → correlation/fault + domain tips 去重 → factor grid → prediction → extra）。

## 接口决策（初判，实现轮可修正）

- 新库 libs/closure_workflow（产品线装配/消费者层；不碰 catalog 内核/科学算法）。依赖：workflow_runtime + workflow_engine + factor_fusion + project(Json) + ui_controllers(仅 host_bindings 头)。
- 根 CMake：PWB_BUILD_CLOSURE_WORKFLOW 门（implies CONV_33/26B 链）。
- 持久化：FileCatalogRepository 与 RuntimeStore 同 CatalogRepository 接口；JSON 文件原子写（tmp+rename），文件格式 {store_version, assets, versions, runs, current}；checksum 沿 payload sha256。
- scheduler：WorkflowScheduler 不新建第二队列权威——消费 job_runtime JobScheduler seam（或注入的 std::function 提交面）；同步 token：宿主 cancel → 引擎 CancelToken；并行驱动受 max_concurrency 与中央 clamp 双上限。

## 已知问题复现清单（先复现再修）

- 重复节点 id：workflow_spec validation 应拒绝 → 测试钉住。
- 环依赖：spec validation + graph → 测试钉住。
- 证据解析（evidence selector）：workflow_graph/evidence 全分支已移植 → 消费面（fusion_inputs_from_document）复现 mismatch/缺失路径。

## 独立审查结果（子代理，NEEDS-FIX → 已全部落实）

P1：① resolve deselect 边迭代边删（改快照迭代）② run_integrated_fusion move-after-use（改传拷贝，审查前已修）③ map_product 测试 id 分配方案与 generator 不一致（改共享 seq + grid 预注册消耗 seq）④ polygon_qc 单键 vs 冻结 10 键（补全 + area_warnings 两条目 quirk，审查前已修、审查后补第二条约目）⑤ e2e 缓存键 version_ids 不被收集器识别 + G/H 场景缓存污染（补 version_id + 独立 store）⑥ scheduler pending_ 先插后提交/队列取消泄漏（submit 后插入 + on_cancel 清理）⑦ assemble 失败丢 extra_parameters（seam 三参 update_run_status 全链）。
P2：skipped-rules 只认 dict 条目、sensitivity 注册路径 best-effort、type=factor_map 对齐、cloned_from 空串、resolve run 索引提升（#538）、restore_state 计数器 max 后缀 + 重复 id 拒绝、resume/cache 弱断言收紧、scheduler cancel 覆盖（K2）、unknown-weight 全消息、CMake BUILD_TESTING 门。未采纳：时钟回绕 floor（头文件已文档化，生产注入真实 Clock）。
