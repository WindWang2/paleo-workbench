"""Authenticated inference-service protocol and persistence contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from geoviz import CurveData, IntervalItem, WellIntervals, WellLogData

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.prediction.geoviz_online import (
    GeoVizOnlinePredictionError,
    build_single_well_payload,
    response_records,
    run_single_well_prediction,
)
from paleo_workbench.prediction.inference_service import (
    execute_run,
    resolve_inputs_for_model,
    resolve_prediction_postprocess_inputs,
    start_inference,
)
from paleo_workbench.prediction.providers import (
    MODEL_ID_GEOVIZ_ONLINE,
    ensure_geoviz_online_model,
)
from paleo_workbench.project.models import ProjectDocument, ResourceItem


def _well_log() -> WellLogData:
    return WellLogData(
        well_name="HZ27-5-3",
        top_depth=1000.0,
        bottom_depth=1010.0,
        curves=[
            CurveData(
                name="GR",
                unit="GAPI",
                depth=[1000.0, 1005.0, 1010.0],
                values=[45.0, float("nan"), 70.0],
            ),
            CurveData(
                name="AC",
                unit="us/ft",
                depth=[1000.0, 1005.0, 1010.0],
                values=[90.0, 95.0, 100.0],
            ),
        ],
        intervals=WellIntervals(
            formation=[IntervalItem(top=1000.0, bottom=1010.0, name="珠海组")],
        ),
    )


def _write_gr_las(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "~VERSION INFORMATION",
                " VERS. 2.0:",
                "~WELL INFORMATION",
                " WELL. HZ27-5-3:",
                "~CURVE INFORMATION",
                " DEPT.M :",
                " GR.GAPI :",
                " AC.US/FT :",
                "~ASCII",
                "1000.0 45.0 90.0",
                "1005.0 55.0 95.0",
                "1010.0 70.0 100.0",
            ]
        ),
        encoding="utf-8",
    )


def _write_gr_xml(path: Path) -> None:
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<WITSMLComposite xmlns="http://www.witsml.org/schemas/1series">
  <log>
    <nameWell>HZ27-5-3</nameWell>
    <logCurveInfo><mnemonic>DEPT</mnemonic><unit>m</unit></logCurveInfo>
    <logCurveInfo><mnemonic>GR</mnemonic><unit>gAPI</unit></logCurveInfo>
    <logCurveInfo><mnemonic>AC</mnemonic><unit>us/ft</unit></logCurveInfo>
    <logData>
      <data>1000.0,45.0,90.0</data>
      <data>1005.0,55.0,95.0</data>
      <data>1010.0,70.0,100.0</data>
    </logData>
  </log>
</WITSMLComposite>
""",
        encoding="utf-8",
    )


def _service(tmp_path: Path) -> DataCatalogService:
    project_path = tmp_path / "P.paleo.json"
    project_path.write_text("{}", encoding="utf-8")
    return DataCatalogService.open(project_path)


def test_predict_payload_uses_the_selected_model_schema_only():
    payload = build_single_well_payload(
        "HZ27-5-3",
        _well_log(),
        model_version_id="model-gr",
        required_curves=["GR"],
        minimum_rows=2,
        wait_timeout_seconds=30,
    )

    assert payload == {
        "modelVersionId": "model-gr",
        "waitTimeoutSeconds": 30,
        "wells": [
            {
                "wellName": "HZ27-5-3",
                # The invalid GR sample is excluded and unrelated AC is not sent.
                "rows": [{"深度": 1000.0, "GR": 45.0}, {"深度": 1010.0, "GR": 70.0}],
            }
        ],
    }

    with pytest.raises(GeoVizOnlinePredictionError, match="窗口"):
        build_single_well_payload(
            "HZ27-5-3",
            _well_log(),
            model_version_id="model-gr",
            required_curves=["GR"],
            minimum_rows=128,
        )


def test_response_records_use_midpoint_boundaries_for_adjacent_depth_samples():
    """Per-depth API labels must not become one-metre overlapping bands."""
    records = response_records(
        {
            "predictions": [
                {"depth": 1000.0, "label": "分流间湾", "confidence": 0.51},
                {"depth": 1000.125, "label": "分流河道", "confidence": 0.43},
                {"depth": 1000.25, "label": "分流间湾", "confidence": 0.52},
            ]
        }
    )

    assert [(item["top"], item["bottom"]) for item in records] == [
        (999.9375, 1000.0625),
        (1000.0625, 1000.1875),
        (1000.1875, 1000.3125),
    ]


