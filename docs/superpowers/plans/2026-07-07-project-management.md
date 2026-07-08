# Project Management V1 Implementation Plan

> **Date:** 2026-07-07
> **Spec:** `docs/superpowers/specs/2026-07-07-project-management-design.md`
> **Approach:** SDD — fresh subagent per task, review after each, final whole-branch review.

## Baseline

- Current tests: **259 passing** (after baseline dep fix commit `397993e`).
- Branch: `main` (HEAD `397993e`).
- Spec premise verified: `HeaderToolbar` has 4 buttons (no signals yet), `ProjectManager` has `save`/`load`, `AppShell(project=...)` constructs all pages and exposes `set_project_name` + per-page `update_*` methods, `ProjectDocument`/`ProjectMeta`/`CoordinateReference` carry all fields the properties dialog needs.

## Architecture Decision (per spec)

Window-level controller inside `PaleoWorkbenchWindow` (`app.py`). No separate controller class for V1.

**Page refresh strategy: rebuild the shell.** The spec explicitly endorses this (avoids stale references; DataPage is constructed from `AppShell.project`). On `new`/`open`, replace `self.app_shell` with a fresh `AppShell(project=self.project)`, re-add to layout, and re-run all `update_*` calls + `set_project_name`. A `_refresh_shell()` private helper centralizes this.

## File Layout

```
paleo_workbench/
  app.py                       # PaleoWorkbenchWindow — gains project lifecycle methods
  ui/
    header_toolbar.py          # gains 4 signals
tests/
  test_project_lifecycle.py    # new — all controller behavior tests
  conftest.py                  # may need a tmp_path fixture wrapper (already builtin)
```

No new modules — V1 fits inside `app.py` and `header_toolbar.py`.

## Tasks (TDD — each dispatched to a fresh subagent)

### Task 1: HeaderToolbar signals

**Files:** `paleo_workbench/ui/header_toolbar.py`, `tests/test_header_toolbar.py`

**Changes:**
- Add 4 `Signal()` to `HeaderToolbar`: `new_project_requested`, `open_project_requested`, `save_project_requested`, `properties_requested`.
- Expose the 4 buttons as named attributes (`new_project_btn`, `open_project_btn`, `save_project_btn`, `properties_btn`) instead of an anonymous `self.buttons` list — keep `self.buttons` as a derived list for backward compat with any existing test that reads it (check first; if no test reads `.buttons`, drop it).
- Wire each button's `clicked` to its signal.
- Keep `_BUTTON_SPECS`, objectNames, search box unchanged.

**Tests (~4):**
1. `test_toolbar_emits_new_project_signal`: click new_project_btn → signal caught.
2. `test_toolbar_emits_open_project_signal`.
3. `test_toolbar_emits_save_project_signal`.
4. `test_toolbar_emits_properties_signal`.
(Use `qtbot.waitSignal` or a list-append slot.)

**Verify:** focused + full suite green (259 + 4 = 263).

**Commit:** `feat: expose project action signals from HeaderToolbar`

---

### Task 2: Project state + new/open/save/save-as core

**Files:** `paleo_workbench/app.py`, `tests/test_project_lifecycle.py` (new)

**Changes to `PaleoWorkbenchWindow`:**
- Add `self.project_path: Path | None = None`.
- Add public/testable methods (no dialogs here — Task 3 adds those):
  - `new_project(name: str = "Untitled Project") -> None`: set `self.project = ProjectDocument.new(name)`, `self.project_path = None`, call `self._refresh_shell()`.
  - `open_project_path(path: str | Path) -> None`: try `ProjectManager(path).load()`; on success set `self.project` + `self.project_path = Path(path)` + `_refresh_shell()`; on failure (JSON/ValidationError/IOError) keep current project, re-raise NOTHING — return a bool or set a flag. **Decision: return `bool`** (`True` loaded, `False` failed) so callers/dialogs can react without exceptions.
  - `save_project() -> Path | None`: if `self.project_path` is set, `ProjectManager(self.project_path).save(self.project)` and return it; else call `self.save_project_as(None)`.
  - `save_project_as(path: str | Path | None) -> Path | None`: if `path is None`, return `None` (Task 3 wires the save dialog here); else normalize filename to end in `.paleo.json` (append if missing, do not strip existing), save via ProjectManager, set `self.project_path`, return the path.
