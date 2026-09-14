# Task Plan — Paleo UI Workbench (feat/paleo-ui-workbench)

## Goal
古地理编图专属 UI 交互工作台与多期次时空联动系统（M1-M5）：层序时间轴期次差分切换
+ 洋葱皮、相带画刷调色板 + 吸色管、单因素约束 HUD + 连井剖面光标联动、交互式 QC
修复向导、全键盘编图流 + FSM。Document-First → TDD（红绿循环，逐 Ticket 原子提交）
→ Review（回环/泄漏/视觉回归）。

Worktree: C:\Users\wangj.KEVIN\projects\paleo-workbench-paleo-ui
Branch: feat/paleo-ui-workbench (off main e7214566)
Docs: docs/development/paleo-ui-workbench/
Loop exit: docs_generated && ui_tdd_all_green && memory_and_leak_free && visual_review_passed

## Hard constraints
- subagents ≤ 3 并发（已用 2 Explore，后续 Review ≤ 2）
- QT_QPA_PLATFORM=offscreen；无交互弹窗
- 纯 Python/PySide6，不重编 C++ 桥；`-m "not slow and not opengl"`
- UI 线程零耗时空间运算（O(1) 网格采样/节流）；无 Signal Echo Loop（suppress-flag /
  source-tag / changed-field 既有模式）

## Environment recipe (verified)
- 解释器：主仓 .venv（editable finder 在 sys.meta_path 尾部，worktree rootdir 的
  pythonpath=["."] 前置生效 → 导入 worktree 代码，已验证）
- `cd /c/Users/wangj.KEVIN/projects/paleo-workbench-paleo-ui && QT_QPA_PLATFORM=offscreen
  /c/Users/wangj.KEVIN/projects/paleo-workbench/.venv/Scripts/python.exe -m pytest ...`
- 冒烟：tests/test_facies_taxonomy.py 15 passed @ worktree
- 无桥 → fallback canvas（测试用 `_force_fallback` monkeypatch 模式，见
  tests/test_mapping_stage_ui.py L21）

## Phases
- [x] PHASE 0: worktree + branch + geo-viz-engine 子模块 + 冒烟
- [ ] PHASE 1: 规划文件 + 文档 00-decisions / 01-interaction-specs /
      02-state-machine-design / 03-tdd-ui-test-plan / 04-known-limitations
- [ ] PHASE 2 / Ticket 1: ui/components/stratigraphic_timeline_slider.py +
      workflow/stratigraphic_epochs.py + mapping_workspace/epoch_switching.py +
      composite_document/layer_groups 接线；tests/ui/test_stratigraphic_timeline.py
- [ ] PHASE 3 / Ticket 2: ui/components/facies_palette_widget.py +
      facies_eyedropper.py + facies_selector.py 画刷上下文；tests/ui/test_facies_palette.py
- [ ] PHASE 4 / Ticket 3: ui/components/constraint_factor_hud.py +
      连井光标桥（view_coordination 扩展）；tests/ui/test_constraint_hud.py
- [ ] PHASE 5 / Ticket 4: ui/components/interactive_qc_hub.py +
      mapping/qc_quickfix.py + cartographic_qa.py 接线；tests/ui/test_interactive_qc_hub.py
- [ ] PHASE 6 / Ticket 5: workstation/keybinding_manager.py + mode_state.py(FSM) +
      shortcuts.py + shell.py 组装 + 提示条；tests/ui/test_keybinding_flow.py
- [x] PHASE 7: 双轴审查（Standards 双 gate PASS / Spec B1-B4+F 项修复）+
      echo/泄漏审计测试 + 视觉回归（D13-rev2 政策）+ 像素级洋葱皮证据 +
      04-visual-qa-verification.md + 全量套件复跑 + PR

## Key architecture anchors (from Explore reports)
- Shell = WorkstationFrame (ui/workstation/shell.py L96)；dock 注册 dock_framework.py
  WORKSTATION_DOCKS + shell._PANEL_TOGGLE_TABLE/_shell_docks()
- CompositeDocument：canvas=QgisCanvasShim|UnifiedMapCanvas；signals map_position_changed/
  native_identified；set_layer_snapshot(snapshot, changed_hints) 增量镜像；
  set_extent(extent, record_history, coalesce_history)；无动画 pan
- 期次锚点：stratigraphy.target_horizon（workflow/stratigraphy.py：set_target_from_boundary/
  active_target_horizon/horizons_from_data/ensure_horizon_catalog）；PaleoMapDocument.
  linked_target_horizon；现无按 horizon 换层逻辑（GAP=本任务补齐）
- 相：resources/facies_taxonomy.json（8相/24亚相/66微相）；属性 facies/sub_facies/
  micro_facies/level；现无"当前相带"状态（每次捕获弹模态框）；颜色=stage_actions.
  _categorized_facies_style；花纹=mapping/facies_patterns.py
- 拾取：composite_editing.identify_all(point, base_layers) L2802（双画布可用）；
  FeatureQueryIndex.query 顶层优先
- 撤销：无 QUndoStack；VectorEditSession.begin/end_edit_command（fallback）+
  NativeEditSessionController gesture（native）
- 快捷键：shortcuts.register_shortcut（ApplicationShortcut + 同 id 重注册替换）；
  已占用 Ctrl+S/N/O/F、1-5(hub)、Alt+1/2/3、Ctrl+K、Ctrl+Alt+D、F5、F1、Delete、
  Ctrl+Z、Ctrl+Shift+Z、Esc(map)
- QC：TopologyCheckerPanel(zoom/highlight/fix 信号已有)；cartographic_qa.py 纯检测
  无 UI 无修复；issue dict=make_issue(workflow/qc.py L27)
- 跨视图：ViewCoordinationController.set_link_cursor_sink((well,md)→engine crosshair)
  已有；连井 CrossWellHost 未接入 SelectionContext（本任务接线）
- 泄漏审计：conftest cleanup_qt_deferred_deletes L153 autouse（reap 匿名 parentless）
- 视觉：visual_qa_v11.py v11_shot_table 模式；像素 diff 非 gate（V5 D8），本任务按
  prompt 做带阈值 diff 并记录数值

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| (none yet) | | |

## Decisions
1. 复用主仓 .venv（已验证 import 解析到 worktree）——不为 worktree 另建 venv
2. 时间轴期次 = 项目 horizon 目录（权威）+ 内置地质年代方案（寒武系…第四系）标签
   合并；排序 age 优先（见 00-decisions D3）
3. 期次差分切换 = 纯计划器（epoch_switching.py）算 show/hide/onion 集合 → 增量可见
   性/透明度应用（零画布重建）
4. 相带数字键 1-9 与 hub 导航 1-5 冲突 → 画布域 WidgetWithChildrenShortcut + 工具
   激活期动态注册；Ticket 2 先以测试实证 Qt 跨上下文优先级再定稿（00-decisions D6）
