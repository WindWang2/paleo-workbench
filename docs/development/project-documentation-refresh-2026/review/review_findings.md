# review_findings.md — First-pass documentation-to-code audit

**Baseline code**: `origin/main` @ `18c674ef` (+ docs tip `f4d3bc62`)  
**Date**: 2026-09-22 (Asia/Shanghai)  
**Method**: claims in primary docs and linked design/status docs checked against tree, CMake, UI registration, and existing ledger honesty rules.

## Counts (first pass)

| Severity | Count |
| --- | --- |
| P0 | 1 |
| P1 | 8 |
| P2 | 14 |
| P3 | 6 |
| **Total** | **29** |

**Documents / areas sampled**: root README/PROJECT/CLAUDE/CONTEXT + refreshed docs IA/architecture/conversion/ribbon STATUS + linked UI design authority READMEs + ribbon `00-plan.md` + selected root legacy reports (FINAL_REPORT, TEST_*) + build presets/CMake + `libs/`/`apps/` layout + pyproject + submodule stubs (~25 primary docs + code surfaces).  
**Claims matrix rows**: see below (~40 audited claims).

---

## Claim matrix (excerpt)

| Claim | Referenced module | Actual code | Status | Severity | Required fix |
| --- | --- | --- | --- | --- | --- |
| Native product = `pwb-platform` | apps/paleo_workbench_platform | `add_executable(pwb-platform)` | OK | — | — |
| 63 libs | libs/ | `ls libs` → 63 | OK | — | — |
| Presets linux/windows-native-product → build/native-product | CMakePresets.json | binaryDir matches | OK | — | — |
| CMake ≥ 3.24 | README | `cmake_minimum_required(VERSION 3.27)` | **FALSE** | P0 | Raise to ≥ 3.27 |
| Qt 6.8+ | README | `find_package(Qt6 6.8 …)` + presets 6.8.0 | OK | — | — |
| `--headless-self-check` / `--capabilities` | README | bootstrap.cpp / main.cpp | OK | — | — |
| Gate scripts exist | README | run-integrated-gate.sh, final-closure-gate.sh, Invoke-* | OK | — | — |
| Ribbon adopted on main | STATUS / README | fa9ba744 / cebc9f0a on main | OK for STATUS | — | — |
| Design authority still “未实现” | ui-redesign READMEs | contradicts fa9ba744 | **CONFLICT** | P1 | Status banners |
| Plan still “计划草案” | ribbon 00-plan.md | STATUS claims header updated | **FALSE ledger** | P1 | Fix plan header |
| CONTEXT dual-track banner | refresh 01-findings | **no banner in CONTEXT.md** | **FALSE** | P1 | Add banner |
| Packaging entry still Python | conversion-status | pyproject scripts paleo-workbench | OK | — | — |
| Python count ~678 | conversion-status | find paleo_workbench → 678 | OK | — | — |
| ~991 cpp / ~895 hpp | conversion-status | 991 cpp; 895 hpp (+57 .h) | OK | — | — |
| 33 ADRs | conversion-status | ls docs/adr → 33 | OK | — | — |
| Workspace labels 数据管理…验证 | README short list | ribbon_spec.cpp: 数据管理 / 1 智能预测 / 2 … / 3 … / 验证 | DRIFT | P2 | Align labels |
| F5 `closure_mapping` lib | PROJECT.md | no such lib; app `closure_mapping_install.cpp` | **MISNAME** | P2 | Rename to install/closure_workflow |
| Module map “covers 63” | DoD D4 | group sketch, not enumerated 63 | OVERCLAIM | P2 | Soften / list |
| WellPlot path | README | needs submodule init; dirs empty here | CONDITIONAL | P2 | Note submodule required |
| Binary path only under apps/… | README | deploy also finds bin/ and build root | INCOMPLETE | P3 | Note alternates |
| #1473 gaps still open | conversion-status | PR still OPEN | OK honesty | — | — |
| Local links in refreshed set | link script | 47 checked, 0 broken | OK | — | — |
| FINAL_REPORT root marketing | root | Aug-2026 Python-era metrics | STALE | P1 | Historical banner / demote |
| Screenshots in ui-redesign | design READMEs | design mockups, not product shots | OK if labeled | P2 | Ensure CURRENT/DESIGN labels |
| CMake STATUS “Python pages remain production path” | CMakeLists | skip messages for optional UI slices | CONFUSING | P3 | Docs note only if cited |
| geomodel-architecture.md Python paths | docs/ | paleo_workbench.viz; Aug 2026 | STALE | P2 | Historical marker |
| plugin-runtime-status WLE paths | docs/ | submodule empty; WellPlot Python host | LEGACY-LEANING | P2 | Dual-track / historical note |
| Submodule READMEs | well-log / geo-viz | **empty checkout** | UNVERIFIED here | P2 | Note; do not invent |

---

## Findings

### P0

