// mapping_kernel.grid_envelope — FactorGridResult JSON envelope codec vs the
// frozen Python oracle (tools/oracle/generate_grid_envelope_fixtures.py).
// Every case is produced by the live Python module; nothing is hand-written.

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/mapping/factor_grid_io.hpp>

using pwb::domain::Json;
using pwb::mapping::FactorGridEnvelope;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

std::optional<std::string> opt_arg(const Json& case_json, const char* key) {
    const auto it = case_json.find(key);
    if (it == case_json.end() || !it->is_string()) return std::nullopt;
    return it->get<std::string>();
}

// Semantic comparator tuned for this oracle: object key SETS must match
// exactly, arrays compare element-wise, int-vs-float is a type difference,
// floats compare within 1e-9 relative (numpy pairwise summation vs the
// kernel's sequential accumulation in mean/std — the grid_stats oracle uses
// the same tolerance). null/bool/string compare exactly.
std::string diff_json(const Json& got, const Json& want,
                      const std::string& path) {
    // Integer kind covers signed and unsigned; int-vs-float remains a type
    // difference, matching pwb::domain::json_semantic_diff.
    const bool got_int = got.is_number_integer();
    const bool want_int = want.is_number_integer();
    if (got_int != want_int || (!got.is_number() && got.type() != want.type())) {
        return path + ": type differs (" + got.dump() + " vs " + want.dump() +
               ")";
    }
    if (got.is_object()) {
        for (auto it = got.begin(); it != got.end(); ++it) {
            if (!want.contains(it.key())) {
                return path + "." + it.key() + ": key missing on want";
            }
            std::string child = diff_json(it.value(), want.at(it.key()),
                                          path + "." + it.key());
            if (!child.empty()) return child;
        }
        for (auto it = want.begin(); it != want.end(); ++it) {
            if (!got.contains(it.key())) {
                return path + "." + it.key() + ": key missing on got";
            }
        }
        return "";
    }
    if (got.is_array()) {
        if (got.size() != want.size()) {
            return path + ": array length " + std::to_string(got.size()) +
                   " vs " + std::to_string(want.size());
        }
        for (std::size_t i = 0; i < got.size(); ++i) {
            std::string child = diff_json(
                got[i], want[i],
                path + "[" + std::to_string(i) + "]");
            if (!child.empty()) return child;
        }
        return "";
    }
    if (got.is_number_float() && want.is_number_float()) {
        const double a = got.get<double>();
        const double b = want.get<double>();
        if (std::isnan(a) && std::isnan(b)) return "";
        const double tol = 1e-9 * std::max({1.0, std::fabs(a), std::fabs(b)});
        if (std::fabs(a - b) <= tol) return "";
        return path + ": float " + got.dump() + " vs " + want.dump();
    }
    if (got != want) {
        return path + ": value " + got.dump() + " vs " + want.dump();
    }
    return "";
}

// to_descriptor / to_legacy_dict must be strict JSON: no non-finite float
// anywhere (Python dumps them with allow_nan=False).
std::string find_non_finite(const Json& value, const std::string& path) {
    if (value.is_number_float() &&
        !std::isfinite(value.get<double>())) {
        return path + ": non-finite float survived serialization";
    }
    if (value.is_array()) {
        for (std::size_t i = 0; i < value.size(); ++i) {
            std::string child =
                find_non_finite(value[i],
                                path + "[" + std::to_string(i) + "]");
            if (!child.empty()) return child;
        }
    }
    if (value.is_object()) {
        for (auto it = value.begin(); it != value.end(); ++it) {
            std::string child = find_non_finite(it.value(), path + "." + it.key());
            if (!child.empty()) return child;
        }
    }
    return "";
}

void check_cells(const std::vector<float>& got, const Json& want,
                 int height, int width, const std::string& what) {
    const std::size_t n =
        static_cast<std::size_t>(height) * static_cast<std::size_t>(width);
    if (want.size() != n || got.size() != n) {
        check(false, what + ": cell count " + std::to_string(got.size()) +
                         " vs " + std::to_string(want.size()) +
                         " (expected " + std::to_string(n) + ")");
        return;
    }
    for (std::size_t i = 0; i < n; ++i) {
        const Json& cell = want[i];
        if (cell.is_null()) {
            if (!std::isnan(got[i])) {
                check(false, what + "[" + std::to_string(i) +
                                 "]: want nodata, got " +
                                 std::to_string(got[i]));
            }
        } else if (std::isnan(got[i])) {
            check(false, what + "[" + std::to_string(i) + "]: got nodata");
        } else if (static_cast<double>(got[i]) != cell.get<double>()) {
            // float32 widen must be bit-identical on both sides.
            check(false, what + "[" + std::to_string(i) + "]: " +
                             std::to_string(got[i]) + " vs " + cell.dump());
        }
    }
}

