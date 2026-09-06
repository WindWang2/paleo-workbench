# 07 — ResourceGovernor Convergence（#1225）

日期：2026-09-07 · branch `feat/data-runtime-foundation-v6`

## 1. 移除的旁路

| 位置 | 旧行为 | 现行为 |
|---|---|---|
| vendored `fast_grid._pin_blas_threads` | **每次插值调用运行时改写** OMP/OPENBLAS/MKL/NUMEXPR/VECLIB_NUM_THREADS（泄漏给之后所有子进程与无关计算）+ `threadpoolctl.threadpool_limits` 不带 with 全局永久生效 | 全部环境变量改写删除；`_blas_limit(n)` 返回**作用域化的 threadpoolctl 上下文**，批次结束恢复；单线程路径批内 BLAS 满核仍然成立（作用域内） |
| workflow DAG `_drive_parallel` | 池宽 = spec `max_concurrency`（未治理） | `min(spec, clamp_workers("background.compute"))` —— spec 值只是上限，并行度来自中央允许量 |
| `interchange.batch` | 本地硬编码 1..4 | `clamp_workers("background.io")` |

## 2. 保留的中央通道

vendored IDW 池宽 = `ComputeSettings.cpu_workers()` ← 引导期 `governance` 注入的 `set_cpu_percent`（ResourceBudget 派生）——vendored 包不 import 运行时模块，资源契约经此单一通道注入（§10 "wrap with explicit worker-count contract"）。转码/factor-prepare/扫描器/ONNX 线程数原本就走 `clamp_workers`/governor。

## 3. 证据（tests/test_resource_governance_convergence.py）

真实插值批次全程 OMP/BLAS 环境变量零变化；threadpoolctl 限制批后恢复（前后 threadpool_info 键一致）；DAG 池宽收敛契约；batch 构造宽度=治理允许量且 <99；相关模块导入期无环境变量改写。

## 4. 附带发现

`QProcessFutureBridge`（ProcessPoolExecutor 桥）在全库无 ProcessPoolExecutor 使用者——休眠基础设施，未删除（无危害），记录于 11。
