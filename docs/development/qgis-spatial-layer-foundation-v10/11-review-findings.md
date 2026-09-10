# 11 — Review findings & verification（V10）

> **状态：五轮审查执行完毕，P0/P1 全部清零；P2 级处置见下表，
> 未处置项全部降级为 12-known-limitations.md 条目。**

## 1. 轮次

| 轮 | 主题 | 覆盖 |
|---|---|---|
| Round 1 | Runtime | 01-qgis-runtime.md：双配方加载、proj 供给、health 探针、boot 顺序 |
| Round 2 | Spatial correctness | 02-crs-transform.md：判定表、runtime_crs_capable、scratch raw-frame、quiet-4326 |
| Round 3 | Layer authority | 04-layer-registry.md（R1/R2/R4 账本加固、R3 跨栈纪律） |
| Round 4 | Provider/schema | 06-provider-schema.md：三态门禁、widget 单一化、unique 执行 |
| Round 5 | Lifecycle/perf | 09-lifecycle.md + 10-performance.md（500/1000 层 native 探针） |

## 2. 发现与处置

| ID | 级别 | 发现 | 处置 |
|---|---|---|---|
| R1-1 | P0 | vendored 运行时无 proj.db → 全部 CRS 解析失败 → `canvas_destination_crs` 恒 ""（V9 限制 #1 的根因） | **修复**：qgis_runtime.proj_data 部署链 + runtime_facts 实证（EPSG:4326/4490/4214/4610 全 True，transform True） |
| R1-2 | P1 | 桥加载逻辑散布 5+ 处、3 个默认根（qgis_style / conftest / run_qgis_env 硬编码 V7 worktree 路径） | **修复**：qgis_runtime.loader 单一权威，qgis_style/conftest 委托 |
| R1-3 | P1 | geoviz bootstrap（numpy）先于 conda Qt 预载执行 → ENTRYPOINT_NOT_FOUND（包导入即触发） | **修复**：`paleo_workbench/__init__` 中 loader 先行 + `.env` 先载；MSVCP 预载钉仅 VENDOR 配方（conda 配方钉 System32 CRT 反而破坏加载——loader 二分实证） |
| R1-4 | P2 | setup.py 0.4.0a0 vs bindings 0.5.0a0 版本漂移 | **修复**：统一 0.6.0a0 + 注释谱系 |
| R2-1 | P0 | 原生采点 scratch 在画布 CRS 无效时静默兜底 `?crs=EPSG:4326`（quiet-4326 家族原生侧） | **修复**：无效 CRS → 不带 crs 参数（raw 帧），manifest `digitize_scratch_honest_crs` |
| R2-2 | P1 | 镜像发布只在 canvas_crs 非空时 set_destination_crs → 切工程后画布残留旧 CRS | **修复**：恒调用（空 = 显式清除，QGIS no-OTF） |
| R2-3 | P1 | digitize 守卫在 CRS 可用运行时里仍「未知不比对」（fail-open） | **修复**：crs_chain.evaluate_commit_guard——runtime_crs_capable 时未知 = 拒绝；无能运行时保留 V9 诚实语义（判定表有测试钉死） |
| R2-4 | P2 | geological_pipeline 模型默认 4326、well_location_xml 按 lon/lat 形状猜 4326 | **修复**：默认 ""；消费点服务边界已 resolve_crs 记录回退（pinned 测试） |
| R2-5 | P2 | main 上 `test_project_crs_propagates_to_factor_dataset` 期望逐字传播描述式拼写，与 crs_contract 规范化冲突（既有红测） | **修复**：测试改为规范 authid 期望（#1050 意图由首断言覆盖） |
| R3-1 | P1 | 发布账本 no-op 判定漏 name → 程序化改名后镜像树残留旧名（upsertMirrorLayer 的 setName 不执行） | **修复**：name token + 改名重发测试 |
| R3-2 | P1 | 账本按 id(stack) 键控、地址复用 → 新栈被误判 no-op（静默空镜像；scratch/repro_mirror_noop.py 家族） | **修复**：弱引用守卫（死栈复用即清）；不可弱引用栈诚实保留旧语义 |
| R3-3 | P2 | 快照内重复 doc_id 静默塌缩成一个镜像层 | **修复**：显式诊断 + 只发布首个 |
| R3-4 | P2 | 跨栈镜像认领（共享 QgsProject::instance() 上 pwb/doc_id 匹配即收养） | **保留**（纪律收敛：单活 shim + shutdown_live_shims；known-limitations #9） |
| R4-1 | P1 | 无任何 provider 能力探测：`pwb/editable` 是宿主声明；ToolContext.vector_writable 无运行时事实 | **修复**：桥 mirror_provider_facts + ToolContext v4 provider_writable（三态）+ `_writable_gate` fail-closed |
| R4-2 | P2 | editor widget 推断逻辑在 attribute_schema/qgis_layer_schema 双份（且实际有行为分歧） | **修复**：单一权威导入（分歧点：纯文本 "" vs "TextEdit"、datetime、Range 限定——均收编到权威实现，新 parity 测试钉死） |
| R4-3 | P2 | SpecField.unique 到达 wire/provider 但宿主编辑路径不执行 | **修复**：属性表写路径 O(n) 唯一性检查（空值不冲突、数值按 float 归一） |
| R5-1 | P2 | 捕捉配置不持久化、阶段切换无 re-push 钩子 | **修复**：mapping_workspace["snapping"] 快照/恢复（schema_version 守卫）+ set_stage 后 repush_snapping |
| R5-2 | P2 | 活动图层链 6 处漂移位点（D1–D6）中 D2/D3/D4/D5 未闭环 | **修复**：create/duplicate/remove 经 set_active_layer 全链；identify 自动置位同步树选中；空 doc_id 显式清画布 current（桥 `current_layer_clear`）+ 控制器级不变量测试 |
| R5-3 | P2 | QgsProject CRS/ellipsoid 从不配置 → 原生 measure 椭球分支死代码（V9 限制 #3） | **修复**：镜像发布推进 set_project_crs（adjustEllipsoid=true）；桥测试钉死 |
| R5-4 | P2 | 原生 1000 层全量发布实测 7.5s（upsertMirrorLayer 每次 syncCanvasLayers，渐近 O(n²)） | **度量在案**：预算 = 实测曲线（tests/perf/test_qgis_v10_native_scale.py 注释）；no-op/可见性翻转走廉价路径已钉；批量发布 API 列为后续优化面 |

