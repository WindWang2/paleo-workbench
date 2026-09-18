#include <pwb/mapping_document/composition.hpp>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <unordered_map>

#include "python_compat.hpp"

namespace pwb::mapping_document {

namespace {

using detail::collect_extras;
using detail::py_float;
using detail::py_int;
using detail::py_int_json;
using detail::py_str;
using detail::py_truthy;

// `payload.get(key) or default` for numbers.
double number_or(const Json& payload, const char* key, double fallback) {
    if (!payload.contains(key)) return fallback;
    const Json& value = payload.at(key);
    if (!py_truthy(value)) return fallback;
    return py_float(value);
}

// `payload.get(key) or default` for integers.
long long integer_or(const Json& payload, const char* key, long long fallback) {
    if (!payload.contains(key)) return fallback;
    const Json& value = payload.at(key);
    if (!py_truthy(value)) return fallback;
    return py_int(value);
}

// `str(payload.get(key) or default)`.
std::string string_or(const Json& payload, const char* key,
                      const std::string& fallback) {
    if (!payload.contains(key)) return fallback;
    const Json& value = payload.at(key);
    if (!py_truthy(value)) return fallback;
    return py_str(value);
}

// `payload.get(key, default)` coerced through bool().
bool bool_or_default(const Json& payload, const char* key, bool fallback) {
    if (!payload.contains(key)) return fallback;
    return py_truthy(payload.at(key));
}

// composer/models.py ElementType vocabulary.
const std::unordered_map<std::string, bool>& element_type_vocabulary() {
    static const std::unordered_map<std::string, bool> vocabulary{
        {"main_map", true},      {"legend", true},
        {"north_arrow", true},   {"scale_bar", true},
        {"grid", true},          {"title", true},
        {"annotation", true},    {"timescale", true},
        {"text", true},          {"image", true},
        {"inset_map", true},     {"stat_chart", true},
        {"metadata", true},      {"colorbar", true},
        {"neatline", true},      {"datasource", true},
        {"time_credits", true},  {"fault_symbols", true},
        {"facies_legend", true}, {"lithology_legend", true},
        {"strat_labels", true},  {"subtitle", true},
        {"well_legend", true},   {"profile", true},
    };
    return vocabulary;
}

const Json* known_key(const Json& payload, const char* key) {
    return payload.contains(key) ? &payload.at(key) : nullptr;
}

bool is_known_element_type(const std::string& value) {
    return element_type_vocabulary().count(value) != 0;
}

const std::vector<const char*> kElementKeys{
    "id", "element_type", "x_mm", "y_mm", "width_mm", "height_mm",
    "z_index", "visible", "locked", "properties"};

const std::vector<const char*> kTopLevelKeys{
    "id", "title", "paper_size", "orientation", "width_mm", "height_mm",
    "dpi", "schema_version", "elements", "metadata"};

}  // namespace

ComposerElement parse_composer_element(const Json& payload) {
    if (!payload.is_object()) {
        throw std::invalid_argument(
            "composition: element payload must be an object");
    }
    ComposerElement element;
    // Python: str(payload.get("element_type") or "text"); an unknown value is
    // carried by a TEXT element, never rejected.
    const std::string raw_type = string_or(payload, "element_type", "text");
    element.carried_raw_type = !is_known_element_type(raw_type);
    element.element_type = element.carried_raw_type ? "text" : raw_type;

    // Python: str(payload.get("id") or <random>); the kernel never invents
    // ids (decision D-04) — an absent/empty id stays empty.
    element.id = string_or(payload, "id", "");
    element.x_mm = number_or(payload, "x_mm", 0.0);
    element.y_mm = number_or(payload, "y_mm", 0.0);
    element.width_mm = number_or(payload, "width_mm", 1.0);
    element.height_mm = number_or(payload, "height_mm", 1.0);
    element.z_index = integer_or(payload, "z_index", 0);
    element.visible = bool_or_default(payload, "visible", true);
    element.locked = bool_or_default(payload, "locked", false);

    const Json* properties = known_key(payload, "properties");
    element.properties =
        (properties != nullptr && properties->is_object())
            ? *properties
            : Json::object();
    if (element.carried_raw_type
        && !element.properties.contains("_raw_element_type")) {
        element.properties["_raw_element_type"] = raw_type;
    }

    // Unknown element fields survive (§7.4) where Python drops them (D-08).
    detail::collect_extras(payload, kElementKeys, element.extras);
    return element;
}

Json dump_composer_element(const ComposerElement& element) {
    Json properties = element.properties.is_object() ? element.properties
                                                     : Json::object();
    std::string element_type = element.element_type;
    // Python to_dict: raw = props.pop("_raw_element_type", None); a non-null
    // pop on a TEXT element relabels the output type. This fires even when
    // the marker was plain payload data on a genuine text element — frozen
    // as the raw_marker_pop_quirk oracle case.
    if (properties.contains("_raw_element_type")) {
        const Json marker = properties.at("_raw_element_type");
        properties.erase("_raw_element_type");
        if (!marker.is_null() && element_type == "text") {
            element_type = py_str(marker);
        }
    }
    Json out;
    out["id"] = element.id;
    out["element_type"] = element_type;
    out["x_mm"] = element.x_mm;
    out["y_mm"] = element.y_mm;
    out["width_mm"] = element.width_mm;
    out["height_mm"] = element.height_mm;
    out["z_index"] = py_int_json(element.z_index);
    out["visible"] = element.visible;
    out["locked"] = element.locked;
    out["properties"] = properties;
    for (auto it = element.extras.begin(); it != element.extras.end(); ++it) {
        out[it.key()] = it.value();
    }
    return out;
}

Composition parse_composition(const Json& payload) {
    if (!payload.is_object()) {
        throw std::invalid_argument(
            "composition: document payload must be an object");
    }
    Composition doc;
    doc.id = string_or(payload, "id", "");
    doc.title = string_or(payload, "title", "");
    doc.paper_size = string_or(payload, "paper_size", "A4");
    doc.orientation = string_or(payload, "orientation", "landscape");
    doc.width_mm = number_or(payload, "width_mm", 297.0);
    doc.height_mm = number_or(payload, "height_mm", 210.0);
    doc.dpi = number_or(payload, "dpi", 300.0);
    doc.schema_version = 2;  // payload schema_version is never read back

    const Json* elements = known_key(payload, "elements");
    if (elements != nullptr && !elements->is_null()) {
        if (!elements->is_array()) {
            throw std::invalid_argument("composition: elements must be a list");
        }
        for (const auto& entry : *elements) {
            if (!entry.is_object()) continue;  // Python skips non-Mappings
            doc.elements.push_back(parse_composer_element(entry));
        }
    }
    std::stable_sort(doc.elements.begin(), doc.elements.end(),
                     [](const ComposerElement& left,
                        const ComposerElement& right) {
                         return left.z_index < right.z_index;
                     });

    const Json* metadata = known_key(payload, "metadata");
    doc.metadata =
        (metadata != nullptr && metadata->is_object()) ? *metadata : Json::object();

    detail::collect_extras(payload, kTopLevelKeys, doc.extras);
    return doc;
}

Json dump_composition(const Composition& doc) {
    Json out;
    out["id"] = doc.id;
    out["title"] = doc.title;
    out["paper_size"] = doc.paper_size;
    out["orientation"] = doc.orientation;
    out["width_mm"] = doc.width_mm;
    out["height_mm"] = doc.height_mm;
    out["dpi"] = doc.dpi;
    out["schema_version"] = py_int_json(doc.schema_version);
    Json elements = Json::array();
    for (const ComposerElement& element : doc.elements) {
        elements.push_back(dump_composer_element(element));
    }
    out["elements"] = elements;
    out["metadata"] = doc.metadata;
    for (auto it = doc.extras.begin(); it != doc.extras.end(); ++it) {
        out[it.key()] = it.value();
    }
    return out;
}

void add_element(Composition& doc, ComposerElement element) {
    doc.elements.push_back(std::move(element));
    std::stable_sort(doc.elements.begin(), doc.elements.end(),
                     [](const ComposerElement& left,
                        const ComposerElement& right) {
                         return left.z_index < right.z_index;
                     });
}

ComposerElement* find_element(Composition& doc,
                                   const std::string& element_id) {
    for (ComposerElement& element : doc.elements) {
        if (element.id == element_id) return &element;
    }
    return nullptr;
}

namespace {

// PAPER_SIZES_MM lookup: *canonical receives the upper-case key on a hit.
const std::pair<double, double>* paper_size_lookup(const std::string& paper,
                                                   std::string* canonical) {
    static const std::unordered_map<std::string, std::pair<double, double>>
        sizes{
            {"A5", {148.0, 210.0}},  {"A4", {210.0, 297.0}},
            {"A3", {297.0, 420.0}},  {"A2", {420.0, 594.0}},
            {"A1", {594.0, 841.0}},  {"A0", {841.0, 1189.0}},
        };
    std::string upper;
    upper.reserve(paper.size());
    for (char c : paper) {
        upper.push_back(static_cast<char>(std::toupper(static_cast<unsigned char>(c))));
    }
    const auto found = sizes.find(upper);
    if (found == sizes.end()) return nullptr;
    if (canonical != nullptr) *canonical = found->first;
    return &found->second;
}

}  // namespace

void set_paper(Composition& doc, const std::string& paper_size,
               const std::string& orientation) {
    std::string canonical;
    const std::pair<double, double>* size =
        paper_size_lookup(paper_size, &canonical);
    if (size == nullptr) {
        // Exact Python message: f"unknown paper size {paper_size!r}".
        throw std::invalid_argument("unknown paper size '" + paper_size + "'");
    }
    const double short_edge = size->first;
    const double long_edge = size->second;
    if (orientation == "portrait") {
        doc.width_mm = short_edge;
        doc.height_mm = long_edge;
    } else {
        doc.width_mm = long_edge;
        doc.height_mm = short_edge;
    }
    doc.paper_size = canonical;
    doc.orientation = orientation;
}

std::pair<long long, long long> composition_page_pixels(
    const Composition& doc, double dpi) {
    // Python: max(1, round(doc.width_mm / _MM_PER_INCH * float(dpi))).
    // The evaluation order (divide, then multiply) is part of the contract:
    // the frozen oracle stores the IEEE754 result of that exact expression.
    // Absurd dpi values that overflow the integer result clamp to the type
    // range (Python would produce a bignum; the clamp exists to keep the
    // cast free of UB on parsed documents).
    const auto px = [](double mm, double dpi_value) {
        const double raw = mm / 25.4 * dpi_value;
        constexpr double kLimit = 9.2e18;
        if (!std::isfinite(raw) || raw >= kLimit) {
            return std::numeric_limits<long long>::max();
        }
        if (raw <= -kLimit) return std::numeric_limits<long long>::min();
        return static_cast<long long>(std::nearbyint(raw));
    };
    const long long width_px = std::max(1LL, px(doc.width_mm, dpi));
    const long long height_px = std::max(1LL, px(doc.height_mm, dpi));
    return {width_px, height_px};
}

}  // namespace pwb::mapping_document
