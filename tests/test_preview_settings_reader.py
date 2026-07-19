from dataclasses import replace

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QTextEdit, QWidget

import paleo_workbench.ui.pages.data_reader_panel as reader_module
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel
from paleo_workbench.ui.pages.preview_provider import PreviewProvider, PreviewResult
from paleo_workbench.ui.pages.preview_settings import (
    PreviewSettings,
    PreviewSettingsStore,
)
from paleo_workbench.ui.pages.preview_widgets import (
    GeoTiffPreviewWidget,
    ImagePreviewWidget,
    JsonTreePreviewWidget,
    MediaPreviewWidget,
    PdfPreviewWidget,
    RichTextPreviewWidget,
    TablePreviewWidget,
    TextPreviewWidget,
)


def _store(tmp_path, settings=None):
    store = PreviewSettingsStore(
        QSettings(
            str(tmp_path / "reader-settings.ini"),
            QSettings.Format.IniFormat,
        )
    )
    if settings is not None:
        store.save(settings)
    return store


def test_text_rich_text_and_table_widgets_apply_display_settings(qtbot):
    settings = replace(
        PreviewSettings.defaults(),
        font_size=15,
        wrap_text=True,
        auto_fit_columns=False,
    )
    text = TextPreviewWidget()
    rich = RichTextPreviewWidget()
    table = TablePreviewWidget()
    for widget in (text, rich, table):
        qtbot.addWidget(widget)

    text.apply_settings(settings)
    rich.apply_settings(settings)
    table.apply_settings(settings)
    table.load_table(("A", "B"), (("1", "2"),))

    assert text.lineWrapMode() == QTextEdit.LineWrapMode.WidgetWidth
    assert text.font().pointSize() == 15
    assert rich.font().pointSize() == 15
    assert table.font().pointSize() == 15
    assert table.auto_fit_columns is False


def test_image_pdf_json_geotiff_and_media_widgets_apply_settings(qtbot):
    settings = replace(
        PreviewSettings.defaults(),
        smooth_images=False,
        pdf_fit_mode="width",
        pdf_zoom_percent=135,
        json_array_collapse_threshold=25,
        json_expand_depth=4,
        show_geo_metadata=False,
        media_autoplay=True,
        media_volume=35,
    )
    image = ImagePreviewWidget()
    pdf = PdfPreviewWidget()
    json_tree = JsonTreePreviewWidget()
    geotiff = GeoTiffPreviewWidget()
    media = MediaPreviewWidget()
    for widget in (image, pdf, json_tree, geotiff, media):
        qtbot.addWidget(widget)

    image.apply_settings(settings)
    pdf.apply_settings(settings)
    json_tree.apply_settings(settings)
    geotiff.apply_settings(settings)
    media.apply_settings(settings)

    assert image.transformation_mode == Qt.TransformationMode.FastTransformation
    assert pdf.fit_mode == "width"
    assert pdf.zoom_percent == 135
    assert json_tree.array_collapse_threshold == 25
    assert json_tree.expand_depth == 4
    assert geotiff.summary_table.isHidden() is True
    assert media.autoplay is True
    assert media.volume_slider.value() == 35


def test_reader_panel_loads_settings_without_embedded_editor_and_applies_external_changes(
    qtbot, tmp_path
):
    initial = replace(
        PreviewSettings.defaults(),
        font_size=14,
        wrap_text=True,
        show_metadata=False,
    )
    panel = DataReaderPanel(
        provider=PreviewProvider(),
        settings_store=_store(tmp_path, initial),
    )
    qtbot.addWidget(panel)
    emitted: list[PreviewSettings] = []
    panel.preview_settings_changed.connect(emitted.append)

    assert panel.preview_settings == initial
    assert not hasattr(panel, "settings_panel")
    assert not hasattr(panel, "settings_button")

    panel.render(PreviewResult(mode="text", title="notes", text="hello"))
    assert panel.meta_label.isHidden() is True
    assert panel.text_preview.lineWrapMode() == QTextEdit.LineWrapMode.WidgetWidth

    updated = replace(initial, font_size=17)
    panel.set_preview_settings(updated)

    assert emitted[-1].font_size == 17
    assert panel.preview_settings.font_size == 17
    assert panel.text_preview.font().pointSize() == 17


def test_lazy_web_preview_applies_persisted_settings_before_first_load(
    qtbot, tmp_path, monkeypatch
):
    initial = replace(PreviewSettings.defaults(), font_size=18)
    events: list[tuple[str, object]] = []

    class FakeWebDocumentWidget(QWidget):
        def apply_settings(self, settings):
            events.append(("settings", settings))

        def load_document(self, path, html=""):
            events.append(("load", (path, html)))

    monkeypatch.setattr(
        reader_module,
        "WebDocumentPreviewWidget",
        FakeWebDocumentWidget,
    )
    panel = DataReaderPanel(
        provider=PreviewProvider(),
        settings_store=_store(tmp_path, initial),
    )
    qtbot.addWidget(panel)

    panel.render(
        PreviewResult(
            mode="web_document",
            title="page.html",
            path="/tmp/page.html",
            rich_html="<h1>Preview</h1>",
        )
    )

    assert events == [
        ("settings", initial),
        ("load", ("/tmp/page.html", "<h1>Preview</h1>")),
    ]
