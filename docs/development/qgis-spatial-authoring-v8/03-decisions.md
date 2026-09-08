# 03 — Decisions

审计驱动的裁定记录（依据 00-overlap-audit + 实现代码）。

## D1 — M1 字段权威链（W1）

```
GeologicalLayerSpec（唯一字段权威，Python 验证）
  → qgis_layer_schema.fields_json_for_spec（wire，V7 已有）
  → C++ parseFieldSchema（新）：wire → QgsField（类型/长度/精度）
      + 字段级 QgsFieldConstraints（not_null/unique/expression，provider origin）
      + QgsEditorWidgetSetup（ValueMap/Range/CheckBox/DateTime/TextEdit + domain 配置）
      + QgsDefaultValue（字面量 → QGIS 表达式）
  → applyFieldSchema（新）：provider addAttributes/deleteAttributes + updateFields
      + 图层级 setFieldAlias / setEditorWidgetSetup / setDefaultValueDefinition
  → QgsJsonUtils::stringToFeatureList(text, fields, nullptr)（typed 解析——
      properties 不再被空 QgsFields 丢弃）
  → mirrorLayerSchemaJson / mirrorFeaturesJson（自省面：测的是 provider 真相）
```

关键裁定：
- **约束随 QgsField 进 provider**（ConstraintOriginProvider）——属性表单按
  field.constraints() 强制，与 origin 无关；不额外用 layer.setFieldConstraint
  造第二份约束声明。
- **schema 漂移 = 整体重建**（deleteAttributes 全部 + re-add），不做
  per-field changeAttributeType——host 是数据权威、全量重发语义下，整体
  重建不可能留下半迁移状态。
- **schema 变化强制跳过 delta 通道**：delta 的 delete+re-add 只覆盖变更
  要素，schema 换血后未变更要素的属性会丢——漂移时回退全量路径（代码
  显式 `&& !schema_changed` 守卫）。
- **畸形 wire 抛错（fail-closed）**：能到桥的坏 JSON 只能是编程错误；
  静默降级会掩盖 spec↔provider 漂移。
- **`__pwb_fid` 不进 schema**：身份侧信道继续走原文抓取 + fid 表，与
  provider 字段互不污染。
- **OGR positional quirk（实现期发现）**：vendored 4.2 的
  `stringToFeatureList(text, fields)` 对属性按**位置**映射（`__pwb_fid`
  首键实测错位后续字段值）——W1 不用该路径，手工构建 QgsFeature：
  几何 `geometryFromGeoJson`、属性按名 `setAttribute`；缺省属性 = NULL
  （诚实），`__pwb_*` 键天然忽略。

## D2 — M3 复合撤销原子性（W2）

- **命令对象身份制**：传播命令按 `undo_stack` 中的对象身份追踪（不是
  位置——用户后续编辑会移动栈位）。
- **all-or-nothing + 快照命令粒度**：SetVertex 系列存整要素快照，冲突
  检测按要素粒度（同要素后继编辑 → 整组拒绝），**同组命令互不算冲突**
  （多边形闭合点会产生同要素双命令）。
- **历史寄存在组**：pop 的命令不进任何单层 redo 栈——单层 redo 不能
  重放半组；复合重做以各涉及会话的 revision 快照守卫（撤销后任一层有
  新编辑 → 拒绝重做，线性历史）。
- **会话终结即作废**：提交/回滚/删层 → discard_compounds（与单层 undo
  随会话消失的语义一致）；宏打开时如实降级 compound_registered=False
  （保持 V7 非原子行为并上报）。
- **双宿主同语义**：机制在 TopologyService（mapping/topology.py），
  workstation（edit_command）与编图页（_on_action_command_requested）
  都经 pending_compound 拦截。**修订（review-2）**：V7 里编图页的同层
  原子性来自宏合并（P1-4 的 begin/end_edit_command），并非本机制——
  V8 把传播回调移到宏关闭后（map_tools._commit_vertex），同层/跨层统
  一由复合组承载原子性；生产路径以真实 _commit_vertex 驱动的回归钉
  钉死（此前测试绕过宏，恒未覆盖真实调用序列——review-2 P0）。
