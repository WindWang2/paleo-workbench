#include "qgis_render_bridge.hpp"

// pybind11 (and therefore Python.h) must be included BEFORE any Qt/QGIS
// header: Qt redefines `slots`, which corrupts PyType_Spec in object.h.
#include <array>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <pybind11/functional.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <qgis.h>
#include <qgsrenderer.h>
#include <qgsrendercontext.h>
#include <qgssymbol.h>

#include "geometry_service.hpp"
#include "gui_service.hpp"
#include "map_stack_service.hpp"
#include "style_codec.hpp"

namespace py = pybind11;
using pwb::qgis_render::CategorySpec;
using pwb::qgis_render::FeatureSpec;
using pwb::qgis_render::GeometryServiceError;
using pwb::qgis_render::GuiDialogRequest;
using pwb::qgis_render::QgisRenderBridge;
using pwb::qgis_render::RangeSpec;
using pwb::qgis_render::RuleSpec;
using pwb::qgis_render::VectorLayerSpec;

namespace {

py::dict as_dict(const py::handle& value, const char* what) {
    // reinterpret_borrow without a type check would run PyDict_Next on a
    // non-dict (user-typed JSON can supply lists/strings) — undefined
    // behavior. Validate and raise a proper TypeError instead (audit I6).
    if (!py::isinstance<py::dict>(value)) {
        throw py::type_error(std::string(what) + " must be a dict");
    }
    return py::reinterpret_borrow<py::dict>(value);
}

std::vector<VectorLayerSpec> parse_layers(const py::iterable& values) {
    std::vector<VectorLayerSpec> layers;
    for (const py::handle item : values) {
        const py::dict data = as_dict(item, "layer");
        VectorLayerSpec layer;
        layer.id = py::cast<std::string>(data["id"]);
        layer.name = py::cast<std::string>(data["name"]);
        layer.crs = py::cast<std::string>(data["crs"]);
        if (data.contains("kind") && py::cast<std::string>(data["kind"]) == "raster") {
            layer.kind = VectorLayerSpec::Kind::Raster;
            layer.source_path = py::cast<std::string>(data["source_path"]);
        }
        if (data.contains("style")) {
            const py::dict style = as_dict(data["style"], "layer style");
            if (style.contains("fill")) layer.fill = py::cast<std::string>(style["fill"]);
            if (style.contains("stroke")) layer.stroke = py::cast<std::string>(style["stroke"]);
            if (style.contains("stroke_width")) layer.stroke_width = py::cast<double>(style["stroke_width"]);
            if (style.contains("marker_size")) layer.marker_size = py::cast<double>(style["marker_size"]);
            if (style.contains("marker")) layer.marker = py::cast<std::string>(style["marker"]);
            if (style.contains("line_pattern")) layer.line_pattern = py::cast<std::string>(style["line_pattern"]);
            if (style.contains("renderer")) layer.renderer_kind = py::cast<std::string>(style["renderer"]);
            if (style.contains("field")) layer.classification_field = py::cast<std::string>(style["field"]);
            if (style.contains("renderer_xml")) {
                layer.renderer_xml = py::cast<std::string>(style["renderer_xml"]);
            }
            if (style.contains("labeling_xml")) {
                layer.labeling_xml = py::cast<std::string>(style["labeling_xml"]);
            }
            if (style.contains("rules")) {
                for (const py::handle rule_item :
                     py::reinterpret_borrow<py::iterable>(style["rules"])) {
                    const py::dict rule = as_dict(rule_item, "style rule");
                    RuleSpec parsed;
                    parsed.name = py::cast<std::string>(rule["name"]);
                    parsed.expression = py::cast<std::string>(rule["expression"]);
                    if (rule.contains("label")) parsed.label = py::cast<std::string>(rule["label"]);
                    if (rule.contains("fill")) parsed.fill = py::cast<std::string>(rule["fill"]);
                    if (rule.contains("stroke")) parsed.stroke = py::cast<std::string>(rule["stroke"]);
                    if (rule.contains("stroke_width")) parsed.stroke_width = py::cast<double>(rule["stroke_width"]);
                    if (rule.contains("marker_size")) parsed.marker_size = py::cast<double>(rule["marker_size"]);
                    layer.rules.push_back(std::move(parsed));
                }
            }
            if (style.contains("categories")) {
                const py::dict categories = as_dict(style["categories"], "style categories");
                for (const auto item : categories) {
                    layer.categories.push_back({
                        py::cast<std::string>(py::str(item.first)),
                        py::cast<std::string>(py::str(item.second)),
                        py::cast<std::string>(py::str(item.first)),
                    });
                }
            }
            if (style.contains("ranges")) {
                for (const py::handle range_item : py::reinterpret_borrow<py::iterable>(style["ranges"])) {
                    const py::dict range = as_dict(range_item, "style range");
                    layer.ranges.push_back({
                        py::cast<double>(range["lower"]),
                        py::cast<double>(range["upper"]),
                        py::cast<std::string>(range["color"]),
                        range.contains("label") ? py::cast<std::string>(range["label"]) : "",
                    });
                }
            }
            if (style.contains("labels")) {
                const py::dict labels = as_dict(style["labels"], "style labels");
                // #922: an explicit labels.visible=false must hide labels even
                // when a field is configured (previously dropped → drawn anyway).
                const bool visible = labels.contains("visible")
                                         ? py::cast<bool>(labels["visible"])
                                         : true;
                layer.labels_enabled =
                    visible && labels.contains("field")
                    && !py::cast<std::string>(labels["field"]).empty();
                if (labels.contains("field")) layer.label_field = py::cast<std::string>(labels["field"]);
                if (labels.contains("font_family")) layer.label_font_family = py::cast<std::string>(labels["font_family"]);
                if (labels.contains("size")) layer.label_size = py::cast<double>(labels["size"]);
                if (labels.contains("bold")) layer.label_bold = py::cast<bool>(labels["bold"]);
                if (labels.contains("color")) layer.label_color = py::cast<std::string>(labels["color"]);
                if (labels.contains("buffer")) layer.label_buffer_size = py::cast<double>(labels["buffer"]);
                // #1102: the buffer (halo) colour uses the same wire format
                // as "color" (a colour string); previously decoded away and
                // dropped, leaving the C++ side hardcoding white halos.
                if (labels.contains("buffer_color")) {
                    layer.label_buffer_color = py::cast<std::string>(labels["buffer_color"]);
                }
                // #1052: per-feature data-defined label styling. The values
                // are attribute FIELD names evaluated per feature by QGIS
                // PAL (rotation degrees clockwise / size points / colour).
                if (labels.contains("rotation_field")) {
                    layer.label_rotation_field = py::cast<std::string>(labels["rotation_field"]);
                }
                if (labels.contains("size_field")) {
                    layer.label_size_field = py::cast<std::string>(labels["size_field"]);
                }
                if (labels.contains("color_field")) {
                    layer.label_color_field = py::cast<std::string>(labels["color_field"]);
                }
            }
        }
        layer.data_revision = py::cast<std::uint64_t>(data["data_revision"]);
        layer.style_revision = py::cast<std::uint64_t>(data["style_revision"]);
        layer.visible = py::cast<bool>(data["visible"]);
        // #929: scale visibility travels with the layer payload (the fallback
        // honours VectorStyle.scale_range; the QGIS wire used to drop it).
        if (data.contains("scale_range") && !data["scale_range"].is_none()) {
            const py::sequence range = py::reinterpret_borrow<py::sequence>(data["scale_range"]);
            if (py::len(range) == 2) {
                layer.has_scale_range = true;
                layer.scale_range_min_denom = py::cast<double>(range[0]);
                layer.scale_range_max_denom = py::cast<double>(range[1]);
            }
        }
        layer.opacity = py::cast<double>(data["opacity"]);
        // #932: an incremental delta replaces the feature list. Parse it with
        // the same FeatureSpec conversion the full path uses.
        if (data.contains("delta") && !data["delta"].is_none()) {
            const py::dict delta = as_dict(data["delta"], "layer delta");
            VectorLayerSpec::FeatureDelta parsed_delta;
            parsed_delta.base_revision = py::cast<std::uint64_t>(delta["base_revision"]);
            for (const py::handle feature_item :
                 py::reinterpret_borrow<py::iterable>(delta["changed_features"])) {
                const py::dict feature = as_dict(feature_item, "delta feature");
                FeatureSpec parsed{
                    py::cast<std::string>(feature["id"]),
                    py::cast<std::string>(feature["wkt"]),
                    {},
                };
                if (feature.contains("attributes")) {
                    const py::dict attributes = as_dict(feature["attributes"], "feature attributes");
                    for (const auto attribute : attributes) {
                        parsed.attributes.emplace_back(
                            py::cast<std::string>(py::str(attribute.first)),
                            py::cast<std::string>(py::str(attribute.second))
                        );
                    }
                }
                parsed_delta.changed.push_back(std::move(parsed));
            }
            for (const py::handle removed :
                 py::reinterpret_borrow<py::iterable>(delta["removed_ids"])) {
                parsed_delta.removed_ids.push_back(py::cast<std::string>(removed));
            }
            layer.delta = std::move(parsed_delta);
        } else {
        for (const py::handle feature_item : py::reinterpret_borrow<py::iterable>(data["features"])) {
            const py::dict feature = as_dict(feature_item, "feature");
            FeatureSpec parsed{
                py::cast<std::string>(feature["id"]),
                py::cast<std::string>(feature["wkt"]),
                {},
            };
            if (feature.contains("attributes")) {
                const py::dict attributes = as_dict(feature["attributes"], "feature attributes");
                for (const auto attribute : attributes) {
                    parsed.attributes.emplace_back(
                        py::cast<std::string>(py::str(attribute.first)),
                        py::cast<std::string>(py::str(attribute.second))
                    );
                }
            }
            layer.features.push_back(std::move(parsed));
        }
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

GuiDialogRequest parse_dialog_request(const py::dict& data) {
    GuiDialogRequest request;
    request.title = py::cast<std::string>(data.attr("get")("title", ""));
    request.geometry_type = py::cast<std::string>(data["geometry_type"]);
    request.crs = py::cast<std::string>(data.attr("get")("crs", ""));
    if (data.contains("renderer_xml")) {
        request.renderer_xml = py::cast<std::string>(data["renderer_xml"]);
    }
    if (data.contains("style_db_path")) {
        request.style_db_path = py::cast<std::string>(data["style_db_path"]);
    }
    if (data.contains("fill")) request.fill = py::cast<std::string>(data["fill"]);
    if (data.contains("stroke")) request.stroke = py::cast<std::string>(data["stroke"]);
    if (data.contains("stroke_width")) request.stroke_width = py::cast<double>(data["stroke_width"]);
    if (data.contains("marker_size")) request.marker_size = py::cast<double>(data["marker_size"]);
    if (data.contains("fields")) {
        for (const py::handle field : py::reinterpret_borrow<py::iterable>(data["fields"])) {
            request.field_names.push_back(py::cast<std::string>(field));
        }
    }
    return request;
}

py::dict dialog_result_to_python(const pwb::qgis_render::GuiDialogResult& result) {
    py::dict output;
    output["ok"] = result.ok;
    output["renderer_xml"] = result.renderer_xml;
    output["opacity"] = result.opacity;
    return output;
}

/// Build a renderer from a legacy VectorStyle dict and serialize it.
/// This is the legacy_to_qgis_renderer() migration entry point.
py::object legacy_style_to_renderer_xml(const py::dict& style,
                                        const std::string& geometry_type) {
    VectorLayerSpec spec;
    spec.id = "migration";
    if (style.contains("fill")) spec.fill = py::cast<std::string>(style["fill"]);
    if (style.contains("stroke")) spec.stroke = py::cast<std::string>(style["stroke"]);
    if (style.contains("stroke_width")) spec.stroke_width = py::cast<double>(style["stroke_width"]);
    if (style.contains("marker_size")) spec.marker_size = py::cast<double>(style["marker_size"]);
    if (style.contains("renderer")) spec.renderer_kind = py::cast<std::string>(style["renderer"]);
    if (style.contains("field")) spec.classification_field = py::cast<std::string>(style["field"]);
    if (style.contains("categories")) {
        const py::object raw = style["categories"];
        if (py::isinstance<py::dict>(raw)) {
            const py::dict categories = raw;
            for (const auto item : categories) {
                spec.categories.push_back({
                    py::cast<std::string>(py::str(item.first)),
                    py::cast<std::string>(py::str(item.second)),
                    py::cast<std::string>(py::str(item.first)),
                });
            }
        } else {
            for (const py::handle entry : py::reinterpret_borrow<py::iterable>(raw)) {
                const py::sequence item = py::reinterpret_borrow<py::sequence>(entry);
                spec.categories.push_back({
                    py::cast<std::string>(item[0]),
                    py::cast<std::string>(item[1]),
                    py::len(item) > 2 ? py::cast<std::string>(item[2]) : std::string(),
                });
            }
        }
    }
    if (style.contains("ranges")) {
        for (const py::handle entry : py::reinterpret_borrow<py::iterable>(style["ranges"])) {
            const py::sequence item = py::reinterpret_borrow<py::sequence>(entry);
            spec.ranges.push_back({
                py::cast<double>(item[0]),
                py::cast<double>(item[1]),
                py::cast<std::string>(item[2]),
                py::len(item) > 3 ? py::cast<std::string>(item[3]) : std::string(),
            });
        }
    }
    if (style.contains("rules")) {
        for (const py::handle entry : py::reinterpret_borrow<py::iterable>(style["rules"])) {
            const py::dict rule = as_dict(entry, "legacy rule");
            RuleSpec parsed;
            parsed.name = py::cast<std::string>(rule.attr("get")("name", ""));
            parsed.expression = py::cast<std::string>(rule.attr("get")("expression", ""));
            parsed.label = py::cast<std::string>(rule.attr("get")("label", ""));
            parsed.fill = py::cast<std::string>(rule.attr("get")("fill", ""));
            parsed.stroke = py::cast<std::string>(rule.attr("get")("stroke", ""));
            if (rule.contains("stroke_width")) parsed.stroke_width = py::cast<double>(rule["stroke_width"]);
            if (rule.contains("marker_size")) parsed.marker_size = py::cast<double>(rule["marker_size"]);
            spec.rules.push_back(std::move(parsed));
        }
    }

    Qgis::GeometryType geometry = Qgis::GeometryType::Null;
    if (geometry_type == "Point" || geometry_type == "MultiPoint") geometry = Qgis::GeometryType::Point;
    else if (geometry_type == "LineString" || geometry_type == "MultiLineString") geometry = Qgis::GeometryType::Line;
    else if (geometry_type == "Polygon" || geometry_type == "MultiPolygon") geometry = Qgis::GeometryType::Polygon;
    auto renderer = pwb::qgis_render::build_renderer_from_spec(geometry, spec);
    if (!renderer) return py::none();
    return py::str(pwb::qgis_render::renderer_to_xml(*renderer));
}

/// Describe a serialized renderer payload without instantiating host objects:
/// {type, symbol_count} so Python UI can label layers without parsing XML.
py::object renderer_info(const std::string& renderer_xml) {
    auto renderer = pwb::qgis_render::renderer_from_xml(renderer_xml);
    if (!renderer) return py::none();
    QgsRenderContext context;
    py::dict info;
    info["type"] = renderer->type().toStdString();
    info["symbol_count"] = static_cast<int>(renderer->symbols(context).size());
    return info;
}

}  // namespace

PYBIND11_MODULE(qgis_render_bridge, module) {
    module.doc() = "Narrow optional C++ QGIS map-render bridge";
    // Build metadata for freshness checks (#938-8): aligns with
    // paleo_workbench.__version__ ("0.2.17a0"); previously missing and drifted.
    module.attr("__version__") = "0.2.17a0";
    module.attr("__build_commit__") = "unknown";
    py::register_exception<GeometryServiceError>(module, "QgisGeometryError");

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
        .def("cancel_render", &QgisRenderBridge::cancel_render,
             "Cancel any in-flight async render. Threading contract: async "
             "completion requires the GUI event loop; without it, "
             "render_active stays true until cancel_render/shutdown (#938-5).")
        .def("render_sync", [](const QgisRenderBridge& bridge, const py::sequence& extent,
                                 const int width, const int height, const double dpi) {
            // Convert Python input while holding the GIL, then release it for
            // the long C++-only parallel render so other Python threads keep
            // running (#1031). Python objects are only built after the
            // release scope closes.
            const auto parsed = parse_extent(extent);
            const pwb::qgis_render::RenderResult result = [&]() {
                py::gil_scoped_release release;
                return bridge.render_sync(parsed, width, height, dpi);
            }();
            return result_to_python(result);
        })
        .def("export_vector", [](const QgisRenderBridge& bridge, const std::string& path,
                                  const std::string& format, const py::sequence& extent,
                                  const int width, const int height, const double dpi) {
            // Same contract as render_sync: synchronous vector export plus
            // file I/O must not stall the interpreter (#1031).
            const auto parsed = parse_extent(extent);
            const std::size_t written = [&]() {
                py::gil_scoped_release release;
                return bridge.export_vector(path, format, parsed, width, height, dpi);
            }();
            return written;
        })
        .def("shutdown", &QgisRenderBridge::shutdown)
        .def("diagnostics", [](const QgisRenderBridge& bridge) {
            const auto diagnostics = bridge.diagnostics();
            py::dict output;
            output["mirror_builds"] = diagnostics.mirror_builds;
            output["mirror_reuses"] = diagnostics.mirror_reuses;
            output["style_reapplies"] = diagnostics.style_reapplies;
            output["feature_deltas"] = diagnostics.feature_deltas;
            output["delta_changed_features"] = diagnostics.delta_changed_features;
            output["delta_removed_features"] = diagnostics.delta_removed_features;
            return output;
        })
        .def_property_readonly("initialized", &QgisRenderBridge::initialized)
        .def_property_readonly(
            "render_active", &QgisRenderBridge::render_active,
            "Whether an async render is in flight. Without a running Qt "
            "event loop on the GUI thread, remains true until cancel_render "
            "or shutdown (#938-5). Use render_sync() for loop-free contexts.")
        .def_property_readonly("version", &QgisRenderBridge::version);

    module.def("legacy_style_to_renderer_xml", &legacy_style_to_renderer_xml,
               py::arg("style"), py::arg("geometry_type"),
               "Build a QGIS renderer XML payload from a legacy VectorStyle dict.");

    module.def("renderer_info", &renderer_info, py::arg("renderer_xml"),
               "Describe a serialized renderer payload (type, symbol_count).");

    module.def("run_renderer_properties_dialog",
               [](const py::dict& request) {
                   return dialog_result_to_python(
                       pwb::qgis_render::run_renderer_properties_dialog(
                           parse_dialog_request(request))
                   );
               },
               py::arg("request"),
               "Open the native QgsRendererPropertiesDialog; returns the updated payload.");

    module.def("run_symbol_selector_dialog",
               [](const py::dict& request, const int symbol_index) {
                   return dialog_result_to_python(
                       pwb::qgis_render::run_symbol_selector_dialog(
                           parse_dialog_request(request), symbol_index)
                   );
               },
               py::arg("request"), py::arg("symbol_index"),
               "Open the native QgsSymbolSelectorDialog for one renderer symbol.");

    module.def("run_style_manager_dialog",
               [](const std::string& style_db_path) {
                   return pwb::qgis_render::run_style_manager_dialog(style_db_path);
               },
               py::arg("style_db_path"),
               "Open the native QgsStyleManagerDialog on a managed style database.");

    auto geometry = module.def_submodule("geometry", "QGIS-backed vector geometry service");
    // Geometry arguments accept GeoJSON dicts or JSON/WKT strings; results are
    // always GeoJSON JSON strings.
    auto geometry_arg = [](const py::handle& value) -> std::string {
        if (py::isinstance<py::str>(value)) {
            return py::cast<std::string>(value);
        }
        return py::module_::import("json").attr("dumps")(value).cast<std::string>();
    };
    auto geometry_list_arg = [geometry_arg](const py::iterable& values) {
        std::vector<std::string> items;
        for (const py::handle item : values) {
            items.push_back(geometry_arg(item));
        }
        return items;
    };
    geometry.def("union", [&geometry_arg](const py::iterable& parts) {
                      std::vector<std::string> items;
                      for (const py::handle item : parts) {
                          items.push_back(geometry_arg(item));
                      }
                      return pwb::qgis_render::geometry_union(items);
                  }, py::arg("geometries"));
    geometry.def("split_by_line", [&geometry_arg](const py::object& target,
                                                   const py::object& cutter) {
                      return pwb::qgis_render::geometry_split_by_line(
                          geometry_arg(target), geometry_arg(cutter));
                  }, py::arg("geometry"), py::arg("cutter"));
    geometry.def("intersection", [&geometry_arg](const py::object& a, const py::object& b) {
                      return pwb::qgis_render::geometry_intersection(
                          geometry_arg(a), geometry_arg(b));
                  });
    geometry.def("difference", [&geometry_arg](const py::object& a, const py::object& b) {
                      return pwb::qgis_render::geometry_difference(
                          geometry_arg(a), geometry_arg(b));
                  });
    geometry.def("symdifference", [&geometry_arg](const py::object& a, const py::object& b) {
                      return pwb::qgis_render::geometry_symdifference(
                          geometry_arg(a), geometry_arg(b));
                  });
    geometry.def("buffer", [&geometry_arg](const py::object& source, const double distance,
                              const int segments) {
                      return pwb::qgis_render::geometry_buffer(
                          geometry_arg(source), distance, segments);
                  }, py::arg("geometry"), py::arg("distance"), py::arg("segments") = 8);
    geometry.def("offset_curve", [&geometry_arg](const py::object& source, const double distance) {
                      return pwb::qgis_render::geometry_offset_curve(
                          geometry_arg(source), distance);
                  });
    geometry.def("simplify", [&geometry_arg](const py::object& source, const double tolerance) {
                      return pwb::qgis_render::geometry_simplify(
                          geometry_arg(source), tolerance);
                  });
    geometry.def("smooth", [&geometry_arg](const py::object& source, const unsigned int iterations,
                              const double offset) {
                      return pwb::qgis_render::geometry_smooth(
                          geometry_arg(source), iterations, offset);
                  }, py::arg("geometry"), py::arg("iterations") = 1, py::arg("offset") = 0.25);
    geometry.def("densify", [&geometry_arg](const py::object& source, const double interval) {
                      return pwb::qgis_render::geometry_densify(
                          geometry_arg(source), interval);
                  });
    geometry.def("make_valid", [&geometry_arg](const py::object& source) {
                      return pwb::qgis_render::geometry_make_valid(geometry_arg(source));
                  });
    geometry.def("is_valid", [&geometry_arg](const py::object& source) {
                      return pwb::qgis_render::geometry_is_valid(geometry_arg(source));
                  });
    geometry.def("multipart_to_singlepart", [&geometry_arg](const py::object& source) {
                      return pwb::qgis_render::geometry_multipart_to_singlepart(
                          geometry_arg(source));
                  });
    geometry.def("singlepart_to_multipart", [&geometry_arg](const py::iterable& parts) {
                      std::vector<std::string> items;
                      for (const py::handle item : parts) {
                          items.push_back(geometry_arg(item));
                      }
                      return pwb::qgis_render::geometry_singlepart_to_multipart(items);
                  });
    geometry.def("clip", [&geometry_arg](const py::object& source, const py::sequence& extent) {
                      return pwb::qgis_render::geometry_clip(
                          geometry_arg(source), parse_extent(extent));
                  });

    auto mapstack = module.def_submodule("mapstack", "QGIS native map stack");
    py::class_<pwb::qgis_render::QgisMapStack>(mapstack, "QgisMapStack")
        .def(py::init<>())
        .def("initialize", &pwb::qgis_render::QgisMapStack::initialize)
        .def_property_readonly("initialized", &pwb::qgis_render::QgisMapStack::initialized)
        .def("project_layer_count", &pwb::qgis_render::QgisMapStack::projectLayerCount)
        .def("shutdown", [](pwb::qgis_render::QgisMapStack& self) {
          py::gil_scoped_acquire gil;
          self.shutdown();
        })
        .def("create_canvas", &pwb::qgis_render::QgisMapStack::createCanvas)
        .def("destroy_canvas", [](pwb::qgis_render::QgisMapStack& self, std::uintptr_t addr) {
          py::gil_scoped_acquire gil;
          self.destroyCanvas(addr);
        })
        .def("set_canvas_white_background", &pwb::qgis_render::QgisMapStack::setCanvasWhiteBackground)
        .def("set_destination_crs", &pwb::qgis_render::QgisMapStack::setDestinationCrs)
        .def("set_canvas_extent", &pwb::qgis_render::QgisMapStack::setCanvasExtent)
        .def("canvas_extent", &pwb::qgis_render::QgisMapStack::canvasExtent)
        .def("zoom_to_full_extent", &pwb::qgis_render::QgisMapStack::zoomToFullExtent)
        .def("zoom_to_previous_extent", &pwb::qgis_render::QgisMapStack::zoomToPreviousExtent)
        .def("zoom_to_next_extent", &pwb::qgis_render::QgisMapStack::zoomToNextExtent)
        .def("refresh_canvas", &pwb::qgis_render::QgisMapStack::refreshCanvas)
        .def("screen_to_map", &pwb::qgis_render::QgisMapStack::screenToMap)
        .def("map_to_screen", &pwb::qgis_render::QgisMapStack::mapToScreen)
        .def("add_vector_layer_geojson",
             [](pwb::qgis_render::QgisMapStack& self, const std::string& name,
                const std::string& geometry_type, const std::string& crs_auth_id,
                const std::string& geojson, const std::string& renderer_xml,
                const std::string& labeling_xml, py::object legacy_style) {
               std::string legacy_json;
               if (!legacy_style.is_none()) {
                   if (py::isinstance<py::str>(legacy_style)) {
                       legacy_json = py::cast<std::string>(legacy_style);
                   } else if (py::isinstance<py::dict>(legacy_style)) {
                       py::object json_mod = py::module_::import("json");
                       legacy_json = json_mod.attr("dumps")(legacy_style).cast<std::string>();
                   } else {
                       throw py::type_error("legacy_style must be dict, JSON string, or None");
                   }
               }
               return self.addVectorLayerGeoJson(name, geometry_type, crs_auth_id, geojson,
                                                 renderer_xml, labeling_xml, legacy_json);
             },
             py::arg("name"), py::arg("geometry_type"), py::arg("crs_auth_id"),
             py::arg("geojson"), py::arg("renderer_xml") = "", py::arg("labeling_xml") = "",
             py::arg("legacy_style") = py::none())
        .def("set_layer_style",
             [](pwb::qgis_render::QgisMapStack& self, const std::string& layer_id,
                const std::string& renderer_xml, const std::string& labeling_xml,
                py::object legacy_style) {
               std::string legacy_json;
               if (!legacy_style.is_none()) {
                   if (py::isinstance<py::str>(legacy_style)) {
                       legacy_json = py::cast<std::string>(legacy_style);
                   } else if (py::isinstance<py::dict>(legacy_style)) {
                       py::object json_mod = py::module_::import("json");
                       legacy_json = json_mod.attr("dumps")(legacy_style).cast<std::string>();
                   } else {
                       throw py::type_error("legacy_style must be dict, JSON string, or None");
                   }
               }
               self.setLayerStyle(layer_id, renderer_xml, labeling_xml, legacy_json);
             },
             py::arg("layer_id"), py::arg("renderer_xml") = "", py::arg("labeling_xml") = "",
             py::arg("legacy_style") = py::none())
        .def("remove_layer", &pwb::qgis_render::QgisMapStack::removeLayer)
        .def("set_layer_visibility", &pwb::qgis_render::QgisMapStack::setLayerVisibility)
        .def("set_layer_opacity", &pwb::qgis_render::QgisMapStack::setLayerOpacity)
        .def("clear_project_layers", &pwb::qgis_render::QgisMapStack::clearProjectLayers)
        .def("upsert_mirror_layer",
             [](pwb::qgis_render::QgisMapStack& self, const std::string& doc_id,
                const std::string& name, const std::string& geometry_type,
                const std::string& crs_auth_id, const std::string& geojson,
                const std::string& renderer_xml, const std::string& labeling_xml,
                py::object legacy_style, bool visible, double opacity) {
               std::string legacy_json;
               if (!legacy_style.is_none()) {
                   if (py::isinstance<py::str>(legacy_style)) {
                       legacy_json = py::cast<std::string>(legacy_style);
                   } else if (py::isinstance<py::dict>(legacy_style)) {
                       py::object json_mod = py::module_::import("json");
                       legacy_json = json_mod.attr("dumps")(legacy_style).cast<std::string>();
                   } else {
                       throw py::type_error("legacy_style must be dict, JSON string, or None");
                   }
               }
               return self.upsertMirrorLayer(doc_id, name, geometry_type, crs_auth_id, geojson,
                                             renderer_xml, labeling_xml, legacy_json, visible, opacity);
             },
             py::arg("doc_id"), py::arg("name"), py::arg("geometry_type"), py::arg("crs_auth_id"),
             py::arg("geojson"), py::arg("renderer_xml") = "", py::arg("labeling_xml") = "",
             py::arg("legacy_style") = py::none(), py::arg("visible") = true, py::arg("opacity") = 1.0)
        .def("remove_mirror_layers_except", &pwb::qgis_render::QgisMapStack::removeMirrorLayersExcept)
        .def("set_mirror_layer_order", &pwb::qgis_render::QgisMapStack::setMirrorLayerOrder)
        .def("set_mirror_layer_visibility", &pwb::qgis_render::QgisMapStack::setMirrorLayerVisibility)
        .def("mirror_order_top_first", &pwb::qgis_render::QgisMapStack::mirrorOrderTopFirst)
        .def("mirror_layer_visibility", &pwb::qgis_render::QgisMapStack::mirrorLayerVisibility)
        .def("tree_echo_suppressed", &pwb::qgis_render::QgisMapStack::treeEchoSuppressed)
        .def("set_map_tool", &pwb::qgis_render::QgisMapStack::setMapTool)
        .def("set_extent_callback",
             [](pwb::qgis_render::QgisMapStack& self, std::uintptr_t canvas, py::function f) {
               self.setExtentCallback(canvas, [f = std::move(f)](double a, double b, double c, double d) {
                 py::gil_scoped_acquire gil;
                 f(a, b, c, d);
               });
             })
        .def("set_xy_callback",
             [](pwb::qgis_render::QgisMapStack& self, std::uintptr_t canvas, py::function f) {
               self.setXyCallback(canvas, [f = std::move(f)](double x, double y) {
                 py::gil_scoped_acquire gil;
                 f(x, y);
               });
             })
        .def("create_layer_tree_view", &pwb::qgis_render::QgisMapStack::createLayerTreeView)
        .def("set_tree_selection_callback",
             [](pwb::qgis_render::QgisMapStack& self, std::uintptr_t tree, py::function f) {
               self.setTreeSelectionCallback(
                   tree, [f = std::move(f)](const std::string& id) {
                     py::gil_scoped_acquire gil;
                     f(id);
                   });
             })
        .def("tree_view_row_count", &pwb::qgis_render::QgisMapStack::treeViewRowCount)
        .def("tree_view_layer_name", &pwb::qgis_render::QgisMapStack::treeViewLayerName)
        .def("tree_view_set_current_row", &pwb::qgis_render::QgisMapStack::treeViewSetCurrentRow);
}
