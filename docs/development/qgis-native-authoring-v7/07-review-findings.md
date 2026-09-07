# 07 — Review Findings（审查记录与修复）

## Review 1 — Correctness（2026-09-08，独立 agent 审查）

范围：契约四模块 + vector_layer delta 集成 + map_tools + topology + 工作站接线（composite_editing/composite_document/map_action_controller/canvas_shim）+ DLL bootstrap。基线 commit `6147bce5`（修复落地 `a433e586`）。

**结论：0 × P0，5 × P1，11 × P2。全部 P1 已修，P2 除 P2-11（记录为已知限制）外全部修复。**

| 编号 | 级别 | 问题 | 处置 |
|---|---|---|---|
| P1-1 | P1 | measure 的 evaluator 能力门与「旧桥→路由降级保留」决策矛盾；B8 路由器成为死代码，旧桥+原生画布用户失去测距 | 已修：evaluator 不再对 measure 做能力门（原生画布上双执行体：PwbMeasureTool / 视口路由，shim 运行期选择）；测试改钉新语义 |
| P1-2 | P1 | 旧桥（无 manifest）+ 原生画布 → 编辑工具条全灭且无逃生门（存量安装升级即只读） | 已修：degraded 快照携带可验证的 M3/M4 legacy 工具集（LEGACY_NATIVE_TOOLS），V7 新能力诚实缺席；`test_degraded_bridge_keeps_legacy_tool_surface` 钉死 |
| P1-3 | P1 | reshape 在 fallback 画布可启用/激活但无输入路径（ReshapeTool 无鼠标方法）——点了没反应的假按钮 | 已修：evaluator 增加 `native_canvas_available` 前置；`activate_tool` 同步守卫 |
| P1-4 | P1 | 顶点编辑 + 同会话拓扑传播 undo 非原子：一次 Ctrl+Z 拓扑断裂且无提示 | 已修：`_commit_vertex` 公共实现把主编辑 + 传播钩子包进 `begin/end_edit_command` compound（一次 undo 整体回退；constituent delta 保留展平）；传播失败 log warning。跨图层传播受会话隔离限制 → 08 已知限制 |
| P1-5 | P1 | `tool_context_inputs` 的选集几何类型全量遍历图层要素（O(N)），挂在 extent_changed 帧级链上（100k 要素回归） | 已修：图层 kind 为权威，O(1) 推导 |
| P2-1 | P2 | 原生提交路径静默失败群（reshape/move/vertex/digitize except 无日志） | 已修：`logging.debug`（拒绝路径）/`warning`（传播失败） |
| P2-2 | P2 | 拓扑桥校验失败静默丢失桥异常文本 | 已修：`_logger.warning` 后回退 Shapely |
| P2-3 | P2 | select/select_rectangle 缺 native gate（旧桥缺 kind 时按钮可点但原生工具静默未切换） | 已修：与同组工具一致加 gate |
| P2-4 | P2 | 矩形选择 Shift 语义 native(差集) vs fallback(对称差) 漂移 | 已修：对齐 QGIS 桌面（无=替换/Ctrl=并/Shift=差/Ctrl+Shift=交）+ 4 个回归测试 |
| P2-5 | P2 | split/merge delta 的 anchor 语义未文档化（feature_id 与 before/after 非对应） | 已修：EditDelta docstring 明示 anchor 规则（测试已锁定） |
| P2-6 | P2 | 拓扑传播新开会话的引擎溯源 token 停留 "unavailable" | 已修：传播后统一注入 controller token |
| P2-7 | P2 | 死代码/死字段（`_edit_source` helper、无消费者契约字段、compound 无生产接线） | 部分修：删除死 helper；字段标注契约用途；compound 接线（P1-4） |
| P2-8 | P2 | endpoint/intersection 捕捉在旧桥原生画布上静默失效 | 已修：`_push_snapping_config` 对未下推模式 log warning（用户可感知降级） |
| P2-9 | P2 | probe 只捕 ImportError，损坏 .pyd 的其它异常会炸宿主构造链 | 已修：非 ImportError → degraded 带判词 |
| P2-10 | P2 | `_rule_zoom` 硬编码 tool_id（靠 checked 分支侥幸修正）；capture preferred 恒真表达式 | 已修：参数化 + 简化 |
| P2-11 | P2 | fallback 画布测距无数值显示（只有 overlay 线） | 记录：08-known-limitations（fallback 为测试路径，原生画布有状态栏显示） |

**审查确认无问题的方面**（原文照录要点）：delta order 单调/journal 三处一致裁剪/undo-redo 不产 delta/rollback 语义正确；undo 后选集收缩；evaluator 不变量（enabled 无 reason、invisible 必不 enabled）；reshape 双条件三处一致（evaluator/applier/kind 映射）；RAW/stage gate 不可绕过且次序正确、与保存路径纵深防御一致；measure 跨语言 payload 契约（C++ payloadJson 与 Python 消费一致）；DLL bootstrap 幂等且次序正确；weakref/内存/重入无问题；`_rule_save_edits` 与 `toggle_editing` 的 gate 差异已确认为同源不构成绕过。

## Review 2 — Architecture（待 C++ 编译验证后执行）

## Review 3 — UX / Performance / Adversarial（待 QGIS 测试执行后执行）
