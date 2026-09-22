"""WorkstationInspector（B4 数据真实化）测试。

覆盖：show_horizon 无假值、show_seismic / show_map_component / 未知 kind
分派、空选择空态、井联动状态真实化。

全部用真实 ProjectDocument / 领域实体构造，不 mock UI。
"""

from __future__ import annotations

from PySide6.QtWidgets import QFormLayout

from paleo_workbench.project.domain import (
    EntityAssetLink,
    SeismicSurveyEntity,
    WellEntity,
)
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.workstation.inspector import WorkstationInspector


def _project() -> ProjectDocument:
    return ProjectDocument.new("InspectorTest", region="测试工区")


def _form_texts(form: QFormLayout) -> list[str]:
    texts: list[str] = []
    for row in range(form.rowCount()):
        label = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
        field = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
        if label is not None and label.widget() is not None:
            texts.append(label.widget().text())
        if field is not None and field.widget() is not None:
            texts.append(field.widget().text())
    return texts


def _all_texts(inspector: WorkstationInspector) -> str:
    return "\n".join(
        _form_texts(inspector.properties_form) + _form_texts(inspector.interpretation_form)
    )


def test_show_horizon_has_no_fabricated_values(qtbot):
    """show_horizon 不再显示编造的 TWT/深度/IL-XL 拾取值，只显示资源真实属性。"""
    project = _project()
    inspector = WorkstationInspector(project)
    qtbot.addWidget(inspector)

    resource = ResourceItem(
        name="H2.dat",
        path="horizons/H2.dat",
        type="horizon",
        format="dat",
        crs="EPSG:4326",
    )
    inspector.show_payload({"kind": "horizon", "name": "H2", "object": resource})

    text = _all_texts(inspector)
    for fabricated in ("1436", "1352.3", "1680 / 4200", "建议复核"):
        assert fabricated not in text
    # 真实属性在场
    assert "horizons/H2.dat" in text
    assert "dat" in text
    assert "EPSG:4326" in text


def test_show_seismic_dispatch_and_axis_ranges(qtbot):
    """seismic 资源/survey 显示路径、格式与 inline-crossline 范围（若有）。"""
    project = _project()
    survey = SeismicSurveyEntity(
        name="S1",
        survey_type="3d",
        inline_range=[100, 200, 2],
        crossline_range=[300, 400, 4],
    )
    project.seismic_surveys.append(survey)
    inspector = WorkstationInspector(project)
    qtbot.addWidget(inspector)

    resource = ResourceItem(name="S1.segy", path="seis/S1.segy", type="seismic", format="segy")
    inspector.show_payload({"kind": "resource", "object": resource})
    text = _all_texts(inspector)
    assert "seis/S1.segy" in text
    assert "segy" in text
    assert "100 – 200" in text
    assert "300 – 400" in text
    assert inspector.header.text() == "检查器 · S1.segy"

    # 直接以 survey payload 分派
    inspector.show_payload({"kind": "seismic", "object": survey})
    assert inspector.header.text() == "检查器 · S1"

    # 无 survey 匹配且资源无范围 → "—"，不编造
    orphan = ResourceItem(name="X.segy", path="seis/X.segy", type="seismic", format="segy")
    inspector.show_payload({"kind": "resource", "object": orphan})
    text = _all_texts(inspector)
    assert text.count("—") >= 2


def test_show_map_component_dispatch(qtbot):
    """map_component 显示组件类型/位置/可见性（W4 composer 预留入口）。"""
    inspector = WorkstationInspector(_project())
    qtbot.addWidget(inspector)

    inspector.show_payload(
        {
            "kind": "map_component",
            "name": "指北针",
            "component_type": "north_arrow",
            "position": (120, 40),
            "visible": True,
        }
    )
    text = _all_texts(inspector)
    assert "指北针" in inspector.header.text()
    assert "north_arrow" in text
    assert "120, 40" in text
    assert "是" in text

    inspector.show_payload(
        {"kind": "map_component", "name": "比例尺", "component_type": "scale_bar", "visible": False}
    )
    text = _all_texts(inspector)
    assert "否" in text


def test_unknown_kind_shows_generic_table(qtbot):
    """未知 kind 显示通用键值表而不是丢弃。"""
    inspector = WorkstationInspector(_project())
    qtbot.addWidget(inspector)

    inspector.show_payload(
        {"kind": "mystery", "name": "X", "depth": 3.5, "note": "abc", "active": True}
    )
    text = _all_texts(inspector)
    assert "检查器 · X" == inspector.header.text()
    assert "mystery" in text
    assert "3.5" in text
    assert "abc" in text
    assert "是" in text


def test_empty_selection_state(qtbot):
    """无选择空态：构造无工程 / 显式 show_empty 都显示「未选择对象」。"""
    inspector = WorkstationInspector()
    qtbot.addWidget(inspector)
    assert "未选择对象" in _all_texts(inspector)

    inspector.show_well(WellEntity(name="A1", kb=10))
    assert "A1" in _all_texts(inspector)

    inspector.show_empty()
    assert "未选择对象" in _all_texts(inspector)


def test_well_link_state_reflects_real_data(qtbot):
    """井联动状态来自传入数据（坐标/轨迹），缺数据显示 "—"。"""
    project = _project()
    inspector = WorkstationInspector(project)
    qtbot.addWidget(inspector)

    bare = WellEntity(name="B7")
    inspector.show_well(bare)
    interpretation = _form_texts(inspector.interpretation_form)
    assert "—" in interpretation  # 无坐标无轨迹 → 缺失占位

    located = WellEntity(name="C1", project_x=1.0, project_y=2.0)
    inspector.show_well(located)
    assert "井位坐标" in _all_texts(inspector)

    project.entity_asset_links.append(
        EntityAssetLink(entity_type="well", entity_id=located.id, asset_id="a1", role="trajectory")
    )
    inspector.show_well(located)
    text = _all_texts(inspector)
    assert "井位坐标" in text
    assert "轨迹" in text
    assert "地图 / 地震 / 测井已联动" not in text
