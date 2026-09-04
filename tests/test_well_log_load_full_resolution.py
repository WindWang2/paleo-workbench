"""#1193 — full-resolution well-log loading for ML paths.

The production preview loader decimates any well with more rows than
``PREVIEW_MAX_SAMPLES`` (min-max binning). That is correct for rendering and
dishonest for scientific/ML inference: this batch pins

- the preview loader's decimation is REPORTED (original vs returned count),
- a full-resolution loader that keeps every sample,
- separate caches so a preview document is never served as full resolution,
- the online ML provider consuming full resolution and declaring it.
"""

from __future__ import annotations

from pathlib import Path

from paleo_workbench.viz.well_log_load import (
    FULL_RESOLUTION_MAX_SAMPLES,
    PREVIEW_MAX_SAMPLES,
    load_well_log_full_resolution,
    load_well_log_from_path,
    well_log_decimation_info,
)

BIG_ROWS = 120_000  # > PREVIEW_MAX_SAMPLES → preview must decimate


def _write_las(path: Path, rows: int) -> Path:
    lines = [
        "~VERSION INFORMATION",
        " VERS. 2.0:",
        " WRAP. NO:",
        "~WELL INFORMATION",
        " WELL. BIG-1:",
        " NULL. -999.25:",
        "~CURVE INFORMATION",
        " DEPT.M :",
        " GR.GAPI :",
        "~ASCII",
    ]
    lines.extend(f"{1000.0 + i * 0.125:.3f} {30.0 + (i % 97) * 0.5:.2f}" for i in range(rows))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _sample_count(well_log) -> int:
    curves = list(getattr(well_log, "curves", None) or [])
    assert curves, "loaded document must carry curves"
    return len(list(curves[0].depth))


def test_preview_loader_decimates_big_well_and_reports_it(tmp_path: Path):
    path = _write_las(tmp_path / "big.las", BIG_ROWS)

    preview = load_well_log_from_path(str(path))
    assert preview is not None
    returned = _sample_count(preview)
    assert returned <= PREVIEW_MAX_SAMPLES
    assert returned < BIG_ROWS  # decimation actually engaged

    info = well_log_decimation_info(str(path), preview)
    assert info is not None
    assert info.decimated is True
    assert info.loader == "preview"
    assert info.original_row_count == BIG_ROWS
    assert info.returned_sample_count == returned
    assert info.sample_stride == 2  # ceil(120000 / 100000)


def test_full_resolution_loader_keeps_every_sample(tmp_path: Path):
    path = _write_las(tmp_path / "big.las", BIG_ROWS)

    full = load_well_log_full_resolution(str(path))
    assert full is not None
    assert _sample_count(full) == BIG_ROWS

    info = well_log_decimation_info(
        str(path),
        full,
        loader="full_resolution",
        max_samples=FULL_RESOLUTION_MAX_SAMPLES,
    )
    assert info is not None
    assert info.decimated is False
    assert info.original_row_count == BIG_ROWS
    assert info.returned_sample_count == BIG_ROWS
    assert info.sample_stride == 1


def test_preview_loader_unchanged_below_bound(tmp_path: Path):
    path = _write_las(tmp_path / "small.las", 500)

    preview = load_well_log_from_path(str(path))
    assert preview is not None
    assert _sample_count(preview) == 500
    info = well_log_decimation_info(str(path), preview)
    assert info is not None
    assert info.decimated is False
    assert info.original_row_count == 500
    assert info.sample_stride == 1

    full = load_well_log_full_resolution(str(path))
    assert full is not None
    assert _sample_count(full) == 500


def test_full_resolution_is_never_served_from_preview_cache(tmp_path: Path):
    """Cache keys are (path, mtime): sharing a cache would hand the ML path
    the decimated preview document cached by a render load (#1193)."""
    import paleo_workbench.viz.well_log_load as mod

    path = _write_las(tmp_path / "big.las", BIG_ROWS)

    preview = load_well_log_from_path(str(path))
    assert preview is not None
    assert _sample_count(preview) <= PREVIEW_MAX_SAMPLES

    full = load_well_log_full_resolution(str(path))
    assert full is not None
    assert _sample_count(full) == BIG_ROWS

    # The two documents coexist in separate caches.
    assert mod._las_cache is not mod._full_res_cache


def test_online_ml_provider_uses_full_resolution_and_declares_it(
    tmp_path: Path, monkeypatch
):
    """The GeoVizOnlineProvider must not send a decimated preview to the
    remote model, and its payload must declare the data resolution."""
    from paleo_workbench.catalog.service import DataCatalogService
    from paleo_workbench.prediction.inference_service import (
        execute_run,
        resolve_inputs_for_model,
        start_inference,
    )
    from paleo_workbench.prediction.providers import (
        ensure_geoviz_online_model,
    )
    from paleo_workbench.project.models import ProjectDocument, ResourceItem

    project_path = tmp_path / "P.paleo.json"
    project_path.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_path)
    try:
        path = _write_las(tmp_path / "ML.las", BIG_ROWS)
        project = ProjectDocument.new("P")
        resource = ResourceItem(
            id="well-1", name=path.name, path=str(path), type="well_log", format="las"
        )
        project.resources.append(resource)
        service.migrate_legacy_resources(project.resources)
        model_version = ensure_geoviz_online_model(service)
        monkeypatch.setenv("PALEO_GEOVIZ_API_KEY", "ak_test")
        monkeypatch.setenv("PALEO_GEOVIZ_ONLINE_BASE_URL", "https://inference.test/api/v1")
        captured = {}

        def _fake_online(well_name, well_log, **kwargs):
            captured["row_count"] = _sample_count(well_log)
            captured["kwargs"] = kwargs
            return {
                "endpoint": kwargs["base_url"],
                "request_row_count": captured["row_count"],
                "remote_model_version": "model-gr",
                "remote_model_name": "GR 模型",
                "api_summary": {},
                "predicted_regions": [
                    {
                        "region_id": "inference_api_1",
                        "top": 1000.0,
                        "bottom": 15000.0,
                        "facies": "分流河道",
                        "probability": 0.8,
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
        run = start_inference(service, model_version_id=model_version.id,
                              input_version_ids=input_ids)
        out = execute_run(service, run.id)

        assert out["run"].status == "complete"
        # Every sample went to the model — not a 100k-capped preview.
        assert captured["row_count"] == BIG_ROWS
        resolution = out["result"]["result_summary"]["data_resolution"]
        assert resolution["loader"] == "full_resolution"
        assert resolution["decimated"] is False
        assert resolution["original_row_count"] == BIG_ROWS
        assert resolution["returned_sample_count"] == BIG_ROWS
        assert resolution["sample_stride"] == 1
        assert resolution["sent_row_count"] == BIG_ROWS
    finally:
        service.close()


def test_full_resolution_cache_capacity_is_minimal():
    """V4: full-resolution documents can carry millions of rows × dozens of
    curves and the cache bounds by ENTRY COUNT only — capacity stays at 2
    (current + previous well for the sequential ML path), never the preview
    cache's 16."""
    from paleo_workbench.viz import well_log_load

    assert well_log_load._FULL_RES_CACHE_SIZE == 2
    assert well_log_load._full_res_cache.max_entries == 2
    # The preview cache is unaffected.
    assert well_log_load._las_cache.max_entries == well_log_load._MAX_CACHE_SIZE
