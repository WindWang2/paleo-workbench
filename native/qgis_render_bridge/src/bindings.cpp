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

// Qt DOM (v7 raster_renderer_info): AFTER pybind11 per the rule above.
#include <QDomDocument>
#include <QDomElement>

#include <qgis.h>
#include <qgsconfig.h>  // _QGIS_VERSION（capability manifest 的版本串）
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
            // v7 §5: authoritative scalar renderer payload (single-band
            // pseudocolor).  Parsed and validated up front so a bad payload
            // fails the snapshot before any mirror mutates.
            if (data.contains("raster_renderer_xml")) {
                layer.raster_renderer_xml = py::cast<std::string>(data["raster_renderer_xml"]);
            }
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

// ---------------------------------------------------------------------------
// V7 capability manifest：编译期能力注册表（零 QGIS init 成本）。
// Python 侧 capability_model.probe_qgis_capability() 从这里派生
// QgisCapabilitySnapshot——本表是桥能力的唯一权威声明；新增 set_map_tool
// kind / geometry op / 对话框时必须同步本表（test_qgis_capability_manifest
// 钉死 kind 与 set_map_tool 的接受集一致）。
// ---------------------------------------------------------------------------

py::dict capability_manifest() {
    py::dict manifest;
    manifest["contract_version"] = 2;
    manifest["qgis_version"] = std::string(_QGIS_VERSION);
    // set_map_tool kinds（map_stack_service.cpp::setMapTool）。
    py::list native_tools;
    for (const char* kind :
         {"pan", "zoomIn", "zoomOut", "addPoint", "addLine", "addPolygon",
          "vertex", "move", "select", "identify", "measure"}) {
        native_tools.append(kind);
    }
    manifest["native_tools"] = native_tools;
    // geometry 子模块操作（bindings.cpp geometry.def 全集）。
    py::list geometry_ops;
    for (const char* op :
         {"union", "split_by_line", "intersection", "difference", "symdifference",
          "buffer", "offset_curve", "simplify", "smooth", "densify", "make_valid",
          "is_valid", "validate", "reshape", "multipart_to_singlepart",
          "singlepart_to_multipart", "clip",
          // 0.6.0a0 (V10): part operations (QgsGeometry::addPart/deletePart).
          "add_part", "delete_part"}) {
        geometry_ops.append(op);
    }
    manifest["geometry_ops"] = geometry_ops;
    py::list dialogs;
    for (const char* dialog :
         {"renderer_properties", "symbol_selector", "style_manager",
          "layer_properties"}) {
        dialogs.append(dialog);
    }
    manifest["dialogs"] = dialogs;
    // 特性 flag（capability_model.feature() / ToolContext.capability_flags）。
    py::list features;
    for (const char* feature :
         {"snapping_push", "snapping_endpoint", "snapping_intersection",
          "layer_tree", "selection_highlight", "edit_indicator",
          "measure_ellipsoidal", "digitize_crs_guard", "native_capture",
          "native_vertex_move", "native_select_identify",
          // 0.4.0a0 (V8): memory-provider 字段 schema 应用（M1）、
          // 通用行指示器（M5）、legend filter_layers（M8）。
          "provider_fields", "row_indicators", "legend_filter",
          // 0.5.0a0 (V9): topological-editing push in set_snapping_config.
          "snapping_topological_editing",
          // 0.6.0a0 (V10): vertex insert/delete via PwbVertexTool, snap
          // feedback + digitize progress; plus runtime facts / project CRS
          // push / map-settings / provider introspection / style read-back /
          // mirror scale range / explicit current-layer clear / honest
          // scratch CRS (quiet-4326 removal in digitizeToolFor).
          "native_vertex_insert", "native_vertex_delete", "snap_feedback",
          "digitize_progress",
          "runtime_facts", "project_crs_push", "map_settings_facts",
          "provider_introspection", "style_readback", "layer_scale_range",
          "current_layer_clear", "digitize_scratch_honest_crs"}) {
        features.append(feature);
    }
    manifest["features"] = features;
    return manifest;
}

