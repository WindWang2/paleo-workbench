// Qt-free layout-export kernel (CONV-29) — implementation.
// Python source of truth: paleo_workbench/mapping/layout_export.py
// (frozen by tools/oracle/generate_layout_export_fixtures.py).

#include <pwb/layout_export/layout_export.hpp>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace pwb::layout_export {

namespace {

const char* const kNativeTypes[] = {
    "main_map", "legend",  "north_arrow",  "scale_bar",     "title",
    "text",     "annotation", "datasource", "time_credits",
    "strat_labels", "metadata", "subtitle", "image", "neatline", "grid"};

const char* const kHybridTypes[] = {"timescale", "inset_map", "stat_chart",
                                    "profile", "fault_symbols",
                                    "lithology_legend"};

const char* const kLegendBackedTypes[] = {"colorbar", "facies_legend",
                                          "well_legend"};

std::string join(const std::vector<std::string>& parts,
                 const std::string& sep) {
    std::string out;
    for (std::size_t i = 0; i < parts.size(); ++i) {
        if (i != 0) out += sep;
        out += parts[i];
    }
    return out;
}

// Python-written documents parse their integers as unsigned; the domain
// comparator is strict about that distinction, so the kernel emits
// integers in the same shape (same convention as the CONV-02 kernel).
Json py_int_json(long long value) {
    if (value >= 0) return Json(static_cast<std::uint64_t>(value));
    return Json(value);
}

// Python str.strip() (ASCII whitespace — the strip targets here are unit
// labels).
std::string py_strip(const std::string& text) {
    const char* ws = " \t\n\r\f\v";
    const std::size_t start = text.find_first_not_of(ws);
    if (start == std::string::npos) return "";
    const std::size_t end = text.find_last_not_of(ws);
    return text.substr(start, end - start + 1);
}

// Python str(value) for a JSON scalar (used by the metadata fields renderer
// and the property fallbacks). Objects/arrays fall back to compact JSON —
// the Python str(dict/list) form is a repr artifact the product never writes.
std::string python_str(const Json& value) {
    if (value.is_null()) return "None";
    if (value.is_boolean()) return value.get<bool>() ? "True" : "False";
    if (value.is_number_integer()) return std::to_string(value.get<long long>());
    if (value.is_number_float()) return Json(value).dump();
    if (value.is_string()) return value.get<std::string>();
    return value.dump();
}

// Python repr of a str: single quotes, backslashes and single quotes
// escaped (definition further below; used by py_float_or's error).
std::string py_repr(const std::string& text);

// Python truthiness for a JSON value (null/false/0/""/empty container are
// falsy — the `or` fallbacks in the Python property reads).
bool py_truthy(const Json& value) {
    if (value.is_null()) return false;
    if (value.is_boolean()) return value.get<bool>();
    if (value.is_number()) return value.get<double>() != 0.0;
    if (value.is_string()) return !value.get<std::string>().empty();
    if (value.is_array() || value.is_object()) return !value.empty();
    return true;
}

// Python `str(props.get(key) or default)`: falsy JSON values take the
// default; truthy non-strings are str()'d.
std::string py_str_or(const Json& props, const char* key,
                      const std::string& fallback) {
    if (!props.is_object()) return fallback;
    const auto it = props.find(key);
    if (it == props.end() || !py_truthy(*it)) return fallback;
    return python_str(*it);
}

// Python `float(props.get(key) or default)` (falsy → default; numeric
// strings parse; True → 1.0). (py_repr is defined further below.)
double py_float_or(const Json& props, const char* key, double fallback) {
    if (!props.is_object()) return fallback;
    const auto it = props.find(key);
    if (it == props.end() || !py_truthy(*it)) return fallback;
    if (it->is_boolean()) return 1.0;
    if (it->is_number_integer()) return static_cast<double>(it->get<long long>());
    if (it->is_number_float()) return it->get<double>();
    if (it->is_string()) {
        const std::string text = it->get<std::string>();
        try {
            std::size_t consumed = 0;
            const double v = std::stod(text, &consumed);
            const bool only_space = consumed == text.size()
                || text.find_first_not_of(" \t\n\r\f\v", consumed)
                    == std::string::npos;
            if (!only_space) throw std::invalid_argument("trailing");
            // "0" is a TRUTHY string, so float("0") is 0.0 (no fallback).
            return v;
        } catch (const std::invalid_argument&) {
            throw std::invalid_argument("could not convert string to float: "
                                        + py_repr(text));
        } catch (const std::exception&) {
            throw std::invalid_argument("could not convert string to float: "
                                        + py_repr(text));
        }
    }
    return fallback;
}

// Python %g / %.Ng formatting (both route through the same double→shortest
// exponent-style rendering).
std::string format_g(double value, int precision) {
    char buffer[64];
    const std::string spec = "%." + std::to_string(precision) + "g";
    std::snprintf(buffer, sizeof(buffer), spec.c_str(), value);
    return buffer;
}

std::string format_f0(double value) {
    char buffer[64];
    std::snprintf(buffer, sizeof(buffer), "%.0f", value);
    return buffer;
}

// Python repr of a str: single quotes, backslashes and single quotes escaped.
std::string py_repr(const std::string& text) {
    std::string out = "'";
    for (const char c : text) {
        if (c == '\'' || c == '\\') out += '\\';
        out += c;
    }
    out += "'";
    return out;
}

bool layer_type_in(const MirrorLayer& layer,
                   std::initializer_list<const char*> names) {
    for (const char* name : names) {
        if (layer.layer_type == name) return true;
    }
    return false;
}

// style.renderer == "categorized" (the _FACIES_LEGEND categorized-vector
// clause; a non-object style reads as renderer "").
bool is_categorized_vector(const MirrorLayer& layer) {
    if (layer.layer_type != "vector" || !layer.style.is_object()) return false;
    const auto it = layer.style.find("renderer");
    return it != layer.style.end() && it->is_string()
        && it->get<std::string>() == "categorized";
}

std::vector<std::string> sorted_distinct(std::vector<std::string> values) {
    std::set<std::string> unique(values.begin(), values.end());
    return std::vector<std::string>(unique.begin(), unique.end());
}

}  // namespace

