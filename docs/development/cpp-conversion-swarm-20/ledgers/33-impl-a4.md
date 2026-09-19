# CONV-33 impl — route A4（service.py / orchestrator.py 顶层编排移植）

Branch `feat/cpp-workflow-orchestration`（worktree `cpp-workflow-orchestration`）。
输入契约 = 33-findings §A1（service/orchestrator 行）+ 33-decisions D1–D8 +
冻结头 `service.hpp` / `orchestrator.hpp`（常量与消息注释为单一权威，本路由
零改写）。Python ground truth = `paleo_workbench/workflow/service.py`（355 行）
+ `orchestrator.py`（115 行）。

## 1. 范围表（A4 独占文件）

| 文件 | 内容 |
|---|---|
| `libs/workflow_runtime/src/service.cpp` | 全量实装（替换轮1 freeze_stub）：`_evidence_step_status` 五分支 / `_apply_freshness_overlay` / `infer_workflow_step_status` / `home_workflow_steps`（就地回写 + 弱覆盖保留）/ `create_compilation_run` / `build_affected_products_plan` / `downstream_impact_for_version` / `dashboard_state` |
| `libs/workflow_runtime/src/orchestrator.cpp` | `get_step_context` / `next_step` 实装（ctor/访问器轮1 已真实）；四条消息模板逐字取自 `orchestrator.hpp` 冻结注释（= Python L92/98/107/113），零内联第二份 |
| `libs/workflow_runtime/workflow_runtime_tests/service_test.cpp` | 双 fixture 冻结 replay（36 例）+ 4 项篡改负自检；替换轮1 骨架 main |
| `tools/oracle/generate_workflow_service_fixtures.py` | 新生成器：27 例（真实 Python `paleo_workbench.workflow.service` 驱动） |
| `tools/oracle/generate_workflow_orchestrator_fixtures.py` | 新生成器：10 例（真实 `WorkflowOrchestrator` 公开 API 序列驱动） |
| `libs/workflow_runtime/workflow_runtime_tests/fixtures/workflow_service_oracle.json` | 生成物（27 例，双运行 byte-identical） |
| `libs/workflow_runtime/workflow_runtime_tests/fixtures/workflow_orchestrator_oracle.json` | 生成物（10 例，双运行 byte-identical） |

未触碰：qc.cpp / map_qa_rules.cpp / versioning.cpp（A1/A2 所有）、全部头文件、
CMakeLists、ledger 其他文件。

## 2. FreshnessService 组合方式（for_project 等价面）

`compose_freshness(const CatalogRepository*)`（service.cpp 匿名 ns）：

- **null catalog** → 空 `DependencyGraph` + 空 `CurrentProjectVersionContext`
  直接构造（= Python `for_project` 的 `cat is None` 分支：step_freshness
  恒 nullopt / 一切查询 UNKNOWN，调用方保持 evidence 语义）。
- **非 null** → 镜像 `runtime_service.cpp` 的 snapshot 构形：`list_assets ×
  list_versions` + `list_runs` → `DependencyGraph::from_listings` +
  `VersionLookup`（富记录：checksum/trashed/path/created_at，Python
  graph.versions 承载同数据）；上下文 = Python `resolve_current_project_
  version_context` 在 `service=None` 时的推断分支 —— 每资产按
  `(created_at, version_id)` 稳定排序取末版 select，label=版本名，
  首见资产序与 Python flat listing 分组序一致。
- **持有期**：`FreshnessComposition` bundle 拥有图/上下文/记录/服务
  （`runtime_service.hpp` FreshnessSession 同构；service 成员最后声明，
  析构序安全）。
- **缝语义（E-1 相关）**：`seam.resolve_version` 直通仓库、**刻意不吞异常**
  （runtime_service 的 seam 各回调有 try/catch 吞错 —— 那是执行面语义；
  本处探测面的失败必须穿透到 overlay 的 catch 边界，与 Python
  `catalog.resolve_version` 抛出穿透到 broad except 完全同构）。

## 3. broad-except 边界（E-1，audit #847-3）

