"""Integrity checks for the fixed, source-owned QGIS vector runtime."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QGIS = ROOT / "third_party" / "qgis"


def test_vendor_keeps_qgis_vector_edit_render_closure_and_license() -> None:
    assert (QGIS / "COPYING").read_bytes() == (ROOT / "LICENSE").read_bytes()
    assert (QGIS / "src" / "core" / "qgsapplication.h").is_file()
    assert (QGIS / "src" / "auth" / "basic" / "CMakeLists.txt").is_file()
    assert (QGIS / "src" / "core" / "providers" / "memory" / "qgsmemoryprovider.h").is_file()
    assert (QGIS / "src" / "core" / "providers" / "gdal" / "qgsgdalprovider.h").is_file()
    assert (QGIS / "src" / "analysis" / "vector" / "qgsgeometrysnapper.h").is_file()
    assert (QGIS / "src" / "gui" / "qgsmapcanvas.h").is_file()
    assert (QGIS / "src" / "gui" / "maptools" / "qgsmaptooldigitizefeature.h").is_file()
    assert (QGIS / "src" / "app" / "maptools" / "qgsappmaptools.h").is_file()
    assert (QGIS / "src" / "app" / "maptools" / "qgsmaptoolsdigitizingtechniquemanager.h").is_file()
    assert (QGIS / "src" / "plugins" / "geometry_checker" / "qgsgeometrycheckerdialog.h").is_file()
    assert (QGIS / "scripts" / "process_function_template.py").is_file()
    assert not (QGIS / "src" / "server").exists()


def test_vendor_provenance_is_immutable_and_builds_without_external_qgis_lookup() -> None:
    provenance = (QGIS / "UPSTREAM.md").read_text(encoding="utf-8")
    bridge_cmake = (ROOT / "native" / "qgis_render_bridge" / "CMakeLists.txt").read_text(encoding="utf-8")
    bridge_setup = (ROOT / "native" / "qgis_render_bridge" / "setup.py").read_text(encoding="utf-8")
    bridge_source = (ROOT / "native" / "qgis_render_bridge" / "src" / "qgis_render_bridge.cpp").read_text(
        encoding="utf-8"
    )

    assert "final-4_2_0" in provenance
    assert "ca5812c8b8e39b59695a3b0206fc5f3206eda0a9" in provenance
    assert "98f6913e9e836976f2c0d72d992a172a616621b96c78d9d3a820fdeefd737174" in provenance
    assert "ExternalProject_Add(paleo_qgis_vendor" in bridge_cmake
    assert "--target resources qgis_core qgis_gui qgis_analysis" in bridge_cmake
    assert "-DWITH_AUTH=ON" in bridge_cmake
    assert "-DUSE_OPENCL=OFF" in bridge_cmake
    assert "GLOB_RECURSE PALEO_QGIS_CORE_HEADERS" in bridge_cmake
    assert "find_library(QGIS" not in bridge_cmake
    assert "find_path(QGIS" not in bridge_cmake
    assert 'os.environ.get("QGIS_PREFIX_PATH"' not in bridge_setup
    assert '"resources", "qgis_core"' in bridge_setup
    assert 'build_dir / "resources" / "srs.db"' in bridge_setup
    assert '"-DWITH_AUTH=ON"' in bridge_setup
    assert '"-DUSE_OPENCL=OFF"' in bridge_setup
    assert "def _qgis_core_include_dirs" in bridge_setup
    assert "std::getenv(\"QGIS_PREFIX_PATH\")" not in bridge_source
