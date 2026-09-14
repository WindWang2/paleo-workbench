# Prompt 2 — 古地理编图专属 UI 交互工作台与多期次时空联动系统

> **使用方式**：直接复制以下全部内容，粘贴到 zcode agent 的输入框中直接运行（无需在命令行拆分执行）。
> 本 Prompt 内部已通过 `$goal` 与 `$loop` 命令调度，内置「先生成文档 → TDD 驱动开发 → 最终 Multi-pass Review」三阶段闭环。

```markdown
$goal "研发古地理编图系统专属的沉浸式 UI 交互工作台与多期次时空联动系统（M1-M5），支持层序时间轴期次无缝切换与洋葱皮对比、相带交互画刷与拾色管、单因素约束悬浮棚及交互式 QC 修复向导。全程先生成文档，再以 TDD 严格驱动，最后执行代码审查与 GUI 视觉回归闭环。"

$loop max_iterations=60 condition="docs_generated && ui_tdd_all_green && memory_and_leak_free && visual_review_passed"

## 0. 任务元数据与资源边界（硬约束）

- **所属系统**：Paleo Workbench 古地理编图桌面系统（PySide6 Qt6 + QGIS Canvas Shim）。
- **任务目标**：彻底解决当前编图 UI 缺乏地质时空流转逻辑的痛点，构建「多期次地层层序滑块联动、沉浸式沉积相拾色画刷、单因素辅助编绘悬浮 HUD、闭环交互式质检修复向导」的现代化专业交互工作台。
- **研发规模**：支持至少 4 小时全自主推演与开发，对标 10 亿+ tokens 研发交付量（含复杂状态机设计、深层 Qt 控件定制、无头与视觉回归测试套件、交互一致性审查）。
- **⛔ 编译与计算资源硬约束**：
  1. **最多只能启用 3 个 subagents**（严禁任何时刻同时超过 3 个 subagent 运行，防止系统资源与 Qt 线程争用耗尽）。
  2. **无头运行模式**：GUI 自动化测试必须强制 `QT_QPA_PLATFORM=offscreen`，严禁触发交互式弹窗阻塞执行。
  3. **无需重新编译 C++ 桥**：纯 Python / PySide6 领域，默认运行于现有环境（`pytest -m "not slow and not opengl"`）。
  4. **环境隔离**：在主仓库同级目录建立独立 worktree `../paleo-workbench-paleo-ui`，切入独立分支 `feat/paleo-ui-workbench`。
  5. **代码纯洁性**：严禁在 UI 线程直接执行耗时空间运算；遵守 `CLAUDE.md` 规范，杜绝循环信号（Signal Echo Loops）。

---

## 1. 启用的 Skills 与协作规范

请按需自动调用以下 skills：
- `planning-with-files`：强制以文件管理交互原型、状态机规格与测试计划，所有文档落盘于 `docs/development/paleo-ui-workbench/`。
- `matt` / `gstack`：用于 UI 状态切片管理、代码质量门禁与 PR 生成。
- `wayfinder`：将复杂交互逻辑决策转化为明确的 ticket，遇到歧义按照现代工业级地质软件标准自决。
- `tdd`：先编写基于 `pytest-qt` 的 UI 交互事件测试（QtBot 模拟鼠标键盘手势），再实现控件与控制器。
- `code-review`：并行启动 Standards（Qt 内存泄露、Parenting 规则）与 Spec（地质编图工作流顺畅度）双轴审查。

---

## 2. 三阶段开发流转协议（Document-First → TDD → Review）

```
┌────────────────────────────────────────────────────────────────────────┐
│ 阶段一：先生成文档 (Documentation First)                                │
│   └─ 00-decisions.md / 01-interaction-specs.md                         │
│   └─ 02-state-machine-design.md / 03-tdd-ui-plan.md                    │
│   └─ 04-known-limitations.md                                           │
├────────────────────────────────────────────────────────────────────────┤
│ 阶段二：TDD 驱动开发 (TDD-Driven Development)                          │
│   └─ Ticket 1: 层序地层时间轴滑块 (StratigraphicTimelineWidget)         │
│   └─ Ticket 2: 沉浸式相带调色板与吸色管 (FaciesPalette & Eyedropper)    │
│   └─ Ticket 3: 单因素约束提示 HUD 与剖面联动 (Constraint HUD & Sync)   │
│   └─ Ticket 4: 交互式质检修复向导中心 (Interactive QC Hub & QuickFix)  │
│   └─ Ticket 5: 全键盘编图手势流与状态集成 (Workstation Shell Assembly)  │
├────────────────────────────────────────────────────────────────────────┤
│ 阶段三：最后 Review 与视觉回归审计 (Review & Visual Verification)      │
│   └─ QtBot 400+ 用例全绿 + 信号回环检测 (Zero Echo-Loop Audit)          │
│   └─ 界面内存泄漏排查 (Parentless Widget Leak Audit)                   │
│   └─ 04-visual-qa-verification.md 产出与 PR 收尾                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 阶段一：先生成文档（必须首先落地，严禁跳过）

