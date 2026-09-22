from paleo_workbench.ui.pages.seismic_attribute_panel import SeismicAttributePanel


def test_attribute_panel_groups_all_supported_labels(qtbot):
    panel = SeismicAttributePanel()
    qtbot.addWidget(panel)

    assert panel.objectName() == "SeismicAttributePanel"
    assert [panel.attribute_tree.topLevelItem(i).text(0) for i in range(panel.attribute_tree.topLevelItemCount())] == [
        "振幅属性",
        "频率属性",
        "连续性属性",
        "构造属性",
        "未实现",
    ]
    leaves = [
        panel.attribute_tree.topLevelItem(i).child(j).text(0)
        for i in range(panel.attribute_tree.topLevelItemCount())
        for j in range(panel.attribute_tree.topLevelItem(i).childCount())
    ]
    assert set(leaves) == {
        "包络",
        "瞬时相位",
        "瞬时频率",
        "RMS振幅",
        "甜点",
        "相对阻抗",
        "相干(C3)",
        "Dip_IL",
        "Dip_XL",
        "方位角",
        "平均曲率",
        # Honest placeholders — visible but disabled:
        "高斯曲率",
        "最大曲率",
        "RGB融合",
    }
    # Every enabled leaf maps to a kernel the pipeline really has.
    from paleo_workbench.seismic_attributes import available_kernels

    computable = set(available_kernels())
    from paleo_workbench.ui.pages.seismic_attribute_panel import _LABEL_TO_KERNEL

    for label in leaves:
        kernel = _LABEL_TO_KERNEL.get(label)
        if kernel is not None:
            assert kernel in computable


def test_attribute_panel_emits_leaf_selection_and_syncs_programmatically(qtbot):
    panel = SeismicAttributePanel()
    qtbot.addWidget(panel)
    selected: list[str] = []
    panel.attribute_changed.connect(selected.append)

    panel.set_selected_attribute("包络")

    assert panel.selected_attribute() == "包络"
    item = panel.attribute_tree.topLevelItem(0).child(0)
    panel.attribute_tree.itemClicked.emit(item, 0)
    assert selected == ["包络"]
