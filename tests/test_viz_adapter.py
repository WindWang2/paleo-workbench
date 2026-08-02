from pathlib import Path

from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument, ResourceItem
from paleo_workbench.viz.adapter import VizAdapter
from paleo_workbench.viz.well_log_load import load_well_log_from_path


def _minimal_las(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "~VERSION INFORMATION",
                " VERS. 2.0:",
                " WRAP. NO:",
                "~WELL INFORMATION",
                " STRT.M 0.0:",
                " STOP.M 10.0:",
                " STEP.M 1.0:",
                " NULL. -999.25:",
                " WELL. TEST:",
                "~CURVE INFORMATION",
                " DEPT.M :",
                " GR.GAPI :",
                "~ASCII",
                "0.0 10.0",
                "1.0 20.0",
                "2.0 30.0",
            ]
        ),
        encoding="utf-8",
    )


def test_supports_resource_kinds():
    adapter = VizAdapter()
    las = ResourceItem(name="a.las", path="/x/a.las", type="well_log", format="las")
    sgy = ResourceItem(name="b.sgy", path="/x/b.sgy", type="seismic", format="sgy")
    txt = ResourceItem(name="c.txt", path="/x/c.txt", type="document", format="txt")
    assert adapter.supports_resource(las) is True
    assert adapter.supports_resource(sgy) is True
    assert adapter.supports_resource(txt) is False


def test_load_well_log_from_minimal_las(tmp_path: Path):
    path = tmp_path / "w.las"
    _minimal_las(path)
    data = load_well_log_from_path(str(path))
    assert data is not None
    assert data.well_name
    assert data.curves
    assert len(data.curves[0].depth) >= 2


def test_resolve_missing_las_returns_message():
    project = ProjectDocument.new("P")
    res = ResourceItem(
        name="missing.las",
        path="/no/such/missing.las",
        type="well_log",
        format="las",
        status="missing",
    )
    project.resources.append(res)
    adapter = VizAdapter()
    ref = adapter.ref_from_resource(res)
    assert ref is not None
    payload = adapter.resolve(ref, project)
    assert payload.kind == "message"
    assert payload.message


def test_resolve_map_document():
    project = ProjectDocument.new("P")
    doc = PaleoMapDocument(
        name="M1",
        linked_target_horizon="H1",
        facies_polygons=[{
            "id": "f1",
            "name": "A",
            "coordinates": [[0, 0], [1, 0], [1, 1], [0, 0]],
        }],
        well_overlays=[{"name": "W1", "x": 0.5, "y": 0.5}],
    )
    project.paleomap_documents.append(doc)
    adapter = VizAdapter()
    ref = adapter.ref_from_map_document(doc)
    payload = adapter.resolve(ref, project)
    assert payload.kind == "map"
    assert payload.map_features
    assert payload.period_name == "H1"
    assert payload.map_wells


def test_from_prediction_still_works():
    from paleo_workbench.project.models import PredictionTask

    task = PredictionTask(name="T1", seed=1, result_summary={
        "predicted_regions": [{"facies": "砂", "probability": 0.8}],
    })
    payload = VizAdapter().from_prediction(task)
    assert payload.kind in {"well_log", "prediction"}
    assert payload.well_log is not None
    # Dual payload: well tab + seismic volume for composite tabs
    assert payload.seismic_volume is not None


def test_from_prediction_soft_fails_on_helper_error(monkeypatch):
    from paleo_workbench.project.models import PredictionTask
    import paleo_workbench.viz.prediction_helpers as prediction_helpers

    def _boom(_task):
        raise RuntimeError("mock converter broken")

    # Patch module object directly: pages package lazy __getattr__ breaks dotted path.
    monkeypatch.setattr(prediction_helpers, "well_log_data_from_prediction", _boom)
    task = PredictionTask(name="T-fail", seed=1)
    payload = VizAdapter().from_prediction(task)
    assert payload.kind == "message"
    assert "预测可视化失败" in (payload.message or "")


def test_resolve_las_success(tmp_path: Path):
    path = tmp_path / "ok.las"
    _minimal_las(path)
    project = ProjectDocument.new("P")
    res = ResourceItem(name="ok.las", path=str(path), type="well_log", format="las")
    project.resources.append(res)
    adapter = VizAdapter()
    ref = adapter.ref_from_resource(res)
    assert ref is not None
    payload = adapter.resolve(ref, project)
    assert payload.kind == "well_log"
    assert payload.well_log is not None
    assert payload.well_log.curves


def test_resolve_seismic_defers_parse_to_engine_worker(monkeypatch, tmp_path: Path):
    path = tmp_path / "cube.sgy"
    path.write_bytes(b"not-a-real-segy")
    monkeypatch.setattr(
        "paleo_workbench.viz.adapter.load_seismic_volume_from_path",
        lambda _path: (_ for _ in ()).throw(
            AssertionError("adapter must not parse SEGY synchronously")
        ),
        raising=False,
    )
    project = ProjectDocument.new("P")
    res = ResourceItem(name="cube.sgy", path=str(path), type="seismic", format="sgy")
    project.resources.append(res)
    adapter = VizAdapter()
    ref = adapter.ref_from_resource(res)
    assert ref is not None
    payload = adapter.resolve(ref, project)
    assert payload.kind == "seismic"
    assert payload.seismic_volume is None
    assert payload.seismic_path == str(path)
    assert payload.warning


def test_ref_from_resource_unsupported_returns_none():
    adapter = VizAdapter()
    res = ResourceItem(name="c.txt", path="/x/c.txt", type="document", format="txt")
    assert adapter.ref_from_resource(res) is None


def test_engine_preview_uses_shared_version_and_coordinate_request_rules(
    tmp_path: Path,
):
    path = tmp_path / "wells.dat"
    path.write_text(
        "#WellHead File From SMI\n#Name X Y\nA1 10 20\n",
        encoding="utf-8",
    )
    project = ProjectDocument.new("P")
    resource = ResourceItem(
        name="wells.dat",
        path=str(path),
        type="well_head",
        format="dat",
        checksum="abc123",
        crs="EPSG:32648",
        parsed_summary={"coordinate_units": "m"},
    )
    project.resources.append(resource)
    ref = VizAdapter().ref_from_resource(resource)
    assert ref is not None

    payload = VizAdapter().resolve(ref, project)

    assert payload.kind == "engine_preview"
    stat = path.stat()
    assert payload.prepared.payload.source_version == (
        f"checksum:abc123|stat:{stat.st_size}:{stat.st_mtime_ns}"
    )
    assert payload.prepared.payload.source_crs == "EPSG:32648"
    assert payload.prepared.payload.coordinate_units == "m"
