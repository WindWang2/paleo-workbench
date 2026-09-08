# 08 — Known Limitations（V8）

| # | 限制 | 证据/理由 | 影响 |
|---|---|---|---|
| 1 | split/merge/reshape 不进 command palette | 前置条件依赖会话几何细节（split_ready/merge_ready 由 CompositeEditController 派生），palette 的 UIContextSnapshot 无法诚实判定；注册会给假可用/假禁用（违反 M2 同因原则） | palette 覆盖 24 个 `map:*` 命令；split/merge 经工具条+右键（execution re-gate 仍生效） |
| 2 | 「无工程」仅在纯函数层验证 | `PaleoWorkbenchWindow(project=None)` 自动创建 Untitled 工程（app.py:36），工作站永远有工程文档 | 视觉 QA 用「空工程表面」表达（03-decisions D15）；project_open 门禁由 M2 矩阵覆盖 |
| 3 | 原生工具激活失败回退的视觉 QA 是信号模拟 | fallback 画布无原生 QgsMapTool；QA 直接发射 `native_tool_activation_failed` 驱动宿主回退路径。shim 侧记录/发射逻辑（canvas_shim.py set_map_tool 异常分支）在无桥环境不可端到端驱动 | `-m qgis` 腿（有桥）可补端到端；handler 逻辑本身已被 v8 QA 状态覆盖 |
| 4 | `_last_availability` 与 QAction 呈现的组级隐藏仍由 overflow 集合覆盖 | 窄画布收纳优先于 evaluator 可见性（V7 决策保留）：溢出组的 QAction 被 Qt 自动置 disabled，QA/测试断言以 evaluator 结论为准 | 溢出菜单条目使能取自 `_last_availability`（V7 已修），无「灰按钮可点」回归 |
| 5 | M3 深度 token-hygiene 扫描未展开 | 本轮 M3 增量 = 契约驱动的状态语言（M4 help 文本、checked/原因在 tooltip/statusTip 的统一）+ V7 ratchet 全绿（a11y/dpi、visual QA v6/v7/v8、token 测试）。全量 120 页 token 盘点是独立批次 | ratchet 只减不增原则维持；无新增裸 setEnabled 业务判断（grep 证据在 00-overlap-audit §C 基线内） |
| 6 | issue #1230 stale-QTimer 风险：调查结论为「无新增、存量低危」 | 本分支未新增 QTimer；唯一的 singleShot(0)（_update_empty_hint → _sync_hint_geometry）是 0ms 窗口且目标为长寿命 composite，Qt 事件循环在对象销毁后回调会 RuntimeError 但被 Qt 吞掉（不崩溃）；#1230 主体是 CI 配置诉求，明确不属本 Goal | 无行动；如未来出现真实 dangling-timer 崩溃再立项 |
| 7 | `update_state`/`MapActionState`/`action_state`（旧签名）删除 | 生产零消费者（source scan：composite_document 只用 tool_context_inputs；mapping_page 已迁移）；测试迁移到 dict 契约/apply_availability | 第三方（无）不受影响；`action_state()` 保留 dict 兼容别名一个版本 |
| 8 | 100GB seismic 完全排除 | Goal 明确 OUT OF SCOPE；本分支零体数据接触 | — |
| 9 | Inspector action hint / empty-state 集成只完成 API 侧 | `CompositeDocument.explain_action` 已就绪并被 tooltip/palette 消费；Inspector 面板内的动作提示块与 onboarding 空态文案接入留待下批（避免本轮 UI 面铺得过宽） | M4 的 palette/tooltip/statusTip 三面已交付并测试 |
| 10 | blocking 期间画布工具 checked 熄灭（含 pan） | checked=(current_tool==id AND enabled) 的保守语义：禁用工具不得留 checked（防陈旧勾选）；代价是模态阻塞时活动工具指示消失。恢复即回来（review R3-F3 取舍） | 纯指示性；无操作误导（按钮同时禁用） |
| 11 | topology_error_count 无宿主生产者 | 预存（V7 B 时代即从未喂入）；合并的拓扑门只在纯函数层生效。需要 CompositeEditController 在拓扑校验后回填 session 计数（域侧改动，方向 C/D 范围） | 契约字段保留，测试钉语义 |
| 12 | 预存 main 基线失败（与本分支无关，证据：干净 d5181cb3 上同样失败） | `test_coordinate_hub.py::test_velocity_guardrails_and_updates`、`test_coordinate_hub_stress`、`test_data_view_models`（ImportError 私有名）、`test_dependency_audit_and_batch`、`test_challenger_m6_adversarial_stress`、`test_depth_cursor_units`；另 `test_delivery_profiles`/`test_compatibility_matrix` 为本机 temp 目录 PermissionError（环境） | 在 PR body 中列出，供方向 C/运维跟进 |