| Python | C++ |
|---|---|
| `_apply_freshness_overlay` L136-146：探测（含惰性 for_project 组合）整段 try/except Exception → log.warning + 回退 evidence | `apply_freshness_overlay`：同段 `try { 探测+惰性组合 } catch (const std::exception&) { return evidence; }` |
| `home_workflow_steps` L197-206：组合失败 → log.warning + freshness_service=None（后续每步 overlay 会**再次尝试**组合并各自降级 —— 双重尝试语义保真） | `home_workflow_steps`：同构 catch → bundle=null；per-step overlay 按 Python 语义重新组合、各自降级 |

日志缝：本库无 logger —— 降级路径无输出（≡ log sink 为 no-op），边界以
注释在两处 catch 点固化；非 `std::exception`（如 bad_alloc 级）不捕获，
比 Python 的 `except Exception` 更窄（Python 的 Exception 不含
KeyboardInterrupt/SystemExit —— C++ 无对应进程级信号类，`std::exception`
是可承载语义失败的最小边界）。fixture 用**真实路径**打穿两条边界：
- 悬空输入版本 + `resolve_version` 抛出（`overlay_probe_raises_keeps_
  evidence`，Python/C++ 同走 for_project→step_freshness→_input_is_
  withdrawn→resolve 抛出）；
- `list_versions` 抛出（`home_composition_failure_evidence_only`）。

## 4. 逐点实现说明

- `_evidence_step_status`：五分支 + 默认 pending。qc 分支经 `qc.hpp
  active_quality_reports`（A1 所有，只读消费）；"error" 级报告 = failed
  门（L78-83 注释保留）；末行 `complete if reports or quality_reports`
  的 raw-list 回退按字面实现。
- FreshnessState 映射：STALE→stale / FAILED→failed / RUNNING→running /
  MISSING→warning / UNKNOWN→warning（H1）/ FRESH→保持 evidence。
  `apply_freshness=false` 在 evidence 之后短路（infer 入口）。
- `home_workflow_steps`：活动 run = `compilation_runs` 末元素（非 object
  视为无 run）。就地回写经 DTO 反序列化 → 变异 → `to_dict()` 整段写回
  （from_dict 宽松回填 + to_dict 键序保真，对 pydantic model_dump 形状
  往返无损）；`by_type` 同型重复后者胜（dict comprehension 语义）；
  弱覆盖保留按字面（persisted failed/warning ∩ overlay pending/stale →
  pass）。无 run → 临时步骤（默认 clock 戳 id，从不持久化）。
- `create_compilation_run`：stratigraphy 两字段就地写（段缺失创建）；
  clock 调用序对齐 Python 构造序 = 6×step id → run id → created_at
  （oracle 冻结依赖该序，测试注入计数器 clock 复现）。
- `build_affected_products_plan`：无降级捕获（Python 此处 fail-loud）；
  `options.project` 直传整份 project Json（planner 只读
  prediction_tasks/paleomap_documents 两键，缺键 ≙ 空）。
- `downstream_impact_for_version`：根扩展 = 查询版本 + asset 兄弟集 +
  产生 run 的 domain-task 兄弟 run 输出（H1）；`sorted(roots)` 用
  `std::set` 天然有序；行形状七键，label/state_label 查
  OPERATION_LABELS_ZH / FRESHNESS_UI_LABELS（缺省回退原值）。
- `dashboard_state`：13 键全形状；`resource_counts` 按 Python Counter
  首见序；`qc_issue_count` 走 active_quality_reports 的 issues 计数；
  `workflow_complete_count` 来自 home_workflow_steps。

## 5. 偏差与边界（如实声明）

1. **dashboard_state 的 const& 签名 vs home 的就地回写**：冻结头
   `dashboard_state(const Json&)` 为 const —— Python 版会顺带把活动 run
   步骤写回传入文档。C++ 在**本地副本**上跑 home（返回值逐字一致），
   调用方文档不被 dashboard 隐式持久化。这是 D4 冻结签名的直接后果。
2. **A3 resolve 覆盖段不消费**：组合面不读 project 的
   horizon/correlation/fault 引用与 factor grid 指针（未移植的
   resolve 面）。fixture 工程全部规避这些段，且 run.domain_task_id
   与任务 id 不碰撞（无 expected-identity 干扰）—— Python/C++ 在该
   覆盖域内逐字对拍；project 覆盖段留给 A3 消费方切片。
