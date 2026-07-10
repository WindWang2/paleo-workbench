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
    texts = _label_texts(bar)
    assert any("图件:" in text for text in texts)
    assert any("状态:" in text for text in texts)


def test_sidebar_mapping_context_shows_name_and_dirty(qtbot):
    bar = TextSidebar()
    qtbot.addWidget(bar)
    bar.update_mapping_context(map_name="ZJ2 Map", horizon="ZJ2", dirty=True)
    texts = "\n".join(_label_texts(bar))
    assert bar.context_label.text() == "编图"
    assert "图件: ZJ2 Map" in texts
    assert "层位: ZJ2" in texts
    assert "状态: 未保存" in texts


def test_sidebar_data_context_renders_counts_and_selection_defaults(qtbot):
    bar = TextSidebar()
    qtbot.addWidget(bar)

    bar.update_data_context(resource_count=3, artifact_count=2, selected_name="report.pdf")

    texts = "\n".join(_label_texts(bar))
    assert "资源 3" in texts
    assert "成果 2" in texts
    assert "异常 0" in texts
    assert "report.pdf" in texts
    assert "格式: 未选择" in texts
    assert "阅读器: empty" in texts
    assert "上下文面板 (待实现)" not in texts


def test_sidebar_renders_expanded_data_context(qtbot):
    bar = TextSidebar()
    qtbot.addWidget(bar)

    bar.update_data_context(
        resource_count=3,
        artifact_count=2,
        issue_count=1,
        selected_name="demo.pdf",
        selected_type="document",
        selected_format="pdf",
        reader_mode="pdf",
    )

    text = " ".join(label.text() for label in bar._content_labels)
    assert "资源 3" in text
    assert "成果 2" in text
    assert "异常 1" in text
    assert "当前选择: demo.pdf" in text
    assert "格式: document / pdf" in text
    assert "阅读器: pdf" in text


def test_sidebar_object_name(qtbot):
    bar = TextSidebar()
    qtbot.addWidget(bar)
    assert bar.objectName() == "TextSidebar"
