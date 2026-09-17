// mapping_kernel.extract — C++ port vs the frozen Python oracle
// (extract_oracle.json, generated from the REAL implementation by
// tools/oracle/generate_extract_fixtures.py).

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>

#include <pwb/domain/json.hpp>
#include <pwb/mapping/extract.hpp>

using pwb::domain::Json;
using pwb::domain::json_semantic_diff;
using pwb::mapping::ExtractOptions;
using pwb::mapping::FactorDataset;
using pwb::mapping::FactorPoint;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

ExtractOptions options_from_json(const Json& c) {
    ExtractOptions opt;
    opt.target_horizon = c.value("target_horizon", std::string());
    opt.crs = c.value("crs", std::string());
    if (c.contains("unit") && !c["unit"].is_null()) {
        opt.unit = c["unit"].get<std::string>();
    }
    return opt;
}

void compare_point(const FactorPoint& got, const Json& want,
                   const std::string& prefix) {
    check(got.name == want["name"].get<std::string>(), prefix + " name");
    check(std::fabs(got.value - want["value"].get<double>()) < 1e-12,
          prefix + " value");
    check(got.unit == want["unit"].get<std::string>(), prefix + " unit");
    check(got.well_id == want["well_id"].get<std::string>(),
          prefix + " well_id");
    check(got.well_name == want["well_name"].get<std::string>(),
          prefix + " well_name");
    check(std::fabs(got.x - want["x"].get<double>()) < 1e-12, prefix + " x");
    check(std::fabs(got.y - want["y"].get<double>()) < 1e-12, prefix + " y");
    check(got.crs == want["crs"].get<std::string>(), prefix + " crs");
    check(got.formation == want["formation"].get<std::string>(),
          prefix + " formation");
    check(got.qc_flag == want["qc_flag"].get<std::string>(),
          prefix + " qc_flag");
    const auto md = json_semantic_diff(got.metadata, want["metadata"]);
    if (!md.equal) {
        std::fprintf(stderr, "FAIL %s metadata %s: %s\n", prefix.c_str(),
                     md.path.c_str(), md.reason.c_str());
        ++g_failures;
    }
}

}  // namespace

int main() {
    const std::string fixture_path = PWB_EXTRACT_FIXTURE;
    std::ifstream stream(fixture_path, std::ios::binary);
    if (!stream.good()) {
        std::fprintf(stderr, "FAIL cannot open %s\n", fixture_path.c_str());
        return 1;
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    const Json oracle = Json::parse(buffer.str());

    int n_cases = 0;
    for (const auto& c : oracle["cases"]) {
        const std::string id = c["id"].get<std::string>();
        const auto opt = options_from_json(c);
        const FactorDataset got = pwb::mapping::extract_factors(
            c["records"], c["factor_name"].get<std::string>(), opt);
        const Json& want = c["expected"];
        ++n_cases;

        check(got.factor_name == want["factor_name"].get<std::string>(),
              id + " factor_name");
        check(got.unit == want["unit"].get<std::string>(), id + " unit");
        check(got.target_horizon == want["target_horizon"].get<std::string>(),
              id + " target_horizon");
        check(got.crs == want["crs"].get<std::string>(), id + " crs");
        check(got.points.size() == want["points"].size(),
              id + " point count");

        const std::size_t n =
            std::min(got.points.size(), want["points"].size());
        for (std::size_t i = 0; i < n; ++i) {
            compare_point(got.points[i], want["points"][i],
                          id + " [" + std::to_string(i) + "]");
        }

        const auto diag = json_semantic_diff(got.metadata, want["metadata"]);
        if (!diag.equal) {
            std::fprintf(stderr, "FAIL %s diagnostics %s: %s\ngot=%s\n",
                         id.c_str(), diag.path.c_str(), diag.reason.c_str(),
                         got.metadata.dump().c_str());
            ++g_failures;
        }
    }

    check(n_cases >= 18, "at least 18 oracle cases");
    if (g_failures) {
        std::fprintf(stderr, "%d failure(s), %d cases\n", g_failures, n_cases);
        return 1;
    }
    std::printf("ok %d extract cases\n", n_cases);
    return 0;
}
