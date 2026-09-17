# 16 — agent findings（subagent #1 全量阅读笔记）
范围：workstation/ qgis_stack/ ui 顶层 / C++ platform app + libs/ui / cpp-platform 与 UX 文档 / 相关 pytest
方法：全文阅读（大文件 1000 行窗口）。

## paleo_workbench/ui/workstation/__init__.py（5 行）
- 公开符号：仅 `WorkstationFrame`（re-export 自 shell.py，workstation/__init__.py:3）。
- 用户任务：包入口。
- 关键依赖：shell.WorkstationFrame。
- C++ 承接建议：薄模块，直接并入 target 的 umbrella header；无独立逻辑。

## paleo_workbench/ui/workstation/action_help.py（148 行）
- 公开符号：`ActionExplanation`（frozen dataclass，15 字段：tool_id/label/availability/requirements/missing/impact/modifies_data/creates_version/background_task/shortcut/stages/layer_kinds/current_layer/current_stage，action_help.py:41-58）、`explain(tool_id, ctx, layer_name="")`、`format_tooltip/format_status/format_details`。
- 用户任务：从 canonical contract 派生「为什么这个工具可用/不可用」的 tooltip、状态条文案与详情面板。
- 关键依赖：`mapping.tool_availability.evaluate_tool`（动态唯一权威）、`mapping.tool_help.TOOL_HELP/TOOL_LABELS/TOOL_SHORTCUTS`（静态登记处）、`stage_from_value`。
- C++ 承接建议：Qt-free 纯数据/纯函数核心（explain+format 全是字符串组装），配薄 QWidget 消费；`TOOL_HELP` 表移植为 C++ 静态表。
- 分支与边界：未知 tool_id → 构造「未知工具」占位 spec（action_help.py:77-82）；disabled 时 tooltip 多两行「不可用：reason」「需要：requirements」（107-115）；中文错误文案为 oracle 候选。

## paleo_workbench/ui/workstation/activity_rail.py（127 行）
- 公开符号：`ActivityRail(QFrame)` — 信号 `mode_requested(str)`/`settings_requested`/`collapse_requested`；`_MODES` 六模式 project/data/layers/search/history/workspaces（activity_rail.py:24-31）；`set_mode`/`set_explorer_expanded`/`_apply_density_metrics`。
- 用户任务：左侧固定 rail，切换资源管理器视图模式 + 设置/折叠按钮。
- 关键依赖：`ui.tokens.density_tokens/rail_width`、`ui.style.bind_metrics`（密度切换回调，activity_rail.py:110）、`common.workstation_icon`。
- C++ 承接建议：新 Qt widget（QToolButton+QButtonGroup 直译）；密度 token 系统需先行。
- 分支与边界：V11 B1 语义约束——rail 是「资源管理器视图模式」而非页面导航，tooltip 文案（35-42）必须保留；折叠钮 `setAccessibleName` 双向翻转（118-127）是无障碍 oracle 候选。

## paleo_workbench/ui/workstation/app_bar.py（257 行）
- 公开符号：`WorkstationAppBar(QFrame)` — 信号 new/open/open_sample/save/properties/command_submitted(str)/agent_requested/task_center_requested/workspace_preset_requested(str)/about_requested；方法 `set_project(name,region)`、`set_current_workspace(preset_id)`（回写不重发信号，app_bar.py:196-207）、`set_task_count(active)`（activeTasks 属性驱动 QSS repolish，212-217）、`set_viewport_class(viewport)`（V9 视口策略改命令输入最小宽 219-236）、`focus_command()`。
- 用户任务：顶栏 = 品牌 + 工程菜单 + 工作区预设下拉 + Ctrl+K 命令输入 + 主题/密度视图菜单 + 任务计数 + Agent 按钮。
- 关键依赖：`ui.layout_presets.list_presets`、`ui.theme.theme_manager.set_theme/set_density`（生产入口在视图菜单，app_bar.py:113-155）、`dock_framework.COMMAND_INPUT_FLOOR_*`、`tokens.app_bar_height`。
- C++ 承接建议：新 Qt widget 直译；theme_manager 信号连接须绑成员方法（闭包连接在 teardown 后抛 RuntimeError 的教训写在 149-152 注释）。
- 分支与边界：`set_project` 里 region==project（casefold）时隐藏区域段（181-184）；viewport COMPACT→COMMAND_INPUT_FLOOR_COMPACT 否则 NORMAL；任务计数负数钳 0。

## paleo_workbench/ui/workstation/attribute_schema.py（166 行）
- 公开符号：`AttributeFieldMeta`（frozen dataclass：key/label/kind/choices/required/unique/expression/value_range/editor_widget/origin∈spec|template|extra，attribute_schema.py:31-49）、`field_descriptors_for_layer(controller, layer_id)`、`qgis_schema_parity(canvas, layer_id, descriptors) -> (state, detail)`，state∈synced/drift/unavailable。
- 用户任务：把「一层在属性表里如何呈现/编辑」收敛为单一派生（角色 spec 优先→模板 schema→额外属性键），并对比 QGIS provider schema 给一致性标注。
- 关键依赖：`geological_layer_spec.spec_for_role`、`mapping.qgis_layer_schema._editor_widget_for`（控件推断唯一权威，attribute_schema.py:64-66 特意 import 私有名防第二真源）、`composite_editing.schema_fields`、canvas.stack.mirror_layer_schema_json。
- C++ 承接建议：Qt-free 核心派生逻辑 + 属性表 widget 消费；parity 检查依赖 QGIS 桥自省面，需在 bridge 保留 `mirrorLayerSchemaJson`。
- 分支与边界：spec 抛 KeyError/ValueError → 不猜（回落模板）；空描述符兜底 `id` 列（132-134）；parity 缺/多字段中文明细格式「缺 [..]，多 [..]」（159-166）为 oracle 候选。

## paleo_workbench/ui/workstation/common.py（167 行）
- 公开符号：`workstation_icon(name, color="")`（SVG 按主题 TEXT_SECONDARY 染色，DPR 感知缓存，common.py:61-76）、`tinted_map_icon`（map/ 目录优先、无彩灰系才重染，79-108）、`install_theme_hook()`。
- 用户任务：全域主题感知图标工厂。
- 关键依赖：`ui.theme.theme_manager.theme_changed`（清缓存）、`tokens.palette_for`。
- C++ 承接建议：新 Qt 工具函数（QIcon + CompositionMode_SourceIn 可直接翻译）；C++ 侧可简化 DPR/缓存策略但主题切换失效语义必须保留。
- 分支与边界：无彩判定阈值 max-min≤12%*255（146-155）；非法 hex 长度视为可染（151）；资产缺失返回空 QIcon。

## paleo_workbench/ui/workstation/mode_state.py（127 行）
- 公开符号：`WorkstationMode`（IDLE/DIGITIZING/ADJUSTING_BOUNDARY/INSPECTING_QC/TIME_TRAVELLING）、`ModeEvent`（11 事件）、`ADJUSTING_TOOLS={vertex,reshape,move_feature}`、`MODE_HINTS`（每模式中文提示条文案，mode_state.py:41-52）、`ModeStateMachine`（dispatch/hint_text/pan_held）。
- 用户任务：观察既有信号的纯投影状态机，驱动提示条与快捷键域判定。
- 关键依赖：无（纯 QObject 投影层，不拥有工具/画布状态，mode_state.py:1-7）。
- C++ 承接建议：Qt-free 核心（switch 语句直译）+薄接线；转移表是现成 oracle。
- 分支与边界：TOOL_ACTIVATED 在 TIME_TRAVELLING 中被拒绝（91）；QC_HUB_CLOSED 仅在 INSPECTING_QC 时回 IDLE（106-107）；EPOCH_COMMIT 回 `_mode_before_travel`；pan_held 是模式之上的瞬态标志、不换状态；未知事件不抛异常；消费者不得向 FSM 回环派发（M5-ECHO 钉死）。

## paleo_workbench/ui/workstation/process_hub.py（133 行）
- 公开符号：`LOG_LINE_CAP=2000`、`QtLogHandler(QObject, logging.Handler)`（message_ready 信号 + 有界 deque + take_pending）、`LogViewer(QFrame)`（只读 QPlainTextEdit + 1s 轮询兜底）、`ConsolePane`（「预留：嵌入式控制台」占位）。
- 用户任务：「日志」dock 的真实日志查看器 + 「控制台」dock 占位。
- 关键依赖：`logging.getLogger("paleo_workbench")`；shiboken6.isValid 死壳检查（process_hub.py:43）。
- C++ 承接建议：Qt widget（QPlainTextEdit maximumBlockCount 直译）；QtLogHandler 的线程安全（信号跨线程排队）与死 handler 防御是 C++ 要用连接生命周期重新表达的关键点。
- 分支与边界：handler 死了丢弃日志绝不抛（38-44「打开工程报错」根因注释）；shutdown 摘 handler 并还原包级别（107-116）；emit 遇 DeferredDelete 静默。

## paleo_workbench/ui/workstation/state_language.py（150 行）
- 公开符号：`StateToken(glyph,label,tone)`、`_VOCABULARY` 七类：maturity/freshness/session/editability/task/backend/permission/readiness（state_language.py:29-91）、`tone_to_badge(tone)`、`state_token(category,value)`、`workbench_context_text(snapshot, layer_name=)`。
- 用户任务：全域状态 → glyph+文字+tone 单一映射（双信号，禁纯色）；状态条工作台段「阶段 · 编辑目标 · 后端 · 任务」文案。
- 关键依赖：UIContextSnapshot 字段（qgis_bridge_available/editing_active/active_layer_block_reason/running_task_count…）。
- C++ 承接建议：Qt-free 纯数据核心（枚举+查表）；tone→badge 桥保留单向语义。
- 分支与边界：未知值→「未知」muted；未知类别 KeyError（编程错误尽早暴露，state_language.py:110-115）；None 与 False 分开处理（qgis_bridge_available is False 才报回退）；无任务不渲染任务段；被拒编辑目标必须显示原因。

## paleo_workbench/ui/workstation/ui_context.py（166 行）
- 公开符号：`UIContextSnapshot`（frozen dataclass，约 45 字段，全部 None=诚实未知，ui_context.py:28-108）、`UIContextService`（set_provider/clear_provider/snapshot/current/refresh + context_changed 信号）。
- 用户任务：派生式 UI 上下文聚合——展示态投影，非第二领域权威。
- 关键依赖：注册式 provider（SelectionContext/MappingWorkspace controller/QGIS 桥/Harness 权限/TaskScheduler 适配器）。
- C++ 承接建议：Qt-free struct + 观察者；这是 conv-16 面板面板化的中枢——每个 dock/panel 都从 snapshot 读状态；C++ 可保留字段名以便 oracle 对齐。
- 分支与边界：provider 异常→warning+未知（fail-closed，142-147）；refresh 时信号源已销毁静默（163-165）；仅变化才发信号；`set_provider` 未知字段名 raise KeyError（130-131）。

## paleo_workbench/ui/workstation/tool_page_dialog.py（74 行）
- 公开符号：`ToolPageDialog(QDialog)` — 非模态（setModal(False)，tool_page_dialog.py:24）、固定 1080×720/最小 720×480；`present(page,title,home)`、`_release()`。
- 用户任务：数据制备/成图审核等工具页以 closable 对话框浮出（不许占 dock 与地图竞争），关闭时归还原 hub stack。
- 关键依赖：宿主 hub 的 `addWidget` 鸭子接口。
- C++ 承接建议：新 Qt QDialog 直译；「page 归还 home」的所有权语义在 C++ 需明确 parent 转移。
- 分支与边界：同页重复 present → 仅 raise+activateWindow（40-44）；closeEvent/reject 都走 `_release`；home 无 addWidget 时回退 setParent。

## paleo_workbench/ui/workstation/merge_features_dialog.py（121 行）
- 公开符号：`MergeFeaturesDialog(QDialog)` — `__init__(records, facies_fields=("facies",))`、`set_field_value`、`result_payload()->{target_id, attributes}`。
- 用户任务：无缝合并确认——预填面积最大要素属性，可换源、可改冲突值，payload 交桥 `merge_mirror_features`。
- 关键依赖：`mapping.merge_attributes.plan_merge_attributes`（权威计划）、QFormLayout 冲突高亮。
- C++ 承接建议：新 Qt QDialog 直译；`plan_merge_attributes` 移 Qt-free 核心。
- 分支与边界：冲突字段高亮 #fde8a0（相分类）/#fff3cd（其它）（merge_features_dialog.py:90-91）+ tooltip「所选要素该字段值不一致」；换源重建表单（96-103）；properties 非 dict 按 {} 处理。

