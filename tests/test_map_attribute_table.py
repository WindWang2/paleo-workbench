from paleo_workbench.ui.pages.map_attribute_table import MapAttributeTable


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
