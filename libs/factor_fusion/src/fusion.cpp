#include <pwb/factor_fusion/fusion.hpp>

#include <pwb/domain/sha256.hpp>
#include <pwb/factor_fusion/factor_units.hpp>
#include <pwb/factor_host/canonical_json.hpp>

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <set>
#include <utility>

namespace pwb::factor_fusion {
namespace {

using pwb::factor_host::python_repr_double;

// --- Python scalar semantics ------------------------------------------------

// str(float): same digits as repr but lowercase nan/inf.
std::string py_str_double(double v) {
    if (std::isnan(v)) return "nan";
    if (std::isinf(v)) return v > 0 ? "inf" : "-inf";
    return python_repr_double(v);
}

// repr() of a JSON scalar/compound — covers every shape the frozen messages
// reach (strings, ints, floats, bools, null, arrays, objects).
std::string py_repr(const Json& v);

std::string py_repr_string(const std::string& s) {
    // repr() prefers single quotes, switches to double when the string
    // contains ' but no "; escapes backslash + control chars.
    const bool has_sq = s.find('\'') != std::string::npos;
    const bool has_dq = s.find('"') != std::string::npos;
    const char q = (has_sq && !has_dq) ? '"' : '\'';
    std::string out(1, q);
    for (unsigned char c : s) {
        if (c == q || c == '\\') {
            out += '\\';
            out += static_cast<char>(c);
        } else {
            switch (c) {
                case '\n': out += "\\n"; break;
                case '\r': out += "\\r"; break;
                case '\t': out += "\\t"; break;
                default:
                    if (c < 0x20 || c == 0x7F) {
                        char buf[8];
                        std::snprintf(buf, sizeof buf, "\\x%02x", c);
                        out += buf;
                    } else {
                        out += static_cast<char>(c);
                    }
            }
        }
    }
    out += q;
    return out;
}

std::string py_repr(const Json& v) {
    if (v.is_null()) return "None";
    if (v.is_boolean()) return v.get<bool>() ? "True" : "False";
    if (v.is_number_integer()) return std::to_string(v.get<std::int64_t>());
    if (v.is_number_unsigned()) return std::to_string(v.get<std::uint64_t>());
    if (v.is_number_float()) return py_str_double(v.get<double>());
    if (v.is_string()) return py_repr_string(v.get<std::string>());
    if (v.is_array()) {
        std::string out = "[";
        bool first = true;
        for (const Json& item : v) {
            if (!first) out += ", ";
            first = false;
            out += py_repr(item);
        }
        out += "]";
        return out;
    }
    // dict repr — insertion order, {k: v}.
    std::string out = "{";
    bool first = true;
    for (auto it = v.begin(); it != v.end(); ++it) {
        if (!first) out += ", ";
        first = false;
        out += py_repr_string(it.key());
        out += ": ";
        out += py_repr(it.value());
    }
    out += "}";
    return out;
}

// repr() of a condition row as a Python tuple — the ctor (__post_init__)
// messages render tuples, while from_dict renders the original lists.
std::string py_repr_tuple(const Json& row) {
    std::string out = "(";
    if (row.is_array()) {
        bool first = true;
        for (const Json& item : row) {
            if (!first) out += ", ";
            first = false;
            out += py_repr(item);
        }
        if (row.size() == 1) out += ",";  // Python single-element tuple
    } else {
        out += py_repr(row);
    }
    out += ")";
    return out;
}

// str() coercion used by FusionRule.from_dict / model dict coercion.
std::string py_str(const Json& v) {
    if (v.is_string()) return v.get<std::string>();
    if (v.is_null()) return "None";
    if (v.is_boolean()) return v.get<bool>() ? "True" : "False";
    if (v.is_number_integer()) return std::to_string(v.get<std::int64_t>());
    if (v.is_number_unsigned()) return std::to_string(v.get<std::uint64_t>());
    if (v.is_number_float()) return py_str_double(v.get<double>());
    return py_repr(v);  // containers: str() == repr()
}

// float() coercion: bool→0/1, int/float→value, str→strict literal parse;
// anything else is a TypeError. On unconvertible strings the message is the
// CPython "could not convert string to float: 'xyz'" form.
struct TypeError : PyError {
    using PyError::PyError;
    const char* python_class() const override { return "TypeError"; }
};

double py_float(const Json& v) {
    if (v.is_boolean()) return v.get<bool>() ? 1.0 : 0.0;
    if (v.is_number_integer()) return static_cast<double>(v.get<std::int64_t>());
    if (v.is_number_unsigned()) return static_cast<double>(v.get<std::uint64_t>());
    if (v.is_number_float()) return v.get<double>();
    if (v.is_string()) {
        const std::string& s = v.get_ref<const std::string&>();
        // Python float() trims ASCII ws + a few unicode spaces; strict
        // grammar is handled by strtod + full-consumption below.
        std::size_t a = s.find_first_not_of(" \t\n\r\v\f");
        std::size_t b = s.find_last_not_of(" \t\n\r\v\f");
        if (a == std::string::npos) {
            throw ValueError("could not convert string to float: " +
                             py_repr_string(s));
        }
        const std::string t = s.substr(a, b - a + 1);
        if (t.find('_') != std::string::npos) {
            throw ValueError("could not convert string to float: " +
                             py_repr_string(s));
        }
        char* end = nullptr;
        const double d = std::strtod(t.c_str(), &end);
        if (end != t.c_str() + t.size()) {
            throw ValueError("could not convert string to float: " +
                             py_repr_string(s));
        }
        return d;
    }
    const char* tn = v.is_null() ? "NoneType"
                   : v.is_array() ? "list"
                   : v.is_object() ? "dict" : "object";
    throw TypeError(std::string(
        "float() argument must be a string or a real number, not '") + tn + "'");
}

// int() coercion used on len/index paths (model dict numbers are already
// ints in practice; keep float→int truncation parity for dict payloads).
std::int64_t py_int(const Json& v) {
    if (v.is_boolean()) return v.get<bool>() ? 1 : 0;
    if (v.is_number_integer()) return v.get<std::int64_t>();
    if (v.is_number_unsigned()) return static_cast<std::int64_t>(v.get<std::uint64_t>());
    if (v.is_number_float()) return static_cast<std::int64_t>(v.get<double>());
    if (v.is_string()) {
        const double d = py_float(v);  // close enough for frozen inputs
        return static_cast<std::int64_t>(d);
    }
    throw TypeError("int() argument must be a string or a number");
}

// np.isclose scalar form: |a-b| <= atol + rtol*|b|.
bool is_close(double a, double b, double rtol, double atol) {
    return std::fabs(a - b) <= atol + rtol * std::fabs(b);
}

// np.allclose defaults (rtol=1e-5, atol=1e-8), elementwise; NaN unequal.
bool all_close(const std::vector<double>& a, const std::vector<double>& b) {
    if (a.size() != b.size()) return false;
    for (std::size_t i = 0; i < a.size(); ++i) {
        if (!is_close(a[i], b[i], 1e-5, 1e-8)) return false;
    }
    return true;
}

// Rule operator table — "==" is np.isclose(rtol=1e-9, atol=1e-12).
bool rule_op(std::string_view op, double v, double t) {
    if (op == ">=") return v >= t;
    if (op == "<=") return v <= t;
    if (op == ">") return v > t;
    if (op == "<") return v < t;
    return is_close(v, t, 1e-9, 1e-12);  // "=="
}

bool is_rule_op(std::string_view op) {
    return op == ">=" || op == "<=" || op == ">" || op == "<" || op == "==";
}

// --- fingerprint: json.dumps(sort_keys, ensure_ascii=False) with ", "/": " --

void dumps_escape(std::string& out, const std::string& text) {
    out += '"';
    for (unsigned char c : text) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\b': out += "\\b"; break;
            case '\f': out += "\\f"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (c < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof buf, "\\u%04x", c);
                    out += buf;
                } else {
                    out += static_cast<char>(c);  // ensure_ascii=False
                }
        }
    }
    out += '"';
}

