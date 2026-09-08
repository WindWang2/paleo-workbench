# 03 — Decisions（V7 ADR）

| # | 决策 | 理由 |
|---|---|---|
| D1 | 可用性真源 = `tool_surface.evaluate_tool(ToolContext)` 纯函数；所有表面渲染其输出 | goal §3"统一到共享命令/工具 applicability 体系"；纯函数可全矩阵测试（无 Qt） |
| D2 | 不新建 QGIS 桥 C++ 能力；capability 以 `uses_native_stack`/`qgis_bridge_available()`/degraded 字符串适配为三态快照 | goal §15/§16 边界；桥未构建是现实（main 同构），C++ 改动不可测 |
| D3 | 阶段语义真源保持在 `StageToolProfile.edit_actions`（域侧）；面板/palette 词表从 dispatcher 单表派生；死 `command_groups`/未实现 `context_actions` 删除 | 不新增第四套词表；删除死元数据优于保留幻觉 |
| D4 | hide vs disable 分工沿用 V6：工具条上阶段外动作 hidden（QGIS 惯例），palette 内 disabled+原因（可发现性）；kind/role/editing 门禁用 disabled+原因 | goal §4"默认不提供或禁用"允许两种，按表面选最专业形态 |
| D5 | 禁用原因单一字符串源（evaluator 输出）渲染到 tooltip/statusTip/palette/Inspector | goal §5 四表面一致 |
| D6 | MappingPage 第二控制器不删除：共享 evaluator + 适配器收敛语义 | mapping hub 仍是 active 生产页；删除属 L 级架构变更，超出本 Goal 边界 |
| D7 | 树装饰真源 = `LayerPresentationState`（Python 聚合现有权威）；原生树行内装饰不伪造（桥无 API），以面板摘要+tooltip+回退树全装饰呈现，如实文档化 | goal §7 要求可视化；环境内原生树不可测，诚实优先 |
| D8 | 状态词汇 canonical = state_language + tokens；tone 桥接表统一 3 套语法；本地 `_STATUS*` 方言迁移 + import-lint | goal §9"重复状态词汇"收敛 |
| D9 | ratchet 只减不增：现有 hex ratchet 修红后冻结新基线；新增 font-size/定宽/emoji/状态映射 4 条 ratchet | V5 模式延续，防回潮 |
| D10 | 构造期 light-snapshot（44 文件）迁移策略：高频页迁 `style.bind` 或 objectName+tokens QSS；低频对话框至少改用 palette_for(theme) 闭包；目标是主题切换零残影（语义断言：切主题后重截图 diff） | goal §9；"44 文件全 bind"成本高，按可见性分级 |
| D11 | emoji → SVG：导航树/数据视图模型/状态语言表改用现有 SVG 图标库 + StateToken glyph 仅限非 emoji 文本符号（▣✓✕ 等 ASCII/几何字形保留，U+1F000+ 全禁） | goal §7"禁止 emoji；SVG/icon+token+text"；完全无字形会伤 HC 可读性 |
| D12 | Hub force-float 处理：hub_dock 不再强制浮动——停靠为普通 dock（默认右区 tabify），保留窗口记忆；导航进入该页 = show+raise+activate（不 float） | goal §10"处理 Hub force-float 遗留"；全屏工作站形态一致性 |
| D13 | 死代码删除清单（本 Goal 内执行）：fallback_preview、well_seismic_joint_page（连测试）、7 个 test-only 页面保留但标注、MapEditToolbar shim、WorkspacePreset 死枚举、float_visible、register_meta、QMenuBar 死规则、screen_inventory 改为从 navigation 派生或删除 | goal §10"死页面/死 preset/死 placeholder" |
| D14 | 1366×768：响应式规则扩展（<1400 宽时 inspector/图层管理 tabify 折叠 + 底部 dock 上限高度），加视觉 QA 状态 | goal §10/§14 |
| D15 | 快捷键：QAction 快捷键注册进中央注册表的 meta 层（register_meta 复活或等价），conflicts() 覆盖全部绑定；文本 guard 统一类型清单 | goal §13 |
| D16 | 视觉 QA 沿用 V5 D8：pixel diff 永不 CI gate；semantic assertions hard-gate | 政策连续性 |
| D17 | 性能：树/任务/命令面全部差分；benchmark 显式规模上限（1000 层 / 10k 井 / 100k 目录），内存断言用结构性 bound（禁止无界物化）而非 wall-time | goal §17 + V6 经验（性能声明=结构 bound） |
| D18 | 100GB seismic 明确排除；地震仅 synthetic/small fixtures 接口完整性 | goal 总约束 |
