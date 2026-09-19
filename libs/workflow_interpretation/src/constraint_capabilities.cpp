// CONV-32 — C++ port of paleo_workbench/workflow/constraint_capabilities.py.
//
// The method × constraint capability matrix (engine vocabulary) + honest
// request evaluation. Verbatim-string contract: every note/diagnostic below
// is byte-identical to the Python source (em-dashes, fullwidth punctuation,
// case-folding semantics); the oracle fixture
// (tools/oracle/generate_workflow_interpretation_registry_fixtures.py)
// freezes the real Python outputs this port must reproduce.
//
// Port notes (Python -> C++):
//  * KeyError parity: capabilities_for_method throws std::out_of_range with
//    the exact Python message (repr of the ORIGINAL argument + the sorted
//    known list as a Python list-repr). str(KeyError(...)) would repr-quote
//    the message; the oracle freezes both forms and the test verifies them.
//  * ValueError parity: the enum coercions (constraint_kind_from /
//    support_from) throw std::invalid_argument with Python's
//    "'<v>' is not a valid <EnumName>" text; ConstraintViolationError is the
//    ValueError subclass declared in the frozen header (std::runtime_error
//    base — frozen contract).
//  * _METHODS is insertion-ordered in Python; capability_matrix() must emit
//    that exact order, so the table lives in a vector, not a map. The
//    per-method support cells are stored in std::map<ConstraintKind, …>
//    (frozen header type) — enum order equals the Python dict encounter
//    order for every method (each literal is declared in nondecreasing enum
//    order), so iteration order is preserved.
//  * evaluate_request dedupes on the RAW requested strings (Python compares
//    the raw items against the seen set before ConstraintKind coercion);
//    app.requested stores the canonical coerced values.
#include <pwb/workflow_interpretation/constraint_capabilities.hpp>

#include <algorithm>
#include <cstddef>
#include <stdexcept>
#include <utility>
#include <vector>