// ---------------------------------------------------------------------------
// Classification tables
// ---------------------------------------------------------------------------

std::string native_wire_type(const std::string& element_type) {
    if (element_type == "main_map") return "map";
    if (element_type == "legend") return "legend";
    if (element_type == "north_arrow") return "north_arrow";
    if (element_type == "scale_bar") return "scalebar";
    if (element_type == "image") return "picture";
    if (element_type == "neatline") return "shape";
    if (element_type == "grid") return "map_grid";
    for (const char* label_type : {"title", "text", "annotation", "datasource",
                                   "time_credits", "strat_labels", "metadata",
                                   "subtitle"}) {
        if (element_type == label_type) return "label";
    }
    return "";
}

bool is_hybrid_type(const std::string& element_type) {
    for (const char* name : kHybridTypes) {
        if (element_type == name) return true;
    }
    return false;
}

bool is_legend_backed_type(const std::string& element_type) {
    for (const char* name : kLegendBackedTypes) {
        if (element_type == name) return true;
    }
    return false;
}

const std::vector<std::string>& hybrid_type_names() {
    static const std::vector<std::string> kNames(kHybridTypes,
                                                 kHybridTypes + 6);
    return kNames;
}

// ---------------------------------------------------------------------------
// Mirror description
// ---------------------------------------------------------------------------

std::vector<MirrorLayer> normalize_mirror_layers(const Json& mirror_layers) {
    Json layers = Json::array();
    if (mirror_layers.is_array()) {
        layers = mirror_layers;
    } else if (mirror_layers.is_object()) {
        const auto it = mirror_layers.find("layers");
        if (it != mirror_layers.end() && it->is_array()) layers = *it;
    } else {
        return {};
    }
    std::vector<MirrorLayer> out;
    out.reserve(layers.size());
    for (const Json& entry : layers) {
        MirrorLayer layer;
        if (entry.is_object()) {
            // Python: str(_layer_field(layer, key, "") or "") — falsy
            // values (0, false, [], missing) all read as "".
            const auto id = entry.find("id");
            if (id != entry.end() && py_truthy(*id)) layer.id = python_str(*id);
            const auto type = entry.find("layer_type");
            if (type != entry.end() && py_truthy(*type)) {
                layer.layer_type = python_str(*type);
            }
            const auto style = entry.find("style");
            if (style != entry.end()) layer.style = *style;
        }
        out.push_back(std::move(layer));
    }
    return out;
}

bool mirror_proves(const std::string& element_type,
                   const std::vector<MirrorLayer>& mirror) {
    if (element_type == "colorbar") {
        for (const MirrorLayer& layer : mirror) {
            if (layer.layer_type == "scalar_grid") return true;
        }
        return false;
    }
    if (element_type == "facies_legend") {
        for (const MirrorLayer& layer : mirror) {
            if (layer_type_in(layer, {"polygon", "facies"})) return true;
            if (is_categorized_vector(layer)) return true;
        }
        return false;
    }
    if (element_type == "well_legend") {
        for (const MirrorLayer& layer : mirror) {
            if (layer_type_in(layer, {"well_point", "well"})) return true;
        }
        return false;
    }
    return false;
}

