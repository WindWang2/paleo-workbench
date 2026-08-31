# P2 Final Verification

基线 origin/main `e1622496` → 分支 `feat/p2-resource-sdk-agent-harness`（9 commits）。
全程未修改 main（main 只读；独立 worktree）。

## P2-A Resource Governance — DONE

- CPU budget unified ✅（interactive reserve / background ceiling / `cpu_allowance`；四个并行旋钮全部改问 governor：transcode、factor-prepare、ONNX intra-op、scanner 池；BLAS 经 `apply_compute_budget`）
- RAM budget unified ✅（soft limit + PRESSURE/CRITICAL hard guard；救济=缓存驱逐；CRITICAL 拒绝非交互大任务并给可解释错误）
- VRAM governance integrated ✅（VramTextureCache 契约不变；预算经 `apply_vram_budget` 下推；L1 ledger 经子模块 `set_global_budget` 接预算；telemetry 汇报）
- IO governance ✅（io_slots 权重预算；交互不受 IO 槽约束；扫描池按槽收缩）
- cancellation/progress converged ✅（TaskContext 为规范 + 三方言 adapter；lease 终态全释放；cancel-vs-claim 窗口已闭合）
- resource telemetry ✅（`runtime_snapshot()`：scheduler/governor/pressure/caches）
- stress benchmarks executed ✅（5/5 场景，见 §Benchmarks）

## P2-B Provider SDK — DONE

- provider contracts stable ✅（ProviderDescriptor + 结构化校验；JSON-schema 子集参数校验）
- registry / validation / failure isolation ✅（duplicate/version/quarantine；坏 provider 不阻断启动——有测试）
- built-in production providers migrated ✅（kriging、idw、seismic.attribute.c3（按 KERNELS）、inference.tiled_onnx（委托）、export.map_product、viz.map_render.fallback/qgis（可执行，probe 诚实））
- provenance integrated ✅（DataRun 包裹 + register_derived/intermediate/output/store；zarr 目录走 register_derived_store）
- provider tests green ✅（31 SDK 测试 + E2E）

## P2-C Geological Harness — DONE

- ActionSpec/Registry/Context/Executor ✅（25 动作：READ 12 / COMPUTE 8 / WRITE 5 / DESTRUCTIVE 0）
- Agent 不触 UI private API / 不直连 SQLite / 不直写文件系统 ✅（动作面唯一入口；typed refs；路径约束在工作区内且拒绝穿越/覆盖）
- write actions go through domain services ✅（含 catalog 溯源）
- resource admission integrated ✅（每动作 governor lease；压力拒绝=失败结果）
- map validation hook ✅（fail-closed 导出闸门；要素齐备性）
- scientific validation ✅（全 NaN FAIL / 覆盖 / 轴序 / 越界 / CRS；grid 验证先于任何提交）
- context awareness ✅（selection 快照 / active well/volume；workspace.describe_context 免检索复用）
- provenance ✅（数据写→新版本+DataRun；factor map 返回 version identity）
- five E2E scenarios green ✅（A–E，生产路径零 mock）
- no arbitrary shell/python/sql actions ✅（注册表面不存在；DESTRUCTIVE 拒装）

## Tests

命令：`/home/kevin/projects/paleo_project/run_env_p2.sh tests/ -q --timeout=300`（offscreen Qt + 本 worktree geoviz 子模块）

- 结果：**全量通过，除 2 个环境受限文件**：`test_native_backend.py::test_map_edit_core_version_and_acceleration`、`test_welllog_engine_native_integration.py::test_binding_contract_not_silently_skipped` —— 需要已构建的可选 C++ 扩展（map_edit_core / welllog binding）；**两处在 clean main worktree 同命令同样失败**（对照验证），为 P1 已记录的环境限制，非回归。
- 新增 100 个 P2 测试（governance 30 / provider SDK 31 / harness core 26 / E2E 8 + 独立性豁免），全部通过。

## Benchmarks（`benchmarks/p2_resource_governance_benchmark.py`，本机实测 [measured]）

| 场景 | 结果 |
|---|---|
| 1: 100k catalog + 后台校验 | 交互查询队列延迟 p99 **0.61 ms**（预算 <50ms）；直查 p95 19.17 ms；校验 120/120 完成 — PASS |
| 2: 转码 + 切片浏览 | 切片 p95 0.05→0.19 ms（tiny 体，仍亚毫秒；比率 3.67×为极小基数） — PASS |
| 3: 属性计算 + 交互渲染 | 渲染队列延迟 p99 **0.50 ms** — PASS |
| 4: 大导出 + 用户查询 | 交互派发 p99 **30.29 ms** — PASS；查询 p95 0.20→28 ms（SQLite 读尾随并发文件 IO，无治理时同样存在——pre-existing，已记录） |
| 5: RAM/VRAM 压力 | shed/evict/有界/恢复/无死锁 8/8 — PASS |
| Harness READ 动作派发（含上下文快照构建） | p99 **0.137 ms**（预算 <10 ms，不含业务 IO） — PASS |
| Registry 查找 | 10k 次 <200 ms（~O(1)） — PASS |

