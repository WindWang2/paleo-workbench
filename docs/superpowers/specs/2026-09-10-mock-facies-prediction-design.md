# Mock 沉积相预测（测井层位相 + 地震相面状）设计

日期：2026-09-10
状态：已确认（mock 阶段）

## 背景与目标

编图工作站 Phase 1「①智能预测」目前只有「叠加已有预测结果」的动作（叠加地震相预测 / 叠加测井相预测 / 测井点到面），缺少「运行生成」的前半步。本设计补齐两个 mock 功能：

1. **测井层位沉积相预测**：点击「运行测井相预测（mock）」，对当前目标层位的所有井各生成一条预测沉积相区间，并显示到地图。
2. **地震相面状沉积相预测**：点击「运行地震相面预测（mock）」，根据目标层位的平面范围生成一个面状沉积相分布，并显示到地图。

两个功能均为 mock：结果是确定性伪随机生成，全程携带诚实标记，绝不进入科学成果链路。

**硬需求（用户明确要求）**：中间文件与生成文件都必须保存，并经 Data Catalog 建立存储关联（DataRun 血缘）。

## 范围

做：两个 stage 动作按钮、两个 mock provider、标准 inference 管线落盘（DERIVED 结果 + INTERMEDIATE 中间件 + run 血缘）、生成后自动叠加显示、回归测试。

不做（YAGNI）：真实模型接入；连井剖面页显示；栅格直显画布（现有链路未接通，面状结果一律 polygonize）；mock 结果进 MapProduct（制度上被拒，保持）；单井预测页新增按钮（已有演示入口，不重复）。

## 总体数据流

```
[阶段面板按钮] StageActionDispatcher.dispatch
   ├─ run_well_facies_mock ─┐
   └─ run_seismic_facies_mock ─┤
        │ _REQUIRES_HORIZON 门禁（无层位 → status_message 拒绝）
        ▼
  prediction/mock_facies.py 两个 mock provider
        │ start_inference(operation=...) → run(running)
        ▼ execute_run
  provider.run(inputs, parameters) 生成 mock 结果
        │
        ├─ 中间文件 → register_intermediate（同 run_id）   .artifacts/intermediate/
        └─ 结果 payload → register_result_asset(stage=DERIVED, run_id)（execute_run 内置）
        ▼
  materialize_prediction_task → project.prediction_tasks.append
        → link_run_to_domain_task（run ↔ task ↔ version 三向链接）
        ▼
  自动调用既有叠加 handler：
        测井 → add_well_prediction_overlay（井点层，角色 WELL_FACIES_PREDICTION）
        地震 → add_seismic_prediction_overlay（多边形层，角色 SEISMIC_FACIES_PREDICTION）
        图层标题与要素 properties 打 horizon 邮戳
```

## 组件 1：mock providers（新文件 `paleo_workbench/prediction/mock_facies.py`）

沿用 `prediction/providers.py` 的 provider 协议（`run(inputs, parameters) -> dict`，JSON 可序列化），经 `register_provider` 注册，模型种子幂等注册（参照 `ensure_default_models`）：两个模型均 `status="demo"`、`demo_only=True`，永不可晋升生产（`promote_model` 对 demo 拒收，制度保证）。

稳定 id 与词表（新增，不复用 demo/heuristic 的 id）：

- `MODEL_ID_MOCK_WELL_FACIES = "mock-well-facies-v1"`，`operation="well_facies_mock"`
- `MODEL_ID_MOCK_SEISMIC_FACIES = "mock-seismic-facies-v1"`，`operation="seismic_facies_mock"`
- 相类词表（与 CONTEXT ClassMap 示例对齐）：`扇三角洲 / 三角洲前缘 / 滨浅湖 / 湖相泥`，各配概率。

### MockWellFaciesProvider

- 输入：全井一次 run（`resource_ids=None` → `resolve_prediction_inputs` 收集全部 well_log 资源）。无输入时 `raise InferenceInputError`（禁止静默随机，对齐 LocalAssetProvider 行为）。
- 生成（`random.Random(parameters["seed"])` 确定性伪随机）：每口可解析井产一条 region：
  `{region_id, well_id, well_name, stratigraphic_unit=target_horizon, top, bottom, facies, probability}`。
  - `top/bottom`：井 `td` 有限时取 `[0.6*td, 0.8*td]`，否则 `[600.0, 800.0]`（mock 占位规则，写入 parameters 供审计）。
  - `well_id` 与 `well_name` 双写（井身份铁律：`Well.id` 是身份，名字仅供显示与在途聚合器分组）。
