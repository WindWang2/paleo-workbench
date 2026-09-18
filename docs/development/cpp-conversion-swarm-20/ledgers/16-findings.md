# 16 — Findings：UI 面板承接（逐文件原文阅读笔记）

来源约束：本文所有结论均来自本 worktree 中对 §5 清单文件的**全文阅读**（非 grep 摘要）；
subagent #1 独立全文阅读的 workstation/qgis_stack/顶层/C++/docs 笔记在 16-agent-findings.md（68 节，含 file:line 引用）。
路径适配：任务书 /home/kevin/projects/paleo_project/main 本机不存在；实际仓库 /home/kevin/project/paleo-workbench，
worktree /home/kevin/project/worktrees/cpp-conv-16-ui-panel-cluster（BASE = 35987e13）。
覆盖：paleo_workbench/ui/pages/ 全部 133 个 .py（父代理逐文件）；承接策略枚举【Qgs】原生 QGIS 可承接 /【Qt】新 Qt widget /【核+薄】Qt-free 核+薄接线 /【延后】/【退役】。

# 16 — Findings（父代理逐文件精读笔记）第 1 批：pages 001-038

方法：全文 Read（非 grep 摘要）；file:line 为 worktree 相对路径。承接策略枚举：
【Qgs】原生 QGIS 组件可承接 /【Qt】新 Qt widget /【核+薄】Qt-free 核+薄接线 /【延后】/【退役】。

## paleo_workbench/ui/pages/__init__.py（62 行）
- 公开符号：`__all__` 14 个页面名（DataAssetTable/DataDetailPanel/DataPage/DataToolbar/DataWorkspace/HomePage/MappingPage/PreparationPage/ReviewExportPage/SequenceFrameworkPage/SeismicPredictionPage/StratigraphyCorrelationPage/VisualizationPage/WellLogPredictionPage）、`_EXPORTS` 懒加载表、`__getattr__`（子模块 fall-through，:40-58 修过 pytest dotted setattr 级联）。
- 用户任务：页面命名空间门面（lazy import）。
- 承接：【延后】纯 import 机制，C++ 侧对应「按需构造页面」的注册表概念；inventory 的 14 个顶级页面即清单主轴。
- 边界：未知属性 AttributeError 文案 `module {__name__!r} has no attribute {name!r}`。

## sequence_helpers.py（9 行）
- `field_value(source, name, default="")`：dict→get / 对象→getattr。dict 与 attr 双形态统一读取。
- 承接：【核+薄】一行工具；C++ 侧等价 helper（QVariantMap/struct 双态）或直接避免。

## message_preview_widget.py（14 行）
- `MessagePreviewWidget(QLabel)`：居中+wordwrap；`set_message(text)`。
- 承接：【Qt】QLabel 直接对应。

## prediction_task_panel.py（15 行）
- `PredictionTaskPanel(TaskPanelBase)`：objectName=PredictionTaskPanel、title=测井预测任务、show_review_count=True。
- 承接：【Qt】依赖 task_panel_base。

## seismic_task_panel.py（15 行）
- `SeismicTaskPanel(TaskPanelBase)`：title=地震预测任务、show_review_count=False。
- 承接：【Qt】同上。

## qc_helpers.py（26 行）
- `derive_rule_result(rule, issues) -> (severity, text, color_hex)`：无匹配→("pass","✓通过",SUCCESS)；多匹配 error>warning（:16-22 顺序扫描遇 error 即 break）；text=`f"{label} {message}"` 取第一条 message；颜色 QC_RESULT_COLORS[severity]。
- 承接：【核+薄】纯函数可 Qt-free 化（tokens 色值入 Qt-free 常量表）；oracle 候选：无匹配/仅 warning/error+warning 混合/message 缺省空串。
- 边界：空 message → 尾随空格被 rstrip。

## text_preview_widget.py（30 行）
- `TextPreviewWidget(QTextEdit)`：只读、NoWrap 默认、mono 字体 token；`load_text`、`apply_settings(settings)`（font_size、wrap_text→WidgetWidth/NoWrap）。
- 承接：【Qt】QPlainTextEdit/QTextEdit 原生承接。

## map_workbench_bottom.py（34 行）
- `MapWorkbenchBottom(QTabWidget)`：三 tab=MapAttributeTable「属性」/MapTopologyIssuePanel「拓扑问题」/MapFactorShelf「单因素参考图」（各带 tinted 图标）；`set_feature(dict|None)` 转发；`set_collapsed(bool)`=setVisible。
- 承接：【Qt】QTabWidget 直接；图标 tinted_map_icon 需 C++ 主题图标工厂。

## rich_text_preview_widget.py（35 行）
- `RichTextPreviewWidget(QTextBrowser)`：禁外链、只读；`loadResource` 重载：scheme∉{"",file}→None（断网沙箱，:18-22）；`load_html`、`apply_settings`（字号/换行）。
- 承接：【Qt】QTextBrowser 原生；沙箱语义需保留（网络资源阻断）。

## preview_settings.py（59 行）
- `PreviewSettingsStore`：ORGANIZATION=PaleoWorkbench/APPLICATION=paleo-workbench/GROUP=preview/settings；load（逐字段 QSettings.value 带默认值，失败→defaults）/save（to_mapping 逐键 setValue+sync）/reset（remove+defaults）。依赖 resources.preview_settings 的 PreviewSettings（_BOOLEAN_FIELDS/_INTEGER_RANGES 校验）。
- 承接：【Qt】QSettings 原生对应；校验规则 Qt-free 可对账。
- 边界：load 时 from_mapping 抛 TypeError/ValueError → 回落 defaults（:42-45）。

## start_guide_card.py（61 行）
- `StartGuideCard(QFrame)`：objectName=PanelCard；title/subtitle + 三按钮（新建=PrimaryButton/打开/打开样例=SecondaryButton）→ 三个 Signal；QSS 经 style.bind（E1 主题切换重渲染）。
- 承接：【Qt】首页卡；buttons+signals 直译。

## preview_widgets.py（62 行）
- 门面 re-export 11 个 preview 控件 + `_LocalOnlyPage`/`_LocalOnlyRequestInterceptor`；`__getattr__` 懒导出 QMediaPlayer/QAudioOutput/QVideoWidget（#951 不在 import 时初始化 media 后端，:49-62）。
- 承接：【延后】门面本身无逻辑；C++ 用头文件聚合即可。

## data_table_columns.py（65 行）
- `ColumnDefinition(key,label,required)`；`COLUMN_DEFINITIONS` 16 列（name 必需；label 中文）；`COLUMN_BY_KEY`、`COLUMN_TOOLTIPS`（16 条中文）、`DEFAULT_COLUMN_KEYS` 8 列（F5 默认视图）、`HEADERS`。
- 承接：【核+薄】纯数据表 → C++ 常量结构；oracle 候选：列序/label 逐字。

## sequence_scheme_summary.py（68 行）
- `SequenceSchemeSummary(QFrame)`：右栏（min220/max352 宽）；字段值卡 当前方案/层序界面 N 个/体系域 LST / TST / HST/绑定状态；`update_state(stratigraphy)`：scheme 空回 LST/TST/HST、boundaries 数量、target 空→"未设置目标层位" 否则 "目标 {t}"；`set_bind_status`；`save_requested` Signal。
- 承接：【Qt】QLabel 栏；update_state 的回退文案值得 oracle。

## sequence_boundary_table.py（70 行）
- `SequenceBoundaryTable(QFrame)`：3 列表（界面/目标层位/说明）；`boundary_activated(str)` 双击发射（text strip 后）；`update_state`：boundaries 列表行数、说明列 "当前目标"/"第 N 层序界面"；空态 label 显隐。
- 承接：【Qt】QTableWidget。

## correlation_load_worker.py（73 行）
- `CorrelationLoadWorker(QObject)`：信号 finished(object)/failed(str)/cancelled()；run 前/后查 _cancel_event；失败文案 `f"{exc.__class__.__name__}: {exc}"`（:68）；默认 loader=workflow.stratigraphy_correlation.load_correlation_wells，max_wells=8。
- 承接：【Qt】QThread worker 模式；失败文案逐字是 oracle 面。

## qc_issue_table.py（77 行）
- `QCIssueTable(QWidget)`：4 列（检查项目/检查说明/结果说明/定位，宽 160/0stretch/160/100）；`update_state(reports)`：取 reports[0]，spatial_issues 按 rule 分桶（:38-46）；行=report.rules 顺序；description=tokens.RULE_DESCRIPTIONS.get(rule, rule)；结果列染色；定位=首条 spatial 的 feature_id|ref|"可定位"，多条→`f"{loc} (+{n-1})"`；行高 28；`spatial_issues_for_rule(rule)`。
- 承接：【Qt】QTableWidget；依赖 workflow.qc.spatial_issues（QC 核未在 C++）。
- 边界：无 reports→空表；loc 全缺失→"—"。

## geotiff_preview_widget.py（78 行）
- `GeoTiffPreviewWidget(QWidget)`：缩略图 QLabel(min160) + TablePreviewWidget 元数据表（headers=("属性","值")）；`apply_settings`（show_geo_metadata 显隐/smooth_images→Smooth/Fast Transformation+重渲染）；`load(path,revision,image_bytes,geo_metadata)`（path/revision del）；`pixmap()`；null→"缩略图不可用"；resizeEvent 重渲染（KeepAspectRatio，min 240x160）。
- 承接：【Qt】QLabel+QPixmap+QTableWidget。

## resource_summary.py（80 行）
- `ResourceSummaryBar(QFrame)`：单行条（UI v2 压缩）；每 REQUIRED_RESOURCE_TYPES 一组 名称+`f"{count}{unit}"`；`update_state(state)` 读 resource_readiness{available_counts,missing_types,ready}；ready→"数据完整" 否则 "缺少: A、B"；状态色 SUCCESS/ERROR_RED 经 style.bind registry（R1 P2-8 防重复 bind 累积）。
- 承接：【Qt】水平 QLabel 条；readiness 数据来自 workflow.service（Python 服务层，C++ 对应 platform 侧工程状态）。

## map_chrome_panel.py（105 行）
- `MapChromePanel(QFrame)`：图名值/已启用值 + QLineEdit 标题 + 4 QCheckBox（图例/指北针/比例尺/标题栏，DEFAULT_CHROME_ELEMENTS，默认全选）+ 保存草稿/发送审核按钮；`update_state(document)`：chrome.title 空回 document.name 回 "未设置"；`chrome_changed(dict{title:strip,elements})`（editingFinished/toggled 发射，update_state 用 blockSignals 防回环 :94-101）。
- 承接：【Qt】表单面板。

## action_header.py（107 行）
- `ActionHeader(QFrame)`：成图审核页顶幅；标题 `成图与审核 · {horizon} 古地理图（自动质检 + 人工审核）`；4 按钮（运行检查/规则配置/导出检查报告/专家定稿）各带 tooltip；rules_label `检查规则: a · b`（report.rules 或 tokens.DEFAULT_QC_RULES）；`update_state(reports, map_documents)`：horizon 解析（reports[0].linked_map_document_id 匹配 doc.id→linked_target_horizon 回 "—"）；finalize/run/export 按钮 enabled 逻辑（:97-107）。
- 承接：【Qt】按钮幅。

## seismic_attribute_panel.py（107 行）
- `SeismicAttributePanel(QFrame)`：`_COMPUTABLE_LABELS` 11 kernel→中文 label；`_ATTRIBUTE_GROUPS` 5 组（末组「未实现」3 项置灰）；`_LABEL_TO_KERNEL`；`attribute_changed(str)`（叶子且 enabled 才发射）；`set_selected_attribute`（不发信号同步视觉）；`selected_attribute()` 默认回 "振幅"（:103-107 注意：返回的是字面量"振幅"而非选中 label——历史语义）；available_kernels() 来自 seismic_attributes（C++ 侧 seismic_attributes 库已存在）。
- 承接：【Qgs/Qt】QTreeWidget；与 C++ seismic_attributes 对接是已具备依赖。
- 边界：置灰项不可点；label→kernel 映射失败→disabled。

## ai_check_advisor_dialog.py（112 行）
- `AICheckAdvisorDialog(PwbDialog)`：非模态（setModal(False)）550x650；HTML 报告（bh_badge 有 error→不通过(FAIL) 红底 否则 警告(WARNING) 黄底；fault_badge 有 issues→有冲突 否则 通过(PASS)）；钻孔/断层 issues 列表（✕ 错误/⚠️ 警告 徽标、空态文案 ✅ 两条）；建议区=issues 派生（不再硬编码井名），空→固定文案。
- 承接：【Qt】QTextBrowser+HTML；文案逐字 oracle 候选。

## activity_card.py（113 行）
- `RecentActivityCard(QFrame)`：最近活动滚动列表；`update_state(state, steps)`：非 pending steps→`{STEP_LABELS[i]}: {STATUS_TEXT[st]}`（STEP_TYPES.index 失败回 0）；count==0 回落证据行（resource_counts 求和/factor_map_count/... 仅>0 追加）；`entry_count()`；空态 "暂无活动"。
- 承接：【Qt】QScrollArea+QVBox；STEP_ORDER 来自 workflow.service。

## well_map_panel.py（113 行）
- `WellMapPanel(QFrame)`：数据页折叠井位地图（header QToolButton checkable+count_label+内嵌 ProjectWellMapPage）；`set_collapsed/is_collapsed/set_header_visible/add_header_button/expand_and_focus(well_id)`；`refresh_domain(project)`：异常吞掉（:101-104）；计数 `f"{workarea} 口测区井 · {ref} 口参考井"` 或 `f"{n} 口井"`（:105-113）。
- 承接：【Qt】折叠容器。

## preview_cache.py（114 行）
- `preview_result_weight(value)`：estimated_bytes 或 utf-8 文本+image+pdf 字节和；`make_preview_cache_key(asset, settings_fp, comparison_crs)`：artifact→(artifact,id,path,format,"",stat,fp)；resource→9 元组含 checksum/crs/units/comparison_crs/stat；`PreviewCache(max_size=32, max_bytes=128MiB)`：LRU OrderedDict、构造参数 int 校验（TypeError 文案 `f"{name} must be an integer"`、ValueError `must be positive`）、put 超 max_bytes 单条拒收、超限 popitem(last=False)。
- 承接：【核+薄】纯逻辑（无 Qt）→ C++ LRU 可 oracle（容量/字节淘汰/重复 put 扣旧权）。

## hub_page.py（115 行）
- `HubPage(QWidget)`：UI-v2 Ribbon hub 容器：pill switcher 行+QStackedWidget；`add_submodule(key,title,page)`、`finish()`（补 stretch）、`switch_to(key,emit)`（未知 key no-op；调 page.activate_page()；page_activated/submodule_changed 信号；单子模块隐藏 switcher）、`current_key/current_page/page/activate_page`。
- 承接：【Qt】容器语义 C++ 直译。

## map_edit_factory.py（115 行）
- `item_from_record(record)`：kind 分派 facies/well/line/label，无 id→None；`make_facies`：canonical_facies_geometry；外环 len<4 或任一 ring<4→None；extras 收 facies/probability/region_id/properties；`make_well`：coordinate_status_is_flagged→跳过（#1162 不画伪造位置）；coords<2 或 float 转换失败→None；`make_line`：每点须 2 数否则整体 None；`make_label`：text=name 回退链。
- 承接：【核+薄】record→item 构造规则 Qt-free 可对账（依赖 mapping.geometry_schema.canonical_facies_geometry）。

## completeness_card.py（117 行）
- `DataCompletenessCard(QFrame)`：每资源类型行 名称/`{count}{unit}`/已就绪|缺失（>0 才就绪）+ 汇总行（ready→数据完整 / 缺少: …）；数据驱动色经 status_row dict+style.bind 重注册（:48-63、107-117）。
- 承接：【Qt】行卡；文案与 resource_summary 同源（readiness dict）。

# 16 — Findings 第 2 批：pages 039-058

