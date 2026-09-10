# 04 — Layer system & attribute table（V9）

## 1. 图层树权威（复核，无结构变化）

V8 裁定维持：`QgsLayerTree/QgsLayerTreeView`（C++ 面板宿主）为运行时
图层树权威；`LayerGroupController` 的 desired-tree 是组结构权威的宿主侧
表达，经同一 QGIS 树增量 reconcile（`groups=True` 模式跳过 root 平铺
推送）；`QgisLayerTreePanel._layers` 为呈现读模型（`_publishing` 抑制回
写）。V9 未改动该结构——审计确认其「双写抑制 + 回调回写」模式是 V5/V7
评审后的稳定形态，重建只会引入回归面。

## 2. 编辑层的 provider schema（W6）

**变更**：工作站编辑层从此携带 role 标注（快照 `metadata.role`，由
stage membership 单权威派生——控制器 `set_role_lookup` 注入，见
03-decisions D4）。链路：

```
snapshot.metadata.role ──► _fields_json_for_metadata（role → GeologicalLayerSpec）
                          └─ 未知 role → 诊断（不再静默 ""）
                                ▼
                C++ parseFieldSchema → QgsFields/约束/控件/默认值（V8 M1）
                                ▼
                _verify_published_schema（V9 新增）
                  读回 mirror_layer_schema_json，比对字段名序 + 类型
                  ── 漂移 → 诊断条目（发布不阻塞，漂移在案）
```

配套修复：`TypeError` 重试丢弃 `fields_json` 时记诊断（此前静默无
schema 发布）。

**效果**：断层/物源方向等角色图层在 QGIS 侧有真实 QgsFields——字段
分类渲染可绑、identify 属性可读、（未来）原生表单可用；属性表
（W5）与镜像同源，无 schema 漂移。

## 3. 属性表（W5）

`CompositeAttributeTableDialog` 升级为 QGIS provider schema 的诚实消费者
（数据权威不变：仍是 `VectorEditSession`）：

| 面 | V8 前 | V9 |
|---|---|---|
| 列元数据 | 模板 schema | `attribute_schema.field_descriptors_for_layer`：**角色 spec 优先**（与 fields_json 同权威）→ 模板回落 → 额外属性键 |
| 列头 | 字段 label | 别名 + 必填标记（`*`） |
| 编辑器 | 全文本 | 控件词表驱动：choices → ValueMap 下拉、bool → CheckBox、数值 → Range（带上下界校验器） |
| 约束反馈 | 无 | 必填空值 / Range 越界 → 拒绝写入 + 判词（与 QGIS provider constraint 同向同源） |
| 排序 | 无 | 表头点击；数值列 DisplayRole 为 float（数值序），不可解析保持文本 |
| QGIS 一致性 | 无 | 状态行 parity 标注：synced（「QGIS provider schema 一致」）/ drift（⚠ 字段差异明细）/ unavailable（旧桥/回退画布） |
| 差量刷新 | 既有（C-P0-3） | 保留；排序后行映射经 `_on_sort_changed` 重建，新字段出现时列缓存失效走全量 |

QgsDualView 全托管评估决策见 03-decisions D3。

## 4. 测试

`tests/test_v9_schema_and_attribute.py`（13 项）+ qgis-marked 端到端
（`test_qgis_v9_bridge_surface.py::test_mirror_snapshot_verification_end_to_end`
——role 标注快照 → mirror → 真实 QgsFields 断言 name/fault_type 在位 +
无 drift 诊断）。