void dumps_encode(std::string& out, const Json& v) {
    if (v.is_null()) out += "null";
    else if (v.is_boolean()) out += v.get<bool>() ? "true" : "false";
    else if (v.is_number_integer()) out += std::to_string(v.get<std::int64_t>());
    else if (v.is_number_unsigned())
        out += std::to_string(v.get<std::uint64_t>());
    else if (v.is_number_float())
        out += python_repr_double(v.get<double>());
    else if (v.is_string()) dumps_escape(out, v.get<std::string>());
    else if (v.is_array()) {
        out += '[';
        bool first = true;
        for (const Json& item : v) {
            if (!first) out += ", ";
            first = false;
            dumps_encode(out, item);
        }
        out += ']';
    } else {
        std::vector<std::string> keys;
        for (auto it = v.begin(); it != v.end(); ++it) keys.push_back(it.key());
        std::sort(keys.begin(), keys.end());
        out += '{';
        bool first = true;
        for (const std::string& k : keys) {
            if (!first) out += ", ";
            first = false;
            dumps_escape(out, k);
            out += ": ";
            dumps_encode(out, v.at(k));
        }
        out += '}';
    }
}

std::string dumps_sorted(const Json& v) {
    std::string out;
    dumps_encode(out, v);
    return out;
}

// --- grid helpers -----------------------------------------------------------

std::vector<double> grid_values(const FactorGrid& g) {
    // ev.grid.grid_z.astype(float) — float32 storage widened to float64.
    std::vector<double> out;
    out.reserve(g.grid_z.size());
    for (float f : g.grid_z) out.push_back(static_cast<double>(f));
    return out;
}

std::pair<int, int> shape_of(const FactorGrid& g) { return {g.height, g.width}; }

std::string shape_repr(const FactorGrid& g) {
    return "(" + std::to_string(g.height) + ", " + std::to_string(g.width) + ")";
}

std::string crs_text(const FactorGrid& g) {
    // str(first.crs or "").strip()
    if (!g.crs.has_value()) return "";
    const std::string& s = *g.crs;
    const std::size_t a = s.find_first_not_of(" \t\n\r\v\f");
    if (a == std::string::npos) return "";
    const std::size_t b = s.find_last_not_of(" \t\n\r\v\f");
    return s.substr(a, b - a + 1);
}

std::string unit_text(const FactorGrid& g) {
    if (!g.unit.has_value()) return "";
    const std::string& s = *g.unit;
    const std::size_t a = s.find_first_not_of(" \t\n\r\v\f");
    if (a == std::string::npos) return "";
    const std::size_t b = s.find_last_not_of(" \t\n\r\v\f");
    return s.substr(a, b - a + 1);
}

