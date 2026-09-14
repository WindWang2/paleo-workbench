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