namespace pwb::workflow_interpretation {
namespace {

constexpr ConstraintKind kConstraintKinds[] = {
    ConstraintKind::BOUNDARY_MASK, ConstraintKind::BARRIER,
    ConstraintKind::DIRECTION,     ConstraintKind::ANISOTROPY,
    ConstraintKind::TREND,
};

// Python str.strip() for this vocabulary: the method ids/aliases carry only
// ASCII whitespace (no U+00A0/U+3000 forms exist in the frozen data).
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

// Python str.lower() for this vocabulary (ASCII letters only; the CJK
// characters and the '·' separator are lower()-invariant).
std::string lower_ascii(const std::string& s) {
    std::string out = s;
    std::transform(out.begin(), out.end(), out.begin(), [](unsigned char c) {
        return static_cast<char>(c >= 'A' && c <= 'Z' ? c - 'A' + 'a' : c);
    });
    return out;
}

// Python repr() of a str for the frozen inputs: single quotes, backslash
// and single quote escaped. (CPython would switch to double quotes for a
// payload containing ' but no "; no frozen input hits that case.)
std::string py_repr_str(const std::string& s) {
    std::string out = "'";
    for (const char c : s) {
        if (c == '\\' || c == '\'') out += '\\';
        out += c;
    }
    out += '\'';
    return out;
}

std::string join_comma(const std::vector<std::string>& parts) {
    std::string out;
    for (std::size_t i = 0; i < parts.size(); ++i) {
        if (i != 0) out += ", ";
        out += parts[i];
    }
    return out;
}

// sorted(_METHODS) rendered as a Python list-repr.
std::string known_methods_repr(const std::vector<MethodCapabilities>& table) {
    std::vector<std::string> ids;
    ids.reserve(table.size());
    for (const auto& m : table) ids.push_back(m.method);
    std::sort(ids.begin(), ids.end());  // codepoint sort == Python sorted()
    std::string out = "[";
    for (std::size_t i = 0; i < ids.size(); ++i) {
        if (i != 0) out += ", ";
        out += py_repr_str(ids[i]);
    }
    out += ']';
    return out;
}

MethodCapabilities make_caps(
    std::string method, std::string label,
    std::vector<std::pair<ConstraintKind, ConstraintSupport>> cells,
    std::vector<std::string> prerequisites) {
    MethodCapabilities caps;
    caps.method = std::move(method);
    caps.label = std::move(label);
    for (auto& cell : cells) caps.support.emplace(cell.first, cell.second);
    caps.prerequisites = std::move(prerequisites);
    return caps;
}

// Python source quirk, faithfully ported: rbf's prerequisites literal is
// ("global solve; not reachable from the UI method list") — a parenthesized
// str, NOT a 1-tuple (the trailing comma is missing) — so every Python
// iteration (capability_matrix's list(), _from_capabilities' tuple())
// yields the string's individual characters. The frozen oracle captured
// that; this reproduces it byte-for-byte.
std::vector<std::string> python_iterate_str(const std::string& s) {
    std::vector<std::string> out;
    out.reserve(s.size());
    for (const char c : s) out.emplace_back(1, c);
    return out;
}

// _METHODS — insertion order idw, constrained_idw, kriging, spline, linear,
// nearest, rbf, directional (Python dict order; capability_matrix emits it).
const std::vector<MethodCapabilities>& methods() {
    static const std::string partial_hull =
        "clips to the samples' convex hull; a user-drawn boundary ring is not "
        "honored";
    static const std::vector<MethodCapabilities> table = {
        make_caps(
            "idw", "IDW 反距离加权",
            {{ConstraintKind::BARRIER,
              {Support::SUPPORTED,
               "break lines zero node→sample weights across the barrier "
               "segment"}}},
            {}),
        make_caps(
            "constrained_idw", "约束IDW",
            {{ConstraintKind::BOUNDARY_MASK,
              {Support::SUPPORTED,
               "rasterized domain = boundary rings − holes ∩ coverage ∩ "
               "hull"}},
             {ConstraintKind::BARRIER,
              {Support::SUPPORTED,
               "hard line-of-sight barrier + region partitioning + blank "
               "corridor"}},
             {ConstraintKind::DIRECTION,
              {Support::SUPPORTED,
               "curve-coordinate corridor anisotropy along direction "
               "lines"}},
             {ConstraintKind::ANISOTROPY,
              {Support::PARTIAL,
               "anisotropy ratio floored at 16 by the host adapter "
               "(documented)"}},
             {ConstraintKind::TREND,
              {Support::SUPPORTED,
               "declustering weights (q honored via corridor; b_i not "
               "consumed)"}}},
            {"scipy"}),
        make_caps(
            "kriging", "普通克里金",
            {{ConstraintKind::ANISOTROPY,
              {Support::SUPPORTED,
               "geometric anisotropy: azimuth + major/minor ratio via the "
               "anisotropic variogram transform (V6 §11)"}}},
            {"≥3 non-collocated samples"}),
        make_caps(
            "spline", "样条 (CloughTocher)",
            {{ConstraintKind::BOUNDARY_MASK, {Support::PARTIAL, partial_hull}}},
            {"scipy"}),
        make_caps(
            "linear", "线性插值",
            {{ConstraintKind::BOUNDARY_MASK, {Support::PARTIAL, partial_hull}}},
            {}),
        make_caps(
            "nearest", "最近邻",
            {{ConstraintKind::BOUNDARY_MASK, {Support::PARTIAL, partial_hull}}},
            {}),
        make_caps(
            "rbf", "RBF 多二次",
            {{ConstraintKind::BOUNDARY_MASK, {Support::PARTIAL, partial_hull}}},
            python_iterate_str(
                "global solve; not reachable from the UI method list")),
        make_caps(
            "directional", "方向趋势",
            {{ConstraintKind::DIRECTION,
              {Support::PARTIAL,
               "multi-line anisotropy averaged into one global azimuth"}},
             {ConstraintKind::ANISOTROPY,
              {Support::PARTIAL,
               "azimuth + semi-axes honored; global single corridor"}},
             {ConstraintKind::TREND,
              {Support::SUPPORTED,
               "per-sample q/b_i weights multiply the Gaussian kernel"}}},
            {}),
    };
    return table;
}

// _LABEL_ALIASES — applied only after the strip+lower direct lookup misses.
constexpr std::pair<const char*, const char*> kLabelAliases[] = {
    {"克里金", "kriging"},
    {"克里金(mvp·线性)", "kriging"},
    {"反距离加权", "idw"},
    {"idw", "idw"},
    {"约束idw", "constrained_idw"},
    {"样条", "spline"},
    {"线性", "linear"},
    {"最近邻", "nearest"},
    {"方向趋势", "directional"},
    {"rbf", "rbf"},
};

const MethodCapabilities* find_method(const std::string& key) {
    for (const auto& caps : methods()) {
        if (caps.method == key) return &caps;
    }
    return nullptr;
}

}  // namespace

std::string to_string(ConstraintKind v) {
    switch (v) {
        case ConstraintKind::BOUNDARY_MASK: return "boundary_mask";
        case ConstraintKind::BARRIER: return "barrier";
        case ConstraintKind::DIRECTION: return "direction";
        case ConstraintKind::ANISOTROPY: return "anisotropy";
        case ConstraintKind::TREND: return "trend";
    }
    return "boundary_mask";
}

std::string to_string(Support v) {
    switch (v) {
        case Support::SUPPORTED: return "supported";
        case Support::PARTIAL: return "partial";
        case Support::APPROXIMATION: return "approximation";
        case Support::UNSUPPORTED: return "unsupported";
    }
    return "unsupported";
}

ConstraintKind constraint_kind_from(const std::string& v) {
    for (const ConstraintKind kind : kConstraintKinds) {
        if (to_string(kind) == v) return kind;
    }
    throw std::invalid_argument("'" + v + "' is not a valid ConstraintKind");
}

Support support_from(const std::string& v) {
    if (v == "supported") return Support::SUPPORTED;
    if (v == "partial") return Support::PARTIAL;
    if (v == "approximation") return Support::APPROXIMATION;
    if (v == "unsupported") return Support::UNSUPPORTED;
    throw std::invalid_argument("'" + v + "' is not a valid Support");
}

ConstraintSupport MethodCapabilities::for_kind(ConstraintKind kind) const {
    const auto it = support.find(kind);
    if (it != support.end()) return it->second;
    return {Support::UNSUPPORTED, "not consumed by this method"};
}

ConstraintViolationError::ConstraintViolationError(
    std::string method, std::vector<std::string> unsupported,
    std::vector<std::string> ignored)
    : std::runtime_error([&] {
          // "method '<m>' cannot honor the requested constraints:"
          // [+ "; unsupported: a, b"] [+ "; ignored: c"] — joined with ";"
          // (the ":;" artifact when only the colon-part precedes is
          // byte-exact Python behavior; the parameters are only read here,
          // before the member moves below).
          std::string msg = "method " + py_repr_str(method) +
                            " cannot honor the requested constraints:";
          if (!unsupported.empty()) {
              msg += "; unsupported: " + join_comma(unsupported);
          }
          if (!ignored.empty()) {
              msg += "; ignored: " + join_comma(ignored);
          }
          return msg;
      }()),
      method(std::move(method)),
      unsupported(std::move(unsupported)),
      ignored(std::move(ignored)) {}

bool ConstraintApplication::honest() const {
    // not (set(ignored) - set(diagnostics_labels()))
    const std::set<std::string> labels = diagnostics_labels();
    for (const std::string& item : ignored) {
        if (labels.find(item) == labels.end()) return false;
    }
    return true;
}

std::set<std::string> ConstraintApplication::diagnostics_labels() const {
    std::set<std::string> out;
    for (const std::string& d : diagnostics) {
        const std::size_t colon = d.find(':');
        out.insert(colon == std::string::npos ? d : d.substr(0, colon));
    }
    return out;
}

Json ConstraintApplication::as_dict() const {
    Json out = Json::object();
    out["method"] = method;
    out["requested_constraints"] = requested;
    out["applied_constraints"] = applied;
    out["partial_constraints"] = partial;
    out["ignored_constraints"] = ignored;
    out["unsupported_constraints"] = unsupported;
    out["constraint_diagnostics"] = diagnostics;
    return out;
}

MethodCapabilities capabilities_for_method(const std::string& method) {
    const std::string key = lower_ascii(strip(method));
    const MethodCapabilities* caps = find_method(key);
    if (caps == nullptr) {
        for (const auto& [alias, id] : kLabelAliases) {
            if (alias == key) {
                caps = find_method(id);
                break;
            }
        }
    }
    if (caps == nullptr) {
        // KeyError parity (thrown as std::out_of_range — noted in the test):
        // repr of the ORIGINAL argument, not the normalized key.
        throw std::out_of_range("unknown interpolation method " +
                                py_repr_str(method) + "; known: " +
                                known_methods_repr(methods()));
    }
    return *caps;
}

ConstraintApplication evaluate_request(const std::string& method,
                                       const std::vector<std::string>& requested,
                                       bool strict) {
    const MethodCapabilities caps = capabilities_for_method(method);
    ConstraintApplication app;
    app.method = caps.method;
    std::vector<std::string> seen_kinds;  // raw strings, Python parity
    for (const std::string& raw : requested) {
        if (std::find(seen_kinds.begin(), seen_kinds.end(), raw) !=
            seen_kinds.end()) {
            continue;
        }
        seen_kinds.push_back(raw);
        const ConstraintKind kind = constraint_kind_from(raw);
        const std::string value = to_string(kind);
        app.requested.push_back(value);
        const ConstraintSupport cs = caps.for_kind(kind);
        switch (cs.level) {
            case Support::SUPPORTED:
                app.applied.push_back(value);
                break;
            case Support::PARTIAL:
                app.partial.push_back(value);
                app.diagnostics.push_back(value + ":partial:" + cs.note);
                break;
            case Support::APPROXIMATION:
                app.partial.push_back(value);
                app.diagnostics.push_back(value + ":approximation:" + cs.note);
                break;
            case Support::UNSUPPORTED:
                app.unsupported.push_back(value);
                app.diagnostics.push_back(
                    value + ":unsupported:" + caps.label + " ignores " +
                    value + " — the surface will NOT reflect this constraint");
                break;
        }
    }
    if (strict && (!app.unsupported.empty() || !app.ignored.empty())) {
        throw ConstraintViolationError(caps.method, app.unsupported,
                                       app.ignored);
    }
    return app;
}

Json capability_matrix() {
    Json out = Json::object();
    for (const auto& caps : methods()) {
        Json row = Json::object();
        for (const ConstraintKind kind : kConstraintKinds) {
            const ConstraintSupport cs = caps.for_kind(kind);
            row[to_string(kind)] = Json{
                {"support", to_string(cs.level)}, {"notes", cs.note}};
        }
        out[caps.method] = Json{{"label", caps.label},
                                {"prerequisites", caps.prerequisites},
                                {"constraints", row}};
    }
    return out;
}

}  // namespace pwb::workflow_interpretation
