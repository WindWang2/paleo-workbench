# 03 — TDD UI 测试计划（pytest-qt 用例矩阵）

运行配方（所有用例）：
```
cd <worktree> && QT_QPA_PLATFORM=offscreen \
  <main>/.venv/Scripts/python.exe -m pytest tests/ui/... -m "not slow and not opengl"
```
通用约定：构造走既有三范式（AppShell 全壳 / WorkstationFrame+`_force_fallback`
monkeypatch / 纯鸭子 Fake）；禁止交互弹窗（模态断言：QDialog 实例计数）；
每 Ticket Red→Green→Refactor→原子 commit。

## M1 时间轴（tests/ui/test_stratigraphic_timeline.py）

| 组 | 用例 | 手势/机制 | 断言要点 |
|---|---|---|---|
| 目录 | epoch_catalog_merge_builtin_and_project | 纯函数 | horizon 目录+内置年代合并、去重、age 排序（D1） |
| 目录 | epoch_catalog_empty_project_honest | 纯函数 | 空项目→空目录，UI 显示"无期次数据"占位 |
| 去抖 | drag_scrub_no_commit_until_release | qtbot mousePress/Move ×20/Release | scrubbed≥1、committed==1、目标=末刻度 |
| 去抖 | rapid_key_steps_single_commit | keyClick(→)×5 + wait 150ms | committed==1 |
| 差分 | switch_plan_symmetric_diff_only | 纯函数 | show/hide==对称差；非期次层零触碰 |
| 差分 | switch_applies_incremental_no_rebuild | FakeCanvas 记账 | set_layer_visible 计数==对称差；无 set_project/重建调用 |
| 差分 | switch_writes_horizon_metadata | ProjectDocument | target_horizon==新期次（经 set_target_from_boundary） |
| 差分 | switch_failure_rolls_back | 执行器注入异常 | 可见性恢复切换前快照 |
| 洋葱皮 | onion_enables_prev_epoch_30pct | qtbot click | 前期次相带层 opacity==30 且可见；当前层不透明度不变 |
| 洋葱皮 | onion_disable_restores_user_values | qtbot click×2 | 恢复 StageViewState 原值 |
| 洋葱皮 | onion_first_epoch_no_prev | click | 边界：最老期次开启→提示无前期次，零层触碰 |
| 键 | arrow_step_wraps_ends | keyClick(←/→) | 到端不越界（clamp 或回绕按实现声明） |
| 集成 | timeline_in_composite_document | _force_fallback 全文档 | 挂载位置、信号连通、stage_bar horizon 同步不回环 |

约 26 用例。

## M2 调色板/吸色管（tests/ui/test_facies_palette.py）

| 组 | 用例 | 手势/机制 | 断言要点 |
|---|---|---|---|
| 前置 | digit_key_scope_precedence | QApplication 级"5"+画布域"5" 双注册 | 实证跨上下文分发；结论写 00-D6（gate 用例） |
| 面板 | palette_renders_taxonomy_sections | 构造 | 8 相分区、亚相格数==taxonomy 树 |
| 面板 | palette_click_equips_brush | qtbot click 格 | FaciesBrushContext 四元组更新+高亮 |
| 面板 | palette_colors_match_renderer | 纯函数 | 格颜色==分类渲染器同相颜色（三处一致 D11） |
| 画刷 | captured_feature_auto_assigned_no_dialog | FakeEditController feature_captured | 0 次模态；要素属性==装备相带 |
| 画刷 | continuous_assignment_three_features | 连续 3 次捕获 | 3 要素全赋值；每要素 1 撤销命令 |
| 画刷 | brush_off_falls_back_to_dialog | 装备空+捕获 | 回退既有模态路径（不回归） |
| 吸管 | eyedropper_pick_equips_from_feature | FakeCanvas map_clicked | identify_all 顶层优先；四元组+颜色+花纹==源 |
| 吸管 | eyedropper_empty_click_keeps_brush | 点击空白 | 装备不变+toast |
| 吸管 | eyedropper_skips_non_facies_layer | 拾取命中非相层 | 跳过取下一命中或空 |
| 数字键 | digit_key_switches_when_tool_active | 激活工具+keyClick("3") | 装备==第3常用格 |
| 数字键 | digit_key_inert_when_tool_off | 工具未激活+keyClick("3") | 装备无变化（且 hub 导航可达） |
| 数字键 | digit_keys_bound_unbound_with_tool | 生命周期 | 工具退出→快捷键注销（注册表空） |

约 22 用例。

## M3 HUD/联动（tests/ui/test_constraint_hud.py）

| 组 | 用例 | 手势/机制 | 断言要点 |
|---|---|---|---|
| 采样 | bilinear_sample_grid_bounds | 纯函数 | 网格内插值正确、外/空网格→None |
| 采样 | slope_from_local_gradient | 纯函数 | 平面网格→解析坡度；单位换算 |
| 采样 | confidence_from_variance | 纯函数 | σ→置信单调；无 variance→None |
| HUD | hud_updates_throttled_under_burst | 发射 map_position_changed×1000（<60ms 间隔） | 刷新调用 ≤ ⌈时长/60ms⌉+1；值==最后点 |
| HUD | hud_missing_data_shows_dash | 无网格/无井 | 字段"—"（不猜值） |
| HUD | hud_no_widget_growth_high_freq | burst 后 | topLevelWidgets 恒定；无新 QLabel 分配 |
| HUD | hud_parented_to_canvas_container | 构造 | parent 链到画布容器；WA_TransparentForMouseEvents |
| 联动 | map_cursor_near_well_publishes_link | FakeViewCoordination | (well,md=None) publish；source tag 正确 |
| 联动 | section_sink_receives_crosshair | Fake sink | sink 调用；300ms 延迟清除 |
| 联动 | echo_break_no_republish_on_sink_write | sink 回写模拟 | 无二次 publish（计数==1） |
| 联动 | leave_tolerance_clears_once | 出入容差抖动 | 清除恰一次（防闪烁） |

