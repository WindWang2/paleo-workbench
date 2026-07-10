from paleo_workbench.ui.pages.map_edit_commands import EditCommandStack, MoveCommand


def test_move_command_undo_redo():
    positions = {"f1": [0.0, 0.0]}

    def apply(fid, dx, dy):
        positions[fid][0] += dx
        positions[fid][1] += dy

    stack = EditCommandStack(max_depth=50)
    stack.push(MoveCommand(feature_ids=["f1"], dx=3, dy=4, apply_move=apply))
    assert positions["f1"] == [3.0, 4.0]
    assert stack.can_undo() is True
    assert stack.can_redo() is False

    stack.undo()
    assert positions["f1"] == [0.0, 0.0]
    assert stack.can_undo() is False
    assert stack.can_redo() is True

    stack.redo()
    assert positions["f1"] == [3.0, 4.0]
    assert stack.can_undo() is True
    assert stack.can_redo() is False


def test_edit_command_stack_max_depth_and_clear():
    log: list[str] = []

    def apply(fid, dx, dy):
        log.append(f"{fid}:{dx}:{dy}")

    stack = EditCommandStack(max_depth=2)
    stack.push(MoveCommand(feature_ids=["a"], dx=1, dy=0, apply_move=apply))
    stack.push(MoveCommand(feature_ids=["b"], dx=1, dy=0, apply_move=apply))
    stack.push(MoveCommand(feature_ids=["c"], dx=1, dy=0, apply_move=apply))
    # Only last two remain undoable
    stack.undo()
    stack.undo()
    assert stack.can_undo() is False
    # redo still available for the two kept commands
    assert stack.can_redo() is True
    stack.clear()
    assert stack.can_undo() is False
    assert stack.can_redo() is False


def test_move_features_mutates_coordinate_lists():
    from paleo_workbench.mapping import map_edit_api as api

    records = {
        "poly": {
            "id": "poly",
            "kind": "facies",
            "coordinates": [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 0.0]],
        },
        "well": {
            "id": "well",
            "kind": "well",
            "coordinates": [1.0, 1.0],
        },
    }
    api.move_features(records, ["poly", "well"], 3.0, 4.0)
    assert records["poly"]["coordinates"][0] == [3.0, 4.0]
    assert records["poly"]["coordinates"][1] == [5.0, 4.0]
    assert records["well"]["coordinates"] == [4.0, 5.0]
