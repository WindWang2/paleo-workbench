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

## 分里程碑验证（随实现追加）

（每条包含：日期 / 测试集 / 结果 / 截图证据路径）

## 已知环境性失败（非本方向回归）
- `tests/test_unified_map_visual_regression.py` 3 项：native C++ 扩展缺失环境
  （baseline commit 上同样失败；design-qa.md Iteration 4 已记录）。
