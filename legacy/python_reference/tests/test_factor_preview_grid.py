from PySide6.QtWidgets import QLabel

from paleo_workbench.project.models import FactorMapTask
from paleo_workbench.ui.pages.factor_preview_grid import FactorPreviewGrid


def _make_tasks():
    return [
        FactorMapTask(
            name="地层厚度图",
            target_horizon="ZJ-2",
            factor_type="地层厚度",
            method="克里金",
            status="complete",
            quality_metrics={"range": "12 — 86 m", "r_squared": 0.91, "grid": "50×50"},
        ),
        FactorMapTask(
            name="砂岩含量图",
            target_horizon="ZJ-2",
            factor_type="砂岩含量",
            method="克里金",
            status="complete",
            quality_metrics={"range": "10 — 70 %", "r_squared": 0.88, "grid": "50×50"},
        ),
        FactorMapTask(
            name="水深图",
            target_horizon="ZJ-2",
            factor_type="水深",
            method="克里金",
            status="pending",
            quality_metrics={"grid": "50×50"},
        ),
    ]


def test_grid_object_name(qtbot):
    grid = FactorPreviewGrid()
    qtbot.addWidget(grid)
    assert grid.objectName() == "FactorPreviewGrid"
    assert grid.header_label.text() == "单因素图集"


def test_grid_header_format(qtbot):
    grid = FactorPreviewGrid()
    qtbot.addWidget(grid)
    grid.update_state(_make_tasks())
    header = grid.header_label.text()
    assert "ZJ-2" in header
    assert "克里金" in header
    assert "网格" in header


def test_grid_filters_completed(qtbot):
    grid = FactorPreviewGrid()
    qtbot.addWidget(grid)
    grid.update_state(_make_tasks())
    cards = grid.grid_container.findChildren(FactorPreviewGrid.FactorPreviewCard)
    assert len(cards) == 2


def test_grid_card_shows_range(qtbot):
    grid = FactorPreviewGrid()
    qtbot.addWidget(grid)
    grid.update_state(_make_tasks())
    cards = grid.grid_container.findChildren(FactorPreviewGrid.FactorPreviewCard)
    ranges = {c.range_label.text() for c in cards}
    assert "12 — 86 m" in ranges
    # rsquared label visible and formatted
    first = cards[0]
    assert "R²" in first.rsquared_label.text()
    assert not first.rsquared_label.isHidden()


def test_grid_card_hides_missing_rsquared(qtbot):
    task = FactorMapTask(
        name="水深图",
        target_horizon="ZJ-2",
        factor_type="水深",
        method="克里金",
        status="complete",
        quality_metrics={"range": "—", "grid": "50×50"},
    )
    card = FactorPreviewGrid.FactorPreviewCard(task)
    qtbot.addWidget(card)
    # #939-5: metrics present without R² (the plan/batch contract) now show
    # an explicit "not computed" label instead of silently hiding the metric.
    assert card.rsquared_label.text() == "R² 本轮未计算"
    assert not card.rsquared_label.isHidden()


def test_grid_default_grid_metric(qtbot):
    """A completed task whose quality_metrics lacks 'grid' defaults to 50×50."""
    tasks = [
        FactorMapTask(
            name="地层厚度图",
            target_horizon="ZJ-2",
            factor_type="地层厚度",
            method="克里金",
            status="complete",
            quality_metrics={"range": "12 — 86 m", "r_squared": 0.91},
        ),
    ]
    grid = FactorPreviewGrid()
    qtbot.addWidget(grid)
    grid.update_state(tasks)
    header = grid.header_label.text()
    assert "50×50" in header


def test_grid_empty_state(qtbot):
    grid = FactorPreviewGrid()
    qtbot.addWidget(grid)
    grid.update_state([])
    cards = grid.grid_container.findChildren(FactorPreviewGrid.FactorPreviewCard)
    assert cards == []
    assert grid.header_label.text() == "单因素图集"
    placeholders = grid.grid_container.findChildren(QLabel)
    texts = [p.text() for p in placeholders]
    assert "暂无已生成的单因素图" in texts
