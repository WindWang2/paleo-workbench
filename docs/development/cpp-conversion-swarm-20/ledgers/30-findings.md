# CONV-30 findings — async jobs / threading / progress / cancellation 全面 C++ 化

Branch: `feat/cpp-async-job-runtime` (base origin/main @ ff67dcf3). Worktree:
`../worktrees/cpp-async-job-runtime`. 编号 26–29 已被并行 PR（#1346/#1348/#1351/#1352/#1361/#1363/#1364）
占用，本方向取 30。

## Scope ledger

### 本分支负责（Python surfaces → C++）

| # | Python source of truth | 语义要点（冻结） | C++ 目标 |
|---|---|---|---|
| 1 | `paleo_workbench/runtime/task_scheduler.py` | TaskState 七态（queued/running/cancelling/**degraded**/done/failed/cancelled）、协作取消（queued 丢弃 / running 置 cancelling+事件）、task_key 去重 + queued 重提交 supersede（#1224）/ running 拒绝、优先级堆 + aging（5s+5、cap50）、admission 租约协议、interactive/background 严格双 lane、回调先于终态落盘、有界历史 200、shutdown 全取消+join、work_dir crash-safe | `libs/job_runtime` `pwb::job::BoundedJobScheduler`（Qt-free，固定 jthread，无 unbounded 线程） |
| 2 | `paleo_workbench/runtime/task_categories.py` | 11 类 CategoryPolicy 阶梯（base_priority/interactive/io_weight/default_cpu_cores）+ kind 前缀映射（未知→background.io） | `pwb::job::job_categories.hpp` + JSON oracle |
| 3 | `paleo_workbench/ui/owned_worker_job.py` + `ui/thread_keeper.py` | worker 所有权、released 旗标迟到投递守卫、queued 投递跨线程安全、超时 shutdown 交 keeper、destroyed receiver 无害、app 退出收尾 | `pwb_job_qt`：`JobBridge`（queued invoke + context-object 安全析构）、`JobOwner`、`DetachedJobKeeper`、`install_quit_drain` |
| 4 | `apps/paleo_workbench_platform/main_window.cpp::importSegy`（GUI 线程同步读盘+落盘） | SEG-Y→PWBVOL1 导入 + run 注册/发布 | 迁移为 scheduler job（分阶段协作取消 + 非模态进度） |
| 5 | `apps/paleo_workbench_platform/main_window.cpp::runAttributeDialog`（模态 QEventLoop，M1 注释自认欠账） | 属性计算监督（queued/running/publishing 轮询） | 非模态进度 + 取消传播（AlgorithmRunner 增补 `cancel(request_id)`，加法式 API） |
| 6 | `apps/paleo_workbench_platform/main_window.cpp` 地质因子图（GUI 线程同步 run_map_pipeline） | 地质因子图计算 | GUI 采集点位 → job 计算 → GUI 回填图层 |

### 本分支不负责

- `paleo_workbench/runtime/resource_governor.py` / `memory_pressure.py` / `resource_budget.py`
  （资源治理三件套——留给独立方向；本分支只在 job contract 里承载 resource hint +
  admission hook 协议位）。
- `libs/workflow/task_runtime.hpp`（science 域单 worker 运行时，已被 AlgorithmRunner
  使用且被并行 PR #1349/#1352 触碰——不重构、不复刻，仅新增 `AlgorithmRunner::cancel`）。
- Python `TaskCenter` UI（`ui/workstation/task_center.py`）的 C++ 化。
- workflow/factor_prepare_scheduler 等 Python 侧 ThreadPoolExecutor 调用点（它们在
  Python legacy 链上，主链已不依赖）。

### 共享/冲突文件

- `apps/paleo_workbench_platform/main_window.cpp/.hpp`（PR #1351 UI 闭环也改——改动集中在
  import/attribute/factor-map 三个函数 + 新增 job_center.*，冲突面小）。
- `libs/application/algorithm_runner.hpp/.cpp`（加法式 cancel；#1349/#1352 若重写该类需
  rebase）。
- `CMakeLists.txt`（顶层 CONV-30 块）、`apps/paleo_workbench_platform/CMakeLists.txt`。

## Oracle 计划

`tools/oracle/generate_job_policy_oracle.py` 从**真实 Python**（`runtime/task_categories.py`
+ `TaskScheduler` aging 公式 + submit/supersede 决策表）冻结
`job_runtime_tests/fixtures/job_policy_oracle.json`；C++ 侧 replay + negative self-check
（篡改表必须被检测）。

## 测试计划（ctest 名协议 `job_runtime.*` / `job_qt.*`）

start/finish、FIFO 单并发、priority+boost、cancel-before-start、cancel-running（部分结果
→ cancelled）、重复 key（active 拒绝/queued supersede/running 拒绝）、exception→failed、
degraded 谓词、shutdown（全取消+join+submit 拒绝+析构 drain）、admission 推迟/租约释放、
aging、双 lane 隔离、many tiny jobs（1000）、oracle replay+negative、Qt：主线程断言、
destroyed receiver、迟到投递抑制、窗口关闭 while running、app quit drain。
