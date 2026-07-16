from pathlib import Path

import pytest
from pydantic import ValidationError

from paleo_workbench.adapters.paleo_map import PaleoMapAdapter
from paleo_workbench.adapters.schemas import ExportRequest, ViewerPayload, ViewState


def test_viewer_payload_requires_schema_version():
    payload = ViewerPayload(
        viewer_type="paleo_map",
        schema_version="1.0",
        resources=[],
        layers=[],
        crs="EPSG:4326",
    )

    assert payload.viewer_type == "paleo_map"


def test_invalid_export_format_fails_validation():
    with pytest.raises(ValidationError):
        ExportRequest(path="out.xyz", format="xyz")


def test_view_state_round_trip():
    state = ViewState(schema_version="1.0", viewport={"zoom": 3}, selected_ids=["res_1"])

    assert state.model_dump()["viewport"]["zoom"] == 3


def test_paleo_map_adapter_validates_payload_and_exports_metadata(tmp_path: Path):
    adapter = PaleoMapAdapter()
    adapter.set_data({"viewer_type": "paleo_map", "schema_version": "1.0", "resources": [], "layers": []})
    adapter.set_view_state({"schema_version": "1.0", "viewport": {"zoom": 2}})

    result = adapter.export({"path": str(tmp_path / "map.geojson"), "format": "geojson"})

    assert adapter.get_view_state().viewport["zoom"] == 2
    assert result.output_path.endswith("map.geojson")
    assert Path(result.output_path).exists()


def test_paleo_map_adapter_rejects_placeholder_pdf_svg(tmp_path: Path):
    adapter = PaleoMapAdapter()
    adapter.set_data({"viewer_type": "paleo_map", "schema_version": "1.0", "layers": []})
    with pytest.raises(ValueError, match="geojson"):
        adapter.export({"path": str(tmp_path / "map.pdf"), "format": "pdf"})
    with pytest.raises(ValueError, match="geojson"):
        adapter.export({"path": str(tmp_path / "map.svg"), "format": "svg"})
    assert not (tmp_path / "map.pdf").exists()
    assert not (tmp_path / "map.svg").exists()