## map_edit_draft.py（117 行）
- `MapDraftManager(scene)`：polyline/facies 草稿点+QGraphicsPathItem 预览（Z=50，cosmetic DashLine ACCENT）；`append_point`（与上点距 <1e-9 去重，:43-45）；`update_preview`（facies 预览闭合需 len≥2）；`cancel`；`finish_line(create_fn)`：kind 非 line→None、点<2→None、record{id:new_feature_id("line"),name:""}；`finish_facies(create_fn,refresh_fn)`：点<3→None、首尾不闭则补闭合点、name="新相带"、成功后调 refresh_topology_fn。
- 承接：【Qgs】几何草稿在原生 QgsMapTool/简 Qt 场景中承接；去重/闭合/最少点数规则可 Qt-free 对账。

## preview_provider.py（119 行）
- `PreviewProvider`：`preview(None)`→PreviewResult(mode=empty,title=请选择数据项,message=从列表中选择一个数据、成果或文件)（:70-76）；`_build_preview`→resources.preview_parsers.registry.default_registry()；`preview_summary`=preview；`preview_visualization`：ResourceItem→(name,path,format,status,type) else 成果/status=generated；固定 message="此数据不支持可视化预览"；`with_settings` 浅拷贝。
- 承接：【核+薄】provider 是纯构建层（线程安全、无 Qt）→ C++ Qt-free preview 管线+registry；空资产文案为 oracle 面。

## map_reference_panel.py（123 行）
- `MapReferencePanel(QFrame)`：参考图 QListWidget（勾选=可见）+透明度 slider 0-100；`set_layers` 键差分（reconcile_widget_items，V11 D2 ⑮）+首层选中+slider 置 round(op*100)；`_layer_label`：offline→"(离线)"、failed→"(失败)"、external→"[外部]"；`_status_summary`："坐标已对齐"+"N 层离线/N 层失败/N 外部" join " · "；_suppress 防回环；信号 visibility(id,bool)/opacity(id,float=值/100)。
- 承接：【Qt】QListWidget+QSlider；_status_summary 文案可 oracle。

## seismic_control_panel.py（125 行）
- `SeismicControlPanel(QFrame)`：SEISMIC_DISPLAY_MODES=("vd","wiggle")；值卡 分析状态(待开始)/体数据维度(" × ".join 或 "—")/目标层位(model_metadata→result_summary 回退)/输出性质/当前属性(振幅)；`update_state(task, volume_shape)`：task None→"—"+禁控件；诚实输出标注 P2：is_mock→"Mock"、非 final_scientific_prediction→"启发式"、否则 "科学预测"；demo/synthetic→前缀 "Demo · "；可替换 is_replaceable→"可替换"否则"固定"（:113-124）；井震标定 checkable 按钮；发送编图 PrimaryButton；_suppress。
- 承接：【Qt】与 C++ 平台地震属性链对接（C++ 已有 rms 等 kernel）；诚实标注文案 oracle。

## visualization_trace_panel.py（125 行）
- `VisualizationTracePanel(QFrame)`：视图追踪值卡（预测任务/古地理图/来源/标签/类型/路径消息）+刷新/导出 PNG|SVG|PDF 按钮；`update_state` 用 active_prediction_task/active_map_document；`update_ref(ref,payload)`：prediction/map kind 时覆写对应值卡；path_or_message 组合规则（path+\n+message / warning / label 回退，:98-106）；`set_export_capabilities`：大写集合驱动 enable+逐格式 tooltip（不支持文案 "当前 Tab 不支持 SVG，请切换测井/连井/古地理或改用 PNG"）。
- 承接：【Qt】导出能力诚实标注（capability gating）值得保留语义。

## geoviz_preview_provider.py（127 行）
- `LocalVisualizationProvider(PreviewProvider)`：sgy/segy 或 type=seismic 走 fallback registry；engine.supports/prepare；GeoVizError→fallback+warning 合并 `_merge_warning`（" · " join 非空段）；`preview_summary` 附 visualization_available（supports 异常→warning=str(error)）；`preview_visualization`：UNSUPPORTED→fallback；IO_ERROR/RENDER_ERROR→retryable=True 且 cacheable=False；`_engine_result`：mode=geoviz+engine_preview+estimated_bytes；`_error_text`=detail or str(error)。
- 承接：【核+薄】依赖 geoviz 引擎（C++ 对应 geo-viz-engine native / seismic_viewer）；错误分类语义 oracle。

## map_document_panel.py（132 行）
- `MapDocumentPanel(QFrame)`：左栏只读摘要（当前图件/目标层位/`{n} 个相带`/`{n} 口井`+图件列表）；`update_state`：active_map_document；列表键差分 `_document_key`=id or `doc@{id(obj)}`；行标签 `f"{name} · {horizon}"`（name 空→未命名图件）。
- 承接：【Qt】QListWidget。

