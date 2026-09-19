// CONV-32 — C++ port of
// paleo_workbench/workflow/interpretation/algorithm_registry.py.
//
// The single authority for algorithm capability declarations: the frozen
// 9-entry ALGORITHMS table (insertion order kriging, idw, constrained_idw,
// spline, directional, linear, nearest, rbf, factor_fusion), the case-folded
// alias index, and the UI method-list derivations. Verbatim-string contract:
// labels/aliases/notes are byte-identical to the Python source; the oracle
// fixture (tools/oracle/generate_workflow_interpretation_registry_fixtures.py)
// freezes the real Python outputs this port must reproduce.
//
// Port notes (Python -> C++):
//  * ValueError parity: the frozen header declares canonical_algorithm_id
//    throws "AlgorithmValueError" but does not export the type, so it lives
//    here as a std::invalid_argument subclass with python_class()
//    == "ValueError". Callers catch std::invalid_argument; the message text
//    is the oracle ("empty algorithm reference" / "unknown algorithm:
//    '<repr of the ORIGINAL unstripped ref>'").
//  * ALGORITHMS insertion order cannot be preserved: the frozen header
//    exposes std::map<std::string, AlgorithmSpec> (key-sorted). No Python
//    observable depends on that order — the only iteration is
//    _rebuild_alias_index, whose per-spec key writes never collide across
//    algorithms, and the UI lists derive from UI_INTERPOLATION_METHODS, not
//    ALGORITHMS. Membership (order-insensitive) is the frozen contract.
//  * supported_constraints projects from capabilities_for_method in the
//    caps dict encounter order. MethodCapabilities::support is a
//    std::map<ConstraintKind, …> ordered by enum, which equals the Python
//    encounter order for every multi-cell method (constrained_idw:
//    boundary_mask < barrier < direction < anisotropy < trend;
//    directional: direction < anisotropy < trend). AlgorithmSpec stores the
//    projection keyed by kind VALUE string (frozen header type), so to_dict
//    emits those keys lexicographically — the Python dict order differs;
//    key order is not observable through the oracle's semantic compare.
//  * factor_fusion is a LITERAL spec: supported_constraints empty and
//    prerequisites empty (NOT projected from the capabilities matrix).
#include <pwb/workflow_interpretation/algorithm_registry.hpp>

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace pwb::workflow_interpretation {
namespace {

// Python ValueError parity (see header comment). Defined here because the
// frozen header does not export the exception type; catch via its
// std::invalid_argument base.
class AlgorithmValueError : public std::invalid_argument {
public:
    explicit AlgorithmValueError(const std::string& what_arg)
        : std::invalid_argument(what_arg) {}
    [[nodiscard]] const char* python_class() const noexcept {
        return "ValueError";
    }
};

// Python str.strip() — ASCII whitespace only (no U+00A0/U+3000 forms exist
// in the frozen vocabulary).
std::string strip(const std::string& s) {
    const auto ws = [](unsigned char c) {
        return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' ||
               c == '\v';
    };
    std::size_t b = 0;
    std::size_t e = s.size();
    while (b < e && ws(static_cast<unsigned char>(s[b]))) ++b;
    while (e > b && ws(static_cast<unsigned char>(s[e - 1]))) --e;
    return s.substr(b, e - b);
}

// Python str.lower() for this vocabulary (ASCII letters only; CJK and the
// '·' separator are lower()-invariant).
std::string lower_ascii(const std::string& s) {
    std::string out = s;
    std::transform(out.begin(), out.end(), out.begin(), [](unsigned char c) {
        return static_cast<char>(c >= 'A' && c <= 'Z' ? c - 'A' + 'a' : c);
    });
    return out;
}

// Python repr() of a str for the frozen inputs (single quotes; backslash
// and single quote escaped). CPython would switch to double quotes when the
// payload contains ' but no "; no frozen input hits that case.
std::string py_repr_str(const std::string& s) {
    std::string out = "'";
    for (const char c : s) {
        if (c == '\\' || c == '\'') out += '\\';
        out += c;
    }
    out += '\'';
    return out;
}

Json schema(const std::string& text) { return Json::parse(text); }

struct RegistryState {
    std::map<std::string, AlgorithmSpec> algorithms;
    std::map<std::string, std::string> alias_index;
};

// _from_capabilities — capability projection (engine vocabulary).
AlgorithmSpec from_capabilities(const std::string& algorithm_id,
                                const std::string& label,
                                const std::vector<std::string>& aliases,
                                const std::string& ui_label,
                                const Json& parameter_schema,
                                bool produces_uncertainty,
                                const std::string& backend,
                                const std::string& notes) {
    std::optional<MethodCapabilities> caps;
    try {
        caps = capabilities_for_method(algorithm_id);
    } catch (const std::out_of_range&) {
        caps.reset();  // Python: except KeyError -> caps = None
    }
    AlgorithmSpec spec;
    spec.algorithm_id = algorithm_id;
    spec.family = "interpolation";
    spec.display_label = label;
    spec.aliases = aliases;
    spec.ui_label = ui_label.empty() ? label : ui_label;  // ui_label or label
    spec.parameter_schema = parameter_schema;
    if (caps.has_value()) {
        for (const auto& [kind, cell] : caps->support) {
            spec.supported_constraints[to_string(kind)] = {
                to_string(cell.level), cell.note};
        }
        spec.prerequisites = caps->prerequisites;
    }
    spec.produces_uncertainty = produces_uncertainty;
    spec.backend = backend;
    spec.notes = notes;
    return spec;
}

void rebuild_alias_index(RegistryState& state) {
    state.alias_index.clear();
    for (const auto& [id, spec] : state.algorithms) {
        state.alias_index[lower_ascii(id)] = id;
        for (const std::string& alias : spec.aliases) {
            state.alias_index[lower_ascii(alias)] = id;
        }
    }
}

RegistryState build_registry() {
    RegistryState state;
    // Insertion order kriging, idw, constrained_idw, spline, directional,
    // linear, nearest, rbf (factor_fusion appended below). std::map stores
    // key-sorted; only the rebuild iteration order is lost (collision-free —
    // see file header note).
    const std::vector<AlgorithmSpec> specs = {
        from_capabilities(
            "kriging", "克里金", {"克里金", "克里金(MVP·线性)", "ordinary_kriging", "ok"},
            "克里金",
            schema(R"({"type":"object","properties":{"grid_n":{"type":"integer","minimum":8,"maximum":2000},"variogram_model":{"type":"string","enum":["spherical","exponential","gaussian"]}}})"),
            true, "kriging", ""),
        from_capabilities(
            "idw", "IDW 反距离加权", {"IDW", "反距离加权", "IDW反距离加权"}, "IDW",
            schema(R"({"type":"object","properties":{"grid_n":{"type":"integer","minimum":8,"maximum":2000},"power":{"type":"number","minimum":0.5,"maximum":8.0}}})"),
            false, "idw", ""),
        from_capabilities(
            "constrained_idw", "约束IDW", {"约束IDW", "约束反距离加权", "constrained idw"},
            "约束IDW",
            schema(R"({"type":"object","properties":{"grid_n":{"type":"integer","minimum":8,"maximum":2000},"power":{"type":"number","minimum":0.5,"maximum":8.0}}})"),
            false, "constrained_idw", ""),
        from_capabilities(
            "spline", "样条 (CloughTocher)", {"样条", "spline", "cubic", "样条插值"},
            "样条", Json::object(), false, "cubic", ""),
        from_capabilities(
            "directional", "方向趋势", {"方向趋势", "方向趋势面", "directional trend"},
            "方向趋势",
            schema(R"({"type":"object","properties":{"azimuth_deg":{"type":"number","minimum":0,"maximum":360},"semi_major":{"type":"number","exclusiveMinimum":0},"semi_minor":{"type":"number","exclusiveMinimum":0}}})"),
            false, "directional", ""),
        from_capabilities("linear", "线性插值", {"线性插值", "linear"}, "",
                          Json::object(), false, "", ""),
        from_capabilities("nearest", "最近邻", {"最近邻", "nearest"}, "",
                          Json::object(), false, "", ""),
        from_capabilities("rbf", "RBF 多二次", {"RBF", "rbf", "RBF 多二次"}, "",
                          Json::object(), false, "", ""),
        // factor_fusion — literal spec (supported_constraints and
        // prerequisites are NOT projected from the capabilities matrix).
        [] {
            AlgorithmSpec spec;
            spec.algorithm_id = "factor_fusion";
            spec.family = "fusion";
            spec.display_label = "多因素证据融合";
            spec.aliases = {"factor_fusion", "融合", "多因素融合",
                            "weighted_evidence"};
            spec.ui_label = "";
            spec.parameter_schema = schema(
                R"({"type":"object","properties":{"kind":{"type":"string","enum":["weighted_evidence","rule_based"]},"class_thresholds":{"type":"array","items":{"type":"number"}}}})");
            spec.supported_constraints = {};
            spec.requires_crs = true;
            spec.produces_uncertainty = true;
            spec.backend = "factor_fusion";
            spec.notes = "不确定性=coverage×agreement 置信格 + 公共支撑方差传播";
            return spec;
        }(),
    };
    for (const AlgorithmSpec& spec : specs) {
        state.algorithms.emplace(spec.algorithm_id, spec);
    }
    rebuild_alias_index(state);
    return state;
}

RegistryState& state() {
    static RegistryState registry = build_registry();
    return registry;
}

}  // namespace

ConstraintSupport AlgorithmSpec::constraint_support(ConstraintKind kind) const {
    const auto it = supported_constraints.find(to_string(kind));
    if (it == supported_constraints.end()) {
        return {Support::UNSUPPORTED, "not consumed by this method"};
    }
    return {support_from(it->second.first), it->second.second};
}

Json AlgorithmSpec::to_dict() const {
    Json projected = Json::object();
    for (const auto& [kind, entry] : supported_constraints) {
        projected[kind] = Json::array({entry.first, entry.second});
    }
    Json out = Json::object();
    out["algorithm_id"] = algorithm_id;
    out["family"] = family;
    out["display_label"] = display_label;
    out["ui_label"] = ui_label.empty() ? display_label : ui_label;
    out["aliases"] = aliases;
    out["parameter_schema"] = parameter_schema;
    out["supported_constraints"] = projected;
    out["supports_cancel"] = supports_cancel;
    out["requires_crs"] = requires_crs;
    out["requires_unit"] = requires_unit;
    out["produces_uncertainty"] = produces_uncertainty;
    out["backend"] = backend;
    out["prerequisites"] = prerequisites;
    return out;
}

const std::map<std::string, AlgorithmSpec>& algorithms() {
    return state().algorithms;
}

void register_algorithm(const AlgorithmSpec& spec) {
    RegistryState& reg = state();
    reg.algorithms[spec.algorithm_id] = spec;  // replace-or-insert
    rebuild_alias_index(reg);
}

const AlgorithmSpec* get_algorithm(const std::string& id) {
    const auto it = state().algorithms.find(strip(id));
    return it == state().algorithms.end() ? nullptr : &it->second;
}

std::string canonical_algorithm_id(const std::string& ref) {
    const std::string text = strip(ref);
    if (text.empty()) {
        throw AlgorithmValueError("empty algorithm reference");
    }
    const auto it = state().alias_index.find(lower_ascii(text));
    if (it == state().alias_index.end()) {
        // repr of the ORIGINAL unstripped reference.
        throw AlgorithmValueError("unknown algorithm: " + py_repr_str(ref));
    }
    return it->second;
}

std::string display_label(const std::string& algorithm_id) {
    const AlgorithmSpec* spec = get_algorithm(canonical_algorithm_id(algorithm_id));
    return spec != nullptr ? spec->display_label : algorithm_id;
}

const std::vector<std::string>& ui_interpolation_method_ids() {
    // UI_INTERPOLATION_METHODS — Python insertion order.
    static const std::vector<std::string> ids = {"kriging", "idw",
                                                 "constrained_idw", "spline",
                                                 "directional"};
    return ids;
}

std::vector<std::string> ui_interpolation_methods() {
    std::vector<std::string> out;
    for (const std::string& id : ui_interpolation_method_ids()) {
        const auto it = state().algorithms.find(id);
        if (it == state().algorithms.end()) continue;
        const AlgorithmSpec& spec = it->second;
        out.push_back(spec.ui_label.empty() ? spec.display_label
                                            : spec.ui_label);
    }
    return out;
}

std::map<std::string, std::string> interpolation_algorithm_labels() {
    std::map<std::string, std::string> out;
    for (const std::string& id : ui_interpolation_method_ids()) {
        const auto it = state().algorithms.find(id);
        if (it == state().algorithms.end()) continue;
        const AlgorithmSpec& spec = it->second;
        out[spec.ui_label.empty() ? spec.display_label : spec.ui_label] = id;
    }
    return out;
}

}  // namespace pwb::workflow_interpretation