在开始编写代码前，必须在 `docs/development/paleo-ui-workbench/` 目录下创建并维护以下 5 份结构化交互工程文档：

1. `00-decisions.md`：记录所有交互决策（如时间轴层级划分粒度、洋葱皮透视模式透明度计算公式、快捷键冲突消解表）。
2. `01-interaction-specs.md`：详细描述地质编图人员的端到端交互路径图（Storyboards / Wireframe Specifications）。
3. `02-state-machine-design.md`：给出编图工作台的完整有限状态机（FSM）图表，严密定义 `IDLE`、`DIGITIZING`、`ADJUSTING_BOUNDARY`、`INSPECTING_QC`、`TIME_TRAVELLING` 等状态的跳转条件。
4. `03-tdd-ui-test-plan.md`：详细设计基于 `pytest-qt` 的人机交互测试用例矩阵（含模拟鼠标连击、拖拽取消、键盘快捷键连击、多线程数据刷新）。
5. `04-known-limitations.md`：记录本期不支持的边缘特性（如 4K 屏特殊 DPI 缩放下的像素微调等）。

---

## 4. 阶段二：TDD 驱动开发（红绿循环，逐 Ticket 推进）

每个 Ticket 严格执行：**写失败测试（Red）→ 最小实现（Green）→ 重构优化（Refactor）→ 单一 Atomic Git Commit**。

### Ticket 1：多期次地层层序时空滑块与视口联动 (`StratigraphicTimelineWidget`)
- **文件定位**：
  - 新建 `paleo_workbench/ui/components/stratigraphic_timeline_slider.py`
  - 修改 `paleo_workbench/ui/workstation/composite_document.py`
  - 修改 `paleo_workbench/mapping_workspace/layer_groups.py`
- **契约要求**：
  - 时间轴以地质年代刻度呈现（寒武系/奥陶系/石炭系等各期次），支持拖拽或方向键步进切换。
  - 切换期次时，主视口图层树以差分模式（Diff Transition）原子切换当前时期的矢量相带与参考图层，无需重建画布。
  - **洋葱皮模式（Onion-skinning）**：开启后，自动以 30% 半透明轮廓叠加相邻前一期次的相带边界，直观展示古地理进积/退积演化。
  - **TDD 先行**：编写 `tests/ui/test_stratigraphic_timeline.py`，使用 `qtbot` 模拟快速拖拽时间轴滑块，验证信号发射去抖动（Debounce）与图层切换状态一致性。

### Ticket 2：沉浸式相带编绘调色板与吸色管 (`FaciesPaletteWidget` & `FaciesEyedropper`)
- **文件定位**：
  - 新建 `paleo_workbench/ui/components/facies_palette_widget.py`
  - 新建 `paleo_workbench/ui/components/facies_eyedropper.py`
  - 修改 `paleo_workbench/ui/workstation/facies_selector.py`
