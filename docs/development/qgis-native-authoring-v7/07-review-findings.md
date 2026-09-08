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

## Review 2 — Architecture（2026-09-08，独立 agent 审查）

范围：`db21f6cf..HEAD` 全变更面（6 commits，+4214/−142），逐文件 diff 审阅。修复落地 commit `3ab9222d`。

**结论：0 × P0，1 × P1，10 × P2。架构不变量 A–J 全部成立（无第二 GIS authority、无 lifecycle 绕过、无 QGIS 绕过、无第二 tool state authority、FFI ownership 与既有模式一致、manifest 单权威、EditDelta 保持派生契约、接口冻结、未越模块边界、vendored 补丁最小且文档化）。**

| 编号 | 级别 | 问题 | 处置 |
|---|---|---|---|
| P1-1 | P1 | measure 双执行体的旧桥降级无运行期提示（与 P2-8 snapping 降级处理不对称——用户拿到平面距离却不知无椭球修正） | 已修：shim 一次性 warning「测距已降级为平面计算，地理坐标系下不含椭球修正」 |
| P2-1 | P2 | KNOWN_NATIVE_TOOLS/KNOWN_GEOMETRY_OPS 为零消费的手工能力镜像（第二能力清单的种子） | 已修：删除；LEGACY 集合显式限定 degraded 路径并注明 manifest 单权威 |
| P2-2 | P2 | LEGACY_NATIVE_TOOLS 是对旧桥能力面的手工断言（若某 0.2.x 实际缺工具会伪可用） | 记录：旧桥版本面已封死，风险受控（注释言明断言性质） |
| P2-3 | P2 | LayerCapabilitySnapshot 无生产消费者；can_split/merge 在桥缺算子时仍 True（shapely 语义兜底） | 记录：并行 UI 分支契约预置（08-10）；二元结构限制已注明 |
| P2-4 | P2 | evaluate_tool 的 checked 重建分支丢弃 conflicts 字段 | 已修：透传 |
| P2-5 | P2 | reshape 激活不防御 selection != 1；evaluator 是唯一门禁 | 已修：激活侧双重防御（画布 + 恰一选集） |
| P2-6 | P2 | TopologyService.validate 逐要素重复桥探测（O(N) import 探测 + 潜在刷屏） | 已修：探测单次提升；桥失败 warning 一次后回退 |
| P2-7 | P2 | snapshot_stable_hash 不含 contract_version（不同契约版本撞 token） | 已修：纳入 hash |
| P2-8 | P2 | scratch_full_tests.log（含崩溃堆栈）被提交入库 | 已修：移出 git + gitignore |
| P2-9 | P2 | RectangleSelectTool Shift 语义变更（XOR→差集）无变更公告面 | 记录：对齐 QGIS 桌面是 Goal 方向；PR 描述中将列入行为变更 |
| P2-10 | P2 | canvas_shim 注释并行的无语义 diff 噪音 | 记录（无害） |

审查原文逐项确认（摘要）：A 无第二 authority（ReshapeTool 几何全走桥、测距在 C++ QgsDistanceArea、topology 收敛而非扩张）；B 无 lifecycle 绕过（reshape/vertex/传播/回滚全链过会话与门禁，镜像层只读）；C 唯一非原生执行是显式声明的 measure 双执行体与命令型 split/merge（引擎记入 delta）；D 工作站路径单一 evaluator 来源，旧 update_state 仅为 mapping_page legacy 宿主保留，UIContextSnapshot 关注点正交；E FFI 逐点与 select/identify 同型（per-canvas 缓存/回调表/孤儿坟场/GIL）；F manifest 双向钉死（kind ⊆ set_map_tool 接受集 + snapshot 派生相等）；G EditDelta 无第二命令栈/无持久化副作用；H 契约只加不改 + mapping_page 未破坏；I diff 面未越界；J 两处 vendored 补丁最小且 UPSTREAM.md 记录。

## Review 3 — UX / Performance / Adversarial（2026-09-08，独立 agent 审查）

