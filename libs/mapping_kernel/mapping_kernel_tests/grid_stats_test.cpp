// mapping_kernel.grid_stats — GridStatistics.from_grid vs Python oracle.

#include <cmath>
#include <cstdio>
#include <fstream>
#include <limits>
#include <sstream>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/mapping/interpolator.hpp>

using pwb::domain::Json;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

bool same_num(double got, const Json& want) {
    if (want.is_null()) return !std::isfinite(got);
    if (!std::isfinite(got)) return false;
    return std::fabs(got - want.get<double>()) < 1e-12;
}

}  // namespace

int main() {
    std::ifstream stream(PWB_GRID_STATS_FIXTURE, std::ios::binary);
    if (!stream.good()) {
        std::fprintf(stderr, "FAIL cannot open fixture\n");
        return 1;
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    const Json oracle = Json::parse(buffer.str());
    int n = 0;
    for (const auto& c : oracle["cases"]) {
        ++n;
        const std::string id = c["id"].get<std::string>();
        std::vector<float> cells;
        for (const auto& v : c["cells"]) {
            cells.push_back(v.is_null()
                                ? std::numeric_limits<float>::quiet_NaN()
                                : static_cast<float>(v.get<double>()));
        }
        const auto got = pwb::mapping::grid_statistics(cells);
        const auto& want = c["stats"];
        check(got.valid_count == want["valid_count"].get<int>(),
              id + " valid_count");
        check(got.total_count == want["total_count"].get<int>(),
              id + " total_count");
        check(same_num(got.min, want["min"]), id + " min");
        check(same_num(got.max, want["max"]), id + " max");
        check(same_num(got.mean, want["mean"]), id + " mean");
        check(same_num(got.std, want["std"]), id + " std");
    }
    check(n == 8, "8 grid-stats cases");
    std::printf("%s: %d failure(s) over %d grid-stats cases\n",
                g_failures == 0 ? "PASS" : "FAIL", g_failures, n);
    return g_failures == 0 ? 0 : 1;
}
