from PySide6.QtCore import QSize
from paleo_workbench.ui.pages.module_relationship import ModuleRelationshipWidget, ModuleRelationshipCanvas


def test_module_relationship_widget_canvas_resizing(qtbot):
    widget = ModuleRelationshipWidget()
    qtbot.addWidget(widget)
    
    # Verify inner canvas exists and maintains fixed width
    assert isinstance(widget.canvas, ModuleRelationshipCanvas)
    assert widget.canvas.width() == 1180

    # Resize parent container to small and large dimensions
    widget.resize(1200, 800)
    qtbot.wait(50)
    assert widget.canvas.width() == 1180

    widget.resize(1920, 1080)
    qtbot.wait(50)
    # The canvas width must stay fixed at 1180 so grid coordinates never stretch or distort arrow positions
    assert widget.canvas.width() == 1180


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