#### F-P0-01 — Wrong CMake minimum version
- **Document**: `README.md` § Native product / Requirements  
- **Section**: Requirements  
- **Claim**: “CMake ≥ 3.24”  
- **Evidence**: `CMakeLists.txt:4` → `cmake_minimum_required(VERSION 3.27)`; platform ledgers cite 3.27.  
- **Problem**: New users / CI with 3.24–3.26 will fail configure after following README.  
- **Recommended fix**: Change README (and any mirrored claim) to **CMake ≥ 3.27**.

### P1

#### F-P1-01 — UI design authority still says “not implemented” while product docs say adopted
- **Documents**: `docs/ui-redesign/qt-ribbon-workspaces-2026-09-21/README.md`, `docs/ui-redesign/qt-five-workspaces-2026-09-21/README.md`  
- **Claim**: “设计稿，未修改 C++ 生产界面” / “尚未实现 C++ 界面”  
- **Evidence**: `fa9ba744` on main; `libs/ui_ribbon`; STATUS.md “adopted”; README production UI section.  
- **Problem**: `docs/README.md` points here as **UI design authority**. Readers hit contradictory “not shipped” wording.  
- **Fix**: Add adopted-on-main banner; clarify screenshots are design references (`ACCEPTABLE_REFERENCE`), behaviour rules still authoritative.

#### F-P1-02 — Ribbon plan header still “计划草案” despite STATUS claiming update
- **Document**: `docs/development/ribbon-five-workspaces/00-plan.md`  
- **Claim**: “状态：计划草案（待评审）”  
- **Evidence**: STATUS.md says header was updated; file still says 草案; code landed.  
- **Problem**: Dual source of truth; STATUS itself is inaccurate about the plan header.  
- **Fix**: Retitle plan to “historical implementation plan — adopted on main (see STATUS.md)”.

#### F-P1-03 — CONTEXT.md missing dual-track banner (refresh ledger overclaimed)
- **Document**: `CONTEXT.md` (listed as canonical in `docs/README.md`)  
- **Claim** (in refresh `01-findings.md`): “CONTEXT.md silent about C++ → dual-track banner” as fixed  
- **Evidence**: CONTEXT opens with Python-module vocabulary only (`paleo_workbench/…`); no native/`pwb-platform` banner.  
- **Problem**: Canonical glossary reads as live Python architecture; agents follow Python paths for native work.  
- **Fix**: Add dual-track banner pointing to `docs/architecture/dual-track.md` + module-map; keep glossary as domain/oracle vocabulary.

#### F-P1-04 — Root `FINAL_REPORT.md` presents Python-era system as current truth
- **Document**: `FINAL_REPORT.md` (repo root, highly visible)  
- **Claim**: large “当前系统状态” with pybind counts, Python harness, etc. (2026-08-23)  
- **Evidence**: Native product is `pwb-platform`; report predates ribbon + geo-viz closure.  
- **Problem**: New-user / search landing contradicts native-first README.  
- **Fix**: Banner: historical audit (2026-08); not product authority; see docs/README.md.

#### F-P1-05 — Root `TEST_READY.md` / `TEST_INFRA.md` freeze PySide6 as the stack
- **Documents**: `TEST_READY.md`, `TEST_INFRA.md`  
- **Claim**: UI Framework PySide6 6.11.2 as current test stack narrative  
- **Evidence**: Valid for **legacy Python** pytest; native uses Qt6 6.8 + CTest.  
- **Problem**: Unscoped root docs look like product stack truth.  
- **Fix**: Banner: applies to legacy Python pytest track only; native → README / cpp-building docs.

#### F-P1-06 — Cross-doc ribbon status contradiction (canonical vs design)
- **Documents**: README/PROJECT/STATUS vs ui-redesign READMEs / 00-plan  
- **Claim**: adopted vs not implemented / 草案  
- **Evidence**: as F-P1-01/02  
- **Problem**: Same as above; tracked as the contradiction theme for re-scan.  
- **Fix**: Same banners; docs/README precedence note: STATUS + code > design README status lines.

#### F-P1-07 — Refresh DoD / findings claim CONTEXT banner done (ledger falsehood)
- **Document**: `docs/development/project-documentation-refresh-2026/01-findings.md`  
- **Claim**: CONTEXT dual-track banner fixed  
- **Evidence**: not present  
- **Fix**: Correct findings ledger after real banner lands; note in verification.

#### F-P1-08 — Packaging / M12 honesty OK in refreshed docs, but root Python install still looks “equal” without courage note near top for agents skimming only Legacy section
- **Document**: `README.md`  
- **Claim**: Dual-track table is good; Legacy section is long and actionable  
- **Evidence**: pyproject still default entry — correctly stated under M12  
- **Problem**: Mild: skimmers may still treat Python block as primary if they skip the table. Severity borderline P1/P2 — keep as P1 for new-user “what language?” confusion risk.  
- **Fix**: One-line callout under Legacy header: “Not the recommended product entry; packaging default only until M12.”

### P2

#### F-P2-01 — Workspace label wording drift
- README: “data management → 智能预测 → …” vs code “数据管理 / 1 智能预测 / 2 约束与单因素 / 3 综合编图 / 验证”.  
- **Fix**: Use UI-visible strings from `ribbon_spec.cpp`.

