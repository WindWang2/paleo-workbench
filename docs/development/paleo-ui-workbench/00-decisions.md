# 00 — 交互决策记录（Paleo UI Workbench M1-M5）

状态：权威。实现与测试与本文冲突时，以本文为准并在此登记修订。
关联：01-interaction-specs.md / 02-state-machine-design.md / 03-tdd-ui-test-plan.md

## D1 时间轴层级粒度
- 时间轴呈显 **期次（epoch）** 一级；不呈显代/纪/世多级嵌套（编图工作流的切换
  对象是"期次图"，非年代地层多重层级）。
- 期次目录来源（合并、去重，项目权威优先）：
  1. `workflow.stratigraphy.ensure_horizon_catalog(project)`（层序界面/目标层位）；
  2. `paleomap_documents[*].linked_target_horizon`、`factor_map_tasks[*].target_horizon`；
  3. 内置地质年代方案 `BUILTIN_PERIOD_SCHEME`（寒武系…第四系，含底界年龄 Ma），
     仅当其名称被 1/2 命中时进入目录（避免虚构项目不存在的期次）。
- 排序：能匹配内置年代者按底界年龄 **自老到新**（左→右 = 老→新）；未匹配者保持
  项目声明序，追加在已匹配期次之后（"第 N 层序界面" 这类无名年代 horizon 属此类）。

## D2 洋葱皮（Onion-skin）公式
- 范围：仅 **相邻前一期次**（index-1）；不叠加多期（噪声>收益，登记为 04 限制）。
- 透明度：轮廓层 alpha 固定 `0.30`（30%），经既有 API
  `set_layer_opacity(layer_id, 0.30)`（fraction 0..1）应用。
- 参与层：目标期次的 **相带面/相带边界类** 图层（kind∈{facies, facies_boundary,
  boundary} 或 role∈{FACIES_BOUNDARY, PALEO_SHORELINE}）；非相带类（底图/井位等）
  不参与洋葱皮，避免参考层闪烁。
- 洋葱皮期间当前期次图层不透明度 **不受影响**；关闭洋葱皮时恢复该层用户原值
  （`StageViewState` 记录的 layer_opacity）。
- 语义：洋葱皮是 **查看态**（view-time），不写入工程持久层；期次切换/关闭时撤销。

## D3 期次差分切换（Diff Transition）
- 切换期次 = 纯函数计划器 `build_epoch_switch_plan(layers, current, target)` 产出
  `EpochSwitchPlan{show, hide, onion, target_epoch}`；执行器按 **集合差分** 逐层调用
  既有 `set_layer_visible` / `set_layer_opacity`（增量镜像 set_layer_snapshot(
  changed_hints)，**零画布重建、零工程重开**）。
- 层→期次归属：`epoch_of_layer` 分类器（可注入）；默认按层名/层 membership 的
  horizon 标签匹配期次 key；无归属层（底图、井位、区域参考）**不随期次切换**。
- horizon 元数据写穿：期次提交后走既有 `set_target_from_boundary` +
  `stage_controller.refresh_evaluation()` 通道（与 horizon_combo 同路，不新增权威）。
- 原子性：一次提交 = 一个 `tree_transaction` 窗口（桥支持时）/ 一次 `_publish`
  增量发布；中途异常回滚可见性到切换前快照。

## D4 时间轴信号去抖
- 拖拽中：`epoch_scrubbed(str)` 高频预览信号（≤60Hz 合并，仅驱动刻度高亮），
  **不触发图层切换**。
- 提交：拖拽释放 / 键盘步进停顿 `150ms` / 单击刻度 → `epoch_committed(str)` 一次。
  与 `_composition_timer`(120ms) 既有节奏同量级。

## D5 快捷键冲突消解表（现有占用 ← 全仓 grep 实证）
| 键 | 现有占用 | 本任务处置 |
|---|---|---|
| Ctrl+S/N/O/F, Ctrl+K, Ctrl+Alt+D, F5, F1 | app_shell/app.py | 不碰 |
| 1–5 | hub 页导航（ApplicationShortcut+文本输入守卫） | 相带快捷键 1–9 见 D6 |
| Alt+1/2/3 | 子模块导航 | 不碰 |
| Delete | 删除选中要素（map 域） | 不碰 |
| Ctrl+Z / Ctrl+Shift+Z | 撤销/重做 | 不碰 |
| Esc | map 工具取消 | 复用语义，扩展为"安全退出当前工具"（见 D9） |
| Z / X | **未占用** | 缩放中心放大 / 缩小（画布域） |
| Space | **未占用** | 按住临时平移（画布域，keyup 退出） |
| Tab | 焦点链（无快捷键占用） | 循环切换要素（仅 DIGITIZING/ADJUSTING 且画布聚焦） |
| Ctrl+D | **未占用** | 吸取选中要素相带属性→装备画刷 |

## D6 相带数字键 1–9 与 hub 导航 1–5 冲突
- 方案：相带快捷键注册为 **画布域 WidgetWithChildrenShortcut**（parent=CompositeDocument），
  且仅当"绘图工具激活"时注册（工具退出即 unregister，动态生命周期）。
