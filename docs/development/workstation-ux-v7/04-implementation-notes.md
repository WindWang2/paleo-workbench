# 04 — Implementation Notes（V7 实现纪要）

按里程碑（commit 见 git log `0b8d2b86..HEAD`，分支 feat/workstation-ux-v7）：

## M1/M2 上下文命令面（0e398f98）
- `ui/workstation/tool_surface.py`（新增，无 Qt 依赖）：`ToolContext` /
  `ToolAvailability` / `QgisCapabilitySnapshot` / `LayerCapabilitySnapshot`
  （goal §16 typing seam）+ `evaluate_tool` 门禁链 + `TOOL_GROUPS` 12 组 IA
  + `stage_group_visibility` + UIContext 适配器。
- `MapActionController`：+13 surface actions（layer/symbology/factor/qa/
  layout_export），`apply_availability` 渲染 enabled/visible/reason 到
  tooltip+statusTip。
- `CompositeDocument`：`tool_context()`/`tool_availability()` 从既有权威取数；
  冻结/发布成熟度门禁并入 `_role_allows_editing` 单点；split 特例经
  `split_inputs_ready` 收敛；新命令分派（含 style_manager/zoom/export）。
- `MappingPage` 第二控制器消费同一求值器（stage=None 自由面语义）。
- palette：stage 命令与 map:* surface 命令 applicability 同源。

## M4 图层树（a5941bdb）
- `ui/workstation/layer_decorations.py`（新增）：`LayerPresentationState`
  优先级装饰（missing>dirty>editing>missing_input>superseded>stale>
  degraded>maturity）+ `GroupPresentationSummary`。
- 回退树：状态列（glyph+label+主题色）+ hover 摘要 + 差分重载（同结构
  复用行对象，保选择/滚动）+ 双击定位。
- 原生树：同构 seam + 组摘要行（桥侧行内装饰仅铅笔——如实）。
- `LayerGroupController.group_summary` += frozen/published（maturity
  provider 注入）；group_ids/成员在无 reconcile 时从 placement 派生。

## M5 Inspector（834e33df）
- show_feature/show_factor/show_map_product 类型化分节；树选择路由
  （factor 系角色→任务+live 网格摘要）；identify 双击进 Inspector；
  assemble 后 MapProduct 进 Inspector（staleness token）。

## M6 视觉收敛（4b70cdf9, 4f48e214）
- ratchet 修红；geo3d 47 处 snapshot→style.bind；5+10 文件批量迁移；
  43 处 emoji→文本字形；readiness/session/maturity 词表统一；3 条新
  ratchet（font-size 104→41、fixed 42→12、emoji 硬禁）。

## M7 布局（160d843f）
- hub 停靠化（D12）；死代码清理（fallback_preview、command_groups、
  float_visible、4 枚举成员、QMenuBar 规则、screen_inventory 派生化）；
  工具条溢出（»菜单，核心组永不收纳，确定性宽度计算）；1366 级核心组
  完整显示验证。

## M8-M10（b72128dc）
- palette surface 命令；focus guard 统一；任务重试/取消诚实文案。

## M11/M12（a2e502ea）
- `visual_qa_v7.py` 8 状态 + 语义检查；capture --v7 模式；SIZES+1366/
  2560；32 张基线；perf 结构 bound ×4。
- 顺带修复：armed 取消置 cancel_requested（真 V6 bug）；溢出菜单使能取
  自求值器（Qt 对隐藏 action 自动禁用的对策）。

## M13 评审修复（eeeeb504）
- P0 style_manager 签名；P1×6（阶段刷新/取消中渲染/run_qa 假通过/装饰
  反应性/词表派生/palette 单源）；P2×10。详见 07-review-findings.md。

## 关键经验
- Qt 对工具条上隐藏的 QAction 自动置 disabled——溢出菜单条目使能必须
  取自求值结果而非 action.isEnabled()。
- 隐藏 widget 的 resize() 不发 QResizeEvent（Qt 延迟到 show）——布局
  响应需 showEvent 补发。
- 并发子 agent 编辑不相交文件集仍可能因共享 import 链互相踩（inspector_panel
  NameError / geo3d f-string）；合并后必须全量回归。
- `git add -A` 会复活 git rm 掉的文件（fallback_preview 教训）。
