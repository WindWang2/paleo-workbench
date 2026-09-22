"""井/震预测任务分类：键存在不算数，键值非空才算（pipeline 恒写双键）。"""
from __future__ import annotations

from paleo_workbench.mapping.factor_layer_products import classify_prediction_task
from paleo_workbench.project.models import PredictionTask
from paleo_workbench.ui.workstation.stage_actions import StageActionDispatcher


def _task(refs, name=""):
    return PredictionTask(name=name, input_refs=refs)


def _both(task):
    return (
        classify_prediction_task(task),
        StageActionDispatcher._classify_prediction_task(task),
    )


def test_pipeline_well_task_classifies_well():
    # materialize_prediction_task 恒写双键；seismic 值为空列表
    task = _task({"well_log_resource_ids": ["res_a"], "seismic_resource_ids": []})
    assert _both(task) == ("well", "well")


def test_pipeline_seismic_task_classifies_seismic():
    task = _task({"well_log_resource_ids": [], "seismic_resource_ids": ["seis1"]})
    assert _both(task) == ("seismic", "seismic")


def test_legacy_single_key_shapes_still_work():
    assert _both(_task({"well_log_resource_ids": ["res_a"]})) == ("well", "well")
    assert _both(_task({"seismic_resource_ids": ["seis1"]})) == ("seismic", "seismic")


def test_empty_values_fall_back_to_name():
    assert _both(_task(
        {"well_log_resource_ids": [], "seismic_resource_ids": []},
        name="测井相预测（mock）· Sq1",
    )) == ("well", "well")
    assert _both(_task({}, name="地震相面预测")) == ("seismic", "seismic")
    assert _both(_task({}, name="")) == ("unknown", "unknown")
