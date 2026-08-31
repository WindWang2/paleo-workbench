from paleo_workbench.ui import tokens
from paleo_workbench.ui.sidebar import (
    SIDEBAR_COLLAPSED_WIDTH,
    SIDEBAR_DEFAULT_WIDTH,
    SIDEBAR_MAX_WIDTH,
    SIDEBAR_MIN_WIDTH,
    TextSidebar,
)


def _label_texts(bar):
    return [label.text() for label in bar.findChildren(type(bar.context_label))]


def test_sidebar_page_margin(qtbot):
    bar = TextSidebar()
    qtbot.addWidget(bar)
    m = bar._layout.contentsMargins()
    assert m.left() == tokens.PAGE_MARGIN
    assert m.top() == tokens.PAGE_MARGIN
    assert m.right() == tokens.PAGE_MARGIN
    assert m.bottom() == tokens.PAGE_MARGIN


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


def test_sidebar_generic_context_with_progress(qtbot):
    sb = TextSidebar()
    qtbot.addWidget(sb)
    sb.update_context("制备", progress="步骤 3/6 · 制图数据制备 · 进行中")
    texts = [lbl.text() for lbl in sb._content_labels]
    assert any("步骤 3/6" in t for t in texts)


def test_sidebar_generic_context_with_tips(qtbot):
    sb = TextSidebar()
    qtbot.addWidget(sb)
    sb.update_context("制备", tips="Ctrl+F 搜索 · Delete 移出")
    texts = [lbl.text() for lbl in sb._content_labels]
    assert any("Ctrl+F" in t for t in texts)


def test_sidebar_generic_context_minimal(qtbot):
    sb = TextSidebar()
    qtbot.addWidget(sb)
    sb.update_context("首页")  # no progress/tips
    texts = [lbl.text() for lbl in sb._content_labels]
    assert any("项目总览" in t for t in texts)


def test_sidebar_generic_context_with_selection(qtbot):
    sb = TextSidebar()
    qtbot.addWidget(sb)
    sb.update_context("测井预测", selection="井 W1 · ZJ-2")
    texts = [lbl.text() for lbl in sb._content_labels]
    assert any("井 W1" in t for t in texts)


def test_sidebar_generic_context_all_sections_append_after_page_lines(qtbot):
    """Progress/selection/tips sections append below the existing page lines."""
    sb = TextSidebar()
    qtbot.addWidget(sb)
    sb.update_context(
        "成图审核",
        progress="2/6 规则已执行",
        selection="图件: 古地理图 v1",
        tips="双击问题跳转 · 右键忽略",
    )
    texts = [lbl.text() for lbl in sb._content_labels]
    # Page-line heading still present and first.
    assert texts[0] == "成图审核"
    # Section headings present.
    assert "工作流" in texts
    assert "当前选择" in texts
    assert "快捷操作" in texts
    # Order: page lines, then 工作流, 当前选择, 快捷操作.
    assert texts.index("工作流") < texts.index("当前选择") < texts.index("快捷操作")


def test_sidebar_generic_context_unknown_page(qtbot):
    """An unknown page name still renders its name as a heading."""
    sb = TextSidebar()
    qtbot.addWidget(sb)
    sb.update_context("自定义页面", tips="提示")
    texts = [lbl.text() for lbl in sb._content_labels]
    assert texts[0] == "自定义页面"
    assert any("提示" in t for t in texts)


def test_sidebar_generic_context_omits_absent_sections(qtbot):
    """Absent fields (empty selection/tips) must not add empty headings."""
    sb = TextSidebar()
    qtbot.addWidget(sb)
    sb.update_context("可视化", progress="进行中")
    texts = [lbl.text() for lbl in sb._content_labels]
    assert "工作流" in texts
    assert "当前选择" not in texts
    assert "快捷操作" not in texts


def test_sidebar_update_context_sets_context_label(qtbot):
    sb = TextSidebar()
    qtbot.addWidget(sb)
    sb.update_context("层序格架")
    assert sb.context_label.text() == "层序格架"


def test_sidebar_render_context_backwards_compat(qtbot):
    """_render_context still works as a backward-compat delegate."""
    sb = TextSidebar()
    qtbot.addWidget(sb)
    sb._render_context("可视化")
    texts = [lbl.text() for lbl in sb._content_labels]
    assert any("综合可视化" in t for t in texts)


# --- M7: float button + user-resizable docked width --------------------------


def test_sidebar_float_button_emits_float_requested(qtbot):
    bar = TextSidebar()
    qtbot.addWidget(bar)
    emitted = []
    bar.float_requested.connect(lambda: emitted.append(True))
    assert bar.float_btn.objectName() == "SidebarFloatBtn"
    bar.float_btn.click()
    assert emitted == [True]


def test_sidebar_default_docked_width(qtbot):
    bar = TextSidebar()
    qtbot.addWidget(bar)
    assert bar.user_width() == SIDEBAR_DEFAULT_WIDTH
    assert bar.minimumWidth() == SIDEBAR_DEFAULT_WIDTH
    assert bar.maximumWidth() == SIDEBAR_DEFAULT_WIDTH


def test_sidebar_user_width_clamped_to_bounds(qtbot):
    bar = TextSidebar()
    qtbot.addWidget(bar)
    bar.set_user_width(SIDEBAR_MIN_WIDTH - 100)
    assert bar.user_width() == SIDEBAR_MIN_WIDTH
    bar.set_user_width(SIDEBAR_MAX_WIDTH + 500)
    assert bar.user_width() == SIDEBAR_MAX_WIDTH
    bar.set_user_width(220)
    assert bar.user_width() == 220
    assert bar.minimumWidth() == 220
    assert bar.maximumWidth() == 220


def test_sidebar_collapse_pins_rail_and_expand_restores_user_width(qtbot):
    bar = TextSidebar()
    qtbot.addWidget(bar)
    bar.set_user_width(240)

    bar.toggle_collapse(True)
    assert bar.is_collapsed is True
    assert bar.minimumWidth() == SIDEBAR_COLLAPSED_WIDTH
    assert bar.maximumWidth() == SIDEBAR_COLLAPSED_WIDTH

    bar.toggle_collapse(False)
    assert bar.is_collapsed is False
    assert bar.user_width() == 240
    assert bar.minimumWidth() == 240
    assert bar.maximumWidth() == 240


def test_sidebar_set_user_width_while_collapsed_only_remembers(qtbot):
    bar = TextSidebar()
    qtbot.addWidget(bar)
    bar.toggle_collapse(True)
    bar.set_user_width(250)
    assert bar.user_width() == 250
    assert bar.maximumWidth() == SIDEBAR_COLLAPSED_WIDTH
    bar.toggle_collapse(False)
    assert bar.maximumWidth() == 250


def test_sidebar_set_floated_relaxes_width_bounds(qtbot):
    """The floated top-level window resizes freely; docking restores clamps."""
    bar = TextSidebar()
    qtbot.addWidget(bar)
    bar.set_user_width(200)

    bar.set_floated(True)
    assert bar.maximumWidth() > SIDEBAR_MAX_WIDTH

    bar.set_floated(False)
    assert bar.user_width() == 200
    assert bar.minimumWidth() == 200
    assert bar.maximumWidth() == 200
