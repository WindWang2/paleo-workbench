from dataclasses import replace
import json
import threading
import time
import zipfile

import pytest
from PySide6.QtCore import QSettings

from geoviz import PreparedPreview, PreviewKind, PreviewOptions

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.geoviz_preview_provider import LocalVisualizationProvider
from paleo_workbench.ui.pages.preview_provider import PreviewProvider
from paleo_workbench.ui.pages.preview_provider import PreviewResult
from paleo_workbench.ui.pages.preview_cache import make_preview_cache_key
from paleo_workbench.ui.pages.preview_disk_cache import (
    PreviewDiskCache,
    _entry_key_material,
)
from paleo_workbench.ui.pages.preview_worker import PreviewRequestController

from paleo_workbench.ui.pages.preview_settings import (
    PreviewSettings,
    PreviewSettingsStore,
)


def test_preview_settings_defaults_match_recommended_profile():
    settings = PreviewSettings.defaults()

    assert settings.font_size == 12
    assert settings.show_metadata is True
    assert settings.text_limit_kib == 256
    assert settings.wrap_text is False
    assert settings.table_max_rows == 200
    assert settings.table_max_columns == 40
    assert settings.auto_fit_columns is True
    assert settings.smooth_images is True
    assert settings.geotiff_thumbnail_px == 256
    assert settings.show_geo_metadata is True
    assert settings.pdf_fit_mode == "width"
    assert settings.pdf_zoom_percent == 100
    assert settings.json_limit_mib == 5
    assert settings.json_array_collapse_threshold == 100
    assert settings.json_expand_depth == 2
    assert settings.media_autoplay is False
    assert settings.media_volume == 70
    assert settings.geoviz_max_curves == 12
    assert settings.geoviz_max_depth_samples == 2_000
    assert settings.geoviz_max_slice_axis == 512
    assert settings.geoviz_max_points == 50_000
    assert settings.geoviz_surface_grid_size == 256


def test_preview_settings_validate_types_ranges_and_pdf_mode():
    with pytest.raises(ValueError, match="font_size"):
        PreviewSettings(font_size=7)
    with pytest.raises(ValueError, match="media_volume"):
        PreviewSettings(media_volume=101)
    with pytest.raises(TypeError, match="media_autoplay"):
        PreviewSettings(media_autoplay=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="pdf_fit_mode"):
        PreviewSettings(pdf_fit_mode="invalid")  # type: ignore[arg-type]


def test_preview_settings_mapping_and_fingerprint_are_stable():
    defaults = PreviewSettings.defaults()
    restored = PreviewSettings.from_mapping(defaults.to_mapping())
    changed = replace(defaults, text_limit_kib=512)

    assert restored == defaults
    assert restored.fingerprint() == defaults.fingerprint()
    assert changed.fingerprint() != defaults.fingerprint()


def test_preview_settings_map_to_geoviz_options():
    settings = replace(
        PreviewSettings.defaults(),
        geoviz_max_curves=8,
        geoviz_max_depth_samples=1_500,
        geoviz_max_slice_axis=384,
        geoviz_max_points=25_000,
        geoviz_surface_grid_size=128,
    )

    options = settings.to_geoviz_options()

    assert options.profile == "local"
    assert options.max_curves == 8
    assert options.max_depth_samples == 1_500
    assert options.max_slice_axis == 384
    assert options.max_points == 25_000
    assert options.surface_grid_size == 128


def test_preview_settings_store_round_trip_and_reset(tmp_path):
    path = tmp_path / "preview-settings.ini"
    backend = QSettings(str(path), QSettings.Format.IniFormat)
    store = PreviewSettingsStore(backend)
    custom = replace(
        PreviewSettings.defaults(),
        font_size=15,
        wrap_text=True,
        media_autoplay=True,
        media_volume=35,
    )

    assert store.load() == PreviewSettings.defaults()
    store.save(custom)

    reopened = PreviewSettingsStore(
        QSettings(str(path), QSettings.Format.IniFormat)
    )
    assert reopened.load() == custom
    assert reopened.reset() == PreviewSettings.defaults()
    assert reopened.load() == PreviewSettings.defaults()


def test_provider_with_settings_creates_an_isolated_snapshot():
    provider = PreviewProvider()
    custom = replace(PreviewSettings.defaults(), text_limit_kib=16)

    configured = provider.with_settings(custom)

    assert configured is not provider
    assert provider.settings == PreviewSettings.defaults()
    assert configured.settings == custom


