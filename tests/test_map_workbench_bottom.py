from paleo_workbench.ui.pages.map_workbench_bottom import MapWorkbenchBottom


def test_bottom_workbench_has_attribute_topology_and_factor_tabs(qtbot):
    bottom = MapWorkbenchBottom()
    qtbot.addWidget(bottom)
    assert [bottom.tabText(index) for index in range(bottom.count())] == ["属性", "拓扑问题", "单因素参考图"]
    bottom.set_collapsed(True)
    assert bottom.isHidden()
    bottom.set_collapsed(False)
    assert not bottom.isHidden()
