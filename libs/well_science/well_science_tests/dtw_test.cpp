// well_science.dtw — DTW well-log matcher kernel vs Python oracle
// (tools/oracle/generate_dtw_fixtures.py, frozen from the real
// paleo_workbench.viz.dtw_log_matcher).
//
// Comparison discipline: normalization replicates numpy's pairwise summation
// bit-exactly, so every number is compared with exact `==` (null in the
// fixture = non-finite value, matching the kernel's inf/NaN outcomes), and
// path indices must be element-wise identical.

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <limits>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/well_science/dtw.hpp>

using pwb::domain::Json;
namespace ws = pwb::well_science;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

// Fixture convention (generator _num): non-finite values are frozen as the
// tagged strings "inf"/"-inf"/"nan"; finite values as exact doubles.
bool same_finite(double got, const Json& want) {
    if (want.is_string()) {
        const std::string tag = want.get<std::string>();
        if (tag == "inf") return got == std::numeric_limits<double>::infinity();
        if (tag == "-inf") {
            return got == -std::numeric_limits<double>::infinity();
        }
        return std::isnan(got);  // "nan"
    }
    return got == want.get<double>();
}

std::vector<double> read_doubles(const Json& node) {
    std::vector<double> out;
    out.reserve(node.size());
    for (const auto& v : node) {
        if (v.is_string()) {
            const std::string tag = v.get<std::string>();
            if (tag == "inf") {
                out.push_back(std::numeric_limits<double>::infinity());
            } else if (tag == "-inf") {
                out.push_back(-std::numeric_limits<double>::infinity());
            } else {
                out.push_back(std::numeric_limits<double>::quiet_NaN());
            }
        } else {
            out.push_back(v.get<double>());
        }
    }
    return out;
}

std::vector<std::int64_t> read_ints(const Json& node) {
    std::vector<std::int64_t> out;
    out.reserve(node.size());
    for (const auto& v : node) out.push_back(v.get<std::int64_t>());
    return out;
}

std::string ints_to_string(const std::vector<std::int64_t>& v) {
    std::string s = "[";
    for (std::size_t i = 0; i < v.size(); ++i) {
        if (i) s += ",";
        s += std::to_string(v[i]);
    }
    return s + "]";
}

void check_normalized(const Json& c) {
    const std::string id = c["id"].get<std::string>();
    const std::vector<double> input = read_doubles(c["input"]);
    const std::vector<double> got = ws::normalized(input);
    const Json& want = c["output"];
    check(got.size() == want.size(), id + " size");
    const std::size_t n = std::min(got.size(), want.size());
    for (std::size_t i = 0; i < n; ++i) {
        check(same_finite(got[i], want[i]), id + "[" + std::to_string(i) + "]");
    }
}

void check_downsample(const Json& c) {
    const std::string id = c["id"].get<std::string>();
    const std::vector<double> input = read_doubles(c["input"]);
    const auto got = ws::min_max_downsample(input, c["bin_size"].get<std::int64_t>());
    const Json& want_values = c["values"];
    const Json& want_indices = c["indices"];
    check(got.values.size() == want_values.size(), id + " values size");
    check(got.indices.size() == want_indices.size(), id + " indices size");
    // Structural contract (#1054): indices strictly increasing and the kept
    // samples are exact originals, regardless of oracle values.
    for (std::size_t i = 1; i < got.indices.size(); ++i) {
        check(got.indices[i - 1] < got.indices[i], id + " indices strict");
    }
    for (std::size_t i = 0; i < got.indices.size(); ++i) {
        if (got.indices[i] < 0 ||
            static_cast<std::size_t>(got.indices[i]) >= input.size()) {
            check(false, id + " index range");
            continue;
        }
        const double kept = input[static_cast<std::size_t>(got.indices[i])];
        const double value = got.values[i];
        const bool same = std::isnan(kept)
                              ? std::isnan(value)
                              : (std::isfinite(kept) ? kept == value
                                                     : !std::isfinite(value));
        check(same, id + " value==input[idx]");
    }
    const std::size_t n = std::min(got.values.size(), want_values.size());
    for (std::size_t i = 0; i < n; ++i) {
        check(same_finite(got.values[i], want_values[i]),
              id + " values[" + std::to_string(i) + "]");
    }
    const std::size_t m = std::min(got.indices.size(), want_indices.size());
    for (std::size_t i = 0; i < m; ++i) {
        check(got.indices[i] == want_indices[i].get<std::int64_t>(),
              id + " indices[" + std::to_string(i) + "]");
    }
}