void check_numeric_json(const Json& got, const Json& want,
                        const std::string& what) {
    const std::string diff = diff_json(got, want, "$");
    check(diff.empty(), what + (diff.empty() ? "" : " -> " + diff));
}

void check_strict(const Json& value, const std::string& what) {
    const std::string bad = find_non_finite(value, "$");
    check(bad.empty(), what + (bad.empty() ? "" : " -> " + bad));
}

// Declared-key-order walk (objects iterate in insertion order, arrays
// positionally) — pins the Python dict literal layout beyond key sets.
void collect_layout(const Json& value, std::vector<std::string>& out,
                    const std::string& path) {
    if (value.is_object()) {
        for (auto it = value.begin(); it != value.end(); ++it) {
            out.push_back("{" + path + "." + it.key());
            collect_layout(it.value(), out, path + "." + it.key());
        }
    } else if (value.is_array()) {
        for (std::size_t i = 0; i < value.size(); ++i) {
            out.push_back("[" + path);
            collect_layout(value[i], out, path);
        }
    }
}

// Spot-check promised by 18-decisions D10: for two representative cases the
// C++ output must match Python byte-layout (declared key order) AND compare
// exactly under the domain semantic comparator (bit-exact doubles). The
// output is dump()/parse() normalized first so constructed integers compare
// under the same number kind the domain comparator expects (parsed vs
// parsed, its intended use).
void check_layout_exact(const Json& got, const Json& want,
                        const std::string& what) {
    std::vector<std::string> got_layout;
    std::vector<std::string> want_layout;
    collect_layout(got, got_layout, "$");
    collect_layout(want, want_layout, "$");
    check(got_layout == want_layout,
          what + " layout (declared key order)");
    check(pwb::domain::json_semantically_equal(Json::parse(got.dump()), want),
          what + " exact semantic equality");
}

}  // namespace

