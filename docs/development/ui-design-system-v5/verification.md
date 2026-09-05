# UI Design System V5 — Verification Plan & Log

所有验证在本机离线完成（无线上 CI 依赖）。命令模板：

```bash
# targeted Qt/UI tests（worktree 内，offscreen）
cd /home/kevin/projects/paleo_project && \
  ./run_env.sh /home/kevin/projects/paleo-wt-ui-design-system-v5 tests/test_tokens.py ...

# 截图矩阵
./run_env.sh --python /home/kevin/projects/paleo-wt-ui-design-system-v5 \
  scripts/capture_workstation_screens.py <outdir>
```

## 基线（M0）
| 日期 | 范围 | 结果 |
|---|---|---|
| 2026-09-06 | test_tokens + test_theme_and_sidebar + test_workstation_presets（42 项） | 全部通过 |

## 分里程碑验证

| 日期 | 里程碑 | 测试集 | 结果 |
|---|---|---|---|
| 2026-09-06 | M0 baseline | test_tokens + theme_and_sidebar + workstation_presets | 42 passed |
| 2026-09-06 | U1 token V5 | hygiene + tokens + theme_and_sidebar + ui_batch6 | 37 passed |
| 2026-09-06 | U2 components | test_ui_components（3 主题×2 密度矩阵）| 15 passed |
| 2026-09-06 | U3 批次1 | module_relationship + home_start_guide + hygiene | 8 passed |
| 2026-09-06 | U4 dialogs | data_manager_* ui 套件 | 97 passed, 1 skipped |
| 2026-09-06 | U5 hosts | map_canvas_panel + qgis_screen_export_parity + composite（3 项失败为 native C++ 缺失环境性，基线同样失败）| 8 passed, 1 skipped |
| 2026-09-06 | U6 palette/shortcuts | test_command_and_shortcuts + app_shell + layout_persistence | 32 passed |
| 2026-09-06 | U7 density | tokens + theme_and_sidebar + workstation_lifecycle | 43 passed |
| 2026-09-06 | U8 matrix | capture_ui_matrix --core | 30/30 shots，26/30 与基线像素一致 |
| 2026-09-06 | U10 adversarial | test_ui_adversarial_v5 | 7 passed |

## 最终收敛（三轮 review 后，commit 3f832b2e）

分批跑全量 targeted UI 套件（Qt 重模块拆批防 core dump）：
- tokens + theme_and_sidebar + ui_components：45 passed
- command_and_shortcuts + app_shell：23 passed
- workstation_shell + module_relationship + layout_presets + layout_persistence：34 passed
- token_hygiene + data_manager_ui2 + adversarial_v5 + ui_batch6：22 passed

review 修复后重新捕获：矩阵 30/30（`--update-baseline` 落盘），
12 状态证据集刷新（`visual_qa/*.png`）。

## 已知环境性失败（非本方向回归）
- `tests/test_unified_map_visual_regression.py` 3 项 / `test_native_map_canvas.py` 2 项 /
  `test_map_canvas_panel.py` 1 项：native C++ 扩展（layer_model_core 等）缺失，
  基线 commit 上同样失败（design-qa.md Iteration 4 有记录）。

## 已知环境性失败（非本方向回归）
- `tests/test_unified_map_visual_regression.py` 3 项：native C++ 扩展缺失环境
  （baseline commit 上同样失败；design-qa.md Iteration 4 已记录）。