void check_match(const Json& c) {
    const std::string id = c["id"].get<std::string>();
    const std::vector<double> ref = read_doubles(c["ref"]);
    const std::vector<double> target = read_doubles(c["target"]);
    std::optional<std::int64_t> window;
    if (!c["window"].is_null()) window = c["window"].get<std::int64_t>();
    const auto got = ws::match_curves(ref, target, window);
    check(same_finite(got.cost, c["cost"]), id + " cost");
    const Json& want_ref = c["path_ref"];
    const Json& want_target = c["path_target"];
    check(got.path_ref.size() == want_ref.size(), id + " path_ref size");
    check(got.path_target.size() == want_target.size(),
          id + " path_target size");
    check(got.path_ref.size() == got.path_target.size(),
          id + " paths equal length");
    const std::size_t n = std::min(got.path_ref.size(),
                                   static_cast<std::size_t>(want_ref.size()));
    for (std::size_t i = 0; i < n; ++i) {
        if (got.path_ref[i] != want_ref[i].get<std::int64_t>()) {
            check(false, id + " path_ref[" + std::to_string(i) + "] got " +
                             ints_to_string(got.path_ref));
            break;
        }
    }
    const std::size_t m =
        std::min(got.path_target.size(),
                 static_cast<std::size_t>(want_target.size()));
    for (std::size_t i = 0; i < m; ++i) {
        if (got.path_target[i] != want_target[i].get<std::int64_t>()) {
            check(false, id + " path_target[" + std::to_string(i) +
                             "] got " + ints_to_string(got.path_target));
            break;
        }
    }
}

void check_transfer(const Json& c) {
    const std::string id = c["id"].get<std::string>();
    const auto got = ws::transfer_top_index(
        c["ref_top_idx"].get<std::int64_t>(), read_ints(c["path_ref"]),
        read_ints(c["path_target"]));
    check(got == c["expected"].get<std::int64_t>(), id + " expected");
}

}  // namespace

int main() {
    std::ifstream stream(PWB_DTW_FIXTURE, std::ios::binary);
    if (!stream.good()) {
        std::fprintf(stderr, "FAIL cannot open fixture\n");
        return 1;
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    const Json oracle = Json::parse(buffer.str());
    check(oracle["max_cost_cells"].get<std::int64_t>() == ws::kMaxCostCells,
          "kMaxCostCells == _MAX_COST_CELLS");
    int counts[4] = {0, 0, 0, 0};
    int n = 0;
    for (const auto& c : oracle["cases"]) {
        ++n;
        const std::string kind = c["kind"].get<std::string>();
        if (kind == "normalized") {
            check_normalized(c);
            ++counts[0];
        } else if (kind == "downsample") {
            check_downsample(c);
            ++counts[1];
        } else if (kind == "match") {
            check_match(c);
            ++counts[2];
        } else if (kind == "transfer") {
            check_transfer(c);
            ++counts[3];
        } else {
            check(false, "unknown kind " + kind);
        }
    }
    check(n == 53, "53 oracle cases");
    check(counts[0] == 10 && counts[1] == 9 && counts[2] == 27 &&
              counts[3] == 7,
          "per-kind case counts");
    std::printf("%s: %d failure(s) over %d DTW cases "
                "(normalized=%d downsample=%d match=%d transfer=%d)\n",
                g_failures == 0 ? "PASS" : "FAIL", g_failures, n, counts[0],
                counts[1], counts[2], counts[3]);
    return g_failures == 0 ? 0 : 1;
}