std::vector<std::string> legend_backed_types(
    const std::vector<MirrorLayer>& mirror) {
    std::vector<std::string> proven;
    // Enumerate in the Python set-iteration output order used by callers
    // that sort anyway; callers needing order sort explicitly.
    for (const char* name : kLegendBackedTypes) {
        if (mirror_proves(name, mirror)) proven.emplace_back(name);
    }
    return proven;
}

std::vector<std::string> legend_filter_doc_ids(
    const std::string& element_type, const std::vector<MirrorLayer>& mirror) {
    std::vector<std::string> ids;
    auto push_id = [&ids](const MirrorLayer& layer) {
        ids.push_back(layer.id);
    };
    if (element_type == "colorbar") {
        for (const MirrorLayer& layer : mirror) {
            if (layer.layer_type == "scalar_grid") push_id(layer);
        }
    } else if (element_type == "facies_legend") {
        for (const MirrorLayer& layer : mirror) {
            if (layer_type_in(layer, {"polygon", "facies"})
                || is_categorized_vector(layer)) {
                push_id(layer);
            }
        }
    } else if (element_type == "well_legend") {
        for (const MirrorLayer& layer : mirror) {
            if (layer_type_in(layer, {"well_point", "well"})) push_id(layer);
        }
    }
    return ids;
}

// ---------------------------------------------------------------------------
// Spec building
// ---------------------------------------------------------------------------

std::vector<const ComposerElement*> visible_elements(const Composition& doc) {
    std::vector<const ComposerElement*> visible;
    for (const ComposerElement& element : doc.elements) {
        if (element.visible) visible.push_back(&element);
    }
    std::stable_sort(visible.begin(), visible.end(),
                     [](const ComposerElement* a, const ComposerElement* b) {
                         return a->z_index < b->z_index;
                     });
    return visible;
}

std::vector<std::string> hybrid_element_types(const Composition& doc,
                                              const Json& mirror_layers) {
    const std::vector<MirrorLayer> mirror =
        normalize_mirror_layers(mirror_layers);
    const std::vector<std::string> proven = legend_backed_types(mirror);
    std::vector<std::string> types;
    for (const ComposerElement* element : visible_elements(doc)) {
        const std::string& type = element->element_type;
        if (!native_wire_type(type).empty()) continue;
        if (is_legend_backed_type(type)
            && std::find(proven.begin(), proven.end(), type) != proven.end()) {
            continue;
        }
        types.push_back(type);
    }
    return sorted_distinct(std::move(types));
}

