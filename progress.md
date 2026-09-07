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
