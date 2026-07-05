# ReviewExportPage Implementation Plan

> **Date:** 2026-07-05
> **Spec:** `docs/superpowers/specs/2026-07-05-reviewexportpage-design.md`
> **Approach:** SDD — fresh subagent per task, review after each, final whole-branch review.

## Baseline

- Current tests: 119 passing.
- Branch: `main` (at `32dbd81`).
- Files: `paleo_workbench/ui/pages/`, `tests/`, `paleo_workbench/ui/tokens.py`, `paleo_workbench/ui/app_shell.py`, `paleo_workbench/app.py`.

## Tasks (TDD — each dispatched to a fresh subagent)

### Task 1: Tokens — `WARNING`, `QC_RESULT_*`, `DEFAULT_QC_RULES`, `RULE_DESCRIPTIONS`

**Files:** `paleo_workbench/ui/tokens.py`, `tests/test_tokens.py`

**Changes:** add the new token constants verbatim from the spec's Design Tokens section. Note `WARNING = "#c47e12"` is a new standalone constant (currently only embedded as STEP_COLORS[3]).

**Tests (~3) in `tests/test_tokens.py`:**
- `test_warning_token`: `tokens.WARNING == "#c47e12"`.
- `test_qc_result_colors`: 3 mappings, pass→SUCCESS, warning→WARNING, error→ERROR_RED.
- `test_qc_result_labels`: pass→"✓通过", warning→"!警告", error→"!待处理".
- `test_default_qc_rules`: list has 6 entries, contains "层级一致性" and "字段与输出格式完整性".
- `test_rule_descriptions`: contains keys "层级一致性" and "facies_polygons_present".

**Verify:** `pytest tests/test_tokens.py -q`; full suite still 119.

**Commit:** `feat: add QC result/rule tokens for ReviewExportPage`

---

### Task 2: ActionHeader — `action_header.py`

**Files:** `paleo_workbench/ui/pages/action_header.py`, `tests/test_action_header.py`

**Behavior:**
- `ActionHeader(QFrame)`, objectName "ActionHeader".
- Style: QFrame, bg BG_SIDEBAR, border 1px BORDER, radius RADIUS_CARD, padding 12px.
- `self.title_label` (QLabel, default "成图与审核 · — 古地理图（自动质检 + 人工审核）", TEXT_PRIMARY 13px bold).
- Button row QHBoxLayout: `self.run_btn` (运行检查, objectName "PrimaryButton"), `self.config_btn` (规则配置, objectName "SecondaryButton"), `self.export_btn` (导出检查报告, objectName "PrimaryButton").
- `self.rules_label` (QLabel, default `f"检查规则: {' · '.join(DEFAULT_QC_RULES)}"`, TEXT_SECONDARY 11px).
- `update_state(reports, map_documents)`:
  - If reports: find first report's linked_map_document_id in map_documents; if found, horizon = doc.linked_target_horizon; else horizon = "—". Title = `f"成图与审核 · {horizon} 古地理图（自动质检 + 人工审核）"`.
  - Rules chips: if reports and reports[0].rules → " · ".join(those); else " · ".join(DEFAULT_QC_RULES).

**Tests (~4):**
1. `test_header_object_name`: objectName == "ActionHeader".
2. `test_header_has_three_buttons`: run_btn/config_btn/export_btn exist with correct objectNames.
3. `test_header_update_title_horizon`: build QualityReport + PaleoMapDocument, update_state → title contains horizon.
4. `test_header_empty_state`: update_state([], []) → title contains "—".
5. `test_header_rules_chips`: update with report having custom rules → rules_label contains those rules.

**Verify:** focused + full suite green.

**Commit:** `feat: add ActionHeader widget for QC review actions`

---

### Task 3: QCIssueTable — `qc_issue_table.py`

**Files:** `paleo_workbench/ui/pages/qc_issue_table.py`, `tests/test_qc_issue_table.py`

