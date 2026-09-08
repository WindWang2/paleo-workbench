# 07 — Review Findings（V7 三轮评审）

三轮独立评审（R1 UX 正确性 / R2 设计系统与架构 / R3 对抗-视觉-性能），
全部 P0/P1 已修复并带回归测试（commit eeeeb504；tests/test_review_fixes_v7.py）。

## R1 — UX Correctness（P0×1, P1×3, P2×8）

| # | 级 | 发现 | 处置 |
|---|---|---|---|
| 1 | P0 | style_manager 调用缺必需 style_db_path——native 上必 TypeError 且归咎 QGIS | 修复：受管样式库路径（工程 .artifacts/styles.db）+ False 返回可见；回归 test_style_manager_call_signature |
| 2 | P1 | 阶段切换不刷新统一可用性（组/白名单停留旧阶段） | 修复：shell 阶段处理器 +_sync_action_state；回归 test_stage_switch_refreshes_evaluator_availability |
| 3 | P1 | 「取消中」渲染不可达（RUNNING 分支在前） | 修复：优先级倒转；回归 test_cancelling_render_priority（确定性构造） |
| 4 | P1 | run_qa 吞验证器崩溃 → 假「QA 通过」 | 修复：崩溃转 error issue；回归 test_run_qa_validator_crash_becomes_issue |
| 5 | P2 | write_granted 文档声称门禁未实现 | docstring 改为如实（保留字段，注明门控 Agent 动作） |
| 6 | P2 | 重复 showEvent 遮蔽 + resize 丢 _sync_hint_geometry | 修复（合并 R3#2） |
| 7 | P2 | missing 装饰从未产生 | 修复：注册表缺失行→missing=True；回归 test_missing_layer_gets_missing_decoration |
| 8 | P2 | attribute_table 被当编辑动作门禁（RAW 连查看都禁） | 修复：只读语义（QGIS）；回归 test_attribute_table_available_on_raw_layer |
| 9 | P2 | 未知几何类型捕获 fail-open | 修复：fail-closed「几何类型未知」；回归 test_unknown_kind_capture_fails_closed |
| 10 | P2 | open_factor_workbench 路由到画布而非制备页 | 修复：emit "preparation" |
| 11/12 | P2 | writable 语义差异（潜在）/ 无操作静默 | 记录（11 潜在无危害；12 低频） |

干净区（评审确认）：43 工具 id 全有后端分派；palette 激活守卫；溢出交互
收敛；装饰不伪造；inspector 分节诚实；取消/重试状态机健全。

## R2 — Design System / Architecture（P0×0, P1×2, P2×6）

| # | 级 | 发现 | 处置 |
|---|---|---|---|
| F1 | P1 | 三套阶段词表未按承诺派生 | 修复：dispatcher STAGE_CONTEXT_ACTIONS 单表，panel/palette 派生；profile 死 id 删除 |
| F2 | P1 | palette 上下文两套 id 源可漂移 | 修复：全部图层字段从 composite.tool_context() 单源推导 |
| F3 | P2 | fallback_preview 被 git add -A 复活 | 再删除；经验记录 |
| F4 | P2 | QMenuBar::item:selected 孤儿规则 | 删除 |
| F5 | P2 | 新 ratchet 表无僵尸检查 | test_ratchet_only_shrinks 扩三表 |
| F6 | P2 | write_granted 上下文两构造器分歧 | 并入 R1#5 处置 |
| F7 | P2 | artifact-key 解析两处维护（历史） | 记录为已知限制（08） |
| F8 | P2 | controller 内 legacy/evaluator 双写（既有，顺序依赖） | 记录；建议的 id 全等测试纳入 08 待办 |

干净区：无第二 enable/visible 权威；无 QGIS dialog 重写；inline 债务净
-131 行；tokens.py 未被污染。

## R3 — Adversarial / Visual / Performance（P0×0, P1×1, P2×5）

| # | 级 | 发现 | 处置 |
|---|---|---|---|
| 1 | P1 | 树装饰对新鲜度变化不反应（懒更新） | 修复：stale_summary_changed → _push_layer_decorations；回归 test_stale_summary_refreshes_tree_decorations |
| 2 | P2 | 重复 showEvent / resize 丢 hint 几何 | 修复（同 R1#6） |
| 3 | P2 | 主题切换后状态列颜色滞留 | 修复：theme_changed → 重推装饰 |
| 4 | P2 | 每 pan 全量重算（27ms@1000 层） | 修复：extent 轻路径 |
| 5 | P2 | 死 factor task 静默降级 | 记录（诚实但未解释；08 待办） |

干净区（实测）：删除层装饰无泄漏；取消/重试健全；RAW 门禁三层不可绕过
（palette 未注册 toggle_editing 且执行侧复查）；1366×768 全绿；GC-flaky
两文件与 main 字节一致。