- **origin 命令传播前捕获**：同层传播会把自己的命令压过 origin，事后
  读栈顶会错认 origin；origin 于传播循环前按 skip 参数捕获。

## D3 — M4 收敛边界（W3）

- **语义变体进内核、调用方只做适配**：边界包含 PIP（工区井位分类）
  提升为 `point_in_ring_scalar_inclusive`（显式 on-edge + epsilon），
  与默认 even-odd 内核并列——语义差异必须显式命名，不能靠调用方复刻
  隐式存在。
- **线段距离单一内核** `distance_to_segment`（原 map_interaction /
  composite_editing 两份内联）。
- **facade 补缺吸收复刻动机**：`centroid`（面=面积质心、线=顶点均值——
  显式声明非 shapely 线积分；qc 顶点均值复刻已迁）与 `bbox_intersects`
  （闭区间 + tolerance；cartographic_qa 手工判定已迁）。
- **保留不动**（记录于 01-scope）：map_qa_rules 逐点越界（热循环）；
  workarea survey 角点均值（矩形算术恒等，非 GIS 复刻）；F7 双索引合并
  延后。
- **facade host ops 零调用问题**：crs_transform_xy/repair 等此前无生产
  调用者——F10/F11 迁移后 domain_binding/gis_agent 成为真实消费者，
  "零调用"状态解除。

## D4 — M2 编辑面：不新增按钮（决策）

30 工具 evaluator 门控的现有面（pan/zoom/measure/identify/select×2/
add×3/move/vertex/reshape + 21 个桥几何算子经 geometry_operations 门面）
已覆盖目标地质工作流（物源线/方向/展布线/岸线/相带边界/断层/相面/插值
边界/mask/综合边界）。逐能力裁定：
- **split/merge**：经门面可用（split_polygon_by_line/merge_selected_
  polygons，桥优先）；不加独立工具按钮——选集+右键菜单已是入口。
- **rotate/translate/advanced digitizing/tracing**：不做。旋转/平移对
  地质制图语义弱（move_feature 已覆盖平移）；追踪与高级数字化面板属
  QGIS 桌面级交互，与 Paleo 的版本/门禁权威（RAW/锁定）模型冲突面大。
- **add/delete ring、multipart 处理**：会话命令已存在（AddRing/
  DeleteRing/单复互转在门面），按需经菜单入口即可，不做画布工具。
- **Python fallback 冻结**：维持 V7 契约（reshape 无回退等），不扩张。

## D5 — M8 legend filter 的实现路径

- `setCustomLayerTree` 在 QGIS 4.2 已 **private**——公开等价路径是
  `setSyncMode(Qgis::LegendSyncMode::Manual)`（内部克隆工程树）+
  `model()->rootGroup()`（即那份手动树）剪枝。剪枝用
  `QgsLayerTreeGroup::removeChildNode`（连节点销毁，无泄漏）。
- include 表解析顺序：mirror doc_id → QGIS layer id → layer name；
  空表/缺省键 = 不过滤（历史行为）。工程本树永不被触碰（测试钉死
  tree_snapshot_json 前后一致）。

## D6 — 运行时配方（M9 关联，工程事实）

V7 遗留两套 Windows 运行时配方并存，V8 显式化（tests/conftest.py +
scripts/run_qgis_env.py）：
- **默认（authoring 系）**：PySide6 6.8.3（与 vendor build 的 Qt 6.8.0
  同 minor）+ 自包含 vendor bin（381 DLL，含 Qt6Core5Compat）。
  `ensure_qgis_bridge_dll_dirs` 是唯一 loader 权威 + MSVCP 预钉。
- **conda-Qt 统一（cartography 系，PALEO_QGIS_CONDA_QT=1）**：中性
  vendor（5 DLL）+ deps 前缀预载。本 worktree 的标量栅格（osgeo）测试
  在默认配方下诚实跳过（osgeo 与 vendor gdal 的 DLL 名冲突无解），
  CI qgis 腿覆盖该路径。
- 混用两套（如 conda Qt satellite 抢占 PySide6 Qt）→ WinError 127，
  已在 conftest 注释与本文件记录——不引入第三套。
