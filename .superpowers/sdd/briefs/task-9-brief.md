### Task 9: Workflow Dashboard Widget

**Files:**
- Create: `paleo_workbench/ui/dashboard.py`
- Modify: `paleo_workbench/app.py`
- Modify: `paleo_workbench/main.py`
- Create: `tests/test_integration_smoke.py`

**Interfaces:**
- Consumes: `dashboard_state(project) -> dict[str, object]`
- Produces: `WorkflowDashboard(QWidget)`
- Produces: `PaleoWorkbenchWindow(QWidget)`

- [ ] **Step 1: Write failing dashboard smoke test**

Create `tests/test_integration_smoke.py`:

```python
from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.project.models import ProjectDocument


def test_dashboard_window_shows_project_name(qtbot):
    project = ProjectDocument.new(name="HZ26 Demo")
    window = PaleoWorkbenchWindow(project)
    qtbot.addWidget(window)

    assert "HZ26 Demo" in window.windowTitle()
    assert window.dashboard.project_name_label.text() == "HZ26 Demo"
```

- [ ] **Step 2: Run dashboard test to verify it fails**

Run:

```bash
python -m pytest tests/test_integration_smoke.py::test_dashboard_window_shows_project_name -v
```

Expected: FAIL with missing `paleo_workbench.app`.

- [ ] **Step 3: Implement dashboard widget**

Create `paleo_workbench/ui/dashboard.py`:

```python
from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class WorkflowDashboard(QWidget):
    def __init__(self, state: dict[str, object], parent=None):
        super().__init__(parent)
        self.project_name_label = QLabel(str(state.get("project_name", "")))
        self.target_label = QLabel(f"目标层位: {state.get('active_target_horizon') or '未设置'}")
        self.status_label = QLabel(f"流程状态: {state.get('workflow_status', 'draft')}")
        self.summary = QLabel(
            f"资源 {sum(state.get('resource_counts', {}).values())} · "
            f"单因素图 {state.get('factor_map_count', 0)} · "
            f"预测 {state.get('prediction_count', 0)} · "
            f"QC问题 {state.get('qc_issue_count', 0)} · "
            f"导出 {state.get('export_count', 0)}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        title_card = QFrame()
        title_card.setStyleSheet("QFrame { background: #ffffff; border: 1px solid #d8dee6; border-radius: 12px; }")
        card_layout = QVBoxLayout(title_card)
        for widget in [self.project_name_label, self.target_label, self.status_label, self.summary]:
            card_layout.addWidget(widget)
        layout.addWidget(title_card)
        layout.addStretch()
```

- [ ] **Step 4: Implement main window**

Create `paleo_workbench/app.py`:

```python
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.dashboard import WorkflowDashboard
from paleo_workbench.workflow.service import dashboard_state


class PaleoWorkbenchWindow(QWidget):
    def __init__(self, project: ProjectDocument | None = None):
        super().__init__()
        self.project = project or ProjectDocument.new("Untitled Project")
        self.setWindowTitle(f"{self.project.meta.name} - Paleogeography Workbench")
        self.resize(1280, 820)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.dashboard = WorkflowDashboard(dashboard_state(self.project))
        layout.addWidget(self.dashboard)
```

Modify `paleo_workbench/main.py`:

```python
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from paleo_workbench.app import PaleoWorkbenchWindow


def main() -> int:
    app = QApplication(sys.argv)
    window = PaleoWorkbenchWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run dashboard smoke test**

Run:

```bash
python -m pytest tests/test_integration_smoke.py::test_dashboard_window_shows_project_name -v
```

Expected: PASS.

- [ ] **Step 6: Checkpoint or commit**

If root git is repaired, run:

```bash
git add paleo_workbench/app.py paleo_workbench/main.py paleo_workbench/ui/dashboard.py tests/test_integration_smoke.py
git commit -m "feat: add workflow dashboard shell"
```

If root git is still invalid, record checkpoint: `Task 9 complete; root commit pending repository repair`.

---

