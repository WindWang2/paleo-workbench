# C++ 转换清单：Python 页面 → 原生 QGIS/Qt 承接（conv-16）

分支 `feat/cpp-conv-16-ui-panel-cluster`（BASE = origin/main `35987e13`）。
本清单覆盖 `paleo_workbench/ui/pages/` **全部 132 个 .py**（约 4.9 万行），逐文件给出：
用户任务、承接策略、C++ 落点、依赖核现状。逐文件阅读笔记见
`docs/development/cpp-conversion-swarm-20/ledgers/16-findings.md`（父代理 132/132）
与 `16-agent-findings.md`（subagent #1：workstation/qgis_stack/顶层/C++/docs，68 节）。

## 策略枚举与统计

| 策略 | 含义 | 文件数 |
|---|---|---|
| **QGS** | 原生 QGIS 组件可承接（QgsMapCanvas/QgsLayerTreeView/QgsMapTool/QgsVectorLayer/QgsAttributeTable 家族） | 13 |
| **QT** | 新 Qt widget（QtWidgets 直译，无科学数值核） | 76 |
| **CORE** | Qt-free 核 + 薄接线（逻辑可对冻结 Python oracle，Qt 只留壳） | 33 |
| **DEFER** | 延后（依赖 M8 viz/geoviz 引擎或未迁移服务层，语义先行不伪造） | 10 |
| **RET** | 退役（被 QGIS 原生面取代后不复刻） | 0 |

主轴结论（M10 落地顺序建议）：
1. **CORE 先行**（33 个）：与 mapping_kernel 同方法论——纯逻辑冻结 oracle、C++ 对账、Qt 只留壳。其中
   `data_view_models/asset_table_model/filter_index/preview_strategy/map_edit_commands/preview_cache`
   是最大且零依赖的 oracle 富矿；`factor_prepare_worker/create_factor_map_dialog/contour_draft_worker`
   直接对接已在 C++ 落地的 `mapping_kernel`（interpolate_factor/contouring/grid_statistics）。
2. **QGS 次之**（13 个）：C++ 侧已有 QgsMapCanvas/QgsLayerTreeView 承载（M1-M5），
   这些文件是行为契约蓝本（§20 CRS 警示不静默、§24 批次渲染、dock 浮动镜像状态机、
   `mapping_page._sync_composition_bindings` 的 statistics→色条绑定）。
3. **QT**（76 个）：面板/表单/表格直译，其中「值卡族」（统计数值 HUD：
   `project_overview_panel/resource_summary/result_summary/completeness_card`）
   与本切片 FactorStatsDock 同构，可批量复用同一 dock/panel 骨架。
4. **DEFER**（10 个）：geoviz 引擎面（M8）与 prediction/interchange 服务层（M9）；
   迁移时只搬已验证的语义纪律（offscreen GL 守卫、worker target 迟到拒绝、凭证打码）。
5. **RET=0**：没有建议直接退役的页面文件；legacy 表面（map_layer_tree/map_canvas_panel）
   按「Qgs 原生就绪后降级为兼容回退」处理，不删除。

## 本切片（第一簇）的落点

只读因子统计 HUD（`FactorStatsDock`）：读 `pwb::mapping::GridStatistics`
（= Python `FactorGrid.statistics`，M7 已冻 oracle），挂 MainWindow dock。
Python 对应面：`inspector.show_factor` 的 grid 行（`f"{min:g} ~ {max:g}"`，
test_inspector_v7 钉死 "10 ~ 220.5"/"0.5 ~ 3.25"）+ `shell._factor_grid_summary`
（isfinite 过滤→min/max/uncertainty）+ `factor_preview_grid` 的 range 卡——
即「统计数值只读展示」这一族面板的第一个 C++ 原生实例。
后续值卡面板可复用同一骨架批量承接。

## 逐文件清单（pages/ 132 文件）

