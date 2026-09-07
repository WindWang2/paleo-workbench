# Progress — Workstation UI/UX V7

## Session 2026-09-08 (setup + audit)
- Worktree .worktrees/workstation-ux-v7 (branch feat/workstation-ux-v7 off main db21f6cf)
- Submodules geo-viz-engine (40ebd168) + well-log-engine (f845e7ab) via manual local
  clone from main checkout (network clone avoided, per V6 session note)
- uv venv cp312 + `uv pip install -e ".[dev]" -r requirements-geoviz.txt` OK
- Native pyds copied from main (grid_render_core, layer_model_core, seismic_3d_core,
  well_log_core) — cp312 ABI-compatible
- Smoke: tests/test_audit_ui.py 6 passed 1 skipped (offscreen)
- Full baseline suite running (fast selection) → .baseline-test-results.txt
- 5 parallel explore audits completed: command surface, pages/docks, design debt,
  context/state services, visual QA + prior-goal docs. Synthesized into findings.md.
- KEY: CommandRegistry predicates dormant (0 production uses); 2 MapActionController
  instances; 3 stage vocabularies; 44-file light-snapshot theme debt; ratchet RED
  (agent_panel 3>2, curve_operation_dialog 1>0); layer tree has zero state decorations;
  group_summary computed but unconsumed; hub force-float seam; 11 non-active page files.
- Planning files rewritten for V7 (repo convention: tracked per-goal).

## Next
- PHASE 2: write docs/development/workstation-ux-v7/00-baseline.md (from findings),
  01-target-state.md, 02-architecture.md, 03-decisions.md; then M1 implementation.

## Session 2026-09-08 (M1–M4)
- M1/M2 committed 0e398f98: tool_surface.py 单一可用性真源（42 矩阵单测 +
  12 Qt 集成）；composite/mapping_page/shell/palette 全部接线；冻结成熟度
  门禁进入 _role_allows_editing；hub 导航经 navigation_requested 真切换。
- M4 committed a5941bdb: layer_decorations + 回退树状态列/差分重载/双击定位 +
  原生面板摘要行 + 组聚合（frozen/published + fallback 真实派生）。
- state_language 扩词（freshness 全集 + session；🔒→⊘）。
- 基线：tests/test_lod_render_path.py 与 test_layer_visibility_authority.py
  在全量运行时 Windows access violation（GC-in-import 时序 flake；单跑均过，
  main 同现象——非本分支引入）。全量基线第三轮（排除上述两文件）后台进行中。
- test_composite_qgis_canvas 5 失败为 main 既有（需桥）。
- 注意：git add -A 不会加入 .baseline-*.log（已 gitignore）。

## Session 2026-09-08 (M5–M6)
- M5 committed 834e33df: 类型化 Inspector（feature/factor/map_product 分节
  + 树选择路由 + identify 双击 + assemble 后进入 Inspector）。
- M6a committed 4b70cdf9: 视觉收敛 wave1——ratchet 修红；geo3d 47 处
  setStyleSheet→style.bind（+20 字号 token 化）；5 文件快照迁移；10 文件
  snapshot+定宽批；43 处 emoji 清零（测试 pin 同步 9 处）。
- M6b committed 4f48e214: readiness 词表 + tone_to_badge 桥 + STAGE_ICONS
  派生 + filter_index canonical 路由 + 3 条新 ratchet（font 104→41 冻结、
  fixed 42→12 冻结、emoji 硬禁）。
- 4 个并行迁移 agent 曾并发编辑：inspector_panel NameError 与 geo3d f-string
  语法错误均在合并后修复（互相补救）；教训：并发 agent 共享文件有风险，
  后续按不相交文件集分派（本次已如此，残余是跨集引用）。
- 基线-3 全量在 86% 因 test_theme_switch_with_open_project_shell 超时中断
  （单跑 PASS 22s；HEAD 与工作树均如此——满载堆压力下的时序环境项，
  与 test_lod_render_path/test_layer_visibility_authority GC-flake 同类）。
- pre-existing main 失败（本分支同样出现，非本分支引入）：
  test_data_view_models::test_enrich_tag_map_cached_by_revision（符号缺失）、
  test_composite_qgis_canvas 5 项（需桥）、test_version_workbench_dialog_ui
  1 项 Windows PermissionError flake。
- 剩余 M6 债（登记在 ratchet 预算中）：41 行字号字面量 / 12 处定宽。
