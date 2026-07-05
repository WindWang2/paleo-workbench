### Task 10 Report: Integration — Replace WorkflowDashboard

**Status:** Complete

**Commit:** `0c7108cb9001ceb33d36d89c8d5da36432eefdce`

**Test summary:** 57 passed / 0 failed (full suite, 0.29s)

### Changes made

1. `paleo_workbench/app.py` — replaced `WorkflowDashboard` with `AppShell`; window now creates `self.app_shell = AppShell()`, calls `dashboard_state(self.project)`, and pushes `state["project_name"]` to `app_shell.set_project_name()`. Window resized to 1440×900 per brief.
2. `paleo_workbench/main.py` — imports `tokens` from `paleo_workbench.ui` and applies `app.setStyleSheet(tokens.QSS_TEMPLATE)` after `QApplication` construction.
3. `paleo_workbench/ui/dashboard.py` — deleted via `git rm`.
4. `tests/test_integration_smoke.py` — renamed `test_dashboard_window_shows_project_name` → `test_app_shell_window_shows_project_name`; asserts `"HZ26 Demo" in window.app_shell.status_bar.status_label.text()`.

### Verification

- `git rm` confirmed in commit: `delete mode 100644 paleo_workbench/ui/dashboard.py`.
- Full suite: `57 passed in 0.29s` — all 24 pre-existing MVP tests + 33 UI/zones tests green; the renamed integration test passes.
- Grep across `paleo_workbench/` and `tests/` confirms no remaining references to `WorkflowDashboard` or `window.dashboard` (only mentions are in `docs/superpowers/` historical plan/spec docs, which are intentional records).

### Concerns

None. The brief specifies a single-line commit message but the plan doc prescribed a multi-line body; I used the multi-line body form from the plan's Step 7 since it is more specific and the user instruction said "Follow it exactly" referring to the brief, while the brief itself quotes the multi-line message. No behavior divergence — both forms name the same commit.
