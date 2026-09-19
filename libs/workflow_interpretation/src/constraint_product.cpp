// constraint_product.cpp — C++ port of
// paleo_workbench/workflow/interpretation/constraint_product.py (CONV-32).
// See include/pwb/workflow_interpretation/constraint_product.hpp.

#include <pwb/workflow_interpretation/constraint_product.hpp>

#include <pwb/factor_host/canonical_json.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>
#include <pwb/workflow_runtime/constraint_versions.hpp>

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::workflow_interpretation {
namespace {

// ---- local Python-parity helpers (workflow_runtime/src/python_compat.hpp
// is not part of that library's public surface; the small subset needed here
// is mirrored locally) -----------------------------------------------

std::string strip_ascii(std::string text) {
    const auto is_space = [](unsigned char c) {
        return c == ' ' || c == '\t' || c == '\n' || c == '\r' ||
               c == '\v' || c == '\f';
    };
    std::size_t begin = 0;
    while (begin < text.size() && is_space(text[begin])) ++begin;
    std::size_t end = text.size();
    while (end > begin && is_space(text[end - 1])) --end;
    return text.substr(begin, end - begin);
}

std::string lower_ascii(std::string text) {
    for (char& c : text) {
        c = static_cast<char>(
            std::tolower(static_cast<unsigned char>(c)));
    }
    return text;
}

// Python truthiness of a JSON value.
bool truthy(const Json& value) {
    switch (value.type()) {
    case Json::value_t::null: return false;
    case Json::value_t::boolean: return value.get<bool>();
    case Json::value_t::number_integer:
        return value.get<std::int64_t>() != 0;
    case Json::value_t::number_unsigned:
        return value.get<std::uint64_t>() != 0;
    case Json::value_t::number_float:
        return value.get<double>() != 0.0;
    case Json::value_t::string:
        return !value.get_ref<const std::string&>().empty();
    case Json::value_t::array: return !value.empty();
    case Json::value_t::object: return !value.empty();
    default: return false;
    }
}

// str(x or "") — Python str() of a truthy scalar, "" for falsy/missing.
// (Container values never reach these fields in the host document model.)
std::string str_or(const Json& obj, const char* key) {
    if (!obj.is_object() || !obj.contains(key)) return "";
    const Json& value = obj.at(key);
    if (!truthy(value)) return "";
    return pwb::factor_host::python_str_scalar(value);
}

// Python repr() of a string (single quotes unless the text contains ' and
// not "; minimal control escapes) — used by the frozen CRS messages.
std::string repr_str(const std::string& value) {
    const bool has_single = value.find('\'') != std::string::npos;
    const bool has_double = value.find('"') != std::string::npos;
    const char quote = (has_single && !has_double) ? '"' : '\'';
    std::string out(1, quote);
    for (char c : value) {
        switch (c) {
        case '\\': out += "\\\\"; break;
        case '\n': out += "\\n"; break;
        case '\r': out += "\\r"; break;
        case '\t': out += "\\t"; break;
        default:
            if (c == quote) out += '\\';
            out += c;
        }
    }
    out += quote;
    return out;
}

// Python float(x) for the JSON value forms properties.strength can carry.
std::optional<double> python_float(const Json& value) {
    if (value.is_number()) return value.get<double>();
    if (value.is_boolean()) return value.get<bool>() ? 1.0 : 0.0;
    if (value.is_string()) {
        return pwb::factor_host::python_float_from_string(
            value.get_ref<const std::string&>());
    }
    return std::nullopt;
}

// ---- vocabulary -----------------------------------------------------------

constexpr std::array<const char*, 10> kGeoKinds = {
    "source_direction", "provenance_line", "distribution_line",
    "paleo_shoreline",  "facies_boundary",  "fault",
    "interpolation_boundary", "mask",       "exclusion_area",
    "trend_line",
};

// CONSTRAINT_INTERPOLATION_ROLE (layer_roles.py).
std::map<std::string, std::string> make_role_map() {
    return {
        {"source_direction", "direction"},
        {"trend_line", "direction"},
        {"provenance_line", "direction"},
        {"distribution_line", "direction"},
        {"paleo_shoreline", "boundary"},
        {"facies_boundary", "boundary"},
        {"fault", "break"},
        {"interpolation_boundary", "boundary"},
        {"mask", "boundary"},
        {"exclusion_area", "boundary"},
    };
}

// _ROLE_TO_ENGINE_KIND — engine ConstraintKind VALUES.
std::map<std::string, std::string> make_engine_map() {
    return {
        {"break", "barrier"},
        {"direction", "direction"},
        {"boundary", "boundary_mask"},
    };
}

const std::map<std::string, std::string>& role_map() {
    static const std::map<std::string, std::string> kMap = make_role_map();
    return kMap;
}

const std::map<std::string, std::string>& engine_map() {
    static const std::map<std::string, std::string> kMap = make_engine_map();
    return kMap;
}

// ---- line summary ----------------------------------------------------------

ConstraintLineSummary line_summary(const Json& line) {
    ConstraintLineSummary out;
    out.line_id = str_or(line, "id");
    out.name = str_or(line, "name");
    out.role = str_or(line, "role");

    const Json empty_object = Json::object();
    const Json& props =
        (line.is_object() && line.contains("properties") &&
         !line.at("properties").is_null() && line.at("properties").is_object())
            ? line.at("properties")
            : empty_object;

    std::string geo_kind = str_or(props, "constraint_kind");
    if (!constraint_kind_from_value(geo_kind).has_value()) {
        geo_kind = "";  // unknown geological kind is not guessed
    }
    out.geo_kind = geo_kind;

    out.active = true;  // Python bool(getattr(line, "active", True))
    if (line.is_object() && line.contains("active")) {
        out.active = line.at("active").is_null()
                         ? false  // Python bool(None) == False
                         : truthy(line.at("active"));
    }

    // n_points = len(coordinates) — ALL points, no filtering.
    if (line.is_object() && line.contains("coordinates") &&
        line.at("coordinates").is_array()) {
        out.n_points = static_cast<long long>(line.at("coordinates").size());
    }

    out.strength_declared = props.contains("strength");  // KEY presence
    out.strength = 1.0;
    if (out.strength_declared) {
        const std::optional<double> parsed = python_float(props.at("strength"));
        if (parsed.has_value()) {
            out.strength = *parsed;
        } else {
            out.strength = 1.0;
            out.strength_declared = false;
        }
    }

    out.confidence = str_or(props, "confidence");
    if (out.confidence != "low" && out.confidence != "medium" &&
        out.confidence != "high") {
        out.confidence = "unknown";  // undeclared is never guessed
    }

    out.content_fingerprint = str_or(props, "content_fingerprint");
    return out;
}

}  // namespace

std::optional<std::string> constraint_kind_from_value(const std::string& text) {
    const std::string lowered = lower_ascii(strip_ascii(text));
    if (lowered.empty()) return std::nullopt;
    for (const char* kind : kGeoKinds) {
        if (lowered == kind) return std::string(kind);
    }
    return std::nullopt;
}

std::optional<std::string> interpolation_role_for_kind(const std::string& kind) {
    const auto it = role_map().find(kind);
    if (it == role_map().end()) return std::nullopt;
    return it->second;
}

std::optional<std::string> to_engine_kind(const std::string& geo_kind) {
    const auto resolved = constraint_kind_from_value(geo_kind);
    if (!resolved.has_value()) return std::nullopt;
    const auto role = interpolation_role_for_kind(*resolved);
    if (!role.has_value()) return std::nullopt;
    const auto it = engine_map().find(*role);
    if (it == engine_map().end()) return std::nullopt;
    return it->second;
}

std::string assert_constraints_crs_compatible(
    const std::optional<std::string>& factor_crs,
    const std::optional<std::string>& constraint_crs,
    const std::string& context) {
    const std::string a =
        factor_crs.has_value() ? strip_ascii(*factor_crs) : "";
    const std::string b =
        constraint_crs.has_value() ? strip_ascii(*constraint_crs) : "";
    const std::string prefix = context.empty() ? "" : "[" + context + "] ";
    if (!a.empty() && !b.empty() && a != b) {
        throw ConstraintCrsError(
            prefix + "constraint CRS " + repr_str(b) +
            " differs from factor CRS " + repr_str(a) +
            " — reproject the constraint group before interpolation "
            "(mixed coordinates are never silently mixed)");
    }
    if (!a.empty() && b.empty()) {
        return prefix + "constraint CRS undeclared — interpreted in factor CRS " +
               repr_str(a);
    }
    if (!b.empty() && a.empty()) {
        return prefix + "factor CRS undeclared — constraints assumed " +
               repr_str(b);
    }
    if (a.empty() && b.empty()) {
        return prefix +
               "both CRSs undeclared — coordinates assumed consistent (unverified)";
    }
    return "";
}

Json ConstraintLineSummary::to_dict() const {
    Json out = Json::object();
    out["line_id"] = line_id;
    out["name"] = name;
    out["role"] = role;
    out["geo_kind"] = geo_kind;
    out["active"] = active;
    out["n_points"] = n_points;
    out["strength"] = strength;
    out["strength_declared"] = strength_declared;
    out["confidence"] = confidence;
    out["content_fingerprint"] = content_fingerprint;
    return out;
}

bool ConstraintProduct::has_uncommitted_edits() const {
    return !committed_content_hash.empty() && !content_hash.empty() &&
           committed_content_hash != content_hash;
}

Json ConstraintProduct::to_dict() const {
    Json out = Json::object();
    out["constraint_id"] = constraint_id;
    out["name"] = name;
    out["target_horizon"] = target_horizon;
    Json kinds_arr = Json::array();
    for (const std::string& kind : kinds) kinds_arr.push_back(kind);
    out["kinds"] = std::move(kinds_arr);
    Json engine_arr = Json::array();
    for (const std::string& kind : engine_kinds) engine_arr.push_back(kind);
    out["engine_kinds"] = std::move(engine_arr);
    out["crs"] = crs;
    out["crs_declared"] = crs_declared;
    Json lines_arr = Json::array();
    for (const ConstraintLineSummary& line : lines) {
        lines_arr.push_back(line.to_dict());
    }
    out["lines"] = std::move(lines_arr);
    out["n_active"] = n_active;
    out["committed_version_id"] = committed_version_id;
    out["committed_content_hash"] = committed_content_hash;
    out["content_hash"] = content_hash;
    out["maturity"] = maturity;
    out["staleness"] = staleness;
    out["staleness_detail"] = staleness_detail;
    out["source"] = source;
    out["validity"] = validity;
    return out;
}

ConstraintProduct constraint_product_for_group(
    const Json& document, const Json& group,
    const pwb::workflow_runtime::CatalogRepository* catalog) {
    // The runtime seam's read paths are not const-qualified (Python catalog
    // objects are inherently mutable services); the projection only reads.
    auto* repository = const_cast<pwb::workflow_runtime::CatalogRepository*>(
        catalog);

    std::vector<ConstraintLineSummary> lines;
    if (group.is_object() && group.contains("lines") &&
        group.at("lines").is_array()) {
        for (const Json& line : group.at("lines")) {
            lines.push_back(line_summary(line));
        }
    }

    std::vector<std::string> kinds;
    std::vector<std::string> engine;
    for (const ConstraintLineSummary& line : lines) {
        if (!line.geo_kind.empty() &&
            std::find(kinds.begin(), kinds.end(), line.geo_kind) ==
                kinds.end()) {
            kinds.push_back(line.geo_kind);
        }
        std::optional<std::string> engine_kind;
        if (!line.geo_kind.empty()) {
            engine_kind = to_engine_kind(line.geo_kind);
        }
        if (!line.role.empty()) {
            const auto mapped = engine_map().find(line.role);
            if (mapped != engine_map().end() &&
                std::find(engine.begin(), engine.end(), mapped->second) ==
                    engine.end()) {
                engine.push_back(mapped->second);
            }
        }
        if (engine_kind.has_value() &&
            std::find(engine.begin(), engine.end(), *engine_kind) ==
                engine.end()) {
            engine.push_back(*engine_kind);
        }
    }

    std::string committed_version;
    std::string committed_hash;
    if (repository != nullptr) {
        try {
            const auto latest = pwb::workflow_runtime::
                current_constraint_version(*repository,
                                           str_or(group, "id"));
            if (latest.has_value()) {
                committed_version = latest->version_id;
                // str(meta.get("content_hash") or "")
                const Json& meta = latest->metadata;
                if (meta.is_object() && meta.contains("content_hash") &&
                    truthy(meta.at("content_hash"))) {
                    committed_hash =
                        pwb::factor_host::python_str_scalar(
                            meta.at("content_hash"));
                }
            }
        } catch (...) {  // version chain missing -> honest draft
            committed_version.clear();
            committed_hash.clear();
        }
    }

    std::string content_hash;
    try {
        content_hash =
            pwb::workflow_runtime::constraint_group_content_hash(group).first;
    } catch (...) {  // content hash failure -> "" (projection continues)
        content_hash = "";
    }

    // Group staleness: is the latest commit still the live content?
    // (resolve_constraint_ref vocabulary: current/stale/superseded/unknown;
    // never-committed groups with content -> "uncommitted"; "" = 未评估.)
    std::string staleness;
    std::string staleness_detail;
    if (!committed_version.empty()) {
        try {
            const Json verdict = pwb::workflow_runtime::resolve_constraint_ref(
                document, repository,
                "constraints:" + str_or(group, "id") + ":" + committed_version);
            staleness = str_or(verdict, "status");
            staleness_detail = str_or(verdict, "detail");
        } catch (...) {  // resolution failure -> 未评估
            staleness = "unknown";
            staleness_detail = "约束版本解析失败";
        }
    } else if (!content_hash.empty()) {
        staleness = "uncommitted";
        staleness_detail = "约束组从未提交——无版本链，内容以 live 文档为准";
    }

    std::string validity;
    if (!committed_hash.empty() && !content_hash.empty() &&
        committed_hash != content_hash) {
        validity = "存在未提交编辑（live 内容 ≠ 最新提交）";
    }

    ConstraintProduct out;
    out.constraint_id = str_or(group, "id");
    out.name = str_or(group, "name");
    out.target_horizon = str_or(group, "target_horizon");
    out.kinds = std::move(kinds);
    out.engine_kinds = std::move(engine);
    out.crs = str_or(group, "crs");
    out.crs_declared = !out.crs.empty();
    out.lines = std::move(lines);
    out.n_active = 0;
    for (const ConstraintLineSummary& line : out.lines) {
        if (line.active) ++out.n_active;
    }
    out.committed_version_id = std::move(committed_version);
    out.committed_content_hash = std::move(committed_hash);
    out.content_hash = std::move(content_hash);
    out.maturity = out.committed_version_id.empty() ? "draft" : "committed";
    out.staleness = std::move(staleness);
    out.staleness_detail = std::move(staleness_detail);
    out.validity = std::move(validity);
    return out;
}

std::vector<ConstraintProduct> constraint_products_for_document(
    const Json& document,
    const pwb::workflow_runtime::CatalogRepository* catalog) {
    std::vector<ConstraintProduct> products;
    if (!document.is_object() || !document.contains("constraint_layers") ||
        !document.at("constraint_layers").is_array()) {
        return products;
    }
    for (const Json& group : document.at("constraint_layers")) {
        products.push_back(constraint_product_for_group(document, group, catalog));
    }
    return products;
}

}  // namespace pwb::workflow_interpretation
