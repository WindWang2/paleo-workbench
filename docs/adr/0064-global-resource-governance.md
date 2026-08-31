# ADR 0064: 全局资源治理（CPU/RAM/VRAM/IO 统一准入）

- Status: Accepted
- Date: 2026-08-31
- Deciders: WindWang2（产品裁决），ZCode P2 convergence 会话

## Context

P0/P1 之后系统有：TaskScheduler（唯一 heavy 队列，并发 1）、ResourceBudget（advisory caps，
未接线）、VramTextureCache（有界 L2）、RamSliceCache 全局 ledger（硬编码 1 GiB）、以及四处
各自为政的 CPU 旋钮（transcode `default_workers`、factor-prepare worker 数、vendored IDW
`ComputeSettings`、ONNX 会话线程）。没有 admission：后台大任务可以吃满机器、把交互查询挤到
百毫秒之后；RAM 压力只能等 OS OOM-killer。

## Decision

**一个 governor，扩展现有单一权威，不新建平行系统**：

1. **ResourceBudget 增加 CPU/IO 列**：`logical_cores`、`interactive_reserve_cores`（默认 2，
   小机器 1）、`background_core_ceiling`、`io_slots`、压力阈值（0.85/0.95）、
   `background_nice`；`with_pressure_scale()` 只缩 CPU/IO，不动 RAM/VRAM 列。
2. **ResourceGovernor**（`runtime/resource_governor.py`）：`try_admit`（调度器路径，资源不足
   返回 None=继续排队）与 `admit`（直调路径，抛 `ResourceExhausted`，可解释、区分
   retryable 与压力 shedding）；预留/释放记账；`cpu_allowance`/`onnx_thread_allowance` 是
   并行旋钮唯一该问的问题。
3. **TaskScheduler 准入钩子 + 老化**：lease 协议（钩子返回带 `release()` 的对象；终态路径
   全部释放）；优先级老化（5 秒 +5，封顶 +50）——后台永不永久饿死，交互永不抢占正在运行的
   任务；**严格双车道**：1 条 heavy 车道（保持 #1081 的 IO 并发 1）+ 1 条交互专用车道。
4. **MemoryPressureMonitor**：懒采样（1 s 限频，psutil→/proc→永久 NORMAL），非阻塞读
   （sample gate）；PRESSURE 触发缓存救济（seismic volume cache / L1 ledger 注册为
   evictable），CRITICAL 拒绝非交互任务。
5. **遥测**：`telemetry.snapshot()` 聚合 scheduler/governor/pressure/caches（各权威已有计数，
   不新造观测平台）。
6. **接线**：`ensure_global_governance()`（main.py 启动安装，幂等）+ 四个 CPU 旋钮改为问
   governor + transcode 在途窗口取自 `streaming_buffer_bytes` + geoviz `set_global_budget()`
   公开 L1 ledger 预算（子模块跟进提交）。

## Consequences

- 交互派发预算 <50 ms 达成（实测 p99 0.6–23 ms，见
  `.agent-work/p2-convergence/05-performance-budget.md`）；#1081 的 IO 并发 1 语义保持。
- CRITICAL 压力下后台任务得到明确错误而不是进程被杀；UI 可恢复。
- `background_nice` 仅 Linux 生效（其他平台 no-op）；纯 Python CPU 燃烧仍共享 GIL——
  以 2 ms switch-interval 策略 + 车道 niceness 缓解，进程池隔离留作后续（现有 viz/ipc 桥）。
- SQLite 索引读在重文件 IO 并发下有 20–60 ms 尾延迟（无治理时同样存在）——记录为
  catalog 域后续项，不属于本 ADR 范围。
