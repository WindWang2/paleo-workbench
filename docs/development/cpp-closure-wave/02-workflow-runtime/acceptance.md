# 02 — acceptance（验收矩阵）

## 本线验收闭环（任务书原文对照）

| 验收点 | 落地证据 | 状态 |
|---|---|---|
| 导入数据 | e2e phase A：import_input → FileCatalogRepository 登记 raw 资产+版本 | **已验证（×2 全绿）** |
| 选 recipe | e2e phase B：recipe_from_spec → save_recipe → load_recipe 往返 + 结构安全门（api_key 拒绝） | 同上 |
| 执行 | e2e phase C：RunEngine create_run+run → COMPLETED；节点体登记 catalog run+DERIVED 版本 | 同上 |
| 产物版本/provenance | e2e phase C：resolve_version 命中 + WorkflowRuntimeService::provenance_trace；CacheRunRail 登记 workflow.node.* 轨 | 同上 |
| 修改输入判 stale | e2e phase D：新版本 + set_current → resolve 五段上下文 → freshness evaluate_run = STALE + plan 有 REQUIRES_COMPUTE | 同上 |
| 仅重算必要节点 | e2e phase E：execute_plan 执行计数差恰为受影响步；新 run FRESH | 同上 |
| 重开恢复 | e2e phase F：FileCatalogRepository 重开（runs/versions 一致）+ WorkflowRunStore 重载 + RUNNING 残留 resume 走崩溃映射至 COMPLETED | 同上 |
| 失败短路 | e2e phase G：fail_next 注入 → run FAILED、下游 SKIPPED、catalog run failed；rerun 恢复 COMPLETED | 同上 |
| 取消 | e2e phase H1：安全点轮询 token → run CANCELLED | 同上 |
| 过期完成 | e2e phase H2：忽略取消的体在 cancel 后完成 → run 保持 CANCELLED（终态不被复活） | 同上 |
| cache 命中 | e2e phase I：同 spec 再跑 → from_cache=true、体零执行 | 同上 |
| 重复 id/环依赖 | e2e phase J：validate_workflow_spec 拒绝 duplicate id 与 cycle | 同上 |
| 证据解析 | fusion oracle pin_mismatch / unresolvable_factor 例（钉住≠当前、不可解析 fail-closed 聚合消息） | **已冻结并回放验证（×2）** |

## 真实性口径

- 生产路径零 mock：e2e 全链 FileCatalogRepository + RuntimeStore 语义 + RunEngine + JobScheduler + WorkflowRuntimeService 真服务；测试注入仅生命周期故障点（fail/release/ignore-cancel），属测试替身。
- Python 仅作 oracle 冻结源（/tmp/pwb-oracle-venv 真实 import 驱动）；C++ 生产代码无解释器/subprocess。
- 语义对拍三套 fixture 全部由真实 Python 实现生成，两次生成字节一致；测试含篡改负例自检（resolve）。

## 环境限制（如实）

- cmake 本机不可用（与 CONV-31/32/33 披露一致）：验证 = g++ 直连全闭包编译 + 二进制运行 ×2；CMakeLists 已预接线供 CI（PWB_BUILD_CPP_CLOSE_02）。
- 重构建走共享资源门（scripts/cpp-migration/invoke-resource-gate.sh Exec），与同主机其他线互斥；排队退避已记录。
- JobScheduler 队列并行、fusion 注册等已在单进程内验证；多进程 SQLite 目录/真 QGIS 无关本线，未涉及。

## 已知偏差（文档化，非隐瞒）

- resolve：单一 repository 扮演 service 角色（Python 无 service 的降级推断分支归 compose_freshness，service.cpp 已有）。
- product_qa 统一 staleness verdict：mapping 依赖未移植（32-findings A3），C++ 走 Python catch 路径 = QA warning，不伪造通过。
- fusion 注册：C++ 走 CatalogRepository（register_run+asset+versions），Python create_derived 三兄弟版本结构不同——registration 字典语义对齐。
- 引擎内 _drive_parallel 节点池仍为 CONV-32 冻结延后（顺序驱动）；调度级并行（多 run 跨 worker）+ 同步取消为本线交付面。


## 验证结论（2026-09-20，gate 内 ×2）

- closure_workflow.resolve：31 checks，0 failures ×2
- closure_workflow.map_product：24 checks，0 failures ×2
- closure_workflow.fusion：14 checks，0 failures ×2
- closure_workflow.e2e：49 checks，0 failures ×2（验收闭环全链）
- 全闭包 76 TU 编译（-Wall -Wextra，仅库内预存 warning）；run-only 第二遍全绿。
- 命令：`invoke-resource-gate.sh Exec -- bash scripts/cpp-migration/closure02-build-and-test.sh`（GATED_BUILD_OK + GATED_BUILD_OK_RUN2）
