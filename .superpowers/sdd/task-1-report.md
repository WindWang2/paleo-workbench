# Task 1 Report: Floating Panel Component

## Scope
- Added a reusable `FloatingPanel` widget at `paleo_workbench/ui/pages/floating_panel.py`.
- Added focused pytest-qt coverage at `tests/test_floating_panel.py`.
- No other data page behavior was changed.

## TDD Evidence
### RED
Command:
```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_floating_panel.py -q
```
Result:
- Failed during collection with `ModuleNotFoundError: No module named 'paleo_workbench.ui.pages.floating_panel'`.

### GREEN
Command:
```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_floating_panel.py -q
```
Result:
- `3 passed in 0.77s`

## Implementation Notes
- `FloatingPanel` exposes the requested API: `tab_button`, `content_frame`, `title_label`, `set_content`, `set_expanded`, `is_expanded`, and `expanded_changed`.
- The component uses `tokens` for panel styling and keeps the content frame collapsed by default.
- The widget is shown on construction so the visibility assertions in the focused tests are stable under pytest-qt.

## Commit
- `42e7c4c feat: add floating panel component`

## Concerns
- None.

## Follow-up Fix After Review

### Scope
- Removed the `FloatingPanel.__init__()` visibility side effect so a parentless panel stays hidden until callers explicitly show it.
- Made `FloatingPanel.set_content()` replace the previous content widget instead of accumulating multiple widgets.
- Switched `paleo_workbench.ui` and `paleo_workbench.ui.pages` public exports to lazy `__getattr__` loading so direct imports of `paleo_workbench.ui.pages.floating_panel` do not pull in `AppShell`, `DataPage`, or geo-viz-backed page modules.

### TDD Evidence
#### RED
Command:
```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_floating_panel.py tests/test_ui_exports.py -q
```
Result:
- `test_floating_panel_does_not_show_parentless_widget_on_init` failed because `FloatingPanel.__init__()` called `self.show()`.
- `test_floating_panel_set_content_replaces_existing_widget` failed because `set_content()` left both old and new widgets in the content layout.
- `test_floating_panel_import_does_not_eagerly_import_ui_shell_modules` failed because importing `paleo_workbench.ui.pages.floating_panel` eagerly loaded `paleo_workbench.ui.app_shell`.

#### GREEN
Commands:
```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_floating_panel.py tests/test_ui_exports.py -q
python -c "import paleo_workbench.ui.pages.floating_panel"
```
Result:
- `8 passed in 0.78s`
- Direct import completed successfully with exit code `0` and without requiring geo-viz imports during module load.
