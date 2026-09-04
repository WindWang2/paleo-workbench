"""B9: workstation 测井 dock 后端解析（诚实 engine / legacy 降级）。

The docked well panel used to be hardcoded to ``set_backend("legacy")``,
which kept the native WellLogEngine unreachable in the workstation main
flow.  These tests pin the replacement contract:

* binding imports (and the env default is on) → dock resolves to ``engine``;
* env opt-out or manual switch → dock is ``legacy`` and the status bar /
  note explains the fallback instead of disguising it;
* a simulated ``try_import_welllog`` failure auto-falls back to ``legacy``
  without raising and without pretending the engine is in use;
* the selection linkage signals of ``open_well`` / depth cursor keep
  working.

Offscreen CI cannot create the heavy dock views (``ensure_views`` bails on
the offscreen/minimal platform gate), so these tests drive exactly the
public pieces the dock creation path runs: a panel injected into
:class:`LinkedInterpretationWorkspace` followed by
``apply_default_well_backend()`` — the call ``_configure_compact_panels``
makes on view creation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal

from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.domain import WellEntity
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.well_log_canvas_panel import WellLogCanvasPanel
from paleo_workbench.ui.workstation.linked_workspace import (
    LinkedInterpretationWorkspace,
)
from paleo_workbench.viz import welllog_engine_adapter as engine_adapter


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    project.wells.append(
        WellEntity(name="A12", surface_x=1.0, surface_y=2.0, project_x=1.0, project_y=2.0)
    )
    project.resources.append(
        ResourceItem(name="A12.Las", path="wells/A12.Las", type="well_log", format="las")
    )
    return project


def _binding_available() -> bool:
    return engine_adapter.try_import_welllog()[1] is not None


class _RecordingPanel(QObject):
    """Duck-typed WellLogCanvasPanel stand-in with a real depth signal."""

    depth_cursor_moved = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        self.backend_name = "engine"
        self.backend_calls: list[str] = []
        self.shown: list[object] = []
        self.shutdown_calls = 0

    def backend(self) -> str:
        return self.backend_name

    def set_backend(self, name: str) -> None:
        self.backend_calls.append(name)
        self.backend_name = "engine" if name == "engine" else "legacy"

    def show_resource(self, resource, project, prediction_task=None) -> None:
        self.shown.append(resource)

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def _dock_with_recording_panel(qtbot, tmp_path: Path) -> LinkedInterpretationWorkspace:
    lw = LinkedInterpretationWorkspace(_project(tmp_path))
    qtbot.addWidget(lw)
    lw.well_panel = _RecordingPanel()
    lw._views_created = True
    return lw


def _dock_with_real_panel(qtbot, tmp_path: Path) -> LinkedInterpretationWorkspace:
    """Workspace + real panel, wired the way ensure_views does (offscreen-safe)."""
    lw = LinkedInterpretationWorkspace(_project(tmp_path))
    qtbot.addWidget(lw)
    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)
    lw.well_panel = panel
    lw._views_created = True
    panel.depth_cursor_moved.connect(lw._on_depth_cursor)
    return lw


# --- adapter helper ----------------------------------------------------------


def test_resolve_default_backend_reports_honest_legacy_reasons(monkeypatch):
    original = engine_adapter.try_import_welllog
    monkeypatch.delenv("PALEO_USE_WELLLOG_ENGINE", raising=False)

    # Simulated binding failure must degrade to legacy with a stated cause.
    monkeypatch.setattr(engine_adapter, "try_import_welllog", lambda: (None, None, None))
    assert engine_adapter.resolve_default_backend() == (
        "legacy",
        "welllog 绑定不可用，自动回退 Legacy (QPainter)",
    )

    # An explicit env opt-out is a user choice, not a silent degradation —
    # but the legacy resolution still names why.
    monkeypatch.setattr(engine_adapter, "try_import_welllog", original)
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "0")
    backend, reason = engine_adapter.resolve_default_backend()
    assert backend == "legacy"
    assert "PALEO_USE_WELLLOG_ENGINE" in reason


def test_resolve_default_backend_prefers_engine_with_binding(monkeypatch):
    if not _binding_available():
        pytest.skip("built WellLogEngine binding is not on PYTHONPATH")
    monkeypatch.delenv("PALEO_USE_WELLLOG_ENGINE", raising=False)
    assert engine_adapter.resolve_default_backend() == ("engine", None)


# --- dock resolution ---------------------------------------------------------


def test_dock_resolves_to_engine_and_renders_native_when_binding_available(
    qtbot, tmp_path, monkeypatch
):
    if not _binding_available():
        pytest.skip("built WellLogEngine binding is not on PYTHONPATH")
    monkeypatch.delenv("PALEO_USE_WELLLOG_ENGINE", raising=False)
    lw = _dock_with_real_panel(qtbot, tmp_path)
    panel = lw.well_panel
    statuses: list[str] = []
    lw.status_changed.connect(statuses.append)

    lw.apply_default_well_backend()

    assert lw.well_backend() == "engine"
    assert panel.backend() == "engine"
    assert panel.is_native_backend() is True
    assert lw.well_backend_note() is None
    assert statuses == [], "engine 生效时不得谎报回退"

    # End to end: the dock's engine path really hands data to the native view.
    project = _project(tmp_path)
    task = MockPredictionAdapter().run(project, [], seed=1)
    panel.update_state(task)
    assert panel.engine_load_report() is not None
    assert panel.is_canvas_ready()
    assert panel.stack.currentWidget() is panel.engine_host

    panel.shutdown()
    assert panel.engine_load_report() is None
    lw.shutdown_workers()


def test_dock_resolution_follows_binding_availability(qtbot, tmp_path, monkeypatch):
    lw = _dock_with_recording_panel(qtbot, tmp_path)
    panel = lw.well_panel
    monkeypatch.delenv("PALEO_USE_WELLLOG_ENGINE", raising=False)
    statuses: list[str] = []
    lw.status_changed.connect(statuses.append)

    lw.apply_default_well_backend()

    if _binding_available():
        assert panel.backend_calls == ["engine"]
        assert lw.well_backend() == "engine"
        assert lw.well_backend_note() is None
        assert statuses == []
    else:
        assert panel.backend_calls == ["legacy"]
        assert lw.well_backend() == "legacy"
        assert lw.well_backend_note()
        assert any("Legacy" in message for message in statuses)


def test_dock_env_forced_legacy_is_announced(qtbot, tmp_path, monkeypatch):
    if not _binding_available():
        pytest.skip("built WellLogEngine binding is not on PYTHONPATH")
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "0")
    lw = _dock_with_real_panel(qtbot, tmp_path)
    panel = lw.well_panel
    statuses: list[str] = []
    lw.status_changed.connect(statuses.append)

    lw.apply_default_well_backend()

    assert lw.well_backend() == "legacy"
    assert panel.backend() == "legacy"
    assert panel.is_native_backend() is False
    note = lw.well_backend_note()
    assert note and "PALEO_USE_WELLLOG_ENGINE" in note, "回退原因必须可追溯"
    assert any("Legacy" in message and "PALEO_USE_WELLLOG_ENGINE" in message for message in statuses)
    lw.shutdown_workers()


def test_dock_import_failure_falls_back_to_legacy_honestly(qtbot, tmp_path, monkeypatch):
    monkeypatch.delenv("PALEO_USE_WELLLOG_ENGINE", raising=False)

    def _broken_import():
        return None, None, None

    monkeypatch.setattr(engine_adapter, "try_import_welllog", _broken_import)
    lw = LinkedInterpretationWorkspace(_project(tmp_path))
    qtbot.addWidget(lw)
    # Created *after* the patch so the panel's own probe sees the same failure.
    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)
    lw.well_panel = panel
    statuses: list[str] = []
    lw.status_changed.connect(statuses.append)

    lw.apply_default_well_backend()  # must not raise

    assert lw.well_backend() == "legacy"
    assert panel.backend() == "legacy"
    note = lw.well_backend_note()
    assert note, "import 失败必须留下诚实回退原因"
    assert "welllog" in note
    assert ("回退" in note) or ("Legacy" in note)
    assert any("Legacy" in message for message in statuses), "状态条必须注明回退"
    # 不伪装：面板回到可用状态（空态待数据），而不是假装 engine 在跑。
    assert panel.stack.currentWidget() is panel.empty_label
    assert panel.is_native_backend() is False
    panel.shutdown()
    lw.shutdown_workers()


def test_manual_backend_switch_still_available(qtbot, tmp_path, monkeypatch):
    if not _binding_available():
        pytest.skip("built WellLogEngine binding is not on PYTHONPATH")
    monkeypatch.delenv("PALEO_USE_WELLLOG_ENGINE", raising=False)
    lw = _dock_with_real_panel(qtbot, tmp_path)
    panel = lw.well_panel
    lw.apply_default_well_backend()
    assert lw.well_backend() == "engine"

    # Manual dock-level switch (API preserved) — legacy, explained.
    lw.set_well_backend("legacy")
    assert lw.well_backend() == "legacy"
    assert panel.backend() == "legacy"
    assert lw.well_backend_note() == "已切换到 Legacy (QPainter)"

    lw.set_well_backend("engine")
    assert lw.well_backend() == "engine"
    assert lw.well_backend_note() is None

    # Panel-level manual API is equally intact.
    panel.set_backend("legacy")
    assert lw.well_backend() == "legacy"
    panel.shutdown()
    lw.shutdown_workers()


# --- selection / linkage regressions -----------------------------------------


def test_open_well_selection_linkage_signals_unchanged(qtbot, tmp_path, monkeypatch):
    monkeypatch.delenv("PALEO_USE_WELLLOG_ENGINE", raising=False)
    lw = _dock_with_recording_panel(qtbot, tmp_path)
    panel = lw.well_panel
    panel.depth_cursor_moved.connect(lw._on_depth_cursor)

    selected: list[object] = []
    focused: list[str] = []
    statuses: list[str] = []
    lw.object_selected.connect(selected.append)
    lw.well_focused.connect(focused.append)
    lw.status_changed.connect(statuses.append)

    lw.open_well("A12")

    assert panel.shown, "open_well 必须把井资源交给面板"
    assert len(selected) == 1
    assert selected[0]["kind"] == "well"
    assert selected[0]["well_name"] == "A12"
    assert focused == ["A12"]
    assert statuses[-1] == "已打开井 A12"

    # Depth cursor linkage gate (scenario C) still honours the linked flag.
    lw.set_linked(False)
    statuses.clear()
    panel.depth_cursor_moved.emit(1234.5)
    assert statuses == []
    lw.set_linked(True)
    assert lw.is_linked() is True
    panel.depth_cursor_moved.emit(1234.5)
    assert statuses == ["联动深度 1,234.5 m"]

    lw.show_all_wells()
    assert statuses[-1] == "已显示全部工区井位"
    lw.shutdown_workers()