## paleo_workbench/ui/workstation/layer_decorations.py（198 行）
- 公开符号：`LayerPresentationState`（8 布尔/字符串呈现旗标）、`_PRIORITY` 优先级链 missing>dirty>editing>missing_input>superseded>stale>degraded>frozen>published>reviewed（layer_decorations.py:45-56）、`primary_decoration`、`decoration_token`、`decoration_summary_text`、`GroupPresentationSummary`（计数 + summary_text glyph 汇总 153-170）、`presentation_state(...)`（权威结论→呈现态规范入口，173-198）。
- 用户任务：树/检查器共用的图层装饰真源（状态列单主信号 + hover 全信号摘要 + 组级汇总）。
- 关键依赖：state_language 词表；权威输入 `LayerGroupController.layer_freshness`、`session_undo_depth`、maturity。
- C++ 承接建议：Qt-free 纯数据核心（文件明言不 import Qt，layer_decorations.py:3-4）——直接移植为 struct+自由函数。
- 分支与边界：干净→None 无装饰（「显示空白比编造状态更诚实」）；editing 且 dirty 只显 dirty（86）；undo depth>0 即 dirty（191）；summary_text 无异常时输出「无异常」。

## paleo_workbench/ui/workstation/keybinding_manager.py（227 行）
- 公开符号：`ZOOM_STEP=1.5`、`KeybindingHintBar(QLabel)`（apply_mode 切 MODE_HINTS 文案）、`WorkstationKeyBindingManager(QObject)`（install/eventFilter/begin_temporary_pan/release_temporary_pan/cycle_selection/zoom_center/pick_facies_from_selection/handle_escape）。
- 用户任务：全键盘编图流——Space 临时平移、Tab 循环要素、Z/X 中心缩放、Ctrl+D 吸相属性、Esc 安全退出链；画布底部提示条随模式换文案。
- 关键依赖：mode_state FSM、composite 的 edit_controller/canvas/qc_hub/smooth_pan/tab_cycle_selection/ctrl_d_pick_facies/timeline.onion_button、`ui.shortcuts.focus_in_text_input`。
- C++ 承接建议：QObject eventFilter 直译（QShortcut 在 offscreen 测试不可靠的教训 → C++ 测试也走事件过滤器路径，keybinding_manager.py:3-6）。
- 分支与边界：文本输入聚焦全让路（105-107）；按键先 cancel 动画平移（D9，109-111）；仅无修饰键时 Z/X 生效避免吞 Ctrl+Z；临时平移期抑制 FSM 工具事件（74-76）；Esc 退出链顺序=手势取消→洋葱皮→退工具→关 qc_hub→IDLE（191-227）；手势中 Esc 只取消手势不退工具（204-206）；洋葱皮按钮 blockSignals 翻转（211-213）。

## paleo_workbench/ui/workstation/tool_surface.py（227 行）
- 公开符号：re-export `ToolAvailability/ToolContext/evaluate_tool/evaluate_all/TOOL_GROUPS/TOOL_IDS/stage_group_visibility/LAYER_CAPTION`；`QgisCapabilitySnapshot(mode,reason)`（native/degraded/unavailable/unknown 四态，None 不允许→fail-closed「unknown」，tool_surface.py:67-81）、`LayerCapabilitySnapshot`（+layer_facts() 扁平化 107-119）、`LayerMenuFacts`（toggle_editing/repair_geometry/raw_protected）、`tool_context_from_ui_snapshot(snap)->ToolContext`（143-222）、`derived_context(**changes)`。
- 用户任务：canonical evaluator 的呈现层适配器——工具条/palette/树右键菜单统一从单一求值取可用性。
- 关键依赖：`mapping.tool_availability`（业务真源，本模块禁第二套 enabled/visible/reason 判定，tool_surface.py:20-22）。
- C++ 承接建议：Qt-free 适配层（纯数据转换），可与 evaluator 一起移植；UIContextSnapshot→ToolContext 的保守默认值表是 oracle。
- 分支与边界：capability_mode 缺失时由 bridge bool 推导（True→native/False→unavailable/None→unknown，155-163）；queryable 缺席回落「有活动层≈1」（184-187）；is_raster→qgis_layer_type="raster"，否则有活动层→"vector"；None 一律保守 False（210-216）。

## paleo_workbench/ui/workstation/mapping_stage_bar.py（255 行）
- 公开符号：`_StageSegment(QFrame)`（序号圆点+短名+徽标，键盘 Enter/Space 可点 103-108）、`MappingStageBar(QFrame)` — 信号 stage_requested(str)/horizon_requested(str)；方法 set_current_stage（track「complete」属性 195-204）、refresh_badges、current_horizon、set_horizon_state（回写不发请求 223-246）、set_viewport_class（COMPACT 隐藏「层位」前缀标签 186-191）。
- 用户任务：AppBar 旁紧凑分段条切阶段（层位选择→智能预测→约束/单因素→综合编图）；层位下拉写入 `project.stratigraphy.target_horizon`（不可手输）。
- 关键依赖：`mapping_workspace.stages.STAGE_ORDER/MappingStage`；`dock_framework.ViewportClass`。
- C++ 承接建议：新 Qt widget 直译；QSS 属性（active/complete/tone）+ repolish 模式照搬。
- 分支与边界：徽标字符判定 tone——含"!"→error、"~"→warn、"✓"→ok、否则 info（mapping_stage_bar.py:21-28）；无尾 stretch 保 sizeHint=内容宽（同 row AppBar+阶段条 ≥1440 完整可见契约，183-184）；horizon 空白/去重/目标不在选项时插入首位（227-244）；_suppress_horizon + _last_committed_horizon 双防重复发射。

## paleo_workbench/ui/workstation/topology_checker_panel.py（205 行）
- 公开符号：`_RULE_LABELS`（overlap/gap/is_valid/workspace_remainder/dangle 中文名）、`TopologyCheckerPanel(QWidget)` — 信号 zoom_requested(list bbox)/highlight_requested(str)/check_requested/fix_requested(str,int)/fix_all_requested/ignore_requested(dict)/restore_requested(dict)；方法 bind(controller)、set_errors、menu_for。
- 用户任务：拓扑错误列表 + 规则过滤 + 点击定位高亮 + 忽略灰显恢复 + 单条/全部修复（不嵌 QgsGeometryCheckerDialog）。
- 关键依赖：`mapping.topology_checker.ignore_key`；controller.run_topology_checks / topology.checker.ignored_keys/last_run_at。
- C++ 承接建议：新 Qt widget（QListWidget+右键 QMenu 直译）；错误 dict 协议在 C++ 变 struct。
- 分支与边界：badge 三态「{n} 处未忽略 · {stamp}」/「{n} 处未忽略」/「尚未检查」（102-110）；忽略项灰 #a0a0a0+斜体（125-129）；methods 缺省 [{id:0,name:"修复"}]（164,193）；右键先选 itemAt(pos) 再取 error（177-187）。

## paleo_workbench/ui/workstation/mapping_stage_panel.py（424 行）
- 公开符号：`evaluate_stage_commands(stage_value, snapshot)->{action_id:(enabled,reason|None)}`（V11 §7 与 palette 同判：工程未开→「未打开工程」；阶段未知→「当前编图阶段未知」；阶段不匹配→stage_whitelist_reason；有 STAGE_ACTION_TOOLS 映射→evaluate_tool 判词；无映射→保守放行；未知阶段→空表，mapping_stage_panel.py:68-120）、`_ReadinessList`、`_CommandList`（禁用行=ItemIsEnabled 移除+TEXT_DISABLED+「不可用：{reason}」tooltip 178-200）、`_StagePage`、`MappingStagePanel(QWidget)` — 信号 action_requested(stage,action)/locate_requested(stage,target)/stage_switch_requested/constraint_requested；`_CONSTRAINT_ACTIONS` 7 种 ConstraintKind（319-327）。
- 用户任务：阶段上下文 dock（QStackedWidget 三页）——就绪度清单可点定位、阶段动作一键执行、Phase2 专属 7 键 typed 约束创建行；中央地图永不切换（V5 §35）。
- 关键依赖：stage_vocabulary.stage_context_actions/STAGE_ACTION_TOOLS（单表派生，316-318）、tool_availability.evaluate_tool/stage_whitelist_reason、readiness.StageReadiness、style.palette TEXT_DISABLED。
- C++ 承接建议：新 Qt widget（QStackedWidget 直译）；`evaluate_stage_commands` 是 Qt-free 判定函数可直移植；「面板只发请求信号，执行在宿主」的边界必须保持。
- 分支与边界：narrow list 策略（minimumWidth 0 + Ignored policy + ElideRight，57-64）防长文本撑 dock 最小宽——conv-16 面板布局要继承；禁用行程序化点击也 no-op（202-209）；set_action_availability 缺 stage_value 用当前页；未知 stage→set_stage no-op。

## paleo_workbench/ui/workstation/facies_selector.py（486 行）
- 公开符号：`FaciesBrushContext(QObject)`（相带画刷装备态：equip 幂等同值不重播、clear 发 {}、selection 恒含三键，facies_selector.py:41-85）、`FaciesCascadeSelector(QWidget)`（三级级联，子级首项空=任一级可停 Q4-b）、`FaciesSelectionDialog`（绘制完成/指定相带模态弹窗，标题带锚定深度提示 194-199）、`FaciesChangeDialog`（编辑期换相列表形态：搜索+列表+可选细化行）、`FaciesTaxonomyDialog`（词表管理：三级树+GeoJSON 导入+恢复内置，预览后确定才生效）。
- 用户任务：相/亚相/微相选择的一切 UI——数字化后赋相、换相、词表维护。
- 关键依赖：`mapping.facies_taxonomy.FaciesTaxonomy`（names/selection_level/selection_from_attributes/from_geojson_features/builtin/counts/source）。
- C++ 承接建议：新 Qt widgets 直译；FaciesTaxonomy 移 Qt-free 核心。
- 分支与边界：取消/关闭/Esc 返回 None→保留几何属性留空（Q6-a，179-181）；改父级清空更细级（145-152）；锚定级以上保持空（369-371）；导入失败两类中文明细（453-463）；细化未指定→「新相生效即清空亚相/微相」（229-231）。

## paleo_workbench/ui/workstation/composite_panels.py（471 行）
- 公开符号：`_GEOMETRY_TYPE_LABELS`（Point→点…中文）、`_CheckCell`/`_NumericCell`（item-based 单元格代理，防 1000 层×5 widget 冻结，composite_panels.py:46-104）、`IdentifyResultsPanel(QFrame)`（set_results 空→自动隐藏；双击发 result_activated；子行=来源/模板角色/可编辑+排序属性）、`SnappingSettingsDialog(QDialog)`（全局开关/容差 1-100px/单位 px|map|layer/比例依赖 special「关闭（全比例捕捉）」/5 捕捉模式/范围所有|仅当前/每层 6 列表/井位参考点）。
- 用户任务：识别结果面板（QGIS Identify 语义）+ per-layer 捕捉设置（权威在 CompositeEditController 与 SnappingService，面板只是视图）。
- 关键依赖：`controller.snapping`（SnappingService）、`snapping_profiles.recommended_profile_for_role/profile_summary`（V9 W4 角色推荐可解释）。
- C++ 承接建议：新 Qt widgets 直译；item-based 代理模式在 C++ 同样必要（性能教训通用）。
- 分支与边界：_NumericCell 读非法文本→0、钳 [0,max]、0 显示 zero_label「全局」（90-104）；per-row 无法表达的 endpoint/intersection/midpoint 只在全局框表达（404-409 注释）；容差 0=用全局（456-460）；井点为空→checkbox 禁用文案「当前无井点 / 引用参考点」（271-279）；初始尺寸公式 140+rows*26 / 370+rows*30（294-296）。