FactorGrid build_grid(const FusionModel& model,
                    const std::vector<double>& data,
                    const FactorGrid& reference, const std::string& name,
                    const std::string& unit) {
    FactorGrid out;
    out.height = reference.height;
    out.width = reference.width;
    out.grid_z.reserve(data.size());
    for (double v : data) out.grid_z.push_back(to_grid_cell(v));
    out.grid_x = reference.grid_x;
    out.grid_y = reference.grid_y;
    out.factor_name = name;
    out.algorithm_id = "factor_fusion";
    out.algorithm_parameters = {
        {"fusion_kind", model.kind},
        {"fusion_name", model.name},
    };
    out.crs = reference.crs;
    out.unit = unit;
    out.generator_version = kFusionGeneratorVersion;
    std::set<std::string> refs;
    for (const FactorEvidence& ev : model.evidences) {
        refs.insert(ev.grid.source_refs.begin(), ev.grid.source_refs.end());
    }
    out.source_refs.assign(refs.begin(), refs.end());
    return out;
}

// _implied_class: int8 class grid (−1 = non-finite); highest matching class
// wins by sequential overwrite.
std::vector<int> implied_class(const std::vector<double>& values,
                               const std::vector<double>& thresholds) {
    std::vector<int> out(values.size(), 0);
    for (std::size_t idx = 1; idx <= thresholds.size(); ++idx) {
        const double thr = thresholds[idx - 1];
        for (std::size_t i = 0; i < values.size(); ++i) {
            if (std::isfinite(values[i]) && values[i] >= thr) {
                out[i] = static_cast<int>(idx);
            }
        }
    }
    for (std::size_t i = 0; i < values.size(); ++i) {
        if (!std::isfinite(values[i])) out[i] = -1;
    }
    return out;
}

}  // namespace

// --- Normalization ----------------------------------------------------------

Normalization::Normalization(std::string kind, double low, double high)
    : kind(std::move(kind)), low(low), high(high) {
    if (this->kind != "minmax" && this->kind != "ramp") {
        throw ValueError("unknown normalization kind " + py_repr_string(this->kind));
    }
    if (!std::isfinite(low) || !std::isfinite(high)) {
        throw ValueError("normalization bounds must be finite");
    }
    if (high <= low) {
        throw ValueError("normalization requires high > low");
    }
}

std::vector<double> Normalization::apply(const std::vector<double>& values) const {
    const double span = high - low;
    std::vector<double> out(values.size(),
                            std::numeric_limits<double>::quiet_NaN());
    for (std::size_t i = 0; i < values.size(); ++i) {
        if (std::isfinite(values[i])) {
            out[i] = std::clamp((values[i] - low) / span, 0.0, 1.0);
        }
    }
    return out;
}

Json Normalization::to_dict() const {
    return {{"kind", kind}, {"low", low}, {"high", high}};
}

Normalization Normalization::from_dict(const Json& data) {
    return Normalization(py_str(data.at("kind")), py_float(data.at("low")),
                         py_float(data.at("high")));
}

// --- FactorEvidence ---------------------------------------------------------

FactorEvidence::FactorEvidence(std::string factor_name, FactorGrid grid,
                               double weight, Normalization normalization)
    : factor_name(std::move(factor_name)), grid(std::move(grid)),
      weight(weight), normalization(std::move(normalization)) {
    if (!std::isfinite(weight) || weight <= 0.0) {
        throw ValueError("evidence weight must be finite and positive, got " +
                         py_str_double(weight));
    }
}

Json FactorEvidence::to_dict() const {
    Json refs = Json::array();
    for (const std::string& r : grid.source_refs) refs.push_back(r);
    return {
        {"factor_name", factor_name},
        {"weight", weight},
        {"normalization", normalization.to_dict()},
        {"source_version_ids", std::move(refs)},
        {"algorithm_id", grid.algorithm_id},
    };
}

// --- FusionRule -------------------------------------------------------------
//
// ctor mirrors __post_init__: conditions arrive as raw rows (Json arrays) so
// malformed shapes reach the same validation branches as Python.

FusionRule::FusionRule(std::vector<std::tuple<std::string, std::string, double>> conditions,
                       std::string class_name)
    : conditions(std::move(conditions)), class_name(std::move(class_name)) {
    if (this->conditions.empty()) {
        throw ValueError("rule needs at least one condition");
    }
    for (std::size_t index = 0; index < this->conditions.size(); ++index) {
        const auto& [factor, op, threshold] = this->conditions[index];
        (void)factor;
        if (!is_rule_op(op)) {
            throw ValueError("unknown rule operator " + py_repr_string(op));
        }
        if (!std::isfinite(threshold)) {
            throw ValueError("rule condition " + std::to_string(index) +
                             " threshold must be finite, got " +
                             py_str_double(threshold));
        }
    }
}

