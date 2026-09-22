"""V7 §8 类型化 Inspector 测试（feature / factor raster / map product）。"""
from __future__ import annotations

import pytest

from paleo_workbench.project.models import FactorMapTask, MapProductRecord
from paleo_workbench.ui.workstation.inspector import WorkstationInspector
from paleo_workbench.ui.workstation.state_language import state_token


@pytest.fixture()
def inspector(qtbot):
    widget = WorkstationInspector()
    qtbot.addWidget(widget)
    return widget


def _row_texts(inspector) -> dict[str, str]:
    """两个表单（属性/解释）的行文本合并（解释表单行后到，覆盖同名）。"""
    rows: dict[str, str] = {}
    for form in (inspector.properties_form, inspector.interpretation_form):
        for row in range(form.rowCount()):
            label_item = form.itemAt(row, form.ItemRole.LabelRole)
            field_item = form.itemAt(row, form.ItemRole.FieldRole)
            if label_item is None or field_item is None:
                continue
            label = label_item.widget()
            field = field_item.widget()
            if label is None or field is None:
                continue
            rows[label.text()] = getattr(field, "text", lambda: "")()
    return rows


# ---------------------------------------------------------------------------
# Feature 分节
# ---------------------------------------------------------------------------


def test_show_feature_renders_identify_result(inspector):
    inspector.show_payload({
        "kind": "feature",
        "object": {
            "layer_name": "物源线 A",
            "feature_id": "f-123",
            "geometry_type": "LineString",
            "attributes": {"confidence": "高", "strike": 45.0},
            "template": "provenance_line",
            "source": "composite",
            "editable": True,
        },
    })
    assert "要素" in inspector.header.text()
    rows = _row_texts(inspector)
    assert rows["要素 ID"] == "f-123"
    assert rows["图层"] == "物源线 A"
    assert rows["几何"] == "线"
    assert rows["可编辑"] == "是"
    assert rows["confidence"] == "高"


def test_show_feature_missing_fields_honest(inspector):
    inspector.show_payload({"kind": "feature", "object": {}})
    rows = _row_texts(inspector)
    assert rows["要素 ID"] == "—"
    assert rows["几何"] == "—"


# ---------------------------------------------------------------------------
# Factor raster 分节
# ---------------------------------------------------------------------------


def _task() -> FactorMapTask:
    return FactorMapTask(
        name="厚度因子 T1",
        target_horizon="T2",
        factor_type="thickness",
        method="kriging",
        parameters={"unit": "m", "grid_step": 0.5},
        quality_metrics={"rmse": 1.23},
        status="completed",
        source_kind="real",
        input_snapshot_hash="abcdef1234567890",
    )


def test_show_factor_renders_task_and_grid(inspector):
    inspector.show_payload({
        "kind": "factor",
        "task": _task(),
        "grid": {"min": 10.0, "max": 220.5,
                 "uncertainty": (0.5, 3.25)},
    })
    assert "单因素" in inspector.header.text()
    rows = _row_texts(inspector)
    assert rows["因素"] == "thickness"
    assert rows["方法"] == "kriging"
    assert rows["单位"] == "m"
    assert rows["取值范围"] == "10 ~ 220.5"
    assert rows["不确定性"] == "0.5 ~ 3.25"
    assert "rmse=1.23" in rows["QC"]
    assert rows["状态"] == "completed"
    assert rows["源类型"] == "real"


def test_show_factor_without_grid_shows_dash(inspector):
    inspector.show_payload({"kind": "factor", "task": _task(), "grid": {}})
    rows = _row_texts(inspector)
    assert rows["取值范围"] == "—"
    assert "不确定性" not in rows


# ---------------------------------------------------------------------------
# MapProduct 分节
# ---------------------------------------------------------------------------


def _record() -> MapProductRecord:
    return MapProductRecord(
        product_name="综合编图 珠江口",
        factor_task_ids=["f1", "f2", "f3"],
        interpretation_refs=["i1"],
        run_id="run-9",
        output_version_id="ver_abc123",
        scientific_fingerprint="sha:0123456789abcdef0123456789abcdef",
        status="final",
        manual_adjustments=[{"kind": "boundary"}],
    )


def test_show_map_product_renders_lineage(inspector):
    inspector.show_payload({
        "kind": "map_product",
        "object": _record(),
        "staleness": state_token("freshness", "stale"),
    })
    assert "成果" in inspector.header.text()
    rows = _row_texts(inspector)
    assert rows["状态"] == "最终"
    assert rows["因子输入"] == "3 项"
    assert rows["解释引用"] == "1 项"
    assert rows["运行"] == "run-9"
    assert rows["输出版本"] == "ver_abc123"
    assert rows["手工调整"] == "1 项"
    assert rows["指纹"].startswith("sha:0123456789a")


def test_show_map_product_frozen_status(inspector):
    record = _record()
    record.frozen = True
    inspector.show_payload({"kind": "map_product", "object": record})
    rows = _row_texts(inspector)
    assert rows["状态"] == "已冻结"


def test_show_map_product_without_staleness_omits_row(inspector):
    inspector.show_payload({"kind": "map_product", "object": _record()})
    rows = _row_texts(inspector)
    assert "新鲜度" not in rows


# ---------------------------------------------------------------------------
# 旧 kind 不回归（layer 分节仍走 seam）
# ---------------------------------------------------------------------------


def test_layer_kind_still_works(inspector):
    inspector.set_context_seam(lambda payload: {"角色": "物源线"})
    inspector.show_payload({
        "kind": "layer", "layer_type": "约束", "object": None,
    })
    rows = _row_texts(inspector)
    assert rows.get("角色") == "物源线"
