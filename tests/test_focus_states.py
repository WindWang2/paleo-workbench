"""Focus-ring regression tests — verify buttons that should receive QSS focus rules carry the right objectName."""
from paleo_workbench.ui.pages.preview_widgets import PdfPreviewWidget, MediaPreviewWidget


def test_pdf_preview_buttons_use_secondary_button_objectname(qtbot):
    w = PdfPreviewWidget()
    qtbot.addWidget(w)
    assert w.prev_btn.objectName() == "SecondaryButton"
    assert w.next_btn.objectName() == "SecondaryButton"


def test_media_preview_play_button_uses_secondary_button_objectname(qtbot):
    w = MediaPreviewWidget()
    qtbot.addWidget(w)
    assert w.play_btn.objectName() == "SecondaryButton"


def test_qss_template_has_focus_rules():
    from paleo_workbench.ui import tokens
    assert ":focus" in tokens.QSS_TEMPLATE
    assert tokens.FOCUS_RING in tokens.QSS_TEMPLATE