- Add private `_refresh_shell() -> None`:
  - Remove old `self.app_shell` widget from layout, mark for deletion (`self.app_shell.setParent(None)` + `self.app_shell.deleteLater()`).
  - Create new `AppShell(project=self.project)`.
  - Re-run `set_project_name` (from `dashboard_state`) + all `update_*` calls (copy the block from `__init__`).
  - Add to the outer layout.
  - **Wiring caveat:** the toolbar signal connections are set up in `__init__`; after rebuild the new shell has a NEW `header_toolbar`. So signal wiring must live in `_refresh_shell` (or a `_wire_toolbar()` helper called by both `__init__` and `_refresh_shell`), not just `__init__`. Connect the 4 toolbar signals to the 4 handler methods (handlers fully wired in Task 6; for Task 2 connect to methods that may not exist yet — so either create stub handlers now or defer connection to Task 6. **Decision: create the handler methods in Task 2 as thin wrappers calling the public methods + dialogs**, but since dialogs (Task 3) aren't built yet, have handlers call `_choose_*` which Task 3 will add — so connect signals in Task 6, not Task 2. Task 2 only adds the state methods + `_refresh_shell` + `_wire_toolbar` helper WITHOUT calling it from `__init__` yet.)

**Refactor `__init__`:** extract the "set_project_name + all update_*" block into `_apply_project_to_shell()` so both `__init__` and `_refresh_shell` call it without duplication. `_refresh_shell` = teardown old shell + new AppShell + `_apply_project_to_shell()`.

**Tests (~6) — call path-based methods directly, no dialogs:**
1. `test_new_project_clears_path`: window with a saved path → `new_project()` → `project_path is None`, title contains "Untitled".
2. `test_new_project_uses_custom_name`: `new_project("X")` → `project.meta.name == "X"`.
3. `test_save_as_writes_file_and_stores_path`: `save_project_as(tmp_path/"p")` → file exists at `p.paleo.json`, `project_path` set, return value matches.
4. `test_save_as_normalizes_extension`: `save_project_as(tmp_path/"p.json")` → file is `p.paleo.json` (not `p.json`); if `p.paleo.json` already passed, no double extension.
5. `test_save_project_uses_existing_path`: set `project_path` manually, `save_project()` → saves there, returns it.
6. `test_save_project_without_path_returns_none`: `project_path=None`, `save_project()` → returns `None` (no dialog in test).
7. `test_open_project_path_loads`: save a project, then on a fresh window `open_project_path(saved)` → loads, `project_path` set, resources visible in data page.
8. `test_open_project_path_invalid_returns_false`: `open_project_path(nonexistent)` → returns `False`, current project unchanged.

**Verify:** focused + full suite green (259 + 6-8 = ~267).

**Commit:** `feat: add project lifecycle methods to PaleoWorkbenchWindow`

---

### Task 3: File dialog helpers + signal wiring

**Files:** `paleo_workbench/app.py`, `tests/test_project_lifecycle.py` (extend)

**Changes:**
- Add private dialog helpers using `QFileDialog`:
  - `_choose_open_project() -> Path | None`: `getOpenFileName` with filter `"Project (*.paleo.json)"`, default dir = `project_path.parent` if set else home. Return `Path` or `None`.
  - `_choose_save_project() -> Path | None`: `getSaveFileName` with same filter, suggested name `f"{project.meta.name}.paleo.json"`. Return `Path` or `None`.
- Add the 4 toolbar handler methods that glue signals → dialogs → core methods:
  - `_on_new_project()`: `new_project()`.
  - `_on_open_project()`: `path = _choose_open_project()`; if path: `ok = open_project_path(path)`; if not ok: `self._show_project_error("打开工程失败", ...)`.
  - `__on_save_project()`: `path = save_project()`; if `path is None`: `path = save_project_as(_choose_save_project())`. (i.e. `save_project` already delegates to save-as-with-dialog when no path — keep handler thin: just `save_project()` if it internally calls `_choose_save_project` when path missing. **Decision:** make `save_project()` itself call `self._choose_save_project()` when `project_path is None` and return the result; then `_on_save_project` is just `self.save_project()`.) Update Task 2's `save_project` accordingly.
  - `_on_properties()`: `self._show_properties()`.
- Wire signals: ensure `_wire_toolbar()` (from Task 2) connects the 4 toolbar signals to these 4 handlers. Call `_wire_toolbar()` from both `__init__` (after shell built) and `_refresh_shell` (after each rebuild).

**Dialog testability:** QFileDialog is hard to test directly. Tests cover the path-based public methods (Task 2) and a wiring test that verifies signals reach the handlers WITHOUT opening real dialogs — use `monkeypatch`/`patch` on the `_choose_*` helpers or the public methods to assert the handler calls them. Do NOT instantiate real QFileDialog in tests.

**Tests (~3):**
1. `test_save_project_uses_dialog_when_no_path`: monkeypatch `_choose_save_project` to return a tmp path; `save_project()` on a window with `project_path=None` → file written, path stored. (Validates the Task 3 amendment to `save_project`.)
2. `test_open_handler_reports_error_on_failure`: monkeypatch `_choose_open_project` to return a bad path; trigger `_on_open_project()`; assert `_show_project_error` called (patch it to record calls) and active project unchanged.
3. `test_toolbar_signals_wired_after_refresh`: rebuild shell via `new_project()`; emit `header_toolbar.new_project_requested` (or call handler) → confirm handler invoked (patch the handler to count).

**Verify:** focused + full suite green.

**Commit:** `feat: add file dialogs and wire toolbar signals to project handlers`

---

### Task 4: Error handling + properties dialog

**Files:** `paleo_workbench/app.py`, `tests/test_project_lifecycle.py` (extend)

**Changes:**
- Add `_show_project_error(title: str, message: str) -> None`: `QMessageBox.critical(self, title, message)`. Used by open/save failure paths.
- Add `project_properties_text() -> str`: returns a multi-line string with:
  - 工程名称: `{project.meta.name}`
  - 区域: `{project.meta.region or "—"}`
  - 工程文件: `{project_path or "未保存"}`
  - 资源数量: `{len(project.resources)}`
  - 导出图件: `{len(project.export_artifacts)}`
  - 显示坐标系: `{project.coordinate.display_crs}`
  - 版本: `{project.meta.version}`
- Add `_show_properties() -> None`: `QMessageBox.information(self, "工程属性", self.project_properties_text())`.

**Error path completeness (already partly in Task 2/3):** confirm `open_project_path` catches `json.JSONDecodeError`, `pydantic.ValidationError`, `OSError`, and returns `False` for all (current project preserved). Save path: `save_project_as`/`save_project` should catch `OSError` on write and call `_show_project_error`, return `None`.

**Tests (~3):**
1. `test_properties_text_contains_fields`: build project with known name/region/resources; assert each field label + value present; assert "未保存" when `project_path is None`.
2. `test_properties_text_shows_path_when_saved`: save; `project_properties_text()` contains the path string.
3. `test_open_handles_corrupt_json`: write a tmp file with invalid JSON; `open_project_path(file)` → returns `False`, active project unchanged.

**Verify:** focused + full suite green (~270).

**Commit:** `feat: add properties dialog and non-destructive error handling`

---

### Task 5: Integration smoke + final wiring

**Files:** `tests/test_project_lifecycle.py` (extend), maybe `app.py` for any missed glue.

**Behavior verified end-to-end (still avoiding real dialogs via monkeypatch):**
1. `test_full_new_open_save_cycle`:
   - window with project A (has 1 resource)
   - `save_project_as(tmp/"a")` → `a.paleo.json` exists
   - `new_project()` → path None, data page empty
   - monkeypatch `_choose_open_project` → return `tmp/"a.paleo.json"`
   - trigger `_on_open_project()` → data page shows the 1 resource again, title updated.
2. `test_window_title_updates_on_project_change`: title contains project name; after `new_project("Z")` contains "Z"; after open contains loaded name.
3. `test_status_bar_updates_on_project_change`: status bar project name matches.

**Verify:** full suite green.

**Commit:** `test: add project lifecycle integration smoke tests`

---

### Task 6: Final whole-branch review + ledger update

**Actions:**
- Whole-branch review (controller logic, dialog testability, signal wiring across rebuilds, error handling completeness, no stale references after shell rebuild).
- Update `task_plan.md` / `progress.md` / `findings.md` with Project Management V1 section + test history (259 → ~272).

**Commit:** `chore: sync SDD progress ledger (Project Management V1 complete)`

## Risks / Notes

- **Signal wiring across shell rebuild** is the trickiest part: each `_refresh_shell` creates a new `HeaderToolbar`, so connections MUST be re-established. Centralize in `_wire_toolbar()` called by both `__init__` and `_refresh_shell`. Forgetting this = silent regression where buttons stop working after new/open. The Task 3 wiring test (`test_toolbar_signals_wired_after_refresh`) guards this.
- **Dialogs untestable directly:** cover via monkeypatch of `_choose_*` and the public path-based methods. Never instantiate `QFileDialog`/`QMessageBox` in tests.
- **`save_project` flow:** final design = `save_project()` returns existing path if set, else calls `_choose_save_project()` and saves. This matches spec ("if no path, show save dialog").
- **Extension normalization:** append `.paleo.json` only if the filename doesn't already end with it. Avoid double-appending (`x.paleo.json.paleo.json`).
- **`AppShell` construction signature** already accepts `project=` — good, no change needed there.
- **`requirements-geoviz.txt`** (just added) is unrelated to this feature but documents how the engine deps are installed; mention in findings.
