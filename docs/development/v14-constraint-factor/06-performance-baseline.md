# V14-CONSTRAINT-FACTOR — 06 性能基线

机器：linux 7.2.5-1-cachyos x64，`-O2`（test binary）/ `-O3 -DNDEBUG`（Release 构建），单线程（`PALEO_PREPARE_WORKERS` 默认 1）。测量脚本可复现：`factor_prepare_production` 的公开 seam + `run_factor_prepare_schedule` 直调（与 app 安装路径同一条内核链）。

## compute（run_factor_prepare_schedule，含 LOO R²）

| 场景 | wells | tasks | grid | compute |
|---|---|---|---|---|
| IDW 小批 | 100 | 4 | 50 | 55 ms |
| IDW 中批 | 1 000 | 4 | 50 | 397 ms（≈99 ms/任务） |
| IDW 大网格 | 1 000 | 4 | 200 | 789 ms |
| IDW 单任务标度 | 50 / 200 / 1 000 | 1 | 50 | 8 / 27 / 145 ms |
| 克里金 | 100 | 4 | 50 | 583 ms |
| 克里金 | 1 000 | 4 | 50 | 6 319 ms |
| 克里金 | 1 000 | 4 | 200 | 8 471 ms |
| 队列规模 | 100 | 20 | 50 | 216 ms（≈11 ms/任务） |

读法：
- IDW 标度近似 O(N·n²)：1k 井 grid50 ≈ 4×10⁷ 距离评估，145 ms/任务（含 ≤64 折 LOO，折网格 20×20）。
- 克里金在 >32 井时走 kNN 邻域（12 邻）：1k 井 6.3 s/任务主要是每格 12+1 阶系统的重复构造与变差函数拟合；这是 native 权威核（mapping_kernel interpolator，numpy-OLS OK + 球状模型）的实际成本，与 geoviz WLS 估计器是不同估计器（既有决策：不引入第二个 kriging）。grid200 仅比 grid50 慢 34%，说明成本受邻域构造主导而非格点数。
- LOO R² 在 n≤64 时全量折；>64 折按 linspace 子采样 64 折（每折一次 20×20 网格插值 + 一次双线性采样）。

## commit（GUI 线程，含 catalog 登记）

| 场景 | commit |
|---|---|
| 4 任务 × 50 网格 | 6.7 ms |
| 4 任务 × 200 网格 | 81 ms |
| 20 任务 × 50 网格 | 34 ms |
| 4 任务 × 200 网格 + kriging payload | 136 ms |

commit = 指纹复验（每任务一次无 memo 重推导）+ 目标替换 + 每任务一次 run→INTERMEDIATE 版本→complete 登记。payload 外置后 store JSON 每次 flush 只写元数据（KBs）；200×200 网格 payload ≈0.79 MB（IDW）/1.57 MB（kriging）落 sidecar 文件。修复前（payload 内联）同样批量每次 mutation 全量重写 ≈16 MB store，累计 O(T²)（T=100 ≈16 GB 磁盘写）。

## 取消 / 中断

| 场景 | 结果 |
|---|---|
| 预取消 token（GUI 线程探测） | 0.9 ms 内拒绝（调度器 pre-classify guard） |
| 运行中取消 | cancel bridge 50 ms 粒度把取消传播到 job token；调度器在任务边界 + LOO 折边界检查；未完成任务标 cancelled |
| 页面 shutdown(3000ms) | 有界等待；超时后 worker 分离，其终回调被 generation+target 守卫丢弃（GUI 不再冻结在内核调用上） |

## 复用 / 队列

- 全 CLEAN 重跑（4 任务）：classify 阶段 <5 ms（memo 命中），executed=0，无 catalog 重复登记。
- 值变更单任务：仅该任务重算（E2E 实测「复用 1 · 计算 1」，rail 增加恰好 1 run/1 asset）。
- 20 任务队列串行 <0.25 s（100 井/50 网格）；并行组路径（PALEO_PREPARE_WORKERS>1）同样受 governor clamp ≤min(硬件,4) 限制。

## 内存

- LiveFactorGridStore 上限 64 条目 / 256 MiB（env `PALEO_LIVE_FACTOR_GRIDS_MAX` / `_MAX_BYTES_MB`）；200²×4B ≈160 KB/格，默认网格远低于上限。
- 单任务峰值额外副本：normalized 点集 + grid + envelope + payload dump ≈ MB 级（200² float）。

## 结论

100 井 / 1k 井 / 20 任务队列 / 半途取消 / 重开缓存命中全部满足交互预算（commit 与 20 任务队列在百 ms 级；1k 井 IDW 单任务 145 ms；kriging 1k 井 6 s 为可接受的重计算档位并有取消逃生门）。catalog 写放大已从 O(T²) 降为 O(T)。未做 100GB 地震体优化（范围外）。