Json build_layout_spec(const Composition& doc, const BuildSpecInput& input,
                       std::vector<std::string>* warnings) {
    auto warn = [warnings](std::string message) {
        if (warnings != nullptr) warnings->push_back(std::move(message));
    };
    const std::vector<MirrorLayer> mirror =
        normalize_mirror_layers(input.mirror_layers);
    const std::vector<std::string> proven = legend_backed_types(mirror);
    const auto is_proven = [&proven](const std::string& type) {
        return std::find(proven.begin(), proven.end(), type) != proven.end();
    };

    // Fail-closed gate: every visible element must have a native layout
    // counterpart (or a proven legend-backed mapping).
    std::vector<std::string> unmapped;
    for (const ComposerElement* element : visible_elements(doc)) {
        if (native_wire_type(element->element_type).empty() && !is_proven(element->element_type)) {
            unmapped.push_back(element->element_type);
        }
    }
    if (!unmapped.empty()) {
        throw std::invalid_argument(
            "composition has elements with no native layout counterpart: "
            + join(sorted_distinct(std::move(unmapped)), ", "));
    }

    std::vector<std::string> legend_backed_present;
    for (const ComposerElement* element : visible_elements(doc)) {
        if (is_proven(element->element_type)) {
            legend_backed_present.push_back(element->element_type);
        }
    }
    legend_backed_present = sorted_distinct(std::move(legend_backed_present));
    if (!legend_backed_present.empty()) {
        warn(join(legend_backed_present, ", ")
             + " mapped to the native legend bound to the main map with a "
               "filter_layers include list (bridge >= 0.4.0); an older "
               "bridge ignores the filter and lists every layer of the "
               "linked map");
    }

    const ComposerElement* main_map = nullptr;
    for (const ComposerElement* element : visible_elements(doc)) {
        if (element->element_type == "main_map") {
            main_map = element;
            break;
        }
    }

    Json items = Json::array();
    bool grid_present = false;
    double grid_spacing_units = 0.0;
    for (const ComposerElement* element : visible_elements(doc)) {
        if (element->width_mm <= 0.0 || element->height_mm <= 0.0) {
            throw std::invalid_argument(
                "element " + element->id + " (" + element->element_type
                + ") has non-positive extent; fix the composition before "
                  "export");
        }
        const Json& props = element->properties;
        Json base = Json::object();
        base["x"] = element->x_mm;
        base["y"] = element->y_mm;
        base["w"] = element->width_mm;
        base["h"] = element->height_mm;
        const std::string& type = element->element_type;

        if (type == "main_map") {
            Json item = Json::object();
            item["type"] = "map";
            item["key"] = "map";
            for (auto it = base.begin(); it != base.end(); ++it) item[it.key()] = it.value();
            item["crs"] = input.crs;
            Json extent = Json::array();
            for (double v : input.map_extent) extent.push_back(v);
            item["extent"] = extent;
            item["frame"] = true;
            items.push_back(std::move(item));
        } else if (type == "legend" || type == "colorbar"
                   || type == "facies_legend" || type == "well_legend") {
            std::string legend_title;
            if (type == "colorbar") {
                const std::string title = py_str_or(props, "title", "图例");
                const std::string units =
                    py_strip(py_str_or(props, "units", ""));
                legend_title = units.empty() ? title : title + " (" + units + ")";
            } else {
                legend_title = py_str_or(props, "title", "图例");
            }
            Json item = Json::object();
            item["type"] = "legend";
            item["map_item"] = "map";
            item["title"] = legend_title;
            item["x"] = element->x_mm;
            item["y"] = element->y_mm;
            if (type == "legend") {
                item["w"] = element->width_mm;
                item["h"] = element->height_mm;
            } else {
                item["resize_to_contents"] = false;
                const std::vector<std::string> filter_ids =
                    legend_filter_doc_ids(type, mirror);
                if (!filter_ids.empty()) {
                    Json filter = Json::array();
                    for (const std::string& id : filter_ids) filter.push_back(id);
                    item["filter_layers"] = filter;
                }
            }
            items.push_back(std::move(item));
        } else if (type == "north_arrow") {
            Json item = Json::object();
            item["type"] = "north_arrow";
            item["map_item"] = "map";
            item["svg_path"] = north_arrow_svg_path();
            for (auto it = base.begin(); it != base.end(); ++it) item[it.key()] = it.value();
            items.push_back(std::move(item));
        } else if (type == "scale_bar") {
            Json item = Json::object();
            item["type"] = "scalebar";
            item["map_item"] = "map";
            item["segments"] = py_int_json(4);
            item["unit_label"] = py_str_or(props, "units", "");
            for (auto it = base.begin(); it != base.end(); ++it) item[it.key()] = it.value();
            items.push_back(std::move(item));
        } else if (type == "grid") {
            // Paper-mm spacing → map units via the main map's
            // extent-to-width scale (same projection assumption as the
            // canvas). Last GRID element wins; no main map → warn + drop.
            // Evaluation order matches Python: the main-map gate runs
            // BEFORE the spacing coercion (a non-numeric spacing with no
            // main map warns and drops instead of raising).
            if (main_map == nullptr || main_map->width_mm <= 0.0) {
                warn("grid element " + element->id
                     + " has no main map to attach to; dropped");
            } else {
                const double spacing_mm =
                    py_float_or(props, "spacing_mm", 10.0);
                const double extent_width =
                    std::max(1e-9, input.map_extent[2] - input.map_extent[0]);
                grid_spacing_units =
                    spacing_mm * extent_width / main_map->width_mm;
                grid_present = true;
            }
        } else if (type == "title" || type == "subtitle" || type == "text"
                   || type == "annotation" || type == "datasource"
                   || type == "time_credits" || type == "strat_labels"
                   || type == "metadata") {
            std::string text;
            if (type == "metadata" && props.is_object()) {
                const auto fields = props.find("fields");
                if (fields != props.end() && fields->is_object()) {
                    std::string joined;
                    for (auto it = fields->begin(); it != fields->end(); ++it) {
                        if (!joined.empty()) joined += "\n";
                        joined += it.key() + ": " + python_str(it.value());
                    }
                    text = joined;
                } else {
                    text = py_str_or(props, "text", "");
                }
            } else {
                text = py_str_or(props, "text", "");
            }
            Json item = Json::object();
            item["type"] = "label";
            item["text"] = text;
            item["font_size"] = py_float_or(props, "font_size", 10.0);
            item["bold"] = (type == "title" || type == "subtitle");
            item["color"] = py_str_or(props, "color", "#000000");
            item["halign"] = py_str_or(props, "align", "left");
            for (auto it = base.begin(); it != base.end(); ++it) item[it.key()] = it.value();
            items.push_back(std::move(item));
        } else if (type == "image") {
            const std::string image_path = py_str_or(props, "image_path", "");
            if (image_path.empty()) {
                throw std::invalid_argument(
                    "image element " + py_repr(element->id)
                    + " has no image_path; embedded image data needs the "
                      "composer renderer");
            }
            Json item = Json::object();
            item["type"] = "picture";
            item["path"] = image_path;
            for (auto it = base.begin(); it != base.end(); ++it) item[it.key()] = it.value();
            items.push_back(std::move(item));
        } else if (type == "neatline") {
            Json item = Json::object();
            item["type"] = "shape";
            item["frame"] = true;
            item["fill"] = "#00000000";
            for (auto it = base.begin(); it != base.end(); ++it) item[it.key()] = it.value();
            items.push_back(std::move(item));
        } else {
            // Unreachable: the gate above rejected non-native types.
            throw std::invalid_argument(
                "composition has elements with no native layout counterpart: "
                + type);
        }
    }

    if (grid_present && main_map != nullptr) {
        for (Json& item : items) {
            if (item.is_object() && item.value("type", "") == "map") {
                Json grid = Json::object();
                grid["enabled"] = true;
                grid["interval_x"] = grid_spacing_units;
                grid["interval_y"] = grid_spacing_units;
                grid["annotation"] = true;
                item["grid"] = grid;
            }
        }
    }

    Json spec = Json::object();
    Json page = Json::object();
    page["width_mm"] = doc.width_mm;
    page["height_mm"] = doc.height_mm;
    spec["page"] = page;
    spec["items"] = items;
    return spec;
}

