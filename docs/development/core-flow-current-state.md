# Core Flow — Current State Baseline (A0)

Baseline commit: `a1a526475794b6ad42013f307ab58eda2bc1a5a7` (main, 2026-09-05)

> **注**：本文档记录的是本分支开工前 main 基线的事实状态。文中"仍存在的 issues"
> 绝大多数已在本分支（feat/core-geoscience-flow-v4）修复——逐项对应关系见
> `core-flow-target-state.md` 的勾选清单与各 commit message。

本文档基于对最新 main 源码的全领域审计（6 个并行领域调查），记录"从源码看系统今天是什么"，而不是历史文档宣称什么。每节给出关键 `file:line` 证据。目标态见 `core-flow-target-state.md`。

## 1. Project / Workarea 生命周期

- 工程文件 `<name>.paleo.json`（+ `.bak`），受管存储 `<name>.artifacts/{raw,derived,intermediate,outputs,working,trash,blobs,metadata}`（`catalog/storage.py:30-36`、`project/paths.py:186-198`）。
- 创建/打开/切换：`ProjectController.new_project / open_project_path`（`ui/project_controller.py:168-232`）→ `ProjectManager.load()` → 停后台会话 → `DataCatalogService.open()`。
- 另存为：可逆 `stage_artifact_relocation` + `rebase_artifact_paths`，回滚路径完整（`project/paths.py:119-156`、`catalog/service.py:3005-3048`）。
- 相对路径强制不得逃出工程目录（`paths.py:273-306`），外部绝对路径带 `external=True` 标志。
- **缺口**：无 relink 机制（外部 RAW 丢失后只能靠 `resolve_path` 降级兜底，见 §2 #1140）；`safe_rmtree` 双层吞异常（#1190）；load/save 快照不对称、未知段落静默丢弃（#1170）。

## 2. Data Catalog / Version / Tag / Provenance

- `DataCatalogService`（ADR 0056/后继 #1027）是唯一写入口：`import_raw`（流式 SHA-256 单遍拷贝）、`link_external`、`materialize_external`、`create_derived`、`register_intermediate/register_output`、`register_derived_store`（目录型 zarr `os.replace` 整体移入）。
- `DataStage` 枚举 RAW/DERIVED/INTERMEDIATE/OUTPUT 必填；stage 变更只能经 `promote_version` 产生新版本。
- **canonical 存储 = `catalog.sqlite`（WAL）**；`catalog.json` 仅 close/export 检查点 manifest。`catalog_revision` 每次 `_save` +1，flush 失败回滚。
- 行级写已走 `DirtySet → apply_changes` 单事务；**但** `adapter.py:203,476` 仍有 2 处无 dirty 的 `_save()` 触发全量 reconcile（#1138 残留）。
- **#1139 仍存在**：`service.py:697` 在 batch 判定之前自增 revision，batch 期间索引新鲜度检查（`adapter.py:318,346`）必然失败 → 批量导入第 2 个文件起退化为 O(M×N) 线性去重扫描。
- **#1140 仍存在**：`resolve_path`（`service.py:998-1008`）对非受管版本逐级降级到 basename 兜底，外部文件丢失后可静默错绑工程内同名文件。
- **#1175 部分修复**：`version_id` 已消毒；`asset.id` 仍无路径段消毒直接拼入受管存储路径（`storage.py:396`）。
- stale write 防护：catalog flush 与 index refresh 有 `CatalogStaleWriteError`；工程文件有 `ProjectStaleWriteError`（mtime 比对，prepare 阶段，存在 GUI→worker TOCTOU 窗口）；`export_manifest` 无防护（#1172）。
- 查询能力：sqlite 索引支持 asset/version/lineage/tag/managed-raw/external-path 查询 + 聚合；`get_lineage_chain` 支持祖先/后代 BFS；output→run→inputs 反查完整。
- crash consistency：工程文件/manifest 均 temp+fsync+rename+dir fsync+.bak；sqlite 单事务；payload temp+fsync+rename+只读位；trash 三步有恢复探测；`grid_artifact` 写入无 fsync 且固定名 `.tmp` 并发覆盖（#1149）。

## 3. Well 领域