- **契约要求**：
  - 基于 `facies_taxonomy.json` 树结构渲染网格化相带调色板，展示真实岩相 SVG 矢量花纹与地质代号。
  - **吸色管工具（Eyedropper）**：激活后在地图上点击任意已有相带，一键吸取其相带编码、颜色、花纹及属性模板，自动装备为当前绘图工具上下文。
  - 支持数字快捷键 `1~9` 快速切换常用相带类型，支持连续数字化无缝赋值。
  - **TDD 先行**：编写 `tests/ui/test_facies_palette.py`，测试吸色管点击、属性同步与快捷键快速切换响应。

### Ticket 3：单因素约束参考悬浮棚与跨视口联动 (`ConstraintFactorHUD`)
- **文件定位**：
  - 新建 `paleo_workbench/ui/components/constraint_factor_hud.py`
  - 修改 `paleo_workbench/ui/workstation/shell.py`
- **契约要求**：
  - 在编图视口右上角浮动显示当前光标所在位置的单因素支撑数据：等值线坡度值、最近控制井的相别分歧、砂地比数值及地震相预测置信度。
  - 支持多视口光标同步：当用户在主地图画线时，关联打开的连井剖面图自动以垂直光标线指示对应井位与层段，辅助边界决策。
  - **TDD 先行**：编写 `tests/ui/test_constraint_hud.py`，断言高频鼠标移动下 HUD 刷新无卡顿且不产生内存堆积。

### Ticket 4：交互式质检修复向导中心 (`InteractiveQCHub`)
- **文件定位**：
  - 新建 `paleo_workbench/ui/components/interactive_qc_hub.py`
  - 修改 `paleo_workbench/mapping/cartographic_qa.py`
  - 修改 `paleo_workbench/ui/workstation/topology_checker_panel.py`
- **契约要求**：
  - 将质检规则升级为交互式向导面板。列表中双击任一错误（如相带重叠、孤岛相带、悬挂断层），主地图立即平滑平移居中（Smooth Pan）并以差分红线高亮。
  - 提供**一键快速修复动作（QuickFix Actions）**：
    - 针对碎多边形：提供「吸附合并到相邻优势相」向导；
    - 针对未封闭边界：提供「沿切线自动延伸闭合」向导。
  - 每次修复均作为单一可撤销命令推入撤销栈。
  - **TDD 先行**：编写 `tests/ui/test_interactive_qc_hub.py`，验证从错误识别到一键修复并触发撤销的全链路交互。

### Ticket 5：工作台全键盘流与状态集成 (`WorkstationKeyBindingManager`)
- **文件定位**：
  - 修改 `paleo_workbench/ui/workstation/shell.py`
  - 修改 `paleo_workbench/ui/shortcuts.py`
- **契约要求**：
  - 实现专为古地理编图定制的高效快捷键方案（空格平移、Tab 键循环切换要素、Z/X 缩放、Ctrl+D 快速复制相带属性、Esc 安全退出工具），提供屏幕底部实时操作提示条（Keybinding HUD）。
  - **TDD 先行**：编写全键盘流端到端测试用例。

---

## 5. 阶段三：最后 Review 与视觉回归审计闭环

在所有界面控件与交互逻辑完成后，**启动严格的多重视角审查与自动化视觉验收**（并发 subagents $\le 2$）：

1. **Qt 内存与生命周期审查（Standards Track）**：
   - 检查所有动态生成的浮动面板、HUD 标签和上下文菜单是否均指定了正确的父级对象（Parent QObject），杜绝孤立部件导致的内存泄漏（参考 #962/#965 历史修复经验）。
   - 验证跨视口信号槽连接使用 Qt 的 `Qt::UniqueConnection` 或明确的断开机制，严禁循环触发（Signal Echo Loop）。
2. **地质编图工作流顺畅度审查（Spec Track）**：
   - 验证连续编图 30 分钟场景下，专家无需多余点击、无突兀弹窗打断创作流。
3. **自动化视觉回归测试（Visual QA）**：
   - 针对典型地质相图截取渲染快照，比对差异像素，验证时间轴切换与洋葱皮叠加的渲染准确性。
4. **验证报告与收尾**：
   - 在 `docs/development/paleo-ui-workbench/04-visual-qa-verification.md` 中记录测试用例通过率、UI 响应帧率与截图证明。
   - 使用 `gstack` 整理 commit，提交 PR。
```