// ---------------------------------------------------------------------------
// Pixel budget
// ---------------------------------------------------------------------------

void check_pixel_budget(const Composition& doc, double dpi) {
    const double width_px = doc.width_mm / 25.4 * dpi;
    const double height_px = doc.height_mm / 25.4 * dpi;
    if (width_px * height_px > kMaxExportPixels) {
        const double suggested =
            0.999 * kMaxExportPixels / std::max(1e-9, width_px * height_px)
            * dpi;
        throw std::invalid_argument(
            "export of " + Json(doc.width_mm).dump() + "x"
            + Json(doc.height_mm).dump() + " mm at " + format_g(dpi, 6)
            + " dpi needs ~" + format_g(width_px * height_px, 3)
            + " px (budget 200000000); reduce dpi to ~" + format_f0(suggested)
            + " or smaller");
    }
}

// ---------------------------------------------------------------------------
// Report + orchestration
// ---------------------------------------------------------------------------

Json LayoutExportReport::to_dict() const {
    Json out = Json::object();
    out["engine"] = engine;
    out["path"] = path;
    out["format"] = format;
    out["dpi"] = dpi;
    out["ok"] = ok;
    out["warnings"] = warnings;
    out["unmapped_elements"] = unmapped_elements;
    out["items"] = py_int_json(items);
    out["hybrid_items"] = hybrid_items;
    out["failure"] = failure;
    out["dimensions"] = Json::object({{"width_px", py_int_json(width_px)},
                                      {"height_px", py_int_json(height_px)}});
    out["filter_layers"] = filter_layers.is_object() ? filter_layers
                                                     : Json::object();
    return out;
}