| 文件 | 行数 | 用户任务 | 策略 | C++ 落点 | 依赖核现状 |
|---|---|---|---|---|---|
| `__init__.py` | 62 | 页面名→模块懒加载门面（14 顶级页面注册表） | **QT** | 对应 C++ 侧按需构造页面的注册表概念 | 无 |
| `action_header.py` | 107 | 成图审核页顶幅（4 动作按钮+规则 chips） | **QT** | QFrame+按钮排 | workflow.qc（延后） |
| `activity_card.py` | 113 | 首页最近活动列表（步骤+证据回退） | **QT** | QScrollArea+QVBox | workflow.service STEP_ORDER（延后） |
| `ai_check_advisor_dialog.py` | 112 | 规则一致性诊断 HTML 报告对话框 | **QT** | QTextBrowser+HTML | viz.geomodel.advisor（延后） |
| `asset_context_menu.py` | 254 | 资产右键菜单（stage×managed×能力门禁） | **QT** | 菜单构建规则表驱动+oracle | resources.exporters/tool_availability |
| `asset_table_model.py` | 374 | 资产表模型（语义排序/视图回用/16 列格式化） | **CORE** | 行视图/排序/格式化 Qt-free oracle 富矿 | AssetView |
| `boundary_panel.py` | 105 | 初始岩相边界右栏表单（阈值/平滑/最小面积） | **QT** | QDoubleSpinBox/QComboBox 表单；默认值范围 oracle | 无 |
| `catalog_health_dialog.py` | 283 | 数据健康检查对话框（audit 渲染+协作取消） | **QT** | audit 报告渲染文案 oracle | catalog.audit（C++ 无） |
| `completeness_card.py` | 117 | 数据完整度行卡（就绪/缺失+汇总） | **QT** | 行卡组 | workflow.service readiness（延后） |
| `composite_visualization_panel.py` | 346 | 可视化工作区（7 host tab+联动竖带） | **DEFER** | 分派/status 组装语义 | viz hosts（M8） |
| `composition_panel.py` | 941 | 组图创作面板（session/schema 驱动属性编辑） | **CORE** | session/registry/schema 纯逻辑 | mapping.composer（C++ 无） |
| `contour_draft_worker.py` | 91 | 等值线初稿 worker（窄快照+GUI 有界提交） | **CORE** | 快照契约+提交边界 | mapping_kernel contouring（核已有） |
| `correlation_link_editor.py` | 368 | 相关链接/顶点属性编辑对话框 | **QT** | 表/对话框模式复用 | workflow.correlation_session（延后） |
| `correlation_load_worker.py` | 73 | 多井 LAS 离线程加载 worker | **QT** | QThread worker 模式；失败文案 {cls}: {msg} 逐字 | workflow.stratigraphy_correlation（延后） |
| `create_factor_map_dialog.py` | 242 | 创建单因素图件对话框（参数+图层勾选+worker） | **CORE** | mapping_kernel interpolate_factor 的用户入口 | mapping_kernel（核已有）/services 层延后 |
| `cross_well_export_dialog.py` | 82 | 连井剖面导出选项（格式/DPI/宽度/纸张联动） | **QT** | 选项对话框直译 | 无 |
| `curve_operation_dialog.py` | 257 | 曲线处理工具箱（11 操作参数编辑+诊断） | **QT** | 对话框壳；文案/参数表 oracle | workflow.curve_operations（延后） |
| `data_asset_table.py` | 672 | 资产总表（分页双模/列适配/显式排序） | **QT** | 核心表交互契约；分页接 C++ search_assets_page | PagedAssetModel/catalog 分页（C++ 已有） |
| `data_detail_panel.py` | 434 | 详情卡（元数据+PDF/图片预览+下游影响） | **QT** | QPdfDocument/QPixmap 原生 | preview_strategy（Qt-free） |
| `data_page.py` | 3154 | 数据页主编排（7 worker 链/分页门/导入收据/门禁） | **CORE** | 编排/收据/门禁文案大面 Qt-free oracle；worker target 会话安全 | import/lifecycle 服务（部分延后） |
| `data_reader_panel.py` | 705 | 预览宿主（13 模式分派表+工具条） | **QT** | 模式分派表结构直译 | 各预览控件 |
| `data_table_columns.py` | 65 | 数据表 16 列定义/tooltip/默认列 | **CORE** | 纯数据表→C++ 常量结构；列序/label 逐字 oracle | 无 |
| `data_toolbar.py` | 316 | 数据页工具条（15 动作+标签筛选菜单） | **QT** | 工具条直译；#413 状态真源语义 | 无 |
| `data_view_models.py` | 1054 | 数据视图模型（AssetView/完整性/富化/概览缓存） | **CORE** | 整个文件 Qt-free——C++ 数据页视图模型直接 oracle | catalog DataStage/normalize_tag_name |
| `data_workspace.py` | 270 | 数据页三栏布局骨架（中心栈+右分+浮动） | **QT** | C++ MainWindow dock 页面级对应物 | FloatController |
| `dtw_propagation_worker.py` | 136 | DTW 波段封顶纯函数+传播 worker | **CORE** | bounded_dtw_band（4M cell 预算）完整 oracle | geoviz DTW（M8） |
| `factor_prepare_worker.py` | 88 | 单因素批插值 worker（快照+进度+取消） | **CORE** | worker 壳；C++ interpolate_factor 对接面 | mapping_kernel（核已有）/scheduler 延后 |
| `factor_preview_grid.py` | 189 | 单因素图卡片网格（range/R²/去重诚实标注） | **CORE** | 卡片值规则 Qt-free；statistics 展示族 | FactorMapTask.quality_metrics |
| `factor_task_panel.py` | 221 | 单因素任务左栏（方法 combo 用户选择保护） | **QT** | 任务行列表 | FactorMapTask；HUD 数据上下文 |
| `filter_chips_bar.py` | 249 | 过滤 chips 条（可见过滤态+保存过滤器） | **QT** | QSettings 持久化；chip 维度序列化 oracle | FilterQuery |
| `filter_index.py` | 407 | 过滤索引（FilterQuery 匹配/干草堆/计数） | **CORE** | 纯逻辑索引/过滤/计数完整 oracle | catalog normalize_tag_name |
| `geo3d_workspace.py` | 905 | 3D 工作区控制器（测量状态机/剖切/持久化降级） | **DEFER** | 测量状态机/降级语义 Qt-free | viz.geomodel（M8） |
| `geological_modeling_3d_page.py` | 3989 | 井震联合 3D 工作台（切片卡/分析 tab/拾取/会话持久化） | **DEFER** | demo 诚实标注/会话持久化/offscreen 守卫是 C++ 必抄纪律 | geoviz 联合引擎（M8） |
| `geological_modeling_workers.py` | 405 | 3D 建模 4 worker（合成 demo/地层切片/导出/顾问） | **DEFER** | demo 合成器 Qt-free 可 oracle | geoviz 3D（M8） |
| `geotiff_preview_widget.py` | 78 | GeoTIFF 缩略图+元数据表 | **QT** | QLabel+QPixmap+TablePreviewWidget | 无 |
| `geoviz_preview_provider.py` | 127 | 本地可视化 provider（引擎错误分类） | **CORE** | 错误分类/警告合并纯逻辑 | geoviz 引擎（延后） |
| `governance_dialog.py` | 137 | 治理元数据编辑对话框（受控词表） | **QT** | QFormLayout 对话框 | catalog.governance（C++ 无） |
| `home_page.py` | 387 | 首页（工区地图为心+卡片群） | **QGS** | QgsMapCanvas 只读嵌入（C++ M4 已做） | workarea_map_snapshot |
| `hub_page.py` | 115 | UI-v2 hub 容器（pill 切换+QStackedWidget） | **QT** | 容器语义直译 | 无 |
| `image_preview_widget.py` | 334 | 图片预览（有界解码+视口窗口化缩放平移） | **QT** | 原生图形项；窗口化绘制契约 | 无 |
| `impact_preview_dialog.py` | 190 | 破坏性操作影响预览（markdown 渲染+fail-closed） | **CORE** | render_markdown 纯函数 oracle | catalog.impact（C++ lineage 已有近亲） |
| `ingest_plan_dialog.py` | 598 | 规划导入对话框（两阶段确认+分块执行） | **QT** | 对话框壳；决策/摘要文案 oracle | resources.ingest_plan（纯服务） |
| `inspector_panel.py` | 1026 | 资产检查器 6 tab（概要/元数据/标签/版本/血缘/完整性） | **QT** | 6 tab 检查器；文案/门禁 oracle | catalog.entity_views（延后） |
| `integrity_worker.py` | 195 | 完整性校验 worker（sha256+catalog 桥） | **CORE** | sha256/状态机 Qt-free | CatalogRepository 完整性（M4 域） |
| `interchange_models.py` | 178 | 交互交换 3 个 Qt 表模型（预检/批量/打包） | **CORE** | 薄 Qt 壳；状态中文化词表 oracle | interchange 线（conv-14 域） |
| `json_tree_preview_widget.py` | 180 | JSON 懒树（折叠阈值/批次/深度帽） | **QT** | QStandardItemModel 懒树 #531 | 无 |
| `lazy_visualization_tabs.py` | 171 | 懒加载可视化双 tab（no-steal 契约） | **QT** | QTabWidget 状态机 | GeoVizPreviewHost（延后） |
| `lineage_explorer_dialog.py` | 708 | 血缘懒树浏览器（单跳展开/断链/循环/上限） | **QT** | 依赖 catalog lineage（C++ M4 已有读模型） | catalog.models |
| `lithology_crossplot_dialog.py` | 94 | 岩相交会统计对话框（HTML 表） | **DEFER** | HTML 文案 oracle | geoviz 分析（M8） |
| `map_attribute_table.py` | 461 | 要素属性格（有界选择器/差量/geometry 摘要） | **QGS** | QgsAttributeTable 原生对应；置顶窗口/差量语义自研 | 无 |
| `map_canvas_panel.py` | 97 | 编图画布宿主（空态/原生场景切换） | **QGS** | 已被 unified canvas 取代（legacy 兼容） | 无 |
| `map_chrome_panel.py` | 105 | 图面要素右栏（标题/图例/指北针勾选） | **QT** | QLineEdit+QCheckBox 表单 | 无 |
| `map_dock_manager.py` | 400 | 编图 dock 栏+面板菜单+浮动镜像状态机 | **QGS** | QgsDockWidget/QgsPanelWidgetStack 可承接大部分 | FloatController |
| `map_document_panel.py` | 132 | 古地理图文档左栏摘要+列表 | **QT** | QListWidget+键差分 | viz.mapping_helpers（延后） |
| `map_edit_commands.py` | 278 | 撤销/重做命令栈（8 命令+深度帽溢出语义） | **CORE** | Qt-free 纯命令栈完整 oracle（#894-3） | 无 |
| `map_edit_draft.py` | 117 | 线/相带草稿点管理+闭合规则 | **CORE** | 去重 1e-9/闭合/最少点数 Qt-free | mapping.geometry_schema |
| `map_edit_factory.py` | 115 | 要素 record→图形 item 构造规则 | **CORE** | Qt-free 构造规则可对账 | mapping.geometry_schema（C++ 无） |
| `map_edit_items.py` | 447 | 编图要素图形项 4 类+顶点手柄 | **QGS** | QgsVectorLayer 原生编辑承接目标 | mapping.geometry_schema |
| `map_edit_scene.py` | 1309 | 编图编辑场景（6 工具/命令栈/拓扑门禁/LOD） | **QGS** | 命令栈/容差/拓扑门禁 Qt-free 可 oracle；QgsMapTool 原生承接目标 | geoviz 几何 api（部分延后） |
| `map_edit_snap.py` | 99 | 捕捉管理（候选收集/缓存/参考点） | **CORE** | 候选收集规则纯逻辑 oracle | geoviz snap |
| `map_edit_toolbar.py` | 188 | 编图工具条（6 工具互斥+9 信号） | **QT** | QGIS QgsMapTool 承接语义；按钮条保留 | 无 |
| `map_edit_topology.py` | 192 | 拓扑计划（环校验/邻接/合并/分割 plan_*） | **CORE** | 计划+命令纯逻辑；polygonization C++ 已有部分 | geoviz api（延后部分） |
| `map_edit_view.py` | 165 | 编图视图（导航 LOD/共享视口状态） | **QGS** | QgsMapCanvas 承载后仅 fallback；视口状态协议保留 | 无 |
| `map_factor_shelf.py` | 102 | 单因素动作架（4 按钮+卡片网格） | **QT** | 动作架；与 HUD 同族面板 | FactorMapTask |
| `map_layer_tree.py` | 332 | 编图图层树（legacy；4 图层+参考组） | **QGS** | QgsLayerTreeView 原生对应（layer_tree_panel 已做） | 无 |
| `map_reference_panel.py` | 123 | 参考图层右栏（勾选/透明度/状态摘要） | **QGS** | QGIS 原生图层树承接；状态摘要文案可 oracle | ReferenceLayerService（延后） |
| `map_topology_issue_panel.py` | 142 | 拓扑问题表（3 列+空态+定位） | **QT** | QTableView+ObjectTableModel | geoviz validate（延后） |
| `map_workbench_bottom.py` | 34 | 编图底部三 tab（属性/拓扑/单因素） | **QT** | QTabWidget 容器 | 子面板各自行裁定 |
| `mapping_page.py` | 2599 | GIS 壳编图页（命令条/dock 栏/统一画布/属性表差量） | **QGS** | statistics→组图色条绑定的 Python 承接点（:893-926）；C++ 综合编修蓝本 | map_action_controller（C++ 有近亲 ToolActionSet） |
| `media_preview_widget.py` | 412 | 音视频播放（QtMultimedia 懒加载） | **QT** | QMediaPlayer 直译；懒初始化契约 | QtMultimedia |
| `message_preview_widget.py` | 14 | 居中消息占位 QLabel | **QT** | QLabel 直译 | 无 |
| `module_relationship.py` | 764 | 模块关系导览画布（自绘箭头/图例） | **QT** | 自绘导览（无数值核）；页面映射表 oracle | 无 |
| `navigation_tree.py` | 898 | 数据导航树（IA 3.0 域分组/分页实体/计数） | **CORE** | 树结构/计数/过滤语义大部 Qt-free | FilterQuery+CatalogCounts |
| `new_project_wizard.py` | 502 | 新建工程两步向导（校验链+分析预览） | **QT** | M2 C++ newProject 已有后端核 | project.onboarding（延后） |
| `onboarding_report_card.py` | 171 | 数据盘点报告卡（导入统计+范围） | **QT** | QLabel 组；格式化文案 oracle | project.onboarding（延后） |
| `paged_asset_model.py` | 704 | SQL 分页资产模型（稀疏页/稳定键/后台取页） | **CORE** | 页模型语义接 C++ search_assets_page（已有） | catalog 分页 |
| `pdf_preview_widget.py` | 620 | PDF 预览（QPdfView 主路+降级连续渲染） | **QT** | QPdfView 原生；降级/状态机语义 | QtPdf |
| `prediction_evidence_panel.py` | 262 | 预测证据右栏（诚实 nature/source 标注） | **QT** | 诚实标注规则表 oracle | 预测结果模型（延后） |
| `prediction_task_panel.py` | 15 | 测井预测任务左栏列表 | **QT** | TaskPanelBase 派生 | 任务词表 state_language（延后） |
| `preparation_page.py` | 377 | 制备页编排（generation 门/诚实汇总） | **CORE** | 插值批处理编排对接 C++ interpolate_factor | mapping_kernel（核已有）/scheduler 延后 |
| `preview_cache.py` | 114 | 预览 LRU（键构造/字节预算淘汰） | **CORE** | 纯逻辑完整 oracle 面（容量/淘汰/重复 put） | project.models |
| `preview_disk_cache.py` | 247 | 预览盘缓存（键指纹/原子写/损坏删） | **CORE** | 缓存键/原子写纯逻辑 oracle | geoviz 编解码（延后） |
| `preview_provider.py` | 119 | 预览构建门面（空资产/不支持文案） | **CORE** | 纯构建层 registry | resources.preview_parsers（Qt-free） |
| `preview_settings.py` | 59 | 预览偏好 QSettings 存取（load/save/reset） | **QT** | QSettings 直译；PreviewSettings 校验 Qt-free | resources.preview_settings（Qt-free 可对账） |
| `preview_settings_panel.py` | 276 | 预览设置 8 分类页 | **QT** | 设置面板 | PreviewSettings（Qt-free） |
| `preview_strategy.py` | 189 | V1 预览策略分派（格式集+截断+文案） | **CORE** | 纯函数全分支 oracle（格式分派+文案逐字） | 无 |
| `preview_widgets.py` | 62 | 11 个预览控件门面+懒加载媒体类 | **QT** | 头文件聚合；懒加载契约保留 | 子控件各自行裁定 |
| `preview_worker.py` | 523 | 预览请求编排（代际/epoch/pending 泵） | **CORE** | 请求编排状态机部分 Qt-free oracle | 无 |
| `project_overview_panel.py` | 189 | 工区概览 8 统计块+提示（counts 未就绪显 —） | **QT** | 统计条（值卡族） | project.domain/CatalogCounts |
| `project_well_map_page.py` | 820 | 工程井位地图（批次散点/§20 CRS 警示/§24 性能契约） | **QGS** | QgsMapCanvas+QgsVectorLayer 承接 | geoviz scatter（fallback 延后） |
| `qc_helpers.py` | 26 | QC 规则→(级别,文案,颜色) 纯函数 | **CORE** | Qt-free 可 oracle（error>warning 优先） | tokens 色表 |
| `qc_issue_table.py` | 77 | 质检问题 4 列表（按规则行+定位列） | **QT** | QTableWidget | workflow.qc（延后） |
| `relink_dialog.py` | 430 | 缺失源重链接对话框（fail-closed 身份证明） | **QT** | 对话框壳；摘要文案 oracle | catalog.sources（C++ 无） |
| `resource_summary.py` | 80 | 资源类型单行计数条（就绪/缺少状态） | **QT** | 水平 QLabel 条 | workflow.service readiness（延后） |
| `resource_table.py` | 147 | 工程资源 5 列小表（状态着色） | **QT** | QTableView+模型 | 无 |
| `result_summary.py` | 161 | QC 结果右栏（通过/警告/待处理计数） | **QT** | 纯展示+计数规则 | qc_helpers+QualityReport |
| `review_export_page.py` | 298 | 成图审核页（QC 运行/导出/专家定稿） | **QT** | 页面组装 | workflow.qc/versioning（延后） |
| `rich_text_preview_widget.py` | 35 | 只读 Markdown/HTML 渲染（断网沙箱） | **QT** | QTextBrowser+loadResource 白名单 | 无 |
| `seismic_attribute_panel.py` | 107 | 地震属性分组树（未实现组置灰） | **QT** | QTreeWidget | seismic_attributes.available_kernels（C++ 已有） |
| `seismic_context_toolbar.py` | 269 | 地震上下文工具条（属性平铺+弹出卡） | **QT** | 与属性面板同词表两壳 | seismic_attributes |
| `seismic_control_panel.py` | 125 | 地震预测控制右栏（诚实输出标注） | **QT** | 值卡+combo+按钮 | 预测结果模型（延后） |
| `seismic_prediction_page.py` | 594 | 地震预测页编排（模型解析/输入契约/会话安全） | **CORE** | 推断编排语义+布局 | prediction 服务层（延后） |
| `seismic_slice_preview_widget.py` | 234 | 地震切片预览（方向/slider/蓝白红色表） | **QT** | 复用 C++ seismic_viewer 切片渲染 | libs/seismic_viewer（已有） |
| `seismic_task_panel.py` | 15 | 地震预测任务左栏列表 | **QT** | TaskPanelBase 派生 | 同上 |
| `seismic_view_panel.py` | 1209 | 地震视图面板（profile 模式/游标门控/解释生命周期） | **DEFER** | 游标门控/解释生命周期/诚实 fail-closed 语义 | geoviz SeismicView（M8） |
| `sequence_boundary_table.py` | 70 | 层序界面 3 列清单表（双击设目标） | **QT** | QTableWidget | 层序模型（延后） |
| `sequence_framework_page.py` | 214 | 层序格架页（三栏+浮动面板框架） | **QT** | 页面组装+dock 浮动框架 | workflow.stratigraphy（延后） |
| `sequence_helpers.py` | 9 | dict/attr 双形态字段读取 helper | **CORE** | 一行工具，C++ QVariantMap/结构体双态 helper | 无 |
| `sequence_scheme_summary.py` | 68 | 层序方案右栏摘要卡 | **QT** | QLabel 值卡组 | 层序模型（延后） |
| `sequence_target_panel.py` | 162 | 层序目标层位左栏（提交语义 combo） | **QT** | QComboBox editable；keystroke 不写工程 | 层序模型（延后） |
| `start_guide_card.py` | 61 | 首页开始卡（新建/打开/样例三按钮） | **QT** | QFrame+QPushButton+Signal | style.bind 主题机制 |
| `stratigraphy_correlation_page.py` | 1524 | 地层对比页（连井加载/DTW 编排/解释版本生命周期） | **DEFER** | 加载/版本生命周期/DTW 编排语义 | geoviz CrossWell（M8） |
| `summary_table_preview_widget.py` | 186 | LAS 摘要双 tab+统计 chips | **QT** | 表+chip 条 | 无 |
| `table_preview_widget.py` | 400 | 虚拟化表格预览（深度列/复制/截断） | **QT** | 虚拟模型直译；格式化规则 oracle | 无 |
| `tag_widgets.py` | 712 | 标签 UI 组件群+标签治理对话框 | **CORE** | parse_multi_tag_input 纯函数 oracle；治理文案 | catalog tag 服务 |
| `task_panel_base.py` | 185 | 任务面板基类（词表徽章+键差分列表） | **QT** | QFrame 基类 | state_language（延后） |
| `text_preview_widget.py` | 30 | 只读文本预览（mono/换行设置） | **QT** | QPlainTextEdit | 无 |
| `version_workbench_dialog.py` | 681 | 版本工作台（时间线+详情+生命周期门控） | **QT** | 依赖 catalog.service（C++ CatalogRepository 对应） | catalog.models |
| `visualization_page.py` | 751 | 可视化页（资产签名门控/导出能力门控） | **DEFER** | 分派/导出/签名缓存语义 | viz（M8） |
| `visualization_summary_panel.py` | 151 | 可视化总览计数+可打开资产列表 | **QT** | 键差分清单 | VizAdapter（延后） |
| `visualization_trace_panel.py` | 125 | 可视化追踪右栏+导出能力门控 | **QT** | 值卡+capability gating | viz（延后） |
| `web_document_preview_widget.py` | 82 | 本地文档 WebEngine 预览（scheme 白名单沙箱） | **QT** | 沙箱语义必须保留 | QtWebEngine |
| `well_detail_panel.py` | 229 | 井数据视图（角色槽表+三卡） | **QT** | 只读渲染无自有状态 | catalog.entity_views（C++ 无） |
| `well_log_canvas_panel.py` | 916 | 测井画布双后端（深度单位 fail-closed/游标门控） | **DEFER** | V6 §3 深度单位契约/游标门控 Qt-free oracle | welllog 引擎（M8） |
| `well_log_load_worker.py` | 92 | 单井 LAS/XML worker（cancelling 诚实语义） | **QT** | worker 语义直接移植 C++ | viz.adapter（延后） |
| `well_log_prediction_page.py` | 928 | 测井预测页（凭证打码/线上超时/会话安全） | **CORE** | redaction/超时/会话安全 Qt-free oracle | prediction 服务层（延后） |
| `well_log_track_settings.py` | 194 | 井道显示设置（拖拽合并/上限 3） | **QT** | QTreeWidget 拖拽合并 | viz.well_log_track_layout（纯模型可 C++） |
| `well_map_panel.py` | 113 | 数据页折叠井位地图（内嵌工区图页） | **QGS** | 折叠头+地图容器 | qgis_stack display_canvas（桥=QgsMapCanvas） |
| `well_seismic_joint_page.py` | 261 | 井震联合薄壳（域回滚/选择保持） | **DEFER** | 壳层语义可抄；3D 引擎 M8 | geoviz 联合引擎 |
| `well_table_panel.py` | 198 | 井点表 11 列（QC 着色+_fmt 数字格式） | **QT** | QTableView；_fmt 纯函数 oracle | WellTable 模型 |
| `workarea_map_widget.py` | 191 | 整幅工区地图（域签名缓存+井拾取 16px） | **QGS** | QgsMapCanvas 只读嵌入（qgis_stack 桥） | mapping.workarea_map_snapshot |
| `workflow_contract_panel.py` | 198 | 工作流合同面板（就绪状态+开放问题） | **QT** | 文案渲染面大 | workflow.contracts（延后） |

