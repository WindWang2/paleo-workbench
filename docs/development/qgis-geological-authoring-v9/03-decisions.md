# 03 — Decisions（V9）

## D1 — CRS 契约模块（W3）

**决策**：新建 `paleo_workbench/mapping/crs_contract.py` 作为单一 CRS
谓词/解析权威；不重实现轴数学——`crs_is_geographic` 委托
`workflow.crs_policy`（轴单位真源），`normalize_crs` 委托
`map_render_backend._normalize_crs_name`（归一化真源）。

**理由**：审计发现 4 套并存谓词/归一化器 + 8 处 quiet-4326。其中
`qgis_mirror._geographic_auth` 的字面量集合 {4326, 4269, 4258} 漏掉
CGCS2000(4490)/Beijing1954(4214)/Xian1980(4610)——这些地理系的图层曾
跳过度域 extent 检查（真实缺陷，去重即修复）。

**边界**：`resolve_crs` 对未声明 CRS 返回 degraded resolution（带 purpose
的判词），绝不静默回填 4326。存量 dataclass 默认值（`layers.py:498` 等
wire 兼容默认）保留——消费点经契约解析后，未声明状态有判词可查；参考
图层导入在未声明时**拒绝**（不再 `or "EPSG:4326"`）。

## D2 — topology_error_count 的刷新点设计（W2）

**决策**：`TopologyService` 增 per-layer 计数缓存
`(data_revision, session_revision, count)`；只在**有界刷新点**重算
（save/flush 校验、拓扑开关开启、几何命令、undo/redo、显式校验、
delete_selected），上下文采集只读缓存。

**理由**：备选方案「上下文构建时惰性重算」把 O(features)×GEOS 校验挂到
帧级链——10 万要素层一次拖顶点就全量重校验，违反 §26。缓存读为
O(层数)。语义与 save 门禁一致：从未校验 = 0（不因未知而拦），校验后
编辑 → 保持最近已知值直到下一刷新点；会话提交/回滚后不再计入。

## D3 — attribute table 不做 QgsDualView 全托管（W5）

**决策**：`CompositeAttributeTableDialog` 以 **QGIS provider schema 事实
驱动的诚实消费者**收编——列元数据 = `GeologicalLayerSpec`（与镜像
fields_json 同权威，无 schema 漂移）+ `mirror_layer_schema_json` parity
标注（synced/drift/unavailable）；ValueMap/CheckBox/Range 编辑器、必填/
范围约束反馈、数值感知排序。**不**在桥内托管 QgsDualView/QgsAttributeTableView。

**理由**：QgsDualView 全托管 = C++ 宿主面板 + editor widget 注册表 +
form layout 同步（估 1500+ 行桥代码 + 新生命周期面），而数据权威必须
留在 Python 会话（编辑命令链）——DualView 的 provider 直编路径与
VectorEditSession 命令模型冲突，双真源风险高于收益。当前方案让 V8 M1
的 provider 控件/约束第一次有了 UI 消费者，且 parity 标注让漂移可见。
全托管评估留档，若未来需要 QGIS 表格的完整交互（表单视图/表达式过滤）
再立项。

## D4 — 编辑层 role 标注的单一权威（W6/W9）

**决策**：控制器不自持角色表——`set_role_lookup` 注入 stage membership
查询（`CompositeDocument._layer_role_value`）。快照 `metadata.role`、
捕获默认值（`_capture_defaults_for_role`）、`apply_capture_spec` 全部
经该查询派生。

**理由**：备选「create_layer(role=) 在控制器存一份」会造成
register_layer（stage 权威）与控制器内表两处角色漂移。派生注解 =
goal §14 的「QGIS fact + Paleo semantic annotation」形态。

## D5 — 捕捉推荐 ≠ 硬编码真值（W4）

**决策**：`snapping_profiles.py` 角色簇表（boundary/shoreline/fault/
direction/line_constraint/polygon_constraint/draft/general）携带 rationale；
应用写 `SnappingService` 既有 per-layer 覆盖通道；对话框右键「按角色推荐」
同时呈现完整推荐语。RAW 保护角色无推荐（不可编辑，推荐无意义）。

**理由**：goal §18 原文「Profile 应可解释、可修改」。模式词表 =
SnappingService 既有词汇（vertex/segment/midpoint/endpoint/intersection/
reference/grid），不发明第二套模式语言。

## D6 — blocking_task 的诚实词表（W1）

**决策**：只有改写编图工程产物的运行中任务阻塞工具面：kind ==
"background.compute" 且 title 以 "workflow:" 开头（DAG 引擎的编图工作流
运行）。渲染/转码/交互查询不阻塞（QGIS 桌面惯例：processing 运行不禁用
工具条）。

**理由**：备选「所有运行中任务都阻塞」会把预览渲染变成全局模态——
过度阻断与 V8 的保守语义都不诚实。词表集中在
`_mapping_blocking_task_label` 单点，采集廉价（statuses() 快照）。

## D7 — 桥 API 纪律（0.5.0a0 三个新增）

| API | 为什么 Python/binding 做不了 | 线程/生命周期 | 失败模式 | fallback |
|---|---|---|---|---|
| `set_snapping_config` 增 `topological_editing` 键 | QgsProject 单例状态，Python 无 qgis 绑定 | GUI 线程（既有配置推送路径） | 旧桥忽略未知键 → host 侧 manifest flag 门控后才发 | 不推送（宿主 TopologyService 仍权威） |
| `canvas_scale` | QgsMapCanvas::scale() 需 C++ 画布指针 | GUI 线程只读 | 无 extent → 0.0（诚实未知） | 回退画布米制推导 / 0.0 |
| `canvas_destination_crs` | 同上（mapSettings 快照） | GUI 线程只读 | CRS 无法解析（proj.db 缺席）→ ""（诚实未知） | 守卫按「未知不比对」 |

均满足 §25 的进入标准（performance critical 之外全是「Python 无法触达
的 C++ 状态」）。版本 0.4.0a0 → 0.5.0a0，manifest 增
`snapping_topological_editing` flag（旧桥探测阴性 → 宿主诚实降级）。

## D8 — 测量 fallback 测地化（W8）

**决策**：`MeasureDistanceTool` 构造带 CRS；地理 CRS（经 crs_contract
轴真值）→ `pyproj.Geod` 测地米（标注「测地」）；投影/未知 → 平面地图
单位（标注「平面，地图单位」）。`last_geodesic` 只读状态供宿主标注。

**理由**：V8 遗留的 `math.dist` 平面度数是真实语义缺陷（地理 CRS 下
显示的"距离"是度）。原生路径 `PwbMeasureTool` 已是 QgsDistanceArea 椭球
测算——本决策让 fallback 路径同样诚实，消除两路径的语义级差。
