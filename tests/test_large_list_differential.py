"""Large-project UI scalability contracts (V6 Phase 5).

Structural assertions only — item/widget creation counts and object-identity
stability, never wall-clock timings:

- 地层对比 well list: differential update via a stable key→item map
  (unchanged refresh ⇒ zero item creation; changed set ⇒ only the delta,
  selection/check state/scroll preserved).
- 测井预测 / 可视化 source combos: refill gated on the underlying
  id-list signature; ``Path.is_file()`` probes cached per source revision.
- 捕捉设置 dialog: bounded widget construction for 1000 layers (no
  5-widgets-per-row explosion), per-layer write contract unchanged.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QComboBox, QListWidgetItem, QWidget

from paleo_workbench.project.models import ProjectDocument, ResourceItem

_PLACEHOLDER_PREDICTION = "数据管理中暂无 LAS / XML 测井数据"


def _well_resources(count: int, start: int = 0) -> list[ResourceItem]:
    return [
        ResourceItem(
            id=f"res-{start + i:05d}",
            name=f"W{start + i:05d}.las",
            path=f"/wells/w{start + i:05d}.las",
            type="well_log",
            format="las",
        )
        for i in range(count)
    ]


# --- P1 stratigraphy well list: keyed differential update -------------------


def _make_strat_page(qtbot, monkeypatch, resources):
    import paleo_workbench.ui.pages.stratigraphy_correlation_page as mod

    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "0")
    page = mod.StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    project = ProjectDocument.new("UI")
    project.resources.extend(resources)
    page.set_project(project)
    return mod, page, project


def test_well_list_unchanged_update_creates_zero_items(qtbot, monkeypatch):
    """A state refresh with the same wells must not rebuild the list."""
    mod, page, project = _make_strat_page(qtbot, monkeypatch, _well_resources(200))
    page.update_state(project)
    assert page.well_list.count() == 200
    original = [page.well_list.item(i) for i in range(page.well_list.count())]

    # User interaction state that must survive a no-op refresh untouched.
    page.well_list.item(5).setCheckState(Qt.CheckState.Checked)
    page.well_list.setCurrentRow(100)
    scroll = page.well_list.verticalScrollBar().value()

    class SpyItem(QListWidgetItem):
        created = 0

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            SpyItem.created += 1

    monkeypatch.setattr(mod, "QListWidgetItem", SpyItem)
    page.update_state(project)

    assert SpyItem.created == 0, "unchanged wells must reuse existing items"
    assert page.well_list.count() == 200
    for i in range(200):
        assert page.well_list.item(i) is original[i], "item identity must be stable"
    assert page.well_list.currentRow() == 100
    assert page.well_list.item(5).checkState() == Qt.CheckState.Checked
    assert page.well_list.verticalScrollBar().value() == scroll


def test_well_list_delta_update_creates_only_new_items(qtbot, monkeypatch):
    """Add/remove/rename ⇒ only added wells get new items; state survives."""
    mod, page, project = _make_strat_page(qtbot, monkeypatch, _well_resources(6))
    page.update_state(project)
    assert page.well_list.count() == 6

    page.well_list.item(2).setCheckState(Qt.CheckState.Checked)
    page.well_list.item(3).setCheckState(Qt.CheckState.Checked)
    item_r4 = page.well_list.item(4)  # res-00004 row
    page.well_list.setCurrentItem(item_r4)

    # Next generation: rename r0 (same id), drop r5, add two new wells.
    project.resources[0].name = "A-renamed.las"
    project.resources = [r for r in project.resources if r.id != "res-00005"]
    project.resources.extend(_well_resources(1, start=6))
    project.resources.extend(_well_resources(1, start=1000))

    class SpyItem(QListWidgetItem):
        created = 0

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            SpyItem.created += 1

    monkeypatch.setattr(mod, "QListWidgetItem", SpyItem)
    page.update_state(project)

    # Only the two added wells create items; everything else is reused.
    assert SpyItem.created == 2
    assert page.well_list.count() == 7
    ids = [
        page.well_list.item(i).data(Qt.ItemDataRole.UserRole)
        for i in range(page.well_list.count())
    ]
    assert "res-00005" not in ids
    assert set(ids) == {
        "res-00000",
        "res-00001",
        "res-00002",
        "res-00003",
        "res-00004",
        "res-00006",
        "res-01000",
    }
    # list_well_log_resources sorts by (name, id): renamed well comes first.
    assert ids[0] == "res-00000"
    assert page.well_list.item(0).text() == "A-renamed.las"
    # Selection / check state ride on the surviving item objects.
    assert page.well_list.currentItem() is item_r4
    checked = {
        page.well_list.item(i).data(Qt.ItemDataRole.UserRole)
        for i in range(page.well_list.count())
        if page.well_list.item(i).checkState() == Qt.CheckState.Checked
    }
    assert checked == {"res-00002", "res-00003"}


# --- P1 source combos: signature-gated refill -------------------------------


def test_prediction_combo_refill_gated_by_signature(qtbot, monkeypatch):
    import paleo_workbench.ui.pages.well_log_prediction_page as mod

    calls = {"add": 0}

    class SpyCombo(QComboBox):
        def addItem(self, *args, **kwargs):  # noqa: N802 (Qt API)
            calls["add"] += 1
            super().addItem(*args, **kwargs)

    monkeypatch.setattr(mod, "QComboBox", SpyCombo)
    page = mod.WellLogPredictionPage()
    qtbot.addWidget(page)

    def _update_and_count(*args, **kwargs) -> int:
        before = calls["add"]
        page.update_state(*args, **kwargs)
        return calls["add"] - before

    project = ProjectDocument.new("P")
    project.resources.extend(_well_resources(30))
    assert _update_and_count([], project=project) == 30
    assert page.well_source_combo.count() == 30

    # Same id list ⇒ no refill at all.
    assert _update_and_count([], project=project) == 0
    assert page.well_source_combo.count() == 30

    # One new source ⇒ exactly one full refill with the new signature.
    project.resources.append(_well_resources(1, start=99)[0])
    assert _update_and_count([], project=project) == 31
    assert page.well_source_combo.count() == 31

    # Empty project ⇒ placeholder refill (once), then stable.
    empty = ProjectDocument.new("empty")
    assert _update_and_count([], project=empty) == 1
    assert page.well_source_combo.itemText(0) == _PLACEHOLDER_PREDICTION
    assert _update_and_count([], project=empty) == 0


def test_visualization_combo_refill_and_file_probes_gated(qtbot, monkeypatch):
    import paleo_workbench.ui.pages.visualization_page as mod

    calls = {"add": 0, "is_file": 0}
    real_path = mod.Path

    class SpyPath:
        def __init__(self, path):
            self._real = real_path(path)

        def is_file(self):
            calls["is_file"] += 1
            return self._real.is_file()

    class SpyCombo(QComboBox):
        def addItem(self, *args, **kwargs):  # noqa: N802 (Qt API)
            calls["add"] += 1
            super().addItem(*args, **kwargs)

    monkeypatch.setattr(mod, "Path", SpyPath)
    monkeypatch.setattr(mod, "QComboBox", SpyCombo)
    page = mod.VisualizationPage()
    qtbot.addWidget(page)

    def _update_and_snapshot(*args, **kwargs) -> tuple[int, int]:
        before = (calls["add"], calls["is_file"])
        page.update_state(*args, **kwargs)
        return (calls["add"] - before[0], calls["is_file"] - before[1])

    resources = [
        ResourceItem(
            id="viz-1",
            name="L1.las",
            path="/nonexistent/L1.las",
            type="well_log",
            format="las",
        ),
        ResourceItem(
            id="viz-2",
            name="L2.las",
            path="/nonexistent/L2.las",
            type="well_log",
            format="las",
        ),
    ]
    added, probed = _update_and_snapshot(resources, [], [], project=None)
    assert added == 2
    assert probed == 2  # each well_log probed once for auto-open

    # Unchanged source list ⇒ neither refill nor filesystem stats.
    added, probed = _update_and_snapshot(resources, [], [], project=None)
    assert added == 0
    assert probed == 0
    assert page.asset_combo.count() == 2

    # New source revision ⇒ refill and fresh probes.
    resources2 = resources + [
        ResourceItem(
            id="viz-3",
            name="L3.las",
            path="/nonexistent/L3.las",
            type="well_log",
            format="las",
        )
    ]
    added, probed = _update_and_snapshot(resources2, [], [], project=None)
    assert added == 3
    assert probed == 3
    assert page.asset_combo.count() == 3


# --- P1 snapping dialog: bounded widget construction ------------------------


class _FakeEditController(QObject):
    """Duck-typed CompositeEditController: only what the dialog touches."""

    state_changed = Signal()

    def __init__(self, layer_count: int):
        super().__init__()
        from paleo_workbench.mapping.map_interaction import SnappingService

        self.snapping = SnappingService()
        self.snapping.enabled = True
        self._layers = {
            f"layer-{i:04d}": SimpleNamespace(name=f"图层 {i:04d}")
            for i in range(layer_count)
        }

    def layer_ids(self) -> tuple[str, ...]:
        return tuple(self._layers)

    def layer(self, layer_id: str):
        return self._layers.get(layer_id)

    def kind_of(self, layer_id: str) -> str:
        return "line"

    def set_snapping(self, enabled: bool) -> None:
        self.snapping.enabled = enabled


def test_snapping_dialog_bounded_widgets_for_1000_layers(qtbot):
    """1000 layers must not materialize 5 cell widgets per row.

    The per-layer table stays fully configured (every layer writable through
    ``_layer_rows`` and flushed to the service on accept) while the dialog's
    widget count stays bounded by its chrome, not by layer count.
    """
    from paleo_workbench.ui.workstation.composite_panels import (
        SnappingSettingsDialog,
    )

    controller = _FakeEditController(1000)
    dialog = SnappingSettingsDialog(controller, well_points=[(1.0, 1.0)])
    qtbot.addWidget(dialog)

    assert dialog._table.rowCount() == 1000
    assert len(dialog._layer_rows) == 1000

    widget_count = len(dialog.findChildren(QWidget))
    assert widget_count <= 50, (
        f"snapping dialog built {widget_count} widgets for 1000 layers; "
        "per-layer rows must not be widget-per-cell"
    )

    # Per-layer write contract is unchanged (same surface as
    # test_snapping_settings_dialog_writes_service).
    row = dialog._layer_rows["layer-0007"]
    row["enabled"].setChecked(True)
    row["vertex"].setChecked(True)
    row["segment"].setChecked(False)
    row["tolerance"].setValue(3.0)
    row["priority"].setValue(2)
    dialog._well_snap.setChecked(True)
    dialog.accept()

    snapping = controller.snapping
    assert snapping.enabled is True
    assert snapping.layer_enabled["layer-0007"] is True
    assert snapping.layer_tolerance["layer-0007"] == pytest.approx(3.0)
    assert snapping.layer_priority["layer-0007"] == 2
    assert "vertex" in snapping.layer_modes["layer-0007"]
    assert "segment" not in snapping.layer_modes["layer-0007"]
    assert "reference" in snapping.modes
    assert (1.0, 1.0) in snapping.reference_points