## paleo_workbench/ui/workstation/task_center.py（609 行）
- 公开符号：`_MAX_ROWS=100`、5 列（状态/任务/进度/用时/操作）、`_OperationHandleAdapter`（OperationRegistry 记录→任务 handle：task_id="op:{id}"，状态映射 completed→DONE/warning→DEGRADED，task_center.py:71-119）、`_TaskTableModel(QAbstractItemModel)`（差分 refresh：后往前删行→按位插行→签名比较只对变化列发 dataChanged，201-256）、`_TaskRowDelegate`（进度条/取消按钮纯绘制，editorEvent 承接点击 348-364）、`TaskCenter(QFrame)`（400ms 轮询 + active_count_changed 信号 + PwbEmptyState 空态「暂无任务」）。
- 用户任务：后台任务中心——调度器任务与页面级长操作同一张表、同一状态词表、同一取消交互（V11 goal §12）。
- 关键依赖：`runtime.task_scheduler.get_scheduler()`（进程级权威）、OperationRegistry（attach_registry，100ms 单发合并刷新防刷新风暴 455-462）、PwbEmptyState。
- C++ 承接建议：QAbstractItemModel+QStyledItemDelegate 模式在 C++ 一比一成立；这是 conv-16 「任务中心 dock」的直接实现参考。
- 分支与边界：失败行标题带错误首行前 40 字符（158-160，视觉 QA：不只藏 tooltip）；状态列必须给模型文本否则 ResizeToContents 塌缩「…」（162-165）；「取消中」优先于「运行中 N%」（339-345）；进度单元 FAILED→红「失败」/CANCELLED→「已取消」/DEGRADED→「降级完成」；顶部插入保持滚动（488-494）；选中按 task_id 恢复（496-507）；重试=同参数重提交、对 registry_op 禁用（539-545）；跳转 RuntimeError 静默（558-561）；format_elapsed <60s→「N s」否则 mm:ss（601-606）。

## paleo_workbench/ui/workstation/linked_workspace.py（700 行）
- 公开符号：`DocumentPane(QFrame)`（标题栏+「联动」badge+host，set_title 同步 dock 标题 63-68）、`LinkedInterpretationWorkspace(QWidget)` — 信号 object_selected/status_changed/well_focused/show_all_wells_requested；方法 ensure_views、make_well_pane/make_seismic_pane（额外窗格）、bind_well/bind_seismic、locate_seismic（联动门控 244-258）、apply_link_cursor（仅同名井才动十字线 260-283）、set_linked/_sync_link_badge（联动/独立）、refresh_domain_status、apply_default_well_backend/set_well_backend/well_backend_note（B9 诚实降级）、shutdown_workers。
- 用户任务：测井轨道/地震剖面双文档窗格协调器——井震联动游标、域状态条（MD·m / TWT 换算 / 同步状态）、方向切换（Inline/Crossline/Time）。
- 关键依赖：`viz.welllog_engine_adapter.resolve_default_backend`、coordination controller（selection_context 只读订阅 + publish_depth_cursor 生产者，236-242/641-658）、ui/pages/seismic_view_panel、well_log_canvas_panel。
- C++ 承接建议：新 Qt widget 集合；联动门控（link switch 是语义门）与只读订阅（不回发）的架构约束必须保留；offscreen/minimal 平台拒绝创建原生视图（323-326）——C++ 测试基建同款约束。
- 分支与边界：TWT 换算四态文案（—/不可用/超范围含区间/未复核后缀，146-181）；井无测井数据→清表面+标题「（无测井数据）」+拒占 active 槽（R3-M1，546-555）；井迹投影失败→「井迹投影不可用：{reason}」（587-610）；_elide 14 字符加省略号；link off 时 locate/apply_link_cursor/depth 发布全短路。

## paleo_workbench/ui/workstation/agent_panel.py（734 行）
- 公开符号：`_ENV_ALLOW_WRITE="PALEO_AGENT_ALLOW_WRITE"`、`AgentPlan`（frozen dataclass：action_id/parameters/gui_action/summary/followup_action/kind）、`_ACTION_RISKS` 14 动作最小权限表（52-68）、`_plan_risks`（registry 权威+静态表兜底）、`_TaskCancelAdapter`、`_AgentBridge`（completed/progress_changed 排队信号跨线程）、`AgentWorkspace(QFrame)` — 信号 open_well_requested/show_wells_requested/focus_joint_requested/undo_requested/write_grant_changed；方法 submit、cancel_current、set_active_well、_confirm_write_actions、_grant_write_session、write_granted_actions、_plan（规则解析器 659-713）。
- 用户任务：Agent 工作区——自然语言指令→typed 动作计划→HarnessExecutor 执行（权限检查/参数校验/结果验证）→HTML 对话历史 + GUI 同步动作 + 撤销。
- 关键依赖：harness（ActionRegistry/ActionContext/HarnessExecutor/ActionRisk）、runtime.task_scheduler、catalog.runtime.get_catalog、workflow.dag.plan_view.WorkflowPlanView。
- C++ 承接建议：新 Qt widget（QTextBrowser 历史+输入行）；权限模型（READ/COMPUTE/WRITE 精确集合授权）必须 Qt-free 先行；跨线程 progress 经排队信号模式照搬。
- 分支与边界：WRITE 未知动作 fail-closed 按 WRITE（287-312）；会话授权=精确动作集合子集语义非空白支票（314-316）；授权对话框拒绝为 default（398-401）；DEGRADED 不是校验通过、warnings 必须可见（605-618）；取消/失败文案「未应用 GUI 变更」；_plan 规划期不虚构井名（675-677）；allow_write 三层：constructor flag > env > 默认（148-154）；进度钳 [0,1]。

## paleo_workbench/ui/workstation/composite_attribute_table.py（771 行）
- 公开符号：`_CellProxy`/`_AttributeTableView`（QTableWidget 兼容面给差分测试）、`_AttributeTableModel`（fid 列 0 + schema 列；sort 空值沉底 (1,0.0,"") 键 192-198）、`_FieldEditorDelegate`（ValueMap→下拉/CheckBox→true,false 下拉/Range→QDoubleValidator；相带三字段词表级联按同行父值过滤，218-310）、`CompositeAttributeTableDialog(QDialog)` — 信号 feature_activated(str)/assign_facies_requested；方法 refresh、_write_attribute、_apply_batch、_refresh_changed_features（差量刷新 C-P0-3）。
- 用户任务：QGIS「打开属性表」语义——要素×字段表格，编辑落 `VectorEditSession.change_attribute`（与画布数字化同一 undo/版本链），表选↔图层选集双向同步，多选批量改字段。
- 关键依赖：attribute_schema（列派生+parity）、CompositeEditController（can_edit_layer/ensure_layer_session/content_changed/state_changed）、session.changes_since（增量日志）、is_facies_template_layer。
- C++ 承接建议：QAbstractTableModel+delegate 直译；差量刷新基线 (session, revision, columns, row_map) 模式可保留。
- 分支与边界：门禁拒写→状态行「只读 — {reason}（输入未写入）」绝不静默（582-590）；Range 字段非数值文本拒绝（600-605）；越界拒绝「超出范围 [low, high]」（608-614）；必填空值拒绝（615-618）；unique 占用拒绝、空值不占域、数值 float 归一（635-662）；非必填 ComboBox 编辑器必须落当前值否则数据损坏（review-1 P0-1，291-304）；新要素/删除/新字段/会话更替→回退全量 refresh（712-760）；图层 None→reject()。

## paleo_workbench/ui/workstation/inspector.py（934 行）
- 公开符号：`WorkstationInspector(QFrame)` — 信号 style_changed(dict)/assign_facies_requested(dict)/edit_style_requested(str)；`show_payload` 分派 14 种 kind（well/horizon/interpretation/layer/project/seismic/resource/map_component/curve/feature/factor/map_product/version/run/未知→show_generic，148-188）；`set_context_seam`（V6 §6 域上下文 seam 注入）；`_readonly(value, unit)`（缺→「—」+missing 属性，123-136）；最小宽 220 无最大宽（51-54）。
- 用户任务：右侧检查器 dock——属性/解释/样式/历史四 tab 的上下文属性展示（诚实未知：缺字段显示「—」不编造）。
- 关键依赖：payload dict 协议（宿主组装：FactorGrid 统计进 `payload["grid"]`/`summary_rows`，MapProduct staleness/readiness 由宿主提供——inspector 自己不解析权威，inspector.py:454-465, 537-543）；state_language（_add_state_row）；project.meta/stratigraphy/seismic_surveys/entity_asset_links。
- C++ 承接建议：新 Qt widget（QTabWidget+QFormLayout 直译）；「宿主组 payload、面板只渲染」边界保留；conv-16 关注点：**FactorGrid.statistics 的现成 UI 承接点就是 show_factor 的 grid 摘要行（min/max/uncertainty）与 summary_rows 协议（FactorSummary.to_display_dict()["rows"]）**。
- 分支与边界：状态行经词表渲染（missing→「（缺失）」/unknown→「（未知）」/warn→「（注意）」，480-486）；属性超 12 项截断并注明（433-437）；0.0/0 是真实读数不能当缺失（372-378）；通用表只显示标量+_OBJECT_ATTR_ROWS 十字段；指纹/SHA 截 12-16 字符+省略号；版本/Run 双读取口径（object 包装或扁平，593-597）；井轨迹缓存键=(project id, links 长度)（848-862）；样式页三态文案（781-808）。

## paleo_workbench/ui/workstation/explorer.py（945 行）
- 公开符号：roles `OBJECT_ROLE/NAVIGATION_ROLE/KEY_ROLE/ICON_ROLE`、`_SEARCH_DEBOUNCE_MS=200`、`_GROUP_ROW_LIMIT=5000`、`_TreeNode`（树规格节点，差分 key=kind+业务 id）、`ElidedFootnoteLabel`（Ignored 水平策略+逐像素省略，脚注永不驱动布局最小值 78-110）、`WorkstationExplorer(QFrame)` — 信号 object_selected/object_activated/navigation_requested(int,str)/joint_workspace_requested；六模式 `_MODE_TITLES`（project/data/layers/search/history/workspaces）；`refresh()->_build_spec->_reconcile`（差分：删除消失行→append 新行→_update_item 原位更新，保持展开/选中/滚动 690-738）。
- 用户任务：左侧资源管理器 dock——工程总览/数据目录（按类型分组）/图层管理器/搜索/历史与成果（解释版本+导出+过程成果）/工作区六种视图模式。
- 关键依赖：project.wells/resources/user_vector_layers/paleomap_documents/horizon_interpretations/export_artifacts/mapping_workspace.memberships/artifact_maturity、state_language、workstation_icon。
- C++ 承接建议：QStandardItemModel+QSortFilterProxyModel 直译；差分 reconcile 模式在 C++ 同样必要；「暂无图层」「未设置目标层位」空态文案保留。
- 分支与边界：隐藏 .preview_cache/、meta.json、payload.npz（656-665）；组超 5000 行截断+尾行「… 还有 N 项（用搜索过滤）」（631-642）；模式/工程切换→默认展开深度 1（783-801）；无目标层位→空态不再回落 "D63"（576-589）；过程成果按角色分组+成熟度 glyph+钉住版本 tooltip（420-506）；解释节点双读取 geological_entities 或 horizon 资源去重（667-680）。

