# 06 — Provider 事实与 schema（V10）

## 1. `mirror_provider_facts`（桥 `provider_introspection`）

C++ 侧一次自省返回 provider 事实，宿主经 `canvas_shim.mirror_provider_facts`
（canvas_shim.py:937）读取。旧桥探测阴性 → 返回 None → 门禁不激活
（§2 的 None 语义）。

**vector**：`provider` / `storage` / `geometry` / `wkbType`；capability
flags（`add_features` / `delete_features` / `change_geometries` /
`change_attribute_values` / `add_attributes` / `delete_attributes` /
`create_spatial_index` / `transaction_support`）；`supports_editing` /
`is_editable`；`spatial_index` 存在性；`feature_count` / `extent` /
`crs` / `field_count`。

**raster**：`provider` / `extent` / `band_count`；per-band `data_type`
（`Qgis::DataType` int 枚举值）+ `nodata`。

现状：只有 memory provider 活着（12-known-limitations.md 第 2 条）。

## 2. ToolContext v4：`provider_writable` 三态（D10）

新增 additive 字段 `provider_writable`（tool_context.py:159）与
`provider_name`（tool_context.py:161）：

| 值 | 语义 | `_writable_gate`（tool_availability.py:258）行为 |
|---|---|---|
| `None` | 无自省面（旧桥/非镜像层） | **不门禁**（不因无知而拦） |
| `False` | provider 明确不支持编辑 | fail-closed：「图层 provider（X）不支持编辑——只读数据源」（tool_availability.py:264） |
| `True` | provider 支持编辑 | 放行（其余门禁照常） |

关闭 00-baseline.md §B.8：`vector_writable` 的 `layer is not None`
猜测（V9 审计 C1-P1）由 capability 事实替代。探针代价核算见
10-performance.md §4。

## 3. schema 权威（单一）

- **`GeologicalLayerSpec` 仍是唯一 schema 权威**（V7 起裁定）；
  provider 事实（§1）是能力面，不是第二 schema。
- widget 推断单一化：`ui/workstation/attribute_schema.py` 现在**从**
  `mapping/qgis_layer_schema._editor_widget_for`（qgis_layer_schema.py:70）
  导入——此前工作站侧有一份平行推断表，构成漂移面；V10 收敛为一个
  推断权威（attribute_schema.py:61 起 import）。

## 4. 约束执行（D11）

- **unique 约束 Python 侧执行**：`composite_attribute_table._write_attribute`
  （composite_attribute_table.py:344）在字段带 unique flag 时 O(n) 扫描
  既有值——空值永不冲突；数值字段按 float 相等比较。这是会话权威
  （编辑命令链）侧的诚实执行，不依赖 provider 侧约束。
- **表达式约束 = provider 侧 only**：QGIS 表达式约束在镜像
  QgsFields 上声明、由 QGIS 侧（表单/校验）消费；Python 会话**不复刻
  表达式引擎**（复刻即第二约束真源）。记录在案，不假装 Python 侧
  已执行。

## 5. VectorEditSession

维持 schema-agnostic（V8 起裁定）：会话只认 feature/命令模型，
schema 事实经 ToolContext/属性表层注入——本批不动。
