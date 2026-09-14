# Progress — Paleo UI Workbench

## Session 2026-09-14

### PHASE 0 (complete)
- worktree ../paleo-workbench-paleo-ui @ feat/paleo-ui-workbench (off main e7214566)
- geo-viz-engine 子模块本地 reference 初始化成功
- 复用主仓 .venv 冒烟通过：tests/test_facies_taxonomy.py 15 passed (offscreen)

### PHASE 1 (complete)
- Explore×2 完成（workstation UI / domain+canvas），要点入 findings.md
- 5 份文档落盘 docs/development/paleo-ui-workbench/：00-decisions(13 条)、
  01-interaction-specs(S1-S5 storyboards)、02-state-machine(5 态 FSM 转移表)、
  03-tdd-ui-test-plan(≈112 用例矩阵)、04-known-limitations(22 条)

### 测试记录
| 命令 | 结果 |
|---|---|
| pytest tests/test_facies_taxonomy.py (worktree, offscreen) | 15 passed |

### PHASE 2 / Ticket 1 (complete)
- 新增 workflow/stratigraphic_epochs.py（内置年代方案+目录合并）、
  mapping_workspace/epoch_switching.py（差分计划器+洋葱皮集合）、
  ui/components/stratigraphic_timeline_slider.py（部件+执行器）
- layer_groups.py 增 epoch 组 id 助手；composite_document.py 挂载时间轴+
  控制器接线+set_project 目录刷新；shell.py 期次→层位条同步
- 外科修复 canvas_shim 半构造残件 resizeEvent AttributeError（_canvas_created
  防护）——同时解除了既有 test_mapping_stage_ui 在本机的环境性失败
- tests/ui/test_stratigraphic_timeline.py 24/24 绿；回归 63 passed

### PHASE 3 / Ticket 2 (complete)
- facies_selector.py + FaciesBrushContext（幂等装备/清空）；stage_actions 抽出
  facies_category_color 单一取色真源；新组件 facies_palette_widget /
  facies_eyedropper（pick_facies_at 纯函数双栈一致）
- composite_document：画刷优先捕获赋值（单一撤销命令零模态）、吸色管点击
  （fallback map_clicked / Python identify_all）、数字键 1-9 绘图期动态注册
- app_shell：hub 页导航"绘图期"守卫（D6 双保险；offscreen 无法实证路由）
- dock：facies_palette 描述符 + shell 停靠 + 面板菜单
- tests/ui/test_facies_palette.py 18/18；回归 97 passed

### PHASE 4 / Ticket 3 (complete)
- ui/components/constraint_factor_hud.py：O(1) 采样纯函数（双线性/钳制差分坡度/
  方差置信度/线性最近井）+ HUD 部件（画布子控件、鼠标穿透、8 标签固定）+
  HudController（60ms 合并节流、井位联动发布、300ms 延迟清除、同井去重）
- view_coordination：set_section_cursor_sink/publish_section_cursor（去重+单次
  清除，clear 不节流）；CompositeDocument 挂 HUD+网格缓存；app_shell 注入
  view_coordination + sink → CompositeVisualizationPanel.show_section_cursor
  （井位级竖带指示；引擎无 crosshair API，04 #11 已更新）
- tests/ui/test_constraint_hud.py 15/15；回归（含 view_coordination/visualization
  panel/workstation shell）151 passed

### PHASE 5 / Ticket 4 (complete)
- mapping/qc_quickfix.py：sliver_merge（共享边最长/并列面积优势相，单命令合并
  +整体撤销）/ tangent_close（切线延伸步长=容差×0.5 上限容差×8，不可修诚实禁用）
- ui/components/interactive_qc_hub.py：SmoothPanController（180ms ease-in-out、
  4-12 帧、历史恰 1 条、用户可打断）+ InteractiveQCHub（来源聚合/双击定位/
  Enter 定位/F 修复键盘流/修复按钮 availability+tooltip）
- composite_document：qc_hub 挂画布下（拓扑 chip 激活时与拓扑面板同开）、
  修复执行→单一撤销命令→mark_resolved→即时重组；cartographic_qa 增
  issues_for_interactive_hub 适配器（bbox/layer_id 定位字段）
- tests/ui/test_interactive_qc_hub.py 15/15；回归（ui/topo/stage）全绿

### PHASE 6 / Ticket 5 (complete)
- workstation/mode_state.py：5 态 FSM（02 转移表全实现 + 瞬态 pan_held +
  mode_before_travel 回退）+ MODE_HINTS 查找表
- workstation/keybinding_manager.py：composite/canvas 双挂事件过滤器
  （Space 临时平移/Tab 循环/Z-X 中心缩放/Ctrl+D 吸属性/Esc 退出链）+
  提示条 KeybindingHintBar；文本输入聚焦全让路
- shortcuts.py：register_shortcut 增 context 参数（默认应用域不变）
- composite_document：tab_cycle_selection/ctrl_d_pick_facies + FSM 事件桥
  （工具/时间轴/QC 面板显隐）；修复中发现并修正 VectorLayer.selection
  为 property 的调用形态
- tests/ui/test_mode_state 8 + test_keybinding_flow 10 全绿；
  全壳回归（workstation_shell/keyboard_shortcuts/dock_framework）59 passed

### PHASE 7 (审查修复 + 视觉验证)
- 双轴审查（2 agents）：Standards 双 gate PASS（memory/echo）；Spec 4 阻断+
  8 摩擦 → 修复 B1-B4/F2/F3/F6/F8/P1-1..P1-5/P2/P3（洋葱皮层序获像素级证据
  #8ead9f=30% 精确混合色）
- 视觉回归 6 用例（结构/状态 gate + 测量记录，D13-rev2 回归 V5 D8 政策）；
  4 张证据截图 assets/；04-visual-qa-verification.md 落盘
- tests/ui 98/98 全绿；全量套件第二轮后台复跑中