- 结果形状：`result_summary.predicted_regions=[...]`（在途 `well_prediction_surface._task_regions` 原生消费），外加 `spatial` 不声明（WELL_INTERVALS 由 top/bottom 隐式成立）。
- 中间文件：逐井抽取明细 JSON（含每井 rng 原始抽值、层位、seed）→ `register_intermediate` 挂 `run_id`。

### MockSeismicFaciesProvider

- 平面范围（按优先级）：目标层位已有解释版本 → 其 `grid_xy` bbox；否则 `project.workarea.boundary` bbox；再否则地震工区角点 bbox。来源记入 parameters。
- 生成：workarea 惯例网格（默认 `grid_n=80`）上按 seed 做最近邻斑块分类（mock_facies.py 自实现简化填格：12 个随机相类中心 + 最近邻归类，**不依赖在途的 mapping/well_prediction_surface.py**，保持 prediction 层自包含）→ `FactorGridResult` → `generate_facies_polygon_layer(thresholds=[i+0.5])`（基线模块 `mapping/polygonization.py`）产出多边形 features。
- 结果形状：`result_summary.spatial = {type: "VECTOR_POLYGONS", crs: project_crs, features: [GeoJSON Polygon, properties 含 facies/probability/horizon]}`。坐标落在工程范围内，**不得**触碰 demo 固定方块 `(114.0, 22.5, 0.04)` 邻域（`spatial_result.py` 脏数据探测器）。
- 中间文件：mock 栅格写 `.factor_grid.npz`（`grid_artifact.write_grid_artifact` 惯例）→ `register_intermediate` 挂 `run_id`；多边形 GeoJSON 为 DERIVED 结果 payload 主体。

## 组件 2：stage 动作与按钮（`paleo_workbench/ui/workstation/stage_actions.py`，在途文件上叠加）

- `STAGE_CONTEXT_ACTIONS["facies_calibration"]` 头部插入两项（面板/命令面板自动派生，零额外接线）：
  - `("run_well_facies_mock", "运行测井相预测（mock）")`
  - `("run_seismic_facies_mock", "运行地震相面预测（mock）")`
- 两个 action id 加入 `_REQUIRES_HORIZON`（无层位统一拒绝文案「请先设定编图层位」）。
- Dispatcher 新增两个 handler，直调式（不走 harness；与既有预测执行惯例一致）：
  1. `horizon = active_target_horizon(project)`；`service = DataCatalogService.for_project(project)`（取项目 catalog 的既有方式）。
  2. `start_inference(service, model_version_id=<对应 mock 版本>, input_version_ids=resolve_prediction_inputs(...), parameters={seed: 新生成, target_horizon: horizon, workflow: ...}, operation=...)`。
  3. `execute_run`（mock 毫秒级，UI 线程同步执行；不开 worker）。
  4. `materialize_prediction_task(project, payload, name_prefix="测井相预测（mock）"/"地震相面预测（mock）", workflow=..., target_horizon=horizon, well_log_resource_ids=... / seismic_resource_ids=..., run_id, output_version_id)` → `project.prediction_tasks.append(task)` → `link_run_to_domain_task`（失败置 `model_metadata["link_failed"]=True`，不静默）。
  5. 自动复用既有叠加 handler 完成「然后显示」：测井 → `add_well_prediction_overlay` 的内部实现；地震 → `add_seismic_prediction_overlay` 的内部实现（叠加按 task_id 幂等，新生成的新 task 必然上新层）。
  6. `status_message` 汇报：「已生成 N 口井的预测沉积相（mock）」/「已生成面状沉积相（mock）：M 个相区」。
- 每次运行生成新 seed（`time`/`secrets` 取），保证重复点击产生新 task 而不被幂等跳过；旧叠加层按既有「删旧建新」语义处理。

## 组件 3：存储与血缘（硬需求映射）

