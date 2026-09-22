"""基础层标注 schema：工区地图五层带 base_reference role，桥侧可建 name 列。

根因：原生桥 labeling 已启用（field="name"），但 memory provider 没有 name
字段（metadata={} → fields_json 为空 → C++ 丢属性留几何），PAL 对不存在
字段求值全 NULL，静默不画。
"""
from __future__ import annotations

import json

from paleo_workbench.mapping import qgis_mirror
from paleo_workbench.mapping.workarea_map_snapshot import (
    build_workarea_map_snapshot,
)
from paleo_workbench.mapping_workspace.geological_layer_spec import (
    spec_for_role,
)
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.project.domain import (
    CoordinateStatus,
    SeismicSurveyEntity,
    WellEntity,
    WorkArea,
)
from paleo_workbench.project.models import ProjectDocument


def _project() -> ProjectDocument:
    doc = ProjectDocument.new("LabelProj")
    doc.workarea = WorkArea(
        name="测试工区",
        boundary=[[0, 0], [10, 0], [10, 10], [0, 10]],
    )
    doc.wells.append(WellEntity(
        name="W1", project_x=2.0, project_y=3.0,
        coordinate_status=CoordinateStatus.OK,
    ))
    doc.wells.append(WellEntity(
        name="W2", project_x=5.0, project_y=5.0,
        coordinate_status=CoordinateStatus.UNTRANSFORMED,
    ))
    doc.seismic_surveys.append(SeismicSurveyEntity(
        name="SVY1", extent=[[1, 1], [8, 1], [8, 8], [1, 8]],
    ))
    return doc


def test_workarea_snapshot_layers_carry_base_reference_role():
    snapshot = build_workarea_map_snapshot(_project())
    assert len(snapshot.layers) == 5
    for layer in snapshot.layers:
        assert layer.metadata.get("role") == LayerRole.BASE_REFERENCE.value


def test_fields_json_for_base_reference_has_name():
    snapshot = build_workarea_map_snapshot(_project())
    for layer in snapshot.layers:
        raw = qgis_mirror._fields_json_for_metadata(dict(layer.metadata))
        assert raw, f"layer {layer.id} fields_json 为空"
        names = [entry.get("name") for entry in json.loads(raw)]
        assert "name" in names, f"layer {layer.id} 缺少 name 字段"


def test_spec_for_base_reference_has_name_field():
    spec = spec_for_role("base_reference")
    assert "name" in [field.name for field in spec.fields]