## paleo_workbench/ui/workstation/shell.py（2217 行）★ conv-16 核心
- 公开符号：`HubScrollArea`（功能页自适应滚动宿主：dock 永远可自由调宽、窄时滚动条诚实降级；NoFocus+FocusIn 滚到焦点，shell.py:58-93）、`WorkstationFrame(QWidget)` — 信号 navigation_requested(int,str)/command_submitted/status_message；方法 `_add_dock(dock_id, widget)`、`_add_clone_dock`、`panel_commands()`、`apply_layout_preset`、`float_all_panels/dock_all_panels`、`_reset_default_layout`、`_apply_canonical_dock_layout`、`_hide_default_closed_docks`、`_restore_layout/_save_layout/flush_layout`、`shutdown_workers/_teardown_docks`、`show_well/show_seismic/show_agent/show_tasks/show_hub_page/activate_legacy/toggle_explorer/toggle_inspector`、`_apply_responsive_panels*`、`_inspect_layer_selection`、`_factor_grid_summary`、`_register_stage_palette_commands/_register_surface_palette_commands`。
- 用户任务：工作站壳——中央编图（永不替换、min 320），其余 15+ dock 全部可停靠/浮动/叠 tab/关闭重开/持久化。
- **MainWindow dock 结构（conv-16 直接蓝本）**：dock 宿主是外部注入的 `QMainWindow`（`PaleoWorkbenchWindow`，shell.py:104-108；孤立构造时 `QMainWindow(self)` 自有宿主 152-154）。dock 全为原生 QDockWidget（B18：**不装自绘标题栏**，setTitleBarWidget 会架空 Qt 原生拖拽——「窗口拖不动」根因，358-360）。创建流程 `_add_dock`（356-388）：`workstation_dock_registry.require(dock_id)` 取描述符→标题/objectName/features（Movable|Closable，can_float 才 Floatable）→`setProperty("pwbDockId", dock_id)`→addDockWidget(描述符.preferred_area)→topLevelChanged 时按描述符 min_floating_size 同步浮动最小尺寸（415-420）。**默认布局** `_apply_canonical_dock_layout`（1696-1726）：左=nav+mapping_stage（竖分）+tab 化 composite_input；右=inspector+composite_layer（tab 化，layer raise）+hub；底=agent+task+logs+console+composite_linked+well+seismic 全 tab 化在 agent 链。`_hide_default_closed_docks`（1728-1750）：默认只留 nav/mapping_stage/composite_layer/inspector（inspector 尊重跨会话 user 偏好）。顶栏 4 工具条：第 1 行 AppBar+StageBar 同行（≥1440 完整可见契约，313-335），addToolBarBreak 后第 2 行两条地图条（337-342）。restoreState 后 `_enforce_toolbar_rows` 强制归位（2068-2100）。
- 关键依赖：dock_framework（registry/ensure_dock_usable/apply_first_run_sizes/classify_viewport/INSPECTOR_HIDE_BELOW/RESTORE_ABOVE）、dock_manager、layout_persistence（QSettings 身份+版本栅栏）、layout_presets、CompositeDocument、QSettings。
- C++ 承接建议：QMainWindow+QDockWidget 直译完全可行（Python 就是纯原生用法）；描述符注册表（dock_framework）须先行；QSettings→QSettings C++ 同 API；「teardown 冻结布局保存」纪律（`_layout_frozen`）在 C++ 用 RAII/布尔同样表达。
- 分支与边界（oracle 候选）：面板菜单 toggle 表 `_PANEL_TOGGLE_TABLE` 15 项必须覆盖全部 dock（1507-1525「任何被关掉的 dock 都要有重开入口」）；具名预设只切可见性绝不重排几何（B-3，1650-1655,1668-1672）；「恢复默认布局」才允许 apply_first_run_sizes+50ms 延迟（1685-1689）；检查器三态显隐归因（user 显隐经 toggleViewAction.triggered、responsive 阈值 <1100 藏 / >=1200 恢复滞回、save 时 responsive 隐藏按可见落盘 #1121，482-491,1454-1496,2135-2158）；浮动例外：GL dock（well/seismic/hub）can_float=False 防 EGL segfault（1585-1607）；Agent 展开是 grow-only（1876-1888）；状态版本栅栏不一致→丢弃走默认（1956-1968）；toolbar 退役改名 `_retired` 防 restoreState 按名复活（2021-2046）；FactorGrid 摘要：`_factor_grid_summary` 用 numpy isfinite 过滤取 min/max/uncertainty（988-1022）——**C++ 承接 FactorGrid.statistics 的样例**；layout 保存 350ms 去抖+isVisible 守卫。

## paleo_workbench/ui/workstation/stage_actions.py（2035 行）
- 公开符号：re-export `STAGE_ACTION_TOOLS/STAGE_CONTEXT_ACTIONS/stage_context_actions`（单一真源在 mapping_workspace.stage_vocabulary，stage_actions.py:39-44）、`facies_category_color`（取色优先级：要素 color>geological_symbols>md5 哈希回退调色板 63-87）、`_categorized_facies_style`（相名分桶→VectorStyle categorized+图案+标注，90-168）、`StageActionDispatcher`（宿主=composite）：`dispatch`（`_REQUIRES_HORIZON` 19 动作未设层位拒绝；未知动作报错；异常→「阶段动作失败（id）：exc」绝不静默，203-239）+ 22 个 handler（load_initial_facies/run_*_mock/add_*_overlay/point_to_surface/toggle_prediction_confidence/create_facies_draft/open_factor_workbench/overlay_factor_results/create_constraint/commit_constraints/select_evidence/freeze_evidence_set/create_integrated_draft/create_integrated_boundary/run_fusion/run_qa/commit_interpretation/assemble_map_product/stage_save）。
- 用户任务：三阶段编图动作的全部编排逻辑（图层创建/角色注册/溯源钉住/目录版本提交/mock 预测生成）；科学算法复用 production service。
- 关键依赖：catalog service（get_catalog_service）、prediction（inference_service/mock_facies）、workflow.interpretation（compilation/evidence/integrated_interpretation/revision）、map_product、factor_layer_products、`peek_live_factor_grid`、mapping_workspace（stage_controller/group_controller/state.set_maturity）。
- C++ 承接建议：这是编图动作编排层——Qt 依赖极少（两处 QInputDialog）；建议 Qt-free 核心+宿主注入对话框钩子；大量中文 status 文案是 oracle。
- 分支与边界（oracle 候选）：图层角色幂等（已存在→「已在图层树/草稿已存在」短消息）；mock 预测失败三态（异常/None result/中间登记失败主结果保留，479-505）；叠加幂等按 role+factor_task_id 判定（880-958）；融合前置三拒绝（未冻结/空/无 factor 条目 1592-1604）；run_qa 验证器崩溃转 error issue 不假「QA 通过」（1710-1721）；stage_save 消息聚合提交数/回填数/修订数（1909-1930）；commit 失败「不伪称已提交」（1255-1257,1815-1818）；_classify_prediction_task 优先 input_refs 键值非空、名称只兜底（857-878）。

## paleo_workbench/ui/workstation/composite_editing.py（4064 行）★ 编辑控制器核心
- 公开符号：`GEOMETRY_KINDS/GEOMETRY_KIND_LABELS`、`GEO_TEMPLATES` 11 个地质模板（well_point/fault/facies×3 级/source/spreading/break/direction/extent，各带字段 schema+样式，composite_editing.py:189-317）、`TemplateField/GeoTemplate/schema_fields/fields_to_schema/template_by_key`、`FACIES_TEMPLATE_KEYS`、`is_facies_family_layer`（模板或角色任一命中，341-355）、`pick_topmost_visible_layer_id`（纯函数）、`EditTargetSnapshot`（V11 五目标模型+divergent，630-654）、`CompositeEditController(QObject)` — 信号 layers_changed/content_changed(str)/sessions_committed/native_join_refused(str)/geology_blocked/feature_captured(str,str)/state_changed。
- 用户任务：QGIS 式矢量编辑全部语义——图层 CRUD（模板建层/复制/删除）、编辑会话（Python VectorEditSession 与 QGIS 镜像原生会话双轨）、数字化工具装配（pan/zoom/identify/select/add_*/move/vertex/reshape/add_ring/add_part/fault_cut/boundary_reshape + V12 shape 工具）、几何命令（split/merge/explode/collect/ring-part/rotate/scale/copy-paste/trim/extend/snap/simplify…）、拓扑门禁、捕捉配置下推、快照发布与 tool_context_inputs 采集。
- 关键依赖：mapping（map_tools/SnappingService/TopologyService/VectorLayer/vector_operations/geometry_*）、NativeEditSessionController（镜像编辑）、qgis_render_bridge（capability_manifest/geometry 算子）、capture_spec/snapping_profiles（角色语义）、pyproj（CRS 真校验，471-496）。
- C++ 承接建议：控制器本身 Qt 依赖极薄（QObject 信号而已）→ 可做 Qt-free 核心+信号；QGIS 原生会话路径在 C++ 更自然（直接 QgsMapCanvas/QgsVectorLayer 编辑）；GEO_TEMPLATES 表直移植。
- 分支与边界（oracle 候选密集）：门禁单点 `_edit_gate`（所有会话起点与 flush 必经，733-752）；`ensure_layer_session` 原生会话期间拒开第二会话「请先保存或回滚编辑」（1551-1554）；CRS 域门禁 #1285（失配阻止进入编辑+apply_crs_fix declare_local/clear，1566-1601）；会话内 CRS 冻结（1603-1611）；flush 全或无两阶段（门禁/拓扑先全判，提交中途失败→剩余回滚+blocked 诚实区分，2064-2130）；`save_edits` 拓扑失败列前 3 offender+「另有 N 个问题」（1752-1763）；地质不变量门 error 拦截/warning 经信号放行（1779-1802）；快照 role 优先序（layer metadata>stage membership>控制器登记，3800-3812）与 `_SNAPSHOT_ROLELESS` 不落 role（366-368）；`tool_context_inputs` 的 dirty 双轨/split/merge/reshape_ready 定义（3955-3992）；捕捉下推 endpoint/intersection 未在桥 manifest 声明时告警不静默（2547-2573）；`set_snapping_config` 返回 False→捕捉降级关闭（2633-2637）；paste CRS 不同拒绝不静默重投影（3012-3015）；删除/复制 N 选一宏一 undo（3674-3710）。

## paleo_workbench/ui/workstation/composite_document.py（5435 行）★ 编图文档宿主
- 公开符号：`_identify_popup_text`（纯函数：≤5 行「图层名：主属性」+超出「共 N 项 · 详见识别结果面板」，184-202）、`_layer_kind_icon`（QPainter 画 16px 几何图标，266-294）、`_decoration_color`（tone→palette 键，298-318）、`_LayerPropertiesAdapter`、`LayerManagerPanel(QFrame)`（回退画布图层树：17 个请求信号、差分 `_reload`、状态装饰列、勾选回调禁重建树防 use-after-free SIGSEGV，864-874）、`InputTreePanel`、`LinkedViewsPanel`（诚实空态）、`CompositeDocument(QWidget)` — 中央画布+2 地图工具条+全部面板实例；信号 object_selected/status_message/well_track_toggled/seismic_section_toggled/link_toggled/hub_page_requested。
- 用户任务：编图中央文档——画布（原生 QgisCanvasShim 优先/桥缺→UnifiedMapCanvas 诚实降级，1434-1459）、时间轴、约束因子 HUD、识别结果、拓扑面板、QC 向导、状态条、编辑控制器装配（门禁/角色注入 1096-1117）、相带画刷/吸色管/调色板（1119-1153）、引用图层、阶段控制器与 StageActionDispatcher、epoch timeline、模式 FSM+键位、工具条与面板菜单。
- 关键依赖：canvas_shim/unified_map_canvas、MapActionController、MapLayerPropertiesDialog、MapStatusBar、MappingStageController、tool_availability/build_tool_context、reference_layers、workarea_map_snapshot、constraint_factor_hud（HUD！1038-1055：`HudController.bind(hud, factor_grid_provider, wells_provider)`+`map_position_changed→handle_position`）、peek_live_factor_grid（HUD 网格缓存 `_refresh_hud_grid_cache`：按「砂地」名匹配候选或 tasks[-1:]，5363-5388）。
- **对 conv-16 最要紧**：(a) 工具条两组 `_toolbar_top_groups`（navigate/selection/inspection/edit_session/capture）与 `_toolbar_bottom_groups`（geometry/snapping/layer/symbology/factor/qa/layout_export），两条 QToolBar objectName `WorkstationMapToolsToolbarTop/Bottom`（2169-2199）；(b) `_apply_tool_availability`（1876-1933）把 evaluator 结论写 QAction+preferred 属性+分隔符重算 `_sync_toolbar_separators`（2001-2042 幂等算法）；(c) `_role_allows_editing` 三门禁（RAW/冻结发布/组证据锁，3603-3645）是编辑门禁真源；(d) `layer_domain_status`（3441-3502）= inspector context seam 数据源（角色/成熟度/可编辑/新鲜度/数据来源/几何/CRS/编辑/已选/推荐动作）；(e) 状态条 `apply_context` 全读 tool_context（3148-3188）；(f) `_sync_composition_now` 组装顺序 基础→引用→编修（5232-5283）+repush_canvas_current_layer 兜底；(g) 面板菜单 `register_panel_actions`（显示面板/布局预设/全部浮动/全部停靠/捕捉设置/恢复默认，2260-2289）。
- 分支与边界（oracle 候选）：画布构造先探测后构造（桥缺失二次构造访问冲突，1441-1449）；空态提示三条件（无编修/无引用/无工程内容 3101-3120）+等值守卫防无限递归（3128-3138）；测距 NaN→「测距: 无效」、椭球/测地/平面标注（2891-2982）；切层先提交其它会话 `_commit_other_open_sessions`（3817-3844）；`_apply_active_target` None 也必须清目标（3426-3439）；duplicate RAW→INITIAL_FACIES_DRAFT/USER_GENERAL 分派+镜像验货（3277-3381）；引用层 CRS 不一致扣发「（坐标系不一致，未叠加）」（4311-4345）；换相读事实源原生会话读镜像缓冲（4954-4978）；样式只接管 managed renderer（5043-5097）；HUD 只在装载时刷新缓存 D7。

