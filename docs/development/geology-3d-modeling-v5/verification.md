# 3D Geological Modeling V5 — Verification Log

本地验证记录（持续追加）。环境：`run_env_g3d.sh`（conda py3.13，offscreen，
PYTHONPATH 指向本 worktree 子模块）。并发约束：native 构建 ≤2，Qt 测试小批。

## 基线（实现前）

- 2026-09-06 targeted 3D 套件：80 passed / 3 skipped / 1 failed
  （`test_geological_modeling_3d_page_clip_and_tie_without_show` maximumWidth
  flake —— origin/main 同样失败，记入 E5 待修）。

## 阶段验证（实现中逐项追加）

- 子模块 scene objects（feat/scene-object-overlays）：
  `tests/test_scene_objects.py` + `tests/test_scene_render_to_world.py`
  18 passed；geoviz_seismic 全量 1752 passed / 6 skipped（无回归）。
- 主仓 geomodel V2 模块：domain 23 + builders 19 + qc 18 + exporters 16 +
  measure/section 14 + scene_adapter 18 = 108 headless 用例全绿。
- 页面集成：joint_layout / stratal_entry / joint_page / 3d_page /
  joint_persistence / well_pick / layer_visibility / cross_page_sync /
  view_coordination / context_scenarios 89 passed；
  V5 集成（含 30 轮 project 切换 teardown）16 passed；
  规模基准（100/500/1000 井、50 面、decimation、内存上限）7 passed；
  provenance 流 6 passed。
- 页面导出入口接 V2（体积对象→FLAC3D/Abaqus、面片→OBJ/STL/VTP），遗留
  GridSpec 路径保留且诚实标注 LEGACY。
- 既有 flake 修复：`test_geological_modeling_3d_page_clip_and_tie_without_show`
  的 maximumWidth<=320 断言与页面契约矛盾（:793 注释明确 cap=QWIDGETSIZE_MAX），
  改为 minimumWidth>=220 + maximumWidth>=QWIDGETSIZE_MAX 的确定性断言；
  `test_geological_modeling_3d_page_ui_elements` 改断言 V5 workspace
  （gl_widget 已按 ADR-01 移除）。

## 最终验证

（全量测试运行后填写）