## 3. 环境性失败（同机基线对照）

| 项 | 对照证据 | 处置 |
|---|---|---|
| 3 个 osgeo 标量栅格测试失败（deps 的 osgeo 绑定为 cp314，venv cp312 ABI 不匹配） | 同机 v9 基线 worktree 同样失败；V8 known-limitations #1 家族 | 测试加 `qgis_scalar_pipeline_ready` 诚实跳过守卫（失败 → skip，原因可读） |
| `test_qgis_layer_panel_menu` teardown 假错误（QMenu 50ms 延迟检查命中已销毁对象，Qt 6.11 时序） | 同机 v9 基线 worktree 同样 ERROR | 测试 helper 加 shiboken 有效性守卫（测试工件，非产品缺陷） |
| 默认（自包含 vendor）配方在本机不可加载（PySide6 6.11.2 vs 6.8 期 vendor DLL） | 手工探针实证（ENTRYPOINT_NOT_FOUND）；conda 配方同机正常 | 文档化（12-known-limitations #6）；health 模块现在会把它诊断出来而不是表现为 ImportError |

## 4. 最终验证记录

- 桥构建：0.6.0a0，`PALEO_QGIS_REUSE_VENDOR=1` 链接中性 vendor
  （C:\Users\wangj.KEVIN\paleo-qgis-build\qgis-vendor），无 QGIS 重编译。
- 运行时健康实证（conda 配方，2026-09-11）：
  QGIS 4.2.0-Belém do Pará / PROJ 9.8.1 / GDAL 3.13.3 / providers 17 /
  CRS probes 4×True / transform True / zero degraded。
- qgis-marked 批次：244+ passed, 12 skipped（skip = osgeo 配方约束 + 旧桥特性面），
  含新增 tests/test_qgis_v10_runtime_foundation.py（10 用例）与
  tests/perf/test_qgis_v10_native_scale.py（4 探针）。
- host 面批次（-m "not qgis"）：V10 新增
  tests/test_v10_crs_chain_and_identity.py（14）、
  tests/test_v10_qgis_runtime_health.py（9）、
  tests/test_v10_active_layer_chain.py（5）、
  tests/test_v10_schema_constraints.py（35）、
  tests/test_snapping_persistence_v10.py（6）全绿；全量批次见 PR 描述。
- 预先存在的 main 红测（`test_project_crs_propagates_to_factor_dataset`
  描述式拼写期望）已按契约语义修正（R2-5）。

## 5. 回填纪律

- 所有「修复」均有对应红绿测试或实证脚本输出（见 §4 文件清单）。
- 环境性失败均附同机 v9 基线 worktree 对照。
- P0/P1 清零；未处置项（R3-4 等）以 known-limitations 条目在案。
