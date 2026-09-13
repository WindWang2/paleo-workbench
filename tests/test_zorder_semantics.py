# -*- coding: utf-8 -*-
"""图层显示序语义（面板顶 = 画布最上 = 压住下层）。

约定的两种读法：**组装列表自下而上**（``_layers`` / 组装快照，末位=最上），
**面板自上而下**（原生树首行=最上；由 mirror 推桥时的显式反转呈现）。

覆盖：模板分类归属（新建层进工作流组而非未分类）、组装序（用户层在
上/基础层反转井位压边界）、新层置顶、副本紧邻源层、显示序单一权威
（面板回写 → 控制器 → 持久化）。
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")


def _project(tmp_path: Path):
    from paleo_workbench.project.domain import WellEntity
    from paleo_workbench.project.models import ProjectDocument

    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    project.wells.append(
        WellEntity(name="A12", surface_x=1.0, surface_y=2.0,
                   project_x=1.0, project_y=2.0)
    )
    return project


# -- 模板分类归属 ---------------------------------------------------------------


def test_template_metadata_classification_into_workflow_groups():
    """新建层按模板进工作流组（快照的模板键在 metadata.template）。"""
    from paleo_workbench.mapping_workspace.layer_groups import (
        classify_layer_for_migration,
    )

    cases = {
        "fault": ("fault_constraint", "phase2.constraints"),
        "source": ("provenance_line", "phase2.constraints"),
        "spreading": ("distribution_line", "phase2.constraints"),
        "direction": ("provenance_direction", "phase2.constraints"),
        "break": ("interpolation_boundary", "phase2.constraints"),
        "well_point": ("map_symbol", "phase3.geology"),
        "facies": ("initial_facies_draft", "phase1.interpretation"),
        "facies_sub": ("initial_facies_draft", "phase1.interpretation"),
        "facies_micro": ("initial_facies_draft", "phase1.interpretation"),
        "extent": ("map_reference", "phase3.geology"),
    }
    for template, (role_value, group) in cases.items():
        layer = SimpleNamespace(id="composite:layer_x",
                                metadata={"template": template})
        role, home, _kind = classify_layer_for_migration(layer)
        assert role.value == role_value, template
        assert home == group, template
    # 无模板 → 兜底未分类
    role, home, _ = classify_layer_for_migration(
        SimpleNamespace(id="composite:layer_x", metadata={}))
    assert role.value == "legacy_unclassified"


# -- 显示序语义（CompositeDocument 级） ------------------------------------------


def test_composition_display_order_top_down(qtbot, tmp_path):
    """组装序自上而下：用户层最上，基础层反转（井位压边界）。"""
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    controller = document.edit_controller
    layer = controller.create_layer("断层线", "line", template="fault")
    document._sync_composition_now()

    layers = document.layer_manager._layers
    ids = [snapshot.id for snapshot in layers]
    # 组装序自下而上：末位 = 画布最上 = 面板顶（显示时整体反转）。
    assert ids[-1] == layer.id
    assert ids[:-1] == [snap.id for snap in document._base_layers]


def test_new_layer_heads_controller_order(qtbot, tmp_path):
    """新建/复制置顶（控制器显示序）；apply_display_state 对未见面层头插。"""
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    controller = document.edit_controller
    first = controller.create_layer("层一", "line")
    second = controller.create_layer("层二", "line")
    assert list(controller._layers.keys())[-1] == second.id  # 新层置顶（组装序末位）

    # 面板回写：面板列表未覆盖的层保守保持原序**尾部**（apply_display_state
    # 的异常路径契约），新层不被丢掉。
    controller.apply_display_state([
        SimpleNamespace(id=first.id, visible=True, opacity=1.0)])
    assert list(controller._layers.keys()) == [first.id, second.id]

    # 复制置顶（与新建层同语义）
    dup = controller.duplicate_layer(first.id)
    assert list(controller._layers.keys())[-1] == dup.id


def test_persistence_follows_display_order(qtbot, tmp_path):
    """工程持久化序 = 控制器显示序（单一权威，无翻转）。"""
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    controller = document.edit_controller
    a = controller.create_layer("A", "line")
    b = controller.create_layer("B", "line")
    controller.sync_to_project(document._project)
    persisted = [record.id for record in document._project.user_vector_layers]
    assert persisted == list(controller._layers.keys())
    assert persisted[-1] == b.id