def test_provider_applies_text_and_table_content_limits(tmp_path):
    text_path = tmp_path / "large.txt"
    text_path.write_text("x" * (20 * 1024), encoding="utf-8")
    table_path = tmp_path / "large.csv"
    table_path.write_text(
        "\n".join(
            [",".join(f"c{i}" for i in range(8))]
            + [",".join(str(i) for i in range(8)) for _ in range(30)]
        ),
        encoding="utf-8",
    )
    settings = replace(
        PreviewSettings.defaults(),
        text_limit_kib=16,
        table_max_rows=20,
        table_max_columns=5,
    )
    provider = PreviewProvider().with_settings(settings)

    text_result = provider.preview(
        ResourceItem(name="large.txt", path=str(text_path), type="document", format="txt")
    )
    table_result = provider.preview(
        ResourceItem(name="large.csv", path=str(table_path), type="tabular", format="csv")
    )

    assert len(text_result.text.encode("utf-8")) == 16 * 1024
    assert text_result.truncated is True
    assert "16 KiB" in text_result.warning
    assert len(table_result.table_headers) == 5
    assert len(table_result.table_rows) == 20
    assert all(len(row) == 5 for row in table_result.table_rows)
    assert table_result.truncated is True


def test_provider_rejects_json_above_configured_limit_without_full_read(tmp_path, monkeypatch):
    path = tmp_path / "large.json"
    path.write_text(json.dumps({"data": "x" * (1024 * 1024)}), encoding="utf-8")
    resource = ResourceItem(name=path.name, path=str(path), type="document", format="json")
    provider = PreviewProvider().with_settings(
        replace(PreviewSettings.defaults(), json_limit_mib=1)
    )

    monkeypatch.setattr(
        path.__class__,
        "read_bytes",
        lambda _self: (_ for _ in ()).throw(AssertionError("must use bounded read")),
    )
    result = provider.preview(resource)

    assert result.mode == "message"
    assert "1 MiB" in result.message
    assert "设置" in result.message


def test_provider_applies_table_limit_to_zip_directory(tmp_path):
    path = tmp_path / "many.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for index in range(30):
            archive.writestr(f"entry-{index:02d}.txt", "x")
    resource = ResourceItem(name=path.name, path=str(path), type="archive", format="zip")
    provider = PreviewProvider().with_settings(
        replace(PreviewSettings.defaults(), table_max_rows=20)
    )

    result = provider.preview(resource)

    # #896: ZIP archive-name budget is MAX_ARCHIVE_NAMES (500), not table_max_rows (20).
    # With 30 entries (<500) the provider must return all 30 and not truncate.
    assert result.mode == "table"
    assert len(result.table_rows) == 30
    assert result.truncated is False


def test_local_visualization_provider_uses_geoviz_settings_snapshot(tmp_path):
    class Engine:
        def __init__(self):
            self.options = None

        def supports(self, _request):
            return True

        def prepare(self, _request, options):
            self.options = options
            return PreparedPreview(
                kind=PreviewKind.XY_SCATTER,
                title="configured",
                payload={"x": (), "y": ()},
            )

    path = tmp_path / "points.dat"
    path.write_text("0 0\n1 1\n", encoding="utf-8")
    engine = Engine()
    settings = replace(
        PreviewSettings.defaults(),
        geoviz_max_curves=7,
        geoviz_max_points=12_345,
        geoviz_surface_grid_size=96,
    )
    provider = LocalVisualizationProvider(engine).with_settings(settings)

    result = provider.preview(
        ResourceItem(name=path.name, path=str(path), type="horizon", format="dat")
    )

    assert result.mode == "geoviz"
    assert engine.options.max_curves == 7
    assert engine.options.max_points == 12_345
    assert engine.options.surface_grid_size == 96


def test_geotiff_thumbnail_respects_non_divisible_target(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")
    import io

    path = tmp_path / "wide.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=257,
        width=511,
        count=1,
        dtype="uint8",
    ) as dataset:
        dataset.write(np.zeros((257, 511), dtype="uint8"), 1)
    resource = ResourceItem(
        name=path.name,
        path=str(path),
        type="image_reference",
        format="tif",
    )
    provider = PreviewProvider().with_settings(
        replace(PreviewSettings.defaults(), geotiff_thumbnail_px=256)
    )

    result = provider.preview(resource)

    assert result.mode == "geotiff"
    with Image.open(io.BytesIO(result.image_bytes)) as thumbnail:
        assert max(thumbnail.size) <= 256


def test_geotiff_thumbnail_does_not_use_overview_when_source_is_below_target(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")
    from rasterio.enums import Resampling
    import io

    path = tmp_path / "small-with-overview.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=32,
        width=64,
        count=1,
        dtype="uint8",
    ) as dataset:
        dataset.write(np.zeros((32, 64), dtype="uint8"), 1)
        dataset.build_overviews([2], Resampling.nearest)
    resource = ResourceItem(
        name=path.name,
        path=str(path),
        type="image_reference",
        format="tif",
    )
    provider = PreviewProvider().with_settings(
        replace(PreviewSettings.defaults(), geotiff_thumbnail_px=256)
    )

    result = provider.preview(resource)

    assert result.mode == "geotiff"
    with Image.open(io.BytesIO(result.image_bytes)) as thumbnail:
        assert thumbnail.size == (64, 32)


