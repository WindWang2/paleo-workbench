from paleo_workbench.ui.sidebar import TextSidebar


def _label_texts(bar):
    return [label.text() for label in bar.findChildren(type(bar.context_label))]


def test_sidebar_default_context_label(qtbot):
    bar = TextSidebar()
    qtbot.addWidget(bar)
    assert bar.context_label.text() == "首页"


def test_sidebar_set_context_updates_label(qtbot):
    bar = TextSidebar()
    qtbot.addWidget(bar)
    bar.set_context("编图")
    assert bar.context_label.text() == "编图"
    assert "上下文面板 (待实现)" not in _label_texts(bar)
    assert any("当前图件" in text for text in _label_texts(bar))


def test_sidebar_data_context_renders_counts_and_reader_capabilities(qtbot):
    bar = TextSidebar()
    qtbot.addWidget(bar)

    bar.update_data_context(resource_count=3, artifact_count=2, selected_name="report.pdf")

    texts = "\n".join(_label_texts(bar))
    assert "资源 3" in texts
    assert "成果 2" in texts
    assert "report.pdf" in texts
    assert "PDF 翻页阅读" in texts
    assert "图片 / 文本 / 表格" in texts
    assert "上下文面板 (待实现)" not in texts


def test_sidebar_object_name(qtbot):
    bar = TextSidebar()
    qtbot.addWidget(bar)
    assert bar.objectName() == "TextSidebar"
