from paleo_workbench.ui.pages.seismic_attribute_panel import SeismicAttributePanel


def test_attribute_panel_groups_all_supported_labels(qtbot):
    panel = SeismicAttributePanel()
    qtbot.addWidget(panel)

    assert panel.objectName() == "SeismicAttributePanel"
    assert [panel.attribute_tree.topLevelItem(i).text(0) for i in range(panel.attribute_tree.topLevelItemCount())] == [
        "振幅属性",
        "频率属性",
        "连续性属性",
        "结构属性",
        "多属性融合",
    ]
    leaves = [
        panel.attribute_tree.topLevelItem(i).child(j).text(0)
        for i in range(panel.attribute_tree.topLevelItemCount())
        for j in range(panel.attribute_tree.topLevelItem(i).childCount())
    ]
    assert set(leaves) == {
        "振幅",
        "包络",
        "瞬时相位",
        "瞬时频率",
        "RMS振幅",
        "甜点",
        "相对阻抗",
        "Dip_IL",
        "Dip_XL",
        "方位角",
        "平均曲率",
        "高斯曲率",
        "最大曲率",
        "RGB融合",
    }


def test_attribute_panel_emits_leaf_selection_and_syncs_programmatically(qtbot):
    panel = SeismicAttributePanel()
    qtbot.addWidget(panel)
    selected: list[str] = []
    panel.attribute_changed.connect(selected.append)

    panel.set_selected_attribute("包络")

    assert panel.selected_attribute() == "包络"
    item = panel.attribute_tree.topLevelItem(0).child(0)
    panel.attribute_tree.itemClicked.emit(item, 0)
    assert selected == ["振幅"]
