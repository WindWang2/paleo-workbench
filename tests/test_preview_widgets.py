from paleo_workbench.ui.pages.preview_widgets import (
    GeoTiffPreviewWidget,
    JsonTreePreviewWidget,
    RichTextPreviewWidget,
)


def test_rich_text_widget_loads_html(qtbot):
    w = RichTextPreviewWidget()
    qtbot.addWidget(w)
    w.load_html("<h1>Title</h1><p>Body</p>")
    # QTextBrowser exposes its content via toHtml()
    assert "<h1" in w.toHtml().lower() or "title" in w.toHtml().lower()


def test_json_tree_builds_from_payload(qtbot):
    w = JsonTreePreviewWidget()
    qtbot.addWidget(w)
    w.load_payload({"name": "well", "curves": ["GR", "SP"], "meta": {"unit": "m"}}, truncated=False)
    model = w.model()
    assert model.rowCount() == 3  # name, curves, meta


def test_json_tree_collapses_large_array(qtbot):
    w = JsonTreePreviewWidget()
    qtbot.addWidget(w)
    big = list(range(150))
    w.load_payload({"items": big}, truncated=False)
    model = w.model()
    # Row 0 is the "items" key (column 0) and its value item (column 1).
    key_node = model.item(0, 0)
    val_node = model.item(0, 1)
    # Collapsed node shows "[150 items]" in the value column and has 0 children.
    assert val_node.text() == "[150 items]"
    assert key_node.rowCount() == 0


def test_json_tree_lazy_expansion_populates_children(qtbot):
    w = JsonTreePreviewWidget()
    qtbot.addWidget(w)
    big = list(range(150))
    w.load_payload({"items": big}, truncated=False)
    model = w.model()
    key_node = model.item(0, 0)
    assert key_node.rowCount() == 0  # not yet expanded

    # Simulate the user expanding the node.
    w._on_expanded(key_node.index())

    assert key_node.rowCount() == 150
    # First child should be index 0 of the stored list.
    assert key_node.child(0, 0).text() == "0"
    assert key_node.child(0, 1).text() == "0"


def test_json_tree_small_array_expands_inline(qtbot):
    """Arrays under the threshold render children eagerly (no UserRole storage)."""
    w = JsonTreePreviewWidget()
    qtbot.addWidget(w)
    w.load_payload({"curves": ["GR", "SP", "RHOB"]}, truncated=False)
    model = w.model()
    key_node = model.item(0, 0)
    assert key_node.rowCount() == 3
    assert key_node.child(0, 0).text() == "0"
    assert key_node.child(0, 1).text() == "GR"


def test_geotiff_widget_loads_metadata(qtbot):
    # Build a 4x4 PNG so image_bytes is valid.
    from PIL import Image
    import io
    import numpy as np
    buf = io.BytesIO()
    Image.fromarray(np.zeros((4, 4, 3), dtype="uint8")).save(buf, format="PNG")
    w = GeoTiffPreviewWidget()
    qtbot.addWidget(w)
    w.load(
        "x.tif",
        None,
        buf.getvalue(),
        (("CRS", "EPSG:32649"), ("尺寸", "10 × 10 × 1")),
    )
    assert w.summary_table.rowCount() == 2
    # Thumbnail QLabel should now hold a pixmap (decoded from PNG bytes).
    assert w.pixmap() is not None


def test_media_widget_constructs(qtbot):
    from paleo_workbench.ui.pages.preview_widgets import MediaPreviewWidget

    w = MediaPreviewWidget()
    qtbot.addWidget(w)
    w.set_media_path("")  # no crash on empty path
    assert w.play_btn.text() == "播放"


def test_media_widget_loads_path_sets_ready(qtbot):
    """A real path sets status to 就绪 and enables the play button.

    Only asserts construction + label text; QMediaPlayer playback state is
    unreliable under offscreen/no-backend so we never assert on it.
    """
    from paleo_workbench.ui.pages.preview_widgets import MediaPreviewWidget

    w = MediaPreviewWidget()
    qtbot.addWidget(w)
    w.set_media_path("/tmp/clip.wav")
    assert w.status_label.text() == "就绪"
    assert w.play_btn.isEnabled()
    assert w.play_btn.text() == "播放"