def test_authenticated_prediction_discovers_schema_then_polls_202(monkeypatch):
    import paleo_workbench.prediction.geoviz_online as client

    calls: list[tuple[str, str, dict | None]] = []

    class _Response:
        def __init__(self, status: int, body: dict):
            self.status = status
            self._body = body

        def read(self):
            return json.dumps(self._body).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def _urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8")) if request.data else None
        calls.append((request.full_url, request.get_method(), body))
        assert request.get_header("X-api-key") == "ak_test"
        if request.full_url.endswith("/models"):
            return _Response(
                200,
                {
                    "total": 1,
                    "models": [
                        {
                            "id": "model-gr",
                            "name": "珠海组 GR 模型",
                            "version": "v1",
                            "algorithm": "tcn_bilstm_markov",
                            "inputSchema": {"curves": ["GR"], "window": 2},
                        }
                    ],
                },
            )
        if request.full_url.endswith("/predict"):
            assert body == {
                "modelVersionId": "model-gr",
                "waitTimeoutSeconds": 30,
                "wells": [
                    {
                        "wellName": "HZ27-5-3",
                        "rows": [
                            {"深度": 1000.0, "GR": 45.0},
                            {"深度": 1010.0, "GR": 70.0},
                        ],
                    }
                ],
            }
            return _Response(
                202,
                {
                    "jobId": "job-1",
                    "status": "predicting",
                    "pollAfterMs": 1,
                    "pollUrl": "/api/v1/predictions/job-1",
                },
            )
        assert request.full_url.endswith("/api/v1/predictions/job-1")
        return _Response(
            200,
            {
                "jobId": "job-1",
                "status": "completed",
                "model": {"id": "model-gr", "name": "珠海组 GR 模型", "version": "v1"},
                "summary": {"meanConfidence": 0.87},
                "predictions": [
                    {"wellName": "HZ27-5-3", "depth": 1000.0, "label": "河道砂体", "confidence": 0.87}
                ],
            },
        )

    monkeypatch.setattr(client, "urlopen", _urlopen)
    monkeypatch.setattr(client.time, "sleep", lambda _seconds: None)
    result = run_single_well_prediction(
        "HZ27-5-3",
        _well_log(),
        api_key="ak_test",
        base_url="http://inference.test/api/v1",
        model_version_id="model-gr",
        wait_timeout_seconds=30,
        poll_timeout_seconds=10,
    )

    assert [method for _url, method, _body in calls] == ["GET", "POST", "GET"]
    assert result["endpoint"] == "http://inference.test/api/v1"
    assert result["remote_model_version"] == "model-gr"
    assert result["request_row_count"] == 2
    assert result["predicted_regions"] == [
        {
            "region_id": "inference_api_1",
            "top": 999.5,
            "bottom": 1000.5,
            "facies": "河道砂体",
            "probability": 0.87,
        }
    ]


@pytest.mark.parametrize(
    ("suffix", "writer"),
    (("las", _write_gr_las), ("xml", _write_gr_xml)),
)
def test_authenticated_provider_persists_mocked_online_result(
    tmp_path, monkeypatch, suffix, writer
):
    service = _service(tmp_path)
    try:
        path = tmp_path / f"HZ27-5-3.{suffix}"
        writer(path)
        project = ProjectDocument.new("P")
        resource = ResourceItem(
            id="well-1",
            name=path.name,
            path=str(path),
            type="well_log",
            format=suffix,
        )
        project.resources.append(resource)
        service.migrate_legacy_resources(project.resources)
        model_version = ensure_geoviz_online_model(service)
        monkeypatch.setenv("PALEO_GEOVIZ_API_KEY", "ak_test")
        captured = {}

        def _fake_online(well_name, well_log, **kwargs):
            captured.update(
                well_name=well_name,
                curves=[curve.name for curve in well_log.curves],
                **kwargs,
            )
            return {
                "endpoint": kwargs["base_url"],
                "request_row_count": 3,
                "remote_model_version": "model-gr",
                "remote_model_name": "珠海组 GR 模型",
                "api_summary": {
                    "meanConfidence": 0.87,
                    "formationGroup": "珠海组",
                    "classCounts": {"分流间湾": 2, "分流河道": 1},
                },
                "predicted_regions": [
                    {
                        "region_id": "inference_api_1",
                        "top": 999.5,
                        "bottom": 1000.5,
                        "facies": "河道砂体",
                        "probability": 0.87,
                    }
                ],
            }

        monkeypatch.setattr(
            "paleo_workbench.prediction.geoviz_online.run_single_well_prediction",
            _fake_online,
        )
        input_ids = resolve_inputs_for_model(
            project, service, model_version.id, resource_ids=[resource.id]
        )
        run = start_inference(
            service,
            model_version_id=model_version.id,
            input_version_ids=input_ids,
            parameters={
                "online_endpoint": "http://inference.test/api/v1",
                "online_model_version_id": "model-gr",
            },
        )
        payload = execute_run(service, run.id)

        assert payload["run"].status == "complete"
        assert payload["model"].model_id == MODEL_ID_GEOVIZ_ONLINE
        assert payload["result"]["adapter_kind"] == "http"
        assert captured["api_key"] == "ak_test"
        assert captured["base_url"] == "http://inference.test/api/v1"
        assert captured["model_version_id"] == "model-gr"
        assert captured["curves"] == ["GR", "AC"]
        summary = payload["result"]["result_summary"]
        assert summary["model_type"] == "inference_api_online"
        assert summary["source"] == "inference_service_online"
        assert summary["remote_model_version"] == "model-gr"
        assert summary["remote_summary"]["classCounts"] == {
            "分流间湾": 2,
            "分流河道": 1,
        }
        assert payload["run"].output_version_ids
        assert "ak_test" not in str(payload["run"].parameters)
    finally:
        service.close()