#### F-P2-02 — PROJECT.md F5 invents `closure_mapping` library and vague `factor_*`
- **Fix**: `mapping_kernel`, `factor_fusion`/`factor_host`, app `closure_mapping_install` / `closure_workflow`.

#### F-P2-03 — Module map DoD “covers 63 libs” overstates
- Map is grouped sketch; several libs only appear as group members in prose.  
- **Fix**: State “63 directories; map is grouped, not an exhaustive inventory” + optional full list or `ls libs`.

#### F-P2-04 — Binary path incomplete
- README shows only `build/native-product/apps/paleo_workbench_platform/pwb-platform`; gates also check `bin/` and build root.  
- **Fix**: Note “or `build/native-product/bin/pwb-platform` depending on generator layout”.

#### F-P2-05 — WellPlot / submodule docs assume populated trees
- Submodules not initialized in this worktree; README commands fail without `git submodule update --init --recursive` (already stated once — strengthen near WellPlot).  

#### F-P2-06 — `docs/geomodel-architecture.md` Python-era without historical banner
- Points at `paleo_workbench.viz.geomodel`; native has `libs/geomodel`.  
- **Fix**: Historical / dual-track banner.

#### F-P2-07 — `docs/plugin-runtime-status.md` WellPlot-centric without native note
- **Fix**: Clarify scoped to WellPlot Desktop plugin roadmap; not pwb-platform.

#### F-P2-08 — Screenshot taxonomy not applied in docs/README
- ui-redesign PNGs are design mocks (READMEs already warn). Index should say DESIGN_REFERENCE vs CURRENT product screenshots.  

#### F-P2-09 — Root `findings.md` / `progress.md` / `task_plan.md` / `design-qa.md` scratch ledgers undemarked
- **Fix**: Brief historical/scratch banners or exclude via docs/README stale layer (name them).

#### F-P2-10 — `docs/README.md` lists CONTEXT as canonical without forcing dual-track read
- **Fix**: In Start here / Canonical table, require dual-track.md (or CONTEXT banner) before treating paths as native homes.

#### F-P2-11 — Seismic / well-log depth in root docs is thin
- Not false, but new-user questions on well-seismic-mapping rely on PROJECT F8–F10 without “probe --capabilities” reminder near those rows.  
- **Fix**: One honesty line under feature inventory.

#### F-P2-12 — Older audit Mermaid diagrams (`docs/audit/*`) map Python-era nodes
- Not in primary nav; still discoverable.  
- **Fix**: Mark audit folder historical in docs/README stale layer (already vaguely covered — name `docs/audit/`).

#### F-P2-13 — `cpp-conversion-status.md` hpp wording OK but could clarify `.h` extras
- Optional P3-ish; keep P2 light: no change required if ~895 hpp kept.

#### F-P2-14 — QGIS vendor path prose is vague but not false
- README points at `native/qgis_render_bridge/build/qgis-vendor/output`; cmake uses sibling-main or local.  
- **Fix**: Point to `cmake/PwbQgisSdk.cmake` as SoT for path resolution.

### P3

#### F-P3-01 — CMake skip messages say “Python pages remain the production path”
- Build-time only; confusing if grepped. Prefer not editing CMake in docs-only PR unless necessary — document in dual-track note that those STATUS strings mean “slice skipped”, not product default.

#### F-P3-02 — Ribbon numbering omitted in README short list
- Covered partly by F-P2-01.

#### F-P3-03 — ADR “0051–0068 and earlier” wording in docs/README vs 33 files
- Soften to “see docs/adr/ (33 files at snapshot)”.

#### F-P3-04 — Minor English/Chinese mix in workspace names
- Prefer UI Chinese labels consistently when describing shell.

#### F-P3-05 — `docs/architecture/dual-track.md` is very short
- Adequate pointer; could link CONTEXT banner once added.

#### F-P3-06 — Open #1473 mentioned correctly; remind readers not to treat open-PR features as shipped (already OK — reinforce in PROJECT F7 note).

---

## Themes with no P0/P1 defect found (still monitored)

- Native vs Python dual-track in **refreshed** README/PROJECT/CLAUDE/conversion-status/dual-track — largely honest.
- Preset names and `PWB_BUILD_NATIVE_PRODUCT` — correct.
- CLI flags `--headless-self-check`, `--capabilities` — present.
- Gate script paths — exist.
- Local links among refreshed docs — 0 broken (47 checked).
- IDW/kriging existence in `mapping_kernel` — supports F5 kernel claim (not “complete algorithm catalog”).
- Qgs* usage in `libs/qgis`, `ui_composite`, `ui_map` — supports QGIS map-stack claim.
- `ProjectSession::mapping_stage()` — supports stage-authority claim.
- `.paleo.json` — supports project file claim.
- Marketing adjectives in refreshed canonical docs — none flagged.

## Open PR features reminder
Do **not** document #1473 capabilities as current product. conversion-status already points to re-check — keep that discipline in fixes.
