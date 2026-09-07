# 05 — Verification（V7 验证）

环境：Windows 11 + Git Bash；offscreen Qt；`qgis_render_bridge` 未构建
（与 main 一致——fallback 画布/树是本环境验证的生产行为）。venv cp312
（worktree 独立）。

## 新增测试（本 Goal）

| 文件 | 覆盖 | 数量 |
|---|---|---|
| tests/test_tool_surface.py | 可用性矩阵纯函数（§4 全阶段/角色/几何/会话/能力/未知 fail-closed） | 42 |
| tests/test_tool_surface_integration.py | QAction 表面（原因进 tooltip/statusTip、组可见、冻结门禁） | 12 |
| tests/test_layer_decorations.py | 装饰优先级/摘要/组聚合纯函数 | 9 |
| tests/test_layer_tree_v7.py | 状态列/差分重载/选择-滚动保持/双击定位/组聚合 | 10 |
| tests/test_inspector_v7.py | feature/factor/map_product 分节诚实性 | 14 |
| tests/test_toolbar_overflow_v7.py | 溢出收纳/恢复/1366 核心组/图层组门控 | 6 |
| tests/test_visual_qa_v7.py | 8 新状态语义 hard-gate | 9 |
| tests/test_perf_bounds_v7.py | §17 结构 bound ×4 | 4 |
| tests/test_review_fixes_v7.py | 评审 P0/P1 回归 | 8 |

合计 114 个新测试。

## 关键批次（全绿记录）

- 工具面/上下文：test_tool_surface*.py + test_stage_tool_filtering +
  test_mapping_stage_ui + test_ui_context_model + test_visual_qa_v6（119 passed）
- 工作站壳：test_workstation_shell/presets/lifecycle + test_app_shell +
  test_shell_p0_fixes（约 150 passed）
- 树/检查器：test_layer_tree_v7 + test_inspector_v6/v7 +
  test_composite_gis（54+27 passed）
- 视觉 QA：test_visual_qa_v7 + v6 + perf（24 passed）；评审修复批
  （105 passed）
- 视觉基线：`visual_qa/baseline-v7-matrix/` 32 PNG（尺寸与文件名一致
  校验过）+ manifest（ok=true ×32）+ 语义检查旁车

## Pre-existing 失败（非本分支引入；与 main db21f6cf 对比验证）

1. `test_composite_qgis_canvas.py` 5 项：需 qgis_render_bridge（未构建）。
2. `test_data_view_models.py::test_enrich_tag_map_cached_by_revision`：
   `_version_tag_display_map` 符号在 main 即缺失。
3. `test_keyboard_shortcuts.py::test_digit_shortcut_blocked_in_text_field`：
   offscreen 焦点行为（pristine main 同失败）。
4. 全量长跑环境项：`test_lod_render_path.py` 与
   `test_layer_visibility_authority.py` Windows access violation（GC-in-
   import 时序；单跑均过；字节级与 main 一致）；满载长跑时
   `test_theme_switch_with_open_project_shell` 可能超时（单跑 22s 过）。
   全量验收策略：分批运行（本 Goal 实际采用）+ 上述文件单跑。

## 100GB seismic

零涉及——无 seismic 代码路径修改，无 benchmark，无专项优化。
