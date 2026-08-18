"""T-SEIS-01: seismic facies workflow controls → SeismicView + run/send."""

from __future__ import annotations

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.seismic_prediction_page import SeismicPredictionPage


def test_workbench_controls_emit_mode_attribute_and_auto_tie(qtbot):
    from paleo_workbench.ui.pages.seismic_attribute_panel import SeismicAttributePanel
    from paleo_workbench.ui.pages.seismic_control_panel import SeismicControlPanel

    panel = SeismicControlPanel()
    attributes = SeismicAttributePanel()
    qtbot.addWidget(panel)
    qtbot.addWidget(attributes)
    modes: list[str] = []
    attrs: list[str] = []
    ties: list[bool] = []
    panel.display_mode_changed.connect(modes.append)
    attributes.attribute_changed.connect(attrs.append)
    panel.well_tie_toggled.connect(ties.append)

    panel.mode_combo.setCurrentText("wiggle")
    attributes.attribute_tree.itemClicked.emit(
        attributes.attribute_tree.topLevelItem(0).child(1), 0
    )
    panel.well_tie_btn.setChecked(True)

    assert modes[-1] == "wiggle"
    assert attrs[-1] == "包络"
    assert ties[-1] is True


def test_view_panel_bridges_mode_and_attribute(qtbot):
    from paleo_workbench.ui.pages.seismic_view_panel import SeismicViewPanel
    import numpy as np

    panel = SeismicViewPanel()
    qtbot.addWidget(panel)
    volume = np.zeros((4, 5, 6), dtype=np.float32)
    panel._show_volume(volume)

    panel.set_display_mode("wiggle")
    assert panel.display_mode() == "wiggle"

    # Attribute combo may or may not include all labels depending on engine version
    ok = panel.set_attribute_label("包络") or panel.set_attribute_label("振幅")
    assert ok is True
    assert panel.attribute_label()


def test_page_run_creates_task_and_updates_view(qtbot, tmp_path):
    from paleo_workbench.catalog import (
        CoreCatalogAdapter,
        DataCatalogService,
        reset_catalog,
        set_catalog,
    )
    from paleo_workbench.prediction.providers import ensure_default_models

    project = ProjectDocument.new("Run")
    project.stratigraphy.target_horizon = "H9"
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_path)
    set_catalog(CoreCatalogAdapter(service))
    ensure_default_models(service)
    try:
        page = SeismicPredictionPage()
        qtbot.addWidget(page)
        page.set_project(project)
        page.update_state([], project=project)

        # Production path needs a registered production model; the demo path is
        # the explicit, honestly-marked run available out of the box.
        with qtbot.waitSignal(page.prediction_updated, timeout=5000):
            page.context_toolbar.demo_btn.click()

        assert len(project.prediction_tasks) == 1
        assert page.view_panel.volume_shape == (8, 10, 12)
        assert page.control_panel.horizon_value.text() == "H9"
        assert "H9" in page.context_toolbar.task_value.text()
    finally:
        reset_catalog()
        service.close()
