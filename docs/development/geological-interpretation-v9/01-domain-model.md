# 01 — V9 Domain Model（领域模型与 ADR）

## 目标工作流

```
PHASE 1  Evidence / Initial interpretation
   RAW import → EvidenceRef（统一证据契约）
   RAW checkout → DERIVED draft（源版本 pin）→ 人工修编 → InterpretationRevision
   prediction 输出 = evidence（可 pin）
        ↓
PHASE 2  Constraints + single-factor
   ConstraintProduct（组=身份，内容寻址版本链，draft→committed）
   FactorProduct（factor_id 统一身份：grid/contours/polygon/uncertainty/QC 为其 artifacts）
   AlgorithmSpec registry（能力声明唯一权威）
        ↓
PHASE 3  Integrated interpretation
   CompilationInputSet（pin 全部输入版本，可 freeze）
   → fusion run（pinned 输入计算）→ IntegratedInterpretation（first-class artifact）
   → 人工修编 → InterpretationRevision（证据归因）
        ↓
QA / Review（QC 分级 INFO/WARNING/ERROR/BLOCKER；BLOCKER 阻断 publish）
        ↓
MapProduct（DRAFT→REVIEWED→FROZEN→PUBLISHED→SUPERSEDED，冻结禁隐式修改）
```

Stage 仍是 workflow context（V5 §5 语义不变），不是页面。

## ADR-1：V9 领域脊柱放在 `paleo_workbench/workflow/interpretation/`

**决定**：新建子包 `workflow/interpretation/`，模块：
`evidence.py`、`factor_product.py`、`constraint_product.py`、`compilation.py`、
`integrated_interpretation.py`、`revision.py`、`algorithm_registry.py`、
`summaries.py`、`version_compare.py`、`staleness.py`。

**理由**：goal §3 的 ownership 是 `workflow/` + scientific domain models；V8 已把
约束生命周期放 `workflow/constraint_versions.py`，同层延续。不建顶层新包（避免与
`mapping_workspace/`（QGIS 侧投影）和 `catalog/`（数据权威）职责混淆）。

**备选（否决）**：扩展现有散模块（factors.py 等）——P0 的根因正是同一领域对象
散落多处；新建脊柱 + 现有模块投影到它，迁移可渐进。

## ADR-2：全部 V9 对象是投影/索引，不是第二数据库

**决定**：`FactorProduct`/`ConstraintProduct`/`IntegratedInterpretation`/
`InterpretationRevision`/`CompilationInputSet` 是**只读投影或 ProjectDocument 内
的 id-索引记录**（Pydantic 模型，随文档持久化）；载荷与版本唯一权威仍是
Catalog（DataAsset/DataVersion/DataRun）。禁止任何 V9 模块复制载荷。

**理由**：goal §13/§22「不要第二数据库」；基线审计确认 catalog 已具备 CAS、
不可变版本、run 溯源、working-copy 生命周期——重造即倒退。

## ADR-3：Evidence 契约 = 类型化选择器 + 解析结果

**决定**：`EvidenceSelector`（字符串，持久化形态）+ `EvidenceKind`：
`phase1_draft | factor | prediction | constraint_group | catalog_version`。
语法（向后兼容现有词汇并扩展）：

```
draft:<layer_id>                        # 阶段1草稿（content fingerprint 身份）
factor:<task_id>[:<version_id>]         # 单因素（version 空=未pin→UNKNOWN）
prediction:<task_id>[:<version_id>]     # 预测（V9 新增）
constraints:current                     # 浮动引用（诚实 UNKNOWN 语义保留）
constraints:<group>:<version_id>        # 约束组 pin（V9 新增）
version:<version_id>                    # 任意 catalog 版本（RAW 图等）
```

`resolve_evidence(document, catalog, selector)` → `EvidenceResolution`：
`status(resolved|missing|unknown|unpinned)` + pinned_version_id + asset_id +
kind + display + quality 摘要。**显示名称绝不作为身份**（goal §6）。

**理由**：基线 `dict[label→selector]` 的 label 是 UI 文案，随重命名漂移；
类型化选择器让 dependencies/fusion/validation 共用同一解析。

## ADR-4：FactorProduct 是投影，artifacts 统一为引用

