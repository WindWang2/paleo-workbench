from paleo_workbench.ui.pages.module_relationship import (
    ModuleRelationshipCanvas,
    ModuleRelationshipWidget,
)


def test_module_relationship_widget_canvas_resizing(qtbot):
    widget = ModuleRelationshipWidget()
    qtbot.addWidget(widget)

    # DS V5：画布为最小宽度约束的可伸展布局（滚动容器负责超宽），
    # 箭头锚点每 paint 读实时 geometry，不再钉死 1180px。
    assert isinstance(widget.canvas, ModuleRelationshipCanvas)
    assert widget.canvas.minimumWidth() == ModuleRelationshipCanvas.MIN_CANVAS_WIDTH

    widget.resize(1200, 800)
    widget.show()
    qtbot.wait(50)
    assert widget.canvas.width() >= ModuleRelationshipCanvas.MIN_CANVAS_WIDTH

    widget.resize(1920, 1080)
    qtbot.wait(50)
    assert widget.canvas.width() >= ModuleRelationshipCanvas.MIN_CANVAS_WIDTH

    # 箭头锚点依赖实时 geometry：渲染一帧验证 paint 路径不抛异常
    pix = widget.grab()
    assert not pix.isNull()


def test_module_relationship_card_properties(qtbot):
    widget = ModuleRelationshipWidget()
    qtbot.addWidget(widget)

    # Verify card accessor properties exposed on ModuleRelationshipWidget
    assert widget.card_sequence is widget.canvas.card_sequence
    assert widget.card_well is widget.canvas.card_well
    assert widget.card_seismic is widget.canvas.card_seismic
    assert widget.card_facies is widget.canvas.card_facies
    assert widget.card_mapping is widget.canvas.card_mapping
    assert widget.card_data is widget.canvas.card_data