## workstation/、qgis_stack/、ui 顶层与 C++ 现状（摘要）

* `ui/workstation/`（30 文件 22.6k 行）：综合工作站（shell/composite_document/composite_editing/
  stage_actions 等）。dock 契约蓝本 `_add_dock`（shell.py:356-388）与
  `dock_framework`/`test_dock_framework_v9`（14 dock id、GL dock 不可浮、preset 只切可见性、
  grow-only、检查器 1100/1200 滞回）是 C++ MainWindow dock 系统的直译 oracle——**C++ 缺口 =
  saveState/restoreState/预设/grow-only/responsive**（详见 16-agent-findings.md）。
* `ui/qgis_stack/`（8 文件 3.3k 行）：QGIS 桥（canvas_shim/layer_tree_panel/display_canvas）；
  无桥 fallback=`UnifiedMapCanvas`。C++ 侧无需 Shiboken 桥（直接链接 QGIS），此目录是行为契约。
* `ui/` 顶层（app_shell/dock_framework/dock_manager/navigation/command_registry）：
  布局持久化与动作注册；C++ `ToolActionSet.apply` 已是同构纯投影（golden 28×77 全等）。
* C++ 现状：`apps/paleo_workbench_platform/main_window.cpp` 已有 3 dock
  （图层左 / 测井右 / 地震右，buildUi 内）；`libs/ui` 仅 `tool_actions`。
  本切片按 v3-handoff §1.4 指引追加第一簇 dock（CONV-16 守卫，`factor-stats-dock`）。
