# 10 — Visual QA v10（M15）

`visual_qa_v10.py` + `tests/test_visual_qa_v10.py`（语义断言 hard-gate；
pixel diff 非门禁——V5 D8 政策）。

10 状态 × 语义检查（呈现 = canonical evaluator 结论）：

| 状态 | 关键语义断言 |
|---|---|
| raw_layer_readonly_surface | RAW 编辑禁用 + 判词 + chip「RAW · 只读」+ 查看类可用 |
| capture_preferred_line_role | add_line preferred + 按钮属性 + tooltip 编辑目标块 |
| editing_dirty_chip | chip「● 未保存」（文字符号，非仅颜色）+ save 可用 |
| snapping_detail_surface | 读数「捕捉: 开」+ tooltip 容差 + evaluator checked |
| topology_error_chip | chip 计数 + ⚠ + merge 被拓扑判词阻断 |
| crs_undeclared_surface | 「CRS: 未声明」诚实读数 + topology 门禁 |
| crs_mismatch_warning | ⚠ 前缀 + tooltip 解释 + 无伪造 CRS |
| frozen_layer_surface | chip「已冻结」+ 编辑禁用 + 冻结判词 |
| canvas_context_menu_surface | 菜单组合与工具条零漂移（同批 QAction） |
| compact_1366_toolbar_identity | 1366 下动作身份/结论保全 + 画布在场 |

注：本环境（Windows + 无桥）多状态同进程连跑有 Qt 崩溃面（既有环境
问题，见 13）；逐状态运行为绿。
