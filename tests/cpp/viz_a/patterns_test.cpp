// viz_a.patterns — drawing-differential kernels: the Chinese lithology/
// facies vocabulary (tables + fuzzy lookup + WLE pattern definitions) and
// the robust display-range port, frozen against
// tests/cpp/viz_a/fixtures/scale_patterns_oracle.json (real Python:
// pattern_map.py/pattern_engine.py/robust_scale.py @ geoviz 08851951).
// Robust-scale comparison is exact (same IEEE ops; declared tolerance
// 1e-9 absorbs no differences today — failures print the delta).

#include <cstdio>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/viz/well_log_patterns.hpp>
#include <pwb/viz/well_log_robust_scale.hpp>

using pwb::domain::Json;
using namespace pwb::viz;

namespace {

int g_cases = 0;
int g_failures = 0;

void fail(const std::string& what) {
    std::fprintf(stderr, "FAIL %s\n", what.c_str());
    ++g_failures;
}

}  // namespace

int main() {
    const std::filesystem::path oracle_path =
        std::filesystem::path(PWB_VIZ_A_FIXTURE_ROOT) /
        "scale_patterns_oracle.json";
    std::ifstream in(oracle_path);
    if (!in) {
        std::fprintf(stderr, "cannot open %s\n", oracle_path.c_str());
        return 2;
    }
    Json oracle = Json::parse(in);

    // Frozen tables (order included — ties depend on it).
    ++g_cases;
    const auto& entries = pattern_map_entries();
    if (entries.size() != oracle["pattern_map"].size()) {
        fail("PATTERN_MAP size mismatch");
    } else {
        for (std::size_t i = 0; i < entries.size(); ++i) {
            if (entries[i].first != oracle["pattern_map"][i][0].get<std::string>() ||
                entries[i].second != oracle["pattern_map"][i][1].get<std::string>()) {
                fail("PATTERN_MAP entry mismatch at " + std::to_string(i));
                break;
            }
        }
    }
    ++g_cases;
    const auto& colors = facies_color_entries();
    if (colors.size() != oracle["facies_colors"].size()) {
        fail("FACIES_COLORS size mismatch");
    } else {
        for (std::size_t i = 0; i < colors.size(); ++i) {
            if (colors[i].first != oracle["facies_colors"][i][0].get<std::string>() ||
                colors[i].second != oracle["facies_colors"][i][1].get<std::string>()) {
                fail("FACIES_COLORS entry mismatch at " + std::to_string(i));
                break;
            }
        }
    }

    // Fuzzy lookups.
    for (const auto& probe : oracle["pattern_lookups"]) {
        ++g_cases;
        const std::string name = probe["name"].get<std::string>();
        const std::string expected = probe["pattern_id"].get<std::string>();
        const std::string actual = pattern_id_for(name);
        if (actual != expected) {
            fail("pattern_id_for('" + name + "') = '" + actual + "' expected '" +
                 expected + "'");
        }
    }
    for (const auto& probe : oracle["color_lookups"]) {
        ++g_cases;
        const std::string name = probe["name"].get<std::string>();
        const std::string expected = probe["color"].get<std::string>();
        const std::string actual = facies_color_for(name);
        if (actual != expected) {
            fail("facies_color_for('" + name + "') = '" + actual + "' expected '" +
                 expected + "'");
        }
    }

    // WLE pattern definitions: geometry spec + deterministic primitives for
    // every id the vocabulary can produce.
    for (const auto& [name, id] : entries) {
        ++g_cases;
        auto definition = make_pattern_definition(id);
        if (!definition.has_value()) {
            fail("no pattern definition for id '" + id + "' (name '" + name + "')");
            continue;
        }
        if (definition->tile_width.value != 4.0 ||
            definition->tile_height.value != 4.0) {
            fail("tile geometry spec violated for '" + id + "'");
        }
        if (definition->primitives.empty()) {
            fail("pattern '" + id + "' has no primitives");
        }
        // Determinism: a second build is identical.
        auto again = make_pattern_definition(id);
        if (!again.has_value() ||
            again->primitives.size() != definition->primitives.size() ||
            again->version != definition->version) {
            fail("pattern '" + id + "' not deterministic");
        }
    }
    if (!make_pattern_definition("no-such-pattern").has_value()) {
        ++g_cases;  // unknown id honestly rejected
    } else {
        fail("unknown pattern id produced a definition");
    }

    // Robust display range.
    for (const auto& case_json : oracle["robust_scale_cases"]) {
        ++g_cases;
        const std::string name = case_json["curve_name"].get<std::string>();
        std::vector<double> values;
        for (const auto& v : case_json["values"]) values.push_back(v.get<double>());
        const bool has_null = !case_json["null_value"].is_null();
        const double null_value =
            has_null ? case_json["null_value"].get<double>() : 0.0;
        const auto range = compute_robust_display_range(
            values, name, has_null ? std::optional<double>(null_value)
                                   : std::nullopt);
        const double evmin = case_json["expected"][0].get<double>();
        const double evmax = case_json["expected"][1].get<double>();
        if (std::fabs(range.vmin - evmin) > 1e-9 ||
            std::fabs(range.vmax - evmax) > 1e-9) {
            char buf[256];
            std::snprintf(buf, sizeof(buf), "case %s: got (%.17g, %.17g) "
                         "expected (%.17g, %.17g)",
                         case_json["id"].get<std::string>().c_str(),
                         range.vmin, range.vmax, evmin, evmax);
            fail(buf);
        }
    }

    if (g_failures == 0) {
        std::printf("viz_a.patterns: OK (%d checks)\n", g_cases);
        return 0;
    }
    std::printf("viz_a.patterns: %d failure(s) over %d checks\n", g_failures,
                g_cases);
    return 1;
}