范围：规则矩阵、接线、四个测试文件、08 诚实度。修复落地 commit `074cd5d0`（P1 第一批：context O(1)/blocking 门/loader）、`0b25aee3`（P1-3~P1-5）、`8fabe6dd`（P2 批）。

**结论：0 × P0，5 × P1（含 2 个接近 P0 的诚实度/性能问题），P2 若干。P1 全修；P2 全修或记录（UX-1 cancel 常开为有意设计；P2-10 无害注释；P2-9 修饰键变更在 PR 描述列入行为变更）。**

| 编号 | 级别 | 问题 | 处置 |
|---|---|---|---|
| P1-1 | P1 | `tool_context_inputs` 的 `wkb_type` O(N) 全量拷贝（帧级链），且稳定性探针因直接构造 ToolContext 而测不到 | 已修：kind 映射 O(1)；新增 `test_context_inputs_constant_in_layer_size`（1k vs 100k 比率门）回归探针 |
| P1-2 | P1 | full/refresh/prev-next/toggle/delete/split/merge/repair/选择命令/snapping/topology/history 缺 blocking 门（后台任务下语义不一致） | 已修：统一加 `_blocking_gate`；新增全矩阵 blocking 测试（cancel 例外） |
| P1-3 | P1 | 原生+旧桥测距无数值显示（未记录；08 只承认 fallback） | 已修：宿主订阅 measure_segment/preview，状态栏显示平面距离（明确标注）；08-13 记录 |
| P1-4 | P1 | 工程切换 `set_project` 静默 rollback（靠调用方自觉 flush） | 已修：`load_from_project` 先 flush，阻断时返回 False；`set_project` 拒绝带病切换并明示；新增脏会话/阻断会话切换测试 |
| P1-5 | P1 | `_on_measure_updated` 段数语义未钉死 + NaN 未守卫 | 已修：segments=完成段+live 段语义注释+测试；NaN/Inf 显示"测距无效" |
| UX-1 | P2 | cancel 永远可用 | 记录：有意设计（Esc 逃生通道），08-16 |
| UX-2 | P2 | 阶段隐藏的按钮无可见解释 | 已修：阶段切换时 status_message 列出被隐藏工具名 |
| UX-3 | P2 | 原生 identify 未命中静默 + 面板残留 | 已修：miss 时清空面板；要素已删时提示 |
| UX-4 | P2 | validate 只报首条 issue | 已修：前 3 offender + 总数 |
| UX-5 | P2 | raw/stage 布尔失真（瞬态拒绝误标 stage 锁） | 已修：`_layer_lock_classes` 只在真分支置位 |
| PERF-1 | P2 | overlay_state O(全量) | 已修：选集 id 点查 O(选集) |
| PERF-2 | P2 | _split_inputs 高频扫描 | 记录：50 图层可接受；与 P1-1 同链路但量级小 |
| PERF-3 | P2 | tool_operation(True) immediate 重组 | 记录：原生采点按 feature 提交，单次成本可接受 |
| PERF-4 | P2 | undo 栈无界 | 记录：08-14（与基线一致） |
| ADV-1 | P2 | set_map_tool/回调注册失败静默 | 已修：warning + backend_status 告警 |
| ADV-2 | P2 | digitize commit 被拒无感知 | 已修：commit_rejected 信号 → status_message |
| ADV-3 | P2 | reshape 目标删除后工具残留 | 已修：选集变化触发重绑 + 失配回落 pan |
| ADV-4 | P2 | import_layer_features 半脏会话 | 已修：失败 rollback + 重抛 |
| ADV-5 | P2 | NaN/Inf 输入守卫 | 已有：`_point` isfinite（VectorFeature 构造即校验）+ 测距 NaN 显示 |
| ADV-6 | P2 | CRS 只判非空 | 已修：pyproj 真校验 + 缓存 |
| ADV-7 | P2 | _stage_hidden_edit_actions 高频查 profile | 记录：开销小 |
