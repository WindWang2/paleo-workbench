# P2 Convergence — 00 Baseline

日期：2026-08-31 · 基线：origin/main `e1622496` (PR #1115 merge) · worktree：`../paleo-p2-convergence`，分支 `feat/p2-resource-sdk-agent-harness`。main 全程只读。

## P0/P1 status on latest main

全部已合并（gh pr list --state open 为空）：

- P1 六 PR：#1087 #1088 #1089 #1090 #1091 #1092 — MERGED。
- P0：#1098 (SQLite thread ownership) #1099 (catalog canonical store) #1100 (cartography units) — MERGED。
- 100G/生产收敛 #1108 + #1093–#1097、#1104 (VramTextureCache L2)、#1106/#1105 (RenderContext DPI)、#1110 (SQLite self-heal)、#1111–#1115 (CI legs/flake fixes) — MERGED。

结论：P2 直接在当前 seam 上扩展，无 P0/P1 欠账阻塞。

## Existing single authorities (must extend, never duplicate)

| Authority | Location | State at baseline |
|---|---|---|
| TaskScheduler（唯一 heavy 队列） | `paleo_workbench/runtime/task_scheduler.py` | priority heap + cooperative cancel + crash-safe work dirs；全局 max_workers=1；**无 admission/aging** |
| ResourceBudget（唯一资源预算） | `paleo_workbench/runtime/resource_budget.py` | RAM/VRAM advisory caps；`apply_vram_budget` 是唯一被 push 的 cap；**无 CPU/IO 字段、无 admission** |
| VramTextureCache VRAM（L2） | `geoviz_seismic/vram_cache.py` 单例 `VRAM` | 全类型 LRU + budget + stats；已收敛 |
| RamSliceCache（L1） | `geoviz_seismic/cache.py` | per-instance budget + 全局 ledger `_GLOBAL_MAX_BYTES=1GiB` **硬编码，未接 budget** |
| DataCatalogService | `paleo_workbench/catalog/` | 唯一写入口、immutable versions、DataRun provenance、model registry（ADR 0056） |
| open_volume | `geoviz_seismic/chunked.py` | 唯一体积 IO（zarr v3 生产 / SEG-Y 降级浏览） |
| SelectionContext / CoordinateHub | `viz/selection_context.py` / `viz/coordinate_hub.py` | 唯一 selection 总线（P1） |
| LayerRegistry | mapping layer 状态权威 | P1 收敛 |

## CPU 并行度旋钮（四处独立 = P2-A 要收敛的对象）

1. `seismic_transcode.default_workers()` — `min(physical_cores-2, 8)`
2. `workflow/factor_prepare_scheduler.prepare_worker_count()` — env `PALEO_PREPARE_WORKERS` clamp 1..4（默认 1）
3. `_vendored/haiyou_constrained_idw ComputeSettings.cpu_workers()` — `cpu_percent=60` → 1..cores
4. ONNX `InferenceSession` — 未设 intra_op threads（ORT 默认 = 全核）

其余线程面：scanner ThreadPool(32)、map fallback render executor(1/实例)、catalog-maintenance thread、SeismicLifecycle→TaskScheduler、OwnedWorkerJob(QThread) 页面任务、geoviz workers（SliceReadWorker latest-wins + prefetch ±1/±2）。

## 压力/遥测现状

- 无 RAM pressure 监测（psutil 只用于数核）。
- 遥测计数已存在但分散：`VRAM.stats()`、`SeismicVolumeCache.stats()`、`render_diagnostics()`、`TranscodeStats`、`TaskHandle`。
- 取消方言三套：TaskContext（scheduler）、geoviz CancellationToken、ad-hoc callable/Event —— 需 adapter 而非替换。

## Provider/SDK 现状（P2-B 地基）

- 深模块：`CatalogPort`/`CoreCatalogAdapter`；`ModelProvider` protocol + `register_provider` + `model_package` manifest + `inference_service`（完整 provider 生命周期，tiled_onnx 已证可行）；`MapRenderBackend` ABC + probe；`KERNELS`（volume attributes）与 `AttributeSpec` 表；`Interpolator` ABC（Kriging/IDW）；`DomainWorkflowContract` registry（声明式能力目录，静态）。
- 浅/未接线：`DataAssetRegistry/FormatSpec`（无生产 caller）、`io_registry`/`exporters._CONVERTERS`（静态表）、`agent/registries/*`（元数据-only）。
- 插件机制现状：仅 `register_provider()` + `PALEO_DATA_CATALOG` env 动态导入；无 entry points。ADR 0055 把插件运行时定为 P.REG/P.DISC/P.LOAD 分期 —— P2-B 即 P.REG 切片。

## Agent/Harness 现状（P2-C 地基）

- `paleo_workbench/agent/`：PaleoAIHarness（IntentParser→TaskPlanner DAG→8 agent swarm），多数 agent 模拟；ToolRegistry 可导出 OpenAI 格式 JSON Schema 但近乎空。已知缺陷 audit ISSUE-021（上游失败 DAG 不完整）。
- 无 LLM vendor 耦合（无 OpenAI/Anthropic 硬编码）。
- Harness-ready 服务：`GeologicalMappingService`（headless 纯 Python，docstring 明示 AI Harness）、`SeismicLifecycleService`、catalog lifecycle run helpers、`workflow/service.py`。

## Environment

- 测试：`/home/kevin/projects/paleo_project/run_env_p2.sh`（本 worktree geoviz submodule、offscreen Qt、libxmlshim、miniconda py3.13）。
- 机器：62.6 GB RAM。缺已构建可选 C++ 扩展（P1 已知环境限制，clean main 同样失败，非回归）。
- gh 已认证（WindWang2），远端 https。

## Wayfinder destination（本轮）

1. **P2-A Global Resource & Performance Governance** — 扩展 TaskScheduler + ResourceBudget 为统一 admission/pressure/telemetry。
2. **P2-B Provider SDK** — capability contracts + registry + validation + isolation + built-ins（P.REG）。
3. **P2-C Geological Harness** — ActionSpec/Registry/Context/Executor + validation hooks + 5 E2E 场景。

依赖方向 P2-A → P2-B → P2-C（B 的执行走 A 的 admission；C 的 compute 走 B 的 provider 与 A 的 admission），允许局部并行。
