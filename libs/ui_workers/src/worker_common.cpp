#include "pwb/ui_workers/worker_common.hpp"

#include <charconv>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <system_error>

namespace pwb::ui_workers {

namespace {

// Python repr()/str() for floats: shortest round-trip, always carrying a
// decimal point or exponent (repr(7.0) == "7.0").
std::string py_float_repr(double v) {
    if (std::isnan(v)) return "nan";
    if (std::isinf(v)) return v < 0 ? "-inf" : "inf";
    char buf[64];
    const auto [ptr, ec] = std::to_chars(buf, buf + sizeof(buf), v);
    std::string s(buf, ptr);
    if (s.find_first_of(".eEnN") == std::string::npos) s += ".0";
    return s;
}

}  // namespace

std::string py_error_class_name(const std::exception& exc) {
    if (dynamic_cast<const PyStyleError*>(&exc) != nullptr) {
        return dynamic_cast<const PyStyleError&>(exc).py_class();
    }
    if (dynamic_cast<const std::invalid_argument*>(&exc) != nullptr) {
        return "ValueError";
    }
    if (dynamic_cast<const std::out_of_range*>(&exc) != nullptr) {
        return "IndexError";
    }
    if (dynamic_cast<const std::filesystem::filesystem_error*>(&exc) !=
            nullptr ||
        dynamic_cast<const std::system_error*>(&exc) != nullptr) {
        return "OSError";
    }
    if (dynamic_cast<const std::runtime_error*>(&exc) != nullptr) {
        return "RuntimeError";
    }
    return "Exception";
}

[[noreturn]] void rethrow_as_py_error(const std::exception& exc) {
    if (const auto* py = dynamic_cast<const PyStyleError*>(&exc)) {
        throw PyStyleError(py->py_class(), py->py_message());
    }
    if (const auto* value_error =
            dynamic_cast<const std::invalid_argument*>(&exc)) {
        throw PyValueError(value_error->what());
    }
    if (const auto* range_error =
            dynamic_cast<const std::out_of_range*>(&exc)) {
        throw PyStyleError("IndexError", range_error->what());
    }
    const std::string cls = py_error_class_name(exc);
    if (cls == "RuntimeError") {
        throw PyRuntimeError(exc.what());
    }
    throw PyStyleError(cls, exc.what());
}

double py_round(double value, int digits) {
    // Python round(x, n) performs a correctly-rounded decimal rounding of
    // the true binary value (round-half-even). The naive `v * 10^n ->
    // nearbyint -> / 10^n` breaks when the scaled product lands exactly on
    // a .5 tie that the true value sits just below (round(2.675, 2) == 2.67
    // but 2.675*100 == 267.5 exactly). printf %.*f is correctly rounded
    // under FE_TONEAREST and matches CPython digit-for-digit.
    if (!std::isfinite(value)) return value;
    char buf[128];
    if (digits >= 0) {
        std::snprintf(buf, sizeof buf, "%.*f", digits, value);
        return std::strtod(buf, nullptr);
    }
    // Negative digits: two-pass scientific formatting — first extract the
    // decimal exponent from an exact 17-significant-digit rendering, then
    // reformat with the surviving precision.
    char tmp[64];
    std::snprintf(tmp, sizeof tmp, "%.*e", 17, value);
    const char* ep = std::strchr(tmp, 'e');
    const int e10 = ep ? std::atoi(ep + 1) : 0;
    const int prec = e10 + digits;  // significant digits kept, minus one
    if (prec < 0) {
        const double av = std::fabs(value);
        const double boundary = 5.0 * std::pow(10.0, e10);
        if (av > boundary) {
            return std::copysign(std::pow(10.0, e10 + 1), value);
        }
        return std::copysign(0.0, value);
    }
    std::snprintf(buf, sizeof buf, "%.*e", prec, value);
    return std::strtod(buf, nullptr);
}

bool py_isclose(double a, double b, double rel_tol, double abs_tol) noexcept {
    // math.isclose: abs(a-b) <= max(rel_tol * max(|a|,|b|), abs_tol).
    if (a == b) return true;
    if (std::isinf(a) || std::isinf(b)) return false;
    const double diff = std::fabs(a - b);
    return diff <= std::max(rel_tol * std::max(std::fabs(a), std::fabs(b)),
                            abs_tol);
}

std::vector<double> np_linspace(double lo, double hi, std::size_t n) {
    std::vector<double> out(n);
    if (n == 0) return out;
    if (n == 1) {
        out[0] = lo;
        return out;
    }
    const double step = (hi - lo) / static_cast<double>(n - 1);
    for (std::size_t i = 0; i < n; ++i) out[i] = lo + step * i;
    out.back() = hi;  // np.linspace pins the endpoint exactly
    return out;
}

int env_int(const char* name, int fallback) {
    const char* raw = std::getenv(name);
    if (raw == nullptr) return fallback;
    std::string text = raw;
    const auto first = text.find_first_not_of(" \t\r\n");
    const auto last = text.find_last_not_of(" \t\r\n");
    if (first == std::string::npos) return fallback;
    text = text.substr(first, last - first + 1);
    try {
        // Python int() accepts surrounding whitespace and a sign.
        std::size_t pos = 0;
        const long long value = std::stoll(text, &pos);
        while (pos < text.size() && (text[pos] == ' ' || text[pos] == '\t')) {
            ++pos;
        }
        if (pos != text.size()) return fallback;
        return static_cast<int>(value);
    } catch (const std::exception&) {
        return fallback;
    }
}

// ---------------------------------------------------------------------------
// FactorTaskSlice::parameters helpers.
// ---------------------------------------------------------------------------

bool param_has(const FactorTaskSlice& task, const std::string& key) {
    return task.parameters.find(key) != task.parameters.end();
}

std::optional<std::string> param_str(const FactorTaskSlice& task,
                                     const std::string& key) {
    const auto it = task.parameters.find(key);
    if (it == task.parameters.end()) return std::nullopt;
    if (const auto* s = std::any_cast<std::string>(&it->second)) {
        if (s->empty()) return std::nullopt;  // `or` fallback parity
        return *s;
    }
    if (const auto* c = std::any_cast<const char*>(&it->second)) {
        if (*c == nullptr || **c == '\0') return std::nullopt;
        return std::string(*c);
    }
    // `str(params.get(k) or fallback)` parity: falsy scalars take the
    // fallback (nullopt); truthy scalars are str()'d like Python.
    if (const auto* b = std::any_cast<bool>(&it->second)) {
        if (!*b) return std::nullopt;
        return std::string("True");  // str(True)
    }
    if (const auto* i = std::any_cast<int>(&it->second)) {
        if (*i == 0) return std::nullopt;
        return std::to_string(*i);
    }
    if (const auto* i64 = std::any_cast<std::int64_t>(&it->second)) {
        if (*i64 == 0) return std::nullopt;
        return std::to_string(*i64);
    }
    if (const auto* d = std::any_cast<double>(&it->second)) {
        if (*d == 0.0) return std::nullopt;
        return py_float_repr(*d);
    }
    if (const auto* f = std::any_cast<float>(&it->second)) {
        if (*f == 0.0f) return std::nullopt;
        return py_float_repr(static_cast<double>(*f));
    }
    return std::nullopt;
}

std::optional<double> param_double(const FactorTaskSlice& task,
                                   const std::string& key) {
    const auto it = task.parameters.find(key);
    if (it == task.parameters.end()) return std::nullopt;
    if (const auto* d = std::any_cast<double>(&it->second)) return *d;
    if (const auto* f = std::any_cast<float>(&it->second)) return *f;
    if (const auto* i = std::any_cast<int>(&it->second)) return *i;
    if (const auto* i64 = std::any_cast<std::int64_t>(&it->second))
        return static_cast<double>(*i64);
    return std::nullopt;
}

std::optional<int> param_int(const FactorTaskSlice& task,
                             const std::string& key) {
    const auto it = task.parameters.find(key);
    if (it == task.parameters.end()) return std::nullopt;
    if (const auto* i = std::any_cast<int>(&it->second)) return *i;
    if (const auto* i64 = std::any_cast<std::int64_t>(&it->second))
        return static_cast<int>(*i64);
    if (const auto* d = std::any_cast<double>(&it->second))
        return static_cast<int>(*d);
    return std::nullopt;
}

bool param_truthy(const FactorTaskSlice& task, const std::string& key) {
    const auto it = task.parameters.find(key);
    if (it == task.parameters.end()) return false;
    if (!it->second.has_value()) return false;
    if (const auto* v = std::any_cast<std::vector<std::any>>(&it->second)) {
        return !v->empty();
    }
    if (const auto* v =
            std::any_cast<std::vector<std::map<std::string, std::any>>>(
                &it->second)) {
        return !v->empty();
    }
    if (const auto* s = std::any_cast<std::string>(&it->second)) {
        return !s->empty();
    }
    if (const auto* b = std::any_cast<bool>(&it->second)) {
        return *b;
    }
    if (const auto* m =
            std::any_cast<std::map<std::string, std::any>>(&it->second)) {
        return !m->empty();
    }
    if (const auto* i = std::any_cast<int>(&it->second)) return *i != 0;
    if (const auto* i64 = std::any_cast<std::int64_t>(&it->second))
        return *i64 != 0;
    if (const auto* d = std::any_cast<double>(&it->second))
        return *d != 0.0;
    if (const auto* f = std::any_cast<float>(&it->second))
        return *f != 0.0f;
    return true;  // any other present value is truthy (Python parity)
}

// ---------------------------------------------------------------------------
// Path helpers.
// ---------------------------------------------------------------------------

bool is_within_directory(const std::string& path,
                         const std::string& directory) {
    // pathlib resolve().relative_to() parity: a non-relative answer or an OS
    // error is False; ".." as the first relative component is an escape.
    try {
        const std::filesystem::path resolved_path =
            std::filesystem::weakly_canonical(path);
        const std::filesystem::path resolved_dir =
            std::filesystem::weakly_canonical(directory);
        const auto rel = resolved_path.lexically_relative(resolved_dir);
        if (rel.empty() || rel.is_absolute()) return false;
        return *rel.begin() != "..";
    } catch (const std::exception&) {
        return false;
    }
}

namespace {

// pathlib expanduser(): "~/x" -> "$HOME/x"; bare "~" -> $HOME. "~user"
// forms are left untouched (Python would need pwd; not used by callers).
std::string expand_user_path(const std::string& path) {
    if (path.empty() || path[0] != '~') return path;
    if (path.size() > 1 && path[1] != '/' && path[1] != '\\') return path;
    const char* home = std::getenv("HOME");
    if (home == nullptr || *home == '\0') return path;
    return std::string(home) + path.substr(1);
}

std::string trimmed(const std::string& text) {
    const auto first = text.find_first_not_of(" \t\r\n");
    const auto last = text.find_last_not_of(" \t\r\n");
    if (first == std::string::npos) return "";
    return text.substr(first, last - first + 1);
}

// Shared project-root join (confined, resolved). Returns "" when the join
// does not apply (empty/invalid root or an escape attempt).
std::string joined_within_root(const std::string& candidate,
                               const std::string& project_root) {
    namespace fs = std::filesystem;
    const std::string root = trimmed(project_root);
    if (root.empty() || root == "." || root == "..") return "";
    std::error_code ec;
    const fs::path root_path = fs::weakly_canonical(root, ec);
    const fs::path joined = fs::weakly_canonical(root_path / candidate, ec);
    if (ec || !is_within_directory(joined.string(), root_path.string())) {
        return "";
    }
    return joined.string();
}

}  // namespace

std::string resource_path(const std::string& path,
                          const std::string& project_root) {
    // stratigraphy_correlation._resource_path: expanduser -> file-or-
    // absolute hit returns the BARE candidate; else confined root join.
    namespace fs = std::filesystem;
    std::error_code ec;
    const fs::path candidate = fs::path(expand_user_path(path));
    if (fs::is_regular_file(candidate, ec) || candidate.is_absolute()) {
        return candidate.string();
    }
    const std::string joined = joined_within_root(candidate.string(), project_root);
    if (!joined.empty()) return joined;
    return candidate.string();
}

std::string absolute_resource_path(const std::string& path,
                                   const std::string& project_root) {
    // VizAdapter._absolute_path: file hit -> resolve(); absolute -> bare;
    // else confined root join.
    namespace fs = std::filesystem;
    std::error_code ec;
    const fs::path candidate = fs::path(expand_user_path(path));
    if (fs::is_regular_file(candidate, ec)) {
        return fs::weakly_canonical(candidate, ec).string();
    }
    if (candidate.is_absolute()) {
        return candidate.string();
    }
    const std::string joined = joined_within_root(candidate.string(), project_root);
    if (!joined.empty()) return joined;
    return candidate.string();
}

}  // namespace pwb::ui_workers
