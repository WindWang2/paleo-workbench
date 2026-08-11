#include "qgis_render_bridge.hpp"

#include <array>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;
using pwb::qgis_render::FeatureSpec;
using pwb::qgis_render::QgisRenderBridge;
using pwb::qgis_render::VectorLayerSpec;

namespace {

std::vector<VectorLayerSpec> parse_layers(const py::iterable& values) {
    std::vector<VectorLayerSpec> layers;
    for (const py::handle item : values) {
        const py::dict data = py::reinterpret_borrow<py::dict>(item);
        VectorLayerSpec layer;
        layer.id = py::cast<std::string>(data["id"]);
        layer.name = py::cast<std::string>(data["name"]);
        layer.crs = py::cast<std::string>(data["crs"]);
        layer.data_revision = py::cast<std::uint64_t>(data["data_revision"]);
        layer.style_revision = py::cast<std::uint64_t>(data["style_revision"]);
        layer.visible = py::cast<bool>(data["visible"]);
        layer.opacity = py::cast<double>(data["opacity"]);
        for (const py::handle feature_item : py::reinterpret_borrow<py::iterable>(data["features"])) {
            const py::dict feature = py::reinterpret_borrow<py::dict>(feature_item);
            layer.features.push_back({
                py::cast<std::string>(feature["id"]),
                py::cast<std::string>(feature["wkt"]),
            });
        }
        layers.push_back(std::move(layer));
    }
    return layers;
}

std::array<double, 4> parse_extent(const py::sequence& extent) {
    if (py::len(extent) != 4) throw std::invalid_argument("extent must have four values");
    return {
        py::cast<double>(extent[0]), py::cast<double>(extent[1]),
        py::cast<double>(extent[2]), py::cast<double>(extent[3]),
    };
}

py::dict result_to_python(const pwb::qgis_render::RenderResult& result) {
    py::dict output;
    output["generation"] = result.generation;
    output["width"] = result.width;
    output["height"] = result.height;
    output["stride"] = result.stride;
    output["render_ms"] = result.render_ms;
    output["rgba"] = py::bytes(
        reinterpret_cast<const char*>(result.rgba.data()), result.rgba.size()
    );
    return output;
}

}  // namespace

PYBIND11_MODULE(qgis_render_bridge, module) {
    module.doc() = "Narrow optional C++ QGIS map-render bridge";
    py::class_<QgisRenderBridge>(module, "QgisRenderBridge")
        .def(py::init<>())
        .def("initialize", &QgisRenderBridge::initialize, py::arg("prefix_path") = "")
        .def("set_layer_snapshot", [](QgisRenderBridge& bridge, const py::iterable& layers,
                                       const std::string& project_crs) {
            bridge.set_layer_snapshot(parse_layers(layers), project_crs);
        })
        .def("request_render", [](QgisRenderBridge& bridge, const py::sequence& extent,
                                  const int width, const int height, const double dpi,
                                  const std::uint64_t generation) {
            bridge.request_render(parse_extent(extent), width, height, dpi, generation);
        })
        .def("take_completed_frame", [](QgisRenderBridge& bridge) -> py::object {
            const auto result = bridge.take_completed_frame();
            if (result) return result_to_python(*result);
            return py::none();
        })
        .def("cancel_render", &QgisRenderBridge::cancel_render)
        .def("render_sync", [](const QgisRenderBridge& bridge, const py::sequence& extent,
                                 const int width, const int height, const double dpi) {
            return result_to_python(bridge.render_sync(parse_extent(extent), width, height, dpi));
        })
        .def("shutdown", &QgisRenderBridge::shutdown)
        .def_property_readonly("initialized", &QgisRenderBridge::initialized)
        .def_property_readonly("render_active", &QgisRenderBridge::render_active)
        .def_property_readonly("version", &QgisRenderBridge::version);
}
