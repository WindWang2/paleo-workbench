from pathlib import Path

from geoviz import ErrorCode, GeoVizError, PreparedPreview, PreviewKind, PreviewOptions, PreviewRequest

from paleo_workbench.project.models import ResourceItem


def _las_resource(path: Path) -> ResourceItem:
    path.write_text(
        "\n".join(
            [
                "~VERSION INFORMATION",
                " VERS. 2.0:",
                " WRAP. NO:",
                "~WELL INFORMATION",
                " STRT.M 0.0:",
                " STOP.M 1.0:",
                " STEP.M 1.0:",
                " NULL. -999.25:",
                " WELL. TEST:",
                "~CURVE INFORMATION",
                " DEPT.M : Depth",
                " GR.GAPI : Gamma Ray",
                "~ASCII",
                "0.0 10.0",
                "1.0 20.0",
            ]
        ),
        encoding="utf-8",
    )
    return ResourceItem(
        id="res-well-1",
        name="well.las",
        path=str(path),
        type="well_log",
        format="las",
        status="parsed",
    )


class RecordingEngine:
    def __init__(self, *, supported: bool = True, failure: GeoVizError | None = None) -> None:
        self.supported = supported
        self.failure = failure
        self.support_requests: list[PreviewRequest] = []
        self.prepare_calls: list[tuple[PreviewRequest, PreviewOptions]] = []
        self.prepared = PreparedPreview(
            kind=PreviewKind.WELL_LOG,
            title="Professional well",
            payload={"depth": (0.0, 1.0), "curves": {"GR": (10.0, 20.0)}},
            summary_rows=(("井名", "TEST"),),
            warning="engine warning",
            estimated_bytes=512,
        )

    def supports(self, request: PreviewRequest) -> bool:
        self.support_requests.append(request)
        return self.supported

    def prepare(self, request: PreviewRequest, options: PreviewOptions) -> PreparedPreview:
        if not self.supported:
            raise GeoVizError(ErrorCode.UNSUPPORTED, "unsupported")
        self.prepare_calls.append((request, options))
        if self.failure is not None:
            raise self.failure
        return self.prepared


def test_provider_maps_resource_to_facade_request_and_returns_prepared_preview(tmp_path: Path):
    from paleo_workbench.ui.pages.geoviz_preview_provider import LocalVisualizationProvider

    resource = _las_resource(tmp_path / "well.las")
    engine = RecordingEngine()

    result = LocalVisualizationProvider(engine).preview(resource)

    request = engine.support_requests[0]
    stat = Path(resource.path).stat()
    assert request == PreviewRequest(
        resource_id=resource.id,
        path=resource.path,
        semantic_type=resource.type,
        format=resource.format,
        label=resource.name,
        source_version=f"stat:{stat.st_size}:{stat.st_mtime_ns}",
    )
    assert type(request) is PreviewRequest
    assert engine.prepare_calls == [(request, PreviewOptions.local())]
    assert result.mode == "geoviz"
    assert result.engine_preview is engine.prepared
    assert result.estimated_bytes == 512
    assert result.summary_rows == (("井名", "TEST"),)
    assert not hasattr(result, "widget")
    assert not hasattr(result, "file_handle")


def test_resource_request_carries_versioned_source_coordinate_metadata(
    tmp_path: Path,
):
    from paleo_workbench.ui.pages.geoviz_preview_provider import (
        request_from_resource,
    )

    path = tmp_path / "wells.dat"
    path.write_text("well data", encoding="utf-8")
    resource = ResourceItem(
        id="well-head-1",
        name="wells.dat",
        path=str(path),
        type="well_head",
        format="dat",
        checksum="abc123",
        crs="EPSG:32648",
        parsed_summary={
            "coordinate_units": "m",
            "comparison_crs": "EPSG:4326",
        },
    )

    request = request_from_resource(resource)

    assert request.source_version == "checksum:abc123"
    assert request.source_crs == "EPSG:32648"
    assert request.coordinate_units == "m"
    assert request.comparison_crs == "EPSG:4326"


def test_provider_prefers_project_crs_as_the_explicit_comparison_context(
    tmp_path: Path,
):
    from paleo_workbench.ui.pages.geoviz_preview_provider import (
        LocalVisualizationProvider,
    )

    resource = _las_resource(tmp_path / "well.las")
    resource.parsed_summary["comparison_crs"] = "EPSG:4326"
    engine = RecordingEngine()

    LocalVisualizationProvider(
        engine,
        comparison_crs="EPSG:3857",
    ).preview(resource)

    assert engine.support_requests[0].comparison_crs == "EPSG:3857"