- 实证结论（D6-rev0，2026-09-14）：offscreen 平台无活动窗口，QTest 模拟键
  不驱动 QShortcutMap（仓库既有经验 tests/test_keyboard_shortcuts.py），跨
  上下文路由无法在无头环境直接观测。落地双保险：
  1) 相带键仍是画布域 WidgetWithChildrenShortcut（Qt 语义上最近作用域优先）；
  2) hub 页导航回调加"绘图工具激活期"守卫（app_shell._workstation_drawing_active）
     ——即便真实窗口环境双触发，hub 也不切页，行为仍正确。
  结构契约由 test_digit_key_scope_and_hub_guard 钉住。

## D7 HUD 刷新与内存预算
- 光标→HUD 更新走 `map_position_changed`，**60ms 合并节流**（QTimer 单实例，仅保
  最新点）；值计算 O(1)：双线性网格采样 + 预建井序表线性最近邻（井数 ≤ 数千
  可接受；>5000 登记为 04 限制）。
- HUD 是 canvas 容器的 **子控件**（父级=canvas 父 QWidget，非 topLevel），
  `WA_TransparentForMouseEvents`，无逐次控件分配 → 长时高频移动零内存增长（测试
  断言 QApplication.topLevelWidgets 数量恒定）。
- 缺数据字段显示 `—`（诚实降级，不猜值）。

## D8 QC QuickFix 撤销粒度
- 一次修复 = **一个可撤销命令**：fallback 引擎 `begin_edit_command("QC修复:…")` …
  `end_edit_command()`（多要素合并=更新优势相要素 + 删除碎屑要素同命令）；native
  引擎=同层 gesture 宏。复用既有撤销栈，不引入 QUndoStack。
- 修复动作注册表 `QUICK_FIX_ACTIONS: dict[rule_id, list[QuickFixAction]]`；
  `availability(issue, context)` 诚实判定（几何前提不满足→按钮禁用+原因 tooltip）。
- 碎多边形合并目标 = 共享边界最长的相邻相（"优势相"判定：共享边长并列时取面积大者）。
- 未封闭边界闭合 = 端点沿 **末端切线方向** 延伸（步长=局部容差×0.5 迭代），
  端点进入吸附容差后闭合；超出最大延伸距离（容差×8）判不可修，禁用按钮。

## D9 平移/缩放交互
- QC 定位 = **平滑平移**：180ms、ease-in-out（cubic），≥4 ≤12 插值帧，
  `set_extent(record_history=False, coalesce_history=True)`，末帧单独记录历史一次
  （既不污染撤销也不丢后退）。
- Z/X = 以画布中心 ×1.5 / ÷1.5（复用 zoom_by）；Space 平移 = 按住进入 pan 工具态
  （FSM TRANSIENT_PAN），释放还原先前工具。
- Esc 安全退出顺序：取消当前数字化手势 → 退出当前工具 → 关闭浮层面板 → IDLE。

## D10 吸色管（Eyedropper）语义
- 激活后点击地图：`identify_all(point)` 顶层优先取第一个 **相带属性层** 要素；
  读取 facies/sub_facies/micro_facies/level + 所在层 id + 分类渲染器颜色 + 花纹名，
  装备到相带画刷上下文（FaciesBrushContext）并弹 toast 确认；空击（无要素）→
  toast 提示且保持原装备。
- 双栈一致：native 栈点击走 Python 侧 identify_all（不用 native identify 工具，
  保证与 fallback 同代码路径、同测试）。

## D11 调色板数据与渲染
- 数据源 = `CompositeDocument.facies_taxonomy()`（项目 override 优先，与图例/分配
  对话框同源）；花纹 = `mapping/facies_patterns.py` 既有花纹；颜色 =
  分类渲染器色带同款（复用 `_categorized_facies_style` 的色映射），保证调色板、
  图例、地图三者颜色一致。
- 网格：顶级 8 相为分区（section），每区亚相为格；格 = 花纹缩略 + 代号 + 名称；
  当前装备高亮；1-9 角标仅在"常用"前 9 格显示。

## D12 FSM 所有权与降级
- `ModeStateMachine` 是 **纯 QObject 协调器**（ui/workstation/mode_state.py），
  只观察既有信号（工具激活/期次提交/QC 激活），**不拥有**工具/画布状态——它是
  投影层，删掉它系统行为不变（用于 HUD 提示条与快捷键域判定）。
- 未知/竞态事件按 02-state-machine-design.md 的 default 行处理，不抛异常。

## D13 视觉回归阈值
- 快照 offscreen 渲染，DPR=1；结构断言（控件树/几何）为 gate；像素 diff 阈值
  `≤0.5%` 差异像素（时间轴切换前后同期次快照必须 0 差异；洋葱皮开/关必须 ≥0.5%
  差异——双向断言），数值记录于 04-visual-qa-verification.md。