LayoutExportReport export_composition_reported(
    const Composition& doc, const std::filesystem::path& output_path,
    const ExportRequest& request, const LayoutExecutor* executor) {
    LayoutExportReport report;
    report.format = request.format;
    report.dpi = request.dpi;
    report.path = output_path.string();

    // Python: out.parent.mkdir(parents=True, exist_ok=True) before anything
    // else, so an export into a fresh directory succeeds.
    if (!output_path.parent_path().empty()) {
        std::error_code mkdir_ec;
        std::filesystem::create_directories(output_path.parent_path(),
                                            mkdir_ec);
    }

    // A budget breach is a caller error: raise, never degrade.
    check_pixel_budget(doc, request.dpi);

    const std::vector<MirrorLayer> mirror =
        normalize_mirror_layers(request.mirror_layers);
    const std::vector<std::string> proven = legend_backed_types(mirror);
    const auto is_proven = [&proven](const std::string& type) {
        return std::find(proven.begin(), proven.end(), type) != proven.end();
    };

    // V7 §13: the hybrid boundary is computed up front so every exit path
    // reports WHICH element types forced (or would force) the composer
    // engine.
    const std::vector<std::string> hybrid =
        hybrid_element_types(doc, request.mirror_layers);
    std::map<std::string, int> counts;
    for (const ComposerElement* element : visible_elements(doc)) {
        const std::string& type = element->element_type;
        if (native_wire_type(type).empty() && !is_proven(type)) {
            ++counts[type];
            report.unmapped_elements.push_back(element->id);
        }
    }
    report.hybrid_items = hybrid;
    if (!hybrid.empty()) {
        std::string forced;
        for (const auto& [name, count] : counts) {
            if (!forced.empty()) forced += ", ";
            forced += name + "×" + std::to_string(count);
        }
        report.warnings.push_back(
            "composer fallback forced by unmapped elements: " + forced);
        std::vector<std::string> unproven;
        for (const ComposerElement* element : visible_elements(doc)) {
            const std::string& type = element->element_type;
            if (is_legend_backed_type(type) && !is_proven(type)) {
                unproven.push_back(type);
            }
        }
        unproven = sorted_distinct(std::move(unproven));
        if (!unproven.empty()) {
            report.warnings.push_back(
                join(unproven, ", ")
                + " element(s) have no matching layer in the mirror "
                  "description (mirror_layers); a legend-backed element goes "
                  "native only when its layer is provably mirrored");
        }
    }

    bool can_use_layout = executor != nullptr && request.has_map_extent;
    std::string no_engine_reason;
    Json spec;
    if (can_use_layout) {
        try {
            BuildSpecInput input;
            input.map_extent = request.map_extent;
            input.crs = request.crs;
            input.mirror_layers = request.mirror_layers;
            spec = build_layout_spec(doc, input, &report.warnings);
            if (request.geo_pdf) spec["geo_pdf"] = true;
            if (request.force_vector) spec["force_vector"] = true;
            if (!request.background.empty()) {
                spec["page"]["background"] = request.background;
            }
        } catch (const std::invalid_argument& ex) {
            report.warnings.push_back(ex.what());
            no_engine_reason = ex.what();
            can_use_layout = false;
        }
    } else {
        if (executor == nullptr) {
            report.warnings.push_back("no QGIS map stack available");
            no_engine_reason = "no native layout executor available";
        }
        if (!request.has_map_extent) {
            report.warnings.push_back("no map extent provided");
            no_engine_reason = "no map extent provided";
        }
    }

    if (can_use_layout) {
        try {
            const Json payload = (*executor)(spec.dump(), output_path.string(),
                                             request.format, request.dpi);
            report.engine = "qgis_layout";
            report.ok = payload.is_object()
                && payload.contains("ok") && payload["ok"].is_boolean()
                && payload["ok"].get<bool>();
            report.items = 0;
            report.width_px = 0;
            report.height_px = 0;
            if (payload.is_object()) {
                // Python: int(payload.get("items") or 0) — falsy/absent → 0.
                const auto items = payload.find("items");
                if (items != payload.end() && items->is_number_integer()) {
                    report.items = items->get<long long>();
                }
                const auto width = payload.find("width_px");
                if (width != payload.end() && width->is_number_integer()) {
                    report.width_px = width->get<long long>();
                }
                const auto height = payload.find("height_px");
                if (height != payload.end() && height->is_number_integer()) {
                    report.height_px = height->get<long long>();
                }
            }
            Json filters = Json::object();
            if (spec.is_object()) {
                const auto items = spec.find("items");
                if (items != spec.end() && items->is_array()) {
                    for (const Json& item : *items) {
                        if (!item.is_object()
                            || item.value("type", "") != "legend") {
                            continue;
                        }
                        const auto filter = item.find("filter_layers");
                        if (filter == item.end()) continue;
                        filters[item.value("title", "")] = *filter;
                    }
                }
            }
            report.filter_layers = std::move(filters);
            return report;
        } catch (const std::exception& ex) {
            report.warnings.push_back(
                std::string("qgis layout export failed: ") + ex.what());
            // D-03: no composer fallback — the executor failure is the
            // report, with the partial file removed by the executor.
            report.engine = "qgis_layout";
            report.ok = false;
            report.failure = ex.what();
            return report;
        }
    }

    // Python would route here into the composer SVG renderer
    // (engine="composer_fallback", ok=true). The native chain has no second
    // engine (29-decisions.md D-03): this is an honest failure report.
    report.engine = "none";
    report.ok = false;
    report.failure = "composer fallback unavailable in the native chain "
                     "(fail-closed)";
    if (!no_engine_reason.empty()) {
        report.failure += ": " + no_engine_reason;
    }
    return report;
}