// Raw-row ctor for the oracle path: Json rows can be ragged / mistyped just
// like Python tuples. Validation messages stay verbatim.
FusionRule rule_from_rows(const Json& rows, const std::string& class_name,
                          bool from_dict_messages) {
    const std::string shape_msg = from_dict_messages
        ? " must be [factor, op, threshold], got "
        : " must be (factor, op, threshold), got ";
    std::vector<std::tuple<std::string, std::string, double>> out;
    std::size_t index = 0;
    for (const Json& row : rows) {
        if (!row.is_array() || row.size() != 3) {
            throw ValueError("rule condition " + std::to_string(index) +
                             shape_msg +
                             (from_dict_messages ? py_repr(row)
                                                 : py_repr_tuple(row)));
        }
        // ctor path: elements already typed — factor/op checked raw (op
        // must equal a rule string; non-string ops repr verbatim), threshold
        // must be int|float (bool counts) and finite. from_dict path:
        // str()/float() coercions happen BEFORE __post_init__.
        std::string factor, op;
        double threshold = 0.0;
        if (from_dict_messages) {
            factor = py_str(row[0]);
            op = py_str(row[1]);
            threshold = py_float(row[2]);
        } else {
            factor = py_str(row[0]);
            const Json& opj = row[1];
            if (!opj.is_string() || !is_rule_op(opj.get<std::string>())) {
                throw ValueError("unknown rule operator " + py_repr(opj));
            }
            op = opj.get<std::string>();
            const Json& t = row[2];
            const bool numeric = t.is_number() || t.is_boolean();
            if (!numeric || !std::isfinite(py_float(t))) {
                throw ValueError("rule condition " + std::to_string(index) +
                                 " threshold must be finite, got " +
                                 py_repr(t));
            }
            threshold = py_float(t);
        }
        out.emplace_back(std::move(factor), std::move(op), threshold);
        ++index;
    }
    return FusionRule(std::move(out), class_name);
}

Json FusionRule::to_dict() const {
    Json conds = Json::array();
    for (const auto& [f, op, t] : conditions) {
        conds.push_back(Json::array({f, op, t}));
    }
    return {{"conditions", std::move(conds)}, {"class_name", class_name}};
}

FusionRule FusionRule::from_dict(const Json& data) {
    const Json rows = data.contains("conditions") && data["conditions"].is_array()
        ? data["conditions"]
        : Json::array();
    return rule_from_rows(rows, py_str(data.at("class_name")), true);
}

// --- FusionModel ------------------------------------------------------------

void FusionModel::validate() const {
    if (kind != "weighted_evidence" && kind != "rule_based") {
        throw ValueError("unknown fusion kind " + py_repr_string(kind));
    }
    if (kind == "weighted_evidence" && evidences.empty()) {
        throw ValueError("weighted_evidence fusion needs at least one evidence");
    }
    if (kind == "rule_based" && rules.empty()) {
        throw ValueError("rule_based fusion needs at least one rule");
    }
    if (kind == "weighted_evidence") {
        if (class_names.empty()) {
            throw ValueError("weighted_evidence fusion needs class_names");
        }
        if (class_thresholds.size() + 1 != class_names.size()) {
            throw ValueError(
                "class_thresholds must have exactly len(class_names) - 1 entries");
        }
    }
}

Json FusionModel::to_dict() const {
    Json payload = {
        {"name", name},
        {"kind", kind},
        {"default_class", default_class},
        {"generator_version", kFusionGeneratorVersion},
        {"evidences", Json::array()},
        {"rules", Json::array()},
    };
    for (const FactorEvidence& e : evidences) payload["evidences"].push_back(e.to_dict());
    for (const FusionRule& r : rules) payload["rules"].push_back(r.to_dict());
    if (kind == "weighted_evidence") {
        payload["class_thresholds"] = class_thresholds;
        payload["class_names"] = class_names;
    }
    if (weight_provenance.has_value()) {
        const Json& wp = *weight_provenance;
        const bool falsy = wp.is_null() ||
            (wp.is_object() && wp.empty()) || (wp.is_array() && wp.empty()) ||
            (wp.is_string() && wp.get<std::string>().empty()) ||
            (wp.is_boolean() && !wp.get<bool>()) ||
            (wp.is_number() && wp.get<double>() == 0.0);
        if (!falsy) payload["weight_provenance"] = wp;
    }
    return payload;
}

FusionModel FusionModel::from_dict(
    const Json& data, const std::map<std::string, FactorGrid>& grids) {
    FusionModel m;
    m.name = py_str(data.at("name"));
    m.kind = py_str(data.at("kind"));
    if (data.contains("evidences") && data["evidences"].is_array()) {
        for (const Json& e : data["evidences"]) {
            const std::string factor = py_str(e.at("factor_name"));
            const auto it = grids.find(factor);
            if (it == grids.end()) {
                throw ValueError("runtime grid for factor " +
                                 py_repr_string(factor) +
                                 " not supplied — pass grids={factor_name: "
                                 "FactorGridResult}");
            }
            m.evidences.emplace_back(
                factor, it->second, py_float(e.at("weight")),
                Normalization::from_dict(e.at("normalization")));
        }
    }
    if (data.contains("rules") && data["rules"].is_array()) {
        for (const Json& r : data["rules"]) {
            m.rules.push_back(FusionRule::from_dict(r));
        }
    }
    // data.get("default_class") or "未定" — every falsy value resets.
    const Json& dc = data.contains("default_class") ? data["default_class"]
                                                    : Json(nullptr);
    const bool dc_falsy = dc.is_null() ||
        (dc.is_string() && dc.get<std::string>().empty()) ||
        (dc.is_boolean() && !dc.get<bool>()) ||
        (dc.is_number() && dc.get<double>() == 0.0) ||
        (dc.is_array() && dc.empty()) || (dc.is_object() && dc.empty());
    m.default_class = dc_falsy ? "未定" : py_str(dc);
    if (data.contains("class_thresholds") && data["class_thresholds"].is_array()) {
        for (const Json& t : data["class_thresholds"]) {
            m.class_thresholds.push_back(py_float(t));
        }
    }
    if (data.contains("class_names") && data["class_names"].is_array()) {
        for (const Json& n : data["class_names"]) {
            m.class_names.push_back(n.is_string() ? n.get<std::string>()
                                                  : py_str(n));
        }
    }
    // dict(data["weight_provenance"]) if data.get(...) else None — falsy
    // values (null, {}, [], "", 0, False) all map to None.
    const Json& wp = data.contains("weight_provenance")
        ? data["weight_provenance"]
        : Json(nullptr);
    const bool wp_falsy = wp.is_null() ||
        (wp.is_object() && wp.empty()) || (wp.is_array() && wp.empty()) ||
        (wp.is_string() && wp.get<std::string>().empty()) ||
        (wp.is_boolean() && !wp.get<bool>()) ||
        (wp.is_number() && wp.get<double>() == 0.0);
    if (!wp_falsy) m.weight_provenance = wp;
    m.validate();
    return m;
}