- 导入链：data_page 登记 `type="well_log"` 资源 → 打开项目时后台 `stage_resources` 解析井名 → `migrate_project_to_workarea` 绑定 WellEntity → 显示经 `load_well_log_from_path` → 引擎 `load_las_preview`（max_curves=30, max_samples=100_000）LRU 缓存。
- 井口坐标来自独立 well_head `.dat`/`.xml`，存 `WellEntity.surface_x/y + source_crs`，投影到工程 CRS 存 `project_x/y`；`coordinate_status` 标记 MISSING/INVALID。
- curve 处理：解释性操作仅 depth_shift/despike/baseline_shift 3 种（经 lasio 读写 + catalog DERIVED 版本 + DataRun）；渲染 LOD 用 C++ `minmax_downsample` 仅绘制。**无单位换算（ft 井深度原样进入米制上下文）、无通用滤波/平滑/归一化/重采样**。
- 解释对象：`FormationTop`（含 depth_domain/confidence/status/method）；`CorrelationLink`；lithology/facies 复用引擎区间模型；版本化经 `CorrelationInterpretationDraft` copy-on-edit → `save_correlation_draft` 不可变版本 + catalog 注册 + 重开恢复。
- 多井：`MultiWellEnginePlan`（order_index/shared_display_top/bottom/datum_mode md|tvdss|horizon）；DTW 匹配 + `StratigraphicCorrelationEngine`；`SelectionContext` 总线 active_well_id。
- TimeDepthCalibration：分段线性 (MD m, TWT ms)，fail-closed（无标定返回 None），带 provenance。**风险**：`well_to_seismic` 旁路存在默认 2000 m/s 速度路径（`coordinate_hub.py:494,501-504`）；ft 深度不换算；`seismic_to_well` 无近井返回 `(None, 0.0)` 歧义哨兵。
- **#1193 仍存在**：生产 loader `load_las_preview(max_samples=100_000)` 是 stride 均匀抽稀（非 min-max）；`GeovizOnlineProvider.run` → `build_single_well_payload` 把抽稀行原样发远端 /predict，`WellLogData` 无 truncated/sampled 标志，整条链不感知。
- **#1151 仍存在**：`sample_points_from_well_table`、`well_table_to_arrays`、`apply_mad_outlier_qc` 三处 `z→R_s→H_t` 逐行回退，无量纲比值与米制厚度混入同一插值场。

## 4. Seismic 领域

- 导入链：SEG-Y → `start_transcode`（DataRun "segy-to-zarr"）→ `transcode_segy_to_zarr`（Zarr v3, chunk 64×128×128, shard 128×512×512, zstd-5）→ `_register_derived` mark_stale 旧 DERIVED → `register_derived_store`。
- geometry：`_axis_spec` 支持正/负恒定步长，非线性轴 fail-closed（#1130 已修复，有回归测试）。
- 视图：inline/crossline/time 三正交剖面 + `SeismicVolumeState` 三轴同步；显示模式仅 VD/wiggle；**无 arbitrary line、无 depth slice、无用户 gain/clip/colormap 控制**。
- Interpretation：horizon 拾取 → `HorizonInterpretationDraft`（单 patch 可撤销、fingerprint、no-op 检测）→ `save_draft_as_new_version`（不可变 artifact + sha256 + catalog + 失败补偿）；fault 走 map 断裂线 `fault_lifecycle`。无剖面 fault 拾取。
- 属性：c3 coherence/envelope/inst phase/freq/rms/sweetness/relimp/dip/curvature；ROI halo 扩边一次批量读；全卷按 inline band 流式 + `.done/band_<k>` 续算标记。
- **仍存在的 issues**：#1136（取消路径 reader 线程阻塞满队列 + 30s join 超时 + segyio 句柄关闭竞态）、#1141（`_validate_existing` 不比对 source_path，换源续算产混源体）、#1146（band_inlines=64 硬编码与内存预算解耦，单批 RSS 12-20GB）、#1161（band 标记按位置编号，重开不校验 band_inlines）、#1192（`resume_pending` 不查已存在完整 DERIVED，崩溃窗口后完好旧 store 被误标 stale + 全量重转码）、#1194（band 完成标记只 fsync 目录不 fsync 数据）、#1188（C++ 时斜切片核 prefetch 越界地址计算）、#1189（死测试文件）。
- cancellation 语义：task 尾部 check_cancelled → run 标 "cancelled"；异常 → "failed"；崩溃残留 running → 重开时 `resume_pending` 改标 cancelled。无 "interrupted" 状态。

## 5. Mapping / Factor Map / MapProduct

- Factor pipeline 全链已通：WellTable → factor 别名表 + 派生计算（R_s=H_s/H_t、H_t=base-top）→ `extract_factors` → 插值（mapping 层 Kriging/IDW + workflow 层 geoviz 引擎/约束 IDW 双轨）→ `FactorGridResult`（NaN=nodata、显式 CRS、float32）→ contour/polygonization（纯 Python Marching Squares + DP/Chaikin）→ 约束（断裂屏障/方向各向异性/boundary 环）→ MapDocument 五层 → `MapProductRecord`。
- 组装 `map_product.py:81-172` fail-closed（拒绝 mock/mixed/无 grid version 任务），溯源经 factor_task→run.input_version_ids 可回答"用了哪些井/哪个解释版本/哪个 factor map/什么参数"，但**无一步式查询 API、无 rerun/clone/compare/promote 专用 API**。
- **仍存在的 issues**：#1150（`pipeline.py:150-151` or 链把 0.0 当缺失——丢点/混 CRS 键）、#1162（`document_io.py:98-103` label 坐标无长度守卫 IndexError；well 单元素坐标静默落 (x,0)）、#1159（scheduler 迟到合成默认任务 append 进已变化 live 工程）、#1168（组内 JobCancelled 被记组失败）、#1174（harness `create_factor_map` factor_name 未消毒直接拼 `.npz` 落盘路径——工作区外写）。
- 插值 bounds：数据包围盒 +10% padding，无用户边界/mask；`InterpolationOptions.boundary` 声明但无消费者；无重投影/单位换算/lat-lon 各向异性校正。

