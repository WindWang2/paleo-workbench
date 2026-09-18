#include <pwb/geomodel/advisor_contract.hpp>

#include <cmath>
#include <cstdio>

namespace pwb::geomodel {

namespace {

// python type name for <class '...'> rendering in TypeError text
const char* py_type_name(const Json& v) {
    if (v.is_null()) return "NoneType";
    if (v.is_boolean()) return "bool";
    if (v.is_number_float()) return "float";
    if (v.is_number()) return "int";
    if (v.is_string()) return "str";
    if (v.is_array()) return "list";
    if (v.is_object()) return "dict";
    return "object";
}

// dict.get(key, default) — present (even null) wins, like Python.
const Json& jget(const Json& d, const char* key, const Json& dflt) {
    if (d.is_object() && d.contains(key)) return d[key];
    return dflt;
}

double jnum(const Json& v, double dflt = 0.0) {
    if (v.is_number()) return v.get<double>();
    if (v.is_boolean()) return v.get<bool>() ? 1.0 : 0.0;
    return dflt;
}

// np.isfinite on the JSON domain: numbers/bools ok; anything else raises
// numpy's ufunc TypeError verbatim.
bool np_isfinite(const Json& v) {
    if (v.is_number()) return std::isfinite(v.get<double>());
    if (v.is_boolean()) return true;
    throw TypeError(
        "ufunc 'isfinite' not supported for the input types, and the "
        "inputs could not be safely coerced to any supported types "
        "according to the casting rule ''safe''");
}

Json issue(const char* type, const std::string& who, const char* who_key,
           const std::string& msg) {
    return Json{{"type", type}, {who_key, who}, {"message", msg}};
}

// f"{v:.2f}"
std::string fmt2(double v) {
    char buf[64];
    std::snprintf(buf, sizeof buf, "%.2f", v);
    return buf;
}

}  // namespace

Json check_boreholes(const Json& records) {
    Json issues = Json::array();
    std::size_t checked = 0;
    const Json zero(0.0);
    const Json unk("Unknown");
    for (const auto& item : records) {
        if (!item.is_object())
            throw TypeError(
                "Expected BoreholeRecord or dict, got <class '" +
                std::string(py_type_name(item)) + "'>");
        ++checked;
        const Json name = jget(item, "name", unk);
        const Json x = jget(item, "x", zero);
        const Json y = jget(item, "y", zero);
        const Json td = jget(item, "total_depth", zero);
        const Json& layers = item.contains("layers") &&
                                     item["layers"].is_array()
                                 ? item["layers"]
                                 : Json::array();
        const std::string name_s = py_str(name);

        // np.isfinite(bh.x) / (bh.y) — TypeError on non-numbers
        const bool fx = np_isfinite(x);
        const bool fy = np_isfinite(y);
        if (!fx || !fy)
            issues.push_back(issue("error", name_s, "borehole",
                                   "Invalid coordinates: X=" + py_str(x) +
                                       ", Y=" + py_str(y)));

        if (!td.is_number() && !td.is_boolean())
            throw TypeError(
                "'<=' not supported between instances of '" +
                std::string(py_type_name(td)) + "' and 'int'");
        if (jnum(td) <= 0)
            issues.push_back(issue("error", name_s, "borehole",
                                   "Non-positive total depth: " +
                                       py_str(td)));

        // layers — last_bottom keeps its JSON number kind through max()
        Json last_bottom(0.0);
        for (std::size_t idx = 0; idx < layers.size(); ++idx) {
            const Json& l = layers[idx];
            const Json top = jget(l, "top", zero);
            const Json bottom = jget(l, "bottom", zero);
            const Json lith = jget(l, "lithology", unk);
            const std::string idx_s = std::to_string(idx);
            const std::string lith_s = py_str(lith);
            if (jnum(top) > jnum(bottom))
                issues.push_back(issue(
                    "error", name_s, "borehole",
                    "Layer " + idx_s + " (" + lith_s +
                        ") has inverted depths: top=" + py_str(top) +
                        " > bottom=" + py_str(bottom)));
            if (jnum(top) < jnum(last_bottom) - 1e-5)
                issues.push_back(issue(
                    "warning", name_s, "borehole",
                    "Layer " + idx_s + " (" + lith_s +
                        ") top=" + py_str(top) +
                        " overlaps with previous bottom=" +
                        py_str(last_bottom)));
            // last_bottom = max(last_bottom, layer.bottom) — Python max
            // returns the larger OBJECT, preserving int/float kind.
            if (jnum(bottom) > jnum(last_bottom)) last_bottom = bottom;
        }
        if (jnum(last_bottom) > jnum(td) + 1e-5)
            issues.push_back(issue(
                "warning", name_s, "borehole",
                "Layers extend to bottom=" + py_str(last_bottom) +
                    ", exceeding total depth=" + py_str(td)));
    }
    bool any_error = false;
    for (const auto& i : issues)
        if (i["type"] == "error") any_error = true;
    return Json{{"checked_boreholes", static_cast<long long>(checked)},
                {"issues", std::move(issues)},
                {"status", any_error ? "FAIL" : "PASS"}};
}

Json check_coplanar_faults(const Json& records) {
    Json issues = Json::array();
    struct F {
        std::string name;
        double n[3];
        double d;
    };
    std::vector<F> fs;
    const Json unk("Unknown");
    const Json dflt_normal = Json::array({1.0, 0.0, 0.0});
    const Json zero(0.0);
    for (const auto& item : records) {
        if (!item.is_object())
            throw TypeError("Expected FaultRecord or dict, got <class '" +
                            std::string(py_type_name(item)) + "'>");
        F f;
        f.name = py_str(jget(item, "name", unk));
        const Json& n = jget(item, "normal", dflt_normal);
        for (int i = 0; i < 3; ++i)
            f.n[i] = (n.is_array() && n.size() > static_cast<size_t>(i))
                         ? jnum(n[i])
                         : 0.0;
        f.d = jnum(jget(item, "d", zero));
        fs.push_back(f);
    }
    for (std::size_t i = 0; i < fs.size(); ++i) {
        for (std::size_t j = i + 1; j < fs.size(); ++j) {
            const F& f1 = fs[i];
            const F& f2 = fs[j];
            const double l1 = std::sqrt(f1.n[0] * f1.n[0] +
                                        f1.n[1] * f1.n[1] + f1.n[2] * f1.n[2]);
            const double l2 = std::sqrt(f2.n[0] * f2.n[0] +
                                        f2.n[1] * f2.n[1] + f2.n[2] * f2.n[2]);
            const double dot = (f1.n[0] / l1) * (f2.n[0] / l2) +
                               (f1.n[1] / l1) * (f2.n[1] / l2) +
                               (f1.n[2] / l1) * (f2.n[2] / l2);
            const bool parallel = std::abs(std::abs(dot) - 1.0) < 0.05;
            if (!parallel) continue;
            const double d1 = f1.d / std::max(l1, 1e-12);
            const double d2 = (dot < 0 ? -f2.d : f2.d) / std::max(l2, 1e-12);
            const double dist = std::abs(d1 - d2);
            if (dist < 15.0) {
                const double deg =
                    std::acos(std::min(std::abs(dot), 1.0)) * 180.0 /
                    3.14159265358979323846;
                issues.push_back(Json{
                    {"type", "warning"},
                    {"faults", Json::array({f1.name, f2.name})},
                    {"message", "Faults " + f1.name + " and " + f2.name +
                                    " are coplanar. Angle diff: " +
                                    fmt2(deg) +
                                    "\xC2\xB0, Distance diff: " + fmt2(dist)}});
            }
        }
    }
    const char* status = issues.empty() ? "PASS" : "WARNING";
    return Json{{"checked_faults", static_cast<long long>(fs.size())},
                {"issues", std::move(issues)},
                {"status", status}};
}

// ---------------------------------------------------------------------------
// lithology
// ---------------------------------------------------------------------------

const std::vector<std::pair<std::string, double>>& litho_gr() {
    static const std::vector<std::pair<std::string, double>> t = {
        {"\xE7\xA0\x82\xE5\xB2\xA9", 40.0},   // 砂岩
        {"\xE6\xB3\xA5\xE5\xB2\xA9", 120.0},  // 泥岩
        {"\xE7\x9F\xB3\xE7\x81\xB0\xE5\xB2\xA9", 25.0},  // 石灰岩
        {"\xE8\x8A\xB1\xE5\xB2\x97\xE5\xB2\xA9", 80.0}};  // 花岗岩
    return t;
}
const std::vector<std::pair<std::string, double>>& litho_sonic() {
    static const std::vector<std::pair<std::string, double>> t = {
        {"\xE7\xA0\x82\xE5\xB2\xA9", 180.0},
        {"\xE6\xB3\xA5\xE5\xB2\xA9", 250.0},
        {"\xE7\x9F\xB3\xE7\x81\xB0\xE5\xB2\xA9", 150.0},
        {"\xE8\x8A\xB1\xE5\xB2\x97\xE5\xB2\xA9", 120.0}};
    return t;
}
const std::vector<std::pair<std::string, double>>& litho_density() {
    static const std::vector<std::pair<std::string, double>> t = {
        {"\xE7\xA0\x82\xE5\xB2\xA9", 2.2},
        {"\xE6\xB3\xA5\xE5\xB2\xA9", 2.4},
        {"\xE7\x9F\xB3\xE7\x81\xB0\xE5\xB2\xA9", 2.65},
        {"\xE8\x8A\xB1\xE5\xB2\x97\xE5\xB2\xA9", 2.7}};
    return t;
}
const std::vector<std::pair<std::string, double>>& litho_ai() {
    static const std::vector<std::pair<std::string, double>> t = {
        {"\xE7\xA0\x82\xE5\xB2\xA9", 8200.0},
        {"\xE6\xB3\xA5\xE5\xB2\xA9", 4800.0},
        {"\xE7\x9F\xB3\xE7\x81\xB0\xE5\xB2\xA9", 14500.0},
        {"\xE8\x8A\xB1\xE5\xB2\x97\xE5\xB2\xA9", 18000.0}};
    return t;
}

namespace {
Json table_json(const std::vector<std::pair<std::string, double>>& t) {
    Json o = Json::object();
    for (const auto& [k, v] : t) o[k] = v;
    return o;
}
}  // namespace

Json lithology_tables() {
    return Json{{"LITHO_GR", table_json(litho_gr())},
                {"LITHO_SONIC", table_json(litho_sonic())},
                {"LITHO_DENSITY", table_json(litho_density())},
                {"LITHO_AI", table_json(litho_ai())},
                {"DEFAULT_GR", kDefaultGR},
                {"DEFAULT_SONIC", kDefaultSonic},
                {"DEFAULT_DENSITY", kDefaultDensity},
                {"DEFAULT_AI", kDefaultAI}};
}

Json sample_log_values(const Json& layers, const Json& depths,
                       const std::string& table_name, double dflt) {
    const std::vector<std::pair<std::string, double>>* table = nullptr;
    if (table_name == "LITHO_GR") table = &litho_gr();
    else if (table_name == "LITHO_SONIC") table = &litho_sonic();
    else if (table_name == "LITHO_DENSITY") table = &litho_density();
    else if (table_name == "LITHO_AI") table = &litho_ai();
    Json out = Json::array();
    for (const auto& d : depths) out.push_back(0.0);
    for (std::size_t li = 0; li < layers.size(); ++li) {
        const Json& l = layers[li];
        const double top = jnum(jget(l, "top", Json(0.0)));
        const double bottom = jnum(jget(l, "bottom", Json(0.0)));
        const std::string lith = py_str(jget(l, "lithology", Json("")));
        double v = dflt;
        if (table)
            for (const auto& [k, tv] : *table)
                if (k == lith) v = tv;
        const float fv = static_cast<float>(v);
        for (std::size_t di = 0; di < depths.size(); ++di) {
            const double d = jnum(depths[di]);
            if (d >= top && d < bottom) out[di] = static_cast<double>(fv);
        }
    }
    return out;
}

}  // namespace pwb::geomodel
