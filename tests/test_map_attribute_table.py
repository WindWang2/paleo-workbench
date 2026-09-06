from PySide6.QtWidgets import QLabel

from paleo_workbench.ui.pages.map_attribute_table import MapAttributeTable


def test_attribute_table_dock_title_object_name(qtbot):
    w = MapAttributeTable()
    qtbot.addWidget(w)
    titles = [c for c in w.findChildren(QLabel) if c.objectName() == "MapDockTitle"]
    assert len(titles) >= 1
    assert titles[0].text() == "属性"
    assert w.objectName() == "MapAttributeTable"
    assert w.table.objectName() == "MapAttributeTableWidget"


def test_attribute_table_empty_and_set_feature(qtbot):
    table = MapAttributeTable()
    qtbot.addWidget(table)

    table.set_feature(None)
    assert table.table.rowCount() == 0

    table.set_feature(
        {
            "id": "f1",
            "kind": "facies",
            "name": "三角洲",
            "coordinates": [[0, 0], [1, 0], [1, 1]],
        }
    )
    assert table.table.columnCount() == 2
    assert table.table.rowCount() >= 3
    keys = [table.table.item(r, 0).text() for r in range(table.table.rowCount())]
    assert "id" in keys
    assert "kind" in keys
    assert "name" in keys


def test_attribute_table_emits_property_changed(qtbot):
    table = MapAttributeTable()
    qtbot.addWidget(table)
    table.set_feature({"id": "w1", "kind": "well", "name": "A1"})

    changes = []
    table.property_changed.connect(lambda fid, key, value: changes.append((fid, key, value)))

    # Find name row and edit value cell
    for row in range(table.table.rowCount()):
        if table.table.item(row, 0).text() == "name":
            table.table.item(row, 1).setText("B2")
            break

    assert ("w1", "name", "B2") in changes


def _feature(fid, name, facies="浅湖"):
    return {
        "id": fid,
        "name": name,
        "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
        "properties": {"facies_name": facies},
    }


def test_attribute_table_filter_restricts_selector(qtbot):
    from paleo_workbench.ui.pages.map_attribute_table import MapAttributeTable

    table = MapAttributeTable()
    qtbot.addWidget(table)
    table.set_layer_features([
        _feature("f1", "W1", "浅湖"),
        _feature("f2", "W2", "深湖"),
        _feature("f3", "W3", "浅湖"),
    ])
    assert table.feature_combo.count() == 4  # placeholder + 3

    visible = table.apply_filter(field="facies_name", needle="浅湖")
    assert visible == ["f1", "f3"]
    assert table.feature_combo.count() == 3  # placeholder + 2

    visible = table.apply_filter(field="facies_name", needle="")
    assert len(visible) == 3


def test_attribute_table_filter_survives_selection_when_matching(qtbot):
    from paleo_workbench.ui.pages.map_attribute_table import MapAttributeTable

    table = MapAttributeTable()
    qtbot.addWidget(table)
    table.set_layer_features([
        _feature("f1", "W1", "浅湖"),
        _feature("f2", "W2", "深湖"),
    ])
    table.set_selected_ids(["f2"])
    table.apply_filter(field="facies_name", needle="深湖")
    assert table.feature_combo.currentData() == "f2"


def test_attribute_table_sort_orders_selector(qtbot):
    from paleo_workbench.ui.pages.map_attribute_table import MapAttributeTable

    table = MapAttributeTable()
    qtbot.addWidget(table)
    table.set_layer_features([
        _feature("f1", "W3"),
        _feature("f2", "W1"),
        _feature("f3", "W2"),
    ])
    visible = table.sort_features("name")
    assert visible == ["f2", "f3", "f1"]
    table.sort_features("")
    assert table.apply_filter() == ["f1", "f2", "f3"]