std::string FusionModel::fingerprint() const {
    return pwb::domain::Sha256::of_bytes(dumps_sorted(to_dict()));
}

// --- FusionResult -----------------------------------------------------------

Json FusionResult::provenance() const {
    return {
        {"model", model_dict},
        {"model_fingerprint", model.fingerprint()},
        {"generator_version", kFusionGeneratorVersion},
        {"qc", qc},
    };
}

// --- _aligned_or_raise ------------------------------------------------------

std::optional<std::string> aligned_or_raise(const std::vector<FactorGrid>& grids) {
    if (grids.empty()) {
        throw IndexError("list index out of range");
    }
    const FactorGrid& first = grids[0];
    for (std::size_t i = 1; i < grids.size(); ++i) {
        const FactorGrid& other = grids[i];
        if (shape_of(other) != shape_of(first)) {
            throw ValueError("evidence grids must share one geometry: " +
                             shape_repr(first) + " vs " + shape_repr(other));
        }
        if (!(all_close(other.grid_x, first.grid_x) &&
              all_close(other.grid_y, first.grid_y))) {
            throw ValueError(
                "evidence grid axes differ — resample to a common grid first");
        }
        const std::string crs_a = crs_text(first);
        const std::string crs_b = crs_text(other);
        if (!crs_a.empty() && crs_b.empty()) {
            throw ValueError(
                "evidence grid " + py_repr_string(other.factor_name) +
                " declares no CRS while " + py_repr_string(first.factor_name) +
                " declares " + py_repr_string(crs_a) +
                " — mixed CRS discipline is not fusable; reproject or declare "
                "first");
        }
        if (!crs_b.empty() && crs_a.empty()) {
            throw ValueError(
                "evidence grid " + py_repr_string(first.factor_name) +
                " declares no CRS while " + py_repr_string(other.factor_name) +
                " declares " + py_repr_string(crs_b) +
                " — mixed CRS discipline is not fusable; reproject or declare "
                "first");
        }
        if (!crs_a.empty() && !crs_b.empty() && crs_a != crs_b) {
            throw ValueError("evidence grids declare different CRSs (" +
                             py_repr_string(crs_a) + " vs " +
                             py_repr_string(crs_b) +
                             "); reproject to a common CRS before fusing");
        }
    }
    const std::string c = crs_text(first);
    return c.empty() ? std::nullopt : std::optional<std::string>(c);
}

// --- fuse -------------------------------------------------------------------

FusionResult fuse(const FusionModel& model) {
    if (model.kind == "weighted_evidence") return fuse_weighted(model);
    return fuse_rule_based(model);
}

