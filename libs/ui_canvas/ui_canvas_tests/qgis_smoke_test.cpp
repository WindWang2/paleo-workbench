// UI-15 QGIS smoke (offscreen, real runtime): snapshot codec ↔ bridge
// spec conversion, QgisSnapshotRenderBackend initialize/render_sync/
// export/shutdown over the vendored QGIS stack, backend-factory
// registration, and the symbology-availability probe. The dialog
// invocation itself needs a user — only the honest non-dialog surface
// runs here (probe + codec + backend).

#include <QApplication>
#include <QFile>

#include <cstdio>
#include <memory>
#include <stdexcept>
#include <string>

#include "ui_canvas_test.hpp"

#include <pwb/ui_canvas/map_render_backend.hpp>
#include <pwb/ui_canvas/qgis/qgis_snapshot_backend.hpp>
#include <pwb/ui_canvas/qgis/qgis_symbology_bridge.hpp>
#include <pwb/ui_canvas/qgis/snapshot_codec.hpp>

using namespace pwb::ui_canvas;
namespace cq = pwb::ui_canvas::qgis;

namespace {

MapRenderSnapshot vector_snapshot() {
    MapRenderSnapshot snapshot;
    snapshot.project_crs = "EPSG:4326";
    MapLayerSnapshot layer;
    layer.id = "wells";
    layer.name = "井位";
    layer.layer_type = "vector";
    layer.crs = "EPSG:4326";
    layer.data_revision = 1;
    layer.style_revision = 1;
    layer.visible = true;
    layer.opacity = 1.0;
    layer.features = Json::array({
        Json{{"id", "w1"},
             {"geometry", Json{{"type", "Point"},
                               {"coordinates", Json::array({10.0, 10.0})}}},
             {"properties", Json{{"name", "w1"}}}},
        Json{{"id", "w2"},
             {"geometry", Json{{"type", "Point"},
                               {"coordinates", Json::array({20.0, 20.0})}}},
             {"properties", Json{{"name", "w2"}}}},
    });
    snapshot.layers.push_back(layer);
    return snapshot;
}

}  // namespace

PWB_TEST(codec_layer_spec_from_json) {
    SnapshotEncoderState state;
    const Json layers = encode_qgis_snapshot(vector_snapshot(), state);
    CHECK_EQ(static_cast<long long>(layers.size()), 1);

    const auto specs = cq::layer_specs_from_json(layers);
    CHECK_EQ(static_cast<long long>(specs.size()), 1);
    CHECK_EQ(specs[0].id, std::string("wells"));
    CHECK_EQ(static_cast<long long>(specs[0].features.size()), 2);

    // Missing required keys → invalid_argument (pybind cast parity).
    bool threw = false;
    try {
        cq::layer_spec_from_json(Json::object());
    } catch (const std::invalid_argument&) {
        threw = true;
    }
    CHECK(threw);
}

PWB_TEST(codec_legacy_style_migration_and_renderer_info) {
    // Flat legacy style → migrated renderer XML (never a fake success —
    // a real QgsRenderer is serialized).
    Json style = {
        {"renderer", "single"},
        {"fill", "#FF0000"},
        {"stroke", "#000000"},
        {"stroke_width", 1.0},
    };
    const std::string xml =
        cq::legacy_style_to_renderer_xml(style, "Point");
    CHECK(!xml.empty());
    CHECK(xml.find("renderer") != std::string::npos);

    // renderer_info over the migrated payload → {"type", "symbol_count"}.
    Json info = cq::renderer_info(xml);
    CHECK(info.is_object());
    CHECK(info.contains("type"));
    CHECK(info.contains("symbol_count"));
    // Garbage XML → null Json (py::none parity).
    CHECK(cq::renderer_info("<not xml").is_null());
}

PWB_TEST(snapshot_backend_render_sync_and_export) {
    cq::QgisSnapshotRenderBackend backend;
    CHECK_EQ(backend.backend_name(), std::string("qgis"));
    CHECK(backend.is_available());
    backend.initialize();
    CHECK(backend.initialized());
    CHECK(backend.status().find("ready") != std::string::npos);

    backend.set_layer_snapshot(vector_snapshot());
    backend.set_extent({0.0, 0.0, 40.0, 40.0});
    backend.set_output_size(160, 160);
    backend.set_dpi(96.0);

    RenderFrame frame = backend.render_sync();
    CHECK_EQ(static_cast<long long>(frame.width), 160);
    CHECK_EQ(static_cast<long long>(frame.height), 160);
    CHECK_EQ(static_cast<long long>(frame.rgba.size()),
             static_cast<long long>(frame.stride) * frame.height);

    // The encoder cache survived the push; a second identical snapshot
    // encodes to a full feature list only once (cache hit).
    backend.set_layer_snapshot(vector_snapshot());
    RenderFrame again = backend.render_sync();
    CHECK_EQ(static_cast<long long>(again.width), 160);

    // Vector export through the native renderer writes a real file.
    const std::string svg_path = "/tmp/ui_canvas_qgis_smoke.svg";
    QFile::remove(QString::fromStdString(svg_path));
    CHECK(backend.export_map_body(svg_path, "svg", 400, 300, 96.0));
    CHECK(QFile::exists(QString::fromStdString(svg_path)));

    backend.shutdown();
    backend.shutdown();  // idempotent
}

PWB_TEST(qgis_factory_and_probe) {
    const auto probe = cq::qgis_backend_probe();
    CHECK(probe.first);
    CHECK(probe.second.empty());

    cq::install_qgis_backend_factory();
    auto backend = create_native_map_render_backend();
    CHECK(backend != nullptr);
    CHECK_EQ(backend->backend_name(), std::string("qgis"));
    CHECK(backend->initialized());
    backend->shutdown();

    // Symbology availability is the same cached probe.
    CHECK(cq::qgis_symbology_available());
}

PWB_TEST(symbology_renderer_info_seam) {
    Json info = cq::symbology_renderer_info("<garbage");
    CHECK(info.is_null());
}

int main(int argc, char** argv) {
    // standalone_test.cpp parity: the vendored bridge initializes the
    // process-global QGIS runtime itself (setPrefixPath + init + initQgis
    // behind g_qgis_initialized). Codec paths that build real Qgs
    // renderers need that runtime up front — warm it before run_all.
    QApplication app(argc, argv);
    cq::QgisSnapshotRenderBackend warmup;
    try {
        warmup.initialize();
    } catch (const std::exception& exc) {
        std::fprintf(stderr, "QGIS runtime not initialized: %s\n",
                     exc.what());
        return 2;
    }
    const int failures = pwb_test::run_all();
    warmup.shutdown();
    return failures;
}
