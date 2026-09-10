# 02 — Tool context & availability（V9 W1）

## 1. ToolContext v3（contract_version=3，纯增量）

新增事实（全部来自权威，非 UI 猜测）：

| 字段 | 来源权威 | 语义 |
|---|---|---|
| `project_crs: str` | 工程文档（经 crs_contract 归一） | "" = 未声明（诚实未知，不静默 4326） |
| `layer_crs: str` | 活动图层记录 | 同上 |
| `scale_denominator: float` | 原生：`QgsMapCanvas::scale()`（桥 `canvas_scale`，探针门控）；回退画布：仅米制轴可证时由 mupp×39.37×dpi 推导，否则 0.0 | 0.0 = 诚实未知 |
| `snapping_available` | **派生**：原生路径 = 桥 manifest `snapping_push` flag；回退画布 = True（sanctioned Python 执行体） | 不再硬编码 True |
| `topology_available` | **派生**：桥 `geometry_op.validate` 或 Shapely 任一可用 | 同上 |
| `topology_error_count` | **生产生产者**（W2，见 04） | 从仅测试写入的死事实变为真实门禁输入 |
| `blocking_task` | `_mapping_blocking_task_label`：运行中 workflow DAG（改写编图产物） | 从仅 visual-QA 写入变为生产事实 |

采集分工：`CompositeEditController.tool_context_inputs()`（会话/选集/CRS/
计数）+ `CompositeDocument.tool_context()` 注入画布比例尺与阻塞任务（文档
拥有画布与调度器视野——注入而非在采集器里猜）。

## 2. evaluator 规则变化

- `_rule_snapping`：`snapping_available=False` → 禁用 + 「当前环境的捕捉
  引擎不可用（桥缺少 snapping 配置通道）」。
- `_rule_topology`：`topology_available=False` → 禁用 + 引擎缺失判词。
- `_rule_merge`：`topology_error_count > 0` 门禁现在**可从真实状态触发**
  （此前生产环境恒 0）。

## 3. 执行前 re-gate（V8 既有，V9 复核）

全部表面（toolbar/palette/shortcut/context menu/stage panel）经
`_on_command_requested`/`_on_tool_requested` 单一入口，执行时以最新
context 重新 evaluate，禁用时以 evaluator 判词 fail-closed。图层树右键
编辑动作仍走 `_role_allows_editing` 单点门禁（V8 裁定保留——树菜单的
动作语义是「开始编辑」而非完整工具矩阵；09 记录为已知边界）。

## 4. 测试

- `tests/test_v9_interaction_facts.py`：v3 事实、可用性派生（原生门控/
  回退恒真）、evaluator 门禁、merge 门禁消费真实计数。
- `tests/test_qgis_v9_bridge_surface.py`：桥 manifest flag + scale 随范围
  减半 + destination CRS 自省（proj 缺席环境诚实空串）。
