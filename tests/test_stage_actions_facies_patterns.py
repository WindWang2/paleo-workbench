"""阶段动作接线：mock 预测层与初始相图层获得带图案的分类样式。"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from paleo_workbench.catalog import CoreCatalogAdapter, DataCatalogService
from paleo_workbench.catalog.runtime import reset_catalog, set_catalog
from paleo_workbench.mapping.facies_patterns import (
    FACIES_PATTERN_DIR,
    FACIES_PATTERN_MAP,
)
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.project.domain import WellEntity, WorkArea
from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument
from paleo_workbench.ui.workstation.stage_actions import _categorized_facies_style

QApplication.instance() or QApplication([])

_POLYGON = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}


def _composite(qtbot, monkeypatch, project):
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    def _no_bridge():
        raise RuntimeError("bridge disabled for test")

    monkeypatch.setattr(
        "paleo_workbench.ui.qgis_stack.canvas_shim._load_mapstack", _no_bridge)
    doc = CompositeDocument(project)
    qtbot.addWidget(doc)
    return doc


def _project() -> ProjectDocument:
    project = ProjectDocument.new("相图案接线")
    project.coordinate.project_crs = "EPSG:32650"
    project.workarea = WorkArea(
        name="工区",
        boundary=[[-2, -2], [12, -2], [12, 2], [-2, 2], [-2, -2]],
        project_crs="EPSG:32650",
        boundary_crs="EPSG:32650",
    )
    project.wells.extend([
        WellEntity(id="well_a", name="A", project_x=0.0, project_y=0.0, td=1200.0),
        WellEntity(id="well_b", name="B", project_x=10.0, project_y=0.0),
    ])
    project.stratigraphy.target_horizon = "Sq1"
    return project


@pytest.fixture
def catalog(tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_path)
    set_catalog(CoreCatalogAdapter(service))
    try:
        yield service
    finally:
        reset_catalog()
        service.close()


def _live_layers(doc, role: LayerRole) -> list:
    return [
        layer_id
        for layer_id in doc.stage_controller.state.layers_with_role(role)
        if doc.edit_controller.layer(str(layer_id)) is not None
    ]


def _assert_valid_patterns(style: dict, values: set[str]) -> None:
    assert style.get("renderer") == "categorized"
    patterns = dict(style.get("fill_patterns") or {})
    known_ids = set(FACIES_PATTERN_MAP.values())
    for value in values:
        pattern_id = patterns.get(value)
        assert pattern_id is not None, f"{value} 缺少图案映射"
        assert pattern_id in known_ids
        assert (FACIES_PATTERN_DIR / f"{pattern_id}.svg").is_file()


def test_helper_prefers_feature_color_then_palette() -> None:
    features = [
        (dict(_POLYGON), {"facies_name": "扇三角洲", "color": "#112233"}),
        (dict(_POLYGON), {"facies_name": "自定相"}),
    ]
    style = _categorized_facies_style(features)
    assert style["renderer"] == "categorized"
    assert style["field"] == "facies_name"
    assert isinstance(style["categories"], dict)
    fills = dict(style["categories"])
    assert fills["扇三角洲"] == "#112233"
    assert fills["自定相"] not in ("", "#112233")
    assert style["fill_patterns"] == {"扇三角洲": "delta"}
    repeat = _categorized_facies_style(list(reversed(features)))
    assert dict(repeat["categories"])["自定相"] == fills["自定相"]


def test_helper_blank_and_empty() -> None:
    assert _categorized_facies_style([]) == {}
    assert _categorized_facies_style([
        (dict(_POLYGON), {"facies": "空白相"}),
        (dict(_POLYGON), {"facies": ""}),
    ]) == {}
    assert _categorized_facies_style([
        {"geometry": dict(_POLYGON), "properties": {"facies": "滨浅湖"}},
    ])["field"] == "facies"


def test_helper_output_survives_style_round_trip() -> None:
    from paleo_workbench.mapping.map_styles import VectorStyle

    style = _categorized_facies_style([
        (dict(_POLYGON), {"facies_name": "扇三角洲", "color": "#112233"}),
        (dict(_POLYGON), {"facies_name": "滨浅湖"}),
    ])
    parsed = VectorStyle.from_dict(style)
    assert parsed.renderer == "categorized"
    assert parsed.field == "facies_name"
    assert {value for value, _fill, _label in parsed.categories} == {"扇三角洲", "滨浅湖"}
    assert dict(parsed.fill_patterns)["扇三角洲"] == "delta"


def test_helper_output_accepted_by_native_legacy_entry() -> None:
    bridge = pytest.importorskip("qgis_render_bridge")
    style = _categorized_facies_style([
        (dict(_POLYGON), {"facies_name": "扇三角洲"}),
        (dict(_POLYGON), {"facies_name": "滨浅湖"}),
    ])
    bridge.legacy_style_to_renderer_xml(style, "polygon")


def test_seismic_mock_overlay_gets_pattern_style(qtbot, monkeypatch, catalog) -> None:
    project = _project()
    doc = _composite(qtbot, monkeypatch, project)
    doc.stage_actions.dispatch("facies_calibration", "run_seismic_facies_mock")
    layers = _live_layers(doc, LayerRole.SEISMIC_FACIES_PREDICTION)
    assert len(layers) == 1
    layer = doc.edit_controller.layer(str(layers[0]))
    style = dict(layer.style or {})
    assert style.get("field") == "facies_name"
    observed = {
        str(feature.attributes.get("facies_name") or "")
        for feature in layer.features()
    } - {"", "空白相"}
    assert observed
    assert set(style.get("categories", {})) >= observed
    _assert_valid_patterns(style, observed)


def test_style_failure_never_blocks_layer_creation(
    qtbot, monkeypatch, catalog,
) -> None:
    """样式生成抛异常时建层不受影响（_apply_categorized_facies_style 吞异常保建层）。"""
    import paleo_workbench.ui.workstation.stage_actions as stage_actions

    calls: list[bool] = []

    def _boom(features):
        calls.append(True)
        raise RuntimeError("style backend down")

    monkeypatch.setattr(stage_actions, "_categorized_facies_style", _boom)
    project = _project()
    doc = _composite(qtbot, monkeypatch, project)
    doc.stage_actions.dispatch("facies_calibration", "run_seismic_facies_mock")
    assert calls, "样式路径应被实际调用（否则测试为空断言）"
    layers = _live_layers(doc, LayerRole.SEISMIC_FACIES_PREDICTION)
    assert len(layers) == 1


def test_blank_initial_facies_keeps_translucent_style(qtbot, monkeypatch) -> None:
    project = _project()
    doc = _composite(qtbot, monkeypatch, project)
    doc.stage_actions.dispatch("facies_calibration", "load_initial_facies")
    layers = _live_layers(doc, LayerRole.INITIAL_FACIES_SOURCE)
    assert len(layers) == 1
    style = dict(doc.edit_controller.layer(str(layers[0])).style or {})
    assert "fill_patterns" not in style
    assert style.get("fill") == "#1a64748b"


def test_initial_facies_with_real_names_gets_pattern_style(
    qtbot, monkeypatch,
) -> None:
    project = _project()
    project.paleomap_documents.append(PaleoMapDocument(
        name="已有相图",
        linked_target_horizon="Sq1",
        facies_polygons=[
            {
                "facies": "扇三角洲",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                "properties": {},
            },
            {
                "facies": "滨浅湖",
                "geometry": {"type": "Polygon", "coordinates": [[[2, 2], [3, 2], [3, 3], [2, 2]]]},
                "properties": {"color": "#445566"},
            },
        ],
    ))
    doc = _composite(qtbot, monkeypatch, project)
    doc.stage_actions.dispatch("facies_calibration", "load_initial_facies")
    layers = _live_layers(doc, LayerRole.INITIAL_FACIES_SOURCE)
    assert len(layers) == 1
    style = dict(doc.edit_controller.layer(str(layers[0])).style or {})
    assert style.get("renderer") == "categorized"
    fills = dict(style.get("categories", {}))
    assert fills["滨浅湖"] == "#445566"
    _assert_valid_patterns(style, {"扇三角洲", "滨浅湖"})


def test_create_facies_draft_styles_from_raw(qtbot, monkeypatch) -> None:
    project = _project()
    doc = _composite(qtbot, monkeypatch, project)
    doc.stage_actions.dispatch("facies_calibration", "load_initial_facies")
    doc.stage_actions.dispatch("facies_calibration", "create_facies_draft")
    drafts = _live_layers(doc, LayerRole.INITIAL_FACIES_DRAFT)
    assert len(drafts) == 1
    style = dict(doc.edit_controller.layer(str(drafts[0])).style or {})
    assert "fill_patterns" not in style


def test_create_facies_draft_with_named_facies(qtbot, monkeypatch) -> None:
    project = _project()
    project.paleomap_documents.append(PaleoMapDocument(
        name="已有相图",
        linked_target_horizon="Sq1",
        facies_polygons=[{
            "facies": "三角洲前缘",
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            "properties": {},
        }],
    ))
    doc = _composite(qtbot, monkeypatch, project)
    doc.stage_actions.dispatch("facies_calibration", "load_initial_facies")
    doc.stage_actions.dispatch("facies_calibration", "create_facies_draft")
    drafts = _live_layers(doc, LayerRole.INITIAL_FACIES_DRAFT)
    assert len(drafts) == 1
    style = dict(doc.edit_controller.layer(str(drafts[0])).style or {})
    assert style.get("renderer") == "categorized"
    _assert_valid_patterns(style, {"三角洲前缘"})