FusionResult fuse_weighted(const FusionModel& model) {
    std::vector<FactorGrid> grids;
    grids.reserve(model.evidences.size());
    for (const FactorEvidence& ev : model.evidences) grids.push_back(ev.grid);
    const std::optional<std::string> fused_crs = aligned_or_raise(grids);
    const FactorGrid& reference = grids[0];

    // Unit diagnostics (both branches verbatim).
    std::vector<std::string> unit_warnings;
    for (const FactorEvidence& ev : model.evidences) {
        const std::string grid_unit = unit_text(ev.grid);
        if ((ev.normalization.kind == "minmax" ||
             ev.normalization.kind == "ramp") &&
            (grid_unit == "%" || grid_unit == "percent") &&
            std::max(std::fabs(ev.normalization.low),
                     std::fabs(ev.normalization.high)) <= 1.5) {
            unit_warnings.push_back(
                "evidence " + py_repr_string(ev.factor_name) +
                ": percent-declared grid with 0..1 normalization bounds (low=" +
                py_str_double(ev.normalization.low) +
                ", high=" + py_str_double(ev.normalization.high) +
                ") — bounds unit mismatch");
        }
        auto more = validate_factor_unit_against_values(
            ev.factor_name, ev.grid.unit, ev.grid.grid_z);
        unit_warnings.insert(unit_warnings.end(), more.begin(), more.end());
    }

    std::vector<double> weights;
    double total_weight = 0.0;
    for (const FactorEvidence& ev : model.evidences) {
        weights.push_back(ev.weight);
        total_weight += ev.weight;
    }

    const std::size_t n = static_cast<std::size_t>(reference.height) *
                        static_cast<std::size_t>(reference.width);
    std::vector<double> w_sum(n, 0.0), m_sum(n, 0.0), w_sq(n, 0.0);
    std::vector<std::vector<double>> memberships;
    std::vector<std::vector<char>> finite_masks;
    memberships.reserve(model.evidences.size());
    finite_masks.reserve(model.evidences.size());
    std::size_t ev_idx = 0;
    for (const FactorEvidence& ev : model.evidences) {
        const double weight = weights[ev_idx++];
        std::vector<double> membership =
            ev.normalization.apply(grid_values(ev.grid));
        std::vector<char> mask(n, 0);
        for (std::size_t i = 0; i < n; ++i) {
            mask[i] = std::isfinite(membership[i]) ? 1 : 0;
            if (mask[i]) {
                const double contribution = weight * membership[i];
                w_sum[i] += weight;
                m_sum[i] += contribution;
                w_sq[i] += contribution * membership[i];
            }
        }
        memberships.push_back(std::move(membership));
        finite_masks.push_back(std::move(mask));
    }

    std::vector<double> likelihood(n);
    for (std::size_t i = 0; i < n; ++i) {
        likelihood[i] = w_sum[i] > 0.0 ? m_sum[i] / w_sum[i]
                                     : std::numeric_limits<double>::quiet_NaN();
    }

    std::vector<double> confidence(n);
    for (std::size_t i = 0; i < n; ++i) {
        if (w_sum[i] <= 0.0) {
            confidence[i] = std::numeric_limits<double>::quiet_NaN();
            continue;
        }
        const double coverage = w_sum[i] / total_weight;
        const double mean_sq = w_sq[i] / w_sum[i];
        const double spread_sq =
            std::max(mean_sq - likelihood[i] * likelihood[i], 0.0);
        const double agreement = 1.0 - std::sqrt(spread_sq);
        confidence[i] = coverage * agreement;
    }

    const std::vector<int> fused_class = implied_class(likelihood,
                                                       model.class_thresholds);
    std::vector<double> disagree_weight(n, 0.0);
    ev_idx = 0;
    for (const FactorEvidence& ev : model.evidences) {
        const double weight = weights[ev_idx];
        const std::vector<int> implied =
            implied_class(memberships[ev_idx], model.class_thresholds);
        for (std::size_t i = 0; i < n; ++i) {
            if (finite_masks[ev_idx][i] && implied[i] >= 0 &&
                implied[i] != fused_class[i]) {
                disagree_weight[i] += weight;
            }
        }
        ++ev_idx;
    }
    std::vector<double> conflict_fraction(n);
    for (std::size_t i = 0; i < n; ++i) {
        conflict_fraction[i] = w_sum[i] > 0.0
            ? disagree_weight[i] / w_sum[i]
            : std::numeric_limits<double>::quiet_NaN();
    }

    std::vector<double> margin(n, std::numeric_limits<double>::quiet_NaN());
    if (!model.class_thresholds.empty()) {
        for (std::size_t i = 0; i < n; ++i) {
            if (!std::isfinite(likelihood[i])) continue;
            double best = std::numeric_limits<double>::infinity();
            for (double thr : model.class_thresholds) {
                best = std::min(best, std::fabs(likelihood[i] - thr));
            }
            margin[i] = best;
        }
    } else {
        for (std::size_t i = 0; i < n; ++i) {
            if (std::isfinite(likelihood[i])) margin[i] = 1.0;
        }
    }

    // Variance propagation on the common support of available evidence.
    std::optional<FactorGrid> variance;
    bool any_var = false;
    for (const FactorEvidence& ev : model.evidences) {
        if (ev.grid.variance_grid.has_value()) any_var = true;
    }
    if (any_var) {
        std::vector<double> var_acc(n, 0.0);
        std::vector<char> have_var(n, 0);
        ev_idx = 0;
        for (const FactorEvidence& ev : model.evidences) {
            if (ev.grid.variance_grid.has_value()) {
                const auto& var = *ev.grid.variance_grid;
                for (std::size_t i = 0; i < n; ++i) {
                    if (finite_masks[ev_idx][i]) {
                        const double share_raw = ev.weight / w_sum[i];
                        const double share = share_raw * share_raw;
                        var_acc[i] += share * static_cast<double>(var[i]);
                        have_var[i] = 1;
                    }
                }
            }
            ++ev_idx;
        }
        for (std::size_t i = 0; i < n; ++i) {
            if (!have_var[i]) var_acc[i] = std::numeric_limits<double>::quiet_NaN();
        }
        variance = build_grid(model, var_acc, reference, "融合方差", "1");
    }

    // class_grid: 0 = lowest class, thresholds ascend, highest wins.
    std::vector<double> class_grid(n, 0.0);
    for (std::size_t idx = 1; idx <= model.class_thresholds.size(); ++idx) {
        const double thr = model.class_thresholds[idx - 1];
        for (std::size_t i = 0; i < n; ++i) {
            if (std::isfinite(likelihood[i]) && likelihood[i] >= thr) {
                class_grid[i] = static_cast<double>(idx);
            }
        }
    }
    std::size_t n_finite = 0;
    for (std::size_t i = 0; i < n; ++i) {
        if (!std::isfinite(likelihood[i])) {
            class_grid[i] = std::numeric_limits<double>::quiet_NaN();
        } else {
            ++n_finite;
        }
    }

    std::size_t n_conf = 0, n_low_conf = 0;
    for (std::size_t i = 0; i < n; ++i) {
        if (std::isfinite(confidence[i])) {
            ++n_conf;
            if (confidence[i] < 0.3) ++n_low_conf;
        }
    }
    std::size_t n_cf = 0, n_high_cf = 0;
    double cf_sum = 0.0;
    for (std::size_t i = 0; i < n; ++i) {
        if (std::isfinite(conflict_fraction[i])) {
            ++n_cf;
            cf_sum += conflict_fraction[i];
            if (conflict_fraction[i] > 0.5) ++n_high_cf;
        }
    }
    std::size_t n_mg = 0, n_low_mg = 0;
    for (std::size_t i = 0; i < n; ++i) {
        if (std::isfinite(margin[i])) {
            ++n_mg;
            if (margin[i] < 0.05) ++n_low_mg;
        }
    }

    Json class_counts = Json::object();
    for (std::size_t i = 0; i < model.class_names.size(); ++i) {
        std::size_t count = 0;
        for (std::size_t c = 0; c < n; ++c) {
            if (class_grid[c] == static_cast<double>(i)) ++count;
        }
        class_counts[model.class_names[i]] = static_cast<std::int64_t>(count);
    }

    Json qc = {
        {"fusion_kind", model.kind},
        {"n_factors", static_cast<std::int64_t>(model.evidences.size())},
        {"unit_warnings", unit_warnings},
        {"classified_cells", static_cast<std::int64_t>(n_finite)},
        {"unclassified_cells",
         static_cast<std::int64_t>(n - n_finite)},
        {"class_counts", std::move(class_counts)},
        {"nan_policy", "renormalize"},
        {"low_confidence_fraction",
         n_conf ? Json(static_cast<double>(n_low_conf) /
                       static_cast<double>(n_conf))
                : Json(nullptr)},
        {"mean_conflict_fraction",
         n_cf ? Json(cf_sum / static_cast<double>(n_cf)) : Json(nullptr)},
        {"high_conflict_fraction",
         n_cf ? Json(static_cast<double>(n_high_cf) /
                     static_cast<double>(n_cf))
              : Json(nullptr)},
        {"low_margin_fraction",
         n_mg ? Json(static_cast<double>(n_low_mg) /
                     static_cast<double>(n_mg))
              : Json(nullptr)},
    };
    if (!fused_crs.has_value()) qc["crs_undeclared"] = true;

    FusionResult result;
    result.model = model;
    result.model_dict = model.to_dict();
    result.likelihood = build_grid(model, likelihood, reference,
                                   model.name + " 融合似然", "1");
    result.confidence = build_grid(model, confidence, reference,
                                   model.name + " 融合置信度", "1");
    result.variance = std::move(variance);
    result.class_names = model.class_names;
    result.qc = std::move(qc);
    result.likelihood.algorithm_parameters["class_thresholds"] =
        model.class_thresholds;
    return result;
}