// ---------------------------------------------------------------------------
// Screen/export parity
// ---------------------------------------------------------------------------

namespace {

bool close_enough(double a, double b) {
    return std::abs(a - b) <= 1e-9 + 1e-9 * std::max(std::abs(a), std::abs(b));
}

std::array<double, 4> read_extent(const Json& state, bool* ok) {
    std::array<double, 4> out{0.0, 0.0, 0.0, 0.0};
    *ok = false;
    if (!state.is_object()) return out;
    const auto it = state.find("extent");
    if (it == state.end() || !it->is_array() || it->size() != 4) return out;
    for (int i = 0; i < 4; ++i) {
        if (!(*it).at(i).is_number()) return out;
        out[static_cast<std::size_t>(i)] = (*it).at(i).get<double>();
    }
    *ok = true;
    return out;
}

Json aspect(const ParityAspect& aspect_value) {
    Json out = Json::object();
    out["equal"] = aspect_value.equal;
    out["detail"] = aspect_value.detail;
    return out;
}

}  // namespace

ParityReport screen_export_parity(const Json& canvas_state,
                                  const Json& export_state) {
    ParityReport report;
    std::vector<std::string> diffs;
    auto fail = [&](ParityAspect* field, std::string detail) {
        field->equal = false;
        field->detail = detail;
        report.equal = false;
        diffs.push_back(std::move(detail));
    };

    bool canvas_ok = false;
    bool export_ok = false;
    const std::array<double, 4> canvas_extent = read_extent(canvas_state, &canvas_ok);
    const std::array<double, 4> export_extent = read_extent(export_state, &export_ok);
    if (canvas_ok && export_ok) {
        const bool equal = std::equal(canvas_extent.begin(), canvas_extent.end(),
                                      export_extent.begin(), close_enough);
        if (!equal) {
            fail(&report.extent,
                 "extent differs: canvas [" + join(
                     std::vector<std::string>{
                         Json(canvas_extent[0]).dump(),
                         Json(canvas_extent[1]).dump(),
                         Json(canvas_extent[2]).dump(),
                         Json(canvas_extent[3]).dump()}, ", ")
                     + "] vs export [" + join(
                     std::vector<std::string>{
                         Json(export_extent[0]).dump(),
                         Json(export_extent[1]).dump(),
                         Json(export_extent[2]).dump(),
                         Json(export_extent[3]).dump()}, ", ") + "]");
        }
    } else {
        fail(&report.extent, "extent missing or malformed on one side");
    }

    const auto read_str = [](const Json& state, const char* key) {
        if (!state.is_object()) return std::string();
        const auto it = state.find(key);
        return it != state.end() && it->is_string() ? it->get<std::string>()
                                                    : std::string();
    };
    const std::string canvas_crs = read_str(canvas_state, "crs");
    const std::string export_crs = read_str(export_state, "crs");
    if (canvas_crs != export_crs) {
        fail(&report.crs, "crs differs: canvas '" + canvas_crs
                              + "' vs export '" + export_crs + "'");
    }

    const auto read_layers = [](const Json& state)
        -> std::vector<std::pair<std::string, bool>> {
        std::vector<std::pair<std::string, bool>> out;
        if (!state.is_object()) return out;
        const auto it = state.find("layers");
        if (it == state.end() || !it->is_array()) return out;
        for (const Json& layer : *it) {
            if (!layer.is_object()) continue;
            const auto id = layer.find("id");
            if (id == layer.end() || !id->is_string()) continue;
            const auto visible = layer.find("visible");
            out.emplace_back(id->get<std::string>(),
                             visible != layer.end() && visible->is_boolean()
                                 ? visible->get<bool>()
                                 : true);
        }
        return out;
    };
    const auto canvas_layers = read_layers(canvas_state);
    const auto export_layers = read_layers(export_state);
    // Order comparison covers the VISIBLE layer id sequence (top-first) —
    // hidden layers never render on either side.
    std::vector<std::string> canvas_visible, export_visible;
    for (const auto& [id, visible] : canvas_layers) {
        if (visible) canvas_visible.push_back(id);
    }
    for (const auto& [id, visible] : export_layers) {
        if (visible) export_visible.push_back(id);
    }
    std::vector<std::string> canvas_hidden, export_hidden;
    for (const auto& [id, visible] : canvas_layers) {
        if (!visible) canvas_hidden.push_back(id);
    }
    for (const auto& [id, visible] : export_layers) {
        if (!visible) export_hidden.push_back(id);
    }
    if (canvas_visible != export_visible) {
        fail(&report.layer_order,
             "visible layer order differs: canvas [" + join(canvas_visible, ", ")
                 + "] vs export [" + join(export_visible, ", ") + "]");
    }
    {
        std::set<std::string> canvas_set(canvas_hidden.begin(),
                                         canvas_hidden.end());
        std::set<std::string> export_set(export_hidden.begin(),
                                         export_hidden.end());
        if (canvas_set != export_set) {
            std::vector<std::string> only_canvas, only_export;
            for (const std::string& id : canvas_set) {
                if (!export_set.count(id)) only_canvas.push_back(id);
            }
            for (const std::string& id : export_set) {
                if (!canvas_set.count(id)) only_export.push_back(id);
            }
            fail(&report.visibility,
                 "hidden layer sets differ: canvas-only [" + join(only_canvas, ", ")
                     + "] export-only [" + join(only_export, ", ") + "]");
        }
    }

    const auto read_grid = [](const Json& state) {
        bool enabled = false;
        double ix = 0.0, iy = 0.0;
        bool present = false;
        if (state.is_object()) {
            const auto it = state.find("grid");
            if (it != state.end() && it->is_object()) {
                present = true;
                enabled = it->value("enabled", false);
                ix = it->value("interval_x", 0.0);
                iy = it->value("interval_y", 0.0);
            }
        }
        return std::make_tuple(present, enabled, ix, iy);
    };
    const auto [canvas_has_grid, canvas_grid_on, canvas_ix, canvas_iy] = read_grid(canvas_state);
    const auto [export_has_grid, export_grid_on, export_ix, export_iy] = read_grid(export_state);
    if (canvas_has_grid != export_has_grid || canvas_grid_on != export_grid_on
        || !close_enough(canvas_ix, export_ix)
        || !close_enough(canvas_iy, export_iy)) {
        fail(&report.grid, "map grid state differs between screen and export");
    }

    const auto read_bool = [](const Json& state, const char* key) {
        if (!state.is_object()) return false;
        const auto it = state.find(key);
        return it != state.end() && it->is_boolean() && it->get<bool>();
    };
    if (read_bool(canvas_state, "legend") != read_bool(export_state, "legend")) {
        fail(&report.legend, "legend presence differs between screen and export");
    }

    report.diffs = std::move(diffs);
    return report;
}