def test_geotiff_thumbnail_ignores_overview_when_its_factor_is_insufficient(
    tmp_path,
):
    rasterio = pytest.importorskip("rasterio")
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")
    from rasterio.enums import Resampling
    import io

    path = tmp_path / "wide-with-small-overview.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=64,
        width=511,
        count=1,
        dtype="uint8",
    ) as dataset:
        dataset.write(np.zeros((64, 511), dtype="uint8"), 1)
        dataset.build_overviews([2], Resampling.nearest)
    resource = ResourceItem(
        name=path.name,
        path=str(path),
        type="image_reference",
        format="tif",
    )
    provider = PreviewProvider().with_settings(
        replace(PreviewSettings.defaults(), geotiff_thumbnail_px=128)
    )

    result = provider.preview(resource)

    assert result.mode == "geotiff"
    with Image.open(io.BytesIO(result.image_bytes)) as thumbnail:
        assert max(thumbnail.size) <= 128


def test_preview_cache_key_includes_settings_fingerprint(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    resource = ResourceItem(name=path.name, path=str(path), type="document", format="txt")

    first = make_preview_cache_key(resource, "settings-a")
    second = make_preview_cache_key(resource, "settings-b")

    assert first != second
    assert first[-1] == "settings-a"
    assert second[-1] == "settings-b"


def test_preview_cache_key_includes_xy_trust_metadata(tmp_path):
    path = tmp_path / "wells.dat"
    path.write_text("well data", encoding="utf-8")
    resource = ResourceItem(
        name=path.name,
        path=str(path),
        type="well_head",
        format="dat",
        crs="EPSG:32648",
        parsed_summary={"coordinate_units": "m"},
    )

    base = make_preview_cache_key(resource, comparison_crs="EPSG:3857")
    changed_crs = make_preview_cache_key(
        resource.model_copy(update={"crs": "EPSG:4326"}),
        comparison_crs="EPSG:3857",
    )
    changed_units = make_preview_cache_key(
        resource.model_copy(
            update={"parsed_summary": {"coordinate_units": "ft"}}
        ),
        comparison_crs="EPSG:3857",
    )
    changed_comparison = make_preview_cache_key(
        resource,
        comparison_crs="EPSG:4326",
    )

    assert base != changed_crs
    assert base != changed_units
    assert base != changed_comparison


def test_preview_disk_cache_key_includes_geoviz_options(tmp_path):
    path = tmp_path / "points.dat"
    path.write_text("0 0\n1 1\n", encoding="utf-8")
    resource = ResourceItem(name=path.name, path=str(path), type="horizon", format="dat")

    first = _entry_key_material(resource, PreviewOptions(max_points=10_000))
    second = _entry_key_material(resource, PreviewOptions(max_points=20_000))

    assert first != second
    disk = PreviewDiskCache(tmp_path)
    disk.set_options(PreviewOptions(max_points=20_000))
    assert disk.options.max_points == 20_000


def test_controller_setting_change_discards_old_worker_and_runs_latest(qtbot, tmp_path):
    class RecordingProvider(PreviewProvider):
        def __init__(self):
            super().__init__()
            self.started = threading.Event()
            self.seen: list[int] = []

        def preview(self, asset):
            self.seen.append(self.settings.text_limit_kib)
            self.started.set()
            if self.settings.text_limit_kib == 256:
                time.sleep(0.1)
            return PreviewResult(
                mode="text",
                title=str(self.settings.text_limit_kib),
                text=str(self.settings.text_limit_kib),
            )

    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    resource = ResourceItem(name=path.name, path=str(path), type="document", format="txt")
    provider = RecordingProvider()
    controller = PreviewRequestController(
        provider,
        settings=PreviewSettings.defaults(),
    )
    results: list[PreviewResult] = []
    controller.result_ready.connect(results.append)

    controller.request(resource)
    assert provider.started.wait(timeout=1)
    custom = replace(PreviewSettings.defaults(), text_limit_kib=16)
    old_generation = controller.generation
    controller.set_settings(custom)
    controller.request(resource)

    qtbot.waitUntil(
        lambda: controller._active_job.thread is None
        and controller._pending is None
        and bool(results),
        timeout=3_000,
    )
    assert controller.generation > old_generation
    assert [result.title for result in results] == ["16"]
    assert provider.seen == [256, 16]
    controller.shutdown()
