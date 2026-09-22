"""I1 — adapter contract, registry and content sniffing."""

from __future__ import annotations

import pytest

from paleo_workbench.interchange.contracts import (
    ExportVerification,
    FormatCapability,
    ImportPlan,
    VerificationCheck,
    VerificationState,
)
from paleo_workbench.interchange.registry import (
    FormatAdapter,
    InterchangeRegistry,
    sniff_format,
)

from tests import interchange_fixtures as fx


class _DemoAdapter(FormatAdapter):
    format_id = "demo"
    display_name = "demo"
    extensions = ("demo",)

    def capability(self):
        return FormatCapability()

    def inspect(self, path):
        raise NotImplementedError


def test_registry_rejects_duplicate_and_blank_ids():
    registry = InterchangeRegistry()
    registry.register(_DemoAdapter())
    with pytest.raises(ValueError):
        registry.register(_DemoAdapter())
    registry.register(_DemoAdapter(), replace=True)  # replace is allowed

    class _Blank(FormatAdapter):
        format_id = ""
        extensions = ("x",)

        def capability(self):
            return FormatCapability()

        def inspect(self, path):
            raise NotImplementedError

    with pytest.raises(ValueError):
        registry.register(_Blank())


def test_default_registry_has_expected_formats():
    from paleo_workbench.interchange.adapters import build_default_registry

    registry = build_default_registry()
    ids = {a.format_id for a in registry.adapters()}
    assert {
        "las", "csv", "tsv", "xlsx", "geojson", "vector_gdal",
        "raster", "segy", "flac3d_f3grid", "abaqus_inp",
        "dlis", "vtk_model", "mesh_exchange",
    } <= ids
    matrix = registry.capability_matrix()
    by_id = {row["format_id"]: row for row in matrix}
    # honest unavailability: DLIS/VTK/OBJ/STL and SEG-Y export
    assert by_id["dlis"]["import"] is False
    assert by_id["vtk_model"]["read"] is False
    assert by_id["segy"]["export"] is False
    # unavailable adapters still inspect (reporting unavailability)
    assert by_id["dlis"]["inspect"] is False


def test_sniff_las_by_content_not_extension(tmp_path):
    las = fx.write_valid_las(tmp_path / "ok.las")
    sniff = sniff_format(las)
    assert sniff.format_id == "las"
    assert sniff.confidence == "high"

    # LAS bytes under a wrong extension must still sniff as LAS (high),
    # and never be classified by extension alone.
    masquerade = fx.write_valid_las(tmp_path / "image.las.txt")
    sniff2 = sniff_format(masquerade)
    assert sniff2.format_id == "las"


def test_sniff_geotiff_gpkg_and_segy(tmp_path):
    if fx.geotiff_available():
        tif = fx.write_geotiff(tmp_path / "raster.tif")
        sniff = sniff_format(tif)
        assert sniff.format_id == "geotiff"
        # wrong extension still detected by magic
        weird = tmp_path / "raster.bin"
        weird.write_bytes(tif.read_bytes())
        assert sniff_format(weird).format_id == "geotiff"

    segy = fx.write_tiny_segy(tmp_path / "tiny.segy")
    sniff = sniff_format(segy)
    assert sniff.format_id == "segy"

    # GeoJSON feature collection
    gj = fx.write_geojson(tmp_path / "a.geojson")
    assert sniff_format(gj).format_id == "geojson"


def test_sniff_unknown_file_is_empty_not_guess(tmp_path):
    mystery = tmp_path / "mystery.bin"
    mystery.write_bytes(bytes(range(256)) * 4)
    sniff = sniff_format(mystery)
    assert not sniff.determined


def test_import_plan_roundtrip_serializable():
    plan = ImportPlan(
        format_id="las",
        source_path="/data/w.las",
        action="managed_copy",
        asset_name="w",
        warnings=["w1"],
        estimated_bytes=10,
        metadata={"well_name": "W"},
    )
    payload = plan.to_dict()
    revived = ImportPlan.from_dict(payload)
    assert revived == plan


def test_verification_states_never_confuse_unverified():
    unverified = ExportVerification.unverified("nothing to check")
    assert unverified.state is VerificationState.UNVERIFIED
    assert unverified.summary()["state"] == "UNVERIFIED"
    # UNVERIFIED is not ok() and must not render as verified
    assert unverified.ok is False
    failed = ExportVerification.failed([VerificationCheck("x", False)])
    assert failed.state is VerificationState.FAILED