Json ParityReport::to_dict() const {
    Json out = Json::object();
    out["equal"] = equal;
    out["aspects"] = Json::object({{"extent", aspect(extent)},
                                   {"crs", aspect(crs)},
                                   {"layer_order", aspect(layer_order)},
                                   {"visibility", aspect(visibility)},
                                   {"grid", aspect(grid)},
                                   {"legend", aspect(legend)}});
    out["diffs"] = diffs;
    out["style_source"] = "shared_qgis_project_layers";
    out["by_construction"] = Json::array({"style", "annotations"});
    return out;
}

// ---------------------------------------------------------------------------
// North arrow SVG
// ---------------------------------------------------------------------------

std::string north_arrow_svg_path() {
    static const char kNorthArrowSvg[] =
        "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"30\" "
        "viewBox=\"0 0 20 30\">\n"
        "  <path d=\"M10 1 L16 22 L10 17 L4 22 Z\" fill=\"#1a1a1a\" "
        "stroke=\"#1a1a1a\" stroke-width=\"1\"/>\n"
        "  <text x=\"10\" y=\"29\" font-size=\"7\" text-anchor=\"middle\" "
        "font-family=\"sans-serif\" fill=\"#1a1a1a\">N</text>\n"
        "</svg>\n";
    try {
        const std::filesystem::path cache =
            std::filesystem::temp_directory_path() / "pwb_north_arrow.svg";
        std::error_code ec;
        const bool same = std::filesystem::exists(cache, ec)
            && !std::filesystem::is_directory(cache, ec);
        if (same) {
            std::ifstream in(cache, std::ios::binary);
            const std::string content((std::istreambuf_iterator<char>(in)),
                                      std::istreambuf_iterator<char>());
            if (in.good() && content == kNorthArrowSvg) {
                return cache.string();
            }
        }
        {
            std::ofstream out(cache, std::ios::binary | std::ios::trunc);
            if (!out.good()) return "";
            out.write(kNorthArrowSvg, static_cast<std::streamsize>(
                                          std::strlen(kNorthArrowSvg)));
            if (!out.good()) return "";
        }
        return cache.string();
    } catch (const std::exception&) {
        return "";
    }
}

}  // namespace pwb::layout_export
