# Workstation UX V6 — 09 验证报告

Date: 2026-09-07 · Environment: Windows 11 (win32 10.0.26200), Git Bash, CPython 3.12.13 (uv venv), PySide6 6.11.2, pytest 9.1.1 + pytest-qt 4.5.0, `QT_QPA_PLATFORM=offscreen`, QGIS 渲染桥**未构建**（composite 走诚实回退画布——这正是被验证路径之一）。

## 1. 测试证据（最终验证运行）

| 套件 | 结果 |
|------|------|
| V6 新测试清单（14 文件：ui_context/stage_tool/palette/shell_p0/raw_gate/state_language/inspector_v6/data_overview_perf/attribute_table_differential/large_list_differential/agent_ux/a11y_dpi/visual_qa_v6/review_fixes） | **101 passed** |
| 回归扫（workstation shell/presets/context/inspector/lifecycle + app_shell + app + command_and_shortcuts + composite_editing + mapping_stage e2e/teardown） | **112 passed** |
| 视觉回归（qgis/unified，无桥腿） | 3 passed, 1 qgis-skip |
| 阶段 5-8 子代理各自报告的套件 | data 家族 153+90+5+42p/1s；stratigraphy/visualization/prediction 家族 81p/6s；设计系统/组件/布局 42p；各自独立复核 |

## 2. 性能验证的性质（诚实声明）

- 断言为**结构性界限**（组合框 addItem 计数、QTableWidgetItem 创建数、`Path.is_file` 探针数、行重建数为常数/Δ 而非 O(n)）；墙钟仅宽松 backstop（2000 要素单编辑 <2s）。
- 未运行 100k/10k 全量墙钟基准（prompt 明确排除 100GB 级专项；已有分页契约测试钉 <50ms/页 @100k 构造数据）。
- 机器/平台声明：仅 Windows/offscreen 验证。**无 macOS/Linux 实机验证**（offscreen 平台为 CI 同款）；不做未验证的平台宣称。

## 3. 三轮独立深审

| 轮 | 视角 | 发现 | 处置 |
|----|------|------|------|
| 1 | 正确性 | 0 P0 / 1 P1 / 8 P2 | P1+7×P2 修复；group_summary 树渲染遗留 |
| 2 | 架构 | 1 P0 / 2 P1 / 3 P2 | P0（导入环）+P1×2+P2×1 修复；QA 工具触私有标注接受 |
| 3 | UX/性能/对抗 | 0 P0 / 1 P1 / 3 P2 | P1+P2×2 修复；write_granted 布尔粒度遗留 |

对抗性验证通过项（round 3 报告）：快速 A→B 工程切换无残留/无崩溃；无桥态状态段诚实显示「画布回退」；取消中/已取消语义保持；主题×密度×浮动/停靠循环（10 次）无异常；重名井在 key 差分下存活；新增缓存全部有界（单槽/frozenset/封顶）。

## 4. 已知环境性失败（**主分支即失败**，非本分支引入）

- `tests/test_map_authoring_architecture_guards.py::test_primary_mapping_page_uses_the_renderer_neutral_unified_canvas`（pristine main 复现）
- `tests/test_keyboard_shortcuts.py` 焦点用例 ×3（Windows/offscreen 焦点语义，pristine main 复现）
- `test_ui_exports` 导入顺序交互（子代理在 stash 基线上复现）

## 5. 复现命令

```bash
cd <worktree>
QT_QPA_PLATFORM=offscreen <venv>/Scripts/python.exe -m pytest \
  tests/test_ui_context_model.py tests/test_stage_tool_filtering.py \
  tests/test_palette_context.py tests/test_shell_p0_fixes.py \
  tests/test_raw_gate_closure.py tests/test_state_language.py \
  tests/test_inspector_v6.py tests/test_data_overview_perf.py \
  tests/test_attribute_table_differential.py tests/test_large_list_differential.py \
  tests/test_agent_ux_v6.py tests/test_a11y_dpi_v6.py \
  tests/test_visual_qa_v6.py tests/test_review_fixes_v6.py -q
```

审阅报告全文（不在提交内）：会话 `.planning/2026-09-07-workstation-ux-v6/review/review-{1,2,3}-*.md`。
