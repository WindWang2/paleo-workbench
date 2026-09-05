from paleo_workbench.ui.layout_presets import (
    RESET_LAYOUT_PRESET_ID,
    get_preset,
    list_presets,
    preset_labels,
    visibility_dict,
)


def test_named_presets_cover_composite_and_interpretation():
    presets = list_presets()
    ids = {p.id for p in presets}
    assert "composite_default" in ids
    assert "integrated" in ids  # 原 interpretation（解释工作区）演进为综合
    assert RESET_LAYOUT_PRESET_ID == "composite_default"

    composite = get_preset("composite_default")
    assert composite is not None
    assert composite.label == "编图 · 默认"
    assert not hasattr(composite, "document_tab")
    matrix = visibility_dict(composite.visibility)
    assert matrix["composite_layer"] is True
    assert matrix["well"] is False
    assert matrix["seismic"] is False
    assert matrix["hub"] is False
    assert matrix["nav"] is True

    integrated = get_preset("integrated")
    assert integrated is not None
    im = visibility_dict(integrated.visibility)
    assert im["inspector"] is True
    assert im["process"] is True
    assert im["tasks"] is True
    assert im["well"] is True
    assert im["seismic"] is True
    assert im["composite_layer"] is True


def test_preset_labels_are_stable_menu_pairs():
    labels = preset_labels()
    assert labels[0] == ("composite_default", "编图 · 默认")
    assert ("integrated", "综合") in labels