FusionResult fuse_rule_based(const FusionModel& model) {
    // {factor_name: grid} — later duplicates overwrite (Python dict).
    std::map<std::string, FactorGrid> grids;
    std::vector<FactorGrid> ordered;
    ordered.reserve(model.evidences.size());
    for (const FactorEvidence& ev : model.evidences) {
        ordered.push_back(ev.grid);
        grids[ev.factor_name] = ev.grid;
    }
    const std::optional<std::string> fused_crs = aligned_or_raise(ordered);
    if (ordered.empty()) {
        // unreachable: aligned_or_raise throws first; kept for safety.
        throw IndexError("list index out of range");
    }
    const FactorGrid& reference = ordered[0];
    const std::size_t n = static_cast<std::size_t>(reference.height) *
                        static_cast<std::size_t>(reference.width);

    std::map<std::string, std::vector<double>> fields;
    for (const auto& [name, g] : grids) fields[name] = grid_values(g);

    std::vector<double> class_grid(n, std::numeric_limits<double>::quiet_NaN());
    std::vector<char> matched(n, 0);
    std::vector<std::int64_t> rule_hits(model.rules.size(), 0);
    for (std::size_t r_idx = 0; r_idx < model.rules.size(); ++r_idx) {
        const FusionRule& rule = model.rules[r_idx];
        std::vector<char> applicable(n);
        for (std::size_t i = 0; i < n; ++i) applicable[i] = matched[i] ? 0 : 1;
        for (const auto& [factor_name, op, threshold] : rule.conditions) {
            const auto it = fields.find(factor_name);
            if (it == fields.end()) {
                std::vector<std::string> known;
                for (const auto& [k, v] : fields) {
                    (void)v;
                    known.push_back(py_repr_string(k));
                }
                std::string list_repr = "[";
                for (std::size_t i = 0; i < known.size(); ++i) {
                    if (i) list_repr += ", ";
                    list_repr += known[i];
                }
                list_repr += "]";
                throw ValueError("rule references unknown factor " +
                                 py_repr_string(factor_name) +
                                 "; known: " + list_repr);
            }
            const std::vector<double>& vals = it->second;
            for (std::size_t i = 0; i < n; ++i) {
                if (applicable[i]) {
                    applicable[i] = (std::isfinite(vals[i]) &&
                                     rule_op(op, vals[i], threshold))
                                        ? 1
                                        : 0;
                }
            }
        }
        std::int64_t hits = 0;
        for (std::size_t i = 0; i < n; ++i) {
            if (applicable[i]) {
                class_grid[i] = static_cast<double>(r_idx) + 1.0;
                matched[i] = 1;
                ++hits;
            }
        }
        rule_hits[r_idx] = hits;
    }

    std::vector<char> no_evidence(n, 1);
    for (const auto& [name, vals] : fields) {
        (void)name;
        for (std::size_t i = 0; i < n; ++i) {
            if (std::isfinite(vals[i])) no_evidence[i] = 0;
        }
    }
    for (std::size_t i = 0; i < n; ++i) {
        if (!matched[i] && !no_evidence[i]) class_grid[i] = 0.0;
    }

    std::vector<double> confidence(n, std::numeric_limits<double>::quiet_NaN());
    for (std::size_t i = 0; i < n; ++i) {
        if (matched[i]) confidence[i] = 1.0;
        else if (class_grid[i] == 0.0 && !no_evidence[i]) confidence[i] = 0.0;
    }

    std::vector<std::string> names;
    names.push_back(model.default_class);
    for (const FusionRule& r : model.rules) names.push_back(r.class_name);

    std::int64_t classified = 0, default_cells = 0, unclassified = 0;
    for (std::size_t i = 0; i < n; ++i) {
        if (matched[i]) ++classified;
        if (class_grid[i] == 0.0 && !no_evidence[i]) ++default_cells;
        if (no_evidence[i]) ++unclassified;
    }
    Json hits_obj = Json::object();
    for (std::size_t i = 0; i < model.rules.size(); ++i) {
        hits_obj[model.rules[i].class_name] = rule_hits[i];
    }
    Json qc = {
        {"fusion_kind", model.kind},
        {"n_factors", static_cast<std::int64_t>(grids.size())},
        {"n_rules", static_cast<std::int64_t>(model.rules.size())},
        {"classified_cells", classified},
        {"default_cells", default_cells},
        {"unclassified_cells", unclassified},
        {"rule_hits", std::move(hits_obj)},
    };
    if (!fused_crs.has_value()) qc["crs_undeclared"] = true;

    FusionResult result;
    result.model = model;
    result.model_dict = model.to_dict();
    result.likelihood = build_grid(model, class_grid, reference,
                                   model.name + " 融合分类", "1");
    result.confidence = build_grid(model, confidence, reference,
                                   model.name + " 融合置信度", "1");
    result.variance = std::nullopt;
    result.class_names = std::move(names);
    result.qc = std::move(qc);
    result.likelihood.algorithm_parameters["class_encoding"] =
        "nan=nodata; 0=default; 1..n=rule_index";
    return result;
}