## dtw_propagation_worker.py（136 行）
- `bounded_dtw_band(n_samples, band_radius=None)`：默认 band=max(20,n//4)；cap=max(20,(4_000_000//n-1)//2)；min(max(1,band),cap)（:28-38 纯函数！）。
- `DtwPropagationWorker`：recommendation_ready 先发（失败降级 None）；每井进度回调抛 JobCancelled；compute 缺失→RuntimeError("geo-viz-engine lacks compute_dtw_propagation; ...")；失败文案 f"{cls}: {exc}"。
- 承接：【核+薄】bounded_dtw_band 是 Qt-free 纯函数（oracle 候选：n=1、None band、band>cap）；DTW 核在 geoviz（C++ M8 范围）。

## governance_dialog.py（137 行）
- `GovernanceMetadataDialog(QDialog)`：source/region/creator 自由文本（strip）+ discipline/confidence/review_status 受控词表 combo（未设置=""）；`patch()`：normalize_governance_value 逐键（ValueError 上抛）；`_on_save`：ValueError→error_label 显示并停留（:99-106，词表错误不落半写）；hint 文案（版本数据不可变，治理仅资产级）。
- 承接：【Qt】依赖 catalog.governance（C++ catalog 已有治理字段？——B 线有 metadata；词表归一化在 Python catalog.governance，C++ 侧未移植）。

## map_topology_issue_panel.py（142 行）
- `MapTopologyIssuePanel(QWidget)`：summary `拓扑问题：{n}`/无问题 "当前没有拓扑问题"；ObjectTableModel 3 列（feature_id/message/severity，键=f"{i}:{feature_id}"）；`set_issues` set_rows 差分；双击/Enter→locate_requested(feature_id)（空 id 不发）；PwbEmptyState 覆盖（"未发现拓扑问题","图幅拓扑检查通过。"）；_TopologyTableView 兼容 QTableWidget 断言面。
- 承接：【Qt】QTableView+模型；空态文案 oracle。

## resource_table.py（147 行）
- `ResourceTable(QWidget)`：5 列 文件名/类型/格式/状态/路径（宽 200/100/80/100/stretch）；type 经 tokens.RESOURCE_LABELS 中文化；status 前景 token _status_token（parsed→SUCCESS/error→ERROR_RED/其他 TEXT_SECONDARY）；key=id|path|name；`update_resources` set_rows；空态 PwbEmptyState("暂无资源","导入数据后将在此列出工程资源。")。
- 承接：【Qt】模型/视图。

## visualization_summary_panel.py（151 行）
- `VisualizationSummaryPanel(QFrame)`：可视化总览 计数卡（`{n} 个`/`{n} 幅`/`{n} 项`）+可打开资产列表；`_asset_entries`：resource→VizRef（ref None 跳过）`{label} · {name}`；map→`古地理 · {name}`；prediction→`预测 · {name}`；≥2 口 LAS 井→虚拟 cross_well 条目 `连井剖面 ({n} 口井)` related_ids=前 8（:104-119）；键 res:/map:/pred:/cross_well；激活→asset_selected(VizRef)。
- 承接：【Qt】键差分清单；虚拟连井条目规则 oracle。

## result_summary.py（161 行）
- `ResultSummary(QFrame)`：QC 右栏；按 report.rules 逐条 derive_rule_result 计 pass/warning/error 计数（error 优先已在上游）；`通过项: {n}`/`警告项: {n}`/`待处理项: {n}`；advisory：error>0→"建议先处理待处理项后再输出成果"(ERROR_RED) 否则 "全部通过，可输出成果"(SUCCESS)；导出列表 `• {format} — {output_path}` 或 "暂无导出图件"；_color_label 动态 token 重绑。
- 承接：【Qt】纯展示+计数规则（依赖 qc_helpers + QualityReport 模型）。

## sequence_target_panel.py（162 行）
- `SequenceTargetPanel(QFrame)`：目标层位可编辑 combo（NoInsert；returnPressed+activated 才提交，_last_committed_target 去重；#894-5 update_state 重同步 cache）；解释版本（回退 v1）；体系域方案 combo（LST/TST/HST + tokens.SEQUENCE_SCHEMES）；适用范围 `f"{len(wells)} 口井 / {len(seismic_ranges)} 条测线"`；`update_state`：boundary 名 strip 去重入 options、target 插首、空→[""]、scheme 不在表则补；suppress 包裹。
- 承接：【Qt】提交语义（keystroke 不写工程）重要 UX 约束。

## map_edit_view.py（165 行）
- `MapEditView(QGraphicsView)`：主编图视图；导航 LOD（wheel/pan 时关 AA，120ms idle 恢复 `_NAV_LOD_IDLE_MS`）；滚轮 1.15/-1.15 缩放 AnchorUnderMouse；`_read_view_state`=中心 scene 坐标+m11；`apply_view_state(state,emit)`；`_same_view_state`（center abs_tol=1.5、scale rel_tol=1e-9）；cursor_position_changed(scene xy)；keyPress 转发 scene。
- 承接：【Qgs】原生 QgsMapCanvas 承载后此 QWidget 仅 legacy fallback；view_state 共享协议值得在 C++ 保留（mapchrome/factor shelf 读它）。

## lazy_visualization_tabs.py（171 行）
- `LazyVisualizationTabs(QTabWidget)`：tab0 数据列表（table/text/well_log_summary 三栈）+tab1 可视化预览（prompt/loading/message+reload）；host 懒建（GeoVizPreviewHost）；`set_engine` host 已建→RuntimeError("cannot replace engine after visualization host creation")；`load_summary` 按 mode 分派；show_loading 不抢 tab（#630 no-steal）；show_error（message 或 "可视化预览不可用"，reload 恒可见）；currentChanged→visualization_requested（一次）。
- 承接：【Qt】懒加载契约（启动不拉引擎）+no-steal 语义。

## onboarding_report_card.py（171 行）
- `OnboardingReportCard(QFrame)`：数据盘点报告卡（默认隐藏）；`set_report(dict|None)`：None→隐藏；来源目录（source_folder|intermediate_folder）；summary=`导入 {n} 项 · 井 {n} 口（{n} 有坐标） · 地震 {n} 个 · 地质实体 {n} 个`；by_type 按数量降序 `k v` join " · "；extent 4 元全非 None→`范围：[x, x] · [y, y]`（%.1f，异常→"无坐标井位范围"）；issues+warnings 合并取前 5 行显示（warnings_label 复用隐藏避免重复）。
- 承接：【Qt】QLabel 组；文案/格式化 oracle 面。

## interchange_models.py（178 行）
- `PreflightIssueModel(QAbstractTableModel)`：列 级别/代码/说明；severity 排序 error<warning<info（label→order 反查）；ok/recommendation 暴露。`BatchResultModel`：列 源文件/输出/状态/校验/耗时(ms)/说明；状态中文化 _STATUS_LABELS（converted 已转换/failed 失败/skipped 跳过/cancelled 已取消/pending 等待）；校验列空→"—"。`PackagePlanModel`：列 名称/阶段/状态/大小(B)/说明；状态 included 打包/external 外部引用/missing 缺失/stale 内容可疑/excluded 排除；名称=Path(item.path).name。
- 承接：【核+薄】交互交换（interchange）线 C++ 侧已有 libs 交换成果（conv-14）；模型为薄 Qt 壳。

## json_tree_preview_widget.py（180 行）
- `JsonTreePreviewWidget(QTreeView)`：JSON 树（键/值类型两列）；数组/字典 >array_collapse_threshold(默认100)→单节点 "[N items]"/"{object · N keys}" 懒展开；_EXPAND_BATCH=2000 哨兵行 "… 展开加载下一批（剩余 N 项）"；_MAX_BUILD_DEPTH=64 溢出 "…"；expand_depth=2 初始展开；apply_settings：阈值/深度变化才重建（字号即时）。
- 承接：【Qt】QStandardItemModel 懒树（#531 防冻结契约）。

# 16 — Findings 第 3 批：pages 059-078

## summary_table_preview_widget.py（186 行）
- `SummaryTablePreviewWidget(QWidget)`：LAS 摘要两 tab（曲线定义与元数据/数据内容）；三 stat chip（◆ 井名/▤ 曲线数 N 条/◌ 采样点 N 点，采样点千分位 `f"{int(v):,}"` 失败保原串 :161-167）；info_splitter 元数据表贴合内容高（min(max(total,60),120)）；`load_summary(summary_rows, detail_headers/rows, message, data_headers/rows)`：rows 键 "井名/曲线数/采样点" 驱动 chip；无数据行→tab1 禁用。
- 承接：【Qt】表+chip 条；行高适配逻辑保留。

## map_edit_toolbar.py（188 行）
- `MapEditToolbar(QWidget)`：TOOL_IDS 6 工具（select/move/vertex/facies/line/label，中文 label）互斥 QButtonGroup+11 个 Signal（snap/preview/canvas_priority/topology/merge/split/save_draft/generate_demo/undo/redo/tool_changed）；`set_preview_mode`：预览开→编辑/捕捉/拓扑/合并/分割全禁（blockSignals 同步 checked）；`set_tool(未知)→ValueError(f"Unknown tool: {tool_id}")`；同工具重复 `_apply_tool` no-op。
- 承接：【Qgs】QGIS 原生地图工具（QgsMapTool）承接语义；按钮条 UI 保留。

## factor_preview_grid.py（189 行）
- `FactorPreviewGrid(QWidget)` + 内嵌 `FactorPreviewCard(QFrame)`（min 160x100，左键 release→clicked(task)）；卡片三行：title=factor_type|name、range_label=quality_metrics["range"] 或 "—"、rsquared_label（有 r_squared→`R² {v}`；metrics 非空但无→"R² 本轮未计算"（#939-5 诚实缺口）；metrics 空→隐藏）；dup_label（duplicate_wells_dropped>0→`{n} 口同坐标井已去重（保留先录入值）` ERROR_RED）；`update_state(tasks)`：仅 status=="complete"；空→"暂无已生成的单因素图"；表头 `f"{horizon} 单因素图集（{method}插值 · 网格 {grid} m）"`（method 空→"—"，grid 缺省 "50×50"）；2 列网格。
- 承接：【核+薄】**卡片值来自 task.quality_metrics（含 statistics 派生 range）——本任务 HUD 的 Python 对应面之一**；【Qt】网格卡。

## preview_strategy.py（189 行）
- 常量：MAX_PREVIEW_BYTES=8192/MAX_PREVIEW_LINES=20/格式集合（TEXT={txt,xml}、TABLE={csv,dat}、PDF、MARKDOWN={md,markdown,htm,html}、JSON={json,geojson}、AUDIO、PROFESSIONAL={las,sgy,segy,xlsx,xls,ppt,pptx,wlp,dfb}）。
- `PreviewState` dataclass(mode,title,lines,image_path,document_path,warning)；`_display_path`（相对→base 父目录 resolve，OSError 回未解析 join #891）；`_summary_lines`（文件/格式/路径/大小 format_size）；`_looks_binary`=含 \x00；`_read_preview_lines`：OSError→`f"{name}: {ExcClass}"`；二进制→"内容看起来是二进制，使用安全摘要预览"；截断 warning=`f"仅显示前 {n} 行"`。
- `preview_for_resource`：不存在→metadata+warning="文件不存在"；分派 image/pdf/media/rich_text/json_tree/text/table/professional(非 well_log/seismic→"此格式暂使用安全摘要预览")/table_types/well_log("预览: 测井摘要")/seismic("预览: 地震体元数据")/document 类("此类型使用外部工具预览")/默认 "暂不支持预览"。
- `preview_for_artifact`：lines=格式/路径/关联；title=`成果文件 · {format}`。
- 承接：【核+薄】**纯函数无 Qt → 完整 Qt-free oracle 面（格式分派全分支+文案逐字）**；与 resources.preview_parsers registry 并存（两套：本文件是 V1 简版策略，registry 是 V2）。

## project_overview_panel.py（189 行）
- `ProjectOverviewPanel(QWidget)`：工区概览；8 统计块（井/地震工区/RAW/DERIVED/OUTPUT/缺失外部异常/待治理实体/最近任务）值+caption；`refresh_from_project(project, counts)`：title=`工区 · {name}`、meta=`CRS: {crs|未设置}　区域: {region}`；counts=None→RAW/DERIVED/OUTPUT/issues 显 "—" 不伪造 0（C-P0-1）；derived=derived+intermediate；issues=missing+modified；unresolved=unresolved links+flagged 坐标井；recent=compilation_runs 按 updated_at max；hints（歧义关联 N 条/缺 CRS N 口/工区或井位范围 X[..] Y[..] %.1f）。
- 承接：【Qt】统计条——**数值 HUD 家族成员**（与 FactorStatsDock 同构：值卡+回退 "—"）。

## impact_preview_dialog.py（190 行）
- `collect_trash_impact(service, project, asset_ids, workspace)`→TrashImpactSummary（计算失败不吞：computation_errors 计数 fail-closed :42-56）；descendants 取前 20、map_usages 前 30、cascade_advice 前 5。
- `TrashImpactSummary.render_markdown()`：错误→"⚠ N 项资产的影响计算失败——无法确认是否安全，请按存在影响处理"；下游 N 个/N 图层引用/N run/N 实体/断链/建议；全空→"未发现下游依赖或地图引用——可以安全移出（回收站可随时还原）。"
- `confirm_trash_impact`：无下游静默 True；有→QDialog（标题 移出项目 — 影响预览；取消为 default 按钮——Enter 不误删）；markdown 渲染失败回纯文本。
- 承接：【核+薄】render_markdown 纯函数可 oracle；依赖 catalog.impact（C++ M4 已有 lineage 读模型可接）。

## workarea_map_widget.py（191 行）
- `WorkAreaMapWidget(QWidget)`：整幅工区图（qgis_stack.display_canvas.create_display_canvas：桥可用=QgsMapCanvas）；set_project 域签名缓存（domain_signature 不变不重建快照）；well_selected/well_activated；拾取容差 16px（屏幕距² 比较）；退化 extent 除零被吞（#1166）；overlay=比例尺+指北针(+标题栏+图例)+selected_features；zoom_to_all/select_well(zoom=0.2 half span)。
- 承接：【Qgs】**原生 QGIS 画布承接示范**（qgis_stack 桥+fallback 双路径）。

## map_edit_topology.py（192 行）
- `facies_geometry_issues(item)`：api.validate_ring 逐环（缺省 code=invalid_geometry/message=几何无效）；validate_polygon_geometry 缺失时 ImportError/AttributeError→[]；`apply_adjacency_warnings`（gap_tol，pair 双侧置 warning，仅 ok→warning）；`plan_topology_rebuild`：空→零报告+None；api.rebuild_topology→changes（旧≠新）BatchVertexEditCommand；报告 {snapped_count,ring_warnings,adjacency_issues,changed,ring_issues,adjacency_issue_list}；`plan_merge_facies`：复杂几何/merge 空/新 record 无法建 item→(None,None)；名=a.name|b.name|"合并相带"；`plan_split_facies`：parts<2→None；命名 `f"{base}-{i+1}"`（base 空→"相带"）。
- 承接：【核+薄】plan_* 是「计划+命令」纯逻辑（geoviz api 数值核 + undo 命令）；C++ 由 mapping_kernel 已有 polygonization 部分承接，合并/分割待 M6 余项。

## well_log_track_settings.py（194 行）
- `_CurveLayoutTree.dropEvent`：内部拖=合并请求（source≠target 才发 merge_requested(str,str)，event 恒 ignore）。
- `CurveTrackSettingsDialog(QDialog)`：井道显示设置；勾选控制可见（with_visible）；合并上限 CurveGroupLimitError→status_label=str(exc)；状态文案（"已合并井道。"/"当前井道尚未合并。"/"已解除合并。"/"请选择需要解除的合并井道。"/"已恢复默认 6 个井道。"）；组父项 "+".join 名。
- 承接：【Qt】树拖拽合并；依赖 viz.well_log_track_layout（纯模型可 C++）。

## integrity_worker.py（195 行）
- `compute_sha256(path, max_bytes, is_cancelled)`：非文件→None；64KiB 分块+yield；OSError→None。
- `IntegrityCheckReport.summary_text`：`已校验: {v} · 已修改: {m} · 缺失: {x} · 外部链接: {u}`。
- `IntegrityWorker(QObject)`：catalog 桥资产经 DataCatalogService.verify_integrity（UI 永不改写 checksum，:109-128 details "校验和不匹配 (目录记录保持不变)"）；非桥 legacy：missing/unmanaged/checksum 比对（details `预期 {hash8}, 实际 {hash8|N/A}`）/补算 checksum_updates；取消→details "完整性校验已取消"；_CATALOG_STATUS_TO_STATE 映射。
- 承接：【核+薄】sha256/状态机 Qt-free；catalog 桥对应 C++ CatalogRepository 完整性（M4 域）。

## well_table_panel.py（198 行）
- `WellTablePanel(QFrame)`：井点表 11 列（井名/X/Y/Z/Hs/Ht/Rs/q/b/QC/z*）；QC 前景 token（ok SUCCESS/outlier WARNING/invalid_ratio ERROR_RED/missing TEXT_SECONDARY）；`update_from_well_table`：None/空行→复位 "0 行"+空态（"暂无井点","从单因素 sample_points 或工程 well_tables 同步."）；title=" · ".join(name,horizon,factor_type)；summary=`{n} 行`+`k:{cnt}`（仅非零，序 ok/outlier/invalid_ratio/missing）；StableSelection 跨刷新保选择；`_fmt`：None→""、|f|≥1000 或 0<|f|<0.001→`%.4g`、否则 `%.4f` 去尾零（:189-198 纯函数）。
- 承接：【Qt】模型表；_fmt 纯函数 oracle 面。

## workflow_contract_panel.py（198 行）
- `WorkflowContractPanel(QFrame)`：专业工作流合同（默认 contract factor_interpolation）；STATUS_ZH（可执行/部分就绪/阻塞/未知）、IMPL_ZH（生产/部分实现/演示/占位）；refresh 渲染 功能/实现状态/当前状态(evaluate_readiness reasons)/输入(必需|可选)/主要操作/参数/输出/上下游（"、".join 或 无）/QC（未声明）/待专家确认（无开放问题）；dev 模式追加 contract id/DataRun ops/evidence 8 条/Q certainty。
- 承接：【Qt】依赖 workflow.contracts（M7 引擎外围，C++ 未有）；文案渲染面大。

## sequence_framework_page.py（214 行）
- `SequenceFrameworkPage(QWidget)`+`PanelFloatButton`：层序格架页（target 面板|boundary 表|scheme 摘要 QSplitter 280/900/260）；FloatController 浮动（LayoutPersistence，splitterMoved 400ms 防抖持久化 `_DOCKED_SIZES_DELAY_MS`）；`save_scheme`：未绑工程→QMessageBox "未绑定工程，无法保存"；空 target→"请先选择或输入目标层位"；成功→set_bind_status `已保存 · 目标 {t}`；target_changed→apply_stratigraphy_scheme(bind_downstream=True)+`已绑定 · 目标 {t}`；boundary 双击→set_target_from_boundary。
- 承接：【Qt】页面组装+浮动面板框架（dock 系统核心参考）。

## factor_task_panel.py（221 行）
- `FactorTaskPanel(QFrame)`：准备页左栏；层位 label `层位: {t0.target_horizon}` 或 `层位: —`；method combo（tokens.INTERPOLATION_METHODS+逐项 tooltip；`activated` 才算用户选择 #894-2，刷新不覆盖用户选择）；行 widget name+`f"{method} · {grid}"`（parameters.grid 缺省 "50m"）+状态徽章（complete→done/pending→queued 经 state_language）；`update_state` 众数 method 回填（无用户选择时）；summary=`已制备 {complete} / {total} 个单因素图`；generate_requested(method or "IDW")；contour_draft_requested。
- 承接：【Qt】任务列表；与 FactorGrid 生命周期相连（HUD 数据源上下文）。

## well_detail_panel.py（229 行）
- `WellDetailPanel(QWidget)`：井数据视图（WellDataView 只读渲染，无自有状态）；roles 表 5 列（角色/资产/主用/当前版本/版本数；成员名前 4+`…(+N)`；version id 前 14+"…"；主用 "✓"；版本数 sum）；三卡 过期成果/未提交编辑/缺失异常（列表前 8+`…另有 N 项`；空文案 "无过期成果"/"无未提交编辑"/"-"；缺失行 `角色缺失: {display}`/`源文件缺失: {id}`）；`update_stale` 后到结果回填；close_requested "← 返回资产列表"。
- 承接：【Qt】依赖 catalog.entity_views（conv-15 D2 未移植面）+project.roles。

## seismic_slice_preview_widget.py（234 行）
- `SeismicSlicePreviewWidget(QWidget)`：切片方向 combo（Inline/Crossline/Time）+slider+`{v} / {max}`；load_seismic(volume=None)→清 pixmap 防 resize 重装旧图（#894-4）、文案 message 或 "无地震数据或无法解析"、slider 禁用 "0 / 0"；全局拉伸范围 global_stretch_range 一次（切片间稳定色标）；fast_slice_to_indexed8+蓝白红色表（np.linspace 256，white t=0.5）；拖动时 FastTransformation 否则 Smooth；16ms 渲染防抖 timer。
- 承接：【Qgs/Qt】C++ seismic_viewer 已有切片渲染（libs/seismic_viewer SeismicSliceWidget）——此 widget 与之重叠，承接策略=复用 C++ viewer。

## create_factor_map_dialog.py（242 行）
- `_FactorMapWorker(QObject)`： GeologicalMappingService.create_factor_map（kriging/grid/contour；InterruptionRequested 检查；失败 emit str(exc)）。
- `CreateFactorMapDialog(QDialog)`：模态；参数组（地质因素 7 选/目的层段（工程 target_horizon 优先+固定 7 项去重）/插值算法（kriging|idw）/网格 20-300 步 10 默认 50/色带 11 项）；生成图层 4 checkbox（栅格/等值线/井位默认真，相带多边形默认假）；OwnedWorkerJob 线程管理（closeEvent/reject 先 shutdown(wait_ms=1000)）；成功→`成功生成地质图件：{title}\n包含 {n} 个 GIS 图层。`；失败→`地质编图失败：{msg}`。
- 承接：【核+薄】**单因素图生成入口——mapping_kernel（C++ interpolate_factor）的用户流程终点**；对话框壳 Qt。

## preview_disk_cache.py（247 行）
- `is_disk_cacheable`：ResourceItem+type∈{horizon,well_stratification,well_head}+format dat；`_options_fingerprint`（profile/上限字段+schema sha256 前 16）；`_entry_key_material`（json sort_keys sha256 前 32）；`PreviewDiskCache`：.preview_cache/entries/<key>/{meta.json,payload.npz}；try_load：key 不匹配/损坏→删 entry；store：staging .tmp-<key>-<uuid>→os.replace 原子替换，commit_guard 门；失败永不破坏预览。
- 承接：【核+薄】缓存键/原子写纯逻辑可 oracle（npz/geoviz 编解码除外）。

## filter_chips_bar.py（249 行）
- `FilterChipsBar(QWidget)`：活跃 FilterQuery→可移除 chips（视图:`{label}{ · value}`/搜索:/阶段:/类型:/标签:/全部满足|任一满足/资产: 前16…）；chip_removed(dim)（表拥有 query，bar 只反映）；清除全部；已保存过滤器存 QSettings data_explorer/saved_filters（json [{name,query}]，casefold 排序；应用失败 QMessageBox "该保存的过滤器无法解析"）；FilterChip 点击发 clicked(key)。
- 承接：【Qt】QSettings 键值持久化；chip 维度序列化文案 oracle。

## asset_context_menu.py（254 行）
- `AssetContextMenu(QMenu)`：动态按 stage（RAW：创建派生副本/曲线解释(RAW well_log)/编辑原始数据(已锁定 ⊘, 禁用, tooltip=`不可用：{raw_layer_gate_reason()}` 同源门禁文案)；DERIVED/INTERMEDIATE：新建版本/提升为正式数据；OUTPUT：导出/交付；trashed：还原+打开目录）；非托管→纳管/重新链接（默认禁用）；校验完整性/版本工作台/血缘浏览器（需桥，禁用 tooltip "需要数据目录桥接的资产"）；标签/归类为子菜单/导出子菜单（get_available_formats+工程清单 JSON）/打开目录/用系统应用打开（remote URL 禁用 tooltip "无本地文件路径"）/可视化页打开（能力门控）；多选→批量菜单（`已选择 {n} 项数据资产` 头+批量标签/校验/移出）；破坏动作红色 delete 图标；find_action/find_export_action。
- 承接：【Qt】菜单构建规则表（stage×managed×能力）可表驱动+oracle。

# 16 — Findings 第 4 批：pages 079-098

## curve_operation_dialog.py（257 行）
- `CurveOperationDialog(QDialog)`：11 曲线操作标签表 `_OPERATION_LABELS`（仅 CURVE_OPERATIONS 已注册项入 combo）；按 op 重建参数行（despike σ3.0/窗口3；smooth 5；median 5；normalize zscore|minmax；clip p1.0；baseline delta；unit_conversion 白名单对 hint "m↔ft, g/cm3↔kg/m3, us/m↔us/ft, mm↔in, mv↔v, %↔v/v"；depth_shift Δm；resample step；depth_unit_normalize m|ft；derive_curve 表达式+名+单位）；`_collect_parameters`（spin→value、combo→currentData、lineedit→strip）；`_run_diagnostics`：lasio 读+missing_interval_report，QMessageBox 文案（`曲线 {c}（{n} 样点）`/`缺失样点: {n} ({pct:.1%})`/`最大连续缺口: {g:.2f}（深度轴单位）`/缺口前 8 段 `a–b` 顿号 join + `…等 N 段`/无→"缺口区间: 无（首末有效样点之间连续）"；曲线不存在 `曲线 {c!r} 不在该文件中。`；读取失败 `读取失败: {exc}`）。
- `run_curve_operation_dialog`：Accepted 才 apply_curve_operation→新 DERIVED 版本；失败 `操作失败: {exc}`；成功 `已生成派生版本（{op}）\n输入版本: {id18}…\n输出版本: {id18}…\nRun: {id18}…`。
- 承接：【核+薄】依赖 workflow.curve_operations（conv-11 curve-ops worktree 已移植部分？——独立分支）；对话框 Qt。

## well_seismic_joint_page.py（261 行）
- `WellSeismicJointPage(QWidget)`：井震联合薄壳（WellSeismicJointHost 承载全部场景生命周期）；竖直域 Time|Depth（Depth 被拒→回滚 combo 到场景实际域 blockSignals）；井 A/B combo（刷新间保留选择，B 默认 index 1）；井间剖面/重新加载/导出快照；引擎不可用→`联合三维引擎不可用: {err|unknown}`；`export_snapshot`：grab().save png（`已导出快照: {name}`/失败 "快照导出失败"）+best-effort OUTPUT DataVersion 注册（lineage 源匹配失败→logger.warning 不静默）；`shutdown_workers(wait_ms=400)` 项目切换收尾（#1158）。
- 承接：【延后】geoviz 3D 联合引擎属 M8 viz；壳层 Qt 语义（域回滚/选择保持）值得抄。

## prediction_evidence_panel.py（262 行）
- `PredictionEvidencePanel(QFrame)`：预测证据右栏；值卡 输出性质/数据来源/目标层位/相带段数/预测相带/状态；诚实标注 P2（model_type∈{geoviz_online,inference_api_online}→"线上测井预测"；is_mock→"Mock"；非 final_scientific_prediction→"启发式"；否则 "科学预测"；demo 前缀 "Demo · "；"可替换|固定"）；来源（线上→"认证线上推理服务"/demo|synthetic→"合成演示数据"/bound_las→"绑定 LAS"/否则 "合成曲线"）；class_counts 排序前 2 `{name} {pct:.1%}`（total 0→`{name} {count:g}`）+全量 tooltip；evidence 列表 `{name}: {weight:.0%}`；运行日志 QPlainTextEdit（blockCount 200、占位 "尚无运行日志"、空→复制按钮禁用）；等待态 "正在提交并等待线上推理结果…"+0..0 进条；set_inferring 推断中 run/demo 禁（#850-7）；#897 异步结果在页内不打模态。
- 承接：【Qt】诚实标注规则表（nature/source 双选择器）可 oracle。

## seismic_context_toolbar.py（269 行）
- `SeismicContextToolbar(QFrame)`：单行紧凑工具条；`_ATTRIBUTE_GROUPS` 5 组 16 属性（ALL_SEISMIC_ATTRIBUTES 平铺）；源体 combo（占位 "选择数据管理中的 SEG-Y 地震体"）；设置与详情 ▾ 弹出卡（任务/层位/当前属性/显示模式/体数据维度/输出性质 六值卡+切换显示模式 vd|wiggle QActionGroup+切换地震属性分组子菜单）；`set_context` 逐卡回填（shape `" × ".join`）；set_inferring "推断中…"；set_status（空回 "—"）。
- 承接：【Qt】与 seismic_attribute_panel 是同一属性词表的两壳（toolbar 平铺 vs panel 分组置灰）——注意两表不完全一致（toolbar 含 振幅/高斯曲率/最大曲率/RGB融合 在可选组，panel 置灰），inventory 中标注。

## data_workspace.py（270 行）
- `DataWorkspace(QWidget)`：数据页三栏（NavigationTree | 中心栈(资产表/工区概览/井数据视图)+WellMapPanel | 右竖分(ReaderPanel+InspectorPanel)）；FloatController 浮动（data:navigation/reader/inspector/well_map 四键；地图浮动时先展开、回收时恢复折叠并重插布局 :201-222）；show_overview（概览把共享地图 panel 移入概览页、回表时还原折叠态；浮动中跳过 swap）；show_well_detail(index 2)；set_right_visible；_DOCKED_SIZES_DELAY_MS=400 持久化防抖。
- 承接：【Qt】**数据页布局骨架**（C++ MainWindow dock 的页面级对应物）。

## preview_settings_panel.py（276 行）
- `PreviewSettingsPanel(QFrame)`：8 分类页（通用/文本富文本/表格测井地震/图片GeoTIFF/PDF/JSON/音频/GeoViz）全字段 spin/checkbox/combo（范围见 :131-208）；_MODE_CATEGORY 12 模式→分类映射（未知→general）；`settings()`/`set_settings` 全字段往返；应用→store.save+settings_applied；恢复推荐默认→store.reset。
- 承接：【Qt】设置面板（PreviewSettings dataclass 在 resources，Qt-free 可对账）。

## map_edit_commands.py（278 行）
- `EditCommand` Protocol(do/undo)；`MoveCommand(feature_ids,dx,dy)`（undo 取反）；`VertexEditCommand`（整环替换）；`RingEditCommand`（按 (part,ring) 寻址不塌兄弟洞）；`CreateFeatureCommand`/`DeleteFeatureCommand`（record 快照互逆）；`PropertyChangeCommand`（标量属性）；`BatchVertexEditCommand`（多要素一 undo 步）；`CompositeCommand`（undo 逆序）；`EditCommandStack(max_depth=50)`：push 即 do、超深 pop(0)+`overflowed=True`（#894-3：can_undo 无法回基线时 dirty 保持）、redo 清空、clear 重置 overflowed；`ValueError("max_depth must be >= 1")`。
- 承接：【核+薄】**Qt-free 纯命令栈——完整 oracle 面**（depth 溢出语义/redo 失效/composite 逆序）。

## catalog_health_dialog.py（283 行）
- `CatalogHealthDialog(QDialog)`：audit 报告渲染（summary=`资产 {a} · 版本 {v} · 运行 {r} · 标签 {t}　|　问题 {n} 项: 高 {h} / 中 {m} / 低 {l}`+verdict ✅健康|⚠️需处理）；问题表 4 列（级别 `高 (high)`+前景色/类型/对象/详情）severity high>medium>low 排序，键 `f"{i}:{kind}:{ref_id}"`；快速/深度检查 OwnedWorkerJob（#1056 关窗协作取消 shutdown(3s)）；未连接→"未连接数据目录（请先打开项目）"；失败 `检查失败: {msg}`；空态 "未发现目录健康问题","可定期运行深度检查复核数据校验和。"；relink_requested 信号（D9 解耦重链接流）。
- 承接：【Qt】audit 核在 catalog（Python catalog.audit；C++ 侧 GC/manifest 已有，audit 待）。

## review_export_page.py（298 行）
- `ReviewExportPage(QWidget)`：成图审核页（ActionHeader|QCIssueTable|ResultSummary + FloatController review:summary）；run_qc（未绑→"未绑定工程"；无图→"工程中尚无古地理图草稿，请先编图或生成演示草稿"；逐 doc run_map_qc；完成 `已检查 {n} 幅图件`）；export_report（无报告→"暂无质检报告可导出，请先运行检查"；建议名 `qc_{doc_id}.json`；失败 `{cls}: {exc}`；完成 `已导出: {name}`）；finalize_version（优先 QC 关联 doc，否则最后一张；异常 `定稿失败`；完成 `已定稿图件「{name}」\nVersionSet: {v}\n状态: {s} · 快照数: {n}`，require_qc_pass=False）；tab 链显式设置（audit F1）。
- 承接：【Qt】QC/版本核（workflow.qc/versioning）Python 侧未在 C++。

## data_toolbar.py（316 行）
- `DataToolbar(QWidget)`：15 个动作 Signal；按钮排（导入文件 Primary/导入目录/规划导入…/取消导入(仅导入时可见)/完整性校验(set_verify_running 切 "取消校验")/健康检查/重新扫描/移出项目/打开目录/可视化/清除预览缓存/标签筛选(懒重建菜单：checkable 标签+AND|OR 互斥组+清除；空候选→"暂无可用标签")/标签管理/搜索框（180ms 防抖；set_search_text_silent 防回环）/列设置 slot/预览栏 checkable）；tag 状态真源在 `_selected_tags` 非 menu mirror（#413）；tooltip 全套。
- 承接：【Qt】工具条直译；#413 状态真源语义重要。

# 16 — Findings 第 5 批：pages 099-110

## map_layer_tree.py（332 行）
- `MapLayerTree(QFrame)`：LAYER_KEYS 4 图层（facies/well/line/label 中文标签）；树=图件根+文档节点+活动文档 4 图层子树（勾选=可见/第二列 "⊘"=锁定）+可选 参考图层 组（offline "(离线)"/failed "(失败)"）；键差分（_ROOT_KEY/__root__、doc:{id}、ref:{id}、layer:{k}；非活动文档子树清空）；展开只首填时强制（保留用户收起态 V11 D2 ⑮）；document_selected（reference_layer/layer 行不发射——#bug 修）；layer_visibility_changed/layer_lock_changed；`set_layer_locked`（同值 no-op）。
- 承接：【Qgs】QgsLayerTreeView 是原生对应（qgis_stack.layer_tree_panel 已做）；本 widget 为 legacy fallback。

## image_preview_widget.py（334 行）
- `ImagePreviewWidget(QLabel)`：zoom_changed；有界解码 `_decode_bounded`（QImageReader 长边 ≤2048 解码期缩放 #530）；fit/zoom 双模式：zoom 模式不物化整图位图，paintEvent 视口窗口化采样 O(viewport)（#1135 曾 8×2048px≈1GiB）；缩放 1.25 步、[0.1, 8.0] 钳制、边界外重复 no-op；pan 钳制 `_clamp_pan`（widget 未布局 fallback 240x180）；Ctrl+滚轮缩放；左键拖平移（OpenHand/ClosedHand）；80ms resize 防抖（fit 重采样一次）；失败文案 "图片预览加载失败"；新图回 fit。
- 承接：【Qt】原生图形项；窗口化绘制契约值得 C++ 保留。

## composite_visualization_panel.py（346 行）
- `VisualizationWorkspace(QFrame)`（别名 CompositeVisualizationPanel）：七 host tab（WellLog/WellSection/Seismic/CrossWell(滚动)/PaleoMap/WellTie/EnginePreview，各 Host.tab_title）；多尺度层级 combo（level_choices+hierarchy_active 才显，auto 默认）；M3 `_SectionCursorBand` 井位级联动竖带（x=width*(i+0.5)/n-3，未知井/空名隐藏）；`load_payload`：message→清+状态；按 kind 分派 host.apply 收集 applied（`已加载: {label} → {tabs}` / `未能加载: {label}` join " · "，warning 前置）；kind→默认 tab 映射（prediction 有 seismic_volume→地震否则测井）；`_clear_all(preserve_well)`；export_snapshot（capabilities|导出）。
- 承接：【Qgs/延后】viz hosts 属 M8；壳的分派/status 组装语义可借鉴。

## correlation_link_editor.py（368 行）
- `CorrelationLinkEditor(QDialog)`：链接表 5 列（层位（top_a 缺→"?"）/井 A → 井 B（同）/方法（_METHOD_LABELS 4 中文，坏值 str）/邻接 是|否/备注）+顶点表 5 列（井/层位/深度 `f"{d:.2f} {domain}"`/方法/置信度（空→"—"））；排序 links(top_a,top_b,id)/tops(well,marker,depth)；增链（<2 顶点→"至少需要两个顶点。"；标签 `f"{well} · {marker} ({depth:.1f}) #{i}"` 唯一映射防 index 首匹配 R1-M6；add_manual_link ValueError→warning）；删链/改方法备注（嵌套 QDialog）；顶点属性编辑（method/confidence 自由文本/status active|tentative|rejected/notes）→bump()+重建；`run_link_editor`（generation 变化才 on_changed）。_top_by_id 每次重建（DTW worker 可在模态中扩 tops，R3-M3）。
- 承接：【延后/Qt】依赖 workflow.correlation_session + stratigraphy_models（层序相关，M7 外围）；表/对话框模式可复用。

## asset_table_model.py（374 行）
- `RESOURCE_TYPE_LABELS`（tokens.RESOURCE_LABELS+12 扩展）；`_sort_tuple`（按语义排序 #651：size None→(1,0)；version 数字序列 tuple；modified 空→(1,"")）；`_match_positions_by_identity`（id() 恒等重用，重复对象按序消费，超出→None 保守重建 #1063）；`_recycle_views`；`AssetTableModel(QAbstractTableModel)`：列=可配置 column_keys（16 列词表）；set_assets/set_assets_filtered（view 回用 token=(project_root,enricher)；last_sort 重应用 #1064/#850-1）；`_format_cell_display`（stage=`{icon} {label}`；tags join ", " 或 "—"；managed 受管|外部；integrity=`{icon} {label}`；role input 输入|derived/export 成果；...）；tooltip（`生命周期: {label} ({value})`/`完整性: {label}\n校验和: {cs}`/血缘断链 "未连接数据目录"/`标签: ...|无`）；asset_at/view_at。
- 承接：【核+薄】**行视图/排序/格式化纯逻辑厚重——C++ 可 Qt-free 模型核心+QAbstractTableModel 薄壳；oracle 富矿（排序语义/单元格文案）**。

## preparation_page.py（377 行）
- `PreparationPage(QWidget)`：制备页三栏（FactorTaskPanel|FactorPreviewGrid+WellTablePanel|BoundaryPanel，sizes 240/900/240）；tab 链显式；进程级 generation（#834 并发取代：项目切换 supersede）；`_resolve_display_well_table`（project.well_tables[0] 优先，否则首个有 sample_points 的任务派生 well_table_from_factor_task）；`_run_well_qc_impl`：无数据→"没有可检测的井点数据。"；run_well_table_qc(value_key=value_key_for_factor_type(factor_type))（#1151 砂地比评 R_s）；sync_well_table_to_linked_tasks（#936 不注入无关任务）；完成 `完成：ok={n} outlier={n} invalid_ratio={n} missing={n}`+未绑注记；generate 中再点→"正在生成中，请稍候…"；progress 文案 `制备中：复用 {n} · 需计算 {n} · 已完成 {n}/{n}[ · msg]`；完成 `已制备 {c} / {t} 个单因素图 · 复用 {n} · 计算 {n}[ · 丢弃过期 {n}]`；失败 `单因素图生成失败：{msg}`（页内不模态 #897）；等值线（无工程/生成中→提示；完成 `等值线初稿：已生成 {n} 份并推送到编图。`/无网格 "等值线初稿：没有可提取的单因素网格，请先「批量生成单因素图」。"/失败前缀）。
- 承接：【核+薄】**插值批处理编排（generation 门/诚实汇总）——与 C++ interpolate_factor 对接的主用户流程**；worker/编排 Qt。

## home_page.py（387 行）
- `HomePage(QWidget)`：工区地图为心（create_display_canvas；domain_signature 门控重建；空→PwbEmptyState "工区地图","暂无空间数据。导入井位与地震工区后，这里将展示\n工区边界、井位分布与地震测区范围。"）；CRS 警示幅（"⚠ "+";".join(warnings)，§20 不静默扣 overlay）；井拾取 16px（同 WorkAreaMapWidget）→well_activated；右列 StartGuideCard+OnboardingReportCard（无资源且无报告才显示；都隐藏则整列让宽）；下半 ModuleRelationshipWidget+LegendWidget（导航信号转发）；底部 RecentActivityCard+WorkflowContractPanel(step→contract 映射 data_check→data_import...)+DataCompletenessCard；`shutdown_workers`→canvas.shutdown()。
- 承接：【Qgs】首页=QgsMapCanvas 只读嵌入示范（C++ M4 已做 map embed）；卡片群【Qt】。

## map_dock_manager.py（400 行）
- `DockRail`（36px 图标栏+面板区兄弟 widget，rail AlignTop）；`MapDockManager(QObject)`：add_panel（checkable rail 按钮+area 布局）/register_bottom（左栏底部 toggle+apply 回调重算可见性）；panels_menu（`MapPanelMenu:{key}` 显隐 action+`浮动 · {title}` toggle）；浮动语义：rail 按钮="面板可见"，浮动时显示/隐藏窗口（_on_rail_toggled 分支 :300-315）；浮窗可见性镜像 rail 按钮（用户关窗=偏好变更进 _bottom_user_visible；程序性跳过 _bottom_programmatic 再入护栏 :351-379）；sync_area_visibility（全隐收起 area 让位画布）；panel_title（float_key 反查；缺省 key 尾段）。
- 承接：【Qgs】QgsDockWidget/QgsPanelWidgetStack 原生可承接大部分；浮动/镜像状态机是自研框架（FloatController 在 ui/ 顶层，subagent #1 覆盖）。

## table_preview_widget.py（400 行）
- `TablePreviewModel(QAbstractTableModel)`：虚拟化（data() 视口按需）；深度列（DEPT/DEPTH/深度）mono 粗体+主题色；曲线定义表（headers[0]∈{曲线,Mnemonic} 且 ≥3 列）助记符列 tag 色/单位列灰；数值列右对齐 mono（"NaN" 是数字+PRIMARY_DISABLED 前景）；`row_text`；`_themed_brushes` 按主题缓存（#1047）。
- `TablePreviewWidget(QTableView)`：MAX_PREVIEW_CELLS=1e6 防御性截断（文案 `表格预览已截断：显示 {k}/{n} 行（上限 {MAX} 单元格）` tooltip+statusTip）；auto_fit 采样前 400 行（:67）；`copy_all` TSV（含表头/仅可见行/无行仅表头）；Ctrl+C 复制选区（按行排序单元格）；QTableWidget 兼容访问器（item/_CellRef/horizontalHeaderItem/setRangeSelected）。
- 承接：【Qt】虚拟模型直译；格式化规则可 oracle。

## geological_modeling_workers.py（405 行）
- `GeologicalModelingWorker`：demo=True 合成体（meshgrid 正弦体 40|80|120 按密度含"低/中"）+4 钻孔（HZ21-1/HZ19-6（135<180 刻意重叠告警）/XJ24-3/HZ25-2（168>160 超总深））圆柱段/2 巷道 tube/2 断层面（z+20/+12）；结果 dict demo/source="synthetic/demo"。
- `StratalWorker`：demo→make_demo_stratal_grids(16,20,32)+build_proportional_surfaces；真实→build_stratal_grids(scene,volume,top,bottom) 或解释工件 NPZ（读失败 ValueError("解释工件读取失败：顶部/底部 horizon 缺失。")）；grids None→"survey/registration 不可用或体数据未就绪，无法对齐 horizon."；surfaces None→"horizon 对全部倒转或无效，未生成切片."；labels `k={f:.2f}`。
- `ExportWorker`：V2 域导出（flac3d/abaqus/obj/stl/vtp）或 legacy GridSpec；`AdvisorWorker`：check_boreholes/check_coplanar_faults。
- 承接：【延后】geoviz 3D 几何核属 M8；demo 数据合成器 Qt-free 可 oracle。

## filter_index.py（407 行）
- 常量：CATEGORIES 14 词条（全部=None…）、AUXILIARY_TYPES、ISSUE_STATUSES、_STATUS_LABELS（indexed 已索引/parsed 已解析/missing 缺失/warning|failed|ready 借 tokens/error 错误/generated 借 TASK_STATUS_LABELS[complete]）。
- `FilterQuery` dataclass（node_type 词表含 entity/entity_group；tags+tag_operator and|or；review_status；entity_asset_ids frozenset；entity_role；asset_id）。
- `FilterIndex`：rebuild（视图回用 token=(project_root,enricher)；caller views 胜；last_rebuild_view_builds=0 无变化 #1063）；filter_query（needle in haystack lower）；`_matches_query`（trash 视图独占；stage/stage_any(csv)/type(other 组语义)/auxiliary/tag(normalize_tag_name)/integrity/review_status/legacy_category(ExportArtifact 排除)/entity(交集)；次级 stage/type/tags(and⊆|or∩)/integrity/review_status）；`_haystack` 20 字段 join lower；`compute_catalog_counts`→CatalogCounts（stages/types/tags/integrity/categories/review_status Counter；legacy categories 只数 resources；integrity_known 默认 True）。
- 承接：【核+薄】**纯逻辑索引/过滤/计数——Qt-free 完整 oracle 面**（与 catalog normalize_tag_name 对接）。

## media_preview_widget.py（412 行）
- `MediaPreviewWidget(QWidget)`：QtMultimedia 懒加载（#951 SIGSEGV 规避；_load_media_classes 缓存含失败；PEP 562 重导出）；`_ensure_player`（不可用→"音频预览不可用"+播放禁）；set_media_path（空→"未加载"；就绪→"就绪"；autoplay→播放）；`_toggle_play`（播放|暂停文本）；`_show_fallback`（InvalidMedia/error→隐藏控件+`缺少系统解码器，无法播放：{name}`+路径可复制）；`_ms` mm:ss；hideEvent stop；apply_settings（autoplay/volume）。
- 承接：【Qt】QMediaPlayer 直译（懒初始化契约保留）。

# 16 — Findings 第 6 批：pages 111-114

## relink_dialog.py（430 行）
- `_entry_status`：relinkable→"可重链接"、managed→"需重新导入"、否则 "不支持重链接"。
- `RelinkSourcesDialog(QDialog)`：缺失源扫描（find_missing_sources stat-only）+单个/目录批量重链接（fail-closed：sha256 或 size+mtime 指纹证明身份，`CatalogRelinkIdentityError` 按行留缺失）；表 5 列（数据/阶段 `_STAGE_LABELS`/类别 托管|外部/记录路径/状态）；summary `共扫描 {n} 个版本，缺失 {m} 个，其中可重链接（外部 RAW）{k} 个` / `…未发现缺失源`；目录重定向无同名→"所选目录中没有与缺失源同名的文件；未做任何改动。"；结果 `成功重链接 {ok} 个[，拒绝 {n} 个（身份无法证明或发生错误）+前8条原因+… 共 N 条]`；空态 "未发现缺失源","全部版本的数据源均可正常解析。"；双 OwnedWorkerJob（扫描/重链接各一，关窗才 shutdown——job 纪律）；explicit _busy 标志（is_running 排空期误判防）。
- 承接：【Qt】依赖 catalog.sources（C++ catalog 无 relink；M4 域）。

## data_detail_panel.py（434 行）
- `PdfPreviewPanel(QWidget)`：基准 420x560×factor（1.25 步进 10%-800% 钳制；边界处不重渲染）；翻页保持 factor；Ctrl+滚轮（viewport eventFilter+wheelEvent 双路）；`{page+1} / {count}`；document parenting 归 preview（防泄漏）。
- `DataDetailPanel(QFrame)`：详情卡（update_asset：None→"请选择数据项"+"从列表中选择一个数据、成果或文件"+"暂无预览"；ResourceItem→5 行元数据（类型中文化/格式/状态/路径/校验 "—"）+preview_for_resource 分派（image 220x160 缩略/PdfPreviewPanel/text|table mono 行/其余 muted 行/warning 行）；ExportArtifact→名称=末段/类型 成果/关联；未知→"未知数据项"+str(asset)）；`show_downstream_impact`（前 20 行 `· {label} — {state}`，STALE→WARNING 色）。
- 承接：【Qt】QPdfDocument/QPixmap 原生；preview_strategy 纯逻辑已单列。

## map_edit_items.py（447 行）
- 常量：WELL_RADIUS=0.4、VERTEX_HANDLE_HALF=0.35（world-size；像素拾取由 scene 处理）、各画笔/填充 token 色（相带 PRIMARY α70、井 TEAL、线 ACCENT cosmetic 2、注记 TEXT_DARK z=30）。
- `FeatureItemMixin`：feature_id/kind/topology_status + to_record/get_property/set_property/set_topology_status（空→ok）。
- `VertexHandleItem(QGraphicsRectItem)`：场景管理非要素，Z=100，(part,ring,index) 寻址。
- `FaciesPolygonItem(QGraphicsPathItem)`：canonical_facies_geometry 归一（Multi 支持）；`has_complex_geometry`（非 Polygon 或 ≠1 part/1 ring）；`coordinates()`=首外环；all_rings/iter_ring_addresses/ring_coordinates（越界→[]）；set_ring_coordinates（归一失败静默返回）；set_coordinates（仅换首外环保其余环）；translate_by（顶点平移+setPos(0,0)——几何持久持有，item pos 恒零）；`to_record`（compact_facies_coordinates+geometry_type+geometry+style+topology_status+extras(facies/probability/region_id/properties)；无 facies 有名→facies=name）。
- `WellPointItem`（椭圆 radius 0.4）、`LineItem`（polyline）、`LabelItem`（text|name 显示，name=name|display）。
- 承接：【Qgs】QgsVectorLayer+QgsMapTool 原生编辑承接目标；to_record 往返契约（canonical_facies_geometry 在 mapping.geometry_schema——C++ 侧无）。

## map_attribute_table.py（461 行）
- `_FeatureSelectorList(QListWidget)`：QComboBox 兼容访问面（currentData/findData/itemText/setCurrentIndex）；有界窗口 _MAX_VISIBLE=500；占位行 key=""（"— 未选择 —"）。
- `MapAttributeTable(QFrame)`：底部属性格；搜索框（200ms 防抖有焦点/无焦点立即；按 展示文本|要素 id 过滤）；`apply_filter(field,needle)`（properties[field] 回退顶层键，子串不区分大小写；选中被滤掉→set_feature(None)+feature_selection_requested("")——map 高亮同步 R3-P3；返回可见 ids）；`sort_features`（"" 恢复绑定期序）；`set_layer_features`（id→dict 绑定；选中置顶 pin；id 集变化走全量）；`update_layer_features`（差量 C-P0-3）；`set_selected_ids`（O(1) 不重建）；`_rebuild`：_DISPLAY_KEYS（id/kind/name/text/topology_status；topology warning→"警告"；name/text 可编辑其余只读）+geometry 行（`{n} pts`/`({x}, {y})`/empty/str）；`property_changed(feature_id,key,value)`。
- 承接：【Qgs】QgsAttributeTable/QgsDualView 原生对应；置顶窗口/差量语义自研。

# 16 — Findings 第 7 批：new_project_wizard + preview_worker

## new_project_wizard.py（502 行）
- `_AnalyzeWorker`：analyze_data_folder(data_dir, project_name, engine) on OwnedWorkerJob。
- `NewProjectWizardDialog(QDialog)`：两步向导（设置→分析与预览，QStackedWidget）；step1 校验链文案：请输入工程名称/请选择原始数据文件夹/数据目录不存在/请选择中间文件目录/中间目录不存在/工程文件已存在（目标=`{inter}/{name}.paleo.json` 已存在即拒）；浏览数据目录时名称空→自动填目录名；同目录 checkbox 控制中间目录行显隐；step2：分析中 "正在分析数据文件夹…"+0..0 进度；成功 summary=`导入 {n} 项 · 井 {n} 口（{n} 有坐标） · 地震 {n} 个 · 地质实体 {n} 个`（与 OnboardingReportCard 同构）；by_type 表高贴合（封顶 260）；issues+warnings 前 20 行 browser；嵌 WellMapPanel（refresh_domain 吞异常）；失败 `分析失败: {msg}` finish 禁用；上一步/取消/关闭均 shutdown(wait_ms=0)；`result_document` property。
- 承接：【Qt】M2 C++ newProject 已有后端核（bootstrap）；向导壳 Qt。

## preview_worker.py（523 行）
- 常量：MAX_CACHED_MEDIA_BYTES=512KiB、MAX_PRELOAD_MEDIA_BYTES=64MiB。
- `_CacheEpoch`：RLock 代际（advance/write_if_current/is_current）——清缓存 vs 在写 worker 串行化。
- `snapshot_asset`：model_copy(deep) | deepcopy——worker 不共享可变工程状态。
- `needs_media_preload`（path 有而 image/pdf bytes 空）、`preload_media`（≤64MiB 读 bytes，OSError 吞）、`cacheable_result`（>512KiB media bytes 剥离后入 LRU；geoviz 原样）。
- `_PreviewWorker`：request_kind≠summary 且 disk_cacheable→先盘缓存；构建→preload→store（commit_guard=epoch）；失败 `{exc}\n{traceback}`。
- `PreviewRequestController(QObject)`：单 worker latest-only pending 槽（generation 门）；stale 代不进 UI/LRU；request(None)→同步空结果；cache hit+needs_media→_MediaPreloadWorker（path-only 缓存重读）；set_comparison_crs 变化→清 LRU+invalidate；set_settings 变化→代际+清缓存；invalidate；shutdown（无强杀，两段有限等合并总 deadline）；线程结束后 QTimer.singleShot(0) 泵 pending（#951 offscreen 段错误规避）；`ValueError(f"unknown preview request kind: {k}")`。
- 承接：【核+薄】请求编排纯状态机（generation/epoch/pending 语义）可 Qt-free 部分 oracle；线程壳 Qt。

# 16 — Findings 第 8 批：seismic_prediction_page … tag_widgets

## seismic_prediction_page.py（594 行）
- `SeismicPredictionPage(QWidget)`：地震预测工作台（context_toolbar | 属性面板|视图|控制面板 sizes 280/900/280 + FloatController seismic:attribute/control——**GL 视图从不注册浮动**（GL viewport 跨窗 reparent 脆弱））；`_sync_seismic_sources`：SEG-Y 资源过滤（type=seismic 且 format∈{sgy,segy} 或路径后缀；label `f"{name} · {FMT}"`）+选中保持；`select_seismic_resource`（显示选中源覆盖活动任务）；`_on_run`：未绑工程/未连目录→QMessageBox；无生产模型→"未配置生产模型，无法运行科学预测。\n请先注册生产模型（ModelRegistry），或通过「运行演示预测」查看演示结果。"（P2 §3d 不自动 mock）；`_on_demo`：MODEL_ID_DEMO 未注册→`演示模型未注册: {exc}`；`_start_inference`：InputContractError→`输入不满足模型契约: {exc}`；完成（run failed→`推断失败: {error}`；materialize_prediction_task+link_run_to_domain_task 失败记 model_metadata.link_failed=True 不静默 H3；prediction_updated）；shutdown_workers（不可 join→False 保留旧会话）；session_token 项目切换失效；tab 链 14 控件。
- 承接：【核+薄】推断编排（模型解析/输入契约/异步完成语义）+【Qt】布局；C++ 平台已可跑属性（rms 等），预测线延后。

## ingest_plan_dialog.py（598 行）
- `IngestPlanDialog(QDialog)`：两阶段（build_ingest_plan worker→可编辑计划表→execute_ingest_plan worker 可取消分块幂等）；`_DECISION_LABELS`（pending 待定/accept 接受/skip 跳过/as_new_version 作为新版本）；`_status_display`（重复→"⚠ 重复"、ambiguous→"? 待确认"、skip→"跳过"、else "✓"）；9 列（状态/文件/类型/实体（推断）`{新建 }{label} ({confidence})`/置信度/角色/主用 ✓/决策/备注 `重复: {id12}`）；摘要 `共 {n} 个数据项：接受 {a}，重复 {d}，待确认 {u}，文件族 {b}——选中行可在下方修改决策/角色/实体/主用`；完成 `导入完成：登记 {n}，跳过 {n}，绑定 {n}，新建实体 {n}，问题 {n}`+已取消注记 "（已取消——已完成分块保持一致，可重新执行）"；未确认项执行前 Yes/No 确认（"仍有身份待确认的文件（将按当前决策执行，未确认项默认跳过）。继续吗？"）；全部接受/待确认设跳过；_ItemDetailPanel（决策/角色 roles_for_entity_type/实体（不绑定|井|调查|候选|新建 __new__→strategy=manual confidence=manual）/主用）；`_teardown_worker` 协作停（超时不销毁线程——UB 防护，finished→deleteLater 兜底）；`choose_ingest_root`。
- 承接：【核+薄】依赖 resources.ingest_plan（纯服务）；对话框 Qt。

## pdf_preview_widget.py（620 行）
- `PdfPreviewWidget(QWidget)`：QPdfView 主路+三栈（view|fallback_image 消息|fallback_scroll 连续页渲染）；QPdfDocument/QPdfView 缺失降级（"PDF 预览不可用"）；zoom 10%-800% 1.25 步进（边界 no-op 防死循环）；fit page|width|custom（zoom in/out 进 custom）；pdf_bytes→QBuffer 加载（_source_buffer 生命周期）；加载状态机（Loading pending→"PDF 预览加载中…"；Error/页 0→"PDF 预览加载失败"）；`_render_fallback_pages`（按宽渲染全部页；A4 默认高比 1.414；首页失败→"PDF 页面渲染失败"；滚动中点→页码）；Ctrl+滚轮；`_copy_all_text`（getAllText 逐页 join，>1e6 截断，按钮 "已复制"/"已复制（已截断）" 1.5s 恢复——parented timer #951）；`{page+1} / {count}`。
- 承接：【Qt】QPdfView 原生；降级/状态机语义保留。

## data_asset_table.py（672 行）
- `DataAssetTable(QWidget)`：资产总表（chips+列设置菜单+QTableView+AssetTableModel/PagedAssetTableModel 双模）；update_assets（物化重建必出 paged 模式；index.rebuild 视图回用；列自动适配仅在首填/列集变化，≤4000 cells 全量量宽（>300 钳 300）否则固定 120，用户拖宽豁免 #894-1；last_sort 重应用 #850-1；选择收缩通知 #850-2）；`update_paged(provider)`（SQL 页模；不可映射查询→exit+paged_mode_unavailable #1142 回落物化过滤重建）；set_filter_query/set_search_text（strip().lower()）/chip 维度移除（dataclass replace 逐维）/apply_saved_filter（采纳保存的 search_text）；set_visible_columns（required 恒在；空→["name"]）；`_on_header_clicked` 显式排序（禁内置 sorting #850-1）；`_sync_selection`（key=(kind,id) 恢复；paged 用 row_for_key）；context_menu_requested（单/多选 target）。
- 承接：【Qt】核心表交互契约多（#850 系列/#894-1/#1142）；paged 模式依赖 conv-15 分页（C++ search_assets_page 已有！）。

## version_workbench_dialog.py（681 行）
- `_stage_display`（trashed→"已删除"）、`_checksum_display`（sha256[:12] 或 "—"）、`_short_id`（≤keep）、`_json_text`（sort_keys indent2）、`_value_display`。
- `_VersionCompareDialog`：4 列（字段/vN/vM/结果 同|异红）；行=阶段/大小 format_size/校验和/格式/创建时间[:19]/生成 Run/并集元数据 `元数据 · {key}`。
- `VersionWorkbenchDialog(QDialog)`：单资产版本时间线 newest-first 7 列（`v{n}（当前）`/阶段/校验和/大小/生成 Run/时间/源 托管|外部；trashed 前景置灰）；`reload_versions`（服务读不缓存；CatalogError→"该数据资产已不存在（可能已被彻底删除）"；未连接→"未连接数据目录（请先打开项目）"；header `{name} · {type} · 当前 v{n}`+`共 {n} 个版本`）；详情（父版本 id join/`生成 Run: {op} · 状态 {s} · generator {g} · {t}`/run 参数 JSON/记录路径/解析位置（缺→"解析位置: 源文件缺失"）/元数据 JSON）；动作门控（promote/trash 非回收站、restore 回收站、compare 恰 2 行、open 载荷存在）；promote 走 OwnedWorkerJob（载荷复制+sha256+fsync 无界）；confirm 默认 No；成功 reload+versions_changed。
- 承接：【Qt】依赖 catalog.service（C++ CatalogRepository 对应——版本/promote/trash 在 B 线已有）。

## data_reader_panel.py（705 行）
- `DataReaderPanel(QFrame)`：预览宿主（13 模式分派表 `_mode_handlers`：empty/message/text/table/well_log/seismic/image/pdf/rich_text/web_document/json_tree/geotiff/media）；render 分派（visualization_available→LazyTabs 摘要；geoviz+PreparedPreview→host.render（异常降级 message）；geoviz 非 Prepared→降级 "预览不可用"）；`show_loading`（`加载中… {name}`/"正在生成预览…"）；_merge_warning（" · " join）；表截断上浮 warning（#850-5）；表格复制工具栏（copy_all+截断注记追加+"已复制" 1.2s 恢复）；图片缩放工具栏（fit/±/"{pct}%"）；`_meta_text`=`{type_label} · {format} · {status} · {path}` 非空 join；懒建 WebDocument/Media 控件（#951）；release_engine_widgets；右键 "用系统应用打开"。
- 承接：【Qt】预览面板骨架；模式分派表结构清晰可 C++ 直译。

## lineage_explorer_dialog.py（708 行）
- `LineageExplorerDialog(QDialog)`：单版本血缘浏览器；懒树（每次展开恰一跳 get_lineage；OUTPUT→⚙Run→INPUT 交错习语）；硬上限 MAX_CHILDREN_PER_NODE=200/MAX_EXPAND_DEPTH=25/MAX_EXPAND_NODES=1000；断链父 id→红 "⚠ 断链: {id}"；循环→"↺ 循环引用: {id}"；溢出→"…还有 {n} 个（未展开）"禁用行；展开至 RAW 根（BFS 迭代，RAW 停，超限 "⚠ 展开至 RAW 已停止：达到保护上限（深度 ≤ 25，节点 ≤ 1000）"/成功 "已展开上游至 {n} 个 RAW 根（共 {m} 个上游版本）"）；定位（空→"请输入版本 ID"；未知→`未找到版本：{id}`；无服务→"未连接数据目录（请先打开项目）"）；摘要卡（`{icon} {name} · v{n} · {stage}`/`ID: {id} · 校验和: {cs12}… · 创建于: {t} · 受管 (Managed)|外部 (External)`/路径+缺失 "　⚠ 源文件缺失"）；run 卡（"无生成运行"/`⚙ 生成运行 · {op}`）；version_activated 双击/定位。
- 承接：【Qt】依赖 catalog lineage 读模型（C++ M4 lineage 已有）。

## tag_widgets.py（712 行）
- `parse_multi_tag_input(text)`：分隔符 `[,，;；\s]+`；strip+# 剥离+截 128+有序去重（纯函数 oracle）。
- `TagBadge`（#{name}+x 按钮）、`TagContainerWidget`（+标签；add 弹 TagInputDialog）、`TagInputDialog`（空→"标签名称不能为空"；重复（lower）→"该标签已存在"；get=strip().lstrip("#")）、`BulkAddTagDialog`（空→"请至少输入一个有效的标签名称"）、`BulkRemoveTagDialog`（并集勾选）。
- `TagManagerDialog(QDialog)`：标签治理（CRUD/重命名/合并/删无用/清理全部无用）；3 列（标签/Asset 使用数/Version 使用数；display casefold 排序）；搜索 200ms 去抖；服务失败如实上浮（`标签统计加载失败: {Cls}` #897 不再伪装空表；`标签搜索失败: {Cls}`）；未连接→"未连接数据目录 — 标签管理不可用"；重命名 stale 行→`标签 "{old}" 已不存在，请刷新后重试。`；冲突→合并询问；删在用→`标签 "{n}" 仍关联 {a} 个资产、{v} 个版本，无法删除。`；清理确认 `将删除 {n} 个未使用的标签，继续？`（计数用全表非过滤行）→`已清理 {n} 个无用标签`；双击→tag_selected。
- 承接：【Qt】依赖 catalog tag 服务（normalize_tag_name C++ 侧 name_search 折叠已有近亲）。

# 16 — Findings 第 9 批：visualization_page … navigation_tree

## visualization_page.py（751 行）
- `VisualizationPage(QWidget)`：可视化页（临时横幅 "临时页面 —— 用于验证可视化能力，正式版将并入数据 / 井 / 地震 / 编图各页"；顶栏 资产 combo+坐标切换 ◆网格(IL/XL)|◉地理(X/Y)（仅改自身标签，坐标传播在 3D 页）；summary 隐藏|composite 中心|trace 右栏 sizes 1000/260 + FloatController visualization:trace——composite 中心从不浮动（native view reparent 脆弱））；asset combo 签名门控重建（V6：ref 元组签名；图标前缀 ▤ well_log/◉ map/✦ 其他）；首开探针缓存（probe_signature；首个 is_file 的 well_log 自动打开）；`open_ref`（engine_preview→PreviewRequestController；well_log→_open_well_log LRU 命中同步/冷载 worker latest-wins _load_seq；其余 resolve→composite.load_payload+trace）；失败 payload `井数据加载失败: {msg}`；`_refs_match`（kind+id+path）；导出（caps 门控 "当前 Tab 不支持 {L} 导出（可用: {caps}）。测井 / 连井 / 古地理支持矢量 SVG/PDF."；PNG UnifiedMapCanvas worker 路径（"上一张地图仍在导出"/"已导出视图: {n}"/"已取消导出"）；矢量同步 WaitCursor "正在导出 {L} …"）；建议名 `{safe64}_{tab}{suffix}`（非 [A-Za-z0-9-_]→_）；_project_stub（无工程合成 _viz 文档）；DeferredDelete 也 shutdown。
- 承接：【Qgs/延后】viz hosts M8；分派/导出/签名缓存语义可借鉴。

## module_relationship.py（764 行）
- `ModuleCard`（标题+条目+输入 `<b>输入:</b> a, b`+输出+PwbBadge；_STATUS_TONES complete success/running primary/pending neutral/warning warning/failed error；set_status 缺省 "待开始"）、`DatabaseModuleCard`（子卡行 SubCard：SVG 图标+标签；StyleChange 事件重染图标——不走 style.bind 注册表因 bound-method 强持有 teardown 不安全）、`_LegendLine`（QPainter 线样 solid/double/dashed/rect）、`LegendWidget`（4 线样图例：主要数据流/双向交互/数据供给/模块内部输入输出）。
- `ModuleRelationshipCanvas`（MIN_CANVAS_WIDTH=1080；grid 90/65 间距；6 卡：地层格架构建(page4)/单井相智能分析(2)/地震相智能分析(3)/岩相与沉积相分析(5)/古地理图编制(8,accented)/多源数据管理(数据标准化1/质检管理9/版本控制1)；`update_states(steps)`：data_check→数据卡、factor_map→格架、prediction→井+地震、map_compile→岩相、qc→编图；paintEvent 每帧读实时 geometry 画 5 组箭头（draw_directed_arrow：1.5px 线+7px 箭头+多行标签 top/bottom/left/right 锚位；双线/虚线 ACCENT）；点击→navigation_requested(page_index)）。
- `ModuleRelationshipWidget`：canvas 包装+卡片属性透传。
- 承接：【Qt】自绘导览画布（无数值核）；页面映射表 oracle 面。

## project_well_map_page.py（820 行）
- `WellListModel`（name+flag 显示 `f"{name}{flag}"`、tooltip=name、UserRole+1=well_id；well_id_at/row_for_well）+`_WellFilterProxy`（不区分大小写子串）。
- `ProjectWellMapPage(QWidget)`：工程井位 GIS（geoviz XY_SCATTER widget；7 series：boundary 虚线/survey_extents 点线/reference_layers/wells(PRIMARY 6px)/wells_flagged(WARNING)/wells_selected(ACCENT 9px)/spatial_cursor(CANVAS_CURSOR 11px)；引擎不可用→fallback QLabel "geo-viz-engine 不可用，无法渲染地图"）；§24 性能契约（单批次散点/模型视图列表/引擎级视口操作；域变更才重建数组）；`_rebuild_cache`：参考井排除（is_reference_well）、project_x/y 优先回退 surface、NaN 剔除、OK 块在前 flagged 在后（稳定布局+row↔array 双映射）；`_render_all`（CRS label `工程 CRS: {c|未设置}`）；井名标注开关；参考图层顶点预算 MAX_REFERENCE_VERTICES=20_000（超限降采样防冻结；不可读层记 `_reference_errors` 不绘制）；§20 CRS 警示幅（边界/工区 crs_equivalent 不匹配→"⚠ …未叠加" 汇总横幅，扣留必须可见）；survey 角点 complete_survey_corners 闭合；hover `{name}  X: {x:.2f}  Y: {y:.2f}{（源坐标显示）}`；点击/双击→well_selected/well_activated；select_wells（列表↔地图双向；_sync_list_selection 断信号重连防回环）；`show_spatial_cursor`（"地震光标  X: … Y: …"）；zoom_to_selection（finite 钳制+15% margin）。
- 承接：【Qgs】井位图层在 C++ 由 QgsMapCanvas+QgsVectorLayer 承接（M2/M4 已有井位地图路径）；§20/§24 契约保留。

## navigation_tree.py（898 行）
- `NavigationTree(QTreeWidget)`：IA 3.0 树（全部数据/回收站/工区概览/◉井/◈地震/◆其他参考井/地质解释/辅助资料/工作数据/成果/生命阶段 4 叶/数据类型 13 叶/标签动态/状态与完整性 4 叶/治理·审核状态动态）；节点 UserRole=FilterQuery、UserRole+1=legacy key（成果节点 legacy key=stage=output 值而非 "成果" 标签——防 human label 覆写过滤）；`_rebuild_entity_groups`（参考井/测区井分组；O(L) 链接预扫 well_links；unresolved " ⚠"/invalid_coord " ⚠坐标" 旗标；每井计数；地质实体计数；清空重建防重复）；分页实体（#1046 ENTITY_PAGE_SIZE=500；"▣ 显示更多（已显示 {n}/{m}）"；选中实体按需物化（Map→Data 从不因分页失败））；井文件叶（MAX_WELL_FILE_CHILDREN=30；V11 角色分组 `◧ {display} ({n})`+文件 `▤ {label}`（asset_label_provider）+溢出 `…另有 {n} 个文件`）；`update_counts`（compute_catalog_counts；递归刷计数 label_base=文本 rsplit 空格；辅助/工作数据域计数）；`_update_tag_nodes`（#{name} {n} 排序；选中保持/被删回全部 #656）；`_update_review_nodes`（REVIEW_STATUS_LABELS 4 值）；context（标签组头 "管理标签"；井行 "删除井…"→delete_well_requested）；`_on_current_changed`（域节点只发 filter_query_changed 不发 legacy category——防 clobber）。
- 承接：【核+薄】**树结构/计数/过滤语义大部 Qt-free（FilterQuery+counts）**；QTreeWidget 壳。

# 16 — Findings 第 10 批：seismic_view_panel … geological_modeling_3d_page（五大文件收尾）

## seismic_view_panel.py（1209 行）
- `SeismicCursorGate`（纯逻辑可 oracle：min_interval_ms=30 或 |Δil|>1 即发布，clock 可注入）。
- `SeismicViewPanel(QFrame)`：geoviz SeismicView 嵌入；空态 "未选择预测任务"；解释生命周期行 6 按钮（开始层位解释/同步拾取→草稿/撤销/重做/保存解释版本/重开解释，状态行文本 `解释草稿 {k}（{n}×{m}）— …`/`已写入 {n} 个网格节点 · 草稿状态: {s}`/`已保存版本 {id14}… ({msg})`/`保存失败: {msg}`/`未绑定工程，无法保存解释版本`/`工程中尚无层位解释`/`解释网格与当前数据体几何不一致，已取消载入`）；NaN=未解释基线（np.full nan，从不 0ms）；profile 模式（enter/exit 幂等+首进几何快照恢复；L5 方向 inline|crossline|time 徽章 `{Inline|Crossline} 剖面`/`Time 切片`；set_profile_orientation 未知值 False 拒绝）；游标生产（引擎 cursor_moved_3d→survey 值→notify_cursor 门控）；井迹叠加 fail-closed（reason: no-coordination-hub/no-volume）；`depth_slice_unavailable_reason`（twt-domain-volume 拒绝伪造深度）；#1079 派生 zarr 自动切换；`show_resource`（非 seismic→"所选资源不是地震数据"；ref None→"所选资源不支持地震体可视化"；无 payload→message 或 "无法加载地震体数据"）；`update_state`（task None→空；horizon=model_metadata.target_horizon 回退 project.stratigraphy）；shutdown/cleanup 双路径（DeferredDelete 也触发）。
- 承接：【Qgs/延后】3D 地震视口属 M8 范围（C++ seismic_viewer 承载 2D 切片）；解释生命周期/游标门控语义可移植。

## map_edit_scene.py（1309 行）
- `MapEditScene(QGraphicsScene)`：4 信号（selection_ids_changed/document_dirty_changed/command_stack_changed/topology_issues_changed）；6 工具（select/move/vertex/facies/line/label）；像素容差族（snap 8/edge 8/handle 4/feature 8 屏幕像素经 _units_per_pixel 转场景单位，无视图→1.0）；EditCommandStack(max 50)+edit_history 审计（op/action/ts/ids，封顶 200）；`load_document`（坏几何跳过）；顶点编辑 API（apply_set/insert/delete_vertex，RingEditCommand 寻址不塌兄弟洞）；拖拽=视觉预览（item.setPos），release 才经命令提交几何；双击线工具=结束草稿、vertex 工具=边插入（closest_edge+容差²）；键盘 Enter 结束/Escape 取草稿/Delete 删活动顶点；`refresh_topology`（per-item 缓存+邻接警告 gap_tol=0.5 世界单位独立于像素 snap）；`validate_for_save`（任何 error→False）；dirty 语义 #894-3（undo 到基线不脏；深度帽溢出恒脏）；捕捉索引按 MapSnapManager.build_count 重建；LOD 导航绘制（drawItems 画包围盒替身，仅显示层）；_cancel_vertex_drag 恢复按 (part,ring) 寻址（修洞环静默损坏）。
- 承接：【Qgs】QgsMapTool/QgsVectorLayerEditBuffer 原生承接目标；命令栈/容差/拓扑门禁 Qt-free 可 oracle。

## stratigraphy_correlation_page.py（1524 行）
- `StratigraphyCorrelationPage(QWidget)`：三栏（井选择 200|剖面|操作 200，sizes 260/940/260 + FloatController stratigraphy:wells/actions——中心 CrossWellHost 不浮动）；井清单键差分（resource id 签名；移动不重建）；`load_section`（未选自动勾前 4；CorrelationLoadWorker max 8；完成 `已加载 {n} 口井 ({path})[；警告 {n} 项][；notices 前2]`/失败 `未能加载任何井曲线：{detail}` /`加载失败: {msg}`/取消 "加载已取消"）；工具条（浏览/拾取/连线互斥；formation combo；snap 不吸附|波峰|波谷；DTW 传播/撤销/重做/自动连线/分层顶线 checkbox/间距 50-300）；DTW 流（无拾取→"请先在拾取模式下添加一个参考拾取点"；无关联井→"参考拾取点没有关联井"；运行中再点=协作取消 "正在取消 DTW 传播…"；进度 `DTW 传播中… {d}/{t} 井（再次点击可取消）`；完成 `DTW 已为层位 {f} 生成 {n} 个建议拾取 ({置信度})（点击接受 / 右键拒绝）`；置信度 `置信度: {c:.2f}`/不可用 sentinel ≥999→"置信度: 不可用" 不显示 0.00）；engine/legacy 双径（Legacy 时引擎计划仍构建做 parity）；解释版本生命周期（保存解释版本/打开已保存解释/恢复已保存版本/链接编辑…；未配对井名拒绝保存 "井名与资源 id 配对不一致，已取消保存。请重新加载连井剖面."；noop_unchanged→"科学内容未变化，未创建新版本"；状态 `解释: 已保存 {id}（{msg}）`/`解释: 当前 {id} / {n}`/未保存/未绑定工程）；导出（无 tops→"没有分层顶数据"；engine 抓屏失败 "WellLogEngine 抓屏失败"；CSV/PNG/SVG/PDF 经 CrossWellExportDialog：svg 忽略 dpi、pdf 无纸张时宽度可用）；clear 全复位 "剖面已清空"。
- 承接：【延后/核+薄】viz CrossWell 属 M8；well 加载/版本生命周期/DTW 编排语义可移植。

## mapping_page.py（2599 行）
- `MappingPage(QWidget)`：GIS 壳编图页。命令条=MapActionController QAction 注册表（分组 pan/zoom/identify/编辑/选择/拓扑等 40+ id；hidden shim=MapEditToolbar）；MapDockManager 左右图标栏 dock（layers 左默认开；reference 右开/chrome 右关/composer 右关；bottom 底部 220 高帽）+面板菜单+FloatController FLOAT_KEYS 5（中心画布栈永不注册——视口不离 splitter）；中心栈 MapEditView|预览宿主（preview_canvas_stack=MapCanvasPanel|unified_canvas=display_canvas）；dock 分割器尺寸持久化（_DOCK_SPLITTER_KEY；showEvent 首显恢复）。
- **FactorGrid.statistics 承接点（本任务锚）**：`_sync_composition_bindings`（:893-926）遍历 factor_map_tasks，`descriptor = task.grid_metadata or {}`、`stats = descriptor.get("statistics") or {}`，min/max 缺一跳过；色带 get_color_ramp(task.parameters.color_ramp|viridis).stops 失败回 `_FACTOR_RAMP_FALLBACK`；binding_context["factor.colorbar"]={title:`{task.name} ({unit|''})`.strip(),min,max,stops}→composition_panel.apply_bindings（取第一个任务 break——主色条绑定）。即：**Python 侧 statistics 消费=min/max 数值+unit 标题进组图色条**；说明性 min/max/mean 显示面在 workstation inspector.show_factor（grid 行 "10 ~ 220.5"/"0.5 ~ 3.25" 文案被 test_inspector_v7 钉死，subagent findings #3）。
- 其余要点：`update_state`（脏文档换 id→Save/Discard/Cancel 提示 #532；同 id 重推不重载保脏 #423）；`save_draft`（authoring 校验失败回滚深拷贝+定位首问题；拓扑门禁文案 "拓扑检查未通过（{n} 项问题）。已定位至首项几何问题，请查看底部拓扑面板修复后再保存。"）；工具重绑（活动层切换 _LAYER_BOUND/_KIND_BOUND #523）；`_sync_action_state`（ToolContext 全字段喂 canonical evaluator，checked 三态必须喂真值 R1-P1）；overlay 请求（参考层→显示；factor task id→scene_from_factor_task ScalarGridLayer+move_layer(0)）；属性表差量（C-P0-3：revision<<32+session.revision 缓存键，changes_since 增量/不可恢复全量）；导出（scalar 层 id=factor task id 作 lineage；跨工程切换拒登 "已切换工程，导出结果未登记到旧工程" #1223）；等值线 worker（完成 "等值线初稿：已生成 {n} 份并加载到编图。"/无网格 "没有可提取的单因素网格。请先在制备页生成单因素图。"/失败 tooltip+状态条双写 #843）。
- 承接：【Qgs】本页是 C++ 综合编修区的 Python 蓝本（qgis_bridge 硬依赖）；统计→色条绑定是 HUD 之外 statistics 的第二承接面。

## data_page.py（3154 行）
- `DataPage(QWidget)`：数据页主编排（7 个 OwnedWorkerJob：import/register/rescan/deliver/export/verify/domain_bind/catalog_copy/aggregates；_SHUTDOWN_WAIT_MS=5000 统一预算 C18）；布局=ResourceSummaryBar+DataToolbar+DataWorkspace；update_state（分页门 PAGED_MODE_THRESHOLD：SQL 页服务+树徽章 SQL 聚合+概览 "—" 不伪造 0 C-P0-1；物化路径共享视图一次构建 #527；trash 视图 companion 重建+计数）；导入链（import worker→register worker 分块+进度+协作取消→导入收据（发现/跳过/类型分布/登记成败/取消注记）→domain bind worker（GUI 线程绑定 bind_staged；工区识别摘要 "工区识别: 新增井 {n} 口、地震工区 {m} 个[，歧义待治理 {k} 项]"）→SEG-Y autostart transcode）；右键菜单门禁（catalog_version_id None→禁用+tooltip "…需要活动数据目录（数据未桥接）"；relink 仅 integrity MISSING；materialize 仅 external）；检查器血缘异步（AsyncQuery latest-only+epoch 迟到拒绝+LRU 32）；选择→context 发布（publish_asset_selection）；well 删除守卫（关联文件必须同步移出确认；文案 `井"{name}"关联 {n} 个文件：…`）；实体详情页（EntityViewService+staleness 后台）；标签全套（bulk/mirror 失败注记 "（数据目录同步失败，标签仅写入项目数据）"；候选按 normalize_tag_name 归一去重）；_resource_for_preview（catalog-only 行→只读 companion 重建+resolved_path）。
- 承接：【核+薄】编排/收据/门禁文案大面 Qt-free 可 oracle；worker 纪律（target=project 迟到拒绝）是 C++ 平台必须复刻的会话安全模式。

## geological_modeling_3d_page.py（3989 行）
- `GeologicalModeling3DPage(QWidget)`：井震联合 3D 工作台（左场景树|中 joint 3D+可折叠 2D 条；legacy 右轨隐藏由分析 tab 代理按钮转发）；offscreen GL 守卫 `_opengl_widget_supported`（QT_QPA_PLATFORM=offscreen→占位 "3D 渲染不可用：当前平台不支持 OpenGL（offscreen）"——C++ offscreen 测试同款纪律）；顶栏（域 Time|Depth（Depth 无变换→项禁用+tooltip "Depth 不可用：缺少时深转换…"；被拒回滚场景实际域）/3D 模式 正交切片|三维体/切片位置/分析/交互 选井两点|画线吸附/井 A/B/井间剖面/删 active/从工程刷新/透视|俯瞰|复位相机预设）；切片卡（IL/XL spinbox+Time 选择器/编辑/显示/删除/新增/透明度 10-100%/注记 未加载|Depth·Time 已隐藏|{n}/8；scene 恢复 OrthogonalSliceState+pending survey 编号映射一次）；分析 tab（等时切片：顶/底 horizon .dat 或解释版本（"interp",path）+比例 ¼½¾ 等四选+演示 checkbox（诚实：无体且未勾选→"未加载体数据：无法生成地层切片。可勾选…"，worker 无 parent C17）；井震标定代理 slider 双绑+150ms 防抖重建；沉积相 RGB/交会代理；导出与诊断代理）；颜色卡（地震 蓝白红|灰度|红白蓝、GR viridis|cividis|plasma|turbo 渐变图标、井宽 2-10px；JointDisplaySettings 持久化）；3D 井拾取（点击/拖线 eventFilter；>25px²=拖动让给相机；Esc=半选取消→pop_fence_well； pierce 点命中→append_fence_well+well_selected）；V5 Geo3DWorkspaceController（建模合成 demo ingest+"建模完成 (demo): 井 {n} · 隧道 {n} · 断层 {n} — 已渲染至三维视口"；register_modeling_run DataRun 溯源（demo 源 synthetic/demo 无版本）；网格导出 V2 域对象+export_status 行 "导出成功：{path}"/"网格模型导出失败：{err}"；Auto-Tie 真互相关 `互相关系数 (Cross-Correlation CC): {cc:.3f}`）；`collect_joint_analysis_state`/`save_joint_analysis_to_project`（树勾选/井可见性/域/fence/切片全量持久化）；跨页 sink（highlight_well/focus_seismic_position/highlight_interpretation）。
- 承接：【延后】M8 3D viz；demo 诚实标注/会话持久化/offscreen 守卫是 C++ 必抄纪律。

# 16 — Findings 补遗：合并时遗漏的 18 个 pages 文件（同样全文阅读）

## boundary_panel.py（105 行）
- `BoundaryPanel(QFrame)`：初始岩相边界右栏表单（min220/max352）；概率阈值 QDoubleSpinBox（0-1 步 0.05 默认 0.55 两位）；边界平滑 combo（tokens.SMOOTHING_LEVELS 默认 "中"）；最小图斑面积（0-10 km² 步 0.1 默认 0.5 后缀 " km²"）；相带占位 label "三角洲前缘砂体 · 分流间湾泥"；生成按钮 "生成初始边界并送入编图"（Primary，tooltip 生成初始相带边界）。QSS 经 style.bind（_field_label_sheet/_field_control_sheet）。
- 承接：【Qt】表单面板；默认值/范围 oracle 面。

## composition_panel.py（941 行）
- `CompositionPanel(QFrame)`：组图创作面板（P0-D）；模板 combo（TEMPLATE_LIBRARY label（desc））+新建；撤销/重做/保存JSON/打开JSON；组件列表（右键 锁定|显示/隐藏|复制|置顶|置底；倒序显示=绘制序；label 后缀 "（锁定）"/"（隐藏）"；未知类型前向兼容 `{raw}（未支持）`）；＋组件菜单按 registry 分类；属性编辑器固定 5 行（图件标题/X/Y/宽/高 mm）+ schema 驱动动态行（property_schema：number→QDoubleSpinBox、bool→QCheckBox、choices→QComboBox、text→QTextEdit（FocusOut 提交 _schema_dirty）、list→label/value 表格编辑器（仅 STAT_CHART series 且 `_series_is_label_value`——条目含额外键退化 JSON 框）或 JSON QLineEdit；chart_type 变更延迟重建表格）；锁定元素 session 层拒绝（ComposerError 吞）+lock_hint "组件已锁定（右键解锁后可编辑）"；预览 render_to_svg→QSvgRenderer（失败 "预览渲染失败"）；导出 png|svg|pdf+DPI 72-1200 默认 300（export_composition_reported 物理尺寸契约；composer_fallback 记 warning）；保存/载入 JSON（MapCompositionDocument.to_dict/from_dict）；`apply_bindings`（factor.colorbar 绑定解析）/`set_main_map`（绑定非 undoable 内容编辑）。
- 承接：【核+薄】session/registry/schema 纯逻辑 +【Qt】编辑器壳；composing 核在 mapping.composer（C++ 无）。

## contour_draft_worker.py（91 行）
- `ContourDraftResult`（drafts 列表+count）；`ContourDraftWorker(QObject)`：窄快照（ProjectDocument.new("_contour_snapshot") 仅拷 factor_map_tasks+contour_drafts——不深拷全文档 #850-6）；run：compile_contour_drafts_for_project(apply_to_map=False)→completed/failed(`{cls}: {exc}`)/cancelled/terminal（terminal 恒发）；`commit_contour_drafts(project,result)`：GUI 线程有界提交（upsert_contour_draft+apply_contour_draft_to_map 逐 draft）。
- 承接：【核+薄】快照契约+提交边界；等值线核已进 C++ mapping_kernel（contouring）。

## cross_well_export_dialog.py（82 行）
- `CrossWellExportDialog(QDialog)`：导出连井剖面选项（格式 svg|png|pdf；DPI 96|150|300 默认 150；宽度 0-20000 步 100 special "自然宽度" 后缀 px 默认 0=自然；纸张 内容尺寸|A4|LETTER）；`_update_enabled`（dpi 仅 png|pdf；纸张仅 pdf；pdf+纸张→宽度禁）；`options()`：pdf+纸张→width_px=None；返回 {fmt,dpi,width_px,page_size}。
- 承接：【Qt】选项对话框直译。

## data_view_models.py（1054 行）
- `STAGE_LABELS`（RAW 原始输入/DERIVED 派生数据/INTERMEDIATE 中间结果/OUTPUT 输出成果）+`STAGE_ICONS`（state_language maturity glyph 单一词汇源 V7 §6）+`stage_label/stage_icon/stage_color`；`IntegrityState`（5 值 label/icon_symbol/color_token：已校验✅/已修改⚠️/缺失❌/外部链接§/未校验❓）；`VersionView`（checksum_display：>12→`{8}...{后4}`）；`TagView`/`LineageView`（has_lineage）；`AssetView`（trashed_label "✕ 已移至回收站"；normalized_tags post_init 归一）；`RESOURCE_TYPE_DISPLAY_LABELS` 28 项（含 catalog 产物 factor_map 因子图/prediction 预测/paleomap 古地图…unknown 其他）；`_infer_stage`（role input|derived|intermediate|export|output→阶段，回退 RAW）；`path_exists_safe/path_is_dir_safe`（OSError→False #882 ENAMETOOLONG 长注）；`FsProbeCache`（每刷新每路径一 stat；死目录前缀剪枝 O(1) #917）；`asset_view_from_resource/artifact/object`（duck-typing 回退；artifact 完整性诚实 UNKNOWN 不因存在装已校验 #850-4；modified `%Y-%m-%d %H:%M`）；`_integrity_from_version`（UI 线程不重哈希：trashed→UNKNOWN/非托管→UNMANAGED/载荷缺失→MISSING/有 sha256→VERIFIED）；`_catalog_tag_maps`（document+revision+mutation_serial 键缓存 #1173）；`enrich_view_from_catalog`（tombstone/治理/版本/tags/完整性/血缘原地富化，任何目录失败保 legacy 视图）；`CatalogRowOverview`+`catalog_row_overview`（一次过批量（document,revision) 缓存 #1171；`_lineage_status_text`：`源头`/`{n} 级至源头`/`未接源头`/`无血缘记录`+` ⚠断链`）；`apply_catalog_overview`（current_version `v{n}` 多版本 `v{n} ({count})`）；`make_catalog_enricher`（三种桥接形状解析：同 id/legacy_resource_id/catalog_version_id）；`asset_view_from_catalog_overview`。
- 承接：【核+薄】**整个文件 Qt-free——C++ 数据页视图模型的直接 oracle 富矿**。

## factor_prepare_worker.py（88 行）
- `FactorPrepareWorker(QObject)`：信号 finished(int)/completed(object)/failed(str)/cancelled()/progress(object)；构造优先宿主线程预构建快照（指纹与分类同源）否则 build_prepare_snapshot(project,generation,method|IDW,grid_n|DEFAULT_GRID_N,power,force)；run：token.raise_if_cancelled→run_factor_prepare_schedule(progress 回调)→再 raise→result.cancelled→cancelled()/completed+finished(count)；JobCancelled→cancelled()；异常→`f"{exc.__class__.__name__}: {exc}"`。back-compat 别名 FactorPrepareResult=FactorPrepareBatchResult。
- 承接：【核+薄】worker 壳；schedule 核在 workflow.factor_prepare_scheduler（C++ interpolate_factor 已有单任务核）。

## geo3d_workspace.py（905 行）
- `Geo3DWorkspaceController(QObject)`：GEO_TREE_ROOT_LABEL "地质模型对象 (V5)"；_KIND_LABELS 6（well 井轨迹/horizon 层位面/fault 断层面/volume 地层体/tunnel 隧道/measure 测量）；_MEASURE_MODES 6（point 点坐标 1 点/distance 距离 2/polyline 折线长度 3/vertical_difference 高差 2/thickness 厚度 1/plane_orientation 产状 3）；add_object（重复 id→replace；DomainError→`对象被拒绝: {exc}`）；增量 QC（_qc_single 只重算该对象）+refresh_qc；`ingest_demo_result`（Provenance demo=True source_kind=demo；bh_raw→geo_well_from_head、tunnels_raw→TunnelSection、faults_raw→demo_fault_curtain（平面截 extent 采样 8 点，|b|<1e-9 防护、不足 2 点回对角线）；状态 `演示建模对象已加入场景: 井 {n} · 隧道 {n} · 断层 {n} (demo)`）；`inspector_text`（未选中对象/名称/ID/CRS·域·单位/表示/来源(+demo)/源版本/顶点数/柱数·闭合·最小厚度/QC worst+issues）；测量状态机（set_measure_mode 未知 False；点数不足 `测量: 已选 {n}/{m} 点`；thickness 需两个不同层位面 "厚度测量需要两个不同的层位面对象（名称含 top/顶 与 base/底）"；DomainError `测量失败: {exc}`；id 冲突后缀消解；完成 `{name}: {format_result}`）；剖切（clip_state 0-1 滑条→bounds 派生世界平面 axis_plane（无 bounds 跳过不伪造坐标））；视图预设（capture/save "视口未就绪，无法保存视图"/restore）；rebuild_tree（kind 分支 `{label} ({n})`+勾选=可见性；QC error/blocker 染色；`_object_label` demo (demo)/简化垂直/(2.5D 幕帘)/空数组 (未加载) ADR-03）；`save_state/restore_state`（demo 对象永不持久化；逐条目降级（坏 dict 跳过、from_meta 失败 debug）；_as_bool 严格（"false" 永不真化）/_as_float 有限钳制；状态保存失败可见 "三维工作区状态保存失败（详见日志）"）；`_slug`（[^a-z0-9_.-]+→-，空→obj）。
- 承接：【延后】M8；测量状态机/持久化降级语义 Qt-free 可 oracle。

## inspector_panel.py（1026 行）
- `_fit_key_value_table`（键列贴合/封顶 156px 值列 stretch；表高=表头+行*28+横滚条+边框 钳 max_height）；`_VersionsTableView` 兼容访问器；`LineageTreeWidget`：全链血缘树（⬆ 上游追溯 (至 RAW 输入)/⬇ 下游衍生（收起）；根=当前版本其 run+输入挂下；截断 "… (层级/节点数达上限，已截断)"/"… (已截断)"；OUTPUT→⚙ Run→INPUT 交错；版本 label `{stage_icon} {asset_name} · {stage_label} v{n}[ ✕回收站]`；详情 `版本 {name} v{n} · 阶段 {s}\n路径: {p}\n校验和: {cs} · 标签: {tags} · 生成 Run: {run}`/`Run {op} · 状态 {s} · generator {g}\nid: {rid}`；show_loading "正在加载血缘链…"；clear_chain 默认 "原始导入资产 / 无上游依赖"；双击 version→version_activated）。
- `InspectorPanel(QFrame)`：6 tab（概要 11+行键值表：回收站状态插行 2/CRS 追加/编图图层引用 `{n} 个（前3…）`/地图产品/用途提示 "（结果有截断）"；元数据 3 表（治理 `GOVERNANCE_KEYS` 逐键 label+display 空→"未填写（点击下方按钮编辑）"；目录元数据排 keys 除治理键 空→"暂无目录扩展元数据"；解析摘要 parsed_labels 11 键中文化+role_labels 相|亚相|微相+bool 是|否+list 顿号 join 空→"暂无附加解析元数据"）；标签 TagContainer；版本表 5 列（`★ {id}` 当前/生命阶段/校验和/时间/标签 或 "—"）+版本标签 +/-（+菜单 TagInputDialog "添加版本标签"；−菜单列现有）+创建派生副本（RAW 门禁：非 RAW 置灰 hint `当前为「{stage}」阶段，不可再派生；派生副本只对 RAW 阶段资产开放。`/RAW hint "从该 RAW 资产派生一个可编辑副本：原件保持不变，副本落到「派生数据 (DERIVED)」阶段并钉住来源版本。"）；血缘 LineageTree（未富化 legacy 一跳摘要 `f"{k}: {v}" join "；"`）；完整性（`完整性状态: {icon} {label}`+token 色；SHA-256: {cs|未生成校验和}+复制 Hash 仅有值；立即校验按钮）；_INTEGRITY_TONE_TOKENS。
- 承接：【Qt】6 tab 检查器；文案/门禁 oracle 面。

## lithology_crossplot_dialog.py（94 行）
- `LithologyCrossplotDialog(PwbDialog)`：岩相/波阻抗-伽马交会图分析（560x520）；`_LITHO_EVAL_COLORS` 域语义色 4（砂岩 优质储层 (Sand)/泥岩 盖层/隔层 (Shale)/石灰岩 致密/碳酸盐岩 (Limestone)/花岗岩 基底结晶岩 (Granite)）；HTML 表（`基于钻孔分层测井数据计算得到 {n} 组有效采样点。…`；每 cluster `{count}`/`{mean_gr:.1f} ± {std_gr:.1f}`/`{mean_ai:.0f} ± {std_ai:.0f}`/评价色 span；未分类回退）；结论区 3 条固定建议（聚类边界/储层盖层辨识/流体替代敏感性）；关闭按钮。
- 承接：【延后】geoviz 分析核 M8；HTML 文案 oracle。

## map_canvas_panel.py（97 行）
- `MapCanvasPanel(QFrame)`：编图画布中心（标题 编图画布；QStackedLayout 三页：空态 label（"未选择古地理图"/"暂无图面要素"）/geoviz PaleoMapCanvas/NativeMapCanvas）；`load_preview(features,wells,period_name)`（全空→空态+空文案回 "未选择古地理图"；否则 canvas.load_features）；`load_native_scene(scene)`；`update_state(document)`（None→空；preview_payload_from_document）。
- 承接：【Qgs】画布宿主已被 qgis_bridge/unified canvas 取代（legacy 兼容面）。

## map_edit_snap.py（99 行）
- `MapSnapManager`：默认容差 8.0 屏幕像素；enabled/tolerance（负值钳 0）/reference_points（set 后失效缓存）；`snap_xy(x,y,items,is_visible_fn,draft_points)`（禁用→原值；api.snap_point(candidates,x,y,tol)）；`get_candidates`（缓存命中→缓存+draft 追加；否则按 kind 遍历：FaciesPolygonItem 全环点/LineItem 坐标/Well|Label 中心；追加 reference；缓存+build_count++）。
- 承接：【核+薄】纯逻辑（geoviz snap 核）；候选收集规则可 oracle。

## map_factor_shelf.py（102 行）
- `MapFactorShelf(QWidget)`：编图底部单因素架；动作行 4 按钮（新建单因素地质编图 Primary tooltip "从井点属性执行空间克里金插值，生成包含栅格、等值线及井位标注的 GIS 图件"/从单因素生成等值线初稿/断层约束→解释版本 tooltip "把当前图件中断线/断层多段线提升为正式断层解释…"/装配古地理成果 (MapProduct) Primary tooltip "多因素 + 解释 + 组图 → 一个带完整血缘的 OUTPUT 成果版本（拒绝合成数据）"）5 Signal；FactorPreviewGrid（card_clicked→overlay 请求 outputs[0]|task.id）；view_state/cursor_position 存取（display-only）。
- 承接：【Qt】动作架；与本任务 HUD 同族（factor 上下文面板）。

## paged_asset_model.py（704 行）
- （subagent 摘要+父代理窗口扫）`PAGED_MODE_THRESHOLD` 大目录分页门；`SqlCatalogAssetRef`（SQL 行轻量引用：id/name/type/current_version_id/…）；`CatalogPageProvider`（包 DataCatalogService 分页查询 facade：total()/page(keyset|offset)/total_source_aggregates(+_cached)/count）；`PagedAssetTableModel(QAbstractTableModel)`：按 apply_query(FilterQuery) 服务行（不可映射查询→False 回落物化）；稀疏页按需取（rowCount 全量元数、asset_at 页缺失 demand-fetch）；稳定键 ("resource",asset_id) 行索引 row_for_key（常驻页内）；后台取页线程+shutdown；列集/排序与 AssetTableModel 同词表。
- 承接：【核+薄】页模型语义依赖 catalog 分页（C++ search_assets_page 已有）——两仓可直接对账。

## task_panel_base.py（185 行）
- `_TASK_STATUS_ALIASES` 10（pending/queued→queued、running、cancelling、cancelled、complete/completed/done→done、failed、warning→degraded V11）；`task_status_token(status)`（未知→StateToken("·",原文,"muted") 不编造）；`TaskPanelBase(QFrame)`：任务列表基类（min200；当前任务/适配器/状态 PwbBadge（tone 随 state_language）/平均概率/待复核区(可选)；`update_state(tasks,selected_index)`：显式 index 优先否则 active_prediction_task；值卡（name 空回 "未选择预测任务"/adapter "—"/mean_probability "—"/review `f"{n} 个"`）；键=id:`{id}` 或 name:`{name}`；行文本 `f"{name} · {token.label}"`（name 空 "未命名预测任务"）+tooltip `{name}\n状态：{label}`；_suppress 包裹差分刷新；task_selected(int)。
- 承接：【Qt】Prediction/Seismic 任务面板共用基类。

## web_document_preview_widget.py（82 行）
- `_LocalOnlyRequestInterceptor`/`_LocalOnlyPage`：scheme 白名单 {"file","data","about","blob"}（拦资源请求/拒导航）；懒继承 WebEngine 类（import 时零 WebEngine 初始化）；`WebDocumentPreviewWidget(QWidget)`：QWebEngineView+私有 profile+拦截器+page；LocalContentCanAccessRemoteUrls=False；`load_document(path,html)`（html→setHtml(base=文件父目录)否则 load 本地文件）；`apply_settings`：zoom=font_size/12。
- 承接：【Qt】沙箱语义（断网+白名单）必须保留。

## well_log_canvas_panel.py（916 行）
- `WellLogCanvasPanel(QFrame)`：Legacy WellLogCanvas|WellLogEngine 双后端（env PALEO_USE_WELLLOG_ENGINE 默认 engine；Legacy 永不删 #169/#174；切换重渲染当前数据；engine 选中但加载失败→**回退 Legacy 绘制**但保持 engine 选中便于重试，标题后缀 ` · Engine 不可用，已回退 Legacy ({err})`）；三栈（空态 未选择预测任务|canvas_scroll 横滚|engine_host 占位 "WellLogEngine 默认启用但当前不可用。\n请安装 welllog 绑定；或设 PALEO_USE_WELLLOG_ENGINE=0 使用 Legacy."）；深度游标生产（120ms 门+尾沿 flush R3-m2；legacy 像素→MD 线性映射（header 56 排除）；`depth_cursor_unavailable_reason` fail-closed：ft/unknown 轴拒绝发布（`depth-unit:{raw|unit}`/`depth-unit:unknown`——V6 §3 unknown 永不默换米）；engine crosshair_state 轮询+回声抑制（值匹配 |Δ|≤max(1e-6,1e-9|d|)；回声武装时仍轮询）；`set_link_cursor`（消费端：非 m 文档显式 FT_TO_M 换算、unknown 拒绝；写前武装回声；返回 False=不支持由调用方上报）；jump_to_depth；绑定 LAS 冷载 worker（#842 seq 守卫；LRU 命中同步）；合成预测任务→well_log_data_from_prediction；`_apply_bound_payload`（源 LAS 解释不覆写——预测相带走独立 AI 轨道 build_ai_prediction_tracks，不伪造黄色砂泥）；井道布局 reconcile+设置对话框；标题 `测井预测剖面 · {name} ({LAS|合成})[  [t1 | t2]][ · Engine · {update_kind} · {c} 曲线 / {t} 轨[ · 岩性{n}/相{m}]]`；Stage-12 解释顶层叠加（apply_correlation_tops_to_well_log_data 吞异常）；shutdown(wait_ms) 释放原生 Session。
- 承接：【延后/核+薄】深度单位 fail-closed 契约（V6 §3）与游标门控是 Qt-free 可 oracle 的语义核；画布本体 M8。

## well_log_load_worker.py（91 行）
- `WellLogLoadWorker(QObject)`：单 LAS/XML 离 GUI 线程解析（#842/#1224）；信号 finished(object)/failed(str)/cancelled()/**cancelling()**（V8 M8 诚实语义：cancel 落在不可中断解析中→发 "正在结束" 提示而非假 "已取消"）；run：预取消→cancelled；_parse_started=True→adapter.resolve(ref,project,cancel=…)；finally 恒 _parse_started=False（终态后 cancel() 不得再发 spurious cancelling R1-P2）；WellLogLoadCancelled 或已取消→cancelled；迟到结果丢弃（取消期完成的 payload 永不进 UI #1224 契约）。
- 承接：【Qt】worker 语义（cancelling 区分/迟到丢弃）可直接移植 C++。

## well_log_prediction_page.py（928 行）
- `_redact_endpoint`（urlsplit 无 scheme/host→SECRET 正则打码；无效→"<无效地址>"；否则 scheme://host[:port]/path 去查询）；`_AUTHORIZATION_RE`（Authorization: Bearer …→\1<REDACTED>）+`_SECRET_VALUE_RE`（api[_-]?key|token|secret|password=…→打码）+`_redact_diagnostic_text`（双正则+截 3000）——**凭证永不进 UI 日志（纯函数 oracle 富矿）**。
- `WellLogPredictionPage(QWidget)`：任务|画布|证据 sizes 280/860/260+FloatController well_log:task/evidence（GL 画布不浮动）；选择锚定任务 id（V11 C4 索引钳位曾静默改目标）；井源 combo 签名门控（`{name} · {FMT}`；空→占位 "数据管理中暂无 LAS / XML 测井数据"；同签名仅重断选择）；`select_well_resource`（清任务选择=推理前无叠加语义；恢复该井最近一次线上失败 `上次推断失败: {err}`+诊断 "失败（历史运行）"）；导入按钮（无工程 "请先打开或创建工程"；过滤器 *.las *.LAS *.xml *.XML→well_log_import_requested 交 DataPage 拥有导入）；`_on_run`（未绑工程/未选井 "请先从数据管理选择一口井数据"/未连目录→QMessageBox；ensure_geoviz_online_model 失败 `无法准备线上测井预测: {exc}`；run 参数含 online_endpoint/超时三元组）；`_on_demo`（MODEL_ID_DEMO 未注册 `演示模型未注册: {exc}`）；`_start_inference`（InputContractError `输入不满足模型契约: {exc}`；线上 workflow 追加 postprocess 输入去重；set_inferring(True)+"正在调用线上测井预测服务…"；_write_run_diagnostic 推断中）；完成（run failed→`推断失败: {redacted}`+诊断 失败；无 result→"预测完成但未返回可用结果"；materialize_prediction_task+link 失败记 model_metadata.link_failed=True（H3 谱系不空）；选中最后任务；完成文案 "线上测井预测完成，结果已保存到数据管理"/"预测完成，结果已保存到数据管理"+诊断 完成）；异常→"异常中断"；`_write_run_diagnostic`（线上测井预测运行日志/状态/运行 ID {id|未创建}/井数据 {name} ({id})/模型版本/服务地址(打码)/远端模型 ID/同步等待·请求·轮询超时/错误: 打码）；导出（无就绪画布 "当前没有可导出的测井剖面"；engine 后端非 PNG→RuntimeError "WellLogEngine 路径暂仅支持 PNG 抓屏导出；请切换到 Legacy 导出 SVG/PDF"；抓屏失败/PNG 写入失败；成功 `已导出: {name}`；engine 分支补 register（I5）；legacy export_well_canvas 带 source_task_ids）；`set_selected_well`（3D 页跨页同步：blockSignals 单次更新；按 name 匹配任务）；shutdown_workers（不可 join→False 保会话）。
- 承接：【核+薄】redaction/超时/会话安全 Qt-free 可 oracle；推断编排延后。
