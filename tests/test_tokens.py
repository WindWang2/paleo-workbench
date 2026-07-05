from paleo_workbench.ui import tokens


def test_color_constants_exist():
    assert tokens.PRIMARY == "#1f6fe0"
    assert tokens.ACCENT == "#6f47cf"
    assert tokens.SUCCESS == "#1f9d57"
    assert tokens.TEAL == "#0f93a4"
    assert tokens.BG_BODY == "#eef0f4"
    assert tokens.BG_HEADER == "#f3f5f9"
    assert tokens.BG_SIDEBAR == "#ffffff"
    assert tokens.BG_SEARCH == "#eef2f7"
    assert tokens.BG_RAIL == "#1b3a6b"
    assert tokens.TEXT_PRIMARY == "#28323f"
    assert tokens.TEXT_SECONDARY == "#7e8794"
    assert tokens.BORDER == "#e2e6ec"
    assert tokens.BORDER_STRONG == "#dde2e9"


def test_dimension_constants_exist():
    assert tokens.MENU_BAR_HEIGHT == 36
    assert tokens.HEADER_TOOLBAR_HEIGHT == 38
    assert tokens.ICON_RAIL_WIDTH == 60
    assert tokens.TEXT_SIDEBAR_WIDTH == 248
    assert tokens.STATUS_BAR_HEIGHT == 24
    assert tokens.ICON_RAIL_ITEM_SIZE == 46


def test_font_constants_exist():
    assert "PingFang SC" in tokens.FONT_FAMILY
    assert tokens.FONT_SIZE_BASE == "12.5px"
    assert tokens.FONT_SIZE_STATUS == "11px"


def test_qss_template_is_nonempty_string():
    assert isinstance(tokens.QSS_TEMPLATE, str)
    assert len(tokens.QSS_TEMPLATE) > 100
    assert "#MenuBar" in tokens.QSS_TEMPLATE
    assert "#IconRail" in tokens.QSS_TEMPLATE
    assert "#1f6fe0" in tokens.QSS_TEMPLATE


def test_page_names_constant():
    assert tokens.PAGE_NAMES == [
        "首页", "数据", "测井预测", "地震预测", "层序格架",
        "可视化", "制备", "编图", "成图审核",
    ]
    assert len(tokens.PAGE_NAMES) == 9


def test_step_colors_exist():
    assert tokens.STEP_COLORS == [
        "#1f6fe0", "#0f93a4", "#6f47cf", "#c47e12", "#e2705b", "#7e8794",
    ]
    assert len(tokens.STEP_COLORS) == 6


def test_step_labels_exist():
    assert tokens.STEP_LABELS == [
        "数据管理", "数据转换", "制图数据制备",
        "沉积相预测", "古地理图编制", "质控与导出",
    ]
    assert len(tokens.STEP_LABELS) == 6


def test_status_text_mapping():
    assert tokens.STATUS_TEXT["complete"] == "完成"
    assert tokens.STATUS_TEXT["running"] == "进行中"
    assert tokens.STATUS_TEXT["pending"] == "待开始"
    assert tokens.STATUS_TEXT["warning"] == "警告"
    assert tokens.STATUS_TEXT["failed"] == "失败"
    assert tokens.STATUS_TEXT["ready"] == "就绪"
    assert tokens.STATUS_TEXT["skipped"] == "已跳过"
    assert tokens.STATUS_TEXT["mock"] == "Mock"


def test_error_red_token():
    assert tokens.ERROR_RED == "#dc2626"


def test_resource_labels_exist():
    assert tokens.RESOURCE_LABELS["well_log"] == "测井数据"
    assert tokens.RESOURCE_LABELS["seismic"] == "地震数据"
    assert tokens.RESOURCE_LABELS["horizon"] == "层位数据"


def test_resource_units_exist():
    assert tokens.RESOURCE_UNITS["well_log"] == "井"
    assert tokens.RESOURCE_UNITS["seismic"] == "条测线"
    assert tokens.RESOURCE_UNITS["horizon"] == "层位"