// --- sensitivity_report -----------------------------------------------------

namespace {
std::vector<double> classify_grid(const FusionResult& result) {
    // _classify_grid: weighted → threshold classification; rule → class grid.
    std::vector<double> likelihood;
    likelihood.reserve(result.likelihood.grid_z.size());
    for (float f : result.likelihood.grid_z) {
        likelihood.push_back(static_cast<double>(f));
    }
    if (result.model.kind == "weighted_evidence") {
        std::vector<double> out(likelihood.size(), 0.0);
        for (std::size_t idx = 1; idx <= result.model.class_thresholds.size();
             ++idx) {
            const double thr = result.model.class_thresholds[idx - 1];
            for (std::size_t i = 0; i < likelihood.size(); ++i) {
                if (std::isfinite(likelihood[i]) && likelihood[i] >= thr) {
                    out[i] = static_cast<double>(idx);
                }
            }
        }
        for (std::size_t i = 0; i < likelihood.size(); ++i) {
            if (!std::isfinite(likelihood[i])) {
                out[i] = std::numeric_limits<double>::quiet_NaN();
            }
        }
        return out;
    }
    return likelihood;
}
}  // namespace

Json sensitivity_report(const FusionModel& model, const FusionResult& baseline,
                        double delta) {
    (void)delta;  // accepted for signature parity; unused upstream.
    if (model.kind != "weighted_evidence") {
        return {{"kind", "leave_one_out"}, {"supported", false}};
    }
    const std::vector<double> base_classes = classify_grid(baseline);
    Json report = {
        {"kind", "leave_one_out"},
        {"supported", true},
        {"factors", Json::object()},
    };
    if (model.evidences.size() < 2) {
        report["reason"] = "single factor — no perturbation possible";
        const FactorEvidence& ev = model.evidences[0];
        report["factors"][ev.factor_name] = {
            {"weight", ev.weight},
            {"class_change_fraction", nullptr},
            {"changed_cells", 0},
            {"comparable_cells", 0},
        };
        return report;
    }
    for (std::size_t drop = 0; drop < model.evidences.size(); ++drop) {
        FusionModel reduced;
        reduced.name = model.name;
        reduced.kind = model.kind;
        reduced.rules = model.rules;
        reduced.default_class = model.default_class;
        reduced.class_thresholds = model.class_thresholds;
        reduced.class_names = model.class_names;
        for (std::size_t i = 0; i < model.evidences.size(); ++i) {
            if (i != drop) reduced.evidences.push_back(model.evidences[i]);
        }
        reduced.validate();
        const FusionResult variant = fuse_weighted(reduced);
        const std::vector<double> variant_classes = classify_grid(variant);
        std::int64_t total = 0, changed = 0;
        for (std::size_t i = 0; i < base_classes.size(); ++i) {
            if (std::isfinite(base_classes[i]) &&
                std::isfinite(variant_classes[i])) {
                ++total;
                if (base_classes[i] != variant_classes[i]) ++changed;
            }
        }
        report["factors"][model.evidences[drop].factor_name] = {
            {"weight", model.evidences[drop].weight},
            {"class_change_fraction",
             total ? Json(static_cast<double>(changed) /
                          static_cast<double>(total))
                   : Json(nullptr)},
            {"changed_cells", changed},
            {"comparable_cells", total},
        };
    }
    return report;
}

}  // namespace pwb::factor_fusion