def test_authenticated_provider_persists_postprocessed_regions_with_top_boundaries(
    tmp_path, monkeypatch
):
    service = _service(tmp_path)
    try:
        path = tmp_path / "A17.las"
        _write_gr_las(path)
        tops_path = tmp_path / "DC.dat"
        tops_path.write_text(
            "\n".join(
                [
                    "#WellName Name MD X Y Z TVD Time(ms)",
                    "HZ27-5-3 珠海组 1001.0 0 0 0 1001.0 0",
                ]
            ),
            encoding="utf-8",
        )
        project = ProjectDocument.new("P")
        resource = ResourceItem(
            id="well-1",
            name=path.name,
            path=str(path),
            type="well_log",
            format="las",
        )
        project.resources.extend(
            (
                resource,
                ResourceItem(
                    id="tops-1",
                    name=tops_path.name,
                    path=str(tops_path),
                    type="well_stratification",
                    format="dat",
                ),
            )
        )
        service.migrate_legacy_resources(project.resources)
        model_version = ensure_geoviz_online_model(service)
        monkeypatch.setenv("PALEO_GEOVIZ_API_KEY", "ak_test")
        monkeypatch.setattr(
            "paleo_workbench.prediction.geoviz_online.run_single_well_prediction",
            lambda *_args, **kwargs: {
                "endpoint": kwargs["base_url"],
                "request_row_count": 3,
                "remote_model_version": "model-gr",
                "remote_model_name": "珠海组 GR 模型",
                "api_summary": {},
                "predicted_regions": [
                    {
                        "region_id": "inference_api_1",
                        "top": 1000.0,
                        "bottom": 1001.0,
                        "facies": "分流间湾",
                        "probability": 0.531,
                    },
                    {
                        "region_id": "inference_api_2",
                        "top": 1001.0,
                        "bottom": 1002.0,
                        "facies": "分流间湾",
                        "probability": 0.534,
                    },
                    {
                        "region_id": "inference_api_3",
                        "top": 1002.0,
                        "bottom": 1003.0,
                        "facies": "分流间湾",
                        "probability": 0.532,
                    },
                ],
            },
        )
        input_ids = resolve_inputs_for_model(
            project, service, model_version.id, resource_ids=[resource.id]
        )
        input_ids.extend(resolve_prediction_postprocess_inputs(project, service))
        run = start_inference(
            service,
            model_version_id=model_version.id,
            input_version_ids=input_ids,
            parameters={"online_endpoint": "http://inference.test/api/v1"},
        )

        payload = execute_run(service, run.id)

        assert payload["run"].status == "complete"
        summary = payload["result"]["result_summary"]
        assert [(item["top"], item["bottom"]) for item in summary["predicted_regions"]] == [
            (1000.0, 1001.0),
            (1001.0, 1003.0),
        ]
        assert summary["postprocess"]["formation_boundary_count"] == 1
        assert summary["postprocess"]["raw_region_count"] == 3
        assert summary["postprocess"]["postprocessed_region_count"] == 2
        assert summary["predicted_regions"][1]["stratigraphic_unit"] == "珠海组"
    finally:
        service.close()