## Architecture（最终 authority 图）

```
LLM / Agent（外部，ToolSource/ChatModel 协议）
  → HarnessExecutor（校验→权限→上下文→governor 准入→执行→验证→ActionResult）
  → ActionRegistry（25 ActionSpec；tool schema 单一来源）
  → 领域服务 / Provider SDK（execute_provider：schema→typed→准入→DataRun）
  → DataCatalogService（唯一写入口） / open_volume / Interpolator / KERNELS / 渲染后端
底层共享：TaskScheduler（1 heavy 车道 + 1 交互车道，admission+aging）
          ResourceBudget→ResourceGovernor（唯一准入权威）
          MemoryPressureMonitor（救济驱逐） / VramTextureCache / RamSliceCache ledger
          SelectionContext / LayerRegistry / Well Engine / QGIS Renderer / 3D Scene
```
无第二套权威（调度器/预算/目录/图层/选择总线各一）。

## Built-in Providers（实际接入）

interpolation.kriging、interpolation.idw、seismic.attribute.c3、inference.tiled_onnx、
export.map_product、viz.map_render.fallback（可执行）、viz.map_render.qgis（probe 门控）。

## Harness Actions（实际清单，25）

workspace.list_assets / search / get_lineage / get_versions / describe_context；
well.list / open / list_curves / create_display / apply_template；
seismic.open_volume / get_slice / compute_attribute；
map.create_factor_map / create_well_location_map / add_layer / set_style / apply_template /
add_component / validate / export；geology.list_horizons / list_faults / create_interpretation；
workflow.status。

## E2E（A–E 结果）

- A 井位图+标注+四要素+校验 PASS（tests/e2e/test_harness_scenarios.py）
- B W23 打开+GR/RT/AC 曲线+显示文档+模板 PASS
- C 相干体：open_volume→provider→DERIVED 注册→lineage PASS
- D 克里金单因素图+图例/色标/比例尺/指北针+校验 PASS（version identity 返回）
- E 导出：校验闸门→生产渲染→catalog OUTPUT 版本 PASS（+ 边界：越界路径拒绝/拒绝覆盖）

## Review（Matt code-review，三轮）

**BLOCKER = 0，HIGH = 0**（round1 6H→修复；round2 1H→修复；round3 全 VERIFIED + 尾 LOW 修复）。
明细见 07-review.md。

## Known Limitations（真实说明）

1. 解释类动作（well.create_interpretation / seismic.create_horizon / seismic.export_interpretation）
   未注册：其草稿-版本生命周期当前是 UI 邻接工作流（3D 体积上下文 + GUI 提交语义）；harness 先暴露读取
   （geology.list_*）+ fault 草稿写入（geology.create_interpretation）。补齐需要先为这些生命周期定义
   headless 提交语义（建议下期）。
2. workflow.run_step 未注册：重算计划的执行提交在 WorkflowController（GUI 线程 commit）；
   headless 化需要把 stage/commit 语义下沉（P1 已有 _RecomputeWorker 基础）。
3. PRESSURE 的"降低 prefetch"未接 geoviz SliceReadWorker（子模块内部偏移预取）；救济目前=缓存驱逐 +
   CPU/IO 收缩。需要时在子模块加 prefetch 闸门（记录为 follow-up）。
4. SQLite 索引读在重文件 IO 并发下有 20–60 ms 尾延迟（无治理可复现）——catalog 域后续项。
5. 纯 Python CPU 燃烧共享 GIL：以 2 ms switch-interval + 车道 nice 缓解；进程池隔离（viz/ipc 桥）留作
   导出规模化时的后续选项。
6. DataRun 记录不含 outputs/warnings 字段（端口形状）；输出经注册版本与 run 关联（lineage 可查），
   warnings 在 ActionResult/ProviderResult 中返回——如需入 run 记录需扩 CatalogPort（跨期 API 变更）。
7. 本机缺已构建可选 C++ 扩展（map_edit_core / welllog binding）→ 2 个预存失败与 clean main 一致。
8. Online CI/CD 未使用/未等待（按任务要求；本地全量回归 + 基准为完成闸门）。

## 结论

P2-A / P2-B / P2-C 全部 DONE；全部完成条件满足；提交 PR。
