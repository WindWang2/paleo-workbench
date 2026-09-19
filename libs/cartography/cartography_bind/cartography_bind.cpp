// CONV-27: pybind11 facade over the Qt-free pwb::cartography registries.
//
// Exposes the Python-facing cartography entry points as top-level module
// `pwb_cartography`, consumed by the thin try/except facade
// paleo_workbench/mapping/cartography_native.py (the CONV-20 HAS_CPP
// dispatch pattern):
//
//   list_color_ramps() -> list[str]
//   color_ramp_document(name) -> dict          (unknown -> viridis, parity)
//   evaluate_ramp(name, t) -> str
//   evaluate_ramp_value(name, value, vmin, vmax) -> str
//   list_symbols() -> list[str]
//   symbol_library_document() -> dict          (schema_version 2 + symbols)
//   binding_record(symbol_id) -> dict
//   validate_binding(symbol_id, role, geometry_kind) -> (bool, str)
//   list_templates() -> list[dict]
//   instantiate_template(request: dict) -> dict (composition document)
//   classify_equal_interval(vmin, vmax, n, decimals) -> (list, list)
//   classify_quantile(values, n, decimals) -> (list, list)
//   flatten_qgis_style(style: dict) -> dict
//
// Glue only: dicts/lists/scalars in, plain lists/dicts out. The registry
// errors (unknown symbol / template) propagate as Python exceptions with
// the exact frozen messages.

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <pwb/cartography/cartography.hpp>
#include <pwb/domain/json.hpp>

#include <string>
#include <vector>

namespace py = pybind11;

using pwb::domain::Json;

#ifndef PWB_CARTOGRAPHY_BIND_VERSION
#define PWB_CARTOGRAPHY_BIND_VERSION "0.0.0-dev"
#endif

namespace {

// Python dict -> Json (bool before int; NaN/inf doubles pass through as
// doubles and are the caller's business).
Json to_json(py::handle obj) {
    if (obj.is_none()) return Json(nullptr);
    if (py::isinstance<py::bool_>(obj)) return Json(obj.cast<bool>());
    if (py::isinstance<py::int_>(obj)) return Json(obj.cast<long long>());
    if (py::isinstance<py::float_>(obj)) return Json(obj.cast<double>());
    if (py::isinstance<py::str>(obj)) return Json(obj.cast<std::string>());
    if (py::isinstance<py::list>(obj) || py::isinstance<py::tuple>(obj)) {
        Json arr = Json::array();
        for (py::handle item : obj) arr.push_back(to_json(item));
        return arr;
    }
    if (py::isinstance<py::dict>(obj)) {
        Json out = Json::object();
        py::list items = obj.attr("items")();
        for (py::handle entry : items) {
            py::tuple kv = entry.cast<py::tuple>();
            out[py::str(kv[0]).cast<std::string>()] = to_json(kv[1]);
        }
        return out;
    }
    throw py::type_error("unsupported type for cartography payload");
}

Json request_to_json(const py::dict& request) {
    Json out = Json::object();
    for (auto entry : request) {
        out[py::str(entry.first).cast<std::string>()] =
            to_json(entry.second);
    }
    return out;
}

py::dict json_to_py(const Json& value) {
    py::object parsed = py::module_::import("json")
                            .attr("loads")(value.dump());
    return parsed.cast<py::dict>();
}

py::list json_list_to_py(const Json& value) {
    py::object parsed = py::module_::import("json")
                            .attr("loads")(value.dump());
    return parsed.cast<py::list>();
}

}  // namespace

PYBIND11_MODULE(pwb_cartography, m) {
    m.doc() = "Qt-free cartography registry kernels (CONV-27).";
    m.attr("__version__") = PWB_CARTOGRAPHY_BIND_VERSION;

    m.def("list_color_ramps", []() {
        return pwb::cartography::list_color_ramps();
    });
    m.def("color_ramp_document",
          [](const std::string& name) {
              return json_to_py(
                  pwb::cartography::get_color_ramp(name).to_dict());
          });
    m.def("evaluate_ramp",
          [](const std::string& name, double t) {
              return pwb::cartography::get_color_ramp(name).evaluate(t);
          });
    m.def("evaluate_ramp_value",
          [](const std::string& name, double value, double vmin,
             double vmax) {
              return pwb::cartography::get_color_ramp(name).evaluate_value(
                  value, vmin, vmax);
          });

    m.def("list_symbols", []() {
        py::list ids;
        for (const auto& entry : pwb::cartography::geological_symbols()) {
            ids.append(entry.first);
        }
        return ids;
    });
    m.def("symbol_library_document", []() {
        return json_to_py(pwb::cartography::symbol_library_document());
    });
    m.def("binding_record",
          [](const std::string& symbol_id) {
              // Python parity: the registry lookup surfaces as KeyError.
              try {
                  return json_to_py(
                      pwb::cartography::binding_record(symbol_id));
              } catch (const std::out_of_range& exc) {
                  throw py::key_error(exc.what());
              }
          });
    m.def("validate_binding",
          [](const std::string& symbol_id, const std::string& role,
             const std::string& geometry_kind) {
              const auto& result = pwb::cartography::validate_binding(
                  symbol_id, role, geometry_kind);
              return py::make_tuple(result.first, result.second);
          });

    m.def("list_templates", []() {
        return json_list_to_py(pwb::cartography::template_catalog());
    });
    m.def("instantiate_template",
          [](const py::dict& request) {
              const Json payload = request_to_json(request);
              pwb::cartography::TemplateRequest parsed;
              parsed.template_name = payload.value("template_name", "");
              const Json& map = payload.value("map", Json::object());
              parsed.map.map_document_id = map.value("id", "");
              parsed.map.map_document_title = map.value("title", "");
              parsed.map.map_layer_count = map.value("layer_count", 0LL);
              if (map.contains("extent") && map["extent"].is_array() &&
                  map["extent"].size() == 4) {
                  for (std::size_t i = 0; i < 4; ++i) {
                      parsed.map.extent[i] = map["extent"][i].get<double>();
                  }
              }
              parsed.title = payload.value("title", "");
              parsed.factor_name = payload.value("factor_name", "");
              parsed.unit = payload.value("unit", "");
              parsed.paper_size = payload.value("paper_size", "A4");
              parsed.orientation = payload.value("orientation", "landscape");
              pwb::mapping_document::Composition doc;
              try {
                  doc = pwb::cartography::instantiate_template(parsed);
              } catch (const std::out_of_range& exc) {
                  throw py::key_error(exc.what());
              }
              return json_to_py(pwb::mapping_document::dump_composition(doc));
          });

    m.def("classify_equal_interval",
          [](double vmin, double vmax, long long n, int decimals) {
              const auto result =
                  pwb::cartography::equal_interval_breaks(vmin, vmax, n,
                                                          decimals);
              return py::make_tuple(result.breaks, result.labels);
          });
    m.def("classify_quantile",
          [](const std::vector<double>& values, long long n, int decimals) {
              const auto result = pwb::cartography::quantile_breaks(
                  values, n, decimals);
              return py::make_tuple(result.breaks, result.labels);
          });
    m.def("flatten_qgis_style",
          [](const py::dict& style) {
              return json_to_py(
                  pwb::cartography::flatten_qgis_style(to_json(style)));
          });
}
