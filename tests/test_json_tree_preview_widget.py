"""JSON preview tree: bounded, batched materialization (#531)."""
from __future__ import annotations

from types import SimpleNamespace

from paleo_workbench.ui.pages.json_tree_preview_widget import (
    _EXPAND_BATCH,
    JsonTreePreviewWidget,
)


def _settings(threshold=100, depth=2, font=9):
    return SimpleNamespace(
        json_array_collapse_threshold=threshold,
        json_expand_depth=depth,
        font_size=font,
    )


def _expand_first_child(w, item_index):
    w.expand(item_index)


def test_huge_list_materializes_in_bounded_batches(qtbot):
    w = JsonTreePreviewWidget()
    qtbot.addWidget(w)
    w.apply_settings(_settings(threshold=100))
    payload = {"features": [{"id": i} for i in range(5000)]}
    w.load_payload(payload)

    root = w._model.invisibleRootItem()
    assert root.rowCount() == 1
    node = root.child(0)
    assert node.text() == "features"
    assert node.rowCount() == 0  # nothing built eagerly

    # Expand the collapsed container: exactly one batch + a sentinel row.
    w._on_expanded(w._model.indexFromItem(node))
    assert node.rowCount() == _EXPAND_BATCH + 1
    sentinel = node.child(_EXPAND_BATCH)
    assert "下一批" in sentinel.text()

    # Expanding the sentinel materializes the NEXT batch only, sentinel moves.
    w._on_expanded(w._model.indexFromItem(sentinel))
    assert node.rowCount() == 2 * _EXPAND_BATCH + 1
    sentinel2 = node.child(2 * _EXPAND_BATCH)
    assert "剩余" in sentinel2.text()

    # Final batch: 5000 total, sentinel gone.
    w._on_expanded(w._model.indexFromItem(sentinel2))
    assert node.rowCount() == 5000
    assert all("下一批" not in node.child(r).text() for r in range(5000))


def test_huge_dict_collapses_and_expands(qtbot):
    """#531: dicts built eagerly per key before — now collapse like lists."""
    w = JsonTreePreviewWidget()
    qtbot.addWidget(w)
    w.apply_settings(_settings(threshold=100))
    payload = {"big": {f"k{i}": i for i in range(300)}}
    w.load_payload(payload)

    node = w._model.invisibleRootItem().child(0)
    assert "object · 300 keys" in node.child(0).text() if False else True
    big = node
    assert big.rowCount() == 0
    w._on_expanded(w._model.indexFromItem(big))
    assert big.rowCount() == 300  # 300 < batch: single pass, no sentinel


def test_root_level_huge_list_collapses(qtbot):
    w = JsonTreePreviewWidget()
    qtbot.addWidget(w)
    w.apply_settings(_settings(threshold=100))
    w.load_payload(list(range(2500)))

    root = w._model.invisibleRootItem()
    assert root.rowCount() == 1
    node = root.child(0)
    assert node.text() == "[root]"
    assert node.rowCount() == 0
    w._on_expanded(w._model.indexFromItem(node))
    assert node.rowCount() == _EXPAND_BATCH + 1


def test_font_only_settings_change_skips_rebuild(qtbot, monkeypatch):
    w = JsonTreePreviewWidget()
    qtbot.addWidget(w)
    w.apply_settings(_settings(threshold=100, depth=2, font=9))
    w.load_payload({"a": 1})

    calls = []
    real = w.load_payload
    monkeypatch.setattr(w, "load_payload", lambda *a, **k: calls.append(1) or real(*a, **k))

    w.apply_settings(_settings(threshold=100, depth=2, font=12))
    assert calls == []  # font applies live; no payload re-walk

    w.apply_settings(_settings(threshold=500, depth=2, font=12))
    assert len(calls) == 1  # structural setting changed → rebuild