## 6. Provider / Harness / Agent

- 管线：ActionSpec（25 个动作：READ 11 / COMPUTE 9 / WRITE 5）→ lookup → validate → permissions → context → governor admit → 执行（provider 或 handler）→ 科学/图验证 → ActionResult。
- Provider 管线：lookup → 参数 schema 校验 → typed inputs → governor lease → catalog begin_run → execute → complete_run。
- **仍存在的 issues**：#1137（`execution.py:202-212` 捕 BaseException 吞 Ctrl-C；TaskCancelled 包成 ProviderExecutionError → DataRun 终态 failed——取消被洗白）、#1160（`seismic_attribute.py:129` ROI finite_ratio `astype(bool)` 把 NaN 计为有限——全 NaN 报健康 1.0）、#1178（schema 校验不强制嵌套 required/additionalProperties；output_schema 是死字段）、#1180（第一方 ImportError → 静默无准入直接执行，无 degraded 记录）、#1185（ToolRegistry 同名静默覆盖 + execute 零校验直调）、#1186（agent_panel 无条件授予 WRITE；map.create_factor_map=COMPUTE 实际写盘+catalog）。
- Agent 诚实性：well/data/qa/result 四个 swarm agent 已按 #1143 加 stub 标注；**gis/carto/seismic/viz 四个 agent 仍硬编码伪造数据**（"topology verified"假宣称、合成网格 status:"success"、模拟属性、假排版）。

## 7. Prediction / Model Security

- TLS-only 已落地（#1144/1145 已修复）：`require_secure_endpoint` 拒绝明文 HTTP，loopback/`.test` 例外；endpoint 只取 env 不取工程参数；API key 仅会话 env，经 `X-API-Key` 头，不入 run 元数据；轮询 URL 限同 scheme+netloc。残留：`online_model_version_id` 可从 run 参数覆盖。
- 模型注册链：checksum 注册时校验、身份冲突拒绝、promote gates；**执行时无 checksum 复核**。
- **仍存在的 issues**：#1152（`inference_service.py:369` `**result` 后置展开——provider 可覆写溯源信封 model/input_snapshot_hash/seed/run_id 等保留键）、#1176（tiled_onnx/builtin inference 接受任意 model_path，无 registry/checksum 绑定——不受信模型可携带注册模型身份）、#1167（生产入口未接 cancel；取消返回 dict 缺 shape 键 → KeyError 把取消伪装成失败）、#1169（线上推理阻塞轮询最长 600s 不可取消）、#1184（`register_provider` 静默覆盖）、#1187（batch/classes 无字节上限，softmax (N,C,64,128,128) float32 随 N/C 无界膨胀）。
- redaction：endpoint/api key 正则脱敏已应用于诊断显示；超时有 clamp（request 120s / poll 600s）；无 retry 机制。

## 8. 持久化 / Roundtrip

- 双存储：`*.paleo.json`（显式 Ctrl+S 保存，三段式 prepare/execute/commit + mtime stale 防护）+ catalog sqlite（变更即时 flush）。无 autosave。
- 已持久化域：resources、well_tables、horizon/fault/correlation_interpretations、version_sets、factor_map_tasks（数值网格外化不可变工件）、prediction_tasks、paleomap_documents、map_products、quality_reports、export_artifacts。
- roundtrip 测试已覆盖：工程相对路径/.bak 恢复、解释 draft→version→reopen、factor grid 外化→reopen→注册、map canvas 样式、joint analysis、catalog 损坏/并发 stale、lineage 深链、异步保存。
- **缺口**：map_products 无 save→reopen roundtrip 测试；inference 取消路径无测试；provider 覆写信封无对抗测试；prepare/execute 间 TOCTOU 无测试。

## 9. 测试基础设施

- 统一 wrapper `run_env.sh <worktree> [args]`：python3.13 + 共享 main worktree 的 geo-viz-engine/well-log-engine submodule + offscreen Qt + libxmlshim LD_PRELOAD。
- 本地验证通过冒烟（test_transcode_axis_spec.py 5 passed）。
- #1181（cp313 .so vs 3.12 钉版）在当前环境以 3.13 wrapper 运行，native 契约测试可用性取决于磁盘 .so 是否存在——需在工作树内确认。