| 产物 | Stage | API | 位置 |
|---|---|---|---|
| 测井逐井明细 JSON | INTERMEDIATE | `register_intermediate(..., run_id=run.id)` | `.artifacts/intermediate/` |
| 地震 mock 栅格 `.factor_grid.npz` | INTERMEDIATE | `register_intermediate(..., run_id=run.id)` | `.artifacts/intermediate/` |
| 测井预测 payload（regions JSON） | DERIVED | `execute_run` → `register_result_asset(stage=DERIVED, run_id)` | `.artifacts/derived/` |
| 地震面状 payload（GeoJSON polygons） | DERIVED | 同上 | `.artifacts/derived/` |
| run ↔ task ↔ version 三向链接 | — | `materialize_prediction_task` + `link_run_to_domain_task` | catalog.json + `.paleo.json` |

血缘验证路径：`get_lineage(prediction_version_id)` → run（含 parameters：seed/horizon/grid_n/extent 来源）→ input versions；run → `output_version_ids` + 中间版本（同 run_id）。OUTPUT 仅 `assemble_map_product` 可写，本功能不触碰。

## 诚实标记（不可协商）

两个 provider 的 payload 与 task 全程携带：
`adapter_kind="mock"`、`is_mock=True`、`demo=True`、`final_scientific_prediction=False`、`source="synthetic/demo"`、`probabilities_uncalibrated=True`。
效果：证据面板不误标科学预测；`MapProduct`/`compile_map_production` 对 mock fail-closed 拒收——隔离由制度保证，不靠自觉。

## 错误处理

- 无目标层位：门禁拒绝 + 状态栏提示（既有行为）。
- 无井 / 无可用输入：`InferenceInputError` → run 置 `failed`，状态栏报原因，**不**产出空 task（对齐 inference_service 的诚实失败语义）。
- 无平面范围（无解释、无工区边界、无地震工区）：地震 mock 拒绝并提示，不伪造范围。
- catalog 不可用时：动作整体拒绝并提示（不降级为无血缘产物）。

## 测试计划（tests/，QT_QPA_PLATFORM=offscreen）

1. `tests/test_mock_facies_providers.py`（新）：两个 provider 的输出形状、确定性（同 seed 同结果）、诚实标记全集、无输入报错、地震多边形坐标落在范围内且避开 demo 方块、region 双写 well_id/well_name 且 stratigraphic_unit==层位。
2. `tests/test_stage_prediction_mock_actions.py`（新，参照 test_stage_prediction_overlay.py 惯例）：
   - 无层位 dispatch 被拒；
   - 有层位时测井动作：task 入 `prediction_tasks`、`input_refs` 带 well 键、catalog 出现 DERIVED 版本且 `run_id` 链通、INTERMEDIATE 版本同 run、叠加层出现（角色 WELL_FACIES_PREDICTION）；
   - 地震动作对称断言（seismic 键、VECTOR_POLYGONS、SEISMIC_FACIES_PREDICTION 层）；
   - 重复点击产生新 task（不被幂等吞掉）。

## 命名与文件清单

- 新增：`paleo_workbench/prediction/mock_facies.py`、`tests/test_mock_facies_providers.py`、`tests/test_stage_prediction_mock_actions.py`
- 修改：`paleo_workbench/prediction/providers.py`（注册种子）、`paleo_workbench/ui/workstation/stage_actions.py`（词表 + 门禁 + 2 handler）
- 不改：`mapping/well_prediction_surface.py`、`mapping/factor_layer_products.py`（现有消费端零改动复用）

## 风险与备注

- `stage_actions.py` 是用户 in-flight mapping-stage 功能的脏文件，本次在其上叠加；词表新增项若与在途后续改动冲突，以 `_REQUIRES_HORIZON` 与词表头部顺序为准手工合一。
- 层位显示名与 `representative_facies` 的子串匹配有包含关系陷阱：regions 写 `stratigraphic_unit` 用 `active_target_horizon` 原值，叠加标题用 `_mapping_horizon()` 原值，不做二次加工。
- mock 结果图层 RAW 不可编辑（预测角色保护），人工修编须走 `create_facies_draft` 的 DERIVED 草稿——mock 阶段不接。