# qgis_stack/

## paleo_workbench/ui/qgis_stack/__init__.py（8 行）
- 公开符号：QgisCanvasHost、QgisDisplayCanvas、create_display_canvas（qgis_stack/__init__.py:2-8）。
- C++ 承接：C++ 里原生 Qgs 即本地类，此包整体消解。

## paleo_workbench/ui/qgis_stack/mirror.py（10 行）
- 公开符号：`mirror_snapshot_to_stack`（兼容 re-export，真身在 mapping/qgis_mirror——M7 分层：镜像同步是文档域工作非 UI 域，mirror.py:1-5）。
- C++ 承接：直接在 C++ 文档域实现 snapshot→QgsProject 同步。

## paleo_workbench/ui/qgis_stack/events.py（47 行）
- 公开符号：`StackEvents(QObject)` — extent_changed(float×4)/map_position_changed(float×2)；`attach` 注册桥回调；`_requeue` 经 `QTimer.singleShot(0, context, …)` 带 context 重排队（events.py:33-38）。
- 用户任务：桥回调→Qt Signal 的重排队层（避免在桥调用栈深处触发槽）。
- C++ 承接：C++ 里桥回调可直接 Qt signal（同线程 QueuedConnection 即可）；带 context 防死对象发射的教训同款适用。
- 分支与边界：析构后定时器唤醒→带 context 取消投递+RuntimeError 双守卫（#951 根因类，1-9）。

## paleo_workbench/ui/qgis_stack/widgets.py（121 行）
- 公开符号：`cpp_pointer/wrap_widget`（地址↔控件唯一转换点）、`canvas_viewport`（三层回退：viewport()→QGraphicsView wrap→找 qt_scrollarea_viewport）、`as_tree_view`、`configure_layer_tree_view`（branch QSS+expandAllNodes）、`QgisCanvasHost`（create_canvas→wrapInstance→布局内嵌）、`QgisLayerTreeHost`（create_layer_tree_view）。
- C++ 承接：全部消解——C++ 直接持有 QgsMapCanvas*/QgsLayerTreeView*。
- 分支与边界：shiboken 同地址只认首次 wrap 类型（viewport 二次回退的原因，canvas_viewport 注释）；图层树箭头 QSS 路径含 map/tree-branch-*.svg。

## paleo_workbench/ui/qgis_stack/tree_sync.py（144 行）
- 公开符号：`TreeChangeSet`（visibility/order/renames legacy 平铺）、`TreeEvent`（visibility|rename × layer|group）、`TreeChangeBatch`（schema2：changes+events+tree 结构快照+revision，V11 树修订号 0=旧桥恒通过）、`parse_tree_change`/`parse_tree_events`。
- 关键依赖：C++ 桥 `set_tree_change_callback` payload 契约（native/qgis_render_bridge/src/map_stack_service.cpp flushTreeChange，tree_sync.py:3-24）。
- C++ 承接：C++ 中直接结构体传递，JSON 层消解；但「结构变化才带 tree」「revision 门控过期回声」语义保留。
- 分支与边界：坏 JSON/非 dict→空集（不抛）；visibility value 强转 bool、rename 强转 str；revision≤已应用值→丢弃。

## paleo_workbench/ui/qgis_stack/display_canvas.py（337 行）
- 公开符号：`create_display_canvas`（先探测后构造，ImportError→UnifiedMapCanvas）、`QgisDisplayCanvas`（自有 QgsProject 只读预览画布）：信号 extent_changed/map_position_changed/backend_status_changed/map_clicked/tool_operation；extent 历史 100 条、zoom_by 钳正、mirror failures→backend_status「qgis: degraded (N mirror failures)」（253-259）、shutdown/destroyed 记账分离。
- 用户任务：首页/工区/编图预览的只读 QGIS 画布。
- 分支与边界：click 判定 manhattanLength<6（53）；析构期不 shutdown 整栈只记账（147-152）；programmatic extent 消费防回声。

## paleo_workbench/ui/qgis_stack/layer_tree_panel.py（778 行）
- 公开符号：`QgisLayerTreePanel(QWidget)` — 18 个信号与 LayerManagerPanel 同构（无 rename_layer_requested：树上改名直接生效）；`_MENU_SIGNALS` 16 键映射、`_MENU_GATED_TEXTS` 按文案匹配门禁项、`_RAW_DRAFT_MENU_TEXT="复制为草稿…"`；方法 bind（挂 tree_selection/tree_change/tree_menu 三回调+contextMenuAboutToShow）、set_layer_decorations→`set_row_indicators` 原生行指示器（能力门控+失败仅日志 218-242）、set_group_summaries（问题组前 4+「N 层 · 组状态正常」/「暂无图层」）、`_push_mirror_order`（组装序反转→top-first；组模式返回 False 426-449）、`_on_tree_change`（V13 W-P：用户勾选落阶段视图覆盖层；revision 门控 715）、`_apply_menu_gating`（判词→禁用+tooltip；补 3 个 C++ 菜单缺口动作 527-646）、`_remove_gate`（RAW 可删）。
- 用户任务：QgsLayerTreeView 承载的图层面板——树操作直接落 QgsProject，经回调回写 `_layers` 再落持久化权威。
- C++ 承接：C++ 版是「QgsLayerTreeView+自建菜单 provider」原生化；Python 版补菜单缺口的 contextMenuAboutToShow 技法在 C++ 直接在 provider 里实现。
- 分支与边界：`_publishing`/`reconciling` 双抑制防程序化重排被当作用户切层（453-463）；echo order 必须 reversed（top-first vs 组装序，701-709）；旧桥无 contextMenuAboutToShow 诚实跳过；menu tooltips 必须 setToolTipsVisible(True)。

## paleo_workbench/ui/qgis_stack/canvas_shim.py（1840 行）★ 原生画布适配器
- 公开符号：`shutdown_live_shims()`（进程级 WeakSet 清理）、`bridge_available()`（缓存 find_spec）、`_bridge_features()`（capability_manifest 进程缓存）、`_CanvasMouseRouter`（measure 激活期视口鼠标→Python 工具）、`_ScaleChrome/_NorthChrome/_LegendChrome`（比例尺/指北针/图例 overlay，画在 viewport 上）、`dispatch_edit_pick`（模块级 edit-pick 分发：vertex_moved/feature_moved/vertex_inserted/deleted/rejected/snap_feedback，298-374）、`QgisCanvasShim(QWidget)` — 13 信号（extent_changed/map_position_changed/backend_status_changed/tool_operation/native_identified/measure_segment/measure_preview/measure_updated/snap_feedback/capture_progress/measure_canceled/commit_rejected/native_tool_activation_failed/canvas_context_menu/status_hint）+全量方法（set_extent/zoom_by/#1165 有限性守卫/set_snapping_config/set_current_layer 显式清除语义/current_layer_doc_id 读回权威/set_map_tool_controller 工具包装路由/map_scale/destination_crs/map_units/output_dpi/mirror_provider_facts/export_png(重入哨兵+5s 超时)/export_svg/pdf/set_layer_snapshot(changed_hints)/shutdown）。
- 用户任务：QGIS 原生画布与宿主的全部适配——extent 历史与 programmatic 去重、工具映射（12 种 kind 表，1239-1266）、digitize/edit_pick/selection/measure 四回调接线、镜像发布与失败诊断、导出。
- C++ 承接：**conv-16 在 C++ 中此文件大半消解**（直接调用 QgsMapCanvas API）；需要保留的语义：extent 历史去重、工具 checked 一致性（native_tool_activation_failed→回退 pan）、commit 拒绝必须可感知（无声死键禁令）、mirror failures→backend_status、`_LIVE_SHIMS` 对应的进程级 QgsProject 污染防护。
- 分支与边界（oracle 候选）：半构造防护 `_canvas_created`（423-427）；`_is_fitted_compatible` aspect-fit 容差匹配（530-542）；zoom factor 非有限 raise（740-743）；vertex 无编辑目标提示按内容去重（283-295）；pick_miss 不提示（正常点空白）；vertex_no_move→status_hint「单击不移动节点：拖动以编辑顶点位置」（1393-1400）；测量降级告警一次（1289-1297）；析构期 `_mark_disposed` 纯记账绝不进桥/QGIS（1822-1831）；#1156 删除 update() 重载防重入。

# ui 顶层（5 个）

