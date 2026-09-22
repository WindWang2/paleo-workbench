# review_plan.md — Documentation-to-code audit

**Worktree**: `/workspace/paleo-workbench-doc-refresh`
**Branch**: `docs/project-documentation-refresh-2026`
**Open PR**: https://github.com/WindWang2/paleo-workbench/pull/1474 (base `main`)
**Tip at audit start**: `f4d3bc62` (8 docs commits ahead of `origin/main` @ `18c674ef`)
**Timezone**: Asia/Shanghai
**Mode**: REVIEW FIRST → FIX SECOND → VERIFY LAST (docs-only preferred)

## Phase 0 — Scope (recorded 2026-09-22)

### Git state
- `git status`: clean; branch `docs/project-documentation-refresh-2026`; ahead of `origin/main` by 8
- Tip: `f4d3bc62` — docs: record PR #1474 URL in documentation refresh verification
- `origin/main`: `18c674ef`
- Diff vs main: **12 files**, docs-only (README/PROJECT/CLAUDE + docs architecture/development)

### PR #1474
- Title: docs: refresh project documentation IA for native C++ product reality
- Explicit non-goals: no product source; no M12 packaging flip; no merge of #1473; do not merge until reviewed
- Reviews/comments: none at audit start

### Open PR / issue context (NOT current product capabilities)
- **#1473** `feat(native): C++ 100% final closure…` — OPEN follow-up; not merged → not product truth
- Sample open issues #1463–#1472: concurrency, qgis, io, ci, mapping — stability debt, not features to document as done

### PR-touched paths (verify)
README.md, PROJECT.md, CLAUDE.md, docs/README.md, docs/architecture/*, docs/development/cpp-conversion-status.md, docs/development/project-documentation-refresh-2026/*, docs/development/ribbon-five-workspaces/STATUS.md

### Audit scope (whole-repo docs vs code)
Not limited to PR diff. Priority: current source > build config > UI registration > merged behavior > PR history > current docs > old design docs.

### Checklist coverage (25 themes)
Architecture apps/libs; C++/Python; build/presets/versions; shell commands; root README new-user Qs; docs IA ≤3 clicks; project/dataset lifecycle; well-log; seismic honesty; QGIS boundary; tool/stage lifecycle; layers; single-factor; composite mapping; UI paths; screenshots; algorithms; diagrams; submodule READMEs; cross-doc contradictions; roadmap language; archive marking; SoT dedup; glossary; broken links; marketing ban.

### Evidence anchors used
- `apps/paleo_workbench_platform` → `pwb-platform`; 63 `libs/`; presets `linux-native-product` / `windows-msvc-native-product` → `build/native-product`
- Ribbon labels in `libs/ui_ribbon/src/ribbon_spec.cpp`
- `cmake_minimum_required(VERSION 3.27)`; Qt via `find_package(Qt6 6.8 …)`
- `pyproject.toml` script `paleo-workbench = paleo_workbench.main:main` (M12 not flipped)
- Submodules present in `.gitmodules` but **not checked out** in this worktree (empty dirs)
- Deploy/gate scripts accept multiple `pwb-platform` locations under build dir
