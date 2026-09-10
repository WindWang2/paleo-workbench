# 00 — Baseline（V10）

审计日期：2026-09-11。基线 `origin/main = 3b0e2ba2`（PR #1250 合入点；
worktree 检出于该提交，实现为未提交工作树改动：`qgis_runtime/` 新包 +
桥 0.6.0a0 扩展 + host 侧配套）。worktree：
`C:\Users\wangj.KEVIN\projects\paleo-workbench-qgis-spatial-layer-v10`，
分支 `feat/qgis-spatial-layer-platform-v10`。

## A. 前置集合（均已合入基线）

| 集合 | PR | 备注 |
|---|---|---|
| qgis-geological-authoring-v9 | #1248 | V9 W1–W10 全量（docs/development/qgis-geological-authoring-v9/00-baseline.md） |
| geological-interpretation v9 | #1249 | 解释工作台 |
| facies-svg-patterns-toolbar | #1250 | 基线合入点本身 |
| adaptive-workstation-ui-v9 | #1251 | 工作站 UI |
| V7/V8 系列 | #1236–#1247 | 见 V9 baseline §B，本表不重复 |

## B. 本轮针对的 V9 已知限制 / 起点审计缺口

（引用 V9 限制时标注 docs/development/qgis-geological-authoring-v9/09-known-limitations.md
的条目号；其余为 V10 起点审计新增发现。）

1. 桥 `canvas_destination_crs` 在 vendor 配方下常返回 ""——vendored
   build 无 proj.db，QGIS 侧 CRS 无法解析（V9 限制 #1）。
2. quiet-4326 残留面：geological_pipeline models / extract_factors 默认
   值、`well_location_xml._crs_from` 依 lon/lat 形状猜 4326（V9 限制 #8
   家族的存量消费点）。
3. 桥 loader 逻辑在 5+ 处重复（scripts 入口、tests/conftest.py、
   `qgis_style.ensure_qgis_bridge_dll_dirs`、main 等），默认根 3 套
   并存——无单一发现权威。
4. 桥版本漂移：`setup.py` 0.4.0a0 vs bindings 0.5.0a0（同一桥两个
   版本号）。
5. mirror 发布账本缺 name token：编程改名后 no-op 比较命中陈旧条目，
   C++ `setName` 永不执行。
6. `id(stack)` 复用风险：栈销毁后同地址新建栈，陈旧 token 复活。
7. 活动层漂移位点 D1–D6（审计标注的 6 处 active-layer 状态读点，
   切换/重绑定路径上读写不一致）。
8. 无 provider 能力探针：`vector_writable` 仍是猜测，编辑门禁无事实源。
9. snapping 配置不持久化：工程重载后 per-layer 覆盖丢失。
10. 原生画布无 scale-range 通道：比例尺可见域只在 fallback 生效。
11. QgsProject CRS/ellipsoid 从不配置：椭球测量分支死代码
    （V9 限制 #3 的根因，02-crs-transform.md §3 关闭）。

## C. 实证探针结果（2026-09-11，本机）

- **conda 配方**：桥 0.5.0a0 加载成功；EPSG:4326/4490/4214 解析成功，
  垃圾 CRS 诚实返回 ""——proj.db 经 conda deps 前缀可达。
- **默认（self-contained vendor）配方**：本机不可用——PySide6 已升级
  6.11.2，与 6.8 时代自包含 vendor DLL 的 Qt 契约不匹配。该运行时漂移
  由 `qgis_runtime.health` 诊断（01-qgis-runtime.md §3/§6）。

## D. 已交付基线（禁止重做）

| 来源 | 已交付 | 证据 |
|---|---|---|
| V7 #1236/#1237 | capability manifest/snapshot、ToolContext、45 工具 evaluator、GeologicalLayerSpec V2、几何 facade、标量栅格镜像、增量发布 ledger | `mapping/capability_model.py`、`tool_availability.py`、`mapping_workspace/geological_layer_spec.py` |
| V8 #1238–#1240 | provider fields（fields_json→QgsFields/约束/控件）、compound topology undo、context control plane | `mapping/qgis_layer_schema.py`、`mapping/topology.py`、`ui/workstation/` |
| V9 #1248 | ToolContext v3 事实（project_crs/layer_crs/scale）、topologicalEditing 推送、crs_contract 单一谓词权威、attribute table 收编 provider schema、测地测量 fallback | `mapping/crs_contract.py`、`mapping/tool_context.py`、`ui/workstation/composite_attribute_table.py` |
| #1246/#1247/#1249–#1251 | QTimer context 绑定修复、解释工作台、SVG 图案工具条、工作站 UI | `runtime/`、`ui/workstation/` |

## E. 硬排除（沿 goal 约束）

- 100GB seismic：任何形式新增支持/基准/优化/体数据路径改动 = 禁止。
- 新第二 evaluator / 第二 ToolAvailability / 第二 layer tree authority /
  Python 复刻 QgsRubberBand 捕获：禁止。
- vendored QGIS 重建：禁止（仅链桥扩展 + proj.db 部署，
  01-qgis-runtime.md §4）。
- QgsDualView 全托管：维持 V9 D3 决策不做（06-provider-schema.md）。
- fallback QPainter backend：冻结不扩张（07-rendering.md §3）。

## F. 决策索引

| 决策 | 主题 | 文档 |
|---|---|---|
| D1 | qgis_runtime 单一发现/加载权威 | 01-qgis-runtime.md |
| D2 | proj.db 部署进 vendor，不设 PROJ_DATA | 01-qgis-runtime.md |
| D3 | 双配方并存 + health 漂移诊断 | 01-qgis-runtime.md |
| D4 | 提交守卫判定表（fail-closed） | 02-crs-transform.md |
| D5 | set_destination_crs 恒调用 | 02-crs-transform.md |
| D6 | 数字化 scratch raw-frame（去 quiet-4326） | 02-crs-transform.md |
| D7 | ProjectDocument vs QgsProject 权威边界 | 03-qgsproject-authority.md |
| D8 | snapping 持久化通道 schema_version 1 | 03-qgsproject-authority.md |
| D9 | pwb/doc_id 身份 + 账本 token 加固 | 04-layer-registry.md |
| D10 | provider_writable 三态门禁 | 06-provider-schema.md |
| D11 | unique Python 侧 / 表达式 provider 侧 | 06-provider-schema.md |
| D12 | 样式回读语义签名 | 07-rendering.md |
| D13 | scale-range 桥通道 | 07-rendering.md |
| D14 | 空间查询双路径分工维持 | 08-spatial-query.md |
| D15 | boot 顺序（loader 先于 PySide6） | 09-lifecycle.md |