int main() {
    std::ifstream stream(PWB_GRID_ENVELOPE_FIXTURE, std::ios::binary);
    if (!stream.good()) {
        std::fprintf(stderr, "FAIL cannot open fixture\n");
        return 1;
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    const Json oracle = Json::parse(buffer.str());
    int n = 0;
    int n_ok = 0;
    int n_error = 0;

    for (const auto& c : oracle["cases"]) {
        ++n;
        const std::string id = c["id"].get<std::string>();
        const Json parameters = pwb::mapping::parse_json_python_tolerant(
            c["parameters"].get<std::string>());
        const Json metadata = c["metadata"].is_null()
                                  ? Json()
                                  : pwb::mapping::parse_json_python_tolerant(
                                        c["metadata"].get<std::string>());

        FactorGridEnvelope env;
        bool raised = false;
        std::string message;
        std::string exception_class;
        try {
            env = pwb::mapping::from_legacy_task_parameters(
                parameters, c["factor_name"].get<std::string>(),
                opt_arg(c, "crs"), opt_arg(c, "unit"), metadata);
        } catch (const std::out_of_range& err) {
            raised = true;
            message = err.what();
            exception_class = "KeyError";
        } catch (const std::invalid_argument& err) {
            raised = true;
            message = err.what();
            exception_class = "ValueError";
        } catch (const std::runtime_error& err) {
            raised = true;
            message = err.what();
            exception_class = "TypeError";
        } catch (const std::exception& err) {
            raised = true;
            message = err.what();
            exception_class = "other";
        }

        if (c["error"].is_string()) {
            ++n_error;
            check(raised, id + ": expected a raise, got success");
            if (raised) {
                check(message == c["error"].get<std::string>(),
                      id + ": message '" + message + "' vs '" +
                          c["error"].get<std::string>() + "'");
                check(exception_class == c["error_type"].get<std::string>(),
                      id + ": exception class " + exception_class + " vs Python " +
                          c["error_type"].get<std::string>());
            }
            continue;
        }

        ++n_ok;
        check(!raised, id + ": unexpected raise: " + message);
        if (raised) continue;
        const Json& want = c["result"];

        check(env.height == want["height"].get<int>() &&
                  env.width == want["width"].get<int>(),
              id + ": shape");
        check_cells(env.grid_z, want["grid_cells"], env.height, env.width,
                    id + " grid_cells");
        check_numeric_json(pwb::mapping::encode_legacy_axis_list(env.grid_x),
                           want["encode_axis_x"], id + " encode_axis_x");
        check_numeric_json(pwb::mapping::encode_legacy_axis_list(env.grid_y),
                           want["encode_axis_y"], id + " encode_axis_y");
        if (want["variance_cells"].is_null()) {
            check(env.variance_grid.empty(), id + ": unexpected variance grid");
        } else {
            check(!env.variance_grid.empty(), id + ": variance grid missing");
            if (!env.variance_grid.empty()) {
                check_cells(env.variance_grid, want["variance_cells"],
                            env.height, env.width, id + " variance_cells");
            }
        }
        check_numeric_json(pwb::mapping::grid_statistics_to_json(env.statistics),
                           want["stats_to_dict"], id + " stats_to_dict");

        const Json descriptor = pwb::mapping::to_descriptor(env);
        check_strict(descriptor, id + " descriptor strict");
        check_numeric_json(descriptor, want["descriptor"], id + " descriptor");
        check(descriptor.contains("grid_z") == false &&
                  descriptor.contains("grid_x") == false &&
                  descriptor.contains("grid_y") == false,
              id + ": descriptor must not embed grid arrays");

        const Json legacy = pwb::mapping::to_legacy_dict(env);
        check_strict(legacy, id + " legacy strict");
        check_numeric_json(legacy, want["legacy"], id + " legacy");
        check_numeric_json(
            pwb::mapping::encode_legacy_grid_lists(env.grid_z, env.height,
                                                   env.width),
            want["encode_grid_lists"], id + " encode_grid_lists");
        if (id == "idw_none_cells" || id == "descriptor_metadata_full") {
            // D10 spot-check on byte-layout fidelity.
            check_layout_exact(descriptor, want["descriptor"],
                               id + " descriptor");
            check_layout_exact(legacy, want["legacy"], id + " legacy");
        }

        // Round-trip: read the PYTHON-frozen legacy dict back and require the
        // same grid/statistics/algorithm identity Python's engine path
        // produced (the user-flow acceptance, C++ side of "反向亦然").
        const Json legacy_back = pwb::mapping::parse_json_python_tolerant(
            want["legacy_strict_json"].get<std::string>());
        FactorGridEnvelope env2;
        bool roundtrip_ok = true;
        try {
            env2 = pwb::mapping::from_legacy_task_parameters(
                legacy_back, c["factor_name"].get<std::string>());
        } catch (const std::exception& err) {
            roundtrip_ok = false;
            check(false, id + ": roundtrip raise: " + err.what());
        }
        if (roundtrip_ok) {
            check_cells(env2.grid_z, want["roundtrip"]["grid_cells"],
                        env2.height, env2.width, id + " roundtrip cells");
            check_numeric_json(
                pwb::mapping::grid_statistics_to_json(env2.statistics),
                want["roundtrip"]["stats_to_dict"], id + " roundtrip stats");
            check(env2.algorithm_id ==
                      want["roundtrip"]["algorithm_id"].get<std::string>(),
                  id + " roundtrip algorithm_id");
        }

        // C++'s own legacy output feeds the same read path (write/read
        // symmetry within C++, mirroring the Python lossless round-trip).
        FactorGridEnvelope env3;
        try {
            env3 = pwb::mapping::from_legacy_task_parameters(
                legacy, c["factor_name"].get<std::string>());
            check_cells(env3.grid_z, want["roundtrip"]["grid_cells"],
                        env3.height, env3.width, id + " self-roundtrip cells");
            check_numeric_json(
                pwb::mapping::grid_statistics_to_json(env3.statistics),
                want["roundtrip"]["stats_to_dict"], id + " self-roundtrip stats");
        } catch (const std::exception& err) {
            check(false, id + ": self-roundtrip raise: " + err.what());
        }
    }

    check(n == oracle["n_cases"].get<int>(), "case count vs fixture header");
    check(n_ok == oracle["n_ok"].get<int>(), "ok count vs fixture header");
    check(n_error == oracle["n_error"].get<int>(),
          "error count vs fixture header");
    std::printf("%s: %d failure(s) over %d envelope cases (%d ok, %d error)\n",
                g_failures == 0 ? "PASS" : "FAIL", g_failures, n, n_ok, n_error);
    return g_failures == 0 ? 0 : 1;
}