**决定**：`factor_product_for_task(document, catalog, task_id)` 生成
`FactorProduct`：factor_id(=task id)、factor_type/family、method(engine id)、
parameters、unit、crs、grid artifact version、input versions、run_id、
uncertainty(bool)、qc 摘要、maturity、staleness verdict、artifacts 字典
（grid/contours/polygons/uncertainty/qc → presence + version ref + absent_reason）。
写路径仍由 `factor_interpolation`/`factor_grid_artifacts` 拥有。

**理由**：raster/contour/polygon/uncertainty 当前是"渲染期重建的孤立产物"
（基线 §1）；统一身份后 Inspector/QA/比较才能引用同一产品的不同 artifacts。
不迁移载荷——npz/grid artifact 机制已被 10k 井规模验证。

## ADR-5：AlgorithmSpec registry 为能力唯一权威

**决定**：`algorithm_registry.py` 声明每个算法（idw/kriging/spline/directional/
constrained_idw/factor_fusion…）：`algorithm_id`、显示名、engine 别名表、
`parameter_schema`、`supported_constraints`（投影自 constraint_capabilities）、
`supports_cancel`、`requires_crs`、`requires_unit`、`produces_uncertainty`、
`backend`、capability。提供 `canonical_algorithm(label_or_alias)` 与
`display_label(algorithm_id)`。`tokens.INTERPOLATION_METHODS` 改为从 registry 派生。

**理由**：基线 P1-10：方法词表 ≥5 处重复；UI/对话框硬编码能力。registry 与
template library 严格分离（goal §32：Algorithm=how to compute,
Template=how to present）。

## ADR-6：ConstraintProduct 收敛双枚举 + CRS 纪律

**决定**：`constraint_product.py` 以 `layer_roles.ConstraintKind`（地质 10 态）
为规范类型，`to_engine_kind()` 投影到 `constraint_capabilities.ConstraintKind`
（engine 5 态）；两枚举间映射唯一化（消灭同名异义直传）。新增
`assert_constraints_crs_compatible(factor_crs, group_crs)`，在插值准备期比对
`ConstraintLayers.crs` 与任务 CRS，不兼容→ValueError（不静默）。组级
`ConstraintProduct`：constraint_id、kinds、geometry 摘要、crs、strength
(properties.strength，缺省 1.0 且诚实标注 default)、confidence(缺省 unknown)、
source、committed version 链、maturity(draft|committed)、staleness。

**理由**：基线 P0-2/P1-3/P1-4。编辑生命周期保持「QGIS 负责几何编辑，
commit 产生新 DataVersion」（goal §11）。

## ADR-7：CompilationInputSet 持久化为结构化记录

**决定**：新 `CompilationInputSet`（Pydantic，存
`ProjectDocument.compilation_input_sets`，additive schema）：entries
（selector + pinned_version_id + resolved_asset_id + added_at + added_by）、
`freeze()`（把全部可解析 entry 的版本钉死；不可解析→拒绝并报告）、
recommendation 记录、frozen 标志。工作区旧 `compilation_input_set` dict 保留为
向后兼容视图（由结构化记录镜像；dependencies 优先读结构化记录）。

**理由**：goal §14「不能拿当前可见当科学输入」；基线 P0-3/P1-6/P1-7。
不修改旧字段形状（dependencies/存档兼容），新记录为权威。

## ADR-8：IntegratedInterpretation + InterpretationRevision

**决定**：
- `IntegratedInterpretation`（存 `ProjectDocument.integrated_interpretations`）：
  input_set_id（pin）、run_id、geometry layer_id、committed catalog version id、
  class schema、confidence/uncertainty 摘要、conflicts 摘要（agreement/
  conflict/support count）、revision_ids、qa（product 级）、maturity、staleness。
  `commit_integrated_interpretation()`：层几何 → catalog DERIVED 版本 +
  `integrated_interpretation` DataRun。
- `InterpretationRevision`（存 `ProjectDocument.interpretation_revisions`）：
  target（layer/interpretation id）、parent_revision、base（algorithm seed 版本/
  RAW 版本）、evidence_refs（本修订依据的 factor/constraint/draft 选择器）、
  actor、delta 摘要（EditDelta 聚合：op 计数）、content_fingerprint、note。
  `stage_save` 对 draft/integrated 层自动记录（无编辑则不产生空 revision）。