PYBIND11_MODULE(qgis_render_bridge, module) {
    module.doc() = "Narrow optional C++ QGIS map-render bridge";
    // Build metadata for freshness checks (#938-8): aligns with
    // paleo_workbench.__version__; previously missing and drifted.
    // 0.3.0a0 (V7): capability_manifest + native measure + geometry
    // validate/reshape + snapping endpoint/intersection.
    // 0.4.0a0 (V8): provider field-schema application (fields_json →
    // QgsFields/constraints/widgets), generic row indicators, legend
    // filter_layers.
    // 0.5.0a0 (V9): topological_editing push via set_snapping_config,
    // canvas_scale / canvas_destination_crs introspection.
    // 0.6.0a0 (V10): vertex insert/delete callbacks, snap indicator
    // feedback, digitize progress, geometry add_part/delete_part;
    // runtime_facts / set_project_crs / canvas_map_units /
    // canvas_output_dpi / mirror_provider_facts / mirror_style_json /
    // upsert scale-range channel / explicit current-layer clear / honest
    // digitize scratch CRS.
    // 0.8.0a0 (topo-editing M2): vertex all-layers scope, topological
    // point scatter, avoid-intersections (config + vertex/move
    // replication), canvas tracer.
    // 0.7.0a0 (topo-editing M1): mirror-layer native editing (start/
    // commit/rollback/undo/redo), committed delta callback, add mirror
    // feature, mirror_features_json unlimited readback (limit<=0).
    // 0.9.0a0 (topo-editing M3): split_mirror_features /
    // merge_mirror_features (native buffer split/merge + attribute
    // inheritance; neighbor topo-points on split).
    module.attr("__version__") = "0.9.0a0";
    module.attr("__build_commit__") = "unknown";
    py::register_exception<GeometryServiceError>(module, "QgisGeometryError");

    // V7 能力清单（见上方注册表注释）。cheap probe：不初始化 QGIS 运行时。
    module.def("capability_manifest", &capability_manifest,
               "Compile-time capability registry of this bridge build "
               "(native tool kinds, geometry ops, dialogs, feature flags).");

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

    module.def("build_scalar_renderer_xml",
               [](const std::string& spec_json) {
                   return pwb::qgis_render::build_scalar_renderer_xml(spec_json);
               },
               py::arg("spec_json"),
               "v7: build a QGIS single-band pseudocolor renderer XML from a "
               "scalar style JSON (ramp items + min/max + mode). Authored by "
               "QGIS's own serializer; classification is host-side.");

    module.def("raster_renderer_info",
               [](const std::string& renderer_xml) -> py::object {
                   QDomDocument doc;
                   if (!doc.setContent(QString::fromStdString(renderer_xml), true)) {
                       return py::none();
                   }
                   QDomElement elem = doc.documentElement();
                   if (elem.tagName() != QStringLiteral("rasterrenderer")) {
                       elem = doc.firstChildElement(QStringLiteral("rasterrenderer"));
                   }
                   if (elem.isNull()) return py::none();
                   py::dict info;
                   info["type"] = elem.attribute(QStringLiteral("type")).toStdString();
                   bool ok = false;
                   const int items = elem.attribute(
                       QStringLiteral("colorrampshader")).toInt(&ok);
                   if (!ok) {
                       // R3-6: QGIS nests <item> under
                       // rastershader/colorrampshader — count ALL descendant
                       // items, not just direct children.
                       info["item_count"] = static_cast<int>(
                           elem.elementsByTagName(
                               QStringLiteral("item")).size());
                   } else {
                       info["item_count"] = items;
                   }
                   return std::move(info);
               },
               py::arg("renderer_xml"),
               "v7: inspect a raster renderer XML payload {type, item_count} "
               "or None when invalid.");

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
    geometry.def("validate", [&geometry_arg](const py::object& source) {
                      // V7 详细校验：[{"where": [x,y]|null, "message": str}, ...]
                      return py::module_::import("json")
                          .attr("loads")(
                              pwb::qgis_render::geometry_validate(geometry_arg(source)))
                          .cast<py::list>();
                  }, py::arg("geometry"));
    geometry.def("reshape", [&geometry_arg](const py::object& source,
                                            const py::object& line) {
                      return pwb::qgis_render::geometry_reshape(
                          geometry_arg(source), geometry_arg(line));
                  }, py::arg("geometry"), py::arg("reshape_line"));
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
    // V10 部件操作：QgsGeometry::addPart / deletePart（新整体几何 GeoJSON）。
    geometry.def("add_part", [&geometry_arg](const py::object& source,
                                             const py::object& part) {
                      const std::string source_json = geometry_arg(source);
                      const std::string part_json = geometry_arg(part);
                      return pwb::qgis_render::geometry_add_part(source_json, part_json);
                  },
                 py::arg("geometry"), py::arg("part"));
    geometry.def("delete_part", [&geometry_arg](const py::object& source, int part_index) {
                      const std::string source_json = geometry_arg(source);
                      return pwb::qgis_render::geometry_delete_part(source_json, part_index);
                  },
                 py::arg("geometry"), py::arg("part_index"));
    geometry.def("clip", [&geometry_arg](const py::object& source, const py::sequence& extent) {
                      return pwb::qgis_render::geometry_clip(
                          geometry_arg(source), parse_extent(extent));
                  });

    auto mapstack = module.def_submodule("mapstack", "QGIS native map stack");
    py::class_<pwb::qgis_render::QgisMapStack>(mapstack, "QgisMapStack")
        .def(py::init<>())
        .def("initialize", &pwb::qgis_render::QgisMapStack::initialize,
             py::arg("display") = false)
        .def_property_readonly("initialized", &pwb::qgis_render::QgisMapStack::initialized)
        .def("project_layer_count", &pwb::qgis_render::QgisMapStack::projectLayerCount)
        .def("canvas_layer_count", &pwb::qgis_render::QgisMapStack::canvasLayerCount)
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
        // V9 W1/W7: canvas-authority scale + destination-CRS introspection
        // (ToolContext.scale_denominator source; digitize-commit CRS guard).
        .def("canvas_scale", &pwb::qgis_render::QgisMapStack::canvasScale)
        .def("canvas_destination_crs",
             &pwb::qgis_render::QgisMapStack::canvasDestinationCrs)
        // V10 M-A/M-C/M-O: runtime facts / project CRS push / map facts.
        .def("runtime_facts",
             [](pwb::qgis_render::QgisMapStack& self) {
               const std::string raw = self.runtimeFacts();
               return py::module_::import("json").attr("loads")(raw).cast<py::dict>();
             },
             "V10: one-shot runtime health facts (versions, paths, providers, "
             "CRS + transform probes) as a dict.")
        .def("set_project_crs",
             &pwb::qgis_render::QgisMapStack::setProjectCrs,
             py::arg("authid"),
             "V10: push the owning QgsProject CRS (+derived ellipsoid); "
             "returns an error string, empty on success.")
        .def("canvas_map_units",
             &pwb::qgis_render::QgisMapStack::canvasMapUnits)
        .def("canvas_output_dpi",
             &pwb::qgis_render::QgisMapStack::canvasOutputDpi)
        .def("set_canvas_extent", &pwb::qgis_render::QgisMapStack::setCanvasExtent)
        .def("canvas_extent", &pwb::qgis_render::QgisMapStack::canvasExtent)
        .def("zoom_to_full_extent", &pwb::qgis_render::QgisMapStack::zoomToFullExtent)
        .def("zoom_to_previous_extent", &pwb::qgis_render::QgisMapStack::zoomToPreviousExtent)
        .def("zoom_to_next_extent", &pwb::qgis_render::QgisMapStack::zoomToNextExtent)
        .def("refresh_canvas", &pwb::qgis_render::QgisMapStack::refreshCanvas)
        .def("is_canvas_rendering", &pwb::qgis_render::QgisMapStack::isCanvasRendering)
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
                py::object legacy_style, bool visible, double opacity,
                bool is_reference, bool is_editable, bool reference_snap,
                std::uint64_t data_revision, const std::string& delta_json,
                const std::string& fields_json, double min_scale,
                double max_scale) {
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
                                             renderer_xml, labeling_xml, legacy_json, visible, opacity,
                                             is_reference, is_editable, reference_snap,
                                             data_revision, delta_json, fields_json,
                                             min_scale, max_scale);
             },
             py::arg("doc_id"), py::arg("name"), py::arg("geometry_type"), py::arg("crs_auth_id"),
             py::arg("geojson"), py::arg("renderer_xml") = "", py::arg("labeling_xml") = "",
             py::arg("legacy_style") = py::none(), py::arg("visible") = true, py::arg("opacity") = 1.0,
             py::arg("is_reference") = false, py::arg("is_editable") = false,
             py::arg("reference_snap") = false,
             py::arg("data_revision") = 0, py::arg("delta") = "",
             py::arg("fields_json") = "",
             py::arg("min_scale") = 0.0, py::arg("max_scale") = 0.0)
        .def("upsert_raster_mirror_layer",
             &pwb::qgis_render::QgisMapStack::upsertRasterMirrorLayer,
             py::arg("doc_id"), py::arg("name"), py::arg("source_path"),
             py::arg("crs_auth_id") = "", py::arg("renderer_xml") = "",
             py::arg("visible") = true, py::arg("opacity") = 1.0,
             py::arg("is_reference") = false,
             "v7: upsert a scalar raster mirror (float GeoTIFF + optional "
             "pseudocolor renderer XML); style-only changes reapply the "
             "renderer without touching the raster source.")
        .def("remove_mirror_layers_except", &pwb::qgis_render::QgisMapStack::removeMirrorLayersExcept)
        .def("set_mirror_layer_order", &pwb::qgis_render::QgisMapStack::setMirrorLayerOrder)
        .def("set_mirror_layer_visibility", &pwb::qgis_render::QgisMapStack::setMirrorLayerVisibility)
        .def("mirror_order_top_first", &pwb::qgis_render::QgisMapStack::mirrorOrderTopFirst)
        .def("mirror_layer_visibility", &pwb::qgis_render::QgisMapStack::mirrorLayerVisibility)
        .def("tree_echo_suppressed", &pwb::qgis_render::QgisMapStack::treeEchoSuppressed)
        .def("set_map_tool", &pwb::qgis_render::QgisMapStack::setMapTool)
        .def("set_digitize_callback",
             [](pwb::qgis_render::QgisMapStack& self, std::uintptr_t canvas,
                py::function f) {
               self.setDigitizeCallback(
                   canvas, [f = std::move(f)](const std::string& status,
                                              const std::string& geom) {
                     py::gil_scoped_acquire gil;
                     f(status, geom);
                   });
             })
        // 拓扑编辑迁移 M1（§2）：committed 增量回传（commit 期间同步触发）。
        .def("set_committed_callback",
             [](pwb::qgis_render::QgisMapStack& self, std::uintptr_t canvas,
                py::function f) {
               self.setCommittedCallback(
                   canvas, [f = std::move(f)](const std::string& doc_id,
                                              const std::string& payload) {
                     py::gil_scoped_acquire gil;
                     f(doc_id, payload);
                   });
             })
        .def("start_mirror_layer_editing",
             &pwb::qgis_render::QgisMapStack::startMirrorLayerEditing,
             py::arg("doc_id"),
             "M1 topo-editing: start a native edit session on the mirror "
             "layer (committed* signals captured for host writeback).")
        .def("commit_mirror_layer",
             &pwb::qgis_render::QgisMapStack::commitMirrorLayer,
             py::arg("doc_id"),
             "M1 topo-editing: commit the layer's edit buffer; fires the "
             "committed-callback with the change delta. Failure keeps the "
             "session open.")
        .def("roll_back_mirror_layer",
             &pwb::qgis_render::QgisMapStack::rollBackMirrorLayer,
             py::arg("doc_id"),
             "M1 topo-editing: roll the edit buffer back to the session-"
             "opening snapshot baseline.")
        .def("mirror_layer_editing",
             &pwb::qgis_render::QgisMapStack::mirrorLayerEditing,
             py::arg("doc_id"),
             "M1 topo-editing: True while the mirror layer holds a native "
             "edit session.")
        .def("undo_mirror_edit",
             &pwb::qgis_render::QgisMapStack::undoMirrorEdit,
             py::arg("doc_id"),
             "M1 topo-editing: undo one edit-command macro on the layer's "
             "undo stack.")
        .def("redo_mirror_edit",
             &pwb::qgis_render::QgisMapStack::redoMirrorEdit,
             py::arg("doc_id"),
             "M1 topo-editing: redo one edit-command macro.")
        .def("set_vertex_edit_scope",
             [](pwb::qgis_render::QgisMapStack& self,
                std::uintptr_t canvas, bool all_layers) {
               self.setVertexEditScope(canvas, all_layers);
             },
             py::arg("canvas"), py::arg("all_layers"),
             "M2 topo-editing: vertex tool scope (false = current layer, "
             "true = all layers; cross-layer shared nodes, same-CRS only).")
        .def("set_tracing_enabled",
             [](pwb::qgis_render::QgisMapStack& self,
                std::uintptr_t canvas, bool enabled) {
               self.setTracingEnabled(canvas, enabled);
             },
             py::arg("canvas"), py::arg("enabled"),
             "M2 topo-editing: register QgsMapCanvasTracer on the canvas and "
             "toggle tracing (all capture tools pick it up for free).")
        .def("add_mirror_feature",
             &pwb::qgis_render::QgisMapStack::addMirrorFeature,
             py::arg("doc_id"), py::arg("geojson_feature"),
             "M1 topo-editing: add one GeoJSON feature into the edit buffer "
             "(digitize routing); one undoable macro 'Added feature'.")
        .def("split_mirror_features",
             &pwb::qgis_render::QgisMapStack::splitMirrorFeatures,
             py::arg("doc_id"), py::arg("curve_geojson"),
             py::arg("feature_ids_json") = "",
             "M3 topo-editing: split selected (or listed) features by a "
             "LineString curve; topologicalEditing + neighbor topo points; "
             "one undoable macro 'Features split'.")
        .def("merge_mirror_features",
             &pwb::qgis_render::QgisMapStack::mergeMirrorFeatures,
             py::arg("doc_id"), py::arg("feature_ids_json"),
             py::arg("attrs_json") = "",
             "M3 topo-editing: merge listed features (union + attributes); "
             "one undoable macro 'Merged features'.")
        .def("set_edit_pick_callback",
             [](pwb::qgis_render::QgisMapStack& self, std::uintptr_t canvas,
                py::function f) {
               self.setEditPickCallback(
                   canvas, [f = std::move(f)](const std::string& action,
                                              const std::string& payload) {
                     py::gil_scoped_acquire gil;
                     f(action, payload);
                   });
             })
        .def("set_selection_callback",
             [](pwb::qgis_render::QgisMapStack& self, std::uintptr_t canvas,
                py::function f) {
               self.setSelectionCallback(
                   canvas, [f = std::move(f)](const std::string& action,
                                              const std::string& payload) {
                     py::gil_scoped_acquire gil;
                     f(action, payload);
                   });
             })
        .def("set_measure_callback",
             [](pwb::qgis_render::QgisMapStack& self, std::uintptr_t canvas,
                py::function f) {
               self.setMeasureCallback(
                   canvas, [f = std::move(f)](const std::string& action,
                                              const std::string& payload) {
                     py::gil_scoped_acquire gil;
                     f(action, payload);
                   });
             })
        .def("set_current_layer",
             &pwb::qgis_render::QgisMapStack::setCurrentLayer)
        .def("highlight_features",
             &pwb::qgis_render::QgisMapStack::highlightFeatures)
        .def("clear_highlights",
             &pwb::qgis_render::QgisMapStack::clearHighlights)
        .def("highlight_count",
             &pwb::qgis_render::QgisMapStack::highlightCount)
        .def("set_snapping_config",
             &pwb::qgis_render::QgisMapStack::setSnappingConfig)
        .def("snap_to_map",
             [](pwb::qgis_render::QgisMapStack& self, std::uintptr_t canvas,
                double x, double y) {
               const std::string raw = self.snapToMap(canvas, x, y);
               return py::module_::import("json").attr("loads")(raw).cast<py::dict>();
             },
             py::arg("canvas"), py::arg("x"), py::arg("y"))
        .def("native_tool_busy",
             &pwb::qgis_render::QgisMapStack::nativeToolBusy)
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
        .def("tree_view_set_current_row", &pwb::qgis_render::QgisMapStack::treeViewSetCurrentRow)
        .def("tree_view_set_row_checked", &pwb::qgis_render::QgisMapStack::treeViewSetRowChecked)
        .def("tree_view_rename_row", &pwb::qgis_render::QgisMapStack::treeViewRenameRow)
        .def("tree_view_move_row", &pwb::qgis_render::QgisMapStack::treeViewMoveRow)
        .def("set_tree_change_callback",
             [](pwb::qgis_render::QgisMapStack& self, std::uintptr_t tree, py::function f) {
               self.setTreeChangeCallback(
                   tree, [f = std::move(f)](const std::string& payload) {
                     py::gil_scoped_acquire gil;
                     f(payload);
                   });
             })
        .def("set_tree_menu_callback",
             [](pwb::qgis_render::QgisMapStack& self, std::uintptr_t tree, py::function f) {
               self.setTreeMenuCallback(
                   tree, [f = std::move(f)](const std::string& key, const std::string& doc) {
                     py::gil_scoped_acquire gil;
                     f(key, doc);
                   });
             })
        .def("set_tree_expand_callback",
             [](pwb::qgis_render::QgisMapStack& self, std::uintptr_t tree, py::function f) {
               self.setTreeExpandCallback(
                   tree, [f = std::move(f)](const std::string& node_id, bool expanded) {
                     py::gil_scoped_acquire gil;
                     f(node_id, expanded);
                   });
             })
        // ------------------------------------------------------ V5 layer groups
        .def("group_exists", &pwb::qgis_render::QgisMapStack::groupExists,
             py::arg("group_id"))
        .def("upsert_group", &pwb::qgis_render::QgisMapStack::upsertGroup,
             py::arg("group_id"), py::arg("name"), py::arg("parent_group_id") = "")
        .def("remove_groups_except",
             &pwb::qgis_render::QgisMapStack::removeGroupsExcept,
             py::arg("group_ids"))
        .def("rename_group", &pwb::qgis_render::QgisMapStack::renameGroup)
        .def("set_group_visibility",
             &pwb::qgis_render::QgisMapStack::setGroupVisibility)
        .def("move_layer_to_group",
             &pwb::qgis_render::QgisMapStack::moveLayerToGroup,
             py::arg("doc_id"), py::arg("group_id"), py::arg("index"))
        .def("move_group", &pwb::qgis_render::QgisMapStack::moveGroup,
             py::arg("group_id"), py::arg("parent_group_id"), py::arg("index"))
        .def("tree_snapshot_json",
             &pwb::qgis_render::QgisMapStack::treeSnapshotJson)
        // V8 M1：镜像层已应用 provider schema 的 JSON 自省事实。
        .def("mirror_provider_facts",
             [](pwb::qgis_render::QgisMapStack& self, const std::string& doc_id) {
               const std::string raw = self.mirrorProviderFacts(doc_id);
               return py::module_::import("json").attr("loads")(raw).cast<py::dict>();
             },
             py::arg("doc_id"),
             "V10 M-H: provider capability snapshot for a mirrored layer.")
        .def("mirror_style_json",
             [](pwb::qgis_render::QgisMapStack& self, const std::string& doc_id) {
               const std::string raw = self.mirrorStyleJson(doc_id);
               return py::module_::import("json").attr("loads")(raw).cast<py::dict>();
             },
             py::arg("doc_id"),
             "V10 M-K: applied renderer/labeling XML read-back.")
        .def("mirror_layer_schema_json",
             &pwb::qgis_render::QgisMapStack::mirrorLayerSchemaJson,
             py::arg("doc_id"))
        // V8 M1：镜像层真实存储要素 + typed 属性的自省（数据侧）。
        .def("mirror_features_json",
             &pwb::qgis_render::QgisMapStack::mirrorFeaturesJson,
             py::arg("doc_id"), py::arg("limit") = 16)
        .def("apply_tree_placements",
             &pwb::qgis_render::QgisMapStack::applyTreePlacements,
             py::arg("placements_json"))
        .def("set_group_expanded",
             &pwb::qgis_render::QgisMapStack::setGroupExpanded)
        .def("zoom_to_layer", &pwb::qgis_render::QgisMapStack::zoomToLayer)
        .def("set_edit_indicator", &pwb::qgis_render::QgisMapStack::setEditIndicator)
        .def("edit_indicator_count", &pwb::qgis_render::QgisMapStack::editIndicatorCount)
        // V8 M5: 通用行指示器（kinds 与 host state_language 装饰词汇对齐）。
        .def("set_row_indicators", &pwb::qgis_render::QgisMapStack::setRowIndicators,
             py::arg("tree"), py::arg("doc_id"), py::arg("kinds_json"))
        .def("row_indicator_count", &pwb::qgis_render::QgisMapStack::rowIndicatorCount,
             py::arg("tree"), py::arg("doc_id"), py::arg("kind") = "")
        .def("tree_view_select_doc", &pwb::qgis_render::QgisMapStack::treeViewSelectDoc)
        .def("set_mirror_layer_opacity", &pwb::qgis_render::QgisMapStack::setMirrorLayerOpacity)
        .def("exec_layer_properties",
             [](pwb::qgis_render::QgisMapStack& self, std::uintptr_t canvas,
                const std::string& doc_id) {
               auto raw = self.execLayerProperties(canvas, doc_id);
               py::dict out;
               out["ok"] = raw["ok"] == "1";
               if (raw["ok"] == "1") {
                 out["renderer_xml"] = raw["renderer_xml"];
                 out["labeling_xml"] = raw["labeling_xml"];
                 out["opacity"] = std::stod(raw["opacity"]);
                 out["name"] = raw["name"];
               }
               return out;
             })
        .def("write_project_xml", &pwb::qgis_render::QgisMapStack::writeProjectXml)
        .def("apply_project_xml", &pwb::qgis_render::QgisMapStack::applyProjectXml)
        .def("layout_export",
             &pwb::qgis_render::QgisMapStack::layoutExport,
             py::arg("spec_json"), py::arg("output_path"),
             py::arg("format") = "pdf", py::arg("dpi") = 300.0);
}