3. **orchestrator 前置拒绝分支（数据资产清单不能为空）**：冻结头无
   游标 setter 且 project 为值拷贝（D8）—— Python 靠共享对象中途变异
   或直接戳 `current_step_index` 才能到达该分支。分支代码已实现；
   fixture 以 `cpp_replay: false` 冻结 Python 真值（replay 打印
   SKIP + 边界说明），不入 green 计数。
4. **临时/追加步骤 id**：home 无 run 分支与 run 补缺分支的 id 是宿主
   侧戳（C++ 默认 clock = 随机，Python = uuid）—— fixture 对这些 id
   双侧剥除后比较；预先持久化的 id 不剥（round-trip 保真）。
   `create_compilation_run` 走注入 clock，全字段冻结（含 id）。
5. **MISSING 叠加的到达面**：service 组合固定 `check_integrity=false`
   （= Python for_project 默认）；MISSING→warning 分支经 fixture 的
   `freshness_service: "check_integrity"` 注入标记覆盖（测试侧手工
   构造 check-integrity 服务 —— 冻结头无该旋钮，Python 侧对应
   `for_project(check_integrity=True)`）。
6. **generate 侧确定性缝**：pydantic 2.13 将 `default_factory=_now_iso`
   编译进 validator —— 模块符号 patch 无效，唯一可用缝是替换
   `pmodels.datetime` 类（`_now_iso` 调用点解析的模块全局）；
   `_id` 经 default 里的 lambda 惰性解析，counter patch 有效。
7. **freshness.cpp `_checksum_for` 的 seam 异常吞没差异**（既有
   CONV-26 代码，非本路由文件）：Python `_checksum_for` 包 try/except，
   C++ 未包。对本 fixture 无影响（抛出路径经 `_input_is_withdrawn`
   触发，两语言都不吞）；记录备查。

## 6. 负自检清单（comparator 必须能变红）

| # | 篡改 | 结果 |
|---|---|---|
| 1 | `home_sticky_vs_stale_overlay` steps[2].status: complete→warning | caught |
| 2 | `dashboard_full_shape` workflow_complete_count +1 | caught |
| 3 | `overlay_factor_map_stale`: stale→complete | caught |
| 4 | orchestrator `full_walk_to_completion` 第 4 步消息加 "!" | caught |

## 7. 测试计数与验证记录

- fixture：service 27 例（create 2 / evidence 族 7 / overlay 族 8 /
  home 族 4 / plan 族 2 / downstream 3 / dashboard 2 —— 覆盖
  test_workflow_service 8 例全场景 + test_issue847 overlay 面 +
  issue847 #1/#3 全场景）；orchestrator 10 例（基础 3 + #847-2 拒绝 +
  全程走完 + warning 门有效 + payload 忽略 + 前置拒绝[Python-only]）。
- replay：36 例 compare + 4 例负自检 = **40 checks, 0 failures,
  1 skipped（文档化边界）**；ctest `workflow_runtime\.service` 连续两轮
  100% 通过。
- 回归：本路由 build dir `/tmp/conv33-a4-build`
  （`-DPWB_BUILD_CONV_33=ON` + 三个 QGIS 覆盖），workflow_runtime 全套
  4 测试（contracts / qc / service / versioning）100% 通过 —— 含
  A1/A2 并行落地的面。
- 零警告：`g++ -std=c++20 -Wall -Wextra -Werror -fPIC -fsyntax-only`
  （domain/data_suite/third_party/project/workflow_spec/workflow_engine/
  workflow_graph/workflow_runtime 七组 include）对 service.cpp +
  orchestrator.cpp（+ service_test.cpp）全零。
- 并行路由干扰记录：一次瞬时链接失败（A1 中途移走 qc.cpp 的
  `active_quality_reports` 定义）—— 等待 75s 后其编辑落位恢复，
  未触碰其文件。

## 8. 遗留移交

- A3 resolve 面强类型化后，`compose_freshness` 需补 project 覆盖段
  （horizon/correlation/fault/grid 指针 + expected identity），并解除
  §5.2 的 fixture 规避约束。
- home/dashboard 就地回写若需要 C++ 调用方文档持久化，需回契约冻结轮
  追加裁决（当前 D4 的 const& 读面优先）。