**Behavior:**
- `QCIssueTable(QWidget)`, objectName "QCIssueTable".
- Mirrors `resource_table.py` pattern: QTableWidget wrapper, alternating rows, header bg, border, radius.
- Columns: 检查项目 (rule, 160px), 检查说明 (description, stretch), 结果说明 (result, 160px). Row height 28px.
- `update_state(reports)`:
  - Use first report (or empty if none). Populate rows from report.rules.
  - For each rule: 检查项目 = rule; 检查说明 = RULE_DESCRIPTIONS.get(rule, rule); 结果说明 derived: scan report.issues for issue["rule"] == rule. If found → severity = issue.get("severity","warning"); text = `f"{QC_RESULT_LABELS[severity]} {issue.get('message','')}"`. If not found → "✓通过".
  - Result cell (col 2) foreground: pass→SUCCESS, warning→WARNING, error→ERROR_RED. Use `setForeground(QColor(...))` like resource_table.
  - Empty state (no reports): 0 rows.

**Tests (~5):**
1. `test_table_object_name`.
2. `test_table_three_columns`: columnCount == 3, headers correct.
3. `test_table_pass_result`: report with rule "X" and no issues → that row's result cell text "✓通过", foreground SUCCESS.
4. `test_table_warning_result`: report with rule "X" and issue {rule:"X", severity:"warning", message:"1处"} → result text contains "!警告" and "1处", foreground WARNING.
5. `test_table_error_result`: similar with severity "error" → "!待处理", foreground ERROR_RED.
6. `test_table_empty_state`: update_state([]) → rowCount 0.

Fixture: `QualityReport(linked_map_document_id="m1", rules=["层级一致性","未分类区域"], issues=[{"rule":"未分类区域","severity":"warning","message":"1处未分类"}])`.

**Verify:** focused + full suite green.

**Commit:** `feat: add QCIssueTable widget for QC rule results`

---

### Task 4: ResultSummary — `result_summary.py`

**Files:** `paleo_workbench/ui/pages/result_summary.py`, `tests/test_result_summary.py`

**Behavior:**
- `ResultSummary(QFrame)`, objectName "ResultSummary".
- Style: bg BG_SIDEBAR, border 1px BORDER, radius RADIUS_CARD, padding 12px, fixed width 240px.
- Title label "检查结果输出".
- Three count labels: `self.pass_label` (`f"通过项: {n}"`, color SUCCESS), `self.warning_label` (`f"警告项: {n}"`, WARNING), `self.error_label` (`f"待处理项: {n}"`, ERROR_RED).
- `self.advisory_label`: if error count > 0 → "建议先处理待处理项后再输出成果" (ERROR_RED); else "全部通过，可输出成果" (SUCCESS).
- Divider (QFrame horizontal line, bg BORDER).
- Export section title "导出图件".
- `self.export_container` (QWidget with QVBoxLayout) holding one QLabel per artifact: `f"• {artifact.format} — {artifact.output_path}"`. Empty → single QLabel "暂无导出图件".
- `update_state(reports, artifacts)`:
  - Counts from first report: pass = len(rules) - (warning issues + error issues counted once per rule); warning = count of distinct rules with a warning issue; error = count of distinct rules with an error issue. (Simplest correct: for each rule, if a warning issue exists → warning++; elif error issue → error++; else pass++.)
  - Rebuild export list.

**Tests (~4):**
1. `test_summary_object_name`.
2. `test_summary_counts`: report with 3 rules, 1 warning issue, 1 error issue → pass=1, warning=1, error=1.
3. `test_summary_advisory_with_errors`: error count > 0 → advisory contains "待处理项".
4. `test_summary_advisory_all_pass`: report with rules but no issues → advisory "全部通过，可输出成果".
5. `test_summary_export_list`: 2 artifacts → 2 export labels with format + path.
6. `test_summary_empty_export`: artifacts=[] → "暂无导出图件".

**Verify:** focused + full suite green.

**Commit:** `feat: add ResultSummary widget for QC counts and export list`

