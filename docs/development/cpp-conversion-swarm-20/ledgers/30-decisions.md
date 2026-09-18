# CONV-30 decisions — async jobs / threading / progress / cancellation

Branch `feat/cpp-async-job-runtime` (base ff67dcf3). Scope ledger:
`30-findings.md` in this directory.

## D1 — 新建 libs/job_runtime，双 target

- `pwb_job_runtime`（Qt-free core）：job contract（JobState 七态/CancellationToken/
  JobContext/JobSpec/JobHandle）、BoundedJobScheduler（固定 jthread lane、优先级堆 + aging、
  task_key 去重 + queued supersede、admission 租约、crash-safe work dir、有界历史 200、
  shutdown/drain）。零 Qt / 零 Python / 零 Pwb::Domain 依赖。
- `pwb_job_qt`（Qt6::Core）：`JobOwner`（OwnedWorkerJob 移植）、`DetachedJobKeeper`
  （thread_keeper 移植）、`install_quit_drain`（app 退出有界排空）。
- 理由：核心可被任何 host（含测试、未来 server）复用；Qt 桥是产品 GUI 的交付面。

## D2 — 不动 libs/workflow/task_runtime.hpp（防平行架构冲突）

TaskRuntime 是 science 域单 worker 运行时（发布语义绑定），且被并行 PR #1349/#1352 触碰。
CONV-30 只新增 `AlgorithmRunner::cancel(request_id)`（加法式，见 D5）。两者关系：
TaskRuntime 继续承载"算法执行 + 发布"，job runtime 承载"产品级后台任务监督/进度/取消/
生命周期"；后续方向可在 AlgorithmRunner 下沉时统一。

## D3 — 冻结语义（Python parity 逐条）

task_scheduler.py：七态、协作取消（queued 丢弃 / running 置 cancelling + 事件；CANCELLING
重复取消幂等）、部分结果→cancelled、progress clamp + 观察者异常不杀任务、回调先于终态落盘、
aging（5s+5 cap50）、双 lane 严格隔离、supersede（#1224，queued 重提交替换 + on_cancel 回卷；
running 重提交拒绝并保留 Python 原文消息）、admission 租约（无锁 hook、终态释放、丢失竞态
投机释放）、有界历史、shutdown 全取消 + join。
**已知偏离（1 条，文档化）**：Python 用 daemon 线程，进程可带活任务退出；C++ jthread 不可
抛弃，调度器析构必然 join → 产品以 aboutToQuit 有界 drain + 窗口关闭 400ms 协议显式收口
（install_quit_drain / JobCenter::shutdown_workers）。

task_categories.py：11 类阶梯 + kind 前缀映射逐值移植；JSON oracle 冻结（见 D4）。
owned_worker_job.py / thread_keeper.py：released 旗标迟到投递抑制、queued invoke 上下文安全
（改为 app 级 DeliveryPump + 投递时复查 released——C++ 无 weakref/shiboken，等价且无
悬垂）、超时 shutdown 交 keeper、destroyed owner 非阻塞 adopt、keeper 收敛到 0 可测。

## D4 — Oracle

`tools/oracle/generate_job_policy_oracle.py` 从真实 Python 冻结
`job_policy_oracle.json`（11 policies / 24 kinds / 44 aging 行 / 3 supersede 行）；
`job_runtime.policy_oracle` replay 全表 + negative self-check（5 处篡改必须全部被检出）。
行为类语义（取消/去重/shutdown）不适用 JSON 冻结，以 27 项多线程行为测试覆盖
（tests 与 Python test_task_scheduler/test_owned_worker_job/test_thread_keeper 用例一一对应）。

## D5 — 产品接线（3 个真实 Python 后台面迁移）

| Surface | 原 C++ 状态 | CONV-30 后 |
|---|---|---|
| SEG-Y 导入（import） | GUI 线程同步 read+write+register+publish | job（kind=background.io），阶段安全点协作取消 + 粗粒度进度 + 非模态进度框；同步入口 importSegy 保留（self-check/测试） |
| 属性计算监督（seismic/science） | 模态 QEventLoop 50ms 轮询（M1 自认欠账） | supervision job（kind=seismic.attribute）非模态进度 + 取消传播（新增 `AlgorithmRunner::cancel`，加法式） |
| 地质因子图（mapping） | GUI 线程同步 run_map_pipeline | 拆 collect(GUI)/compute(job, kind=background.compute)/apply(GUI)；同步入口 runGeologicalFactorMap 保留 |

生命周期协议：closeEvent → `JobCenter::shutdown_workers(400)`（超时 detach 到 keeper）；
aboutToQuit → 有界 drain；MainWindow dtor 先 shutdown_workers(1000) 再按原有序 teardown。

## D6 — 共享文件最小化

- `libs/application/algorithm_runner.{hpp,cpp}`：仅加法 `cancel()`（CONV-30 注释块包裹）。
- `apps/paleo_workbench_platform/main_window.{hpp,cpp}`：改动集中在三个迁移函数 + 新增
  job_center.*；全部以 `#ifdef PWB_WITH_CONV_30` 守卫，CONV-30 OFF 时恢复原路径（与其他
  并行分支的 rebase 冲突面最小）。
- 顶层 `CMakeLists.txt`：CONV-30 块（默认 ON；缺目录即 FATAL，fail-closed；隐含
  PWB_BUILD_DATA=ON 供 oracle 测试的 domain JSON，与 CONV-18/23 同形）。

## D7 — 本地验证与已知限制

- PLATFORM=OFF 闭包：configure + targeted build（≤ -j3）+ ctest 27/27 × 20 轮稳定
  （job_runtime.lifecycle/cancel/dedupe/shutdown/policy_oracle + job_qt.bridge +
  既有 mapping_kernel/data 全套）。
- **限制**：本 Linux 主机无 vendored QGIS SDK（无 sibling main checkout），platform app
  （main_window/job_center）无法本地编译；job_center.cpp 已 Qt-only 语法编译验证；
  main_window.cpp 改动以 review 补偿（守卫式追加、遵循原模式），Windows 侧构建即可
  覆盖。在线 CI 不需要也不等待。
