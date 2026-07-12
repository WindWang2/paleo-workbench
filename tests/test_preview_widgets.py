from paleo_workbench.ui.pages.preview_widgets import RichTextPreviewWidget


def test_rich_text_widget_loads_html(qtbot):
    w = RichTextPreviewWidget()
    qtbot.addWidget(w)
    w.load_html("<h1>Title</h1><p>Body</p>")
    # QTextBrowser exposes its content via toHtml()
    assert "<h1" in w.toHtml().lower() or "title" in w.toHtml().lower()