**理由**：goal §13「algorithm result + manual interpretation delta」、§17
human-in-the-loop、§18 conflict 保留。复用 EditDelta 形状（基线 P2-10），
不建 revision 专用存储。

## ADR-9：统一 staleness 词汇 + 贯通到 MapProduct

**决定**：`staleness.py` 定义 `StalenessVerdict`：
`CURRENT | STALE_CONTENT | STALE_VERSION | MISSING_INPUT | SUPERSEDED | UNKNOWN`
（证据不足→UNKNOWN，绝不猜 CURRENT，goal §20）。适配器：
`from_constraint_pin` / `from_workspace_status` / `from_run_freshness`。
`evaluate_verdict(document, catalog, artifact_key)` 为 Inspector/summary 单入口。
`freshness._LINEAGE_EXPECTED_OPS` 与 `recompute_plan` 增加
`factor_fusion / constraint_commit / map_product_assembly /
integrated_interpretation`；`step_freshness` 增加 fusion 阶段。
两旧引擎保留（各自权威域），verdict 是汇聚层而非替换——避免大爆炸迁移。

**理由**：基线 P1-2/P1-12；goal §19 依赖链贯通
well→factor→input set→interpretation→product。

## ADR-10：MapProduct 显式生命周期 + 产品级 QA

**决定**：`MapProductRecord` 增加
`lifecycle: Literal["draft","reviewed","frozen","published","superseded"]`
（读取时与旧 `status/frozen` 和解：frozen→frozen、superseded→superseded、
final→draft[待审]）。转换 API：`review_product`（需 QA 无 ERROR）、
`freeze_product`（沿用 freeze 语义 + BLOCKER 门）、`publish_product`
（需 lifecycle=frozen + 无 BLOCKER + staleness==CURRENT 或显式接受降级记录）、
`supersede_product`。冻结后隐式修改→拒绝。产品级 QA：`product_qa(document,
record)` 运行 map_qa_rules 并把报告 id 挂到 record（publish 门禁查产品级报告，
不再只看工程级 active report）。`MapProductAssembly` 增加
`fusion_version_id` / `integrated_interpretation_id` / `input_set_id` 引用。

**理由**：goal §30/§31；基线 P1-8/P1-9 与"三套生命周期"收敛。

## ADR-11：任务状态补 CANCELLING/DEGRADED

**决定**：`TaskState` 增加 `CANCELLING`（cancel_requested 且 RUNNING 时呈现）
与 `DEGRADED`（终态：完成但校验降级/注册失败——"成功"必须含 registered
artifact + DataRun + output version，否则最多 DEGRADED）。终态判定集合
`TERMINAL_STATES` 扩展。旧持久化字符串兼容（unknown 值按旧语义映射）。

**理由**：goal §27 状态词汇统一；基线 P1。

## ADR-12：UI 通过共享科学核心收敛（不重排 Dock）

**决定**：不把 stage_actions/mapping_page 全量改走 HarnessExecutor（那是
Workstation Dock 方向的地盘）。V9 要求：**同科学操作只有一个实现**——
`create_factor_map` 补齐 pin/指纹（调用 `factor_interpolation` 共享核心）；
stage 的组装/融合/提交动作与 harness action 调用同一领域函数。
新增 UI 入口最小化：P2「提交约束版本」动作、evidence 对话框纳入 predictions、
Inspector 消费 summaries 契约。

**理由**：goal §3「允许通过契约少量修改 UI」；基线 P0-1/P0-8 以"单一实现
双入口"解决而非 UI 大迁移。

## ADR-13：立即登记（interpolation 完成即注册版本）

**决定**：插值/融合等科学后台任务完成时，若 catalog 服务可用，立即注册
INTERMEDIATE/DERIVED 版本 + DataRun（不等 project save）；注册失败→任务
DEGRADED + 状态消息诚实说明（不伪称成功）。save-time 注册保留为幂等补登记。

**理由**：goal §27「后台任务完成必须有 registered artifact/DataRun/output
version」；基线 P0-7「成功即版本」缺口。