## paleo_workbench/ui/dock_framework.py（352 行）★ dock 描述符权威
- 公开符号：`DockImportance`（CORE/SECONDARY/UTILITY）、`AREA_LEFT/RIGHT/BOTTOM`（Qt-free 字符串）、`DockDescriptor`（frozen：dock_id/title/preferred_area/importance/default_visible/**can_float**（GL 内容 False——EGL segfault 类，dock_framework.py:49-51）/can_tabify/min_floating_size(220,160)/preferred_size/preferred_height/workflow_tags/context_tags/object_name 自动 `WorkstationDock_{title}` 保 saveState 兼容 62-66）、`WORKSTATION_DOCKS` 14 dock 描述符（70-205，顺序=canonical 应用序：nav/mapping_stage 左、inspector/composite_layer/facies_palette/hub 右、hub+well+seismic can_float=False）、`DockRegistry`（get/require/by_tag；重复 dock_id raise）、`ensure_dock_usable`（grow-only resize，isFloating/不可见→False，239-258）、`apply_first_run_sizes`（仅首运行/显式重置合法，261-313）、`ViewportClass`（COMPACT<1100/NORMAL/WIDE≥1600/ULTRAWIDE≥2200 逻辑像素）、`INSPECTOR_HIDE_BELOW=1100/RESTORE_ABOVE=1200`（滞回带）、`COMMAND_INPUT_FLOOR_COMPACT=220/NORMAL=300`、`classify_viewport`。
- C++ 承接建议：**原样移植为 C++ 数据结构**（struct+静态表+自由函数，Qt-free 数据层）——这是 conv-16 dock 系统的单一词表；缩放权威规则（resizeDocks 只许首运行/重置/grow-only）必须写成注释+测试。
- 分支与边界：objectName 保历史方案否则持久化布局失配；viewport 阈值是逻辑像素（1366@125%≈1093→COMPACT）。

## paleo_workbench/ui/dock_manager.py（183 行）
- 公开符号：`WorkspacePreset`（well_log/map_authoring/workstation_composite/workstation_interpretation）、`DockPanelConfig/WorkspaceLayout`、`DockManager`（默认 4 preset 注册；panel-id 注册表 seed 自 preset+layout_presets；`panel_title` 先精确 id 再 ':' 后缀；`register_panel` 对已有 id 仅改名不换配置）、单例 `dock_manager`。
- 用户任务：工作区预设与面板 id→标题词表（FloatController 浮窗标题来源）。
- C++ 承接：Qt-free 数据类直移植；与 layout_presets 的同步注册（register_with_dock_manager）保留。
- 分支与边界：id 冲突 first-registration-wins；已有 id 的 area/visible 静默忽略（155-159）。

## paleo_workbench/ui/navigation.py（79 行）
- 公开符号：`PAGE_INDEX_DATA=0/WELL=1/SEISMIC=2/MAPPING=3/VISUALIZATION=4`、`HUB_NAMES=["数据","井","地震","编图","可视化"]`、`SUBMODULES`（hub→[(key,title)]）、`DEFAULT_SUBMODULE`、`submodule_keys/submodule_title`、`LEGACY_PAGE_TO_HUB`（旧 0-10 页→hub 映射，67-79）。
- C++ 承接：常量表直移植（Qt-free）。

## paleo_workbench/ui/command_registry.py（231 行）
- 公开符号：`CommandSpec`（id/label/hint/keywords/shortcut_hint/callback/group/context_tags/stages/requires_write/hidden_when_unavailable/applicability 谓词）、`CommandAvailability(enabled,reason)`、`CommandRegistry`（register 幂等替换/unregister/clear(keep_core)/specs 排序/evaluate/find/recents QSettings 持久化 `_RECENT_MAX=8`）、单例 `command_registry`、`_subsequence_score`（子序列起始索引评分，弱匹配+10、前缀命中-5）。
- 用户任务：命令面板唯一真源——导航/主题/密度/preset/面板显隐/阶段动作/编图工具全部注册于此。
- 关键依赖：`stage_whitelist_reason`（V10 M10 判词真源同一）、UIContextSnapshot 鸭子类型。
- C++ 承接：Qt-free 核心（QSettings 除外）直移植；evaluate 判定序=存在性→WRITE→阶段白名单（fail-closed「当前编图阶段未知」）→领域谓词（崩溃按不可用「无法判定可用性」）。
- 分支与边界：禁用必须带人类可读原因；hidden_when_unavailable 不可用命令从 find 移除但默认保留可发现性。

## paleo_workbench/ui/app_shell.py（1512 行）
- 公开符号：`CommandPalette(QFrame)`（360×320 非模态子部件 offscreen 安全；空查询最近使用置顶；禁用命令灰显+原因+不可激活；map: 命令挂 action_help 全量解释 tooltip，app_shell.py:69-239）、`AdaptivePageStack`（minimumSizeHint 只取当前页，242-273）、`AppShell(QWidget)` — 信号 new/open/save/properties/about/preview_settings_requested；构造=5 hub 页栈+WorkstationFrame（dock_host 注入 399-408）+StatusBar（有宿主占 QMainWindow 原生状态栏槽 421-430）+UIContextService 装配 `_wire_ui_context`（约 40 个 provider，648-940）+`_register_commands`（nav:/core:preset/core:inspector/core:theme/core:density/core:palette/core:panel.*，942-1046）+快捷键（hub 1-5/Alt+1-3/Ctrl+K/Ctrl+Alt+D/F5/F1）+`_wire_seismic_cursor_producer`（复合 locate sink L8/L10）。
- 用户任务：应用壳——hub 导航、Ctrl+K 面板、UIContext 派生、页面延迟绑定（`_run_or_defer_page_update` hub 键控）、工程切换 shutdown（`shutdown_workers` 每页 wait_ms 预算）。
- 关键依赖：theme_manager（#1047 单一主题系统：shell 级+app 级双 setStyleSheet 1087-1095）、ViewCoordinationController/SelectionContext/CoordinateTransformHub、OperationRegistry（bind_registry_to_shell）、WorkstationFrame、navigation/command_registry/shortcuts。
- C++ 承接：新 Qt widget 直译；**注意三条 offscreen/GL 教训**：首次落地不用 fade（graphics effect 强制隐藏兄弟页 QOpenGLWidget 提前 initializeGL，offscreen 死在 pyqtgraph，498-504,1097-1102）；`isHidden` 而非 `isVisible` 判 palette 开关（1049-1052）；数字键在绘图激活期归画刷双保险（1068-1081）。
- 分支与边界（oracle 候选）：agent 命令路由 marker 表（「打开/显示/生成…」→agent，其余→palette，538-551）；running_task_count 口径=QUEUED+RUNNING（806-816）；阶段动作可用性签名差分（15 字段，901-920）；`_PAGE_FADE_ENABLED` env 开关；状态栏宿主摘除防堆叠（1292-1298）。

# C++ 侧

## apps/paleo_workbench_platform/main.cpp（339 行）
- 公开符号：`makeFixtureGpkg`（memory layer→真 GeoPackage，QgsVectorFileWriter）、`runSelfCheck()`（`--self-check`：窗口 offscreen 创建→loadFixtures→provider/CRS 校验（featureCount==3、EPSG:4326 双断言）→QgsMapRendererParallelJob 同步渲染 800×600 非空白校验→LayoutService PNG 导出→(PWB_WITH_WELL_LOG)LAS dock→(PWB_WITH_DATA_INTEGRATION)newProject/openVectorLayer/edit/start_editing+move_vertex+commitActiveLayer→catalog.json 存在→(M3)SEG-Y 导入→RMS 属性 run 轮询→slice viewer ok 态）、`main`（QgsApplication+QgisRuntime::acquire/release RAII）。
- 用户任务：C++ 平台入口+headless 冒烟（CTest/包冒烟用，「failures print diagnostics, never fake success」main.cpp:5-8）。
- C++ 承接建议：conv-16 直接在此模式上扩 MainWindow；oracle 口径=自检退出码+诊断文案。
- 分支与边界：未显示窗口 widget->grab 不确定→用 parallel job 渲染（120-124）；LAS/SGY fixture 缺失→跳过不报错（dev tree only）。

## apps/paleo_workbench_platform/main_window.hpp（208 行）
- 公开符号：`pwb::app::MainWindow : QMainWindow` — session_/actions_(ToolActionSet)/canvas_/tree_/status_label_/project_store_/seismic_dock_/slice_widget_/attribute_runner_/四个 QgsMapTool*；`facts_`（map<layer_id, DomainLayerFacts>——模块级写权限权威，B 绑定接入后让位）；`setDirtyCloseResponder/setDiscardConfirmResponder`（std::function 注入使 offscreen 测试可脚本化 87-93）；`actionWired/governedAction`（wiring 审计面）；`refreshActionStates()` public（外部编辑路径后刷新判决）；`DirtyCloseDecision` 枚举。
- C++ 承接建议：conv-16 的 MainWindow 扩展基座——**测试注入 responder 的模式**（QMessageBox 不可 offscreen 测试）是 C++ oracle 的标准做法，必须沿用。
- 分支与边界：析构序敏感（session_->close() 必须在成员析构前，196-205 注释记录 segfault）。

## apps/paleo_workbench_platform/main_window.cpp（1302 行）
- 现有 MainWindow 结构（conv-16 关注点）：**dock 现状=3 个**——`layer-tree-dock`（左，QgsLayerTreeView 经 MapSession::createLayerTree，main_window.cpp:212-216）、`well-log-dock`（右，PWB_WITH_WELL_LOG，224-229）、`seismic-dock`（右，SeismicSliceWidget，232-237）；中央=QgsMapCanvas（208-210）；状态栏=QLabel「ready」→「工具可用 %1/%2」（397-407）。**注册方式=直接 addDockWidget，无描述符/无预设/无持久化**。菜单/工具条=14 个 Wire{id,text,shortcut}（261-282），QAction 全部由 `pwb::tool_policy::evaluate_all(session_->snapshot())` 判决物化（refreshActionStates 391-395）——menu/toolbar/shortcut 共享同一 QAction，「one policy verdict drives every surface」（hpp:6-8）。`ToolActionSet::apply` 纯投影（enabled/checked/visible/tooltip=disabled_reason/statusTip；checked verdict 先 setCheckable(true)，tool_actions.cpp:26-36）。
- 操作集：openVector/openRaster/openProject（B store+日志恢复+工作副本 materialize `.pwb-working/`，600-710）/newProject（文档工厂+空 catalog+bootstrap asset 走 run 生命周期，499-598）/importSegy（PWBVOL1 publish）/runAttribute（注册 kernel 表）/toggleEditing（dirty 停止走三选一）/saveEdits（stage_commit+sha256 短消息）/rollback（确认）/undo/redo/vertex 工具（自绘 VertexMoveMapTool：12px×mupp 容差最近顶点+QgsVertexMarker+EditController::move_vertex 可撤销，73-152）/exportLayout/closeEvent（脏关闭三选一；保存失败→取消关闭+状态条消息非模态，862-894）。
- C++ 承接建议：conv-16 加 dock 的路径已清晰——(1) QDockWidget+setObjectName+addDockWidget；(2) 动作经 ToolPolicy evaluate_all→ToolActionSet.apply；(3) 测试经 responder 注入+findChild(objectName)。**缺口**：无 saveState/restoreState、无预设、无 grow-only resize、无 responsive 折叠——Python dock_framework/shell 的这些语义是 conv-16 要补的。
- 分支与边界（oracle 候选）：每窗口一工程（「已有工程打开」501-503,601-603）；文件名安全化保留 CJK（505-512）；recovery pending/rolled_back 计数进状态条 summary（698-705）；working copy 复制失败→skipped+first_error；dirty 停止编辑=同 dirty-close 三选一（739-761）。

## apps/paleo_workbench_platform/CMakeLists.txt（43 行）
- 目标：`pwb-platform` exe（AUTOMOC、cxx_std_20），链接 Pwb::Application + Pwb::Ui；BUILD_RPATH=QGIS vendor bin；可选 feature link：Pwb::VisualizationWellLog→PWB_WITH_WELL_LOG、Pwb::SeismicViewer→PWB_WITH_SEISMIC_VIEWER、Pwb::SeismicAttributes(+Data/Science/Workflow)→PWB_WITH_SEISMIC_ATTRIBUTES、Pwb::SeismicIo(+Data)→PWB_WITH_SEISMIC_IO；PWB_SOURCE_DIR 编译定义给自检 fixture。
- C++ 承接：conv-16 新增 dock/面板源文件直接加进 add_executable 源表；新面板库若独立则仿 libs/ui 的 alias 模式。

## libs/ui/CMakeLists.txt（8 行）
- `pwb_ui` STATIC（src/tool_actions.cpp）→ ALIAS Pwb::Ui；PUBLIC include include/；链接 Pwb::ToolPolicy + Qt6::Widgets（PUBLIC）。
- C++ 承接：conv-16 的新 UI 库（如 pwb_workstation_ui）照此模式（STATIC+ALIAS+PUBLIC ToolPolicy+Qt6::Widgets）。

## libs/ui/include/pwb/ui/tool_actions.hpp（43 行）+ src/tool_actions.cpp（72 行）
- 公开符号：`pwb::ui::ToolActionSet` — apply(availability map)（每 verdict 一 QAction，objectName=tool_id，析构自 delete）、action/action_ids、action_enabled/checked/visible/tooltip（parity 读回面）。
- 用户任务：ToolPolicy 判决→QAction 的呈现适配器，「never grows a second gate rule」（hpp:3-6）。
- C++ 承接：已是 V8 canonical evaluator 契约的 C++ 对应物；conv-16 的面板/工具条动作必须继续走它而不是自建 gate。
- 分支与边界：checked verdict→setCheckable(true) 提升（29）；tooltip 与 statusTip 同为 disabled_reason（33-36）；空 reason→空 tooltip。

# cpp-platform 文档

## docs/development/cpp-platform/v3-contracts.md（68 行）★ v3 冻结契约
- 核心约束：一进程一 Qt（Linux 实测 Qt 6.11.2 系统包，PWB_QT_PREFIX fail-closed）；QGIS SDK 只读 imported targets（PwbQgis::Core/Gui/Analysis）；QgsApplication（非 QApplication）+ QgisRuntime acquire/release 恰好一次；**QgsProject 一律 session-owned，QgsProject::instance() 禁止出现在生产代码**（v3-contracts.md:14）。公共 target：Pwb::ToolPolicy（Qt-free，golden 与 Python 28×77 全等）/Pwb::Qgis/Pwb::Application/Pwb::Ui（ToolActionSet）/pwb-platform。UI 契约（platform.ui_wiring 强制）：菜单/工具栏/快捷键同一批 QAction；每个 wired 动作必须真实连接处理器（actionWired 审计）；dirty-close 三态+「保存失败不得销毁编辑」强断言，测试经 setDirtyCloseResponder/setDiscardConfirmResponder 注入（26-31）。EditDeltaV1 键=字段名；commit 拓扑门失败→会话保留可修复。join key `pwb/layer_id` 等（§6）。D/E 开关 fail-closed（§7）。
- 对 conv-16 UI 面板承接清单的要求：**新面板动作必须接入 evaluate_all→QAction 单源投影**；不许第二规则源；dock/widget 注册走既有 target（Pwb::Ui 扩展或新 lib）。

## docs/development/cpp-platform/v3-verification.md（95 行）
- 核心证据：platform.* 9/9（toolpolicy_matrix/golden 28×77 全等、qgis_smoke 真 GPKG+GeoTIFF 渲染非空白、edit_cycle bowtie 阻断、lifecycle 20×0 crash、export_layout 内容级、adapters_substitutes、ui_wiring 动作真实入栏+dirty-close 三态、qgis_smoke_app self-check exit 0）；integrated 45/45→47/47→48/48（§4a 表：P1 发布假成功/保存顺序 stage()/finalize() 拆分/operation ID 唯一化）。
- 对 conv-16 的验收口径：**测试=独立 exe+轻量断言宏，offscreen，headless 无截图以动作触发断言替代**（§6 未执行清单诚实记录）；C++ 侧新增 UI 测试沿用该模式（注入 responder、findChild objectName）。
- 技术根因清单（§5）conv-16 必读：QgsApplication 必须 3 参构造且为应用对象；QGIS 4.x getFeature 返回值式；offscreen 未 show 窗口 grab 不确定→并行渲染 job；双 sqlite3 符号抢占→-fvisibility=hidden；MainWindow 成员逆序析构 UAF。

## docs/development/cpp-platform/v3-runtime-manifest.md（83 行）
- 实测 ABI 表（Qt 6.11.2/GCC 16.2.1/CMake 4.4.3/QGIS 4.2.0 vendored/内存门禁 ≥8GiB exit 75）；QGIS SDK Linux 布局差异（lib/qgis/plugins、系统 /usr/share/proj）；pwb_tool_policy/pwb_qgis/pwb_application/pwb_ui/pwb-platform 实编产物；9 测试证据；9 条首编修复记录（§5——namespace 内 QWidget 前置声明陷阱等）。

## docs/development/cpp-platform/00-baseline.md（60 行）
- Windows ABI 冻结（Qt 6.8.0/MSVC 14.38——被 Linux 实测补充而非推翻）；QGIS SDK 只读消费判据；进程内生命周期：setPrefixPath→init→initQgis 恰好一次（重复=abort）；session-owned QgsProject+QgsLayerTreeMapCanvasBridge；关闭顺序 map tool unset→setLayers({})→setProject(nullptr)→removeAllMapLayers→析构→exitQgis（§5）——conv-16 dock/widget 析构必须落在此序内。

## docs/development/cpp-platform/01-contracts.md（104 行）
- v1 契约：target 职责表；MapSession createCanvas/createLayerTree；EditDeltaV1/StagedAsset 结构；IProjectStore/IResultPublisher adapter 接口；**ToolPolicy：ToolContextSnapshot 与 Python ToolContext contract_version=4 同字段集（60 字段含三态 optional bool），evaluate_tool 返回 ToolAvailability{visible,enabled,checked,disabled_reason,preferred,severity,remediation}，规则 1:1 移植 tool_availability.py，QAction/菜单/快捷键只消费结果**（§6）；native 路径固定 native_canvas_available=true（无 fallback 画布概念）——C++ 无需 UnifiedMapCanvas 双轨。

## docs/development/cpp-platform/04-runtime-manifest.md（51 行）+ 05-build-and-run.md（47 行）
- v2 Windows 计划值闭包清单（QGIS SDK 89 DLL/plugins/data/share/proj、Qt DLL 集、QT_QPA_PLATFORM=offscreen、PROJ_LIB/GDAL_DATA）；构建经 Invoke-PlatformBuild.ps1 资源门禁；链接审计 Oracle 1（dumpbin 无 python/pyside/shiboken/qgis_render_bridge）。

## docs/development/cpp-platform/02-test-plan.md（66 行）+ 03-progress.md（28 行）+ ledger.md（18 行）+ v3-handoff.md（52 行）+ v3-integration-verification.md（84 行）+ v3-ledger.md（31 行）
- 02：CTest `platform.` 前缀、0 tests 不算通过、轻量自研断言宏+独立 exe、每测试 timeout 180s、`--no-tests=error`；T3 action_parity（QAction 状态==policy 输出）。
- v3-handoff §1.4：**嵌入位指引「MainWindow 已有左右 dock 区（图层树左、测井右）；新 viewer dock 接 main_window.cpp，跟随 PWB_WITH_* 编译守卫模式，参考 WLE dock 的 22 行接线」**——conv-16 加 dock 的官方先例。§5 待办 3：「staged 未发布」作为 dirty-close 第二级状态。
- v3-integration-verification §5：集成修复的真实缺陷表（析构 UAF/QAction 所有权/refreshActionStates public 化/layerById 空守卫）。
- v3-ledger：18 轮记录，M1-M5 里程碑（AlgorithmRunner/属性对话框/newProject/SEG-Y/--self-check 全链）；当前 integrated 48/48。

# UX 文档

## docs/development/adaptive-workstation-ui-v9/（9 篇）★ dock/响应式规则权威
- 00-baseline：V9 审计基线——13 dock 全部在 shell 一处构造；454 处 sizing 扫描；P0 问题 B-1（hub dock min=当前页 min）/B-2（约束栈不可行）/B-3（resizeDocks 覆盖用户尺寸）/B-5（GL dock 浮动 EGL segfault 类）；「Already good 保留」清单（原生 dock 无自绘标题栏、版本栅栏持久化、teardown 纪律、min-0/Ignored 模式、token sheet+bind registry）。
- 01-layout-architecture：分层规则（域权威→呈现上下文→自适应壳→面板，「UI 永不重推导科学/工具状态，dock 是 chrome 不是状态」）；V9 五变更：dock 描述符化、resize 权威单一（仅首运行/显式重置/grow-only；预设只切可见性）、viewport 分类+180ms 去抖、内容最小值 advisory 非结构性（仅中央画布 320 与窗口 960×600 是地板）、GL dock 不可浮动。
- 02-dock-system：描述符字段表（dock_id/title/preferred_area/importance/default_visible/can_float/can_tabify/min_floating_size 浮动时才生效/preferred_size 首运行才用/workflow_tags）；resize 正确性契约 6 条（docked min=0；resizeDocks 三个合法调用点；restoreState 后响应式策略去抖重跑；13/13 dock 全接保存信号；运行期屏幕集变化 re-clamp）。
- 03-design-system：tokens.py（1792 行 canonical sheet）+style.bind+theme_manager 三件套保留；**card-avoidance 规则**（新 UI 优先 section header/inline controls/property rows/tree/split/inspector section/status strip，避免 QFrame+border+rounded box 包整面板）；密度 vs viewport 职责分离。
- 04-responsive-rules：硬地板表（窗口 960×600/中央画布 320/Inspector 220/Explorer 180/页侧板 200）；viewport 类与策略（COMPACT<1100 折叠检查器[恢复 ≥1200 滞回]+命令输入地板 220+隐藏层位标签）；规则：viewport 策略≠用户偏好、resize 热路径零布局变更、restore 归一化、降级阶梯（折叠侧板→滚动→绝不阻塞 dock 手柄）。
- 05-workflow-ui-mapping：单一 evaluator → 四表面（工具条/palette/右键/阶段面板）；workflow_tags+阶段 dock_recommendation（仅首次进入建议）；**测试不变式清单**（test_visual_qa_v8/test_dock_framework_v9/test_workstation_context/test_action_help_v8）。
- 06-testing：新测试资产表（test_dock_framework_v9 覆盖 registry 契约/GL 不可浮/viewport 分类/grow-only/preset 只可见性/save wiring 13 dock/去抖响应式/restore 归一化；test_ui_sizing_ratchet_v9 结构棘轮：fixed≥100px、min-width≥400px、QDockWidget 构造点、resizeDocks 权威、不可折叠 splitter、theme-drifted stylesheets）；**语义断言而非像素对比**；分批 pytest 运行清单。
- 07-review-findings：三轮 P0/P1 全修——R2 P0-1 float_all_panels 程序化浮动 GL dock（can_float 必须过滤程序化 setFloating）；R2 P1-1 检查器显隐归因只能走 toggleViewAction().triggered（visibilityChanged 异步不可归因）；R3 P1-1 dock 吸收窗口缩量时帧宽不变→宿主 eventFilter 补触发；R3 P1-2 恢复默认布局必须 50ms 后重应用首运行尺寸；P2-4 管理行文字按钮 360px 地板→Ignored 策略。
- 08-known-limitations：resizeDocks 几何 best-effort（offscreen 常忽略——测试钉请求契约，真机视觉 QA 验证）；主题/密度切换 ~3.2s；offscreen 不能验证 GL 视觉行为；棘轮 allowlist 只减不增。

## docs/development/workstation-ux-v7/（9 篇）
- 00-baseline：V7 起点权威表（CommandRegistry 48 命令 applicability 0 使用；UIContextService 15 字段仅 palette+状态条消费；MapActionController 30 动作无禁用原因；五套树实现并存）；缺陷登记 C1（工具可用性无统一真源 P0）/C2（禁用无原因 P0）/T1（树无状态装饰 P0）等。
- 01-target-state：T1-T13 目标（单一 ToolContext 全表面消费；禁用原因四表面一致同一字符串源；专业分组 IA；图层树全状态装饰禁 emoji；类型化 Inspector；1366×768 支持；性能=显式规模）。
- 02-architecture：**evaluate_tool 八级门序**（capability→context→role[RAW/冻结/stage lock]→stage[hide vs disable 分工：工具条外阶段 hidden，palette disabled+原因]→kind→editing→selection→write，先到先得唯一原因，02-architecture.md §2）；TOOL_GROUPS 12 组；layer_decorations/state_language/tone 桥统一。
- 03-decisions：D1-D17 ADR（可用性真源纯函数；hide vs disable 分工；D12 hub 不再 force-float；D16 像素 diff 永不 CI gate、语义断言 hard-gate；D17 性能声明=结构 bound）。
- 04-implementation-notes/05-verification：114 新测试（test_tool_surface 42 等）；全量 3036 passed 分批验收策略。
- 06-performance：结构 bound 表（1000 层树行复用/装饰推送零 rebuild/可用性求值 O(1)）；extent 轻路径（pan 每帧只刷勾选+状态条——统一可用性与视野无关）。
- 07-review-findings：R1 P0 style_manager 调用签名；R1#4 run_qa 吞崩溃→假 QA 通过；R1#8 attribute_table RAW 只读可查看；R3#1 树装饰对新鲜度变化不反应→stale_summary_changed 接线。
- 08-known-limitations：qgis_render_bridge 未构建时 fallback 画布/树是已验证生产行为；原生树与回退树装饰能力不对等（诚实文档化）；`map:toggle_editing` 不进 palette 的保守选择。

## docs/development/workbench-ux-v11/（14 篇）
- 00-overlap-audit：PR 归属地图（#1267/#1277 不重做）；#1277 已交付 virtual attribute table 等。
- 01-ui-audit：**六路审计发现 A-K 全表**——A1 双图层门禁（原生树无探针→V11 修）；A3 RAW 措辞三处手写→合一；A5 explain() 死路径→接线；C1 井身份 name/id 分裂→总线规范化；C3 selected≠active≠edit target 三层词汇；D2 15 个 item-per-cell 表面排名→Model/View 迁移；E1 38 处静态样式快照；G2 共享状态组件 0 消费。
- 02-information-architecture：六工作域模型；**阶段模型是 Mapping 域内工作流上下文不是页面切换**；B1 rail=explorer 模式非导航（tooltip 词汇化澄清，不加第二导航语义）；B2 编图 hub 三宿主维持（V5 编图页不与中央画布抢 dock 决策固化）。
- 03-ui-context：总线槽位表（selected_layer_id/active_layer_id/edit_target_layer_id/selected_asset_id/selected_version_id/active_survey_id/active_task_id/workflow_stage）+ 井身份 name↔id 双向索引 resolve_well_key；**三个层概念禁止混写**；生命周期纪律（幂等 attach、registry 随 shell 销毁、发布层 changed-only）。
- 04-model-view：共享基础层 ui/modelview/（ObjectTableModel+ColumnSpec、StableSelection、reconcile_widget_items、AsyncQuery epoch/latest-only/迟到拒绝）；15 表面迁移清单；小而固定数据保留 widget 形态的分类决策。
- 05-action-surface：权威链+V11 增量（severity/remediation 字段、原生树探针、阶段面板同因、RAW 措辞合一、explain 接线 palette）；`evaluate_stage_commands` 纯函数。
- 06-inspector：Inspector 2.0 实体覆盖表（Version/Run 新分节、Well 富化、井轨迹缓存 (project id, links 长度)）。
- 07-task-feedback：OperationRegistry 状态机（QUEUED→RUNNING→CANCELLING→COMPLETED|WARNING|FAILED|CANCELLED，终态 FIFO 40 条）+ TaskCenter attach_registry 同表呈现+结果跳转。
- 08-design-system：::item:focus/density token 扩展/FONT_SIZE_MICRO|MINOR/ON_SOLID；tinted_map_icon 仅无彩色 SVG 可染；CANVAS_* 语义 token；词汇=state_language+tone_to_badge。
- 09-accessibility：8 页 tab order 显式链；数字守卫并入 QSpinBox/可编辑 QComboBox/视图编辑器；F5 刷新/F1 帮助=palette；whatsThis 不引入（palette 详情已覆盖）。
- 10-visual-qa：13 场景（V11_SCENARIOS）真实面板+结构检查注册表+grab 非空断言；像素 diff 非门禁。
- 11-performance：结构断言（100k 行 QTableWidgetItem==0 计数、同键差分 beginResetModel==0、10k 键二次同步新建==0、重复发布恰 1 次发射）；AsyncQuery GUI 线程契约。
- 12-known-limitations：L1 CommandRegistry 第二阶段决策残留；L11 原生树菜单门禁经 contextMenuAboutToShow 后处理（桥 API 边界）；L12 井身份索引 bind_project 全量重建。
- 13-verification：85 新断言全绿+全量 7490 passed 对称基座；7 轮评审循环。

# pytest（tests/）

方法说明：全文阅读 8 个最重要文件（下表标★），其余相关文件读文件头+测试函数名清单（grep def test_）并注明。所有 UI 测试均 `qtbot.addWidget` + offscreen（conftest 惯例：不 show 整壳防 offscreen GL 崩溃，test_app_shell.py:124-125）。

## ★ tests/test_app_shell.py（208 行）
- oracle 候选：壳装配五断言（无 ribbon/menu_bar/icon_rail 残留、app_bar objectName、5 hub、默认页 0，test_app_shell.py:7-29）；hub 重入恢复当前子模块（93-100）；palette 总条目≥页面命令数、过滤收敛、激活导航、Esc 双入口关闭（121-185）；Ctrl+K 快捷键存在+toggle（188-200）；导航关闭 palette（203-208）。

## ★ tests/test_dock_framework_v9.py（476 行）★ conv-16 dock 契约主测试
- oracle 候选：registry 14 dock id 全集+objectName 历史方案（71-81）；GL dock（well/seismic/hub）can_float=False（86-90）；viewport 分类 1093→COMPACT/1366→NORMAL/1920→WIDE/2560→ULTRAWIDE（93-97）；ensure_dock_usable grow-only 两情形（103-125）；**preset apply 零 resizeDocks 调用**（128-141）；show_agent 不缩底行（144-159）；hub_dock.widget 是 HubScrollArea 且 min ≤32（165-172）；AdaptivePageStack 逐页最小（175-187）；约束栈 inspector ≤240/explorer ≤200/composite ≤340/窗口 960×600（206-219）；compact 策略三件套（命令输入 ≤220/层位标签隐藏/检查器隐藏）+宽屏恢复（225-245）；resize 后 180ms 内不改布局（248-260）；每个 shell dock visibilityChanged receivers ≥2（266-280）；用户关闭检查器跨会话不弹回（286-321）；首运行默认尺寸真实执行（324-344）；float_all 不浮 GL dock 且仍浮普通 dock（350-372）；手动关闭胜过策略重开（375-405）；宿主 resize 触发策略（411-439）；恢复默认布局重发描述符尺寸 {280,300,420,245}（442-476）。
- 测试基建：autouse fixture 清空全局 QSettings（33-49）——C++ 侧同款「布局 QSettings 无菌」纪律。

## ★ tests/test_design_system.py（132 行）
- oracle 候选：SPACE 刻度 [2,4,8,12,16,24]+legacy 别名 (4,8,12)（11-23）；DENSITY_TOKENS 两模式+compact<comfortable（26-31）；build_qss 密度差异（"24px"/"30px"，34-39）；三主题 palette 必含 SURFACE/SURFACE_RAISED/SURFACE_PANEL/TEXT_MUTED（42-46）；ThemeManager 信号序+持久化键 ui/theme、ui/density（49-87）；style.bind 主题切换重渲染（90-117）；视图菜单是主题生产入口（120-132）。

## ★ tests/test_layer_decorations.py（101 行）
- oracle 候选：干净层无装饰；missing 胜一切且 glyph「✕」；dirty 胜 stale；missing_input>stale>superseded>frozen>published>reviewed 优先序；token 经 state_language 同一实例；hover 摘要含全部信号+「·」分隔；组摘要「12 · 3 · 1 · 2 · 已发布」/干净「5 层 · 无异常」（14-101）。

## ★ tests/test_workstation_shell.py（600 行）
- oracle 候选：默认视图（composite_layer/mapping_stage 可见，input/linked/well/seismic/agent/task 隐藏）（73-81）；dock features 三位（Floatable|Movable|Closable，普通 dock）；well/seismic 无 Floatable（174-183）；同 id 井复用 dock 不复制、异 id 井/震各 spawn 一 dock（215-258，`pwbDockId` 属性检索 207-212）；工具条勾选→dock 显隐（270-291）；explorer 隐藏 meta.json+脚注「存储缓存默认隐藏」（294-311）；agent 计划表三条（314-326）；rail 折叠 tooltip 双向（341-357）；任务中心增量刷新行身份保持+viewport 零常驻 widget（360-437）；inspector 缺失值「—」+missing 属性（440-466）；预设矩阵 composite_default/integrated（469-491）；show_tasks 不连带显示 Agent（494-506）；B18 四 dock 独立（509-543）；LogViewer 2000 行上限+shutdown 摘 handler（546-572）；面板菜单五项（显示面板/布局预设/全部浮动/全部停靠/恢复默认布局，590-600）。

## ★ tests/test_tool_surface.py（578 行，读前 300 行主断言）
- oracle 候选：未知工具「未知工具 'no_such_tool'」fail-closed；无工程全禁+「工程」原因；RAW 原因=edit_gate_reason 原样（单一真源）；phase1 主工具面清单（identify/select/layer_properties/toggle_editing/add_polygon/move/vertex/save/rollback/qa_run）enabled+visible 且 add_line 隐藏带「阶段」原因、factor 组隐藏；phase2 线角色 add_line 主捕获+add_polygon 禁带「线/面」原因（参数化 6 角色）、面角色反转、factor raster 四角色矢量编辑禁+查看面（layer_properties/symbology/layer_export/qa_run）可用；phase3 综合工具面；编辑会话门（save/rollback/add/move/vertex 需会话，snapping 解耦）；选择门（delete 需选择、merge 需 ≥2 兼容面）；split 由 split_ready 覆盖；undo/redo/extent 历史。

## ★ tests/test_inspector_v7.py（174 行）
- oracle 候选：feature 分节行文案（要素 ID/图层/几何=「线」/可编辑=「是」）；缺字段「—」诚实；factor 分节（因素/方法/单位/「10 ~ 220.5」/「0.5 ~ 3.25」/QC「rmse=1.23」/状态/源类型）；空 grid→「—」且无不确定性行；map_product（状态「最终」/「已冻结」/因子输入「3 项」/指纹截断 sha:0123456789a）；staleness 缺席→无新鲜度行；layer kind seam 行。

## ★ tests/test_state_language.py（117 行）
- oracle 候选：maturity raw tone=locked+有 glyph；未知值「未知」muted；未知类别 KeyError；freshness stale=warn/missing=error；task cancelling≠cancelled tone 且中文标签；backend native=ok/fallback=warn；workbench_context_text 四段（阶段·目标·原生·任务数）、被拒目标显原因、无任务不渲染、回退可见（98-101）；AppShell 状态条 workbench_label 非空。

## 其余相关测试（读函数名清单）
- test_tool_surface_integration.py（315）：工具条 12 组齐全；禁用原因进 statusTip；RAW/冻结/factor 门禁流到 QAction；capability 三态；stage palette applicability；tool_requested/command_requested re-gate 拦截。
- test_action_help_v8.py（139）：每工具必有 help；explain 从 evaluator 派生；merge 禁用完整答案；tooltip 仅禁用时带原因+需求；只读工具不 claim 修改。
- test_layout_presets.py（46）：命名 preset 覆盖 composite+interpretation；label 稳定菜单对。
- test_ui_context_model.py（248）：快照默认诚实未知；provider 失败 fail-closed；refresh 差分发射；write gate 两态；阶段白名单禁用带原因；applicability 谓词最后胜；find 不丢禁用项。
- test_mapping_stage_ui.py（327）：层位先于阶段；阶段条信号与高亮；约束行 typed kind；dock_recommendation 只应用一次；跨阶段不继承编辑目标；组可见性覆盖跨切换存活；RAW 拦截带原因；无目标阶段清活动层；降级模式诚实报告。
- test_command_and_shortcuts.py（123）：重复注册替换；子序列模糊匹配；recent 置顶+持久化；快捷键冲突检测；clamp_geometry_to_screens 两态。
- test_workstation_inspector.py（179）：horizon 无编造值；地震轴范围；map_component 分派；未知 kind 通用表；空选择态；井联动状态真实数据。
- test_layout_persistence.py（108）：float 往返、可见性只写 visible 位、键命名空间独立、损坏值回落默认。
- test_shell_p0_fixes.py（97）：showEvent 跑响应式+post-show restore；每个 dock 有 toggle 重开路径；具名预设保浮几何；恢复默认重停靠一切。
- test_workstation_lifecycle.py（319）：响应式隐藏不持久化为用户布局；restore 后窄屏重应用策略；user 旗标持久化；dock min 随浮动翻转；flush_layout hide 前写盘；teardown 冻结保存；活动历史不开 Agent 日志 dock。
- test_workstation_presets.py（258）：preset id/label/描述齐全稳定；逐 preset 可见性矩阵；未知 preset no-op；手动 toggle 使 preset 失效；hub toggle 也失效；app bar 下拉驱动；legacy 迁移 4 态；未知状态版本跳过。
- test_mapping_stage_e2e.py（300）：stage1 RAW 永不被改；重开恢复角色与阶段；stage2 typed 约束；过期依赖不静默替换；工程 roundtrip 保工作区状态。
- test_attribute_table_differential.py（411）：同 id 集不重填、单编辑只动一行、差量成本与要素数无关、2000 要素时限内、结构变化才全量重建。
- test_composite_editing.py（547）：建层快照、编辑会话 add/undo/redo/save、rollback 丢弃工作副本、kind 失配不劫持工具、remove 重绑活动层、工具条跟踪编辑态、模板地质样式、工程 roundtrip、树勾选不杀 item、原生/回退属性对话框双路径。
- test_composite_gis.py（1358）：CRS 穿透、断层/相带/物源模板业务字段、模板默认值、属性 payload 应用、merge/split 拓扑门（bowtie 阻断、禁用放行）、identify 多层、per-layer 捕捉容差优先级。
- test_workstation_context.py（201）：explorer 选择发布到共享上下文、垃圾 payload 不发布、agent 计划永不请求写、井撤销恢复、样式页诚实/路由。
- test_workstation_explorer.py（281）：无编造层位；空态；增量刷新保选择/展开；大组截断提示；搜索防抖。
- test_qgis_layer_panel.py（192）+ test_qgis_layer_panel_menu.py（182）：树回写（可见/改名/排序）不 echo；菜单回调→请求信号映射；程序化发布不 echo active layer；空图层入树；管理行含添加分组。
- test_agent_ux_v6.py（137）：降级结果显 warnings 不假通过；WRITE 授权对话框列动作+会话范围跳二次确认。