约 18 用例。

## M4 QC Hub（tests/ui/test_interactive_qc_hub.py）

| 组 | 用例 | 手势/机制 | 断言要点 |
|---|---|---|---|
| 聚合 | hub_merges_carto_and_topology_issues | set_issues×2 来源 | 统一列表、severity 计数正确 |
| 定位 | double_click_smooth_pan | qtbot 双击项 | FakeCanvas extent 序列：末态==bbox+pad、帧数∈[4,12]、中心单调、history 记录恰1 |
| 定位 | smooth_pan_cancelled_by_user_input | pan 中 wheel | 立即终断（用户优先） |
| 高亮 | focus_highlights_issue_features | 选中/定位 | 高亮状态含目标要素（native: highlight 调用；fallback: 选中集） |
| 修复 | sliver_merge_into_dominant_neighbor | 纯几何 | 并入共享边最长相；并列取面积；属性取优势相 |
| 修复 | sliver_merge_single_undo_command | 真会话 | undo×1 完全复原（要素+几何+属性） |
| 修复 | tangent_close_within_tolerance | 纯几何 | 沿切线延伸闭合成功；几何 valid |
| 修复 | tangent_close_unreachable_disables | 纯几何+UI | 超 容差×8 → 按钮禁用+tooltip 原因 |
| 修复 | fix_refreshes_issue_list | 应用修复 | 该 issue 从列表消失 |
| 修复 | undo_restores_issue_reappears | 修复+undo | issue 复现于列表 |
| 向导 | keyboard_flow_arrows_enter_f | keyClick 序列 | ↑↓ 选择、Enter 定位、F 修复（S5-2 提示一致） |
| 集成 | topology_panel_routes_into_hub | 既有面板信号 | 桥接后旧面板行为不回归 |

约 20 用例。

## M5 键盘流/FSM/组装（tests/ui/test_keybinding_flow.py + test_mode_state.py）

| 组 | 用例 | 手势/机制 | 断言要点 |
|---|---|---|---|
| FSM | full_transition_table_matrix | 全 状态×事件 组合 | 每格符合 02 转移表（参数化 40 组合） |
| FSM | echo_audit_no_reentrant_dispatch | 全组合 | mode_changed 发射≤实际变化；无二次 dispatch |
| FSM | transient_pan_flag_lifecycle | PAN_HELD/RELEASE | 标志置位/复位，mode 不变 |
| 键 | space_temporary_pan_press_release | keyPress/Release(Space) | pan 工具进出对称，原工具还原 |
| 键 | tab_cycles_selection | DIGITIZING+keyClick(Tab)×N | 选中循环 N%len==0 回起点；非画布聚焦无效 |
| 键 | z_x_zoom_center | keyClick Z/X | zoom_by(1.5 / 1/1.5) 恰一次 |
| 键 | ctrl_d_picks_facies_from_selection | 选中要素+Ctrl+D | 装备==选中要素相带（=吸色管键盘路径） |
| 键 | esc_safe_exit_chain | DIGITIZING 中 Esc×3 | 手势取消→工具退出→面板关闭→IDLE（状态序列） |
| 键 | keys_disabled_in_text_input | 焦点入 QLineEdit + 键 | 全部不触发（复用 focus_in_text_input 守卫） |
| HUD条 | hint_bar_text_follows_mode | 驱动 FSM | 文本==查找表；信号驱动 |
| E2E | keyboard_only_authoring_script | 依次：数字键装备→3×捕获→Tab→Ctrl+D→Z/X→Esc | 0 模态框；FSM 轨迹==预期序列；3 要素属性正确 |
| E2E | conflict_regression_hub_nav_intact | 装备态按"1" | hub 页切换不破坏（或按 D6 实证结论） |

约 26 用例（FSM 参数化展开后计数 >40）。

## 视觉回归（tests/ui/test_visual_regression_paleo.py，Phase 7）

| 用例 | 机制 | gate |
|---|---|---|
| same_epoch_snapshot_stable | 同期次两次切换往返 grab() | 像素 diff == 0 |
| onion_skin_diff_measured | 洋葱皮开/关 grab() 对比 | diff ≥0.5% 差异像素且 <80%（防渲染错误） |
| palette_snapshot_deterministic | 重建调色板两次 grab | diff == 0（无随机色/布局） |
| hud_not_obscuring_canvas_center | HUD 显示时中心区域 grab | HUD 像素不侵入中心 50% 区域 |
| timeline_epoch_labels_visible | 时间轴 grab + 结构断言 | 每期次刻度 label visible（结构 gate） |

## 量级合计

新增 ≈ 112 显式用例（FSM 参数化展开 +~40）；连同既有 UI 套件，Phase 7 全量
`-m "not slow and not opengl"` 回归 ≥400 用例（$loop 的 `ui_tdd_all_green` 口径）。
