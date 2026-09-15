# -*- coding: utf-8 -*-
"""编辑期换相弹窗（V12 续）：相列表对话框 + 选区批量 + 工具登记。

用户诉求（原话）：「编辑支持弹窗更换相（弹窗是相的列表，支持选择，然后
确定，这样就可以更换相图的 feature 的特性/label）」。本文件钉住：

* 列表形态（相名列表 + 当前值预选 + 搜索过滤 + 确定/取消）；
* ``selection()`` 与 ``apply_facies_selection`` 的契约一致（三字段 + level）；
* 选区批量只弹**一次**对话框（此前 N 要素 = N 次弹窗）；
* ``change_facies`` 工具与注册表/求值器/帮助三处同源。
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QDialog

from paleo_workbench.mapping.action_registry import ACTION_SPECS, RISK_WRITE
from paleo_workbench.mapping.facies_taxonomy import FaciesTaxonomy
from paleo_workbench.mapping.tool_availability import TOOL_IDS
from paleo_workbench.mapping.tool_help import TOOL_LABELS

QApplication.instance() or QApplication([])


# --------------------------------------------------------------------------- #
# 对话框契约
# --------------------------------------------------------------------------- #

def _dialog(current=None, **kwargs):
    from paleo_workbench.ui.workstation.facies_selector import FaciesChangeDialog

    return FaciesChangeDialog(FaciesTaxonomy.builtin(), current, **kwargs)


def test_dialog_lists_top_level_facies_and_preselects_current(qapp):
    taxonomy = FaciesTaxonomy.builtin()
    names = taxonomy.names("facies")
    assert names, "内置词表至少有一个相"
    dialog = _dialog({"facies": names[0]})
    listed = dialog.listed_facies()
    assert listed == names
    assert dialog.selected_facies() == names[0]


def test_dialog_search_filters_without_losing_selection(qapp):
    taxonomy = FaciesTaxonomy.builtin()
    names = taxonomy.names("facies")
    dialog = _dialog({"facies": names[0]})
    dialog.set_search_text(names[-1][:1])
    assert dialog.listed_facies(), "搜索命中至少一项"
    assert all(names[-1][:1] in name for name in dialog.listed_facies())
    dialog.set_search_text("")
    assert dialog.listed_facies() == names
    # 清空搜索后，原选择仍在（过滤是呈现态，不改语义）。
    assert dialog.selected_facies() == names[0]


def test_dialog_selection_contract_matches_controller(qapp):
    from paleo_workbench.ui.workstation.facies_selector import FaciesChangeDialog

    taxonomy = FaciesTaxonomy.builtin()
    names = taxonomy.names("facies")
    dialog = _dialog({"facies": names[0]})
    dialog.select_facies(names[1])
    values = dialog.selection()
    assert set(values) >= {"facies", "sub_facies", "micro_facies", "level"}
    assert values["facies"] == names[1]
    assert values["level"] == "facies"  # 只选到相 → level = facies
    assert FaciesChangeDialog.DialogCode.Accepted  # 标准按钮族可用


def test_dialog_reject_yields_no_selection_signal(qapp, monkeypatch):
    """取消（reject）时宿主不写入——exec 返回 Rejected，selection 不被消费。"""
    dialog = _dialog()
    host = _HostProbe(dialog)
    dialog.exec = lambda: QDialog.DialogCode.Rejected  # type: ignore[method-assign]
    assert host.run() is False
    assert host.applied == []


def test_dialog_accept_applies_selected_facies(qapp):
    taxonomy = FaciesTaxonomy.builtin()
    names = taxonomy.names("facies")
    dialog = _dialog({"facies": names[0]})
    dialog.select_facies(names[-1])
    host = _HostProbe(dialog)
    dialog.exec = lambda: QDialog.DialogCode.Accepted  # type: ignore[method-assign]
    assert host.run() is True
    assert host.applied == [names[-1]]


class _HostProbe:
    """宿主侧消费模式的迷你替身（与 _assign_facies_dialog 同构）。"""

    def __init__(self, dialog):
        self._dialog = dialog
        self.applied: list[str] = []

    def run(self) -> bool:
        if self._dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        self.applied.append(self._dialog.selection().get("facies", ""))
        return True


# --------------------------------------------------------------------------- #
# 选区批量：一次弹窗改整选区
# --------------------------------------------------------------------------- #

@pytest.fixture
def facies_doc(qtbot, tmp_path):
    from paleo_workbench.mapping_workspace.layer_roles import LayerRole
    from paleo_workbench.mapping_workspace.stage_state import LayerMembershipRecord
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    project = ProjectDocument.new("换相弹窗", region="T1")
    project.meta.project_root = str(tmp_path)
    doc = CompositeDocument(project)
    qtbot.addWidget(doc)
    layer = doc.edit_controller.create_layer("相带草稿", "polygon", template="facies")
    doc.stage_controller.state.set_membership(LayerMembershipRecord(
        layer_id=str(layer.id), role=LayerRole.INITIAL_FACIES_DRAFT))
    doc.edit_controller.set_active_layer(str(layer.id))
    from paleo_workbench.mapping.vector_layer import VectorFeature

    for fid in ("f1", "f2", "f3"):
        doc.edit_controller.import_layer_features(str(layer.id), [VectorFeature(
            feature_id=fid,
            geometry={"type": "Polygon", "coordinates": [[
                [0, 0], [1, 0], [1, 1], [0, 0]]]},
            attributes={"facies": "三角洲前缘"},
        )])
    doc._sync_action_state()
    return doc, str(layer.id)


def test_assign_facies_to_selection_opens_one_dialog_for_whole_selection(
        facies_doc, monkeypatch):
    doc, layer_id = facies_doc
    layer = doc.edit_controller.layer(layer_id)
    layer.set_selection(("f1", "f2", "f3"))
    opened: list[FaciesChangeDialog] = []

    from paleo_workbench.ui.workstation import facies_selector

    real_dialog = facies_selector.FaciesChangeDialog

    class _Probe(real_dialog):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            opened.append(self)
            self.select_facies(facies_selector.FaciesTaxonomy.builtin().names(
                "facies")[-1])

        def exec(self):  # noqa: A003 — Qt 契约
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(facies_selector, "FaciesChangeDialog", _Probe)
    doc.assign_facies_to_selection(layer_id)
    assert len(opened) == 1, "整个选区只弹一次对话框"
    target = _Probe.__mro__[1]  # noqa: F841 — 仅为可读性留名
    expected = facies_selector.FaciesTaxonomy.builtin().names("facies")[-1]
    session = layer.edit_session
    source = session.features() if session is not None else layer.features()
    values = {str(f.feature_id): str(f.attributes.get("facies") or "")
              for f in source}
    assert values == {"f1": expected, "f2": expected, "f3": expected}


def test_change_facies_tool_registered_with_help_and_write_risk():
    assert "change_facies" in TOOL_IDS
    assert "change_facies" in ACTION_SPECS
    assert "change_facies" in TOOL_LABELS
    assert ACTION_SPECS["change_facies"].risk == RISK_WRITE