---

### Task 5: ReviewExportPage assembly — `review_export_page.py`

**Files:** `paleo_workbench/ui/pages/review_export_page.py`, `tests/test_review_export_page.py`

**Behavior:**
- `ReviewExportPage(QWidget)`, objectName "ReviewExportPage".
- Outer QVBoxLayout (16px margins, 16px spacing): ActionHeader (stretch 0) + content QHBoxLayout (QCIssueTable stretch 1, ResultSummary stretch 0).
- `update_state(reports, map_documents, artifacts)`: delegates to action_header.update_state(reports, map_documents), qc_table.update_state(reports), result_summary.update_state(reports, artifacts).

**Tests (~2):**
1. `test_page_assembles_three_widgets`: has action_header, qc_table, result_summary of correct types; objectName "ReviewExportPage".
2. `test_page_update_delegates`: spy on sub-widgets' update_state; verify all called with correct args.

**Verify:** focused + full suite green.

**Commit:** `feat: assemble ReviewExportPage from action/table/summary widgets`

---

### Task 6: Integration — AppShell idx 8, exports, app.py wiring

**Files:** `paleo_workbench/ui/app_shell.py`, `paleo_workbench/ui/pages/__init__.py`, `paleo_workbench/app.py`, `tests/test_review_export_integration.py`

**Changes:**
- `pages/__init__.py`: export ReviewExportPage.
- `app_shell.py`:
  - Import ReviewExportPage.
  - Update page construction — replace the trailing `for name in tokens.PAGE_NAMES[7:]` loop with:
    ```python
    for name in tokens.PAGE_NAMES[7:8]:            # 7 = 编图
        self.page_stack.addWidget(PagePlaceholder(name))
    self.page_stack.addWidget(ReviewExportPage())   # 8 = 成图审核
    ```
  - Add `update_review_export_page(self, reports, map_documents, artifacts)` delegating to widget 8's `update_state`.
- `app.py`: after `update_preparation_page`, add `self.app_shell.update_review_export_page(self.project.quality_reports, self.project.paleomap_documents, self.project.export_artifacts)`.

**Tests (~2):**
1. `test_app_shell_page_eight_is_review_export_page`: `page_stack.widget(8)` is ReviewExportPage.
2. `test_review_export_page_receives_data`: build project with a QualityReport (via run_basic_qc on a PaleoMapDocument) and an ExportArtifact (via record_export); construct PaleoWorkbenchWindow; verify page 8 qc_table has rows.

**Verify:** `pytest -q` full suite (~137) green.

**Commit:** `feat: wire ReviewExportPage into AppShell at page index 8`

---

### Task 7: Final review + ledger update

**Actions:**
- Whole-branch review: read all new files, verify spec conformance, unused imports, dead code, token usage.
- Run full test suite, confirm count.
- Update `task_plan.md`: Phase 5 → ✅ COMPLETE, page matrix row 9, test history.
- Update `progress.md`: add Phase 5 section.
- Update `findings.md`: append ReviewExportPage notes.

**Commit:** `chore: sync SDD progress ledger (ReviewExportPage complete)`

## Risk / Notes

- `run_basic_qc` produces issues with rule keys like "facies_polygons_present" (not the Chinese display names). RULE_DESCRIPTIONS maps both Chinese prototype rules AND these engine keys, so the table description column works for either. The QCIssueTable test should use whichever rule keys the report actually carries.
- Severity mapping: engine uses "warning"/"error"; prototype shows 通过/警告/待处理. Per spec: warning→警告, error→待处理 (treat error as 待处理/needs-action). This is a deliberate display choice; the advisory text "待处理项" reinforces it.
- Counts in ResultSummary count distinct rules (one result per rule), matching the prototype's "通过项 5 / 警告项 2 / 待处理项 1" semantics.
- IMPORTANT for Task 6 implementer: stay on `main` branch — do NOT create a feature branch (matches established project convention; previous phases committed directly to main).
