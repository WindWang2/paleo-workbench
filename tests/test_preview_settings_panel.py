from dataclasses import replace

import pytest
from PySide6.QtCore import QSettings

from paleo_workbench.ui.pages.preview_settings import (
    PreviewSettings,
    PreviewSettingsStore,
)
from paleo_workbench.ui.pages.preview_settings_panel import PreviewSettingsPanel


def _store(tmp_path):
    return PreviewSettingsStore(
        QSettings(
            str(tmp_path / "preview-panel.ini"),
            QSettings.Format.IniFormat,
        )
    )


def test_preview_settings_panel_applies_and_persists_controls(qtbot, tmp_path):
    store = _store(tmp_path)
    panel = PreviewSettingsPanel(store=store)
    qtbot.addWidget(panel)
    emitted: list[PreviewSettings] = []
    panel.settings_applied.connect(emitted.append)

    panel.font_size_spin.setValue(16)
    panel.wrap_text_check.setChecked(True)
    panel.table_rows_spin.setValue(350)
    panel.media_volume_spin.setValue(45)
    panel.apply_btn.click()

    assert emitted[-1].font_size == 16
    assert emitted[-1].wrap_text is True
    assert emitted[-1].table_max_rows == 350
    assert emitted[-1].media_volume == 45
    assert store.load() == emitted[-1]


def test_preview_settings_panel_round_trips_every_setting(qtbot, tmp_path):
    panel = PreviewSettingsPanel(store=_store(tmp_path))
    qtbot.addWidget(panel)
    custom = replace(
        PreviewSettings.defaults(),
        font_size=14,
        show_metadata=False,
        text_limit_kib=512,
        wrap_text=True,
        table_max_rows=500,
        table_max_columns=60,
        auto_fit_columns=False,
        smooth_images=False,
        geotiff_thumbnail_px=512,
        show_geo_metadata=False,
        pdf_fit_mode="width",
        pdf_zoom_percent=125,
        json_limit_mib=12,
        json_array_collapse_threshold=250,
        json_expand_depth=4,
        media_autoplay=True,
        media_volume=30,
        geoviz_max_curves=20,
        geoviz_max_depth_samples=4_000,
        geoviz_max_slice_axis=1_024,
        geoviz_max_points=120_000,
        geoviz_surface_grid_size=384,
    )

    panel.set_settings(custom)

    assert panel.settings() == custom


def test_preview_settings_panel_reset_emits_and_persists_recommended_defaults(
    qtbot,
    tmp_path,
):
    store = _store(tmp_path)
    store.save(replace(PreviewSettings.defaults(), font_size=18))
    panel = PreviewSettingsPanel(store=store)
    qtbot.addWidget(panel)
    emitted: list[PreviewSettings] = []
    panel.settings_applied.connect(emitted.append)

    panel.reset_btn.click()

    assert emitted == [PreviewSettings.defaults()]
    assert panel.settings() == PreviewSettings.defaults()
    assert store.load() == PreviewSettings.defaults()


@pytest.mark.parametrize(
    ("mode", "category"),
    [
        ("empty", "general"),
        ("text", "text"),
        ("rich_text", "text"),
        ("web_document", "text"),
        ("table", "table"),
        ("well_log", "table"),
        ("seismic", "table"),
        ("image", "image"),
        ("geotiff", "image"),
        ("pdf", "pdf"),
        ("json_tree", "json"),
        ("media", "media"),
        ("geoviz", "geoviz"),
    ],
)
def test_preview_settings_panel_selects_category_for_current_mode(
    qtbot,
    tmp_path,
    mode,
    category,
):
    panel = PreviewSettingsPanel(store=_store(tmp_path))
    qtbot.addWidget(panel)

    panel.set_preview_mode(mode)

    assert panel.category_combo.currentData() == category
