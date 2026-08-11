#include "qgis_render_bridge.hpp"

#include <QApplication>

#include <cassert>
#include <cstdlib>
#include <iostream>

int main(int argc, char** argv) {
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
