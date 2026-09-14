#include "geological_topology_core.hpp"
#include "qgis_render_bridge.hpp"

#include <QApplication>

#include <cassert>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <vector>

// geotopo core selftest: pure std, runs before the Qt-dependent render check.
static int run_geotopo_selftest() {
    namespace gt = pwb::geotopo;
    // Framed cross: 4 quadrant faces, 3 parents each.
    std::vector<gt::ControlLineInput> lines{
        {"frame", {0, 0, 10, 0, 10, 10, 0, 10, 0, 0}},
        {"shore", {0, 5, 10, 5}},
        {"boundary", {5, 0, 5, 10}},
    };
    gt::PolygonizeOptions options;
    gt::PolygonizeResult result = gt::polygonize_control_lines(lines, options);
    assert(result.error == gt::ErrorCode::Ok);
    assert(result.faces.size() == 4);
    for (const auto& face : result.faces) {
        assert(face.area > 24.999 && face.area < 25.001);
        assert(face.source_lines.size() == 3);
    }
    // 51×51 grid (5100 segments): 2500 faces, performance gate.
    std::vector<gt::ControlLineInput> grid;
    std::vector<double> h, v;
    for (int i = 0; i <= 50; ++i) {
        h.clear();
        v.clear();
        for (int j = 0; j <= 50; ++j) {
            h.push_back(static_cast<double>(j));
            h.push_back(static_cast<double>(i));
            v.push_back(static_cast<double>(i));
            v.push_back(static_cast<double>(j));
        }
        grid.push_back({std::string("h") + std::to_string(i), h});
        grid.push_back({std::string("v") + std::to_string(i), v});
    }
    gt::PolygonizeResult perf = gt::polygonize_control_lines(grid, options);
    assert(perf.error == gt::ErrorCode::Ok);
    assert(perf.faces.size() == 2500);
    std::cout << "geotopo selftest: grid elapsed_ms=" << perf.elapsed_ms << "\n";
    assert(perf.elapsed_ms <= 30.0);
    return EXIT_SUCCESS;
}

int main(int argc, char** argv) {
    if (const int geotopo = run_geotopo_selftest(); geotopo != EXIT_SUCCESS) {
        return geotopo;
    }
    QApplication app(argc, argv);
    pwb::qgis_render::QgisRenderBridge bridge;
    bridge.initialize();
    pwb::qgis_render::VectorLayerSpec layer;
    layer.id = "facies";
    layer.name = "Facies";
    layer.crs = "EPSG:3857";
    layer.data_revision = 1;
    layer.style_revision = 1;
    layer.features.push_back({"f1", "POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0))"});
    bridge.set_layer_snapshot({layer}, "EPSG:3857");
    const auto result = bridge.render_sync({0.0, 0.0, 10.0, 10.0}, 160, 120, 96.0);
    assert(result.width == 160);
    assert(result.height == 120);
    assert(result.stride >= 160 * 4);
    assert(result.rgba.size() == static_cast<std::size_t>(result.height * result.stride));
    bridge.shutdown();
    std::cout << "qgis_render_bridge selftest passed\n";
    return EXIT_SUCCESS;
}
