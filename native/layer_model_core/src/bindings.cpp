// bindings.cpp — pybind11 control-surface binding for the authoritative layer registry.
//
// Rendering state lives in C++. Python receives shared layer handles so a layer object
// remains valid for inspection after it is removed from a registry, while the registry
// alone decides whether the layer participates in composition.
#include "layer_model.hpp"

#include <memory>
#include <stdexcept>
#include <string>

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;
namespace lm = pwb::layer_model;

PYBIND11_MODULE(layer_model_core, m) {
    m.doc() = "Authoritative C++ map-layer registry for paleo-workbench native maps.";

    py::enum_<lm::LayerType>(m, "LayerType")
        .value("ScalarGrid", lm::LayerType::ScalarGrid)
        .value("Raster", lm::LayerType::Raster)
        .value("Contour", lm::LayerType::Contour)
        .value("Vector", lm::LayerType::Vector)
        .value("Point", lm::LayerType::Point)
        .value("Annotation", lm::LayerType::Annotation)
        .value("Group", lm::LayerType::Group)
        .export_values();

    py::class_<lm::ScaleRange>(m, "ScaleRange")
        .def(py::init<double, double>(), py::arg("min_scale") = 0.0,
             py::arg("max_scale") = 0.0)
        .def_readwrite("min_scale", &lm::ScaleRange::min_scale)
        .def_readwrite("max_scale", &lm::ScaleRange::max_scale)
        .def("visible_at", &lm::ScaleRange::visible_at,
             py::arg("scale_denominator"));

    py::class_<lm::MapLayer, std::shared_ptr<lm::MapLayer>>(m, "MapLayer")
        .def_property_readonly("id", &lm::MapLayer::id)
        .def_property_readonly("type", &lm::MapLayer::type)
        .def_property("name", &lm::MapLayer::name, &lm::MapLayer::set_name)
        .def_property("visible", &lm::MapLayer::visible, &lm::MapLayer::set_visible)
        .def_property("opacity", &lm::MapLayer::opacity, &lm::MapLayer::set_opacity)
        .def_property("crs", &lm::MapLayer::crs, &lm::MapLayer::set_crs)
        .def_property(
            "extent",
            [](const lm::MapLayer& layer) {
                const lm::Extent extent = layer.extent();
                return py::make_tuple(extent[0], extent[1], extent[2], extent[3]);
            },
            &lm::MapLayer::set_extent)
        .def_property(
            "scale_range",
            // Return a COPY: the default reference_internal policy would hand
            // out a live reference to the C++ member, letting callers mutate
            // render state without bumping style_revision (H12).
            [](const lm::MapLayer& layer) { return layer.scale_range(); },
            &lm::MapLayer::set_scale_range)
        .def_property("source_ref", &lm::MapLayer::source_ref,
                      &lm::MapLayer::set_source_ref)
        .def_property_readonly("provenance_ref", &lm::MapLayer::provenance_ref)
        .def("set_provenance_ref", &lm::MapLayer::set_provenance_ref,
             py::arg("source_ref"))
        .def_property_readonly("metadata", &lm::MapLayer::metadata)
        .def("set_metadata", &lm::MapLayer::set_metadata, py::arg("key"),
             py::arg("value"))
        .def_property_readonly("data_revision", &lm::MapLayer::data_revision)
        .def_property_readonly("style_revision", &lm::MapLayer::style_revision)
        .def("bump_data_revision", &lm::MapLayer::bump_data_revision)
        .def("bump_style_revision", &lm::MapLayer::bump_style_revision)
        .def_property("dirty", &lm::MapLayer::dirty, &lm::MapLayer::set_dirty)
        .def("visible_at_scale", &lm::MapLayer::visible_at_scale,
             py::arg("scale_denominator"));

    py::class_<lm::LayerRegistry>(m, "LayerRegistry")
        .def(py::init<>())
        .def("add_layer",
             [](lm::LayerRegistry& registry, const std::string& id,
                const std::string& name, lm::LayerType type,
                const std::string& parent_id) {
                 registry.add_layer(std::make_unique<lm::MapLayer>(id, name, type),
                                    parent_id);
                 return registry.get_shared(id);
             },
             py::arg("id"), py::arg("name"), py::arg("type"),
             py::arg("parent_id") = "")
        .def("remove_layer", &lm::LayerRegistry::remove_layer, py::arg("id"))
        .def("get", &lm::LayerRegistry::get_shared, py::arg("id"))
        .def_property_readonly("size", &lm::LayerRegistry::size)
        .def_property_readonly("empty", &lm::LayerRegistry::empty)
        .def("layers", [](const lm::LayerRegistry& registry) {
            return registry.layers();
        })
        .def("index_of", &lm::LayerRegistry::index_of, py::arg("id"))
        .def("move_layer", &lm::LayerRegistry::move_layer, py::arg("id"),
             py::arg("new_index"))
        .def("move_above", &lm::LayerRegistry::move_above, py::arg("id"),
             py::arg("other"))
        .def("move_below", &lm::LayerRegistry::move_below, py::arg("id"),
             py::arg("other"))
        .def("set_parent", &lm::LayerRegistry::set_parent, py::arg("id"),
             py::arg("parent_id"))
        .def("is_effectively_visible", &lm::LayerRegistry::is_effectively_visible,
             py::arg("id"), py::arg("scale_denominator"))
        .def("children_of", [](const lm::LayerRegistry& registry,
                                const std::string& group_id) {
            std::vector<std::shared_ptr<lm::MapLayer>> children;
            for (const lm::MapLayer* child : registry.children_of(group_id)) {
                children.push_back(registry.get_shared(child->id()));
            }
            return children;
        }, py::arg("group_id"))
        .def("parent_id", &lm::LayerRegistry::parent_id, py::arg("id"));
}