def test_geoviz_error_falls_back_to_las_summary_and_merges_warning(tmp_path: Path):
    from paleo_workbench.ui.pages.geoviz_preview_provider import LocalVisualizationProvider

    resource = _las_resource(tmp_path / "well.las")
    engine = RecordingEngine(
        failure=GeoVizError(ErrorCode.INVALID_DATA, "专业预览数据无效")
    )

    result = LocalVisualizationProvider(engine).preview(resource)

    assert result.mode == "well_log"
    assert ("井名", "TEST") in result.summary_rows
    assert "专业预览数据无效" in result.warning


def test_unsupported_resource_uses_ordinary_reader_without_preparing(tmp_path: Path):
    from paleo_workbench.ui.pages.geoviz_preview_provider import LocalVisualizationProvider

    path = tmp_path / "notes.txt"
    path.write_text("ordinary reader", encoding="utf-8")
    resource = ResourceItem(
        name="notes.txt",
        path=str(path),
        type="document",
        format="txt",
    )
    engine = RecordingEngine(supported=False)

    result = LocalVisualizationProvider(engine).preview(resource)

    assert result.mode == "text"
    assert result.text == "ordinary reader"
    assert engine.prepare_calls == []


def test_summary_probe_marks_visualization_without_preparing(tmp_path: Path):
    from paleo_workbench.ui.pages.geoviz_preview_provider import LocalVisualizationProvider

    resource = _las_resource(tmp_path / "well.las")
    engine = RecordingEngine()

    result = LocalVisualizationProvider(engine).preview_summary(resource)

    assert result.mode == "well_log"
    assert result.visualization_available is True
    assert result.table_headers == ("曲线", "单位", "描述")
    assert engine.support_requests
    assert engine.prepare_calls == []


def test_visualization_request_prepares_only_on_explicit_call(tmp_path: Path):
    from paleo_workbench.ui.pages.geoviz_preview_provider import LocalVisualizationProvider

    resource = _las_resource(tmp_path / "well.las")
    engine = RecordingEngine()
    provider = LocalVisualizationProvider(engine)

    result = provider.preview_visualization(resource)

    assert result.mode == "geoviz"
    assert result.engine_preview is engine.prepared
    assert len(engine.prepare_calls) == 1
    assert engine.support_requests == []


def test_visualization_request_returns_stable_message_when_unsupported(tmp_path: Path):
    from paleo_workbench.ui.pages.geoviz_preview_provider import LocalVisualizationProvider

    path = tmp_path / "notes.txt"
    path.write_text("ordinary reader", encoding="utf-8")
    resource = ResourceItem(
        name=path.name,
        path=str(path),
        type="document",
        format="txt",
    )
    engine = RecordingEngine(supported=False)

    result = LocalVisualizationProvider(engine).preview_visualization(resource)

    assert result.mode == "message"
    assert result.message == "此数据不支持可视化预览"
    assert engine.prepare_calls == []


def test_visualization_engine_failure_returns_noncacheable_retry_result(tmp_path: Path):
    from paleo_workbench.ui.pages.geoviz_preview_provider import LocalVisualizationProvider

    resource = _las_resource(tmp_path / "well.las")
    engine = RecordingEngine(
        failure=GeoVizError(ErrorCode.IO_ERROR, "LAS暂时被占用")
    )

    result = LocalVisualizationProvider(engine).preview_visualization(resource)

    assert result.mode == "message"
    assert result.cacheable is False
    assert result.retryable is True
    assert result.message == "LAS暂时被占用"
    assert "LAS暂时被占用" in result.warning


def test_visualization_invalid_data_failure_is_not_retryable(tmp_path: Path):
    from paleo_workbench.ui.pages.geoviz_preview_provider import LocalVisualizationProvider

    resource = _las_resource(tmp_path / "well.las")
    engine = RecordingEngine(
        failure=GeoVizError(ErrorCode.INVALID_DATA, "LAS曲线无效")
    )

    result = LocalVisualizationProvider(engine).preview_visualization(resource)

    assert result.mode == "message"
    assert result.cacheable is False
    assert result.retryable is False
    assert result.message == "LAS曲线无效"


def test_visualization_failure_preserves_specific_engine_detail(tmp_path: Path):
    from paleo_workbench.ui.pages.geoviz_preview_provider import (
        LocalVisualizationProvider,
    )

    resource = _las_resource(tmp_path / "well.las")
    engine = RecordingEngine(
        failure=GeoVizError(
            ErrorCode.INVALID_DATA,
            "DAT 数据结构与资源类型不匹配",
            detail="missing required Name/X/Y columns",
        )
    )

    result = LocalVisualizationProvider(engine).preview_visualization(resource)

    assert result.mode == "message"
    assert result.message == "missing required Name/X/Y columns"
    assert "missing required Name/X/Y columns" in result.warning
